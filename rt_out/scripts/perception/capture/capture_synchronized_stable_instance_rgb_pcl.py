#!/usr/bin/env python3
"""Capture synchronized stable-instance panoptic labels, RGB, and direct PCL."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CONFIG = PROJECT_ROOT / "rt_out/experiments/perception_rt_small_v0/run_20260522_133045/config/perception_dataset_config.json"
CPP_ROOT = PROJECT_ROOT / "rt_out/scripts/perception/capture/cpp"
BUILD_SCRIPT = CPP_ROOT / "build_capture_synchronized_stable_instance_rgb_pcl_topics.sh"
CPP_BINARY = CPP_ROOT / "capture_synchronized_stable_instance_rgb_pcl_topics"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Subscribe to synchronized stable-instance labels, RGB, and direct point-cloud topics and save matched groups by timestamp."
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Perception dataset config JSON.")
    parser.add_argument("--max-groups-per-camera", type=int, default=3, help="How many synchronized label/RGB/PCL groups to save per camera.")
    parser.add_argument("--timeout-seconds", type=int, default=30, help="Maximum capture duration.")
    parser.add_argument("--stride", type=int, default=4, help="Stride over organized point-cloud pixels when writing PLY.")
    parser.add_argument("--max-sync-delta-ms", type=float, default=50.0, help="Maximum allowed label/RGB/PCL timestamp delta in milliseconds.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing synchronized stable-instance capture outputs and summaries.")
    parser.add_argument("--no-build", action="store_true", help="Skip rebuilding the C++ capture utility.")
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


def project_rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def clear_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def ensure_outputs_writable(paths: list[Path], force: bool) -> None:
    existing = [path for path in paths if path.exists()]
    if existing and not force:
        fail(
            "Output already exists. Re-run with --force to overwrite: "
            + ", ".join(str(path) for path in existing)
        )
    if force:
        for path in existing:
            clear_path(path)


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
    if not isinstance(requested_ids, list) or not all(isinstance(item, str) for item in requested_ids):
        fail("Config field 'camera_ids' must be a list of camera IDs.")
    cameras: list[dict[str, Any]] = []
    for camera_id in requested_ids:
        if camera_id not in camera_map:
            fail(f"Camera rig missing required camera '{camera_id}'.")
        cameras.append(camera_map[camera_id])
    return cameras


def maybe_build_binary(no_build: bool) -> Path:
    if not BUILD_SCRIPT.is_file():
        fail(f"Build script not found: {BUILD_SCRIPT}")
    if not no_build:
        result = subprocess.run(
            ["bash", str(BUILD_SCRIPT.resolve())],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            fail(
                "Failed to build synchronized stable-instance capture utility.\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )
    if not CPP_BINARY.is_file():
        fail(f"Synchronized stable-instance capture utility binary not found after build: {CPP_BINARY}")
    return CPP_BINARY


def build_topics(cameras: list[dict[str, Any]]) -> tuple[list[str], list[str], list[str], list[str]]:
    labels_topics = [
        f"/perception/native/stable_instance_panoptic/{camera['camera_id']}/labels_map"
        for camera in cameras
    ]
    colored_topics = [
        f"/perception/native/stable_instance_panoptic/{camera['camera_id']}/colored_map"
        for camera in cameras
    ]
    rgb_topics = [f"/perception/native/rgbd/{camera['camera_id']}/rgb" for camera in cameras]
    pcl_topics = [f"/perception/native/rgbd/{camera['camera_id']}/depth/points" for camera in cameras]
    return labels_topics, colored_topics, rgb_topics, pcl_topics


def run_utility(
    binary_path: Path,
    output_root: Path,
    labels_topics: list[str],
    colored_topics: list[str],
    rgb_topics: list[str],
    pcl_topics: list[str],
    max_groups_per_camera: int,
    timeout_seconds: int,
    stride: int,
    max_sync_delta_ms: float,
) -> dict[str, Any]:
    command = [
        str(binary_path.resolve()),
        "--output-root",
        str(output_root.resolve()),
        "--max-groups-per-camera",
        str(max_groups_per_camera),
        "--timeout-seconds",
        str(timeout_seconds),
        "--stride",
        str(stride),
        "--max-sync-delta-ms",
        str(max_sync_delta_ms),
    ]
    for topic in labels_topics:
        command.extend(["--labels-topic", topic])
    for topic in colored_topics:
        command.extend(["--colored-topic", topic])
    for topic in rgb_topics:
        command.extend(["--rgb-topic", topic])
    for topic in pcl_topics:
        command.extend(["--pcl-topic", topic])
    result = subprocess.run(
        command,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        fail(
            "Synchronized stable-instance capture utility failed.\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        fail(f"Utility did not emit valid JSON summary: {exc}\nstdout:\n{result.stdout}")


def collect_metadata_rows(output_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not output_root.is_dir():
        return rows
    for camera_dir in sorted(path for path in output_root.iterdir() if path.is_dir()):
        metadata_dir = camera_dir / "metadata"
        if not metadata_dir.is_dir():
            continue
        for metadata_path in sorted(metadata_dir.glob("sync_*.json")):
            payload = load_json(metadata_path, f"metadata {metadata_path}")
            if not isinstance(payload, dict):
                fail(f"Metadata file at {metadata_path} must be a JSON object.")
            payload["_metadata_path"] = metadata_path
            rows.append(payload)
    rows.sort(key=lambda row: (str(row.get("camera_id", "")), int(row.get("group_index", 0))))
    return rows


def count_files(directory: Path, suffixes: tuple[str, ...]) -> int:
    if not directory.is_dir():
        return 0
    return len([path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in suffixes])


def write_index_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "camera_id",
        "group_index",
        "labels_rgb_path",
        "compact_instance_label_path",
        "gazebo_instance_count_path",
        "colored_map_path",
        "rgb_path",
        "pcl_path",
        "metadata_path",
        "labels_header_stamp",
        "rgb_header_stamp",
        "pcl_header_stamp",
        "max_time_delta_ms",
        "width",
        "height",
        "stride",
        "written_point_count",
        "skipped_nonfinite_count",
        "has_pixel_coordinates",
        "status",
        "notes",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "camera_id": row.get("camera_id", ""),
                    "group_index": row.get("group_index", ""),
                    "labels_rgb_path": row.get("labels_rgb_path", ""),
                    "compact_instance_label_path": row.get("compact_instance_label_path", ""),
                    "gazebo_instance_count_path": row.get("gazebo_instance_count_path", ""),
                    "colored_map_path": row.get("colored_map_path", ""),
                    "rgb_path": row.get("rgb_path", ""),
                    "pcl_path": row.get("pcl_path", ""),
                    "metadata_path": project_rel(Path(row["_metadata_path"])),
                    "labels_header_stamp": row.get("labels_header_stamp", ""),
                    "rgb_header_stamp": row.get("rgb_header_stamp", ""),
                    "pcl_header_stamp": row.get("pcl_header_stamp", ""),
                    "max_time_delta_ms": row.get("max_time_delta_ms", ""),
                    "width": row.get("width", ""),
                    "height": row.get("height", ""),
                    "stride": row.get("stride", ""),
                    "written_point_count": row.get("written_point_count", row.get("point_count", "")),
                    "skipped_nonfinite_count": row.get("skipped_nonfinite_count", ""),
                    "has_pixel_coordinates": row.get("has_pixel_coordinates", ""),
                    "status": "ok",
                    "notes": "",
                }
            )


def build_summary(
    utility_summary: dict[str, Any],
    rows: list[dict[str, Any]],
    output_root: Path,
    max_groups_per_camera: int,
    timeout_seconds: int,
    stride: int,
    max_sync_delta_ms: float,
    binary_path: Path,
) -> dict[str, Any]:
    camera_dirs = sorted(path for path in output_root.iterdir() if path.is_dir()) if output_root.is_dir() else []
    labels_count = sum(count_files(camera_dir / "labels_maps_rgb", (".ppm", ".png")) for camera_dir in camera_dirs)
    compact_count = sum(count_files(camera_dir / "compact_instance_label", (".pgm", ".png")) for camera_dir in camera_dirs)
    gazebo_count = sum(count_files(camera_dir / "gazebo_instance_count", (".pgm", ".png")) for camera_dir in camera_dirs)
    colored_count = sum(count_files(camera_dir / "colored_maps", (".ppm", ".png")) for camera_dir in camera_dirs)
    rgb_count = sum(count_files(camera_dir / "rgb", (".ppm", ".png", ".jpg", ".jpeg")) for camera_dir in camera_dirs)
    ply_count = sum(count_files(camera_dir / "ply", (".ply",)) for camera_dir in camera_dirs)
    metadata_count = len(rows)

    points = [int(row.get("written_point_count", row.get("point_count", 0)) or 0) for row in rows]
    deltas = [float(row.get("max_time_delta_ms", 0.0) or 0.0) for row in rows]
    per_camera_counts: dict[str, int] = {}
    for row in rows:
        camera_id = str(row.get("camera_id", ""))
        per_camera_counts[camera_id] = per_camera_counts.get(camera_id, 0) + 1

    return {
        "mode": "sync_stable_instance_rgb_pcl",
        "output_root": project_rel(output_root),
        "topic_count": len(utility_summary.get("topics", [])),
        "camera_count": len(camera_dirs),
        "max_groups_per_camera": max_groups_per_camera,
        "timeout_seconds": timeout_seconds,
        "stride": stride,
        "max_sync_delta_ms_threshold": max_sync_delta_ms,
        "any_message_received": bool(utility_summary.get("any_message_received", False)),
        "captured_group_count": metadata_count,
        "captured_labels_count": labels_count,
        "captured_compact_instance_label_count": compact_count,
        "captured_gazebo_instance_count_count": gazebo_count,
        "captured_colored_map_count": colored_count,
        "captured_rgb_count": rgb_count,
        "captured_ply_count": ply_count,
        "captured_metadata_count": metadata_count,
        "total_points_written": sum(points),
        "min_points_per_cloud": min(points) if points else 0,
        "max_points_per_cloud": max(points) if points else 0,
        "min_time_delta_ms": min(deltas) if deltas else 0.0,
        "max_time_delta_ms": max(deltas) if deltas else 0.0,
        "failed_write_count": int(utility_summary.get("failed_write_count", 0)),
        "write_errors": list(utility_summary.get("write_errors", [])),
        "topics": [
            {
                "camera_id": camera_id,
                "group_count": per_camera_counts.get(camera_id, 0),
            }
            for camera_id in sorted(per_camera_counts)
        ],
        "capture_binary": project_rel(binary_path),
        "warnings": list(utility_summary.get("write_errors", [])),
    }


def main() -> None:
    args = parse_args()
    if args.max_groups_per_camera <= 0:
        fail("--max-groups-per-camera must be positive.")
    if args.timeout_seconds <= 0:
        fail("--timeout-seconds must be positive.")
    if args.stride <= 0:
        fail("--stride must be positive.")
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
    output_root = experiment_root / "perception_raw" / "native" / "sync_stable_instance_rgb_pcl"
    index_path = experiment_root / "perception_raw" / "native" / "sync_stable_instance_rgb_pcl_capture_index.csv"
    summary_path = experiment_root / "perception_raw" / "native" / "sync_stable_instance_rgb_pcl_capture_summary.json"
    ensure_outputs_writable([output_root, index_path, summary_path], args.force)

    binary_path = maybe_build_binary(args.no_build)
    labels_topics, colored_topics, rgb_topics, pcl_topics = build_topics(cameras)
    utility_summary = run_utility(
        binary_path,
        output_root,
        labels_topics,
        colored_topics,
        rgb_topics,
        pcl_topics,
        args.max_groups_per_camera,
        args.timeout_seconds,
        args.stride,
        args.max_sync_delta_ms,
    )

    rows = collect_metadata_rows(output_root)
    write_index_csv(index_path, rows)
    summary = build_summary(
        utility_summary,
        rows,
        output_root,
        args.max_groups_per_camera,
        args.timeout_seconds,
        args.stride,
        args.max_sync_delta_ms,
        binary_path,
    )
    write_json(summary_path, summary)

    print(
        "Captured synchronized stable-instance RGB/PCL groups: "
        f"groups={summary['captured_group_count']} "
        f"labels={summary['captured_labels_count']} "
        f"rgb={summary['captured_rgb_count']} "
        f"ply={summary['captured_ply_count']} "
        f"metadata={summary['captured_metadata_count']}"
    )
    print(f"output_root={project_rel(output_root)}")
    print(f"index_csv={project_rel(index_path)}")
    print(f"summary_json={project_rel(summary_path)}")


if __name__ == "__main__":
    main()
