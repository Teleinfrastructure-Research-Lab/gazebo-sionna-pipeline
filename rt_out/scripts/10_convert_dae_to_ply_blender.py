import sys
from pathlib import Path
import bpy

def clear_scene():
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    if hasattr(bpy.ops.outliner, "orphans_purge"):
        bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)

def export_ply(filepath: str):
    # Нов оператор
    if hasattr(bpy.ops.wm, "ply_export"):
        op = bpy.ops.wm.ply_export
        props = op.get_rna_type().properties

        kwargs = {
            "filepath": filepath,
        }

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

        # Внимателно с export_colors: понякога е bool, понякога enum
        if "export_colors" in props:
            p = props["export_colors"]
            if p.type == 'BOOLEAN':
                kwargs["export_colors"] = False
            elif p.type == 'ENUM':
                enum_ids = [item.identifier for item in p.enum_items]
                if "NONE" in enum_ids:
                    kwargs["export_colors"] = "NONE"
                elif "SRGB" in enum_ids:
                    kwargs["export_colors"] = "SRGB"
                elif "LINEAR" in enum_ids:
                    kwargs["export_colors"] = "LINEAR"

        op(**kwargs)
        return

    # Стар оператор
    elif hasattr(bpy.ops.export_mesh, "ply"):
        bpy.ops.export_mesh.ply(
            filepath=filepath,
            use_selection=True,
            use_mesh_modifiers=True,
            use_normals=True,
            use_uv_coords=False,
            use_colors=False
        )
        return

    raise RuntimeError("Не е намерен оператор за износ към PLY в Blender.")

def import_dae(filepath: str):
    if hasattr(bpy.ops.wm, "collada_import"):
        bpy.ops.wm.collada_import(filepath=filepath)
    else:
        raise RuntimeError("Не е намерен оператор за внос на COLLADA (.dae) в Blender.")

def main():
    argv = sys.argv
    if "--" not in argv:
        raise SystemExit("Използване: blender --background --python 10_convert_dae_to_ply_blender.py -- input.dae output.ply")

    args = argv[argv.index("--") + 1:]
    if len(args) != 2:
        raise SystemExit("Трябват 2 аргумента: input.dae output.ply")

    input_path = Path(args[0]).expanduser().resolve()
    output_path = Path(args[1]).expanduser().resolve()

    if not input_path.exists():
        raise SystemExit(f"Липсва входен файл: {input_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    clear_scene()
    import_dae(str(input_path))

    mesh_objects = [obj for obj in bpy.context.scene.objects if obj.type == 'MESH']
    if not mesh_objects:
        raise SystemExit(f"Няма внесени mesh обекти от: {input_path}")

    bpy.ops.object.select_all(action='DESELECT')

    for obj in mesh_objects:
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        mod = obj.modifiers.new(name="Triangulate", type='TRIANGULATE')
        bpy.ops.object.modifier_apply(modifier=mod.name)

    bpy.context.view_layer.objects.active = mesh_objects[0]
    export_ply(str(output_path))

    print(f"OK: {input_path} -> {output_path}")

if __name__ == "__main__":
    main()
