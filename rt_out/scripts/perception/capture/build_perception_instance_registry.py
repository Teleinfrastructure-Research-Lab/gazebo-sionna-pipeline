#!/usr/bin/env python3
"""Build a stable perception instance registry for the pilot dataset."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
import re
from typing import Any


DEFAULT_CONFIG = Path(
    "rt_out/experiments/perception_rt_small_v0/run_20260522_133045/config/perception_dataset_config.json"
)
DEFAULT_STATIC_MANIFEST = Path(
    "rt_out/experiments/factory_panda_ur5/legacy_run_20260522_133045/manifests/static_manifest.json"
)
DEFAULT_STATIC_REGISTRY = Path(
    "rt_out/experiments/factory_panda_ur5/legacy_run_20260522_133045/manifests/static_registry.json"
)
DEFAULT_ACTOR_MANIFEST = Path(
    "rt_out/experiments/factory_panda_ur5/legacy_run_20260522_133045/manifests/actor_manifest.json"
)

REQUIRED_SEMANTIC_IDS = tuple(str(value) for value in range(1, 11))


class RegistryError(RuntimeError):
    """Raised when the instance registry cannot be built structurally."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a stable instance registry for the perception+RT pilot.",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--selected-frames", type=Path, default=None)
    parser.add_argument("--semantic-label-map", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--summary-output", type=Path, default=None)
    parser.add_argument("--review-csv", type=Path, default=None)
    return parser.parse_args()


def load_json(path: Path, *, required: bool = True) -> Any | None:
    if not path.exists():
        if required:
            raise RegistryError(f"Required JSON file does not exist: {path}")
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise RegistryError(f"Failed to parse JSON from {path}: {exc}") from exc


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")


def require_dict(payload: Any, path: Path) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RegistryError(f"Expected JSON object/dict in {path}, got {type(payload).__name__}.")
    return payload


def normalize_name(text: str) -> str:
    return text.strip().lower().replace("-", "_").replace(" ", "_")


def token_set(*values: str | None) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        if not value:
            continue
        tokens.update(token for token in re.split(r"[^a-z0-9]+", value.lower()) if token)
    return tokens


def assign_semantic(
    instance_name: str,
    model_name: str | None = None,
) -> tuple[int, str, str]:
    normalized_instance = normalize_name(instance_name)
    normalized_model = normalize_name(model_name) if model_name else None
    haystack = " ".join(
        value for value in (instance_name, model_name or "") if value
    ).lower()
    tokens = token_set(instance_name, model_name)

    exact_misc_object_names = {
        "arm_part",
        "gear_part",
        "disk_part",
        "gasket_part",
        "piston_rod_part",
        "cross_joint_part",
        "t_brace_part",
        "monitorandkeyboard",
        "picking_shelves",
    }
    for key in (normalized_instance, normalized_model):
        if key and key in exact_misc_object_names:
            return 10, "misc_object", "scene_specific_name_rule"

    if {"actor", "human", "person", "walking", "standing", "sitting"} & tokens:
        return 9, "human", "heuristic_name_match"

    checks = [
        (1, "floor", ("floor", "ground", "plane")),
        (2, "ceiling", ("ceiling",)),
        (3, "wall", ("wall",)),
        (4, "door", ("door", "gate")),
        (5, "window", ("window", "glass")),
        (6, "table", ("table", "desk")),
        (7, "chair", ("chair", "seat")),
        (
            8,
            "robot",
            (
                "panda",
                "ur5",
                "ur5_rg2",
                "robot",
                "gripper",
                "finger",
                "hand",
                "link",
                "arm",
                "cerberus",
                "anymal",
                "x500",
                "uav",
                "drone",
                "quadrotor",
                "quadcopter",
            ),
        ),
    ]
    for semantic_id, semantic_name, needles in checks:
        if any(needle in haystack for needle in needles):
            return semantic_id, semantic_name, "heuristic_name_match"
    return 10, "misc_object", "fallback_misc_object"


def validate_semantic_map(label_map: dict[str, Any], path: Path) -> None:
    for semantic_id in REQUIRED_SEMANTIC_IDS:
        if semantic_id not in label_map:
            raise RegistryError(
                f"semantic_label_map is missing required semantic id {semantic_id} in {path}"
            )


def resolve_paths(config_path: Path, args: argparse.Namespace, config: dict[str, Any]) -> dict[str, Path]:
    output_root = config_path.parent.parent
    source_experiment = config.get("source_experiment")
    if not isinstance(source_experiment, str) or not source_experiment.strip():
        raise RegistryError("Config is missing a valid 'source_experiment' string.")
    source_root = Path(source_experiment)
    return {
        "selected_frames": args.selected_frames or (output_root / "frames" / "selected_frames.json"),
        "semantic_label_map": args.semantic_label_map or (output_root / "config" / "semantic_label_map.json"),
        "output": args.output or (output_root / "frames" / "instance_registry.json"),
        "summary_output": args.summary_output or (output_root / "frames" / "instance_registry_summary.json"),
        "review_csv": args.review_csv or (output_root / "validation" / "instance_registry_review.csv"),
        "dynamic_visual_frames": source_root / "frames" / "dynamic_visual_frames.json",
        "actor_frame_samples": source_root / "frames" / "actor_frame_samples.json",
    }


def extract_selected_frames(payload: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    selected = payload.get("selected_frames")
    if not isinstance(selected, list):
        raise RegistryError(f"{path} is missing a list 'selected_frames'.")
    if not selected:
        raise RegistryError(f"{path} contains no selected frames.")
    for index, item in enumerate(selected):
        if not isinstance(item, dict):
            raise RegistryError(f"selected_frames[{index}] in {path} is not a dict.")
    return selected


def build_static_instances(
    warnings: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    used_inputs: list[str] = []
    instances: list[dict[str, Any]] = []

    static_manifest = load_json(DEFAULT_STATIC_MANIFEST, required=False)
    if isinstance(static_manifest, list):
        used_inputs.append(str(DEFAULT_STATIC_MANIFEST))
        for offset, item in enumerate(static_manifest):
            if not isinstance(item, dict):
                warnings.append(
                    f"Skipping static_manifest entry {offset}: expected dict, got {type(item).__name__}."
                )
                continue
            model_name = str(item.get("model") or f"static_model_{offset:03d}")
            instance_name = normalize_name(model_name) or f"static_model_{offset:03d}"
            semantic_id, semantic_name, assignment_method = assign_semantic(instance_name, model_name)
            members: list[dict[str, Any]] = []
            links = item.get("links", [])
            if isinstance(links, list):
                for link in links:
                    if not isinstance(link, dict):
                        continue
                    link_name = link.get("link")
                    visuals = link.get("visuals", [])
                    if isinstance(visuals, list):
                        for visual in visuals:
                            if not isinstance(visual, dict):
                                continue
                            members.append(
                                {
                                    "link_name": link_name,
                                    "visual_name": visual.get("visual_name"),
                                    "geometry_type": visual.get("geometry_type"),
                                    "uri": visual.get("uri"),
                                }
                            )
                    elif link_name is not None:
                        members.append({"link_name": link_name})
            instances.append(
                {
                    "instance_id": 1000 + len(instances),
                    "instance_name": instance_name,
                    "semantic_id": semantic_id,
                    "semantic_name": semantic_name,
                    "source": "static",
                    "source_key": f"static_manifest[{offset}]::{model_name}",
                    "model": model_name,
                    "members": members,
                    "assignment_method": assignment_method,
                    "review_status": "auto_assigned",
                }
            )
        return instances, used_inputs

    static_registry = load_json(DEFAULT_STATIC_REGISTRY, required=False)
    if isinstance(static_registry, dict) and isinstance(static_registry.get("entries"), list):
        used_inputs.append(str(DEFAULT_STATIC_REGISTRY))
        warnings.append(
            "Fell back to static_registry.json; static grouping may be more visual/material-oriented."
        )
        grouped: dict[str, list[dict[str, Any]]] = {}
        for entry in static_registry["entries"]:
            if not isinstance(entry, dict):
                continue
            model_name = str(entry.get("model_name") or "unknown_static_model")
            grouped.setdefault(model_name, []).append(entry)
        for model_name in sorted(grouped):
            instance_name = normalize_name(model_name)
            semantic_id, semantic_name, assignment_method = assign_semantic(instance_name, model_name)
            members = [
                {
                    "entry_id": item.get("id"),
                    "link_name": item.get("link_name"),
                    "visual_name": item.get("visual_name"),
                    "geometry_type": item.get("geometry_type"),
                    "uri": item.get("uri"),
                }
                for item in grouped[model_name]
            ]
            instances.append(
                {
                    "instance_id": 1000 + len(instances),
                    "instance_name": instance_name,
                    "semantic_id": semantic_id,
                    "semantic_name": semantic_name,
                    "source": "static",
                    "source_key": f"static_registry::{model_name}",
                    "model": model_name,
                    "members": members,
                    "assignment_method": assignment_method,
                    "review_status": "auto_assigned",
                }
            )
        return instances, used_inputs

    warnings.append("No usable static manifest/registry found; static instance discovery is empty.")
    return instances, used_inputs


def build_dynamic_instances(
    dynamic_path: Path,
    warnings: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    used_inputs: list[str] = []
    payload = load_json(dynamic_path, required=False)
    if payload is None:
        warnings.append(f"Dynamic visual frames file not found: {dynamic_path}")
        return [], used_inputs

    data = require_dict(payload, dynamic_path)
    frames = data.get("frames")
    if not isinstance(frames, list) or not frames:
        warnings.append(f"Dynamic visual frames file has no usable frames: {dynamic_path}")
        return [], used_inputs
    first_frame = frames[0]
    if not isinstance(first_frame, dict):
        warnings.append(f"Dynamic visual frames first frame is malformed: {dynamic_path}")
        return [], used_inputs

    visuals = first_frame.get("renderable_visuals")
    if not isinstance(visuals, list):
        warnings.append(f"Dynamic visual frames missing renderable_visuals in first frame: {dynamic_path}")
        return [], used_inputs

    used_inputs.append(str(dynamic_path))
    grouped: dict[str, list[dict[str, Any]]] = {"Panda": [], "UR5": []}
    for visual in visuals:
        if not isinstance(visual, dict):
            continue
        model_name = str(visual.get("model_name") or "")
        lowered = model_name.lower()
        if "panda" in lowered:
            grouped["Panda"].append(visual)
        elif "ur5" in lowered or "ur5_rg2" in lowered:
            grouped["UR5"].append(visual)

    instances: list[dict[str, Any]] = []
    if grouped["Panda"]:
        semantic_id, semantic_name, assignment_method = assign_semantic("panda", "Panda")
        members = [
            {
                "entry_id": item.get("id"),
                "model_name": item.get("model_name"),
                "link_name": item.get("link_name"),
                "visual_name": item.get("visual_name"),
            }
            for item in sorted(grouped["Panda"], key=lambda x: str(x.get("id", "")))
        ]
        instances.append(
            {
                "instance_id": 2000,
                "instance_name": "panda",
                "semantic_id": semantic_id,
                "semantic_name": semantic_name,
                "source": "dynamic_rigid",
                "source_key": "dynamic_visual_frames::Panda",
                "model": "Panda",
                "members": members,
                "assignment_method": assignment_method,
                "review_status": "auto_assigned",
            }
        )

    if grouped["UR5"]:
        semantic_id, semantic_name, assignment_method = assign_semantic("ur5_rg2", "ur5_rg2")
        members = [
            {
                "entry_id": item.get("id"),
                "model_name": item.get("model_name"),
                "link_name": item.get("link_name"),
                "visual_name": item.get("visual_name"),
            }
            for item in sorted(grouped["UR5"], key=lambda x: str(x.get("id", "")))
        ]
        instances.append(
            {
                "instance_id": 2001,
                "instance_name": "ur5_rg2",
                "semantic_id": semantic_id,
                "semantic_name": semantic_name,
                "source": "dynamic_rigid",
                "source_key": "dynamic_visual_frames::ur5_rg2",
                "model": "ur5_rg2",
                "members": members,
                "assignment_method": assignment_method,
                "review_status": "auto_assigned",
            }
        )

    if not instances:
        warnings.append("No dynamic robot instances were discovered from dynamic_visual_frames.json.")
    return instances, used_inputs


def build_actor_instances(
    use_actor: bool,
    actor_samples_path: Path,
    warnings: list[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    used_inputs: list[str] = []
    if not use_actor:
        return [], used_inputs

    sample_actor_names: set[str] = set()
    manifest_actor_names: set[str] = set()

    actor_samples = load_json(actor_samples_path, required=False)
    if isinstance(actor_samples, dict):
        frames = actor_samples.get("frames")
        if isinstance(frames, list):
            used_inputs.append(str(actor_samples_path))
            for frame in frames:
                if not isinstance(frame, dict):
                    continue
                actors = frame.get("actors")
                if not isinstance(actors, list):
                    continue
                for actor in actors:
                    if isinstance(actor, dict) and actor.get("actor_name"):
                        sample_actor_names.add(str(actor["actor_name"]))

    actor_manifest = load_json(DEFAULT_ACTOR_MANIFEST, required=False)
    if isinstance(actor_manifest, dict):
        actors = actor_manifest.get("actors")
        if isinstance(actors, list):
            used_inputs.append(str(DEFAULT_ACTOR_MANIFEST))
            for actor in actors:
                if not isinstance(actor, dict):
                    continue
                name = actor.get("actor_name")
                if name:
                    manifest_actor_names.add(str(name))

    actor_names = sample_actor_names | manifest_actor_names
    if not actor_names:
        warnings.append("use_actor=true but no actor instance could be discovered from actor inputs.")
        return [], used_inputs

    instances: list[dict[str, Any]] = []
    for offset, actor_name in enumerate(sorted(actor_names)):
        semantic_id, semantic_name, assignment_method = assign_semantic(
            actor_name,
            actor_name,
        )
        member = {
            "actor_name": actor_name,
            "present_in_source_samples": actor_name in sample_actor_names,
            "present_in_actor_manifest": actor_name in manifest_actor_names,
        }
        instances.append(
            {
                "instance_id": 3000 + offset,
                "instance_name": normalize_name(actor_name),
                "semantic_id": semantic_id,
                "semantic_name": semantic_name,
                "source": "actor",
                "source_key": f"actor::{actor_name}",
                "model": actor_name,
                "members": [member],
                "assignment_method": assignment_method,
                "review_status": "auto_assigned",
            }
        )
    return instances, used_inputs


def validate_instances(instances: list[dict[str, Any]], semantic_label_map: dict[str, str]) -> None:
    ids = [int(item["instance_id"]) for item in instances]
    if len(ids) != len(set(ids)):
        raise RegistryError("Instance IDs are not unique.")
    allowed_ids = {int(key) for key in semantic_label_map}
    for item in instances:
        semantic_id = int(item["semantic_id"])
        if semantic_id not in allowed_ids:
            raise RegistryError(
                f"Instance {item['instance_id']} uses semantic_id {semantic_id} "
                "which is not present in semantic_label_map."
            )


def write_review_csv(path: Path, instances: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "instance_id",
                "instance_name",
                "semantic_id",
                "semantic_name",
                "source",
                "model",
                "assignment_method",
                "review_status",
                "notes",
            ],
        )
        writer.writeheader()
        for item in instances:
            writer.writerow(
                {
                    "instance_id": item["instance_id"],
                    "instance_name": item["instance_name"],
                    "semantic_id": item["semantic_id"],
                    "semantic_name": item["semantic_name"],
                    "source": item["source"],
                    "model": item.get("model", ""),
                    "assignment_method": item["assignment_method"],
                    "review_status": item["review_status"],
                    "notes": "",
                }
            )


def main() -> None:
    args = parse_args()
    config_path = args.config
    config = require_dict(load_json(config_path), config_path)
    paths = resolve_paths(config_path, args, config)
    experiment_root = config_path.resolve().parents[1]

    selected_frames_payload = require_dict(
        load_json(paths["selected_frames"]),
        paths["selected_frames"],
    )
    selected_frames = extract_selected_frames(selected_frames_payload, paths["selected_frames"])

    semantic_label_map = require_dict(
        load_json(paths["semantic_label_map"]),
        paths["semantic_label_map"],
    )
    validate_semantic_map(semantic_label_map, paths["semantic_label_map"])

    warnings: list[str] = []
    static_instances, static_inputs = build_static_instances(warnings)
    dynamic_instances, dynamic_inputs = build_dynamic_instances(
        paths["dynamic_visual_frames"], warnings
    )
    actor_instances, actor_inputs = build_actor_instances(
        bool(config.get("use_actor", False)),
        paths["actor_frame_samples"],
        warnings,
    )

    instances = static_instances + dynamic_instances + actor_instances
    instances.sort(key=lambda item: int(item["instance_id"]))
    validate_instances(instances, semantic_label_map)

    if bool(config.get("use_actor", False)) and not actor_instances:
        warnings.append("Actor usage is enabled, but no actor/human instance was created.")
    if not dynamic_instances:
        warnings.append("No dynamic robot instance was created.")

    semantic_counts = Counter((int(item["semantic_id"]), item["semantic_name"]) for item in instances)
    summary = {
        "total_instance_count": len(instances),
        "static_instance_count": len(static_instances),
        "dynamic_rigid_instance_count": len(dynamic_instances),
        "actor_instance_count": len(actor_instances),
        "count_per_semantic": [
            {
                "semantic_id": semantic_id,
                "semantic_name": semantic_name,
                "count": count,
            }
            for (semantic_id, semantic_name), count in sorted(semantic_counts.items())
        ],
        "misc_object_count": sum(
            1 for item in instances if int(item["semantic_id"]) == 10
        ),
        "input_files_used": sorted(set(static_inputs + dynamic_inputs + actor_inputs + [
            str(paths["selected_frames"]),
            str(paths["semantic_label_map"]),
        ])),
        "warnings": warnings,
    }

    registry_payload = {
        "experiment_name": config.get("experiment_name"),
        "source_experiment": config.get("source_experiment"),
        "semantic_label_map_path": str(paths["semantic_label_map"]),
        "selected_frames_path": str(paths["selected_frames"]),
        "instance_count": len(instances),
        "instances": instances,
    }

    write_json(paths["output"], registry_payload)
    write_json(paths["summary_output"], summary)
    write_review_csv(paths["review_csv"], instances)

    print(
        f"experiment_name={config.get('experiment_name')}\n"
        f"experiment_root={experiment_root}\n"
        f"selected_frame_count={len(selected_frames)}\n"
        f"instance_count={len(instances)}\n"
        f"static_instance_count={len(static_instances)}\n"
        f"dynamic_rigid_instance_count={len(dynamic_instances)}\n"
        f"actor_instance_count={len(actor_instances)}\n"
        f"warning_count={len(warnings)}\n"
        f"output_json={paths['output']}\n"
        f"summary_json={paths['summary_output']}\n"
        f"review_csv={paths['review_csv']}"
    )


if __name__ == "__main__":
    main()
