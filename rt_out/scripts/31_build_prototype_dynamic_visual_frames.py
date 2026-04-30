#!/usr/bin/env python3

"""Resolve renderable robot visuals for each sampled dynamic frame.

The pose-frame JSON from the previous stage only tells us where robot links are.
This script matches those links to the configured visual assets and records the
per-visual transforms needed by the mesh-export stage.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from dynamic_prototype_config import load_dynamic_prototype_config


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODELS_ROOT = PROJECT_ROOT / "models"
FRAMES_PATH = PROJECT_ROOT / "rt_out" / "dynamic_frames" / "prototype_frames.json"
DYNAMIC_MANIFEST_PATH = PROJECT_ROOT / "rt_out" / "manifests" / "dynamic_manifest.json"
OUTPUT_PATH = PROJECT_ROOT / "rt_out" / "dynamic_frames" / "dynamic_visual_frames.json"

PROTOTYPE_CONFIG = load_dynamic_prototype_config()
MODEL_ORDER = PROTOTYPE_CONFIG["model_names"]
EXPECTED_SAMPLE_INDICES = PROTOTYPE_CONFIG["source_sample_indices"]
EXPECTED_FRAME_IDS = PROTOTYPE_CONFIG["frame_ids"]
EXPECTED_COUNTS = {
    model_name: {
        "logged_links": model_config["expected_link_count"],
        "renderable_links": model_config["expected_renderable_link_count"],
        "renderable_visuals": model_config["expected_renderable_visual_count"],
        "non_renderable_links": model_config["non_renderable_links"],
    }
    for model_name, model_config in PROTOTYPE_CONFIG["dynamic_models"].items()
}
EXPECTED_TOTAL_RENDERABLE_VISUALS = PROTOTYPE_CONFIG["expected_renderable_visual_count_total"]


class DynamicVisualFrameError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build per-frame renderable visual metadata for validated dynamic frames."
    )
    parser.add_argument(
        "--frames-json",
        type=Path,
        default=None,
        help="Optional frame selection JSON with frame_id/source_sample records.",
    )
    parser.add_argument(
        "--dynamic-frames",
        type=Path,
        default=FRAMES_PATH,
        help="Input dynamic frame records JSON. Defaults to the validated prototype output.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
        help="Output visual-frame metadata JSON path.",
    )
    return parser.parse_args()


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise DynamicVisualFrameError(f"Missing input file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise DynamicVisualFrameError(f"Invalid JSON in {path}: {exc}") from exc


def require_non_negative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DynamicVisualFrameError(f"{label} must be a non-negative integer")
    return value


def load_expected_frames(path: Path | None) -> list[dict[str, int]]:
    # Default to the validated 3-frame prototype selection, but also allow a
    # larger experiment frame list with the same frame_id/source_sample schema.
    if path is None:
        return [
            {
                "frame_id": int(frame["frame_id"]),
                "source_sample_index": int(frame["source_sample_index"]),
            }
            for frame in PROTOTYPE_CONFIG["prototype_frames"]
        ]

    raw = load_json(path.expanduser().resolve())
    if isinstance(raw, dict):
        raw_frames = raw.get("frames")
    else:
        raw_frames = raw

    if not isinstance(raw_frames, list) or not raw_frames:
        raise DynamicVisualFrameError("Custom frames JSON must be a non-empty list or an object with frames list")

    frames: list[dict[str, int]] = []
    seen_frame_ids: set[int] = set()
    seen_source_samples: set[int] = set()
    previous_source_sample: int | None = None
    for index, item in enumerate(raw_frames):
        if not isinstance(item, dict):
            raise DynamicVisualFrameError(f"frames[{index}] must be an object")
        frame_id = require_non_negative_int(item.get("frame_id"), f"frames[{index}].frame_id")
        source_value = item.get("source_sample_index", item.get("source_sample"))
        source_sample_index = require_non_negative_int(
            source_value,
            f"frames[{index}].source_sample",
        )
        if frame_id in seen_frame_ids:
            raise DynamicVisualFrameError(f"Duplicate frame_id in custom frames JSON: {frame_id}")
        if source_sample_index in seen_source_samples:
            raise DynamicVisualFrameError(
                f"Duplicate source_sample in custom frames JSON: {source_sample_index}"
            )
        if previous_source_sample is not None and source_sample_index <= previous_source_sample:
            raise DynamicVisualFrameError("Custom source_sample values must be strictly increasing")
        seen_frame_ids.add(frame_id)
        seen_source_samples.add(source_sample_index)
        previous_source_sample = source_sample_index
        frames.append(
            {
                "frame_id": frame_id,
                "source_sample_index": source_sample_index,
            }
        )
    return frames


def parse_float_sequence(value: Any, expected_length: int, label: str) -> list[float]:
    if isinstance(value, str):
        parts = value.split()
    elif isinstance(value, list):
        parts = value
    else:
        raise DynamicVisualFrameError(f"{label} must be a string or list")

    if len(parts) != expected_length:
        raise DynamicVisualFrameError(
            f"{label} must contain {expected_length} numeric values, got {len(parts)}"
        )

    try:
        return [float(item) for item in parts]
    except (TypeError, ValueError) as exc:
        raise DynamicVisualFrameError(f"{label} contains a non-numeric value") from exc


def parse_pose6(value: Any, label: str) -> list[float]:
    return parse_float_sequence(value, 6, label)


def parse_scale3(value: Any, label: str) -> list[float]:
    return parse_float_sequence(value if value is not None else [1.0, 1.0, 1.0], 3, label)


def pose6_to_matrix(pose: list[float]) -> list[list[float]]:
    # Visual poses from the manifest live inside the link frame, so convert them
    # once here for later transform chaining.
    x, y, z, roll, pitch, yaw = pose

    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)

    return [
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr, x],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr, y],
        [-sp, cp * sr, cp * cr, z],
        [0.0, 0.0, 0.0, 1.0],
    ]


def slug_id(model_name: str, link_name: str, visual_name: str) -> str:
    return f"{model_name}__{link_name}__{visual_name}"


def build_model_index() -> dict[str, Path]:
    # Resolve model:// URIs for dynamic robot visuals by finding a unique model
    # directory for each name under models/.
    candidates: dict[str, set[Path]] = {}
    for marker_name in ("model.config", "model.sdf"):
        for marker in MODELS_ROOT.rglob(marker_name):
            model_dir = marker.parent.resolve()
            candidates.setdefault(model_dir.name, set()).add(model_dir)

    index: dict[str, Path] = {}
    for model_name, paths in candidates.items():
        sorted_paths = sorted(paths, key=lambda path: str(path))
        if len(sorted_paths) == 1:
            index[model_name] = sorted_paths[0]

    return index


def resolve_geometry_uri(uri: str, model_index: dict[str, Path]) -> Path:
    # Normalize the source mesh URI now so the later Blender export stage can
    # import each robot visual directly from a resolved filesystem path.
    if not isinstance(uri, str) or not uri.strip():
        raise DynamicVisualFrameError("Mesh geometry URI must be a non-empty string")

    cleaned_uri = uri.strip()
    if cleaned_uri.startswith("model://"):
        relative_uri = cleaned_uri[len("model://"):]
        parts = Path(relative_uri).parts
        if len(parts) < 2:
            raise DynamicVisualFrameError(f"Malformed model URI: {cleaned_uri}")

        model_name = parts[0]
        model_dir = model_index.get(model_name)
        if model_dir is None:
            raise DynamicVisualFrameError(
                f"Could not resolve model {model_name!r} for URI {cleaned_uri}"
            )
        return (model_dir / Path(*parts[1:])).resolve()

    if cleaned_uri.startswith("file://"):
        return Path(cleaned_uri[len("file://"):]).expanduser().resolve()

    if "://" in cleaned_uri:
        raise DynamicVisualFrameError(f"Unsupported geometry URI scheme: {cleaned_uri}")

    path = Path(cleaned_uri).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def validate_matrix44(value: Any, label: str) -> list[list[float]]:
    # Later stages treat link_to_world and visual_pose_matrix as trusted 4x4
    # transforms, so validate the matrix shape before passing it downstream.
    if not isinstance(value, list) or len(value) != 4:
        raise DynamicVisualFrameError(f"{label} must be a 4x4 matrix")

    matrix: list[list[float]] = []
    for row_index, row in enumerate(value):
        if not isinstance(row, list) or len(row) != 4:
            raise DynamicVisualFrameError(f"{label}[{row_index}] must contain 4 values")
        try:
            matrix.append([float(item) for item in row])
        except (TypeError, ValueError) as exc:
            raise DynamicVisualFrameError(f"{label}[{row_index}] contains non-numeric data") from exc
    return matrix


def load_trusted_frames(path: Path, expected_frames: list[dict[str, int]]) -> dict[str, Any]:
    # The output of script 30 is treated as a trusted intermediate artifact. Re-
    # validate the frame order here before attaching per-visual metadata.
    data = load_json(path)
    if not isinstance(data, dict):
        raise DynamicVisualFrameError("prototype_frames.json root must be an object")

    frames = data.get("frames")
    if not isinstance(frames, list):
        raise DynamicVisualFrameError("prototype_frames.json must contain frames list")
    # Preserve the exact frame count and sample ordering because later steps
    # assume a one-to-one correspondence between selected samples and output frames.
    if len(frames) != len(expected_frames):
        raise DynamicVisualFrameError(
            f"Expected {len(expected_frames)} dynamic frames, got {len(frames)}"
        )

    source_indices = data.get("source_sample_indices")
    expected_sample_indices = [frame["source_sample_index"] for frame in expected_frames]
    # The explicit source_sample_indices array is an extra guard against frame
    # reordering or accidental edits in the trusted intermediate artifact.
    if source_indices != expected_sample_indices:
        raise DynamicVisualFrameError(
            f"Unexpected source_sample_indices: {source_indices!r}"
        )

    actual_frame_ids = [frame.get("frame_id") for frame in frames if isinstance(frame, dict)]
    expected_frame_ids = [frame["frame_id"] for frame in expected_frames]
    if actual_frame_ids != expected_frame_ids:
        raise DynamicVisualFrameError(
            f"Expected frame ids {expected_frame_ids}, got {actual_frame_ids}"
        )

    actual_sample_indices = [frame.get("source_sample_index") for frame in frames if isinstance(frame, dict)]
    if actual_sample_indices != expected_sample_indices:
        raise DynamicVisualFrameError(
            f"Expected frame sample indices {expected_sample_indices}, got {actual_sample_indices}"
        )

    return data


def load_dynamic_visual_index() -> dict[str, dict[str, Any]]:
    # Build a reusable index of which visuals belong to each validated Panda/UR5
    # link so later frame iteration does not need to re-scan the manifest.
    manifest = load_json(DYNAMIC_MANIFEST_PATH)
    if not isinstance(manifest, list):
        raise DynamicVisualFrameError("dynamic_manifest.json root must be a list")

    manifest_by_model: dict[str, dict[str, Any]] = {}
    for model_entry in manifest:
        if not isinstance(model_entry, dict):
            raise DynamicVisualFrameError("dynamic_manifest.json contains a non-object model entry")
        model_name = model_entry.get("model")
        if model_name in MODEL_ORDER:
            if model_name in manifest_by_model:
                raise DynamicVisualFrameError(f"Duplicate dynamic model entry: {model_name}")
            manifest_by_model[model_name] = model_entry

    missing = [model_name for model_name in MODEL_ORDER if model_name not in manifest_by_model]
    if missing:
        raise DynamicVisualFrameError(f"Missing dynamic model(s): {', '.join(missing)}")

    model_index = build_model_index()
    visual_index: dict[str, dict[str, Any]] = {}

    for model_name in MODEL_ORDER:
        model_entry = manifest_by_model[model_name]
        links = model_entry.get("links")
        if not isinstance(links, list):
            raise DynamicVisualFrameError(f"{model_name}.links must be a list")

        link_order: list[str] = []
        renderable_links: list[str] = []
        non_renderable_links: list[str] = []
        renderable_visuals: list[dict[str, Any]] = []
        visuals_by_link: dict[str, list[dict[str, Any]]] = {}

        for link_entry in links:
            # Preserve manifest link order so link poses from the trusted frame
            # JSON can be matched back to the correct visual assets.
            if not isinstance(link_entry, dict):
                raise DynamicVisualFrameError(f"{model_name}.links contains a non-object")

            link_name = link_entry.get("link")
            if not isinstance(link_name, str) or not link_name:
                raise DynamicVisualFrameError(f"{model_name} has a link with missing name")
            if link_name in visuals_by_link:
                raise DynamicVisualFrameError(f"{model_name} has duplicate link {link_name!r}")

            visuals = link_entry.get("visuals")
            if not isinstance(visuals, list):
                raise DynamicVisualFrameError(f"{model_name}.{link_name}.visuals must be a list")

            link_order.append(link_name)
            # Links with empty visual lists are still important to track because
            # the pose logs include them even though they never produce meshes.
            if visuals:
                renderable_links.append(link_name)
            else:
                non_renderable_links.append(link_name)

            visual_records: list[dict[str, Any]] = []
            seen_visual_names: set[str] = set()
            for visual in visuals:
                # Keep one metadata record per renderable visual so the next
                # export stage can operate at mesh/visual granularity.
                if not isinstance(visual, dict):
                    raise DynamicVisualFrameError(
                        f"{model_name}.{link_name}.visuals contains a non-object"
                    )

                visual_name = visual.get("visual_name")
                if not isinstance(visual_name, str) or not visual_name:
                    raise DynamicVisualFrameError(
                        f"{model_name}.{link_name} has a visual with missing name"
                    )
                if visual_name in seen_visual_names:
                    raise DynamicVisualFrameError(
                        f"{model_name}.{link_name} has duplicate visual {visual_name!r}"
                    )
                seen_visual_names.add(visual_name)

                geometry_type = visual.get("geometry_type")
                if not isinstance(geometry_type, str) or not geometry_type:
                    raise DynamicVisualFrameError(
                        f"{model_name}.{link_name}.{visual_name} missing geometry_type"
                    )
                geometry_type = geometry_type.lower()

                # Preserve the visual-local pose and scale exactly as declared in
                # the manifest so the later export stage can reconstruct the full chain.
                visual_pose6 = parse_pose6(
                    visual.get("visual_pose", "0 0 0 0 0 0"),
                    f"{model_name}.{link_name}.{visual_name}.visual_pose",
                )
                scale_xyz = parse_scale3(
                    visual.get("scale", "1 1 1"),
                    f"{model_name}.{link_name}.{visual_name}.scale",
                )

                geometry_uri_original: str | None = None
                resolved_source_path: str | None = None
                source_path_exists: bool | None = None
                primitive_parameters: dict[str, Any] | None = None

                if geometry_type == "mesh":
                    # Mesh visuals are the validated rigid dynamic path. Resolve
                    # the source asset now so Blender can import it directly later.
                    uri = visual.get("uri")
                    if not isinstance(uri, str) or not uri.strip():
                        raise DynamicVisualFrameError(
                            f"{model_name}.{link_name}.{visual_name} mesh has no URI"
                        )
                    resolved_path = resolve_geometry_uri(uri, model_index)
                    if not resolved_path.exists():
                        raise DynamicVisualFrameError(
                            f"Resolved source path does not exist for "
                            f"{model_name}.{link_name}.{visual_name}: {resolved_path}"
                        )
                    geometry_uri_original = uri
                    resolved_source_path = str(resolved_path)
                    source_path_exists = True
                elif geometry_type == "box":
                    # Primitive support is kept in the metadata even though the
                    # current validated rigid path mostly uses mesh visuals.
                    primitive_parameters = {
                        "size": parse_scale3(
                            visual.get("size"),
                            f"{model_name}.{link_name}.{visual_name}.size",
                        )
                    }
                elif geometry_type == "cylinder":
                    primitive_parameters = {
                        "radius": float(visual.get("radius")),
                        "length": float(visual.get("length")),
                    }
                elif geometry_type == "sphere":
                    primitive_parameters = {"radius": float(visual.get("radius"))}
                else:
                    raise DynamicVisualFrameError(
                        f"Unsupported geometry_type for {model_name}.{link_name}.{visual_name}: "
                        f"{geometry_type}"
                    )

                visual_record = {
                    # This record is the stable join point between a logged link
                    # pose and the source visual asset that should ride on that link.
                    "id": slug_id(model_name, link_name, visual_name),
                    "model_name": model_name,
                    "link_name": link_name,
                    "visual_name": visual_name,
                    "has_visuals": True,
                    "geometry_type": geometry_type,
                    "geometry_uri_original": geometry_uri_original,
                    "resolved_source_path": resolved_source_path,
                    "source_path_exists": source_path_exists,
                    "visual_pose6": visual_pose6,
                    "visual_pose_matrix": pose6_to_matrix(visual_pose6),
                    "scale_xyz": scale_xyz,
                }
                if primitive_parameters is not None:
                    visual_record["primitive_parameters"] = primitive_parameters

                visual_records.append(visual_record)
                renderable_visuals.append(visual_record)

            visuals_by_link[link_name] = visual_records

        expected = EXPECTED_COUNTS[model_name]
        # Re-check the validated Panda/UR5 visual counts here so downstream
        # stages can trust this metadata file without revisiting the manifest.
        if len(link_order) != expected["logged_links"]:
            raise DynamicVisualFrameError(
                f"{model_name} expected {expected['logged_links']} logged links, got {len(link_order)}"
            )
        if len(renderable_links) != expected["renderable_links"]:
            raise DynamicVisualFrameError(
                f"{model_name} expected {expected['renderable_links']} renderable links, "
                f"got {len(renderable_links)}"
            )
        if len(renderable_visuals) != expected["renderable_visuals"]:
            raise DynamicVisualFrameError(
                f"{model_name} expected {expected['renderable_visuals']} renderable visuals, "
                f"got {len(renderable_visuals)}"
            )
        if sorted(non_renderable_links) != sorted(expected["non_renderable_links"]):
            raise DynamicVisualFrameError(
                f"{model_name} expected non-renderable links {expected['non_renderable_links']}, "
                f"got {non_renderable_links}"
            )

        visual_index[model_name] = {
            "link_order": link_order,
            "renderable_links": renderable_links,
            "non_renderable_links": non_renderable_links,
            "visuals_by_link": visuals_by_link,
            "renderable_visuals": renderable_visuals,
        }

    total_renderable = sum(
        len(visual_index[model_name]["renderable_visuals"]) for model_name in MODEL_ORDER
    )
    # Re-check the grand total so later single-frame exporters can trust one
    # fixed renderable count across all prototype frames.
    if total_renderable != EXPECTED_TOTAL_RENDERABLE_VISUALS:
        raise DynamicVisualFrameError(
            f"Expected {EXPECTED_TOTAL_RENDERABLE_VISUALS} renderable visuals total, "
            f"got {total_renderable}"
        )

    return visual_index


def validate_frame_link(
    frame: dict[str, Any],
    model_name: str,
    link_name: str,
) -> dict[str, Any]:
    # Resolve one link pose inside the trusted frame JSON and fail if the frame
    # no longer matches the validated model/link structure.
    models = frame.get("models")
    if not isinstance(models, dict):
        raise DynamicVisualFrameError(f"Frame {frame.get('frame_id')} missing models object")
    model = models.get(model_name)
    if not isinstance(model, dict):
        raise DynamicVisualFrameError(f"Frame {frame.get('frame_id')} missing model {model_name}")
    links = model.get("links")
    if not isinstance(links, dict):
        raise DynamicVisualFrameError(f"Frame {frame.get('frame_id')} {model_name} missing links object")

    link = links.get(link_name)
    if not isinstance(link, dict):
        raise DynamicVisualFrameError(
            f"Frame {frame.get('frame_id')} missing link join for {model_name}.{link_name}"
        )
    return link


def build_visual_frames(
    trusted_frames: dict[str, Any],
    visual_index: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int], bool]:
    # Join the per-frame link poses from script 30 with the per-visual metadata
    # from the manifest so each renderable mesh gets a world transform.
    frames_out: list[dict[str, Any]] = []
    per_frame_counts: dict[str, int] = {}
    all_source_paths_exist = True

    for frame in trusted_frames["frames"]:
        if not isinstance(frame, dict):
            raise DynamicVisualFrameError("frames contains a non-object")

        frame_id = frame["frame_id"]
        source_sample_index = frame["source_sample_index"]
        timestamp = frame.get("timestamp")
        if not isinstance(timestamp, dict):
            raise DynamicVisualFrameError(f"Frame {frame_id} missing timestamp object")

        renderable_visuals: list[dict[str, Any]] = []
        non_renderable_links: list[dict[str, Any]] = []

        for model_name in MODEL_ORDER:
            # Check the logged link set first, then expand each link into zero or
            # more renderable visuals according to the validated manifest.
            expected_logged_count = EXPECTED_COUNTS[model_name]["logged_links"]
            frame_model = frame["models"].get(model_name)
            if not isinstance(frame_model, dict):
                raise DynamicVisualFrameError(f"Frame {frame_id} missing model {model_name}")
            frame_links = frame_model.get("links")
            if not isinstance(frame_links, dict):
                raise DynamicVisualFrameError(f"Frame {frame_id} {model_name} links must be an object")
            if len(frame_links) != expected_logged_count:
                raise DynamicVisualFrameError(
                    f"Frame {frame_id} {model_name} expected {expected_logged_count} logged links, "
                    f"got {len(frame_links)}"
                )

            expected_link_set = set(visual_index[model_name]["link_order"])
            actual_link_set = set(frame_links)
            if actual_link_set != expected_link_set:
                missing = sorted(expected_link_set - actual_link_set)
                unexpected = sorted(actual_link_set - expected_link_set)
                raise DynamicVisualFrameError(
                    f"Frame {frame_id} {model_name} link mismatch; "
                    f"missing={missing}, unexpected={unexpected}"
                )

            for link_name in visual_index[model_name]["link_order"]:
                # Resolve one logged link pose from the trusted frame JSON, then
                # attach every renderable visual that belongs to that link.
                link = validate_frame_link(frame, model_name, link_name)
                source_name = link.get("source_name")
                expected_source_name = f"{model_name}::{link_name}"
                if source_name != expected_source_name:
                    raise DynamicVisualFrameError(
                        f"Frame {frame_id} {model_name}.{link_name} source_name mismatch: "
                        f"{source_name!r}"
                    )

                link_pose_local_to_model = link.get("link_pose_local_to_model")
                if not isinstance(link_pose_local_to_model, dict):
                    raise DynamicVisualFrameError(
                        f"Frame {frame_id} {model_name}.{link_name} missing local link pose"
                    )
                link_to_world = validate_matrix44(
                    link.get("to_world"),
                    f"frame {frame_id} {model_name}.{link_name}.to_world",
                )

                visual_records = visual_index[model_name]["visuals_by_link"][link_name]
                if visual_records:
                    if link.get("has_visuals") is not True:
                        raise DynamicVisualFrameError(
                            f"Frame {frame_id} {model_name}.{link_name} should be renderable"
                        )
                else:
                    # Preserve non-renderable links explicitly for auditing so
                    # researchers can see which logged links never become geometry.
                    if link.get("has_visuals") is not False:
                        raise DynamicVisualFrameError(
                            f"Frame {frame_id} {model_name}.{link_name} should be non-renderable"
                        )
                    if link_name not in visual_index[model_name]["non_renderable_links"]:
                        raise DynamicVisualFrameError(
                            f"Frame {frame_id} {model_name}.{link_name} unexpectedly non-renderable"
                        )
                    non_renderable_links.append(
                        {
                            "model_name": model_name,
                            "link_name": link_name,
                            "frame_link_source_name": source_name,
                        }
                    )
                    continue

                for visual in visual_records:
                    if visual["source_path_exists"] is not True:
                        all_source_paths_exist = False

                    # The final rigid transform chain for each robot visual is:
                    # model_to_world * logged_link_pose * visual_pose * scale.
                    # We store each term separately here so Blender export can
                    # either inspect them individually or multiply them into one matrix.
                    renderable_visuals.append(
                        {
                            "frame_id": frame_id,
                            "source_sample_index": source_sample_index,
                            "timestamp": timestamp,
                            "id": visual["id"],
                            "model_name": model_name,
                            "link_name": link_name,
                            "visual_name": visual["visual_name"],
                            "frame_link_source_name": source_name,
                            "geometry_type": visual["geometry_type"],
                            "geometry_uri_original": visual["geometry_uri_original"],
                            "resolved_source_path": visual["resolved_source_path"],
                            "source_path_exists": visual["source_path_exists"],
                            "has_visuals": True,
                            "link_pose_local_to_model": link_pose_local_to_model,
                            "link_to_world": link_to_world,
                            "visual_pose6": visual["visual_pose6"],
                            "visual_pose_matrix": visual["visual_pose_matrix"],
                            "scale_xyz": visual["scale_xyz"],
                            **(
                                {"primitive_parameters": visual["primitive_parameters"]}
                                if "primitive_parameters" in visual
                                else {}
                            ),
                        }
                    )

        if len(renderable_visuals) != EXPECTED_TOTAL_RENDERABLE_VISUALS:
            # A per-frame count mismatch would mean the pose/visual join drifted
            # from the validated Panda/UR5 prototype assumptions.
            raise DynamicVisualFrameError(
                f"Frame sample {source_sample_index} expected "
                f"{EXPECTED_TOTAL_RENDERABLE_VISUALS} renderable visuals, got "
                f"{len(renderable_visuals)}"
            )

        frames_out.append(
            {
                "frame_id": frame_id,
                "source_sample_index": source_sample_index,
                "timestamp": timestamp,
                "renderable_visuals": renderable_visuals,
                "non_renderable_links": non_renderable_links,
            }
        )
        per_frame_counts[str(source_sample_index)] = len(renderable_visuals)

    return frames_out, per_frame_counts, all_source_paths_exist


def build_model_summary(visual_index: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    # Keep a compact model-level summary next to the frame records so new users
    # can understand the expected link/visual structure without re-reading the manifest.
    summary: dict[str, dict[str, Any]] = {}
    for model_name in MODEL_ORDER:
        summary[model_name] = {
            "logged_link_count": len(visual_index[model_name]["link_order"]),
            "renderable_link_count": len(visual_index[model_name]["renderable_links"]),
            "renderable_visual_count": len(visual_index[model_name]["renderable_visuals"]),
            "non_renderable_links": visual_index[model_name]["non_renderable_links"],
        }
    return summary


def write_output(path: Path, data: dict[str, Any]) -> None:
    # Persist the full per-visual metadata so all later dynamic stages can reuse
    # it without reopening manifests or pose logs.
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def main() -> int:
    args = parse_args()
    warnings: list[str] = []
    # Resolve the requested frame list first so both inputs are validated
    # against the same ordered source sample indices.
    expected_frames = load_expected_frames(args.frames_json)
    dynamic_frames_path = args.dynamic_frames.expanduser().resolve()
    output_path = args.output.expanduser().resolve()
    trusted_frames = load_trusted_frames(dynamic_frames_path, expected_frames)
    # Build the static visual lookup once, then join it against every selected
    # frame from the trusted dynamic frame file.
    visual_index = load_dynamic_visual_index()
    frames, per_frame_counts, all_source_paths_exist = build_visual_frames(
        trusted_frames,
        visual_index,
    )
    model_summary = build_model_summary(visual_index)

    # Write one per-visual metadata file that downstream mesh export can trust
    # instead of rejoining manifests and pose logs again.
    output = {
        "generated_by": Path(__file__).name,
        "source_frames_file": (
            "rt_out/dynamic_frames/prototype_frames.json"
            if dynamic_frames_path == FRAMES_PATH.resolve()
            else str(dynamic_frames_path)
        ),
        "source_manifest_file": "rt_out/manifests/dynamic_manifest.json",
        "frame_count": len(frames),
        "models": model_summary,
        "frames": frames,
        "validation": {
            "frame_count": len(frames),
            "renderable_visual_count_total": EXPECTED_TOTAL_RENDERABLE_VISUALS,
            "per_frame_renderable_visual_counts": per_frame_counts,
            "source_paths_all_exist": all_source_paths_exist,
            "warnings": warnings,
        },
    }
    write_output(output_path, output)

    print("Dynamic visual frame build")
    print(f"frames: {len(frames)}")
    print(
        f"first: frame_id={frames[0]['frame_id']}, source_sample={frames[0]['source_sample_index']}"
    )
    print(
        f"last: frame_id={frames[-1]['frame_id']}, source_sample={frames[-1]['source_sample_index']}"
    )
    print(f"output: {output_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DynamicVisualFrameError as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1)
