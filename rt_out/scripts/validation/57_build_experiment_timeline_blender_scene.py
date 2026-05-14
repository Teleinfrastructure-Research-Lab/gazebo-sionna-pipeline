#!/usr/bin/env python3
"""Build a multi-frame Blender timeline scene from experiment composed manifests."""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from dynamic_prototype_config import load_dynamic_prototype_config
from runtime_config import PROJECT_ROOT, RuntimeConfigError, find_blender


DEFAULT_CONFIG = (
    PROJECT_ROOT
    / "rt_out"
    / "experiments"
    / "semantic_ablation_actor_200f"
    / "configs"
    / "experiment_config.json"
)
SUPPORTED_SOURCES = {"static", "dynamic", "actor"}
PROTOTYPE_CONFIG = load_dynamic_prototype_config()
EXPECTED_DYNAMIC_COUNT = int(PROTOTYPE_CONFIG["expected_renderable_visual_count_total"])


class ExperimentTimelineSceneError(RuntimeError):
    pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a Blender timeline scene for an experiment-local composed manifest sequence."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--composed-index", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--max-frames", type=int, default=None)
    parser.add_argument("--frame-step", type=int, default=1)
    parser.add_argument("--frame-ids", default=None, help="Comma-separated frame_id list.")
    parser.add_argument(
        "--show-radio-markers",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Show TX/RX markers and TX->RX reference lines.",
    )
    parser.add_argument("--hide-static", action="store_true", help="Hide static objects for the whole timeline.")
    parser.add_argument("--blender", type=Path, default=None)
    parser.add_argument("--blender-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--payload", type=Path, default=None, help=argparse.SUPPRESS)
    return parser.parse_args(argv or [])


def resolve_path(path: Path) -> Path:
    path = path.expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def load_json(path: Path, label: str) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise ExperimentTimelineSceneError(f"Missing {label}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ExperimentTimelineSceneError(f"Invalid JSON in {label} {path}: {exc}") from exc


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ExperimentTimelineSceneError(f"{label} must be an object")
    return value


def require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ExperimentTimelineSceneError(f"{label} must be a list")
    return value


def require_non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExperimentTimelineSceneError(f"{label} must be a non-empty string")
    return value.strip()


def require_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ExperimentTimelineSceneError(f"{label} must be an integer")
    return value


def parse_frame_ids(value: str | None) -> set[int] | None:
    if value is None:
        return None
    ids: set[int] = set()
    for raw_part in value.split(","):
        part = raw_part.strip()
        if not part:
            continue
        try:
            frame_id = int(part)
        except ValueError as exc:
            raise ExperimentTimelineSceneError(f"Invalid frame id in --frame-ids: {part!r}") from exc
        if frame_id < 0:
            raise ExperimentTimelineSceneError("--frame-ids cannot contain negative frame IDs")
        ids.add(frame_id)
    if not ids:
        raise ExperimentTimelineSceneError("--frame-ids did not contain any valid frame IDs")
    return ids


def safe_name(value: Any) -> str:
    chars = [ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in str(value)]
    return "".join(chars).strip("_") or "item"


def frame_dir_name(frame_id: int) -> str:
    return f"frame_{frame_id:03d}"


def script_args() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]


def resolve_blender_or_raise(explicit: Path | None) -> Path:
    requested = None if explicit is None else resolve_path(explicit)
    try:
        return find_blender(requested)
    except RuntimeConfigError as exc:
        raise ExperimentTimelineSceneError(str(exc)) from exc


def default_paths_from_config(config_path: Path) -> tuple[Path, Path]:
    config = require_object(load_json(config_path, "experiment config"), "experiment config")
    output_dir = resolve_path(Path(require_non_empty_string(config.get("output_dir"), "output_dir")))
    return output_dir / "frames" / "composed_manifests" / "composed_manifest_index.csv", output_dir / "blender_timeline"


def load_experiment_config(config_path: Path) -> dict[str, Any]:
    return require_object(load_json(config_path, "experiment config"), "experiment config")


def parse_position_list(value: Any, label: str) -> list[float]:
    items = require_list(value, label)
    if len(items) != 3:
        raise ExperimentTimelineSceneError(f"{label} must contain exactly 3 values")
    result: list[float] = []
    for index, item in enumerate(items):
        if not isinstance(item, (int, float)) or not math.isfinite(float(item)):
            raise ExperimentTimelineSceneError(f"{label}[{index}] must be a finite number")
        result.append(float(item))
    return result


def load_composed_index(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except FileNotFoundError as exc:
        raise ExperimentTimelineSceneError(f"Missing composed manifest index: {path}") from exc
    if not rows:
        raise ExperimentTimelineSceneError(f"Composed manifest index is empty: {path}")
    return rows


def validate_manifest(manifest_path: Path) -> dict[str, Any]:
    manifest = require_object(load_json(manifest_path, "composed frame manifest"), "composed frame manifest")
    frame_id = manifest.get("frame_id")
    source_sample_index = manifest.get("source_sample_index")
    if not isinstance(frame_id, int):
        raise ExperimentTimelineSceneError(f"{manifest_path} is missing integer frame_id")
    if not isinstance(source_sample_index, int):
        raise ExperimentTimelineSceneError(f"{manifest_path} is missing integer source_sample_index")
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise ExperimentTimelineSceneError(f"{manifest_path} is missing entries list")
    for index, raw_entry in enumerate(entries):
        entry = require_object(raw_entry, f"{manifest_path} entries[{index}]")
        source = require_non_empty_string(entry.get("source"), f"{manifest_path} entries[{index}].source")
        if source not in SUPPORTED_SOURCES:
            raise ExperimentTimelineSceneError(f"{manifest_path} entries[{index}] has unsupported source={source!r}")
        if entry.get("baked_world_geometry") is not True:
            raise ExperimentTimelineSceneError(
                f"{manifest_path} entries[{index}] must have baked_world_geometry == true"
            )
        mesh_path = Path(require_non_empty_string(entry.get("mesh_path"), f"{manifest_path} entries[{index}].mesh_path"))
        if not mesh_path.is_absolute():
            mesh_path = PROJECT_ROOT / mesh_path
        if not mesh_path.exists():
            raise ExperimentTimelineSceneError(f"{manifest_path} entries[{index}] mesh_path does not exist: {mesh_path}")
    return manifest


def select_rows(
    rows: list[dict[str, str]],
    *,
    max_frames: int | None,
    frame_step: int,
    frame_ids: set[int] | None,
) -> list[dict[str, str]]:
    if frame_step <= 0:
        raise ExperimentTimelineSceneError("--frame-step must be >= 1")
    if max_frames is not None and max_frames <= 0:
        raise ExperimentTimelineSceneError("--max-frames must be >= 1")

    base_rows = rows
    if frame_ids is not None:
        filtered = [row for row in rows if int(row["frame_id"]) in frame_ids]
        missing = sorted(frame_ids - {int(row["frame_id"]) for row in filtered})
        if missing:
            raise ExperimentTimelineSceneError(f"--frame-ids requested missing frame IDs: {missing}")
        base_rows = filtered
    elif max_frames is not None:
        base_rows = rows[:max_frames]

    selected = base_rows[::frame_step]
    if not selected:
        raise ExperimentTimelineSceneError("No frames selected after applying filters")
    return selected


def inventory_paths(output_root: Path) -> tuple[Path, Path, Path]:
    blend_path = output_root / "actor_200f_timeline_scene.blend"
    inventory_path = output_root / "actor_200f_timeline_inventory.json"
    timeline_frames_path = output_root / "timeline_frames.json"
    return blend_path, inventory_path, timeline_frames_path


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    config_path = resolve_path(args.config)
    config = load_experiment_config(config_path)
    composed_index = resolve_path(args.composed_index) if args.composed_index else default_paths_from_config(config_path)[0]
    output_root = resolve_path(args.output_root) if args.output_root else default_paths_from_config(config_path)[1]
    tx = require_object(config.get("tx"), "tx")
    rx_list = require_list(config.get("rx_list"), "rx_list")
    tx_id = require_non_empty_string(tx.get("id"), "tx.id")
    tx_position = parse_position_list(tx.get("position"), "tx.position")
    rx_positions: list[dict[str, Any]] = []
    for index, raw_rx in enumerate(rx_list):
        rx = require_object(raw_rx, f"rx_list[{index}]")
        rx_positions.append(
            {
                "id": require_non_empty_string(rx.get("id"), f"rx_list[{index}].id"),
                "position": parse_position_list(rx.get("position"), f"rx_list[{index}].position"),
            }
        )

    rows = load_composed_index(composed_index)
    selected_rows = select_rows(
        rows,
        max_frames=args.max_frames,
        frame_step=args.frame_step,
        frame_ids=parse_frame_ids(args.frame_ids),
    )

    selected_frames: list[dict[str, Any]] = []
    warnings: list[str] = []
    static_counts: set[int] = set()
    for row in selected_rows:
        manifest_path = resolve_path(Path(require_non_empty_string(row.get("composed_manifest_path"), "composed_manifest_path")))
        manifest = validate_manifest(manifest_path)
        frame_id = require_int(manifest.get("frame_id"), f"{manifest_path}.frame_id")
        source_sample_index = require_int(
            manifest.get("source_sample_index"), f"{manifest_path}.source_sample_index"
        )
        dynamic_count = int(manifest.get("dynamic_count", 0))
        actor_count = int(manifest.get("actor_count", 0))
        static_count = int(manifest.get("static_count", 0))
        static_counts.add(static_count)
        if dynamic_count != EXPECTED_DYNAMIC_COUNT:
            warnings.append(f"frame {frame_id}: dynamic_count {dynamic_count} != expected {EXPECTED_DYNAMIC_COUNT}")
        if actor_count != 1:
            warnings.append(f"frame {frame_id}: actor_count {actor_count} != expected 1")
        selected_frames.append(
            {
                "frame_id": frame_id,
                "source_sample_index": source_sample_index,
                "manifest_path": str(manifest_path),
                "dynamic_count": dynamic_count,
                "actor_count": actor_count,
                "static_count": static_count,
            }
        )

    if len(static_counts) > 1:
        warnings.append(f"static_count changed across selected frames: {sorted(static_counts)}")
    if len(selected_frames) > 50:
        warnings.append(f"selected_frame_count {len(selected_frames)} is large; the .blend may be heavy")

    output_root.mkdir(parents=True, exist_ok=True)
    _, _, timeline_frames_path = inventory_paths(output_root)
    save_json(
        timeline_frames_path,
        {
            "generated_by": Path(__file__).name,
            "experiment_name": require_non_empty_string(config.get("experiment_name"), "experiment_name"),
            "selected_frames": selected_frames,
        },
    )
    return {
        "config_path": str(config_path),
        "composed_index_path": str(composed_index),
        "output_root": str(output_root),
        "experiment_name": require_non_empty_string(config.get("experiment_name"), "experiment_name"),
        "tx": {"id": tx_id, "position": tx_position},
        "rx_list": rx_positions,
        "selected_frames": selected_frames,
        "show_radio_markers": bool(args.show_radio_markers),
        "hide_static": bool(args.hide_static),
        "expected_dynamic_count": EXPECTED_DYNAMIC_COUNT,
        "preflight_warnings": warnings,
    }


def run_driver(args: argparse.Namespace) -> int:
    payload = build_payload(args)
    output_root = resolve_path(Path(payload["output_root"]))
    payload_path = output_root / "_timeline_payload.json"
    save_json(payload_path, payload)
    blender = resolve_blender_or_raise(args.blender)
    command = [
        str(blender),
        "--background",
        "--python",
        str(Path(__file__).resolve()),
        "--",
        "--blender-worker",
        "--payload",
        str(payload_path),
    ]
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.stdout:
        print(result.stdout.rstrip())
    if result.returncode != 0:
        if result.stderr:
            print(result.stderr.rstrip(), file=sys.stderr)
        raise ExperimentTimelineSceneError(f"Blender timeline scene build failed with exit code {result.returncode}")
    return 0


def import_ply(filepath: Path) -> list[Any]:
    import bpy

    before = {obj.as_pointer() for obj in bpy.data.objects}
    if hasattr(bpy.ops.wm, "ply_import"):
        bpy.ops.wm.ply_import(filepath=str(filepath))
    elif hasattr(bpy.ops.import_mesh, "ply"):
        bpy.ops.import_mesh.ply(filepath=str(filepath))
    else:
        raise ExperimentTimelineSceneError("Blender PLY importer is not available")
    imported = [obj for obj in bpy.data.objects if obj.as_pointer() not in before and obj.type == "MESH"]
    if not imported:
        raise ExperimentTimelineSceneError(f"No mesh objects imported from {filepath}")
    return imported


def link_to_collection(obj: Any, collection: Any) -> None:
    if obj.name not in collection.objects:
        collection.objects.link(obj)
    for existing in list(obj.users_collection):
        if existing != collection:
            existing.objects.unlink(obj)


def get_or_create_collection(name: str, parent: Any) -> Any:
    import bpy

    existing = bpy.data.collections.get(name)
    if existing is not None:
        if existing.name not in parent.children:
            parent.children.link(existing)
        return existing
    collection = bpy.data.collections.new(name)
    parent.children.link(collection)
    return collection


def make_material(name: str, color: tuple[float, float, float, float]) -> Any:
    import bpy

    existing = bpy.data.materials.get(name)
    if existing is not None:
        return existing
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    return mat


def object_name_for_entry(entry: dict[str, Any], frame_id: int, local_index: int) -> str:
    source = entry["source"]
    if source == "static":
        return f"static_{safe_name(entry.get('material_label'))}_{local_index:02d}"
    if source == "dynamic":
        return (
            f"dynamic_{frame_dir_name(frame_id)}_"
            f"{safe_name(entry.get('model_name'))}_{safe_name(entry.get('link_name'))}_{safe_name(entry.get('visual_name'))}"
        )
    return f"actor_{frame_dir_name(frame_id)}_{safe_name(entry.get('actor_name'))}_{local_index:02d}"


def set_constant_visibility_keys(obj: Any, frame_id: int, timeline_start: int, timeline_end: int) -> None:
    obj.hide_viewport = timeline_start != frame_id
    obj.hide_render = timeline_start != frame_id
    obj.keyframe_insert(data_path="hide_viewport", frame=timeline_start)
    obj.keyframe_insert(data_path="hide_render", frame=timeline_start)

    if frame_id != timeline_start:
        obj.hide_viewport = True
        obj.hide_render = True
        obj.keyframe_insert(data_path="hide_viewport", frame=max(timeline_start, frame_id - 1))
        obj.keyframe_insert(data_path="hide_render", frame=max(timeline_start, frame_id - 1))

    obj.hide_viewport = False
    obj.hide_render = False
    obj.keyframe_insert(data_path="hide_viewport", frame=frame_id)
    obj.keyframe_insert(data_path="hide_render", frame=frame_id)

    if frame_id < timeline_end:
        obj.hide_viewport = True
        obj.hide_render = True
        obj.keyframe_insert(data_path="hide_viewport", frame=frame_id + 1)
        obj.keyframe_insert(data_path="hide_render", frame=frame_id + 1)

    if obj.animation_data and obj.animation_data.action:
        for fcurve in obj.animation_data.action.fcurves:
            for keyframe in fcurve.keyframe_points:
                keyframe.interpolation = "CONSTANT"


def add_tx_rx_markers(
    *,
    tx: dict[str, Any],
    rx_list: list[dict[str, Any]],
    marker_collection: Any,
    line_collection: Any,
    materials: dict[str, Any],
) -> tuple[list[str], list[str]]:
    import bpy

    marker_names: list[str] = []
    line_names: list[str] = []
    tx_position = tx["position"]
    tx_name = f"tx_{safe_name(tx['id'])}"
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=0.08, location=tuple(tx_position))
    tx_obj = bpy.context.object
    tx_obj.name = tx_name
    tx_obj.data.name = f"{tx_name}_mesh"
    tx_obj.data.materials.clear()
    tx_obj.data.materials.append(materials["tx"])
    link_to_collection(tx_obj, marker_collection)
    marker_names.append(tx_obj.name)

    for rx in rx_list:
        rx_name = f"rx_{safe_name(rx['id'])}"
        bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=0.06, location=tuple(rx["position"]))
        rx_obj = bpy.context.object
        rx_obj.name = rx_name
        rx_obj.data.name = f"{rx_name}_mesh"
        rx_obj.data.materials.clear()
        rx_obj.data.materials.append(materials["rx"])
        link_to_collection(rx_obj, marker_collection)
        marker_names.append(rx_obj.name)

        curve = bpy.data.curves.new(f"curve_line_{safe_name(tx['id'])}_to_{safe_name(rx['id'])}", type="CURVE")
        curve.dimensions = "3D"
        curve.resolution_u = 1
        curve.bevel_depth = 0.01
        curve.bevel_resolution = 2
        polyline = curve.splines.new("POLY")
        polyline.points.add(1)
        polyline.points[0].co = (tx_position[0], tx_position[1], tx_position[2], 1.0)
        polyline.points[1].co = (rx["position"][0], rx["position"][1], rx["position"][2], 1.0)
        line_name = f"line_{safe_name(tx['id'])}_to_{safe_name(rx['id'])}"
        line_obj = bpy.data.objects.new(line_name, curve)
        curve.materials.append(materials["line"])
        line_collection.objects.link(line_obj)
        line_names.append(line_obj.name)

    return marker_names, line_names


def run_blender_worker(args: argparse.Namespace) -> int:
    import bpy

    if args.payload is None:
        raise ExperimentTimelineSceneError("Missing --payload for Blender worker")
    payload_path = resolve_path(args.payload)
    payload = require_object(load_json(payload_path, "worker payload"), "worker payload")
    selected_frames = require_list(payload.get("selected_frames"), "selected_frames")
    if not selected_frames:
        raise ExperimentTimelineSceneError("selected_frames is empty")

    output_root = resolve_path(Path(require_non_empty_string(payload.get("output_root"), "output_root")))
    blend_path, inventory_path, _ = inventory_paths(output_root)
    experiment_name = require_non_empty_string(payload.get("experiment_name"), "experiment_name")
    tx = require_object(payload.get("tx"), "tx")
    rx_list = require_list(payload.get("rx_list"), "rx_list")
    preflight_warnings = [str(item) for item in require_list(payload.get("preflight_warnings", []), "preflight_warnings")]
    show_radio_markers = bool(payload.get("show_radio_markers", True))
    hide_static = bool(payload.get("hide_static", False))

    frame_ids = [require_int(item.get("frame_id"), f"selected_frames[{index}].frame_id") for index, item in enumerate(selected_frames)]
    timeline_start = min(frame_ids)
    timeline_end = max(frame_ids)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.frame_start = timeline_start
    scene.frame_end = timeline_end
    scene.frame_set(timeline_start)

    root_collection = scene.collection
    static_collection = get_or_create_collection("static_scene", root_collection)
    dynamic_root = get_or_create_collection("dynamic_frames", root_collection)
    actor_root = get_or_create_collection("actor_frames", root_collection)
    radio_collection = get_or_create_collection("radio_markers", root_collection)
    line_collection = get_or_create_collection("tx_rx_reference_lines", root_collection)

    materials = {
        "static": make_material("timeline_static_neutral", (0.58, 0.58, 0.58, 1.0)),
        "dynamic": make_material("timeline_dynamic_robot", (0.16, 0.48, 0.92, 1.0)),
        "actor": make_material("timeline_actor", (0.94, 0.34, 0.18, 1.0)),
        "tx": make_material("timeline_tx_marker", (0.0, 0.8, 0.12, 1.0)),
        "rx": make_material("timeline_rx_marker", (0.95, 0.1, 0.16, 1.0)),
        "line": make_material("timeline_tx_rx_line", (1.0, 0.9, 0.08, 1.0)),
    }

    warnings = list(preflight_warnings)
    imported_names: dict[str, list[str]] = {"static": [], "dynamic": [], "actor": []}
    imported_counts_by_source = {"static": 0, "dynamic": 0, "actor": 0}

    first_manifest = validate_manifest(resolve_path(Path(selected_frames[0]["manifest_path"])))
    static_entries = [entry for entry in first_manifest["entries"] if entry["source"] == "static"]
    for index, entry in enumerate(static_entries):
        mesh_path = Path(entry["mesh_path"])
        if not mesh_path.is_absolute():
            mesh_path = PROJECT_ROOT / mesh_path
        objects = import_ply(mesh_path)
        if len(objects) != 1:
            warnings.append(f"static entry {entry.get('id')} imported as {len(objects)} mesh objects")
        for object_index, obj in enumerate(objects):
            base_name = object_name_for_entry(entry, timeline_start, index)
            obj.name = base_name if object_index == 0 else f"{base_name}_{object_index:02d}"
            obj.data.name = f"{obj.name}_mesh"
            obj.data.materials.clear()
            obj.data.materials.append(materials["static"])
            link_to_collection(obj, static_collection)
            obj.hide_viewport = hide_static
            obj.hide_render = hide_static
            imported_names["static"].append(obj.name)
            imported_counts_by_source["static"] += 1

    for frame_info in selected_frames:
        frame_id = int(frame_info["frame_id"])
        manifest = validate_manifest(resolve_path(Path(frame_info["manifest_path"])))
        dynamic_collection = get_or_create_collection(frame_dir_name(frame_id), dynamic_root)
        actor_collection = get_or_create_collection(frame_dir_name(frame_id), actor_root)
        per_source_index = {"dynamic": 0, "actor": 0}
        for entry in manifest["entries"]:
            source = entry["source"]
            if source == "static":
                continue
            if source not in {"dynamic", "actor"}:
                warnings.append(f"frame {frame_id}: unsupported source ignored: {source}")
                continue
            mesh_path = Path(entry["mesh_path"])
            if not mesh_path.is_absolute():
                mesh_path = PROJECT_ROOT / mesh_path
            objects = import_ply(mesh_path)
            if len(objects) != 1:
                warnings.append(f"frame {frame_id}: {entry.get('id')} imported as {len(objects)} mesh objects")
            target_collection = dynamic_collection if source == "dynamic" else actor_collection
            for object_index, obj in enumerate(objects):
                base_name = object_name_for_entry(entry, frame_id, per_source_index[source])
                obj.name = base_name if object_index == 0 else f"{base_name}_{object_index:02d}"
                obj.data.name = f"{obj.name}_mesh"
                obj.data.materials.clear()
                obj.data.materials.append(materials[source])
                link_to_collection(obj, target_collection)
                set_constant_visibility_keys(obj, frame_id, timeline_start, timeline_end)
                imported_names[source].append(obj.name)
                imported_counts_by_source[source] += 1
            per_source_index[source] += 1

    marker_names: list[str] = []
    line_names: list[str] = []
    if show_radio_markers:
        marker_names, line_names = add_tx_rx_markers(
            tx=tx,
            rx_list=rx_list,
            marker_collection=radio_collection,
            line_collection=line_collection,
            materials=materials,
        )

    inventory = {
        "generated_by": Path(__file__).name,
        "experiment_name": experiment_name,
        "selected_frame_count": len(selected_frames),
        "selected_frame_ids": frame_ids,
        "timeline_start": timeline_start,
        "timeline_end": timeline_end,
        "static_object_count": imported_counts_by_source["static"],
        "dynamic_object_count": imported_counts_by_source["dynamic"],
        "actor_object_count": imported_counts_by_source["actor"],
        "tx_position": tx["position"],
        "rx_positions": {item["id"]: item["position"] for item in rx_list},
        "tx_rx_line_count": len(line_names),
        "imported_object_counts_by_source": imported_counts_by_source,
        "imported_object_names_by_source": imported_names,
        "radio_marker_names": marker_names,
        "tx_rx_line_names": line_names,
        "radio_marker_count": len(marker_names),
        "warning_count": len(warnings),
        "warnings": warnings,
        "estimated_total_mesh_object_count": sum(imported_counts_by_source.values()),
        "blend_path": str(blend_path),
        "config_path": payload["config_path"],
        "composed_index_path": payload["composed_index_path"],
        "show_radio_markers": show_radio_markers,
        "hide_static": hide_static,
    }
    save_json(inventory_path, inventory)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

    print("Experiment timeline Blender scene build")
    print(f"experiment_name: {experiment_name}")
    print(f"blend: {blend_path}")
    print(f"inventory: {inventory_path}")
    print(f"selected_frame_count: {inventory['selected_frame_count']}")
    print(f"timeline_start: {timeline_start}")
    print(f"timeline_end: {timeline_end}")
    print(f"static_object_count: {inventory['static_object_count']}")
    print(f"dynamic_object_count: {inventory['dynamic_object_count']}")
    print(f"actor_object_count: {inventory['actor_object_count']}")
    print(f"radio_marker_count: {inventory['radio_marker_count']}")
    print(f"tx_rx_line_count: {inventory['tx_rx_line_count']}")
    print(f"warning_count: {inventory['warning_count']}")
    for warning in warnings:
        print(f"WARNING: {warning}")
    return 0


def main() -> int:
    args = parse_args(script_args())
    if args.blender_worker:
        return run_blender_worker(args)
    return run_driver(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ExperimentTimelineSceneError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
