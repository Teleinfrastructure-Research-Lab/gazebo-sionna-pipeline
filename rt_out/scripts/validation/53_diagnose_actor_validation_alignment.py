#!/usr/bin/env python3
"""Diagnose actor validation mesh alignment against scripted root poses."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MESH_INDEX = PROJECT_ROOT / "rt_out" / "actor_validation" / "actor_validation_mesh_index.json"
DEFAULT_WORKER_SUMMARY = PROJECT_ROOT / "rt_out" / "actor_validation" / "metadata" / "actor_validation_blender_summary.json"
DEFAULT_OUTPUT_JSON = PROJECT_ROOT / "rt_out" / "actor_validation" / "actor_alignment_diagnostics.json"
DEFAULT_OUTPUT_CSV = PROJECT_ROOT / "rt_out" / "actor_validation" / "actor_alignment_diagnostics.csv"
CENTER_ROOT_OFFSET_WARN = 0.75
BOUNDS_OVER_ROOT_RATIO_WARN = 3.0
TURN_YAW_DELTA_RADIANS = 0.05
TURN_ROOT_MOVE_METERS = 0.20
ANIMATION_WRAP_DROP_SECONDS = 2.0


class ActorAlignmentDiagnosticError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Diagnose actor root/mesh alignment drift.")
    parser.add_argument("--mesh-index", type=Path, default=DEFAULT_MESH_INDEX)
    parser.add_argument("--worker-summary", type=Path, default=DEFAULT_WORKER_SUMMARY)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    path = path.expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def load_json(path: Path, label: str, *, required: bool = True) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        if required:
            raise ActorAlignmentDiagnosticError(f"Missing {label}: {path}") from exc
        return None
    except json.JSONDecodeError as exc:
        raise ActorAlignmentDiagnosticError(f"Invalid JSON in {label} {path}: {exc}") from exc


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ActorAlignmentDiagnosticError(f"{label} must be an object")
    return value


def finite_vec(values: Any, length: int, label: str) -> list[float]:
    if not isinstance(values, list) or len(values) != length:
        raise ActorAlignmentDiagnosticError(f"{label} must contain {length} values")
    try:
        out = [float(item) for item in values]
    except (TypeError, ValueError) as exc:
        raise ActorAlignmentDiagnosticError(f"{label} contains non-numeric values") from exc
    if any(not math.isfinite(item) for item in out):
        raise ActorAlignmentDiagnosticError(f"{label} contains non-finite values")
    return out


def center(bounds_min: list[float], bounds_max: list[float]) -> list[float]:
    return [(bounds_min[i] + bounds_max[i]) * 0.5 for i in range(3)]


def dist_xy(a: list[float], b: list[float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def dist_xyz(a: list[float], b: list[float]) -> float:
    return math.sqrt(sum((b[i] - a[i]) ** 2 for i in range(3)))


def norm_angle(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def yaw_delta(previous: float, current: float) -> float:
    return norm_angle(current - previous)


def worker_exports_by_id(worker_summary: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(worker_summary, dict):
        return {}
    exports = worker_summary.get("exports")
    if not isinstance(exports, list):
        return {}
    return {str(export.get("id")): export for export in exports if isinstance(export, dict)}


def build_records(mesh_index: dict[str, Any], worker_summary: Any) -> list[dict[str, Any]]:
    entries = mesh_index.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ActorAlignmentDiagnosticError("mesh index must contain a non-empty entries list")
    worker_by_id = worker_exports_by_id(worker_summary)

    records = []
    for index, raw_entry in enumerate(entries):
        entry = require_object(raw_entry, f"entries[{index}]")
        root_pose6 = finite_vec(entry.get("root_pose6"), 6, f"entries[{index}].root_pose6")
        bounds_min = finite_vec(entry.get("bounds_min"), 3, f"entries[{index}].bounds_min")
        bounds_max = finite_vec(entry.get("bounds_max"), 3, f"entries[{index}].bounds_max")
        bounds_center = center(bounds_min, bounds_max)
        root_xy = [root_pose6[0], root_pose6[1]]
        center_xy = [bounds_center[0], bounds_center[1]]
        vector = [center_xy[0] - root_xy[0], center_xy[1] - root_xy[1]]
        worker = worker_by_id.get(str(entry.get("id")), {})
        record = {
            "id": entry.get("id"),
            "validation_frame_id": int(entry.get("validation_frame_id")),
            "actor_name": entry.get("actor_name"),
            "actor_time_seconds": float(entry.get("actor_time_seconds")),
            "animation_time_seconds": float(entry.get("animation_time_seconds")),
            "root_pose6": root_pose6,
            "yaw": root_pose6[5],
            "bounds_min": bounds_min,
            "bounds_max": bounds_max,
            "bounds_center": bounds_center,
            "center_root_vector_xy": vector,
            "center_root_horizontal_distance": math.hypot(vector[0], vector[1]),
            "root_pose_source": entry.get("root_pose_source"),
            "neighbor_waypoint_times": entry.get("neighbor_waypoint_times"),
            "worker_sampled_blender_frame": worker.get("sampled_blender_frame"),
            "worker_applied_combined_matrix": worker.get("applied_combined_matrix"),
            "is_turn_segment": False,
            "frame_to_frame_root_movement": None,
            "frame_to_frame_bounds_center_movement": None,
            "bounds_center_over_root_movement_ratio": None,
            "yaw_delta_from_previous": None,
            "animation_loop_wrap": False,
            "warnings": [],
        }
        records.append(record)

    records.sort(key=lambda item: item["validation_frame_id"])
    for previous, current in zip(records, records[1:]):
        root_move = dist_xy(previous["root_pose6"], current["root_pose6"])
        center_move = dist_xyz(previous["bounds_center"], current["bounds_center"])
        dyaw = yaw_delta(previous["yaw"], current["yaw"])
        ratio = center_move / root_move if root_move > 1e-9 else (math.inf if center_move > 1e-9 else 0.0)
        current["frame_to_frame_root_movement"] = root_move
        current["frame_to_frame_bounds_center_movement"] = center_move
        current["bounds_center_over_root_movement_ratio"] = ratio
        current["yaw_delta_from_previous"] = dyaw
        current["animation_loop_wrap"] = (
            current["animation_time_seconds"] + ANIMATION_WRAP_DROP_SECONDS
            < previous["animation_time_seconds"]
        )
        current["is_turn_segment"] = root_move < TURN_ROOT_MOVE_METERS and abs(dyaw) > TURN_YAW_DELTA_RADIANS

    for record in records:
        if record["center_root_horizontal_distance"] > CENTER_ROOT_OFFSET_WARN:
            record["warnings"].append(
                f"center-root horizontal offset {record['center_root_horizontal_distance']:.3f}m > {CENTER_ROOT_OFFSET_WARN:.2f}m"
            )
        ratio = record["bounds_center_over_root_movement_ratio"]
        if isinstance(ratio, float) and math.isfinite(ratio) and ratio > BOUNDS_OVER_ROOT_RATIO_WARN:
            record["warnings"].append(
                f"bounds-center movement/root movement ratio {ratio:.3f} > {BOUNDS_OVER_ROOT_RATIO_WARN:.1f}"
            )
        if record["is_turn_segment"] and record["center_root_horizontal_distance"] > CENTER_ROOT_OFFSET_WARN:
            record["warnings"].append("turn segment with large center drift")
        if record["animation_loop_wrap"] and (
            record["frame_to_frame_bounds_center_movement"] or 0.0
        ) > 0.75:
            record["warnings"].append("sudden center jump near animation loop wrap")
    return records


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "validation_frame_id",
        "actor_name",
        "actor_time_seconds",
        "animation_time_seconds",
        "root_x",
        "root_y",
        "root_z",
        "yaw",
        "bounds_center_x",
        "bounds_center_y",
        "bounds_center_z",
        "center_root_dx",
        "center_root_dy",
        "center_root_horizontal_distance",
        "frame_to_frame_root_movement",
        "frame_to_frame_bounds_center_movement",
        "bounds_center_over_root_movement_ratio",
        "yaw_delta_from_previous",
        "is_turn_segment",
        "animation_loop_wrap",
        "root_pose_source",
        "warnings",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            writer.writerow(
                {
                    "validation_frame_id": record["validation_frame_id"],
                    "actor_name": record["actor_name"],
                    "actor_time_seconds": record["actor_time_seconds"],
                    "animation_time_seconds": record["animation_time_seconds"],
                    "root_x": record["root_pose6"][0],
                    "root_y": record["root_pose6"][1],
                    "root_z": record["root_pose6"][2],
                    "yaw": record["yaw"],
                    "bounds_center_x": record["bounds_center"][0],
                    "bounds_center_y": record["bounds_center"][1],
                    "bounds_center_z": record["bounds_center"][2],
                    "center_root_dx": record["center_root_vector_xy"][0],
                    "center_root_dy": record["center_root_vector_xy"][1],
                    "center_root_horizontal_distance": record["center_root_horizontal_distance"],
                    "frame_to_frame_root_movement": record["frame_to_frame_root_movement"],
                    "frame_to_frame_bounds_center_movement": record["frame_to_frame_bounds_center_movement"],
                    "bounds_center_over_root_movement_ratio": record["bounds_center_over_root_movement_ratio"],
                    "yaw_delta_from_previous": record["yaw_delta_from_previous"],
                    "is_turn_segment": record["is_turn_segment"],
                    "animation_loop_wrap": record["animation_loop_wrap"],
                    "root_pose_source": record["root_pose_source"],
                    "warnings": " | ".join(record["warnings"]),
                }
            )


def compact_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "validation_frame_id": record["validation_frame_id"],
        "actor_time_seconds": record["actor_time_seconds"],
        "animation_time_seconds": record["animation_time_seconds"],
        "center_root_horizontal_distance": record["center_root_horizontal_distance"],
        "center_root_vector_xy": record["center_root_vector_xy"],
        "frame_to_frame_root_movement": record["frame_to_frame_root_movement"],
        "frame_to_frame_bounds_center_movement": record["frame_to_frame_bounds_center_movement"],
        "bounds_center_over_root_movement_ratio": record["bounds_center_over_root_movement_ratio"],
        "yaw": record["yaw"],
        "yaw_delta_from_previous": record["yaw_delta_from_previous"],
        "is_turn_segment": record["is_turn_segment"],
        "animation_loop_wrap": record["animation_loop_wrap"],
        "warnings": record["warnings"],
    }


def build_diagnostics(records: list[dict[str, Any]], worker_summary_path: Path | None) -> dict[str, Any]:
    worst_offsets = sorted(records, key=lambda item: item["center_root_horizontal_distance"], reverse=True)[:10]
    worst_jumps = sorted(
        [record for record in records if record["frame_to_frame_bounds_center_movement"] is not None],
        key=lambda item: item["frame_to_frame_bounds_center_movement"],
        reverse=True,
    )[:10]
    flagged = [record for record in records if record["warnings"]]
    frame14 = next((record for record in records if record["validation_frame_id"] == 14), None)
    return {
        "generated_by": Path(__file__).name,
        "worker_summary": str(worker_summary_path) if worker_summary_path else None,
        "summary": {
            "record_count": len(records),
            "warning_frame_count": len(flagged),
            "max_center_root_horizontal_distance": max(record["center_root_horizontal_distance"] for record in records),
            "max_frame_to_frame_bounds_center_movement": max(
                record["frame_to_frame_bounds_center_movement"] or 0.0 for record in records
            ),
            "max_bounds_center_over_root_movement_ratio_finite": max(
                [
                    record["bounds_center_over_root_movement_ratio"]
                    for record in records
                    if isinstance(record["bounds_center_over_root_movement_ratio"], float)
                    and math.isfinite(record["bounds_center_over_root_movement_ratio"])
                ]
                or [0.0]
            ),
            "turn_segment_count": sum(1 for record in records if record["is_turn_segment"]),
            "animation_loop_wrap_count": sum(1 for record in records if record["animation_loop_wrap"]),
            "frame_14_flagged": bool(frame14 and frame14["warnings"]),
            "frame_14": compact_record(frame14) if frame14 else None,
        },
        "worst_center_root_offsets": [compact_record(record) for record in worst_offsets],
        "worst_bounds_center_jumps": [compact_record(record) for record in worst_jumps],
        "records": records,
    }


def main() -> int:
    args = parse_args()
    mesh_index_path = resolve_path(args.mesh_index)
    worker_summary_path = resolve_path(args.worker_summary)
    output_json = resolve_path(args.output_json)
    output_csv = resolve_path(args.output_csv)
    mesh_index = require_object(load_json(mesh_index_path, "mesh index"), "mesh index")
    worker_summary = load_json(worker_summary_path, "worker summary", required=False)
    records = build_records(mesh_index, worker_summary)
    diagnostics = build_diagnostics(records, worker_summary_path if worker_summary else None)
    save_json(output_json, diagnostics)
    write_csv(output_csv, records)

    print("Actor validation alignment diagnostics")
    print(f"mesh_index: {mesh_index_path}")
    print(f"output_json: {output_json}")
    print(f"output_csv: {output_csv}")
    print(f"record_count: {diagnostics['summary']['record_count']}")
    print(f"warning_frame_count: {diagnostics['summary']['warning_frame_count']}")
    print(f"max_center_root_horizontal_distance: {diagnostics['summary']['max_center_root_horizontal_distance']:.6f}")
    print(f"max_frame_to_frame_bounds_center_movement: {diagnostics['summary']['max_frame_to_frame_bounds_center_movement']:.6f}")
    print(f"turn_segment_count: {diagnostics['summary']['turn_segment_count']}")
    print(f"animation_loop_wrap_count: {diagnostics['summary']['animation_loop_wrap_count']}")
    print(f"frame_14_flagged: {diagnostics['summary']['frame_14_flagged']}")
    print("Worst 10 center-root offsets:")
    for record in diagnostics["worst_center_root_offsets"]:
        print(
            f"  frame {record['validation_frame_id']:03d}: "
            f"offset={record['center_root_horizontal_distance']:.3f} "
            f"vector={record['center_root_vector_xy']} warnings={len(record['warnings'])}"
        )
    print("Worst 10 bounds-center jumps:")
    for record in diagnostics["worst_bounds_center_jumps"]:
        print(
            f"  frame {record['validation_frame_id']:03d}: "
            f"jump={record['frame_to_frame_bounds_center_movement']:.3f} "
            f"root_move={record['frame_to_frame_root_movement']:.3f} "
            f"wrap={record['animation_loop_wrap']} warnings={len(record['warnings'])}"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ActorAlignmentDiagnosticError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
