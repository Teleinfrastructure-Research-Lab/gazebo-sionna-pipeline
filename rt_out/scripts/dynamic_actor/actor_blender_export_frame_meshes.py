#!/usr/bin/env python3
"""Blender worker for production actor frame mesh export."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import bpy
from mathutils import Euler, Matrix, Vector


class ActorBlenderExportError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser(description="Export posed actor meshes from a worker spec.")
    parser.add_argument("--spec", type=Path, required=True, help="Actor export worker spec JSON.")
    return parser.parse_args(argv)


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise ActorBlenderExportError(f"Missing worker spec: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ActorBlenderExportError(f"Invalid worker spec JSON: {exc}") from exc


def require_pose6(value: Any, label: str) -> list[float]:
    if not isinstance(value, list) or len(value) != 6:
        raise ActorBlenderExportError(f"{label} must contain 6 numeric values")
    try:
        pose = [float(item) for item in value]
    except (TypeError, ValueError) as exc:
        raise ActorBlenderExportError(f"{label} contains non-numeric values") from exc
    if any(not math.isfinite(item) for item in pose):
        raise ActorBlenderExportError(f"{label} contains non-finite values")
    return pose


def pose6_to_matrix(pose6: list[float]) -> Matrix:
    x, y, z, roll, pitch, yaw = pose6
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    return Matrix(
        (
            (cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr, x),
            (sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr, y),
            (-sp, cp * sr, cp * cr, z),
            (0.0, 0.0, 0.0, 1.0),
        )
    )


def matrix_rows(matrix: Matrix) -> list[list[float]]:
    return [[float(value) for value in row] for row in matrix]


def frame_set_from_seconds(seconds: float, fps: float) -> dict[str, float | int]:
    frame_float = seconds * fps
    frame = math.floor(frame_float)
    subframe = frame_float - frame
    bpy.context.scene.frame_set(frame, subframe=subframe)
    return {"frame": frame, "subframe": subframe, "frame_float": frame_float}


SUPPORTED_ALIGNMENT_POLICIES = {"none", "bounds_center_xy_to_root"}
SUPPORTED_Z_ALIGNMENT_POLICIES = {"none", "bounds_min_z_to_floor"}


def bounds_for_vertices(vertices: list[tuple[float, float, float]]) -> tuple[list[float], list[float]]:
    bounds_min = [min(vertex[axis] for vertex in vertices) for axis in range(3)]
    bounds_max = [max(vertex[axis] for vertex in vertices) for axis in range(3)]
    if any(not math.isfinite(value) for value in bounds_min + bounds_max):
        raise ActorBlenderExportError("Exported actor mesh bounds are not finite")
    return bounds_min, bounds_max


def bounds_center(bounds_min: list[float], bounds_max: list[float]) -> list[float]:
    return [(bounds_min[index] + bounds_max[index]) * 0.5 for index in range(3)]


def write_ascii_tri_ply(
    path: Path,
    mesh_records: list[tuple[bpy.types.Mesh, Matrix]],
    *,
    root_pose6: list[float],
    alignment_policy: str,
    z_alignment_policy: str,
    floor_z: float | None,
) -> dict[str, Any]:
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []

    for mesh, matrix_world in mesh_records:
        mesh.calc_loop_triangles()
        vertex_offset = len(vertices)
        for vertex in mesh.vertices:
            co = matrix_world @ vertex.co
            values = (float(co.x), float(co.y), float(co.z))
            if any(not math.isfinite(item) for item in values):
                raise ActorBlenderExportError("Exported mesh contains non-finite vertex coordinates")
            vertices.append(values)
        for triangle in mesh.loop_triangles:
            faces.append(tuple(vertex_offset + int(index) for index in triangle.vertices))

    if not vertices or not faces:
        raise ActorBlenderExportError("Exported actor mesh is empty")

    pre_bounds_min, pre_bounds_max = bounds_for_vertices(vertices)
    pre_center = bounds_center(pre_bounds_min, pre_bounds_max)
    pre_offset_xy = math.hypot(pre_center[0] - root_pose6[0], pre_center[1] - root_pose6[1])
    applied_translation = [0.0, 0.0, 0.0]

    if alignment_policy == "bounds_center_xy_to_root":
        applied_translation = [
            root_pose6[0] - pre_center[0],
            root_pose6[1] - pre_center[1],
            0.0,
        ]
        vertices = [
            (
                vertex[0] + applied_translation[0],
                vertex[1] + applied_translation[1],
                vertex[2],
            )
            for vertex in vertices
        ]
    elif alignment_policy != "none":
        raise ActorBlenderExportError(f"Unsupported alignment_policy: {alignment_policy}")

    pre_z_bounds_min, pre_z_bounds_max = bounds_for_vertices(vertices)
    applied_z_translation = 0.0

    if z_alignment_policy == "bounds_min_z_to_floor":
        if floor_z is None or not math.isfinite(floor_z):
            raise ActorBlenderExportError("floor_z must be finite when z_alignment_policy is bounds_min_z_to_floor")
        applied_z_translation = floor_z - pre_z_bounds_min[2]
        vertices = [
            (
                vertex[0],
                vertex[1],
                vertex[2] + applied_z_translation,
            )
            for vertex in vertices
        ]
    elif z_alignment_policy != "none":
        raise ActorBlenderExportError(f"Unsupported z_alignment_policy: {z_alignment_policy}")

    bounds_min, bounds_max = bounds_for_vertices(vertices)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write("ply\n")
        handle.write("format ascii 1.0\n")
        handle.write(f"element vertex {len(vertices)}\n")
        handle.write("property float x\n")
        handle.write("property float y\n")
        handle.write("property float z\n")
        handle.write(f"element face {len(faces)}\n")
        handle.write("property list uchar int vertex_indices\n")
        handle.write("end_header\n")
        for x, y, z in vertices:
            handle.write(f"{x:.9f} {y:.9f} {z:.9f}\n")
        for i, j, k in faces:
            handle.write(f"3 {i} {j} {k}\n")

    return {
        "alignment_policy": alignment_policy,
        "pre_alignment_bounds_min": pre_bounds_min,
        "pre_alignment_bounds_max": pre_bounds_max,
        "pre_alignment_center_root_offset_xy": pre_offset_xy,
        "applied_alignment_translation": applied_translation,
        "post_alignment_bounds_min": bounds_min,
        "post_alignment_bounds_max": bounds_max,
        "z_alignment_policy": z_alignment_policy,
        "floor_z": floor_z,
        "pre_z_alignment_bounds_min": pre_z_bounds_min,
        "pre_z_alignment_bounds_max": pre_z_bounds_max,
        "applied_z_alignment_translation": applied_z_translation,
        "post_z_alignment_bounds_min": bounds_min,
        "post_z_alignment_bounds_max": bounds_max,
        "mesh_vertex_count": len(vertices),
        "mesh_face_count": len(faces),
        "bounds_min": bounds_min,
        "bounds_max": bounds_max,
    }


def import_actor_asset(sample: dict[str, Any]) -> tuple[bpy.types.Object | None, list[bpy.types.Object], bpy.types.Action | None]:
    animation_path = Path(sample["animation_path_resolved"])
    skin_path = Path(sample["skin_path_resolved"])
    if not animation_path.exists():
        raise ActorBlenderExportError(f"Animation asset does not exist: {animation_path}")
    if not skin_path.exists():
        raise ActorBlenderExportError(f"Skin asset does not exist: {skin_path}")
    if animation_path.resolve() != skin_path.resolve():
        raise ActorBlenderExportError(
            "Separate skin and animation DAE assets are not supported yet; "
            f"skin={skin_path}, animation={animation_path}"
        )

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.wm.collada_import(filepath=str(animation_path))

    armatures = [obj for obj in bpy.data.objects if obj.type == "ARMATURE"]
    mesh_objects = [obj for obj in bpy.data.objects if obj.type == "MESH"]
    action = bpy.data.actions[0] if bpy.data.actions else None
    armature = armatures[0] if armatures else None
    if armature is not None and action is not None:
        armature.animation_data_create()
        armature.animation_data.action = action
    return armature, mesh_objects, action


def export_sample(sample: dict[str, Any]) -> dict[str, Any]:
    armature, mesh_objects, action = import_actor_asset(sample)
    if armature is None:
        raise ActorBlenderExportError(f"Actor {sample['actor_name']} imported without an armature")
    if not mesh_objects:
        raise ActorBlenderExportError(f"Actor {sample['actor_name']} imported without mesh objects")
    if action is None:
        raise ActorBlenderExportError(f"Actor {sample['actor_name']} imported without an animation action")

    actor_pose6 = require_pose6(sample["actor_pose6"], f"{sample['actor_name']}.actor_pose6")
    root_pose6 = require_pose6(sample["root_pose6"], f"{sample['actor_name']}.root_pose6")
    alignment_policy = str(sample.get("alignment_policy") or "none")
    if alignment_policy not in SUPPORTED_ALIGNMENT_POLICIES:
        raise ActorBlenderExportError(
            f"{sample['actor_name']}.alignment_policy must be one of {sorted(SUPPORTED_ALIGNMENT_POLICIES)}"
        )
    z_alignment_policy = str(sample.get("z_alignment_policy") or "none")
    if z_alignment_policy not in SUPPORTED_Z_ALIGNMENT_POLICIES:
        raise ActorBlenderExportError(
            f"{sample['actor_name']}.z_alignment_policy must be one of {sorted(SUPPORTED_Z_ALIGNMENT_POLICIES)}"
        )
    floor_z = None
    if sample.get("floor_z") is not None:
        floor_z = float(sample["floor_z"])
        if not math.isfinite(floor_z):
            raise ActorBlenderExportError(f"Invalid floor_z for {sample['actor_name']}: {floor_z}")
    if z_alignment_policy == "bounds_min_z_to_floor" and floor_z is None:
        raise ActorBlenderExportError(
            f"{sample['actor_name']}.floor_z is required when z_alignment_policy is bounds_min_z_to_floor"
        )
    skin_scale = float(sample["skin_scale"])
    animation_time_seconds = float(sample["animation_time_seconds"])
    if not math.isfinite(skin_scale) or skin_scale <= 0:
        raise ActorBlenderExportError(f"Invalid skin scale for {sample['actor_name']}: {skin_scale}")
    if not math.isfinite(animation_time_seconds) or animation_time_seconds < 0:
        raise ActorBlenderExportError(
            f"Invalid animation time for {sample['actor_name']}: {animation_time_seconds}"
        )

    fps = bpy.context.scene.render.fps / bpy.context.scene.render.fps_base
    sampled_frame = frame_set_from_seconds(animation_time_seconds, fps)

    actor_matrix = pose6_to_matrix(actor_pose6)
    root_matrix = pose6_to_matrix(root_pose6)
    combined_matrix = actor_matrix @ root_matrix
    loc, rot, _scale = combined_matrix.decompose()

    armature.location = loc
    armature.rotation_mode = "QUATERNION"
    armature.rotation_quaternion = rot
    armature.scale = (skin_scale, skin_scale, skin_scale)
    bpy.context.view_layer.update()

    depsgraph = bpy.context.evaluated_depsgraph_get()
    mesh_records: list[tuple[bpy.types.Mesh, Matrix]] = []
    temp_meshes: list[bpy.types.Mesh] = []
    for mesh_obj in mesh_objects:
        eval_mesh_obj = mesh_obj.evaluated_get(depsgraph)
        eval_mesh = bpy.data.meshes.new_from_object(
            eval_mesh_obj,
            depsgraph=depsgraph,
            preserve_all_data_layers=True,
        )
        mesh_records.append((eval_mesh, eval_mesh_obj.matrix_world.copy()))
        temp_meshes.append(eval_mesh)

    try:
        stats = write_ascii_tri_ply(
            Path(sample["output_mesh_path"]),
            mesh_records,
            root_pose6=root_pose6,
            alignment_policy=alignment_policy,
            z_alignment_policy=z_alignment_policy,
            floor_z=floor_z,
        )
    finally:
        for mesh in temp_meshes:
            bpy.data.meshes.remove(mesh)

    return {
        "id": sample["id"],
        "actor_name": sample["actor_name"],
        "frame_id": sample.get("frame_id"),
        "validation_frame_id": sample.get("validation_frame_id"),
        "source_sample_index": sample.get("source_sample_index"),
        "output_mesh_path": sample["output_mesh_path"],
        "applied_actor_pose6": actor_pose6,
        "applied_root_pose6": root_pose6,
        "applied_combined_matrix": matrix_rows(combined_matrix),
        "applied_skin_scale": skin_scale,
        "animation_time_seconds": animation_time_seconds,
        "sampled_blender_frame": sampled_frame,
        "mesh_object_count": len(mesh_objects),
        "mesh_object_names": [obj.name for obj in mesh_objects],
        "armature": {
            "found": True,
            "name": armature.name,
        },
        "action": {
            "found": True,
            "name": action.name,
            "frame_range": [float(action.frame_range[0]), float(action.frame_range[1])],
        },
        "fps": fps,
        **stats,
    }


def main() -> int:
    args = parse_args()
    spec = load_json(args.spec)
    samples = spec.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ActorBlenderExportError("Worker spec must contain a non-empty samples list")

    exports = [export_sample(sample) for sample in samples]
    summary = {
        "generated_by": Path(__file__).name,
        "spec_path": str(args.spec.resolve()),
        "frame_id": spec.get("frame_id"),
        "validation_batch": spec.get("validation_batch", False),
        "source_sample_index": spec.get("source_sample_index"),
        "exports": exports,
    }
    summary_path = Path(spec["summary_path"])
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"Actor Blender worker exported {len(exports)} actor mesh(es)")
    print(f"summary: {summary_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ActorBlenderExportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
