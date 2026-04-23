#!/usr/bin/env python3

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dynamic_prototype_config import load_dynamic_prototype_config


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DYNAMIC_VISUAL_FRAMES_PATH = PROJECT_ROOT / "rt_out" / "dynamic_frames" / "dynamic_visual_frames.json"
DEFAULT_DYNAMIC_OUTPUT_ROOT = PROJECT_ROOT / "rt_out" / "dynamic_scene"
CACHE_DIR = DEFAULT_DYNAMIC_OUTPUT_ROOT / "converted_mesh_cache"

PROTOTYPE_CONFIG = load_dynamic_prototype_config()
MODEL_ORDER = PROTOTYPE_CONFIG["model_names"]
EXPECTED_SOURCE_SAMPLE_BY_FRAME = PROTOTYPE_CONFIG["source_sample_by_frame"]
EXPECTED_RENDERABLE_VISUALS = PROTOTYPE_CONFIG["expected_renderable_visual_count_total"]
EXPECTED_PER_MODEL_COUNTS = {
    model_name: model_config["expected_renderable_visual_count"]
    for model_name, model_config in PROTOTYPE_CONFIG["dynamic_models"].items()
}


class DynamicGeometryExportError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExportConfig:
    frame_id: int
    source_sample_index: int
    output_root: Path
    frame_output_root: Path
    raw_mesh_dir: Path
    output_manifest_path: Path


def frame_dir_name(frame_id: int) -> str:
    return f"frame_{frame_id:03d}"


def default_source_sample_index(frame_id: int) -> int:
    try:
        return EXPECTED_SOURCE_SAMPLE_BY_FRAME[frame_id]
    except KeyError as exc:
        known = ", ".join(str(item) for item in sorted(EXPECTED_SOURCE_SAMPLE_BY_FRAME))
        raise DynamicGeometryExportError(
            f"Unsupported frame_id={frame_id}. This prototype exporter only supports frames: {known}"
        ) from exc


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export dynamic-only transformed visual meshes for one prototype frame."
    )
    parser.add_argument("--frame-id", type=int, default=0, help="Prototype frame id to export")
    parser.add_argument(
        "--source-sample-index",
        type=int,
        default=None,
        help="Expected source sample index for the selected frame",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_DYNAMIC_OUTPUT_ROOT,
        help="Base directory for frame_XXX dynamic exports",
    )
    parser.add_argument("--blender-worker", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def build_config(args: argparse.Namespace) -> ExportConfig:
    expected_source_sample_index = default_source_sample_index(args.frame_id)
    source_sample_index = (
        expected_source_sample_index
        if args.source_sample_index is None
        else int(args.source_sample_index)
    )
    if source_sample_index != expected_source_sample_index:
        raise DynamicGeometryExportError(
            f"frame_id={args.frame_id} must use source_sample_index="
            f"{expected_source_sample_index}, got {source_sample_index}"
        )

    output_root = args.output_root.expanduser().resolve()
    frame_output_root = output_root / frame_dir_name(args.frame_id)
    raw_mesh_dir = frame_output_root / "raw_visual_meshes"
    output_manifest_path = (
        frame_output_root / f"dynamic_frame_{args.frame_id:03d}_manifest.json"
    )
    return ExportConfig(
        frame_id=args.frame_id,
        source_sample_index=source_sample_index,
        output_root=output_root,
        frame_output_root=frame_output_root,
        raw_mesh_dir=raw_mesh_dir,
        output_manifest_path=output_manifest_path,
    )


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise DynamicGeometryExportError(f"Missing input file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise DynamicGeometryExportError(f"Invalid JSON in {path}: {exc}") from exc


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def script_args() -> list[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return sys.argv[1:]


def safe_filename(value: str) -> str:
    chars = []
    for ch in value:
        chars.append(ch if ch.isalnum() or ch in {"_", "-", "."} else "_")
    name = "".join(chars).strip("_")
    return name or "visual"


def parse_matrix44(value: Any, label: str) -> list[list[float]]:
    if not isinstance(value, list) or len(value) != 4:
        raise DynamicGeometryExportError(f"{label} must be a 4x4 matrix")

    rows: list[list[float]] = []
    for row_index, row in enumerate(value):
        if not isinstance(row, list) or len(row) != 4:
            raise DynamicGeometryExportError(f"{label}[{row_index}] must contain 4 values")
        try:
            rows.append([float(item) for item in row])
        except (TypeError, ValueError) as exc:
            raise DynamicGeometryExportError(f"{label}[{row_index}] contains non-numeric data") from exc
    return rows


def parse_vec3(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 3:
        raise DynamicGeometryExportError(f"{label} must contain 3 values")
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise DynamicGeometryExportError(f"{label} contains non-numeric data") from exc


def matmul4(a: list[list[float]], b: list[list[float]]) -> list[list[float]]:
    return [
        [sum(a[row][k] * b[k][col] for k in range(4)) for col in range(4)]
        for row in range(4)
    ]


def scale_matrix(scale_xyz: list[float]) -> list[list[float]]:
    sx, sy, sz = scale_xyz
    return [
        [sx, 0.0, 0.0, 0.0],
        [0.0, sy, 0.0, 0.0],
        [0.0, 0.0, sz, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def validate_frame_visuals(data: dict[str, Any], config: ExportConfig) -> list[dict[str, Any]]:
    frames = data.get("frames")
    if not isinstance(frames, list):
        raise DynamicGeometryExportError("dynamic_visual_frames.json must contain frames list")

    frame = None
    for candidate in frames:
        if isinstance(candidate, dict) and candidate.get("frame_id") == config.frame_id:
            frame = candidate
            break

    if frame is None:
        raise DynamicGeometryExportError(
            f"Missing frame_id {config.frame_id} in dynamic_visual_frames.json"
        )
    if frame.get("source_sample_index") != config.source_sample_index:
        raise DynamicGeometryExportError(
            f"Frame {config.frame_id} has source_sample_index="
            f"{frame.get('source_sample_index')}, expected {config.source_sample_index}"
        )

    visuals = frame.get("renderable_visuals")
    if not isinstance(visuals, list):
        raise DynamicGeometryExportError(
            f"Frame {config.frame_id} must contain renderable_visuals list"
        )
    if len(visuals) != EXPECTED_RENDERABLE_VISUALS:
        raise DynamicGeometryExportError(
            f"Frame {config.frame_id} expected {EXPECTED_RENDERABLE_VISUALS} renderable "
            f"visuals, got {len(visuals)}"
        )

    per_model = {model_name: 0 for model_name in MODEL_ORDER}
    seen_ids: set[str] = set()
    validated: list[dict[str, Any]] = []

    for index, visual in enumerate(visuals):
        if not isinstance(visual, dict):
            raise DynamicGeometryExportError(f"renderable_visuals[{index}] is not an object")

        visual_id = visual.get("id")
        if not isinstance(visual_id, str) or not visual_id:
            raise DynamicGeometryExportError(f"renderable_visuals[{index}] missing id")
        if visual_id in seen_ids:
            raise DynamicGeometryExportError(
                f"Duplicate visual id in frame {config.frame_id}: {visual_id}"
            )
        seen_ids.add(visual_id)

        model_name = visual.get("model_name")
        if model_name not in per_model:
            raise DynamicGeometryExportError(f"Unexpected model for {visual_id}: {model_name!r}")
        per_model[model_name] += 1

        if visual.get("frame_id") != config.frame_id:
            raise DynamicGeometryExportError(f"{visual_id} has wrong frame_id")
        if visual.get("source_sample_index") != config.source_sample_index:
            raise DynamicGeometryExportError(f"{visual_id} has wrong source_sample_index")
        if visual.get("geometry_type") != "mesh":
            raise DynamicGeometryExportError(f"{visual_id} is not mesh geometry")
        if visual.get("has_visuals") is not True:
            raise DynamicGeometryExportError(f"{visual_id} is not marked renderable")

        source_mesh_path = visual.get("resolved_source_path")
        if not isinstance(source_mesh_path, str) or not source_mesh_path:
            raise DynamicGeometryExportError(f"{visual_id} missing resolved_source_path")
        if not Path(source_mesh_path).exists():
            raise DynamicGeometryExportError(
                f"{visual_id} source mesh does not exist: {source_mesh_path}"
            )

        link_to_world = parse_matrix44(visual.get("link_to_world"), f"{visual_id}.link_to_world")
        visual_pose_matrix = parse_matrix44(
            visual.get("visual_pose_matrix"),
            f"{visual_id}.visual_pose_matrix",
        )
        scale_xyz = parse_vec3(visual.get("scale_xyz"), f"{visual_id}.scale_xyz")
        final_transform = matmul4(matmul4(link_to_world, visual_pose_matrix), scale_matrix(scale_xyz))

        enriched = dict(visual)
        enriched["final_transform"] = final_transform
        validated.append(enriched)

    if per_model != EXPECTED_PER_MODEL_COUNTS:
        raise DynamicGeometryExportError(
            f"Expected per-model counts {EXPECTED_PER_MODEL_COUNTS}, got {per_model}"
        )

    return validated


def cache_path_for_source(source_path: Path) -> Path:
    digest = hashlib.sha1(str(source_path).encode("utf-8")).hexdigest()[:12]
    return CACHE_DIR / f"{safe_filename(source_path.stem)}__{digest}.ply"


def blender_executable() -> Path:
    env_path = os.environ.get("BLENDER")
    candidates = []
    if env_path:
        candidates.append(Path(env_path))

    which_path = shutil.which("blender")
    if which_path:
        candidates.append(Path(which_path))

    candidates.append(PROJECT_ROOT / "blender-4.5.8-linux-x64" / "blender")
    candidates.append(PROJECT_ROOT.parent / "blender-4.5.8-linux-x64" / "blender")
    candidates.append(Path.home() / "Documents" / "blender-4.5.8-linux-x64" / "blender")

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()

    raise DynamicGeometryExportError(
        "Could not find Blender executable. Set BLENDER, put blender on PATH, "
        f"or place it under {PROJECT_ROOT / 'blender-4.5.8-linux-x64'}."
    )


def run_driver(config: ExportConfig) -> int:
    data = load_json(DYNAMIC_VISUAL_FRAMES_PATH)
    if not isinstance(data, dict):
        raise DynamicGeometryExportError("dynamic_visual_frames.json root must be an object")
    validate_frame_visuals(data, config)

    blender = blender_executable()
    command = [
        str(blender),
        "--background",
        "--python",
        str(Path(__file__).resolve()),
        "--",
        "--blender-worker",
        "--frame-id",
        str(config.frame_id),
        "--source-sample-index",
        str(config.source_sample_index),
        "--output-root",
        str(config.output_root),
    ]
    result = subprocess.run(
        command,
        cwd=str(PROJECT_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        raise DynamicGeometryExportError(f"Blender export failed with exit code {result.returncode}")

    manifest = load_json(config.output_manifest_path)
    validation = manifest.get("validation", {})
    exported_visuals = manifest.get("exported_visuals", [])
    per_model = {model_name: 0 for model_name in MODEL_ORDER}
    for visual in exported_visuals:
        per_model[visual["model_name"]] += 1

    print(f"Dynamic frame-{config.frame_id} geometry export")
    print(f"Frame: {manifest.get('frame_id')}")
    print(f"Source sample: {manifest.get('source_sample_index')}")
    print(f"Renderable visuals expected: {validation.get('expected_renderable_visuals')}")
    print(f"Renderable visuals exported: {validation.get('exported_renderable_visuals')}")
    print(f"Failed exports: {validation.get('failed_exports')}")
    for model_name in MODEL_ORDER:
        print(f"{model_name} exported = {per_model[model_name]}")
    print(f"Output manifest: {config.output_manifest_path}")
    print(f"Output meshes: {config.raw_mesh_dir}")
    return 0


def run_blender_worker(config: ExportConfig) -> int:
    import bpy
    from mathutils import Matrix

    def ensure_object_mode() -> None:
        if bpy.context.mode != "OBJECT":
            bpy.ops.object.mode_set(mode="OBJECT")

    def clear_scene() -> None:
        ensure_object_mode()
        bpy.ops.object.select_all(action="SELECT")
        bpy.ops.object.delete(use_global=False)
        if hasattr(bpy.ops.outliner, "orphans_purge"):
            bpy.ops.outliner.orphans_purge(
                do_local_ids=True,
                do_linked_ids=True,
                do_recursive=True,
            )

    def select_only(objects: list[Any]) -> None:
        ensure_object_mode()
        bpy.ops.object.select_all(action="DESELECT")
        for obj in objects:
            obj.select_set(True)
        bpy.context.view_layer.objects.active = objects[0] if objects else None

    def detach_keep_world(obj: Any) -> None:
        matrix = obj.matrix_world.copy()
        obj.parent = None
        obj.matrix_world = matrix

    def matrix44(value: Any) -> Matrix:
        return Matrix(parse_matrix44(value, "matrix"))

    def import_mesh(filepath: Path) -> list[Any]:
        before = {obj.as_pointer() for obj in bpy.data.objects}
        ext = filepath.suffix.lower()

        if ext == ".dae":
            if not hasattr(bpy.ops.wm, "collada_import"):
                raise DynamicGeometryExportError("Blender COLLADA importer is not available")
            bpy.ops.wm.collada_import(filepath=str(filepath))
        elif ext == ".ply":
            if hasattr(bpy.ops.wm, "ply_import"):
                bpy.ops.wm.ply_import(filepath=str(filepath))
            elif hasattr(bpy.ops.import_mesh, "ply"):
                bpy.ops.import_mesh.ply(filepath=str(filepath))
            else:
                raise DynamicGeometryExportError("Blender PLY importer is not available")
        elif ext == ".obj":
            if hasattr(bpy.ops.wm, "obj_import"):
                bpy.ops.wm.obj_import(filepath=str(filepath), forward_axis="Y", up_axis="Z")
            elif hasattr(bpy.ops.import_scene, "obj"):
                bpy.ops.import_scene.obj(filepath=str(filepath), axis_forward="Y", axis_up="Z")
            else:
                raise DynamicGeometryExportError("Blender OBJ importer is not available")
        elif ext in {".glb", ".gltf"}:
            bpy.ops.import_scene.gltf(filepath=str(filepath))
        elif ext == ".stl":
            bpy.ops.wm.stl_import(filepath=str(filepath))
        else:
            raise DynamicGeometryExportError(f"Unsupported mesh extension: {ext}")

        imported = [
            obj
            for obj in bpy.data.objects
            if obj.as_pointer() not in before and obj.type == "MESH"
        ]
        if not imported:
            raise DynamicGeometryExportError(f"No mesh objects imported from {filepath}")
        return imported

    def triangulate_object(obj: Any) -> None:
        if obj.type != "MESH":
            return
        select_only([obj])
        modifier = obj.modifiers.new(name="Triangulate", type="TRIANGULATE")
        bpy.ops.object.modifier_apply(modifier=modifier.name)

    def recalc_normals_outside(obj: Any) -> None:
        if obj.type != "MESH" or not obj.data.polygons:
            return
        select_only([obj])
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.normals_make_consistent(inside=False)
        bpy.ops.object.mode_set(mode="OBJECT")

    def apply_transform(obj: Any, transform: Matrix) -> None:
        detach_keep_world(obj)
        obj.matrix_world = transform @ obj.matrix_world
        bpy.context.view_layer.update()
        select_only([obj])
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    def export_selected_ply(path: Path) -> None:
        if hasattr(bpy.ops.wm, "ply_export"):
            op = bpy.ops.wm.ply_export
            props = op.get_rna_type().properties
            kwargs: dict[str, Any] = {"filepath": str(path)}
            if "export_selected_objects" in props:
                kwargs["export_selected_objects"] = True
            if "apply_modifiers" in props:
                kwargs["apply_modifiers"] = True
            if "export_normals" in props:
                kwargs["export_normals"] = True
            if "export_uv" in props:
                kwargs["export_uv"] = False
            if "ascii_format" in props:
                kwargs["ascii_format"] = False
            if "export_colors" in props:
                prop = props["export_colors"]
                if prop.type == "BOOLEAN":
                    kwargs["export_colors"] = False
                elif prop.type == "ENUM":
                    enum_ids = [item.identifier for item in prop.enum_items]
                    kwargs["export_colors"] = "NONE" if "NONE" in enum_ids else enum_ids[0]
            op(**kwargs)
            return

        if hasattr(bpy.ops.export_mesh, "ply"):
            bpy.ops.export_mesh.ply(
                filepath=str(path),
                use_selection=True,
                use_mesh_modifiers=True,
                use_normals=True,
                use_uv_coords=False,
                use_colors=False,
            )
            return

        raise DynamicGeometryExportError("Blender PLY exporter is not available")

    def bake_source_cache(source_path: Path, cache_path: Path) -> None:
        if cache_path.exists() and cache_path.stat().st_size > 0:
            return

        clear_scene()
        objects = import_mesh(source_path)
        prepared = []
        for obj in objects:
            detach_keep_world(obj)
            select_only([obj])
            bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
            triangulate_object(obj)
            recalc_normals_outside(obj)
            prepared.append(obj)

        if not prepared:
            raise DynamicGeometryExportError(f"Source cache import produced no mesh objects: {source_path}")

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        select_only(prepared)
        export_selected_ply(cache_path)
        if not cache_path.exists() or cache_path.stat().st_size <= 0:
            raise DynamicGeometryExportError(f"Failed to write source cache: {cache_path}")

    def mesh_stats(objects: list[Any]) -> dict[str, Any]:
        vertices = []
        vertex_count = 0
        face_count = 0
        for obj in objects:
            if obj.type != "MESH":
                continue
            vertex_count += len(obj.data.vertices)
            face_count += len(obj.data.polygons)
            for vertex in obj.data.vertices:
                world_coord = obj.matrix_world @ vertex.co
                vertices.append([float(world_coord.x), float(world_coord.y), float(world_coord.z)])

        if vertex_count <= 0 or face_count <= 0 or not vertices:
            raise DynamicGeometryExportError("Exported mesh is empty")

        bounds_min = [min(vertex[axis] for vertex in vertices) for axis in range(3)]
        bounds_max = [max(vertex[axis] for vertex in vertices) for axis in range(3)]
        for value in bounds_min + bounds_max:
            if not math.isfinite(value):
                raise DynamicGeometryExportError("Exported mesh bounds are not finite")

        return {
            "mesh_vertex_count": vertex_count,
            "mesh_face_count": face_count,
            "bounds_min": bounds_min,
            "bounds_max": bounds_max,
        }

    def export_visual(visual: dict[str, Any]) -> dict[str, Any]:
        visual_id = visual["id"]
        source_path = Path(visual["resolved_source_path"]).resolve()
        cache_path = cache_path_for_source(source_path)
        bake_source_cache(source_path, cache_path)

        clear_scene()
        objects = import_mesh(cache_path)
        transform = matrix44(visual["final_transform"])
        for obj in objects:
            apply_transform(obj, transform)
            triangulate_object(obj)
            recalc_normals_outside(obj)

        stats = mesh_stats(objects)
        exported_mesh_path = config.raw_mesh_dir / f"{safe_filename(visual_id)}.ply"
        exported_mesh_path.parent.mkdir(parents=True, exist_ok=True)
        select_only(objects)
        export_selected_ply(exported_mesh_path)
        if not exported_mesh_path.exists() or exported_mesh_path.stat().st_size <= 0:
            raise DynamicGeometryExportError(f"Failed to write transformed mesh: {exported_mesh_path}")

        return {
            "id": visual_id,
            "model_name": visual["model_name"],
            "link_name": visual["link_name"],
            "visual_name": visual["visual_name"],
            "source_sample_index": visual["source_sample_index"],
            "frame_id": visual["frame_id"],
            "source_mesh_path": str(source_path),
            "cached_source_mesh_path": str(cache_path),
            "exported_mesh_path": str(exported_mesh_path),
            "geometry_type": visual["geometry_type"],
            "link_to_world": visual["link_to_world"],
            "visual_pose_matrix": visual["visual_pose_matrix"],
            "scale_xyz": visual["scale_xyz"],
            "final_transform": visual["final_transform"],
            "export_success": True,
            **stats,
        }

    data = load_json(DYNAMIC_VISUAL_FRAMES_PATH)
    if not isinstance(data, dict):
        raise DynamicGeometryExportError("dynamic_visual_frames.json root must be an object")
    visuals = validate_frame_visuals(data, config)

    config.raw_mesh_dir.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for stale_path in config.raw_mesh_dir.glob("*.ply"):
        stale_path.unlink()

    exported = [export_visual(visual) for visual in visuals]

    actual_files = sorted(config.raw_mesh_dir.glob("*.ply"))
    if len(actual_files) != EXPECTED_RENDERABLE_VISUALS:
        raise DynamicGeometryExportError(
            f"Expected {EXPECTED_RENDERABLE_VISUALS} transformed PLY files, got {len(actual_files)}"
        )
    for entry in exported:
        path = Path(entry["exported_mesh_path"])
        if not path.exists() or path.stat().st_size <= 0:
            raise DynamicGeometryExportError(f"Missing or empty exported mesh: {path}")

    manifest = {
        "generated_by": Path(__file__).name,
        "source_visual_frames_file": "rt_out/dynamic_frames/dynamic_visual_frames.json",
        "frame_id": config.frame_id,
        "source_sample_index": config.source_sample_index,
        "output_mesh_dir": str(config.raw_mesh_dir),
        "converted_mesh_cache_dir": str(CACHE_DIR),
        "exported_visuals": exported,
        "validation": {
            "frame_id": config.frame_id,
            "source_sample_index": config.source_sample_index,
            "expected_renderable_visuals": EXPECTED_RENDERABLE_VISUALS,
            "exported_renderable_visuals": len(exported),
            "failed_exports": 0,
            "actual_ply_file_count": len(actual_files),
            "warnings": [],
        },
    }
    save_json(config.output_manifest_path, manifest)
    return 0


def main() -> int:
    args = parse_args(script_args())
    config = build_config(args)
    if args.blender_worker:
        return run_blender_worker(config)
    return run_driver(config)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except DynamicGeometryExportError as exc:
        print(f"ERROR: {exc}")
        raise SystemExit(1)
