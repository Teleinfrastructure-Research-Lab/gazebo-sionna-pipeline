#!/usr/bin/env python3
"""Build a Blender scene for visual validation of exported actor meshes."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from runtime_config import PROJECT_ROOT, RuntimeConfigError, find_blender  # noqa: E402

DEFAULT_MESH_INDEX = PROJECT_ROOT / "rt_out" / "experiments" / "factory_panda_ur5" / "legacy_run_20260522_133045" / "reports" / "actor_validation_mesh_index.json"
DEFAULT_STATIC_MANIFEST = PROJECT_ROOT / "rt_out" / "experiments" / "factory_panda_ur5" / "legacy_run_20260522_133045" / "static_scene" / "export" / "merged_static_manifest.json"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "rt_out" / "experiments" / "factory_panda_ur5" / "legacy_run_20260522_133045" / "reports" / "actor_validation" / "blender_scene"
ROOM_XY_LIMIT = 10.0
ROOM_Z_MIN = -0.5
ROOM_Z_MAX = 4.0


class ActorValidationSceneError(RuntimeError):
    pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build actor Blender validation scene.")
    parser.add_argument("--mesh-index", type=Path, default=DEFAULT_MESH_INDEX)
    parser.add_argument("--static-manifest", type=Path, default=DEFAULT_STATIC_MANIFEST)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--blender", type=Path, default=None)
    parser.add_argument("--blender-worker", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def script_args() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]


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
        raise ActorValidationSceneError(f"Missing {label}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ActorValidationSceneError(f"Invalid JSON in {label} {path}: {exc}") from exc


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ActorValidationSceneError(f"{label} must be an object")
    return value


def finite_vec3(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ActorValidationSceneError(f"{label} must contain 3 values")
    try:
        values = [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise ActorValidationSceneError(f"{label} contains non-numeric values") from exc
    if any(not math.isfinite(item) for item in values):
        raise ActorValidationSceneError(f"{label} contains non-finite values")
    return values


def finite_pose6(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 6:
        raise ActorValidationSceneError(f"{label} must contain 6 values")
    try:
        values = [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise ActorValidationSceneError(f"{label} contains non-numeric values") from exc
    if any(not math.isfinite(item) for item in values):
        raise ActorValidationSceneError(f"{label} contains non-finite values")
    return values


def safe_name(value: Any) -> str:
    chars = [ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in str(value)]
    return "".join(chars).strip("_") or "item"


def resolve_blender_or_raise(explicit: Path | None) -> Path:
    requested = None if explicit is None else resolve_path(explicit)
    try:
        return find_blender(requested)
    except RuntimeConfigError as exc:
        raise ActorValidationSceneError(str(exc)) from exc


def validate_inputs(mesh_index_path: Path, static_manifest_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    mesh_index = require_object(load_json(mesh_index_path, "actor validation mesh index"), "mesh index")
    static_manifest = require_object(load_json(static_manifest_path, "merged static manifest"), "static manifest")
    entries = mesh_index.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ActorValidationSceneError("mesh index must contain a non-empty entries list")
    for index, entry in enumerate(entries):
        entry = require_object(entry, f"mesh index entries[{index}]")
        mesh_path = Path(str(entry.get("output_mesh_path", "")))
        if not mesh_path.exists():
            raise ActorValidationSceneError(f"Missing actor mesh path: {mesh_path}")
        finite_vec3(entry.get("bounds_min"), f"actor entry {index}.bounds_min")
        finite_vec3(entry.get("bounds_max"), f"actor entry {index}.bounds_max")
        finite_pose6(entry.get("root_pose6"), f"actor entry {index}.root_pose6")
    return mesh_index, static_manifest


def run_driver(args: argparse.Namespace) -> int:
    mesh_index_path = resolve_path(args.mesh_index)
    static_manifest_path = resolve_path(args.static_manifest)
    output_root = resolve_path(args.output_root)
    validate_inputs(mesh_index_path, static_manifest_path)
    output_root.mkdir(parents=True, exist_ok=True)

    blender = resolve_blender_or_raise(args.blender)
    command = [
        str(blender),
        "--background",
        "--python",
        str(Path(__file__).resolve()),
        "--",
        "--blender-worker",
        "--mesh-index",
        str(mesh_index_path),
        "--static-manifest",
        str(static_manifest_path),
        "--output-root",
        str(output_root),
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
        raise ActorValidationSceneError(f"Blender validation scene build failed with exit code {result.returncode}")
    return 0


def import_ply(filepath: Path) -> list[Any]:
    import bpy

    before = {obj.as_pointer() for obj in bpy.data.objects}
    if hasattr(bpy.ops.wm, "ply_import"):
        bpy.ops.wm.ply_import(filepath=str(filepath))
    elif hasattr(bpy.ops.import_mesh, "ply"):
        bpy.ops.import_mesh.ply(filepath=str(filepath))
    else:
        raise ActorValidationSceneError("Blender PLY importer is not available")
    imported = [obj for obj in bpy.data.objects if obj.as_pointer() not in before and obj.type == "MESH"]
    if not imported:
        raise ActorValidationSceneError(f"No mesh objects imported from {filepath}")
    return imported


def link_to_collection(obj: Any, collection: Any) -> None:
    import bpy

    if obj.name not in collection.objects:
        collection.objects.link(obj)
    for existing in list(obj.users_collection):
        if existing != collection:
            existing.objects.unlink(obj)


def make_material(name: str, color: tuple[float, float, float, float]) -> Any:
    import bpy

    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    return mat


def set_constant_visibility_interpolation(obj: Any) -> None:
    if not obj.animation_data or not obj.animation_data.action:
        return
    for fcurve in obj.animation_data.action.fcurves:
        for keyframe in fcurve.keyframe_points:
            keyframe.interpolation = "CONSTANT"


def keyframe_actor_visibility(obj: Any, frame_id: int, frame_start: int, frame_end: int) -> None:
    keyframes = sorted({frame_start, max(frame_start, frame_id - 1), frame_id, min(frame_end, frame_id + 1), frame_end})
    for frame in keyframes:
        visible = frame == frame_id
        obj.hide_viewport = not visible
        obj.hide_render = not visible
        obj.keyframe_insert(data_path="hide_viewport", frame=frame)
        obj.keyframe_insert(data_path="hide_render", frame=frame)
    set_constant_visibility_interpolation(obj)


def add_root_marker(entry: dict[str, Any], collection: Any) -> Any:
    import bpy

    root_pose = finite_pose6(entry["root_pose6"], f"{entry['id']}.root_pose6")
    bpy.ops.object.empty_add(type="PLAIN_AXES", location=(root_pose[0], root_pose[1], root_pose[2]))
    empty = bpy.context.object
    empty.name = f"root_{safe_name(entry['actor_name'])}_frame_{entry['validation_frame_id']:03d}"
    empty.empty_display_size = 0.12
    link_to_collection(empty, collection)
    return empty


def add_root_path_curve(entries: list[dict[str, Any]], collection: Any) -> Any:
    import bpy

    curve = bpy.data.curves.new("actor_walking_root_path", type="CURVE")
    curve.dimensions = "3D"
    curve.resolution_u = 2
    polyline = curve.splines.new("POLY")
    polyline.points.add(len(entries) - 1)
    for point, entry in zip(polyline.points, entries):
        root_pose = finite_pose6(entry["root_pose6"], f"{entry['id']}.root_pose6")
        point.co = (root_pose[0], root_pose[1], root_pose[2], 1.0)
    obj = bpy.data.objects.new("actor_walking_root_path", curve)
    collection.objects.link(obj)
    return obj


def validate_actor_entry_for_scene(entry: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    bounds_min = finite_vec3(entry["bounds_min"], f"{entry['id']}.bounds_min")
    bounds_max = finite_vec3(entry["bounds_max"], f"{entry['id']}.bounds_max")
    root_pose = finite_pose6(entry["root_pose6"], f"{entry['id']}.root_pose6")
    if any(abs(value) > ROOM_XY_LIMIT for value in bounds_min[:2] + bounds_max[:2]):
        warnings.append(f"{entry['id']} bounds outside room-ish XY limits")
    if bounds_min[2] < ROOM_Z_MIN or bounds_max[2] > ROOM_Z_MAX:
        warnings.append(f"{entry['id']} bounds outside room-ish Z limits")
    if abs(bounds_min[2] - root_pose[2]) > 0.35:
        warnings.append(f"{entry['id']} lower z {bounds_min[2]:.3f} differs from root z {root_pose[2]:.3f}")
    return warnings


def center(entry: dict[str, Any]) -> list[float]:
    bounds_min = finite_vec3(entry["bounds_min"], f"{entry['id']}.bounds_min")
    bounds_max = finite_vec3(entry["bounds_max"], f"{entry['id']}.bounds_max")
    return [(bounds_min[i] + bounds_max[i]) * 0.5 for i in range(3)]


def run_blender_worker(args: argparse.Namespace) -> int:
    import bpy

    mesh_index_path = resolve_path(args.mesh_index)
    static_manifest_path = resolve_path(args.static_manifest)
    output_root = resolve_path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    blend_path = output_root / "actor_validation_scene.blend"
    inventory_path = output_root / "actor_validation_scene_inventory.json"
    timeline_path = output_root / "actor_validation_timeline.json"

    mesh_index, static_manifest = validate_inputs(mesh_index_path, static_manifest_path)
    actor_entries = sorted(mesh_index["entries"], key=lambda item: item["validation_frame_id"])
    if not actor_entries:
        raise ActorValidationSceneError("Zero actor meshes in validation mesh index")
    frame_start = 0
    frame_end = max(int(entry["validation_frame_id"]) for entry in actor_entries)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.frame_start = frame_start
    scene.frame_end = frame_end
    scene.frame_set(frame_start)

    static_collection = bpy.data.collections.new("static_scene")
    actor_collection = bpy.data.collections.new("actor_validation_frames")
    helper_collection = bpy.data.collections.new("actor_validation_helpers")
    scene.collection.children.link(static_collection)
    scene.collection.children.link(actor_collection)
    scene.collection.children.link(helper_collection)

    static_mat = make_material("validation_static_neutral", (0.55, 0.55, 0.55, 1.0))
    actor_mat = make_material("validation_actor_current_frame", (0.9, 0.32, 0.18, 1.0))

    warnings = []
    imported_static_names: list[str] = []
    merged_groups = static_manifest.get("merged_groups", [])
    if not isinstance(merged_groups, list):
        raise ActorValidationSceneError("static manifest merged_groups must be a list")
    for index, group in enumerate(merged_groups):
        if not isinstance(group, dict):
            warnings.append(f"static merged_groups[{index}] is not an object")
            continue
        raw_path = group.get("merged_mesh_path")
        mesh_path = Path(str(raw_path)) if raw_path else Path("")
        if not mesh_path.exists():
            warnings.append(f"missing static mesh path: {raw_path}")
            continue
        objects = import_ply(mesh_path)
        for object_index, obj in enumerate(objects):
            obj.name = f"static_{safe_name(group.get('material_class'))}_{object_index:02d}"
            obj.data.name = f"{obj.name}_mesh"
            obj.data.materials.clear()
            obj.data.materials.append(static_mat)
            obj.location = (0.0, 0.0, 0.0)
            obj.rotation_euler = (0.0, 0.0, 0.0)
            obj.scale = (1.0, 1.0, 1.0)
            link_to_collection(obj, static_collection)
            imported_static_names.append(obj.name)

    imported_actor_names: list[str] = []
    timeline = []
    previous_entry: dict[str, Any] | None = None
    previous_center: list[float] | None = None
    max_center_jump = 0.0
    for entry in actor_entries:
        mesh_path = Path(entry["output_mesh_path"])
        if not mesh_path.exists():
            raise ActorValidationSceneError(f"Missing actor mesh path: {mesh_path}")
        objects = import_ply(mesh_path)
        frame_id = int(entry["validation_frame_id"])
        if len(objects) != 1:
            warnings.append(f"{entry['id']} imported as {len(objects)} mesh objects")
        for object_index, obj in enumerate(objects):
            obj.name = f"{safe_name(entry['actor_name'])}_frame_{frame_id:03d}"
            if object_index:
                obj.name = f"{obj.name}_{object_index:02d}"
            obj.data.name = f"{obj.name}_mesh"
            obj.data.materials.clear()
            obj.data.materials.append(actor_mat)
            obj.location = (0.0, 0.0, 0.0)
            obj.rotation_euler = (0.0, 0.0, 0.0)
            obj.scale = (1.0, 1.0, 1.0)
            link_to_collection(obj, actor_collection)
            keyframe_actor_visibility(obj, frame_id, frame_start, frame_end)
            imported_actor_names.append(obj.name)

        add_root_marker(entry, helper_collection)
        warnings.extend(validate_actor_entry_for_scene(entry))
        current_center = center(entry)
        if previous_center is not None and previous_entry is not None:
            jump = math.sqrt(sum((current_center[i] - previous_center[i]) ** 2 for i in range(3)))
            max_center_jump = max(max_center_jump, jump)
            if jump > 1.5:
                warnings.append(
                    f"large visual jump {jump:.3f}m between frame "
                    f"{previous_entry['validation_frame_id']} and {frame_id}"
                )
        previous_center = current_center
        previous_entry = entry
        timeline.append(
            {
                "blender_frame": frame_id,
                "actor_name": entry["actor_name"],
                "actor_object_name": f"{safe_name(entry['actor_name'])}_frame_{frame_id:03d}",
                "actor_time_seconds": entry["actor_time_seconds"],
                "animation_time_seconds": entry["animation_time_seconds"],
                "root_pose_source": entry["root_pose_source"],
            }
        )

    add_root_path_curve(actor_entries, helper_collection)
    if not imported_actor_names:
        raise ActorValidationSceneError("Zero actor meshes were imported")

    index_summary = mesh_index.get("validation_summary", {}) if isinstance(mesh_index.get("validation_summary"), dict) else {}
    inventory = {
        "generated_by": Path(__file__).name,
        "blend_path": str(blend_path),
        "mesh_index": str(mesh_index_path),
        "static_manifest": str(static_manifest_path),
        "static_mesh_count": len(imported_static_names),
        "actor_mesh_count": len(imported_actor_names),
        "timeline_frame_count": frame_end - frame_start + 1,
        "timeline_start": frame_start,
        "timeline_end": frame_end,
        "global_actor_bounds": {
            "bounds_min": index_summary.get("bounds_global_min"),
            "bounds_max": index_summary.get("bounds_global_max"),
        },
        "imported_static_object_names": imported_static_names,
        "imported_actor_object_names": imported_actor_names,
        "max_frame_to_frame_bounds_center_translation": max_center_jump,
        "warning_count": len(warnings),
        "warnings": warnings,
    }
    save_json(inventory_path, inventory)
    save_json(timeline_path, {"timeline": timeline})
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

    print("Actor Blender validation scene build")
    print(f"blend: {blend_path}")
    print(f"inventory: {inventory_path}")
    print(f"static_mesh_count: {inventory['static_mesh_count']}")
    print(f"actor_mesh_count: {inventory['actor_mesh_count']}")
    print(f"timeline_frame_count: {inventory['timeline_frame_count']}")
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
    except ActorValidationSceneError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
