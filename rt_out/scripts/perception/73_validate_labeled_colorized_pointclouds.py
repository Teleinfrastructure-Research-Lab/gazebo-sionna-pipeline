#!/usr/bin/env python3
"""Validate final fully labeled RGB point clouds."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = PROJECT_ROOT / "rt_out/experiments/perception_rt_small_v0/configs/perception_dataset_config.json"
EXPECTED_PROPERTY_NAMES = ["x", "y", "z", "red", "green", "blue", "class_label", "instance_id"]
EXPECTED_PROPERTY_LINES = [
    "property float x",
    "property float y",
    "property float z",
    "property uchar red",
    "property uchar green",
    "property uchar blue",
    "property ushort class_label",
    "property int instance_id",
]
FORBIDDEN_FIELDS = {"pixel_u", "pixel_v", "compact_instance_label", "gazebo_instance_count", "confidence"}
INVALID_ROW_FIELDS = [
    "selected_frame_id",
    "camera_id",
    "issue",
    "output_labeled_pcl_path",
    "point_count",
]


class ValidationError(RuntimeError):
    """Raised when labeled point-cloud outputs fail strict validation."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate final fully labeled RGB point clouds."
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Perception dataset config JSON.")
    parser.add_argument(
        "--labeled-root",
        type=Path,
        default=None,
        help="Root directory containing final labeled point-cloud outputs.",
    )
    parser.add_argument(
        "--expected-cloud-count",
        type=int,
        required=True,
        help="Expected number of valid labeled point clouds.",
    )
    parser.add_argument(
        "--min-points-per-cloud",
        type=int,
        default=1000,
        help="Minimum point count required per final labeled cloud.",
    )
    return parser.parse_args()


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def resolve_path(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


def project_rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def parse_int(value: Any, label: str) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"Could not parse integer for {label}: {value!r}") from exc


def load_json(path: Path, label: str) -> Any:
    if not path.is_file():
        raise ValidationError(f"Missing {label}: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Failed to parse {label} JSON at {path}: {exc}") from exc


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=False)
        handle.write("\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=INVALID_ROW_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def load_config_and_paths(config_path: Path) -> tuple[Path, Path]:
    payload = load_json(config_path, "perception dataset config")
    if not isinstance(payload, dict):
        raise ValidationError(f"Perception dataset config at {config_path} must be a JSON object.")
    experiment_root = config_path.resolve().parents[1]
    stable_map_path = experiment_root / "perception_sdf" / "stable_instance_label_map.json"
    return experiment_root, stable_map_path


def build_instance_lookup(stable_map_path: Path) -> tuple[dict[int, int], set[int]]:
    payload = load_json(stable_map_path, "stable instance label map")
    if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list):
        raise ValidationError(f"Stable instance label map at {stable_map_path} must contain an 'entries' list.")
    semantic_by_instance: dict[int, int] = {}
    known_instance_ids: set[int] = set()
    for entry in payload["entries"]:
        if not isinstance(entry, dict):
            raise ValidationError(f"Stable map entry is not an object: {entry!r}")
        instance_id = parse_int(entry.get("stable_instance_id"), "stable_instance_id")
        semantic_id = parse_int(entry.get("semantic_id"), "semantic_id")
        if not (1 <= semantic_id <= 10):
            raise ValidationError(f"semantic_id must be in 1..10 in {stable_map_path}: {semantic_id}")
        if instance_id <= 0:
            raise ValidationError(f"stable_instance_id must be positive in {stable_map_path}: {instance_id}")
        semantic_by_instance[instance_id] = semantic_id
        known_instance_ids.add(instance_id)
    return semantic_by_instance, known_instance_ids


def load_index_rows(index_path: Path) -> list[dict[str, Any]]:
    if not index_path.is_file():
        raise ValidationError(f"Missing labeled point-cloud index CSV: {index_path}")
    with index_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValidationError(f"Labeled point-cloud index CSV is empty: {index_path}")
    return rows


def parse_ply_header(path: Path) -> tuple[int, list[str], list[str], int]:
    with path.open("r", encoding="utf-8") as handle:
        if handle.readline().strip() != "ply":
            raise ValidationError(f"PLY at {path} must start with 'ply'")
        if handle.readline().strip() != "format ascii 1.0":
            raise ValidationError(f"Only ASCII PLY is supported at {path}")

        header_lines = 2
        vertex_count: int | None = None
        property_names: list[str] = []
        property_lines: list[str] = []
        in_vertex = False
        while True:
            line = handle.readline()
            if not line:
                raise ValidationError(f"Incomplete PLY header at {path}")
            header_lines += 1
            stripped = line.strip()
            if stripped == "end_header":
                break
            if stripped.startswith("element "):
                parts = stripped.split()
                in_vertex = len(parts) >= 3 and parts[1] == "vertex"
                if in_vertex:
                    vertex_count = parse_int(parts[2], "element vertex count")
                continue
            if stripped.startswith("property ") and in_vertex:
                property_lines.append(stripped)
                property_names.append(stripped.split()[-1])
        if vertex_count is None:
            raise ValidationError(f"PLY at {path} is missing an element vertex declaration")
        return vertex_count, property_names, property_lines, header_lines


def validate_ply_rows(
    path: Path,
    header_lines: int,
    expected_vertex_count: int,
    semantic_by_instance: dict[int, int],
    known_instance_ids: set[int],
) -> tuple[int, set[int], set[int]]:
    total_points = 0
    class_labels: set[int] = set()
    instance_ids: set[int] = set()
    with path.open("r", encoding="utf-8") as handle:
        for _ in range(header_lines):
            next(handle, None)
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.split()
            if len(parts) != 8:
                raise ValidationError(f"PLY row at {path} has {len(parts)} columns; expected 8")
            try:
                x = float(parts[0])
                y = float(parts[1])
                z = float(parts[2])
                red = int(parts[3])
                green = int(parts[4])
                blue = int(parts[5])
                class_label = int(parts[6])
                instance_id = int(parts[7])
            except ValueError as exc:
                raise ValidationError(f"PLY row at {path} contains non-numeric values") from exc
            if not all(math.isfinite(value) for value in (x, y, z)):
                raise ValidationError(f"PLY row at {path} contains non-finite xyz values")
            if not (0 <= red <= 255 and 0 <= green <= 255 and 0 <= blue <= 255):
                raise ValidationError(f"PLY row at {path} contains RGB values outside 0..255")
            if not (1 <= class_label <= 10):
                raise ValidationError(f"PLY row at {path} contains class_label outside 1..10: {class_label}")
            if instance_id <= 0:
                raise ValidationError(f"PLY row at {path} contains non-positive instance_id: {instance_id}")
            if instance_id not in known_instance_ids:
                raise ValidationError(f"PLY row at {path} contains unknown instance_id: {instance_id}")
            if semantic_by_instance[instance_id] != class_label:
                raise ValidationError(
                    f"PLY row at {path} has mismatched class_label/instance_id: "
                    f"class_label={class_label}, instance_id={instance_id}, expected semantic_id={semantic_by_instance[instance_id]}"
                )
            class_labels.add(class_label)
            instance_ids.add(instance_id)
            total_points += 1
    if total_points != expected_vertex_count:
        raise ValidationError(
            f"PLY at {path} declared {expected_vertex_count} vertices but contained {total_points} rows"
        )
    return total_points, class_labels, instance_ids


def row_path(labeled_root: Path, row_value: str) -> Path:
    candidate = Path(row_value)
    if candidate.is_absolute():
        return candidate
    return PROJECT_ROOT / candidate


def main() -> None:
    args = parse_args()
    if args.expected_cloud_count <= 0:
        fail("--expected-cloud-count must be positive.")
    if args.min_points_per_cloud <= 0:
        fail("--min-points-per-cloud must be positive.")

    config_path = resolve_path(args.config)
    if not config_path.is_file():
        fail(f"Missing perception dataset config: {config_path}")
    experiment_root, stable_map_path = load_config_and_paths(config_path)
    labeled_root = resolve_path(args.labeled_root) if args.labeled_root is not None else (experiment_root / "reconstruction" / "labeled_colorized_pcl_sync")
    if not labeled_root.is_dir():
        fail(f"Missing labeled point-cloud root: {labeled_root}")

    semantic_by_instance, known_instance_ids = build_instance_lookup(stable_map_path)
    index_path = labeled_root / "labeled_colorized_pcl_index.csv"
    summary_path = labeled_root / "labeled_colorized_pcl_summary.json"
    validation_root = experiment_root / "validation"
    validation_summary_path = validation_root / "labeled_colorized_pcl_validation_summary.json"
    invalid_rows_path = validation_root / "labeled_colorized_pcl_invalid_rows.csv"

    index_rows = load_index_rows(index_path)
    source_summary = load_json(summary_path, "labeled point-cloud summary")
    if not isinstance(source_summary, dict):
        fail(f"Labeled point-cloud summary at {summary_path} must be a JSON object.")

    invalid_rows: list[dict[str, Any]] = []
    total_points = 0
    zero_label_point_count = 0
    unknown_label_point_count = 0
    min_points_per_cloud: int | None = None
    max_points_per_cloud = 0
    unique_class_labels_observed: set[int] = set()
    unique_instance_ids_observed: set[int] = set()

    ok_rows = [row for row in index_rows if row.get("status") == "ok"]
    if len(ok_rows) != args.expected_cloud_count:
        invalid_rows.append(
            {
                "selected_frame_id": "",
                "camera_id": "",
                "issue": f"expected {args.expected_cloud_count} ok rows but found {len(ok_rows)}",
                "output_labeled_pcl_path": "",
                "point_count": "0",
            }
        )

    for row in index_rows:
        selected_frame_id = row.get("selected_frame_id", "")
        camera_id = row.get("camera_id", "")
        status = row.get("status", "")
        zero_count = parse_int(row.get("zero_label_point_count", 0), "zero_label_point_count")
        unknown_count = parse_int(row.get("unknown_label_point_count", 0), "unknown_label_point_count")
        zero_label_point_count += zero_count
        unknown_label_point_count += unknown_count

        if status != "ok":
            invalid_rows.append(
                {
                    "selected_frame_id": selected_frame_id,
                    "camera_id": camera_id,
                    "issue": f"index status is not ok: {status}",
                    "output_labeled_pcl_path": row.get("output_labeled_pcl_path", ""),
                    "point_count": row.get("point_count", "0"),
                }
            )
            continue

        if zero_count != 0:
            invalid_rows.append(
                {
                    "selected_frame_id": selected_frame_id,
                    "camera_id": camera_id,
                    "issue": f"zero_label_point_count must be 0, got {zero_count}",
                    "output_labeled_pcl_path": row.get("output_labeled_pcl_path", ""),
                    "point_count": row.get("point_count", "0"),
                }
            )
            continue
        if unknown_count != 0:
            invalid_rows.append(
                {
                    "selected_frame_id": selected_frame_id,
                    "camera_id": camera_id,
                    "issue": f"unknown_label_point_count must be 0, got {unknown_count}",
                    "output_labeled_pcl_path": row.get("output_labeled_pcl_path", ""),
                    "point_count": row.get("point_count", "0"),
                }
            )
            continue

        output_path_value = row.get("output_labeled_pcl_path", "")
        if not isinstance(output_path_value, str) or not output_path_value.strip():
            invalid_rows.append(
                {
                    "selected_frame_id": selected_frame_id,
                    "camera_id": camera_id,
                    "issue": "missing output_labeled_pcl_path for ok row",
                    "output_labeled_pcl_path": "",
                    "point_count": row.get("point_count", "0"),
                }
            )
            continue
        output_path = row_path(labeled_root, output_path_value)
        if not output_path.is_file():
            invalid_rows.append(
                {
                    "selected_frame_id": selected_frame_id,
                    "camera_id": camera_id,
                    "issue": f"missing output PLY: {output_path}",
                    "output_labeled_pcl_path": output_path_value,
                    "point_count": row.get("point_count", "0"),
                }
            )
            continue

        try:
            expected_point_count = parse_int(row.get("point_count", 0), "point_count")
            vertex_count, property_names, property_lines, header_lines = parse_ply_header(output_path)
            if property_names != EXPECTED_PROPERTY_NAMES:
                raise ValidationError(
                    f"PLY at {output_path} must have exactly these fields: {EXPECTED_PROPERTY_NAMES}; got {property_names}"
                )
            if property_lines != EXPECTED_PROPERTY_LINES:
                raise ValidationError(
                    f"PLY at {output_path} must use the exact final property lines {EXPECTED_PROPERTY_LINES}; got {property_lines}"
                )
            if any(field in property_names for field in FORBIDDEN_FIELDS):
                raise ValidationError(f"PLY at {output_path} contains forbidden fields")
            point_count, class_labels, instance_ids = validate_ply_rows(
                output_path,
                header_lines,
                vertex_count,
                semantic_by_instance,
                known_instance_ids,
            )
            if point_count != expected_point_count:
                raise ValidationError(
                    f"PLY point count mismatch for {output_path}: index={expected_point_count}, ply={point_count}"
                )
            if point_count < args.min_points_per_cloud:
                raise ValidationError(
                    f"PLY at {output_path} has {point_count} points, below minimum {args.min_points_per_cloud}"
                )
            total_points += point_count
            unique_class_labels_observed.update(class_labels)
            unique_instance_ids_observed.update(instance_ids)
            min_points_per_cloud = point_count if min_points_per_cloud is None else min(min_points_per_cloud, point_count)
            max_points_per_cloud = max(max_points_per_cloud, point_count)
        except ValidationError as exc:
            invalid_rows.append(
                {
                    "selected_frame_id": selected_frame_id,
                    "camera_id": camera_id,
                    "issue": str(exc),
                    "output_labeled_pcl_path": output_path_value,
                    "point_count": row.get("point_count", "0"),
                }
            )

    summary_total_points = parse_int(source_summary.get("total_points_written", 0), "summary total_points_written")
    if total_points != summary_total_points:
        invalid_rows.append(
            {
                "selected_frame_id": "",
                "camera_id": "",
                "issue": f"summary total_points_written mismatch: summary={summary_total_points}, validated={total_points}",
                "output_labeled_pcl_path": "",
                "point_count": str(total_points),
            }
        )

    summary_zero = parse_int(source_summary.get("zero_label_point_count", 0), "summary zero_label_point_count")
    summary_unknown = parse_int(source_summary.get("unknown_label_point_count", 0), "summary unknown_label_point_count")
    if summary_zero != 0:
        invalid_rows.append(
            {
                "selected_frame_id": "",
                "camera_id": "",
                "issue": f"summary zero_label_point_count must be 0, got {summary_zero}",
                "output_labeled_pcl_path": "",
                "point_count": "0",
            }
        )
    if summary_unknown != 0:
        invalid_rows.append(
            {
                "selected_frame_id": "",
                "camera_id": "",
                "issue": f"summary unknown_label_point_count must be 0, got {summary_unknown}",
                "output_labeled_pcl_path": "",
                "point_count": "0",
            }
        )

    summary_classes = sorted(parse_int(value, "summary unique class label") for value in source_summary.get("unique_class_labels_observed", []))
    summary_instances = sorted(parse_int(value, "summary unique instance id") for value in source_summary.get("unique_instance_ids_observed", []))
    if summary_classes != sorted(unique_class_labels_observed):
        invalid_rows.append(
            {
                "selected_frame_id": "",
                "camera_id": "",
                "issue": f"summary unique_class_labels_observed mismatch: summary={summary_classes}, validated={sorted(unique_class_labels_observed)}",
                "output_labeled_pcl_path": "",
                "point_count": "0",
            }
        )
    if summary_instances != sorted(unique_instance_ids_observed):
        invalid_rows.append(
            {
                "selected_frame_id": "",
                "camera_id": "",
                "issue": f"summary unique_instance_ids_observed mismatch: summary={summary_instances}, validated={sorted(unique_instance_ids_observed)}",
                "output_labeled_pcl_path": "",
                "point_count": "0",
            }
        )

    validation_summary = {
        "experiment_name": "perception_rt_small_v0",
        "expected_cloud_count": args.expected_cloud_count,
        "actual_cloud_count": len(ok_rows),
        "overall_passed": len(invalid_rows) == 0,
        "failure_count": len(invalid_rows),
        "invalid_row_count": len(invalid_rows),
        "total_points": total_points,
        "zero_label_point_count": zero_label_point_count,
        "unknown_label_point_count": unknown_label_point_count,
        "unique_class_labels_observed": sorted(unique_class_labels_observed),
        "unique_instance_ids_observed": sorted(unique_instance_ids_observed),
        "min_points_per_cloud": min_points_per_cloud or 0,
        "max_points_per_cloud": max_points_per_cloud,
    }
    write_json(validation_summary_path, validation_summary)
    write_csv(invalid_rows_path, invalid_rows)

    print(f"actual_cloud_count={len(ok_rows)}")
    print(f"overall_passed={validation_summary['overall_passed']}")
    print(f"failure_count={validation_summary['failure_count']}")
    print(f"invalid_row_count={validation_summary['invalid_row_count']}")
    print(f"total_points={total_points}")


if __name__ == "__main__":
    main()
