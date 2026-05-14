#!/usr/bin/env python3
"""Build a single-frame Blender inspection scene from a composed frame manifest."""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from dynamic_prototype_config import load_dynamic_prototype_config
from runtime_config import PROJECT_ROOT, RuntimeConfigError, find_blender

DEFAULT_COMPOSED_MANIFEST = (
    PROJECT_ROOT / "rt_out" / "composed_scene" / "frame_000" / "composed_frame_000_manifest.json"
)
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "rt_out" / "composed_scene" / "frame_000" / "blender_inspection"
PROTOTYPE_CONFIG = load_dynamic_prototype_config()
EXPECTED_DYNAMIC_COUNT = PROTOTYPE_CONFIG["expected_renderable_visual_count_total"]
SUPPORTED_SOURCES = {"static", "dynamic", "actor"}


class ComposedFrameBlenderSceneError(RuntimeError):
    pass


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a Blender scene from one composed frame manifest.")
    parser.add_argument("--composed-manifest", type=Path, default=DEFAULT_COMPOSED_MANIFEST)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--blender", type=Path, default=None)
    parser.add_argument("--show-radio-markers", action="store_true", help="Add TX/RX markers and a reference line.")
    parser.add_argument("--tx", default="-0.3,-3.8,1.3", help="TX position as x,y,z.")
    parser.add_argument("--rx", default="2.5,-3.1,1.3", help="RX position as x,y,z.")
    parser.add_argument("--blender-worker", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(normalize_position_args(argv or []))


def normalize_position_args(argv: list[str]) -> list[str]:
    # argparse treats comma-separated negative coordinates after --tx/--rx as a
    # potential option. Normalize "--tx -0.3,-3.8,1.3" to "--tx=-0.3,-3.8,1.3".
    normalized: list[str] = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg in {"--tx", "--rx"} and index + 1 < len(argv):
            normalized.append(f"{arg}={argv[index + 1]}")
            index += 2
            continue
        normalized.append(arg)
        index += 1
    return normalized


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
        raise ComposedFrameBlenderSceneError(f"Missing {label}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ComposedFrameBlenderSceneError(f"Invalid JSON in {label} {path}: {exc}") from exc


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ComposedFrameBlenderSceneError(f"{label} must be an object")
    return value


def require_non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ComposedFrameBlenderSceneError(f"{label} must be a non-empty string")
    return value.strip()


def parse_position(value: Any, label: str) -> list[float]:
    if not isinstance(value, str):
        raise ComposedFrameBlenderSceneError(f"{label} must be a comma-separated x,y,z string")
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 3:
        raise ComposedFrameBlenderSceneError(f"{label} must contain exactly 3 comma-separated values")
    try:
        position = [float(part) for part in parts]
    except ValueError as exc:
        raise ComposedFrameBlenderSceneError(f"{label} contains non-numeric values") from exc
    if any(not math.isfinite(item) for item in position):
        raise ComposedFrameBlenderSceneError(f"{label} contains non-finite values")
    return position


def distance(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((b[index] - a[index]) ** 2 for index in range(3)))


def safe_name(value: Any) -> str:
    chars = [ch if ch.isalnum() or ch in {"_", "-", "."} else "_" for ch in str(value)]
    return "".join(chars).strip("_") or "item"


def frame_dir_name(frame_id: int) -> str:
    return f"frame_{frame_id:03d}"


def output_paths(output_root: Path, frame_id: int) -> tuple[Path, Path]:
    return (
        output_root / f"composed_frame_{frame_id:03d}_scene.blend",
        output_root / f"composed_frame_{frame_id:03d}_scene_inventory.json",
    )


def resolve_blender_or_raise(explicit: Path | None) -> Path:
    requested = None if explicit is None else resolve_path(explicit)
    try:
        return find_blender(requested)
    except RuntimeConfigError as exc:
        raise ComposedFrameBlenderSceneError(str(exc)) from exc


def validate_manifest(manifest_path: Path) -> dict[str, Any]:
    manifest = require_object(load_json(manifest_path, "composed frame manifest"), "composed frame manifest")
    entries = manifest.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ComposedFrameBlenderSceneError("composed manifest must contain a non-empty entries list")
    for index, raw_entry in enumerate(entries):
        entry = require_object(raw_entry, f"entries[{index}]")
        source = require_non_empty_string(entry.get("source"), f"entries[{index}].source")
        if source not in SUPPORTED_SOURCES:
            raise ComposedFrameBlenderSceneError(f"entries[{index}] has unsupported source={source!r}")
        if entry.get("baked_world_geometry") is not True:
            raise ComposedFrameBlenderSceneError(f"entries[{index}] must have baked_world_geometry == true")
        mesh_path = Path(require_non_empty_string(entry.get("mesh_path"), f"entries[{index}].mesh_path"))
        if not mesh_path.is_absolute():
            mesh_path = PROJECT_ROOT / mesh_path
        if not mesh_path.exists():
            raise ComposedFrameBlenderSceneError(f"entries[{index}] mesh_path does not exist: {mesh_path}")
    return manifest


def run_driver(args: argparse.Namespace) -> int:
    composed_manifest = resolve_path(args.composed_manifest)
    output_root = resolve_path(args.output_root)
    manifest = validate_manifest(composed_manifest)
    tx_position = parse_position(args.tx, "--tx")
    rx_position = parse_position(args.rx, "--rx")
    output_root.mkdir(parents=True, exist_ok=True)
    blender = resolve_blender_or_raise(args.blender)
    command = [
        str(blender),
        "--background",
        "--python",
        str(Path(__file__).resolve()),
        "--",
        "--blender-worker",
        "--composed-manifest",
        str(composed_manifest),
        "--output-root",
        str(output_root),
        "--tx",
        ",".join(f"{value:.12g}" for value in tx_position),
        "--rx",
        ",".join(f"{value:.12g}" for value in rx_position),
    ]
    if args.show_radio_markers:
        command.append("--show-radio-markers")
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
        raise ComposedFrameBlenderSceneError(f"Blender composed scene build failed with exit code {result.returncode}")
    return 0


def import_ply(filepath: Path) -> list[Any]:
    import bpy

    before = {obj.as_pointer() for obj in bpy.data.objects}
    if hasattr(bpy.ops.wm, "ply_import"):
        bpy.ops.wm.ply_import(filepath=str(filepath))
    elif hasattr(bpy.ops.import_mesh, "ply"):
        bpy.ops.import_mesh.ply(filepath=str(filepath))
    else:
        raise ComposedFrameBlenderSceneError("Blender PLY importer is not available")
    imported = [obj for obj in bpy.data.objects if obj.as_pointer() not in before and obj.type == "MESH"]
    if not imported:
        raise ComposedFrameBlenderSceneError(f"No mesh objects imported from {filepath}")
    return imported


def link_to_collection(obj: Any, collection: Any) -> None:
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


def add_radio_markers(
    *,
    tx_position: list[float],
    rx_position: list[float],
    collection: Any,
    tx_material: Any,
    rx_material: Any,
    line_material: Any,
) -> list[str]:
    import bpy

    names: list[str] = []
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=0.08, location=tuple(tx_position))
    tx = bpy.context.object
    tx.name = "tx_marker"
    tx.data.name = "tx_marker_mesh"
    tx.data.materials.append(tx_material)
    link_to_collection(tx, collection)
    names.append(tx.name)

    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=0.08, location=tuple(rx_position))
    rx = bpy.context.object
    rx.name = "rx_marker"
    rx.data.name = "rx_marker_mesh"
    rx.data.materials.append(rx_material)
    link_to_collection(rx, collection)
    names.append(rx.name)

    curve = bpy.data.curves.new("tx_rx_reference_line_curve", type="CURVE")
    curve.dimensions = "3D"
    curve.resolution_u = 1
    curve.bevel_depth = 0.01
    curve.bevel_resolution = 2
    polyline = curve.splines.new("POLY")
    polyline.points.add(1)
    polyline.points[0].co = (tx_position[0], tx_position[1], tx_position[2], 1.0)
    polyline.points[1].co = (rx_position[0], rx_position[1], rx_position[2], 1.0)
    line = bpy.data.objects.new("tx_rx_reference_line", curve)
    curve.materials.append(line_material)
    collection.objects.link(line)
    names.append(line.name)
    return names


def object_name_for_entry(entry: dict[str, Any], index: int) -> str:
    source = entry["source"]
    if source == "static":
        return f"static_{safe_name(entry.get('material_label'))}_{index:02d}"
    if source == "dynamic":
        return (
            f"dynamic_{safe_name(entry.get('model_name'))}_"
            f"{safe_name(entry.get('link_name'))}_{safe_name(entry.get('visual_name'))}"
        )
    if source == "actor":
        frame_id = entry.get("frame_id")
        suffix = frame_dir_name(int(frame_id)) if isinstance(frame_id, int) else "frame_unknown"
        return f"actor_{safe_name(entry.get('actor_name'))}_{suffix}"
    return f"unsupported_{safe_name(source)}_{index:02d}"


def run_blender_worker(args: argparse.Namespace) -> int:
    import bpy

    composed_manifest = resolve_path(args.composed_manifest)
    output_root = resolve_path(args.output_root)
    manifest = validate_manifest(composed_manifest)
    tx_position = parse_position(args.tx, "--tx")
    rx_position = parse_position(args.rx, "--rx")
    frame_id = int(manifest.get("frame_id", 0))
    source_sample_index = manifest.get("source_sample_index")
    blend_path, inventory_path = output_paths(output_root, frame_id)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.frame_start = frame_id
    scene.frame_end = frame_id
    scene.frame_set(frame_id)

    static_collection = bpy.data.collections.new("static_scene")
    dynamic_collection = bpy.data.collections.new("dynamic_panda_ur5")
    actor_collection = bpy.data.collections.new("actor_scene")
    scene.collection.children.link(static_collection)
    scene.collection.children.link(dynamic_collection)
    scene.collection.children.link(actor_collection)
    radio_collection = None
    if args.show_radio_markers:
        radio_collection = bpy.data.collections.new("radio_markers")
        scene.collection.children.link(radio_collection)

    materials = {
        "static": make_material("inspection_static_neutral", (0.55, 0.55, 0.55, 1.0)),
        "dynamic": make_material("inspection_dynamic_robot", (0.18, 0.42, 0.86, 1.0)),
        "actor": make_material("inspection_actor", (0.9, 0.32, 0.18, 1.0)),
        "tx": make_material("inspection_tx_marker", (0.0, 0.85, 0.15, 1.0)),
        "rx": make_material("inspection_rx_marker", (0.95, 0.1, 0.1, 1.0)),
        "radio_line": make_material("inspection_tx_rx_reference_line", (1.0, 0.9, 0.05, 1.0)),
    }
    collections = {
        "static": static_collection,
        "dynamic": dynamic_collection,
        "actor": actor_collection,
    }

    warnings: list[str] = []
    imported_names: dict[str, list[str]] = {"static": [], "dynamic": [], "actor": []}
    entries = manifest["entries"]
    per_source_index = {"static": 0, "dynamic": 0, "actor": 0}

    for global_index, entry in enumerate(entries):
        source = entry["source"]
        if source not in SUPPORTED_SOURCES:
            warnings.append(f"unsupported source ignored: {source}")
            continue
        mesh_path = Path(entry["mesh_path"])
        if not mesh_path.is_absolute():
            mesh_path = PROJECT_ROOT / mesh_path
        objects = import_ply(mesh_path)
        if len(objects) != 1:
            warnings.append(f"{entry.get('id')} imported as {len(objects)} mesh objects")
        if not entry.get("material_label"):
            warnings.append(f"{entry.get('id')} is missing optional material_label")
        object_base_name = object_name_for_entry(entry, per_source_index[source])
        per_source_index[source] += 1
        for object_index, obj in enumerate(objects):
            obj.name = object_base_name if object_index == 0 else f"{object_base_name}_{object_index:02d}"
            obj.data.name = f"{obj.name}_mesh"
            obj.data.materials.clear()
            obj.data.materials.append(materials[source])
            obj.location = (0.0, 0.0, 0.0)
            obj.rotation_euler = (0.0, 0.0, 0.0)
            obj.scale = (1.0, 1.0, 1.0)
            link_to_collection(obj, collections[source])
            imported_names[source].append(obj.name)

    actor_count = int(manifest.get("actor_count", len(imported_names["actor"])))
    dynamic_count = int(manifest.get("dynamic_count", len(imported_names["dynamic"])))
    if actor_count == 0:
        warnings.append("actor_count is 0")
    if dynamic_count != EXPECTED_DYNAMIC_COUNT:
        warnings.append(f"dynamic_count {dynamic_count} != expected {EXPECTED_DYNAMIC_COUNT}")

    imported_object_count = sum(len(names) for names in imported_names.values())
    marker_names: list[str] = []
    tx_rx_distance = distance(tx_position, rx_position)
    if args.show_radio_markers:
        if radio_collection is None:
            raise ComposedFrameBlenderSceneError("radio_markers collection was not created")
        marker_names = add_radio_markers(
            tx_position=tx_position,
            rx_position=rx_position,
            collection=radio_collection,
            tx_material=materials["tx"],
            rx_material=materials["rx"],
            line_material=materials["radio_line"],
        )
        for expected_name in ("tx_marker", "rx_marker", "tx_rx_reference_line"):
            if expected_name not in marker_names:
                raise ComposedFrameBlenderSceneError(f"Missing radio marker object: {expected_name}")

    inventory = {
        "generated_by": Path(__file__).name,
        "frame_id": frame_id,
        "source_sample_index": source_sample_index,
        "composed_manifest": str(composed_manifest),
        "blend_path": str(blend_path),
        "static_count": int(manifest.get("static_count", len(imported_names["static"]))),
        "dynamic_count": dynamic_count,
        "actor_count": actor_count,
        "total_count": int(manifest.get("total_count", len(entries))),
        "imported_object_count": imported_object_count,
        "imported_object_names_by_source": imported_names,
        "radio_markers_enabled": bool(args.show_radio_markers),
        "radio_marker_object_names": marker_names,
        "tx_position": tx_position,
        "rx_position": rx_position,
        "tx_rx_distance": tx_rx_distance,
        "missing_path_count": 0,
        "warning_count": len(warnings),
        "warnings": warnings,
    }
    save_json(inventory_path, inventory)
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

    print("Composed frame Blender inspection scene build")
    print(f"composed_manifest: {composed_manifest}")
    print(f"blend: {blend_path}")
    print(f"inventory: {inventory_path}")
    print(f"frame_id: {frame_id}")
    print(f"source_sample_index: {source_sample_index}")
    print(f"static_count: {inventory['static_count']}")
    print(f"dynamic_count: {inventory['dynamic_count']}")
    print(f"actor_count: {inventory['actor_count']}")
    print(f"total_count: {inventory['total_count']}")
    print(f"imported_object_count: {inventory['imported_object_count']}")
    print(f"radio_markers_enabled: {inventory['radio_markers_enabled']}")
    print(f"tx_position: {inventory['tx_position']}")
    print(f"rx_position: {inventory['rx_position']}")
    print(f"tx_rx_distance: {inventory['tx_rx_distance']}")
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
    except ComposedFrameBlenderSceneError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
