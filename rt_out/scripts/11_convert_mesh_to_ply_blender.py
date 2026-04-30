"""Blender-side helper that converts a generic mesh asset into PLY.

Compared with the DAE-specific helper, this version is used for mesh sources
that may arrive in different formats but still need the same import, cleanup,
and export flow before entering the RT pipeline.
"""

import sys
from pathlib import Path
import bpy

def clear_scene():
    """Remove previously loaded Blender objects before importing the next mesh."""
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    if hasattr(bpy.ops.outliner, "orphans_purge"):
        bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)

def import_mesh(filepath: str):
    """Import one supported mesh asset based on its file extension."""
    ext = Path(filepath).suffix.lower()

    if ext == ".dae":
        if hasattr(bpy.ops.wm, "collada_import"):
            bpy.ops.wm.collada_import(filepath=filepath)
        else:
            raise RuntimeError("Няма COLLADA importer в този Blender.")
    elif ext in {".glb", ".gltf"}:
        bpy.ops.import_scene.gltf(filepath=filepath)
    elif ext == ".stl":
        bpy.ops.wm.stl_import(filepath=filepath)
    else:
        raise RuntimeError(f"Неподдържано разширение: {ext}")

def export_ply(filepath: str):
    """Export the selected mesh objects to one PLY file."""
    if hasattr(bpy.ops.wm, "ply_export"):
        bpy.ops.wm.ply_export(
            filepath=filepath,
            export_selected_objects=True,
            apply_modifiers=True,
            export_normals=True,
            export_uv=False,
            ascii_format=False
        )
    elif hasattr(bpy.ops.export_mesh, "ply"):
        bpy.ops.export_mesh.ply(
            filepath=filepath,
            use_selection=True,
            use_mesh_modifiers=True,
            use_normals=True,
            use_uv_coords=False,
            use_colors=False
        )
    else:
        raise RuntimeError("Не е намерен PLY exporter.")

def main():
    """Load one mesh file, keep imported mesh objects selected, and export PLY."""
    argv = sys.argv
    if "--" not in argv:
        raise SystemExit("Използване: blender --background --python 11_convert_mesh_to_ply_blender.py -- input_mesh output.ply")

    args = argv[argv.index("--") + 1:]
    if len(args) != 2:
        raise SystemExit("Трябват 2 аргумента: input_mesh output.ply")

    input_path = Path(args[0]).expanduser().resolve()
    output_path = Path(args[1]).expanduser().resolve()

    if not input_path.exists():
        raise SystemExit(f"Липсва входен файл: {input_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    clear_scene()
    import_mesh(str(input_path))

    mesh_objects = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    if not mesh_objects:
        raise SystemExit(f"Няма внесени mesh обекти от: {input_path}")

    bpy.ops.object.select_all(action='DESELECT')
    for obj in mesh_objects:
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

    export_ply(str(output_path))
    print(f"OK: {input_path} -> {output_path}")

if __name__ == "__main__":
    main()
