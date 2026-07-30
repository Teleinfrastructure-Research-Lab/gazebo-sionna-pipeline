#!/usr/bin/env python3
"""Diagnose actor vertical placement against the static scene floor."""

from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MESH_INDEX = PROJECT_ROOT / "rt_out" / "experiments" / "factory_panda_ur5" / "legacy_run_20260522_133045" / "reports" / "actor_prototype_validation" / "actor_prototype_mesh_index.json"
DEFAULT_STATIC_MANIFEST = PROJECT_ROOT / "rt_out" / "experiments" / "factory_panda_ur5" / "legacy_run_20260522_133045" / "static_scene" / "export" / "merged_static_manifest.json"
DEFAULT_OUTPUT_JSON = PROJECT_ROOT / "rt_out" / "experiments" / "factory_panda_ur5" / "legacy_run_20260522_133045" / "reports" / "actor_prototype_validation" / "actor_floor_alignment_diagnostics.json"
FLOOR_NAME_HINTS = ("floor", "tile", "vinyl", "ground")
FLOATING_WARN_METERS = 0.05


class ActorFloorAlignmentDiagnosticError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose actor floor/vertical alignment.")
    parser.add_argument("--mesh-index", type=Path, default=DEFAULT_MESH_INDEX)
    parser.add_argument("--static-manifest", type=Path, default=DEFAULT_STATIC_MANIFEST)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    return parser.parse_args()


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
        raise ActorFloorAlignmentDiagnosticError(f"Missing {label}: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ActorFloorAlignmentDiagnosticError(f"Invalid JSON in {label} {path}: {exc}") from exc


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ActorFloorAlignmentDiagnosticError(f"{label} must be an object")
    return value


def finite_vec(values: Any, length: int, label: str) -> list[float]:
    if not isinstance(values, list) or len(values) != length:
        raise ActorFloorAlignmentDiagnosticError(f"{label} must contain {length} values")
    try:
        out = [float(item) for item in values]
    except (TypeError, ValueError) as exc:
        raise ActorFloorAlignmentDiagnosticError(f"{label} contains non-numeric values") from exc
    if any(not math.isfinite(item) for item in out):
        raise ActorFloorAlignmentDiagnosticError(f"{label} contains non-finite values")
    return out


def read_ply_bounds(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ActorFloorAlignmentDiagnosticError(f"Missing PLY mesh: {path}")
    with path.open("rb") as handle:
        header_lines: list[str] = []
        vertex_count: int | None = None
        fmt: str | None = None
        in_vertex_element = False
        vertex_properties: list[tuple[str, str]] = []
        while True:
            raw_line = handle.readline()
            if not raw_line:
                raise ActorFloorAlignmentDiagnosticError(f"PLY header ended unexpectedly: {path}")
            line = raw_line.decode("ascii", errors="replace").strip()
            header_lines.append(line)
            if line.startswith("format "):
                fmt = line.split()[1]
            if line.startswith("element vertex "):
                vertex_count = int(line.split()[-1])
                in_vertex_element = True
            elif line.startswith("element "):
                in_vertex_element = False
            elif in_vertex_element and line.startswith("property "):
                parts = line.split()
                if len(parts) == 3:
                    vertex_properties.append((parts[1], parts[2]))
            if line == "end_header":
                break
        if vertex_count is None:
            raise ActorFloorAlignmentDiagnosticError(f"PLY missing vertex count: {path}")
        if not vertex_properties:
            raise ActorFloorAlignmentDiagnosticError(f"PLY missing vertex properties: {path}")
        property_names = [name for _type_name, name in vertex_properties]
        for coordinate in ("x", "y", "z"):
            if coordinate not in property_names:
                raise ActorFloorAlignmentDiagnosticError(f"PLY missing {coordinate} vertex coordinate: {path}")
        coordinate_indices = [property_names.index(coordinate) for coordinate in ("x", "y", "z")]

        bounds_min = [math.inf, math.inf, math.inf]
        bounds_max = [-math.inf, -math.inf, -math.inf]
        if fmt == "ascii":
            for index in range(vertex_count):
                raw_line = handle.readline()
                if not raw_line:
                    raise ActorFloorAlignmentDiagnosticError(f"PLY ended before vertex {index}: {path}")
                parts = raw_line.decode("ascii", errors="replace").strip().split()
                if len(parts) < len(vertex_properties):
                    raise ActorFloorAlignmentDiagnosticError(f"PLY vertex {index} has too few properties: {path}")
                try:
                    values = [float(parts[property_index]) for property_index in coordinate_indices]
                except ValueError as exc:
                    raise ActorFloorAlignmentDiagnosticError(
                        f"PLY vertex {index} has non-numeric coordinates: {path}"
                    ) from exc
                if any(not math.isfinite(value) for value in values):
                    raise ActorFloorAlignmentDiagnosticError(f"PLY vertex {index} has non-finite coordinates: {path}")
                for axis, value in enumerate(values):
                    bounds_min[axis] = min(bounds_min[axis], value)
                    bounds_max[axis] = max(bounds_max[axis], value)
        elif fmt in {"binary_little_endian", "binary_big_endian"}:
            endian = "<" if fmt == "binary_little_endian" else ">"
            type_formats = {
                "char": "b",
                "uchar": "B",
                "int8": "b",
                "uint8": "B",
                "short": "h",
                "ushort": "H",
                "int16": "h",
                "uint16": "H",
                "int": "i",
                "uint": "I",
                "int32": "i",
                "uint32": "I",
                "float": "f",
                "float32": "f",
                "double": "d",
                "float64": "d",
            }
            try:
                vertex_struct = struct.Struct(endian + "".join(type_formats[type_name] for type_name, _name in vertex_properties))
            except KeyError as exc:
                raise ActorFloorAlignmentDiagnosticError(f"Unsupported PLY vertex property type {exc}: {path}") from exc
            for index in range(vertex_count):
                raw_vertex = handle.read(vertex_struct.size)
                if len(raw_vertex) != vertex_struct.size:
                    raise ActorFloorAlignmentDiagnosticError(f"PLY ended before binary vertex {index}: {path}")
                unpacked = vertex_struct.unpack(raw_vertex)
                values = [float(unpacked[property_index]) for property_index in coordinate_indices]
                if any(not math.isfinite(value) for value in values):
                    raise ActorFloorAlignmentDiagnosticError(f"PLY vertex {index} has non-finite coordinates: {path}")
                for axis, value in enumerate(values):
                    bounds_min[axis] = min(bounds_min[axis], value)
                    bounds_max[axis] = max(bounds_max[axis], value)
        else:
            raise ActorFloorAlignmentDiagnosticError(f"Unsupported PLY format {fmt!r}: {path}")

    return {
        "mesh_path": str(path),
        "vertex_count": vertex_count,
        "bounds_min": bounds_min,
        "bounds_max": bounds_max,
        "bounds_min_z": bounds_min[2],
        "bounds_max_z": bounds_max[2],
    }


def actor_vertical_records(mesh_index: dict[str, Any]) -> list[dict[str, Any]]:
    entries = mesh_index.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ActorFloorAlignmentDiagnosticError("mesh index must contain a non-empty entries list")
    records = []
    for index, raw_entry in enumerate(entries):
        entry = require_object(raw_entry, f"mesh index entries[{index}]")
        root_pose6 = finite_vec(entry.get("root_pose6"), 6, f"entries[{index}].root_pose6")
        bounds_min = finite_vec(entry.get("bounds_min"), 3, f"entries[{index}].bounds_min")
        bounds_max = finite_vec(entry.get("bounds_max"), 3, f"entries[{index}].bounds_max")
        records.append(
            {
                "id": entry.get("id"),
                "validation_frame_id": int(entry.get("validation_frame_id")),
                "actor_name": entry.get("actor_name"),
                "actor_time_seconds": float(entry.get("actor_time_seconds")),
                "animation_time_seconds": float(entry.get("animation_time_seconds")),
                "root_z": root_pose6[2],
                "bounds_min_z": bounds_min[2],
                "bounds_max_z": bounds_max[2],
                "lower_z_minus_root_z": bounds_min[2] - root_pose6[2],
                "alignment_policy": entry.get("alignment_policy"),
                "mesh_path": entry.get("output_mesh_path"),
            }
        )
    return sorted(records, key=lambda item: item["validation_frame_id"])


def static_group_bounds(static_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    groups = static_manifest.get("merged_groups")
    if not isinstance(groups, list):
        raise ActorFloorAlignmentDiagnosticError("static manifest must contain merged_groups list")
    out = []
    for index, raw_group in enumerate(groups):
        group = require_object(raw_group, f"static merged_groups[{index}]")
        material_class = str(group.get("material_class") or "")
        raw_path = group.get("merged_mesh_path")
        if not raw_path:
            raise ActorFloorAlignmentDiagnosticError(f"static group {material_class!r} missing merged_mesh_path")
        mesh_path = resolve_path(Path(str(raw_path)))
        bounds = read_ply_bounds(mesh_path)
        is_floor_candidate = any(hint in material_class.lower() for hint in FLOOR_NAME_HINTS)
        out.append(
            {
                "material_class": material_class,
                "is_floor_candidate": is_floor_candidate,
                **bounds,
            }
        )
    return sorted(out, key=lambda item: (not item["is_floor_candidate"], item["bounds_min_z"], item["material_class"]))


def estimate_floor_z(groups: list[dict[str, Any]]) -> dict[str, Any]:
    floor_candidates = [group for group in groups if group["is_floor_candidate"]]
    if floor_candidates:
        chosen = min(floor_candidates, key=lambda item: (abs(item["bounds_max_z"] - item["bounds_min_z"]), item["bounds_min_z"]))
        source = "floor_material_name_hint"
    else:
        chosen = min(groups, key=lambda item: item["bounds_min_z"])
        source = "lowest_static_mesh_fallback"
    return {
        "floor_z_estimate": float(chosen["bounds_max_z"]),
        "floor_z_source": source,
        "chosen_material_class": chosen["material_class"],
        "chosen_floor_bounds_min_z": chosen["bounds_min_z"],
        "chosen_floor_bounds_max_z": chosen["bounds_max_z"],
        "chosen_floor_mesh_path": chosen["mesh_path"],
    }


def build_diagnostics(mesh_index: dict[str, Any], static_manifest: dict[str, Any]) -> dict[str, Any]:
    actor_records = actor_vertical_records(mesh_index)
    groups = static_group_bounds(static_manifest)
    floor = estimate_floor_z(groups)
    floor_z = floor["floor_z_estimate"]
    floating_records = []
    for record in actor_records:
        actor_feet_z = record["bounds_min_z"]
        floating_height = actor_feet_z - floor_z
        enriched = {
            **record,
            "actor_feet_z": actor_feet_z,
            "floor_z_estimate": floor_z,
            "actor_feet_above_floor": floating_height,
            "floating": floating_height > FLOATING_WARN_METERS,
        }
        floating_records.append(enriched)

    max_floating_height = max(record["actor_feet_above_floor"] for record in floating_records)
    min_floating_height = min(record["actor_feet_above_floor"] for record in floating_records)
    recommended_floor_z = floor_z
    return {
        "generated_by": Path(__file__).name,
        "summary": {
            "actor_record_count": len(actor_records),
            "floor_z_estimate": floor_z,
            "floor_z_source": floor["floor_z_source"],
            "floor_material_class": floor["chosen_material_class"],
            "floor_bounds_min_z": floor["chosen_floor_bounds_min_z"],
            "floor_bounds_max_z": floor["chosen_floor_bounds_max_z"],
            "max_actor_feet_above_floor": max_floating_height,
            "min_actor_feet_above_floor": min_floating_height,
            "floating_frame_count": sum(1 for record in floating_records if record["floating"]),
            "floating_confirmed": max_floating_height > FLOATING_WARN_METERS,
            "recommended_floor_z": recommended_floor_z,
        },
        "actor_vertical_records": floating_records,
        "floor_estimate": floor,
        "static_group_z_bounds": groups,
    }


def main() -> int:
    args = parse_args()
    mesh_index_path = resolve_path(args.mesh_index)
    static_manifest_path = resolve_path(args.static_manifest)
    output_json = resolve_path(args.output_json)
    mesh_index = require_object(load_json(mesh_index_path, "actor prototype mesh index"), "mesh index")
    static_manifest = require_object(load_json(static_manifest_path, "static merged manifest"), "static manifest")
    diagnostics = build_diagnostics(mesh_index, static_manifest)
    save_json(output_json, diagnostics)

    summary = diagnostics["summary"]
    print("Actor floor alignment diagnostics")
    print(f"mesh_index: {mesh_index_path}")
    print(f"static_manifest: {static_manifest_path}")
    print(f"output_json: {output_json}")
    print("Actor vertical records:")
    for record in diagnostics["actor_vertical_records"]:
        print(
            f"  frame {record['validation_frame_id']:03d}: "
            f"bounds_min_z={record['bounds_min_z']:.6f} "
            f"bounds_max_z={record['bounds_max_z']:.6f} "
            f"root_z={record['root_z']:.6f} "
            f"lower_z_minus_root_z={record['lower_z_minus_root_z']:.6f} "
            f"actor_feet_above_floor={record['actor_feet_above_floor']:.6f}"
        )
    print("Floor estimate:")
    print(f"  material_class: {summary['floor_material_class']}")
    print(f"  source: {summary['floor_z_source']}")
    print(f"  floor_bounds_min_z: {summary['floor_bounds_min_z']:.6f}")
    print(f"  floor_bounds_max_z: {summary['floor_bounds_max_z']:.6f}")
    print(f"  floor_z_estimate: {summary['floor_z_estimate']:.6f}")
    print(f"floating_confirmed: {summary['floating_confirmed']}")
    print(f"floating_frame_count: {summary['floating_frame_count']}")
    print(f"max_actor_feet_above_floor: {summary['max_actor_feet_above_floor']:.6f}")
    print(f"recommended_floor_z: {summary['recommended_floor_z']:.6f}")
    print("Static group z bounds:")
    for group in diagnostics["static_group_z_bounds"]:
        marker = " floor-candidate" if group["is_floor_candidate"] else ""
        print(
            f"  {group['material_class']}: "
            f"min_z={group['bounds_min_z']:.6f} max_z={group['bounds_max_z']:.6f}{marker}"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ActorFloorAlignmentDiagnosticError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
