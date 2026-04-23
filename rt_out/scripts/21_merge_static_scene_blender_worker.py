#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any

import bpy
from mathutils import Matrix

REFLECTIVE_TABLE_MESH_RELATIVE = Path(
    "rt_out/static_scene/converted_meshes/models/furniture/"
    "Reflective table/meshes/Table.ply"
)
PICKING_SHELVES_SOURCE_RELATIVE = Path(
    "models/furniture/picking_shelves/base_visual.glb"
)
PICKING_SHELVES_CONVERTED_MESH_RELATIVE = Path(
    "rt_out/static_scene/converted_meshes/models/furniture/picking_shelves/base_visual.ply"
)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def slugify(text: str) -> str:
    out = []
    for ch in str(text):
        out.append(ch.lower() if ch.isalnum() else "_")
    slug = "".join(out)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "item"


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


def select_only(objects: list[bpy.types.Object]) -> None:
    ensure_object_mode()
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0] if objects else None


def recalc_normals_outside(obj: bpy.types.Object) -> None:
    if obj.type != "MESH" or not obj.data.polygons:
        return
    select_only([obj])
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.normals_make_consistent(inside=False)
    bpy.ops.object.mode_set(mode="OBJECT")


def detach_keep_world(obj: bpy.types.Object) -> None:
    matrix = obj.matrix_world.copy()
    obj.parent = None
    obj.matrix_world = matrix


def matrix44(value: Any) -> Matrix:
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError("to_world must be a 4x4 matrix")
    rows = []
    for row in value:
        if not isinstance(row, list) or len(row) != 4:
            raise ValueError("to_world must be a 4x4 matrix")
        rows.append([float(item) for item in row])
    return Matrix(rows)


def import_mesh(filepath: str) -> list[bpy.types.Object]:
    mesh_path = Path(filepath)
    ext = mesh_path.suffix.lower()
    before = {obj.as_pointer() for obj in bpy.data.objects}

    if ext == ".obj":
        if hasattr(bpy.ops.wm, "obj_import"):
            bpy.ops.wm.obj_import(
                filepath=str(mesh_path),
                forward_axis="Y",
                up_axis="Z",
            )
        elif hasattr(bpy.ops.import_scene, "obj"):
            bpy.ops.import_scene.obj(
                filepath=str(mesh_path),
                axis_forward="Y",
                axis_up="Z",
            )
        else:
            raise RuntimeError("Blender OBJ importer is not available")
    elif ext == ".ply":
        if hasattr(bpy.ops.wm, "ply_import"):
            bpy.ops.wm.ply_import(filepath=str(mesh_path))
        elif hasattr(bpy.ops.import_mesh, "ply"):
            bpy.ops.import_mesh.ply(filepath=str(mesh_path))
        else:
            raise RuntimeError("Blender PLY importer is not available")
    elif ext == ".dae":
        if hasattr(bpy.ops.wm, "collada_import"):
            bpy.ops.wm.collada_import(filepath=str(mesh_path))
        else:
            raise RuntimeError("Blender COLLADA importer is not available")
    elif ext in {".glb", ".gltf"}:
        bpy.ops.import_scene.gltf(filepath=str(mesh_path))
    elif ext == ".stl":
        bpy.ops.wm.stl_import(filepath=str(mesh_path))
    else:
        raise RuntimeError(f"Unsupported mesh extension: {ext}")

    imported = [
        obj
        for obj in bpy.data.objects
        if obj.as_pointer() not in before and obj.type == "MESH"
    ]
    if not imported:
        imported = [obj for obj in bpy.context.selected_objects if obj.type == "MESH"]
    if not imported:
        raise RuntimeError(f"No mesh objects were imported from {mesh_path}")
    return imported


def export_selected_ply(filepath: Path) -> None:
    filepath.parent.mkdir(parents=True, exist_ok=True)

    if hasattr(bpy.ops.wm, "ply_export"):
        bpy.ops.wm.ply_export(
            filepath=str(filepath),
            export_selected_objects=True,
            apply_modifiers=True,
            export_normals=True,
            export_uv=False,
            ascii_format=False,
        )
        return

    if hasattr(bpy.ops.export_mesh, "ply"):
        bpy.ops.export_mesh.ply(
            filepath=str(filepath),
            use_selection=True,
            use_mesh_modifiers=True,
            use_normals=True,
            use_uv_coords=False,
            use_colors=False,
        )
        return

    raise RuntimeError("Blender PLY exporter is not available")


def triangulate_object(obj: bpy.types.Object) -> None:
    select_only([obj])
    modifier = obj.modifiers.new(name="Triangulate", type="TRIANGULATE")
    bpy.ops.object.modifier_apply(modifier=modifier.name)


def apply_world_transform(obj: bpy.types.Object, transform: Matrix) -> None:
    detach_keep_world(obj)
    obj.matrix_world = transform @ obj.matrix_world
    bpy.context.view_layer.update()
    select_only([obj])
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)


def local_correction_for_entry(
    entry: dict[str, Any],
    reflective_table_mesh_path: Path,
    picking_shelves_source_path: Path,
    picking_shelves_converted_mesh_path: Path,
) -> Matrix:
    resolved_path_raw = entry.get("resolved_path")
    resolved_path = (
        Path(str(resolved_path_raw)).expanduser().resolve()
        if isinstance(resolved_path_raw, str) and resolved_path_raw.strip()
        else None
    )
    scene_mesh_path = (
        Path(str(entry.get("scene_mesh_path", ""))).expanduser().resolve()
    )
    if scene_mesh_path == reflective_table_mesh_path:
        return Matrix.Rotation(-1.5707963267948966, 4, "X")
    if (
        resolved_path == picking_shelves_source_path
        or scene_mesh_path == picking_shelves_converted_mesh_path
    ):
        # The shelf mesh imports with its 1.905 m extent along local Y, but the SDF
        # collision stack shows the shelf height belongs on +Z. Rotate the mesh -90 deg
        # around local X here, before the normal world placement, so the fix stays
        # asset-local and does not contaminate the general transform chain.
        return Matrix.Rotation(-1.5707963267948966, 4, "X")
    return Matrix.Identity(4)


def create_box(size: list[float]) -> list[bpy.types.Object]:
    bpy.ops.mesh.primitive_cube_add(size=2.0, location=(0.0, 0.0, 0.0))
    obj = bpy.context.active_object
    obj.scale = (size[0] / 2.0, size[1] / 2.0, size[2] / 2.0)
    bpy.context.view_layer.update()
    return [obj]


def create_cylinder(radius: float, length: float) -> list[bpy.types.Object]:
    bpy.ops.mesh.primitive_cylinder_add(
        vertices=32,
        radius=radius,
        depth=length,
        location=(0.0, 0.0, 0.0),
    )
    return [bpy.context.active_object]


def create_sphere(radius: float) -> list[bpy.types.Object]:
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=32,
        ring_count=16,
        radius=radius,
        location=(0.0, 0.0, 0.0),
    )
    return [bpy.context.active_object]


def create_entry_objects(entry: dict[str, Any]) -> list[bpy.types.Object]:
    geometry_type = entry["geometry_type"]
    if geometry_type == "mesh":
        return import_mesh(entry["scene_mesh_path"])
    if geometry_type == "box":
        return create_box(entry["size"])
    if geometry_type == "cylinder":
        return create_cylinder(float(entry["radius"]), float(entry["length"]))
    if geometry_type == "sphere":
        return create_sphere(float(entry["radius"]))
    raise RuntimeError(f"Unsupported geometry_type={geometry_type}")


def join_objects(objects: list[bpy.types.Object], name: str) -> bpy.types.Object:
    if not objects:
        raise RuntimeError(f"No objects available to join for {name}")

    if len(objects) == 1:
        obj = objects[0]
        obj.name = name
        obj.data.name = f"{name}_mesh"
        return obj

    select_only(objects)
    bpy.ops.object.join()
    obj = bpy.context.active_object
    obj.name = name
    obj.data.name = f"{name}_mesh"
    return obj


def prepare_entry_object(
    entry: dict[str, Any],
    individual_dir: Path | None,
    reflective_table_mesh_path: Path,
    picking_shelves_source_path: Path,
    picking_shelves_converted_mesh_path: Path,
) -> bpy.types.Object:
    created_objects = create_entry_objects(entry)
    world_matrix = matrix44(entry["to_world"]) @ local_correction_for_entry(
        entry,
        reflective_table_mesh_path,
        picking_shelves_source_path,
        picking_shelves_converted_mesh_path,
    )

    prepared_objects: list[bpy.types.Object] = []
    for obj in created_objects:
        if obj.type != "MESH":
            continue
        apply_world_transform(obj, world_matrix)
        triangulate_object(obj)
        prepared_objects.append(obj)

    if not prepared_objects:
        raise RuntimeError(f"Entry {entry['id']} produced no mesh objects")

    entry_object = join_objects(prepared_objects, slugify(entry["id"]))
    triangulate_object(entry_object)
    recalc_normals_outside(entry_object)

    if individual_dir is not None:
        individual_path = individual_dir / f"{slugify(entry['id'])}.ply"
        select_only([entry_object])
        export_selected_ply(individual_path)

    return entry_object


def process_material_group(
    *,
    material_class: str,
    entries: list[dict[str, Any]],
    merged_dir: Path,
    individual_dir: Path | None,
    reflective_table_mesh_path: Path,
    picking_shelves_source_path: Path,
    picking_shelves_converted_mesh_path: Path,
) -> dict[str, Any]:
    clear_scene()

    entry_objects: list[bpy.types.Object] = []
    for entry in entries:
        entry_objects.append(
            prepare_entry_object(
                entry,
                individual_dir,
                reflective_table_mesh_path,
                picking_shelves_source_path,
                picking_shelves_converted_mesh_path,
            )
        )

    group_name = f"merged_{slugify(material_class)}"
    merged_object = join_objects(entry_objects, group_name)
    triangulate_object(merged_object)
    recalc_normals_outside(merged_object)

    output_path = merged_dir / f"{slugify(material_class)}.ply"
    select_only([merged_object])
    export_selected_ply(output_path)

    return {
        "material_class": material_class,
        "entry_count": len(entries),
        "merged_mesh_path": str(output_path.resolve()),
        "vertex_count": len(merged_object.data.vertices),
        "triangle_count": len(merged_object.data.polygons),
        "entry_ids": [entry["id"] for entry in entries],
    }


def parse_job_args() -> tuple[Path, Path]:
    argv = sys.argv
    if "--" not in argv:
        raise SystemExit(
            "Usage: blender --background --python 21_merge_static_scene_blender_worker.py -- job.json result.json"
        )

    args = argv[argv.index("--") + 1 :]
    if len(args) != 2:
        raise SystemExit("Expected 2 arguments: job.json result.json")

    return Path(args[0]).expanduser().resolve(), Path(args[1]).expanduser().resolve()


def main() -> None:
    job_path, result_path = parse_job_args()
    payload = load_json(job_path)
    if not isinstance(payload, dict):
        raise RuntimeError("Merge job must be a JSON object")

    root = (
        Path(str(payload.get("root", Path(__file__).resolve().parents[2])))
        .expanduser()
        .resolve()
    )
    reflective_table_mesh_path = (root / REFLECTIVE_TABLE_MESH_RELATIVE).resolve()
    picking_shelves_source_path = (root / PICKING_SHELVES_SOURCE_RELATIVE).resolve()
    picking_shelves_converted_mesh_path = (
        root / PICKING_SHELVES_CONVERTED_MESH_RELATIVE
    ).resolve()

    output = payload.get("output", {})
    if not isinstance(output, dict):
        raise RuntimeError("Merge job output block must be an object")

    merged_dir_raw = output.get("merged_dir")
    if not merged_dir_raw:
        raise RuntimeError("Merge job is missing output.merged_dir")
    merged_dir = Path(str(merged_dir_raw)).expanduser().resolve()
    merged_dir.mkdir(parents=True, exist_ok=True)

    individual_dir_raw = output.get("individual_dir")
    individual_dir = None
    if individual_dir_raw:
        individual_dir = Path(str(individual_dir_raw)).expanduser().resolve()
        individual_dir.mkdir(parents=True, exist_ok=True)

    material_groups = payload.get("material_groups", [])
    if not isinstance(material_groups, list):
        raise RuntimeError("Merge job must contain material_groups list")

    result: dict[str, Any] = {
        "ok": False,
        "summary": {
            "material_groups_requested": len(material_groups),
            "material_groups_exported": 0,
            "exported_individual_meshes": 0,
        },
        "groups": [],
        "errors": [],
    }

    try:
        for raw_group in material_groups:
            if not isinstance(raw_group, dict):
                raise RuntimeError("Each material group must be an object")

            material_class = str(raw_group.get("material_class", "")).strip()
            entries = raw_group.get("entries", [])
            if not material_class:
                raise RuntimeError("Material group is missing material_class")
            if not isinstance(entries, list) or not entries:
                raise RuntimeError(
                    f"Material group {material_class!r} must contain a non-empty entries list"
                )

            group_result = process_material_group(
                material_class=material_class,
                entries=entries,
                merged_dir=merged_dir,
                individual_dir=individual_dir,
                reflective_table_mesh_path=reflective_table_mesh_path,
                picking_shelves_source_path=picking_shelves_source_path,
                picking_shelves_converted_mesh_path=picking_shelves_converted_mesh_path,
            )
            result["groups"].append(group_result)
            result["summary"]["material_groups_exported"] += 1
            if individual_dir is not None:
                result["summary"]["exported_individual_meshes"] += len(entries)

        result["ok"] = True
        save_json(result_path, result)
    except Exception as exc:
        result["errors"].append(
            {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
        save_json(result_path, result)
        raise


if __name__ == "__main__":
    main()
