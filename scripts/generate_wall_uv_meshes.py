#!/usr/bin/env python3
"""Generate UV-aware wall meshes for all plaster wall segments.

The current world uses box visuals for the wall sections around the windows,
door, and side walls. Box primitives don't expose UV offset controls in SDF,
so the wall texture restarts on each piece. This script generates OBJ meshes
whose front and back face UVs are derived from shared wall-space coordinates,
letting the texture continue across separate segments while keeping a unified
scale on all walls.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "meshes" / "walls"
MTL_NAME = "wall_placeholder.mtl"
MATERIAL_NAME = "wall_placeholder"

# Lower values make the texture repeat more often.
# With 0.9 m per repeat, the 2.8 m-tall wall gets a little over 3 repeats.
TEXTURE_REPEAT_METERS_U = 0.9
TEXTURE_REPEAT_METERS_V = 0.9


@dataclass(frozen=True)
class WallSpace:
    u_min: float
    width: float
    z_min: float
    height: float
    u_offset_meters: float = 0.0
    reverse_u: bool = False


@dataclass(frozen=True)
class Segment:
    name: str
    size_x: float
    size_y: float
    size_z: float
    center_u: float
    center_x: float
    center_y: float
    center_z: float
    wall_space: WallSpace


NORTH_WALL = WallSpace(u_min=-4.75, width=9.5, z_min=0.1, height=2.8, u_offset_meters=0.0, reverse_u=False)
EAST_WALL = WallSpace(u_min=-4.75, width=9.5, z_min=0.1, height=2.8, u_offset_meters=9.5, reverse_u=True)
SOUTH_WALL = WallSpace(u_min=-4.75, width=9.5, z_min=0.1, height=2.8, u_offset_meters=19.0, reverse_u=True)
WEST_WALL = WallSpace(u_min=-4.75, width=9.5, z_min=0.1, height=2.8, u_offset_meters=28.5, reverse_u=False)

SEGMENTS = [
    Segment("north_wall_lower", 9.5, 0.2, 0.9, 0.0, 0.0, 4.65, 0.55, NORTH_WALL),
    Segment("north_wall_upper", 9.5, 0.2, 0.9, 0.0, 0.0, 4.65, 2.45, NORTH_WALL),
    Segment("north_wall_left_pier", 2.85, 0.2, 1.0, -3.325, -3.325, 4.65, 1.5, NORTH_WALL),
    Segment("north_wall_center_pier", 0.8, 0.2, 1.0, 0.0, 0.0, 4.65, 1.5, NORTH_WALL),
    Segment("north_wall_right_pier", 2.85, 0.2, 1.0, 3.325, 3.325, 4.65, 1.5, NORTH_WALL),
    Segment("south_wall_left", 4.375, 0.2, 2.8, -2.5625, -2.5625, -4.65, 1.5, SOUTH_WALL),
    Segment("south_wall_right", 4.375, 0.2, 2.8, 2.5625, 2.5625, -4.65, 1.5, SOUTH_WALL),
    Segment("south_wall_overdoor", 0.9, 0.2, 0.91545, 0.0, 0.0, -4.65, 2.442275, SOUTH_WALL),
    Segment("east_wall", 9.5, 0.2, 2.8, 0.0, 4.65, 0.0, 1.5, EAST_WALL),
    Segment("west_wall", 9.5, 0.2, 2.8, 0.0, -4.65, 0.0, 1.5, WEST_WALL),
]


def format_vertex(vertex: tuple[float, float, float]) -> str:
    return f"v {vertex[0]:.6f} {vertex[1]:.6f} {vertex[2]:.6f}"


def format_uv(uv: tuple[float, float]) -> str:
    return f"vt {uv[0]:.6f} {uv[1]:.6f}"


def format_normal(normal: tuple[float, float, float]) -> str:
    return f"vn {normal[0]:.6f} {normal[1]:.6f} {normal[2]:.6f}"


def wall_uv(segment: Segment, local_vertex: tuple[float, float, float]) -> tuple[float, float]:
    wall_u = segment.center_u + local_vertex[0]
    wall_z = segment.center_z + local_vertex[2]
    u_meters = wall_u - segment.wall_space.u_min
    if segment.wall_space.reverse_u:
        u_meters = segment.wall_space.width - u_meters
    u = (segment.wall_space.u_offset_meters + u_meters) / TEXTURE_REPEAT_METERS_U
    v = (wall_z - segment.wall_space.z_min) / TEXTURE_REPEAT_METERS_V
    return (u, v)


def local_span_uv(
    local_vertex: tuple[float, float, float],
    axis_u: str,
    axis_v: str,
    half_sizes: tuple[float, float, float],
) -> tuple[float, float]:
    axis_index = {"x": 0, "y": 1, "z": 2}
    u_idx = axis_index[axis_u]
    v_idx = axis_index[axis_v]
    u = (local_vertex[u_idx] + half_sizes[u_idx]) / (2.0 * half_sizes[u_idx])
    v = (local_vertex[v_idx] + half_sizes[v_idx]) / (2.0 * half_sizes[v_idx])
    return (u, v)


def face_definitions(segment: Segment) -> list[tuple[str, list[tuple[float, float, float]], tuple[float, float, float]]]:
    hx = segment.size_x / 2.0
    hy = segment.size_y / 2.0
    hz = segment.size_z / 2.0
    return [
        (
            "wall_face_neg_y",
            [(-hx, -hy, -hz), (hx, -hy, -hz), (hx, -hy, hz), (-hx, -hy, hz)],
            (0.0, -1.0, 0.0),
        ),
        (
            "wall_face_pos_y",
            [(-hx, hy, -hz), (-hx, hy, hz), (hx, hy, hz), (hx, hy, -hz)],
            (0.0, 1.0, 0.0),
        ),
        (
            "side_face_neg_x",
            [(-hx, -hy, -hz), (-hx, -hy, hz), (-hx, hy, hz), (-hx, hy, -hz)],
            (-1.0, 0.0, 0.0),
        ),
        (
            "side_face_pos_x",
            [(hx, -hy, -hz), (hx, hy, -hz), (hx, hy, hz), (hx, -hy, hz)],
            (1.0, 0.0, 0.0),
        ),
        (
            "top_face_pos_z",
            [(-hx, -hy, hz), (hx, -hy, hz), (hx, hy, hz), (-hx, hy, hz)],
            (0.0, 0.0, 1.0),
        ),
        (
            "bottom_face_neg_z",
            [(-hx, -hy, -hz), (-hx, hy, -hz), (hx, hy, -hz), (hx, -hy, -hz)],
            (0.0, 0.0, -1.0),
        ),
    ]


def uv_for_face(
    segment: Segment,
    face_name: str,
    local_vertex: tuple[float, float, float],
) -> tuple[float, float]:
    half_sizes = (segment.size_x / 2.0, segment.size_y / 2.0, segment.size_z / 2.0)
    if face_name.startswith("wall_face_"):
        return wall_uv(segment, local_vertex)
    if face_name.startswith("side_face_"):
        return local_span_uv(local_vertex, "y", "z", half_sizes)
    return local_span_uv(local_vertex, "x", "y", half_sizes)


def write_segment(segment: Segment) -> Path:
    output_path = OUTPUT_DIR / f"{segment.name}.obj"
    vertices: list[str] = [f"mtllib {MTL_NAME}", f"o {segment.name}"]
    uvs: list[str] = []
    normals: list[str] = []
    faces: list[str] = [f"usemtl {MATERIAL_NAME}"]

    vertex_index = 1
    uv_index = 1
    normal_index = 1

    for face_name, face_vertices, normal in face_definitions(segment):
        normals.append(format_normal(normal))
        normal_ref = normal_index
        normal_index += 1

        face_vertex_indices: list[int] = []
        face_uv_indices: list[int] = []
        for local_vertex in face_vertices:
            vertices.append(format_vertex(local_vertex))
            uvs.append(format_uv(uv_for_face(segment, face_name, local_vertex)))
            face_vertex_indices.append(vertex_index)
            face_uv_indices.append(uv_index)
            vertex_index += 1
            uv_index += 1

        faces.append(
            "f "
            f"{face_vertex_indices[0]}/{face_uv_indices[0]}/{normal_ref} "
            f"{face_vertex_indices[1]}/{face_uv_indices[1]}/{normal_ref} "
            f"{face_vertex_indices[2]}/{face_uv_indices[2]}/{normal_ref}"
        )
        faces.append(
            "f "
            f"{face_vertex_indices[0]}/{face_uv_indices[0]}/{normal_ref} "
            f"{face_vertex_indices[2]}/{face_uv_indices[2]}/{normal_ref} "
            f"{face_vertex_indices[3]}/{face_uv_indices[3]}/{normal_ref}"
        )

    output_path.write_text("\n".join(vertices + uvs + normals + faces) + "\n", encoding="ascii")
    return output_path


def write_material_file() -> Path:
    material_path = OUTPUT_DIR / MTL_NAME
    material_path.write_text(
        "\n".join(
            [
                f"newmtl {MATERIAL_NAME}",
                "Ka 1.000000 1.000000 1.000000",
                "Kd 1.000000 1.000000 1.000000",
                "Ks 0.000000 0.000000 0.000000",
                "Ns 10.000000",
                "",
            ]
        ),
        encoding="ascii",
    )
    return material_path


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_material_file()
    generated = [write_segment(segment) for segment in SEGMENTS]
    for path in generated:
        print(path.relative_to(ROOT))


if __name__ == "__main__":
    main()
