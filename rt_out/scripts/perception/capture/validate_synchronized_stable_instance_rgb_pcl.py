#!/usr/bin/env python3
"""Validate synchronized stable-instance panoptic label, RGB, and PCL captures."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CONFIG = PROJECT_ROOT / "rt_out/experiments/perception_rt_small_v0/run_20260522_133045/config/perception_dataset_config.json"
REQUIRED_CAPTURE_SUBDIRS = (
    "labels_maps_rgb",
    "compact_instance_label",
    "gazebo_instance_count",
    "rgb",
    "ply",
    "metadata",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate synchronized stable-instance label/RGB/PCL capture outputs."
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Perception dataset config JSON.")
    parser.add_argument("--expected-groups-per-camera", type=int, default=3, help="Expected synchronized group count per camera.")
    parser.add_argument("--min-points-per-cloud", type=int, default=1000, help="Minimum point count required per synchronized PLY.")
    parser.add_argument("--max-sync-delta-ms", type=float, default=50.0, help="Maximum allowed label/RGB/PCL timestamp delta in milliseconds.")
    return parser.parse_args()


def fail(message: str) -> None:
    raise SystemExit(f"ERROR: {message}")


def load_json(path: Path, label: str) -> Any:
    if not path.is_file():
        fail(f"Missing {label}: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        fail(f"Failed to parse {label} JSON at {path}: {exc}")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=False)
        handle.write("\n")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def project_rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def load_camera_rig(path: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    payload = load_json(path, "camera rig")
    if not isinstance(payload, dict) or not isinstance(payload.get("cameras"), list):
        fail(f"Camera rig file at {path} must contain a 'cameras' list.")
    camera_map: dict[str, dict[str, Any]] = {}
    for camera in payload["cameras"]:
        if not isinstance(camera, dict):
            fail(f"Camera rig entry is not an object: {camera!r}")
        camera_id = camera.get("camera_id")
        if not isinstance(camera_id, str) or not camera_id.strip():
            fail(f"Camera rig entry missing a valid camera_id: {camera!r}")
        camera_map[camera_id] = camera
    requested_ids = config.get("camera_ids")
    if not isinstance(requested_ids, list) or not requested_ids or not all(isinstance(item, str) and item.strip() for item in requested_ids):
        fail("Config field 'camera_ids' must be a non-empty list of camera IDs.")
    return [camera_map[camera_id] for camera_id in requested_ids]


def load_metadata_rows(metadata_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not metadata_dir.is_dir():
        return rows
    for metadata_path in sorted(metadata_dir.glob("sync_*.json")):
        payload = load_json(metadata_path, f"metadata {metadata_path}")
        if not isinstance(payload, dict):
            fail(f"Metadata file at {metadata_path} must be a JSON object.")
        payload["_metadata_path"] = metadata_path
        rows.append(payload)
    return rows


def parse_ply_header(path: Path) -> tuple[int | None, list[str], int]:
    if not path.is_file():
        return None, [], 0
    vertex_count: int | None = None
    property_names: list[str] = []
    header_lines = 0
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            header_lines += 1
            stripped = line.strip()
            if stripped.startswith("element vertex "):
                try:
                    vertex_count = int(stripped.split()[2])
                except (IndexError, ValueError):
                    vertex_count = None
            elif stripped.startswith("property "):
                parts = stripped.split()
                if len(parts) >= 3:
                    property_names.append(parts[2])
            elif stripped == "end_header":
                break
    return vertex_count, property_names, header_lines


def validate_ply_rows(path: Path, header_lines: int, width: int, height: int) -> tuple[list[str], int]:
    issues: list[str] = []
    row_count = 0
    with path.open("r", encoding="utf-8") as handle:
        for _ in range(header_lines):
            next(handle, None)
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            parts = stripped.split()
            if len(parts) < 8:
                issues.append("PLY vertex row has fewer than 8 columns")
                break
            try:
                xyz = [float(parts[0]), float(parts[1]), float(parts[2])]
                pixel_u = int(parts[6])
                pixel_v = int(parts[7])
            except ValueError:
                issues.append("PLY vertex row has non-numeric xyz or pixel coordinates")
                break
            if not all(math.isfinite(value) for value in xyz):
                issues.append("PLY vertex row contains non-finite xyz values")
                break
            if not (0 <= pixel_u < width) or not (0 <= pixel_v < height):
                issues.append(
                    f"PLY pixel coordinates out of bounds: u={pixel_u}, v={pixel_v}, width={width}, height={height}"
                )
                break
            row_count += 1
    return issues, row_count


def _read_token(handle) -> bytes:
    token = bytearray()
    while True:
        char = handle.read(1)
        if not char:
            break
        if char == b"#":
            handle.readline()
            continue
        if char.isspace():
            if token:
                break
            continue
        token.extend(char)
    return bytes(token)


def read_pnm(path: Path) -> tuple[str, int, int, int, bytes]:
    with path.open("rb") as handle:
        magic = _read_token(handle)
        if magic not in {b"P5", b"P6"}:
            raise ValueError(f"Unsupported PNM magic {magic!r} at {path}")
        width = int(_read_token(handle))
        height = int(_read_token(handle))
        max_value = int(_read_token(handle))
        payload = handle.read()
    return magic.decode("ascii"), width, height, max_value, payload


def compact_mask_stats(path: Path, known_labels: set[int]) -> tuple[int, int, int, float]:
    magic, width, height, max_value, payload = read_pnm(path)
    if magic != "P5":
        raise ValueError(f"Compact label mask must be P5 PGM at {path}, got {magic}")
    if max_value > 255:
        raise ValueError(f"Compact label mask max value must be <=255 at {path}, got {max_value}")
    expected_size = width * height
    if len(payload) != expected_size:
        raise ValueError(
            f"Compact label mask size mismatch at {path}: expected {expected_size} bytes, got {len(payload)}"
        )
    zero_count = 0
    nonzero_count = 0
    unknown_count = 0
    for value in payload:
        if value == 0:
            zero_count += 1
            continue
        nonzero_count += 1
        if int(value) not in known_labels:
            unknown_count += 1
    nonzero_ratio = nonzero_count / expected_size if expected_size else 0.0
    return width, height, unknown_count, nonzero_ratio


def validate_count_mask(path: Path) -> tuple[int, int]:
    magic, width, height, max_value, payload = read_pnm(path)
    if magic != "P5":
        raise ValueError(f"Gazebo instance count mask must be P5 PGM at {path}, got {magic}")
    if max_value > 65535:
        raise ValueError(f"Gazebo instance count mask max value must be <=65535 at {path}, got {max_value}")
    expected_size = width * height * (1 if max_value <= 255 else 2)
    if len(payload) != expected_size:
        raise ValueError(
            f"Gazebo instance count mask size mismatch at {path}: expected {expected_size} bytes, got {len(payload)}"
        )
    return width, height


def main() -> None:
    args = parse_args()
    if args.expected_groups_per_camera <= 0:
        fail("--expected-groups-per-camera must be positive.")
    if args.min_points_per_cloud <= 0:
        fail("--min-points-per-cloud must be positive.")
    if args.max_sync_delta_ms < 0.0:
        fail("--max-sync-delta-ms must be non-negative.")

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    config = load_json(config_path, "perception dataset config")
    if not isinstance(config, dict):
        fail(f"Perception dataset config at {config_path} must be a JSON object.")

    experiment_root = config_path.resolve().parents[1]
    print(f"experiment_root={experiment_root}")
    cameras = load_camera_rig(experiment_root / "config" / "camera_rig.json", config)
    camera_ids = [str(camera["camera_id"]) for camera in cameras]
    sync_root = experiment_root / "perception_raw" / "native" / "sync_stable_instance_rgb_pcl"
    validation_root = experiment_root / "validation"
    summary_path = validation_root / "sync_stable_instance_rgb_pcl_capture_validation_summary.json"
    invalid_rows_path = validation_root / "sync_stable_instance_rgb_pcl_invalid_rows.csv"
    stable_map_path = experiment_root / "perception_sdf" / "stable_instance_label_map.json"
    registry_path = experiment_root / "frames" / "instance_registry.json"

    stable_map = load_json(stable_map_path, "stable instance label map")
    if not isinstance(stable_map, dict) or not isinstance(stable_map.get("entries"), list):
        fail(f"Stable instance label map at {stable_map_path} must contain an 'entries' list.")
    known_labels: set[int] = set()
    semantic_lookup_by_stable_id: dict[int, tuple[int, str]] = {}
    for entry in stable_map["entries"]:
        if not isinstance(entry, dict):
            fail(f"stable_instance_label_map entry is not an object: {entry!r}")
        compact_label = int(entry.get("compact_instance_label", 0) or 0)
        stable_id = int(entry.get("stable_instance_id", 0) or 0)
        semantic_id = int(entry.get("semantic_id", 0) or 0)
        semantic_name = str(entry.get("semantic_name", ""))
        if compact_label > 0:
            known_labels.add(compact_label)
        if stable_id > 0 and semantic_id > 0 and semantic_name:
            semantic_lookup_by_stable_id[stable_id] = (semantic_id, semantic_name)

    registry_payload = load_json(registry_path, "instance registry")
    if not isinstance(registry_payload, dict) or not isinstance(registry_payload.get("instances"), list):
        fail(f"Instance registry at {registry_path} must contain an 'instances' list.")
    registry_semantics: dict[int, tuple[int, str]] = {}
    for instance in registry_payload["instances"]:
        if not isinstance(instance, dict):
            continue
        registry_semantics[int(instance["instance_id"])] = (
            int(instance["semantic_id"]),
            str(instance["semantic_name"]),
        )

    invalid_rows: list[dict[str, Any]] = []
    camera_summaries: list[dict[str, Any]] = []
    failure_count = 0
    actual_group_count = 0
    actual_labels_count = 0
    actual_rgb_count = 0
    actual_ply_count = 0
    actual_metadata_count = 0
    total_points_written = 0
    min_points_observed: int | None = None
    max_points_observed = 0
    min_delta_observed: float | None = None
    max_delta_observed: float | None = None
    nonzero_ratios: list[float] = []
    unknown_compact_label_count = 0

    if not sync_root.is_dir():
        fail(f"Synchronized stable-instance root does not exist: {sync_root}")

    for camera_id in camera_ids:
        camera_root = sync_root / camera_id
        missing_subdirs = [subdir for subdir in REQUIRED_CAPTURE_SUBDIRS if not (camera_root / subdir).is_dir()]
        metadata_rows = load_metadata_rows(camera_root / "metadata")
        labels_files = sorted((camera_root / "labels_maps_rgb").glob("*")) if (camera_root / "labels_maps_rgb").is_dir() else []
        rgb_files = sorted((camera_root / "rgb").glob("*")) if (camera_root / "rgb").is_dir() else []
        ply_files = sorted((camera_root / "ply").glob("*.ply")) if (camera_root / "ply").is_dir() else []
        actual_metadata_count += len(metadata_rows)
        actual_labels_count += len([path for path in labels_files if path.is_file()])
        actual_rgb_count += len([path for path in rgb_files if path.is_file()])
        actual_ply_count += len(ply_files)
        camera_failure_count = 0
        camera_unknown_labels = 0
        camera_nonzero_ratios: list[float] = []

        if missing_subdirs:
            camera_failure_count += len(missing_subdirs)
            for subdir in missing_subdirs:
                invalid_rows.append(
                    {
                        "camera_id": camera_id,
                        "group_index": "",
                        "issue": f"missing required subdir: {subdir}",
                        "metadata_path": "",
                        "labels_rgb_path": project_rel(camera_root / "labels_maps_rgb"),
                        "compact_instance_label_path": project_rel(camera_root / "compact_instance_label"),
                        "rgb_path": project_rel(camera_root / "rgb"),
                        "pcl_path": project_rel(camera_root / "ply"),
                        "point_count": "",
                        "max_time_delta_ms": "",
                    }
                )
        for label, found_count in (
            ("metadata rows", len(metadata_rows)),
            ("labels files", len(labels_files)),
            ("RGB files", len(rgb_files)),
            ("PLY files", len(ply_files)),
        ):
            if found_count != args.expected_groups_per_camera:
                camera_failure_count += 1
                invalid_rows.append(
                    {
                        "camera_id": camera_id,
                        "group_index": "",
                        "issue": f"expected {args.expected_groups_per_camera} {label}, found {found_count}",
                        "metadata_path": project_rel(camera_root / "metadata"),
                        "labels_rgb_path": project_rel(camera_root / "labels_maps_rgb"),
                        "compact_instance_label_path": project_rel(camera_root / "compact_instance_label"),
                        "rgb_path": project_rel(camera_root / "rgb"),
                        "pcl_path": project_rel(camera_root / "ply"),
                        "point_count": "",
                        "max_time_delta_ms": "",
                    }
                )

        for row in metadata_rows:
            issues: list[str] = []
            group_index = int(row.get("group_index", 0) or 0)
            labels_rgb_path = Path(str(row.get("labels_rgb_path", "")))
            compact_path = Path(str(row.get("compact_instance_label_path", "")))
            gazebo_count_path = Path(str(row.get("gazebo_instance_count_path", "")))
            rgb_path = Path(str(row.get("rgb_path", "")))
            ply_path = Path(str(row.get("pcl_path", "")))
            metadata_path = Path(str(row["_metadata_path"]))
            if not labels_rgb_path.is_absolute():
                labels_rgb_path = PROJECT_ROOT / labels_rgb_path
            if not compact_path.is_absolute():
                compact_path = PROJECT_ROOT / compact_path
            if not gazebo_count_path.is_absolute():
                gazebo_count_path = PROJECT_ROOT / gazebo_count_path
            if not rgb_path.is_absolute():
                rgb_path = PROJECT_ROOT / rgb_path
            if not ply_path.is_absolute():
                ply_path = PROJECT_ROOT / ply_path

            for required_path, label_name in (
                (labels_rgb_path, "labels_rgb_path"),
                (compact_path, "compact_instance_label_path"),
                (gazebo_count_path, "gazebo_instance_count_path"),
                (rgb_path, "rgb_path"),
                (ply_path, "pcl_path"),
            ):
                if not required_path.is_file():
                    issues.append(f"missing referenced file: {label_name}")

            width = int(row.get("width", 0) or 0)
            height = int(row.get("height", 0) or 0)
            point_count = int(row.get("written_point_count", row.get("point_count", 0)) or 0)
            delta_ms = float(row.get("max_time_delta_ms", 0.0) or 0.0)
            if delta_ms > args.max_sync_delta_ms:
                issues.append(
                    f"max_time_delta_ms {delta_ms:.6f} exceeds threshold {args.max_sync_delta_ms:.6f}"
                )
            if point_count < args.min_points_per_cloud:
                issues.append(
                    f"written_point_count {point_count} is below min threshold {args.min_points_per_cloud}"
                )
            if row.get("has_pixel_coordinates") is not True:
                issues.append("metadata has_pixel_coordinates is not true")
            if row.get("label_mode") != "compact_stable_instance":
                issues.append("metadata label_mode is not compact_stable_instance")

            if rgb_path.is_file():
                try:
                    rgb_magic, rgb_width, rgb_height, _, _ = read_pnm(rgb_path)
                    if rgb_magic != "P6":
                        issues.append(f"RGB image must be P6 PPM, got {rgb_magic}")
                    if rgb_width != width or rgb_height != height:
                        issues.append(
                            f"RGB dimensions {rgb_width}x{rgb_height} do not match metadata {width}x{height}"
                        )
                except ValueError as exc:
                    issues.append(str(exc))

            if compact_path.is_file():
                try:
                    compact_width, compact_height, unknown_count, nonzero_ratio = compact_mask_stats(compact_path, known_labels)
                    if compact_width != width or compact_height != height:
                        issues.append(
                            f"compact instance label dimensions {compact_width}x{compact_height} do not match metadata {width}x{height}"
                        )
                    camera_unknown_labels += unknown_count
                    unknown_compact_label_count += unknown_count
                    camera_nonzero_ratios.append(nonzero_ratio)
                    nonzero_ratios.append(nonzero_ratio)
                    if nonzero_ratio <= 0.0:
                        issues.append("compact instance label mask has no non-zero labels")
                except ValueError as exc:
                    issues.append(str(exc))

            if gazebo_count_path.is_file():
                try:
                    count_width, count_height = validate_count_mask(gazebo_count_path)
                    if count_width != width or count_height != height:
                        issues.append(
                            f"gazebo instance count dimensions {count_width}x{count_height} do not match metadata {width}x{height}"
                        )
                except ValueError as exc:
                    issues.append(str(exc))

            if ply_path.is_file():
                vertex_count, property_names, header_lines = parse_ply_header(ply_path)
                required_properties = {"x", "y", "z", "red", "green", "blue", "pixel_u", "pixel_v"}
                missing_properties = sorted(required_properties - set(property_names))
                if missing_properties:
                    issues.append(f"PLY header missing required properties: {', '.join(missing_properties)}")
                if vertex_count is None:
                    issues.append("PLY header is missing a valid vertex count")
                else:
                    if vertex_count != point_count:
                        issues.append(
                            f"PLY vertex count {vertex_count} does not match metadata point count {point_count}"
                        )
                if header_lines <= 0:
                    issues.append("PLY header was not parsed correctly")
                else:
                    row_issues, parsed_rows = validate_ply_rows(ply_path, header_lines, width, height)
                    issues.extend(row_issues)
                    if vertex_count is not None and parsed_rows != vertex_count:
                        issues.append(
                            f"Parsed PLY row count {parsed_rows} does not match vertex count {vertex_count}"
                        )

            actual_group_count += 1
            total_points_written += max(point_count, 0)
            min_points_observed = point_count if min_points_observed is None else min(min_points_observed, point_count)
            max_points_observed = max(max_points_observed, point_count)
            min_delta_observed = delta_ms if min_delta_observed is None else min(min_delta_observed, delta_ms)
            max_delta_observed = delta_ms if max_delta_observed is None else max(max_delta_observed, delta_ms)

            for stable_id, semantic in registry_semantics.items():
                recovered = semantic_lookup_by_stable_id.get(stable_id)
                if recovered is not None and recovered != semantic:
                    issues.append(
                        f"stable instance semantic mismatch for registry id {stable_id}: "
                        f"map={recovered[0]}:{recovered[1]} registry={semantic[0]}:{semantic[1]}"
                    )
                    break

            if issues:
                camera_failure_count += 1
                invalid_rows.append(
                    {
                        "camera_id": camera_id,
                        "group_index": group_index,
                        "issue": "; ".join(issues),
                        "metadata_path": project_rel(metadata_path),
                        "labels_rgb_path": project_rel(labels_rgb_path),
                        "compact_instance_label_path": project_rel(compact_path),
                        "rgb_path": project_rel(rgb_path),
                        "pcl_path": project_rel(ply_path),
                        "point_count": point_count,
                        "max_time_delta_ms": f"{delta_ms:.6f}",
                    }
                )

        failure_count += camera_failure_count
        camera_summaries.append(
            {
                "camera_id": camera_id,
                "group_count": len(metadata_rows),
                "failure_count": camera_failure_count,
                "unknown_compact_label_count": camera_unknown_labels,
                "compact_label_nonzero_ratio_mean": (
                    sum(camera_nonzero_ratios) / len(camera_nonzero_ratios)
                    if camera_nonzero_ratios
                    else 0.0
                ),
            }
        )

    summary = {
        "experiment_name": str(config.get("experiment_name", "perception_rt_small_v0")),
        "camera_count": len(camera_ids),
        "expected_groups_per_camera": args.expected_groups_per_camera,
        "expected_total_group_count": len(camera_ids) * args.expected_groups_per_camera,
        "actual_group_count": actual_group_count,
        "actual_labels_count": actual_labels_count,
        "actual_rgb_count": actual_rgb_count,
        "actual_ply_count": actual_ply_count,
        "actual_metadata_count": actual_metadata_count,
        "min_time_delta_ms": min_delta_observed if min_delta_observed is not None else 0.0,
        "max_time_delta_ms": max_delta_observed if max_delta_observed is not None else 0.0,
        "total_points_written": total_points_written,
        "min_points_per_cloud": min_points_observed if min_points_observed is not None else 0,
        "max_points_per_cloud": max_points_observed,
        "compact_label_nonzero_ratio_mean": (
            sum(nonzero_ratios) / len(nonzero_ratios) if nonzero_ratios else 0.0
        ),
        "unknown_compact_label_count": unknown_compact_label_count,
        "overall_passed": failure_count == 0,
        "failure_count": failure_count,
        "invalid_row_count": len(invalid_rows),
        "camera_summaries": camera_summaries,
    }

    write_json(summary_path, summary)
    write_csv(
        invalid_rows_path,
        [
            "camera_id",
            "group_index",
            "issue",
            "metadata_path",
            "labels_rgb_path",
            "compact_instance_label_path",
            "rgb_path",
            "pcl_path",
            "point_count",
            "max_time_delta_ms",
        ],
        invalid_rows,
    )

    print(
        "Validated synchronized stable-instance RGB/PCL capture: "
        f"overall_passed={summary['overall_passed']} "
        f"failure_count={summary['failure_count']} "
        f"invalid_row_count={summary['invalid_row_count']}"
    )
    print(f"summary_json={project_rel(summary_path)}")
    print(f"invalid_rows_csv={project_rel(invalid_rows_path)}")


if __name__ == "__main__":
    main()
