#!/usr/bin/env python3
"""Blender helper for the isolated actor_walking feasibility spike."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import bpy


def parse_args() -> argparse.Namespace:
    # Blender forwards everything after `--` to this helper. Keep argument
    # parsing tiny because the outer spike script already prepares the JSON spec.
    argv = []
    if "--" in __import__("sys").argv:
        argv = __import__("sys").argv[__import__("sys").argv.index("--") + 1 :]

    parser = argparse.ArgumentParser(description="Sample a skinned actor DAE in Blender.")
    parser.add_argument("--spec", type=Path, required=True, help="Sampling spec JSON path.")
    return parser.parse_args(argv)


def matrix_rows(matrix) -> list[list[float]]:
    return [[float(value) for value in row] for row in matrix]


def frame_set_from_seconds(seconds: float, fps: float) -> None:
    # Sample the animation at sub-frame precision so the offline actor export
    # does not lose timing accuracy when seconds do not land on whole frames.
    frame_float = seconds * fps
    frame = math.floor(frame_float)
    subframe = frame_float - frame
    bpy.context.scene.frame_set(frame, subframe=subframe)


def write_ascii_tri_ply(path: Path, mesh: bpy.types.Mesh) -> tuple[int, int, list[float], list[float]]:
    # Export an explicit triangle mesh in ASCII PLY so the spike artifacts are
    # easy to inspect outside Blender.
    mesh.calc_loop_triangles()
    verts = [tuple(float(value) for value in vertex.co) for vertex in mesh.vertices]
    tris = [tuple(int(index) for index in tri.vertices) for tri in mesh.loop_triangles]

    mins = [min(v[i] for v in verts) for i in range(3)]
    maxs = [max(v[i] for v in verts) for i in range(3)]

    with path.open("w", encoding="utf-8") as handle:
        handle.write("ply\n")
        handle.write("format ascii 1.0\n")
        handle.write(f"element vertex {len(verts)}\n")
        handle.write("property float x\n")
        handle.write("property float y\n")
        handle.write("property float z\n")
        handle.write(f"element face {len(tris)}\n")
        handle.write("property list uchar int vertex_indices\n")
        handle.write("end_header\n")
        for x, y, z in verts:
            handle.write(f"{x:.9f} {y:.9f} {z:.9f}\n")
        for tri in tris:
            handle.write(f"3 {tri[0]} {tri[1]} {tri[2]}\n")

    return len(verts), len(tris), mins, maxs


def main() -> None:
    args = parse_args()
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    # Create a clean output tree for posed meshes, bone transforms, and summary
    # metadata belonging to this isolated actor_walking spike.
    output_root = Path(spec["output_root"])
    posed_dir = output_root / "posed_meshes"
    bone_dir = output_root / "bone_transforms"
    meta_dir = output_root / "metadata"
    posed_dir.mkdir(parents=True, exist_ok=True)
    bone_dir.mkdir(parents=True, exist_ok=True)
    meta_dir.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.collada_import(filepath=spec["animation_path_resolved"])

    # This spike expects one armature and one skinned mesh from the actor DAE.
    armature = next((obj for obj in bpy.data.objects if obj.type == "ARMATURE"), None)
    mesh_obj = next((obj for obj in bpy.data.objects if obj.type == "MESH"), None)
    if armature is None or mesh_obj is None:
        raise RuntimeError("Expected one imported armature and one mesh object")

    action = bpy.data.actions[0] if bpy.data.actions else None
    if action is None:
        raise RuntimeError("No animation action imported from actor DAE")
    armature.animation_data_create()
    armature.animation_data.action = action

    fps = bpy.context.scene.render.fps / bpy.context.scene.render.fps_base
    exports = []

    for sample in spec["samples"]:
        # Drive the armature to the requested animation time, then place the
        # actor root in the sampled world pose from the Gazebo script trajectory.
        frame_set_from_seconds(sample["animation_time_seconds"], fps)
        root_pose6 = sample["root_pose6"]
        armature.location = root_pose6[:3]
        armature.rotation_mode = "XYZ"
        armature.rotation_euler = root_pose6[3:]
        uniform_scale = float(spec["skin_scale"])
        armature.scale = (uniform_scale, uniform_scale, uniform_scale)
        bpy.context.view_layer.update()

        depsgraph = bpy.context.evaluated_depsgraph_get()
        eval_mesh_obj = mesh_obj.evaluated_get(depsgraph)
        # Bake the deformed mesh exactly as Blender evaluates it at this sample.
        eval_mesh = bpy.data.meshes.new_from_object(
            eval_mesh_obj,
            depsgraph=depsgraph,
            preserve_all_data_layers=True,
        )
        eval_mesh.transform(eval_mesh_obj.matrix_world)

        stem = f"frame_{sample['sample_id']:03d}_t{sample['actor_time_seconds']:.3f}".replace(".", "p")
        posed_mesh_path = posed_dir / f"{stem}.ply"
        vertex_count, face_count, bounds_min, bounds_max = write_ascii_tri_ply(posed_mesh_path, eval_mesh)

        bone_data = {
            "sample_id": sample["sample_id"],
            "actor_time_seconds": sample["actor_time_seconds"],
            "animation_time_seconds": sample["animation_time_seconds"],
            "root_pose6": root_pose6,
            "bones": {},
        }
        for pose_bone in armature.pose.bones:
            # Record per-bone world transforms alongside the posed mesh so the
            # spike can compare mesh-space and skeleton-space outputs later.
            world_matrix = armature.matrix_world @ pose_bone.matrix
            bone_data["bones"][pose_bone.name] = {
                "parent": pose_bone.parent.name if pose_bone.parent else None,
                "matrix_world": matrix_rows(world_matrix),
                "head_world": [float(v) for v in (armature.matrix_world @ pose_bone.head.to_4d()).xyz],
                "tail_world": [float(v) for v in (armature.matrix_world @ pose_bone.tail.to_4d()).xyz],
            }

        bone_path = bone_dir / f"{stem}.json"
        bone_path.write_text(json.dumps(bone_data, indent=2) + "\n", encoding="utf-8")

        bpy.data.meshes.remove(eval_mesh)

        exports.append(
            {
                "sample_id": sample["sample_id"],
                "actor_time_seconds": sample["actor_time_seconds"],
                "animation_time_seconds": sample["animation_time_seconds"],
                "posed_mesh_path": str(posed_mesh_path.resolve()),
                "bone_transforms_path": str(bone_path.resolve()),
                "mesh_vertex_count": vertex_count,
                "mesh_face_count": face_count,
                "bounds_min": bounds_min,
                "bounds_max": bounds_max,
            }
        )

    summary = {
        # Keep one compact summary JSON describing the imported action and every
        # exported sample for quick offline inspection.
        "armature_name": armature.name,
        "mesh_name": mesh_obj.name,
        "action_name": action.name,
        "action_frame_range": [float(action.frame_range[0]), float(action.frame_range[1])],
        "fps": fps,
        "exports": exports,
    }
    (meta_dir / "blender_export_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
