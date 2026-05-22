#!/usr/bin/env python3
"""Capture Gazebo segmentation topics into experiment-local image files.

Gazebo's built-in <save> path is not emitting files on this setup, so this
wrapper subscribes to the segmentation topics through a small Gazebo Transport
utility and saves labels_map / colored_map frames manually. The primary dataset
path is panoptic capture. Legacy split semantic / instance capture is kept only
for explicit debugging.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = PROJECT_ROOT / "rt_out/experiments/perception_rt_small_v0/configs/perception_dataset_config.json"
CPP_ROOT = PROJECT_ROOT / "rt_out/scripts/perception/cpp"
BUILD_SCRIPT = CPP_ROOT / "build_capture_segmentation_topics.sh"
CPP_BINARY = CPP_ROOT / "capture_segmentation_topics"
VALID_MODES = ("panoptic", "semantic", "instance")
DEBUG_SPLIT_MODES = {"semantic", "instance"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Subscribe to Gazebo segmentation topics and save panoptic primary or semantic/instance debug frames."
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Perception dataset config JSON.")
    parser.add_argument(
        "--mode",
        choices=VALID_MODES,
        required=True,
        help="Capture panoptic, semantic, or instance topics. 'panoptic' is primary; split modes require --allow-debug-split-mode.",
    )
    parser.add_argument(
        "--allow-debug-split-mode",
        action="store_true",
        help="Allow legacy semantic/instance split-topic capture for debugging.",
    )
    parser.add_argument("--max-messages-per-topic", type=int, default=5, help="How many messages to save per topic.")
    parser.add_argument("--timeout-seconds", type=int, default=30, help="Maximum topic capture duration.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing mode outputs and summary files.")
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


def build_topics(mode: str, cameras: list[dict[str, Any]]) -> list[str]:
    topics: list[str] = []
    for camera in cameras:
        camera_id = str(camera["camera_id"])
        topics.append(f"/perception/native/{mode}/{camera_id}/labels_map")
        topics.append(f"/perception/native/{mode}/{camera_id}/colored_map")
    return topics


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
                "Failed to build capture utility.\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )
    if not CPP_BINARY.is_file():
        fail(f"Capture utility binary not found after build: {CPP_BINARY}")
    return CPP_BINARY


def run_utility(
    binary_path: Path,
    mode: str,
    output_root: Path,
    topics: list[str],
    max_messages_per_topic: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    command = [
        str(binary_path.resolve()),
        "--mode", mode,
        "--output-root", str(output_root.resolve()),
        "--max-messages-per-topic", str(max_messages_per_topic),
        "--timeout-seconds", str(timeout_seconds),
    ]
    for topic in topics:
        command.extend(["--topic", topic])
    result = subprocess.run(
        command,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        fail(
            "Topic capture utility failed.\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        fail(f"Utility did not emit valid JSON summary: {exc}\nstdout:\n{result.stdout}")


def collect_metadata_rows(native_root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for mode_dir in sorted(path for path in native_root.iterdir() if path.is_dir() and path.name in VALID_MODES):
        for camera_dir in sorted(path for path in mode_dir.iterdir() if path.is_dir()):
            metadata_dir = camera_dir / "metadata"
            if not metadata_dir.is_dir():
                continue
            for metadata_path in sorted(metadata_dir.glob("*.json")):
                payload = load_json(metadata_path, f"metadata {metadata_path}")
                if not isinstance(payload, dict):
                    fail(f"Metadata file at {metadata_path} must be a JSON object.")
                payload["_metadata_path"] = metadata_path
                rows.append(payload)
    rows.sort(key=lambda item: (str(item.get("mode", "")), str(item.get("camera_id", "")), str(item.get("map_type", "")), int(item.get("message_index", 0))))
    return rows


def extract_message_key(path: Path) -> str:
    digits = "".join(character for character in path.stem if character.isdigit())
    if digits:
        return str(int(digits))
    return path.stem


def count_message_files(
    directory: Path,
    primary_suffixes: tuple[str, ...],
    fallback_suffixes: tuple[str, ...],
) -> int:
    if not directory.is_dir():
        return 0
    files = sorted(path for path in directory.iterdir() if path.is_file())
    if not files:
        return 0
    primary = [path for path in files if path.suffix.lower() in primary_suffixes]
    if primary:
        candidates = primary
    else:
        fallback = [path for path in files if path.suffix.lower() in fallback_suffixes]
        candidates = fallback or files
    return len({extract_message_key(path) for path in candidates})


def write_index_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "mode",
        "camera_id",
        "map_type",
        "topic",
        "message_index",
        "width",
        "height",
        "pixel_format_type",
        "data_size",
        "saved_raw_rgb_path",
        "saved_decoded_label_path",
        "saved_semantic_decoded_path",
        "saved_gazebo_instance_count_path",
        "semantic_label_channel",
        "instance_count_high_channel",
        "instance_count_low_channel",
        "gazebo_instance_count_encoding",
        "gazebo_instance_count_is_stable_instance_id",
        "metadata_path",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "mode": row.get("mode", ""),
                    "camera_id": row.get("camera_id", ""),
                    "map_type": row.get("map_type", ""),
                    "topic": row.get("topic", ""),
                    "message_index": row.get("message_index", ""),
                    "width": row.get("width", ""),
                    "height": row.get("height", ""),
                    "pixel_format_type": row.get("pixel_format_type", ""),
                    "data_size": row.get("data_size", ""),
                    "saved_raw_rgb_path": row.get("saved_raw_rgb_path", ""),
                    "saved_decoded_label_path": row.get("saved_decoded_label_path", ""),
                    "saved_semantic_decoded_path": row.get("saved_semantic_decoded_path", ""),
                    "saved_gazebo_instance_count_path": row.get("saved_gazebo_instance_count_path", ""),
                    "semantic_label_channel": row.get("semantic_label_channel", ""),
                    "instance_count_high_channel": row.get("instance_count_high_channel", ""),
                    "instance_count_low_channel": row.get("instance_count_low_channel", ""),
                    "gazebo_instance_count_encoding": row.get("gazebo_instance_count_encoding", ""),
                    "gazebo_instance_count_is_stable_instance_id": row.get("gazebo_instance_count_is_stable_instance_id", ""),
                    "metadata_path": project_rel(Path(row["_metadata_path"])),
                }
            )


def build_summary(
    utility_summary: dict[str, Any],
    rows: list[dict[str, Any]],
    output_root: Path,
    mode: str,
    max_messages_per_topic: int,
    timeout_seconds: int,
    binary_path: Path,
) -> dict[str, Any]:
    discovered_camera_dirs = sorted(path for path in output_root.iterdir() if path.is_dir()) if output_root.is_dir() else []
    metadata_camera_ids = {str(row.get("camera_id", "")) for row in rows if row.get("mode") == mode and str(row.get("camera_id", "")).strip()}
    labels_rows = [row for row in rows if row.get("map_type") == "labels_map" and row.get("mode") == mode]
    colored_rows = [row for row in rows if row.get("map_type") == "colored_map" and row.get("mode") == mode]
    decoded_rows = [
        row for row in labels_rows
        if str(row.get("saved_decoded_label_path", "") or row.get("saved_semantic_decoded_path", "")).strip()
    ]
    raw_label_dir_name = "labels_maps_rgb" if mode == "panoptic" else "labels_maps"
    raw_label_file_count = sum(
        count_message_files(
            camera_dir / raw_label_dir_name,
            primary_suffixes=(".ppm",),
            fallback_suffixes=(".png", ".jpg", ".jpeg", ".ppm"),
        )
        for camera_dir in discovered_camera_dirs
    )
    colored_map_file_count = sum(
        count_message_files(
            camera_dir / "colored_maps",
            primary_suffixes=(".ppm",),
            fallback_suffixes=(".png", ".jpg", ".jpeg", ".ppm"),
        )
        for camera_dir in discovered_camera_dirs
    )
    semantic_decoded_file_count = sum(
        count_message_files(
            camera_dir / ("semantic_decoded" if mode == "panoptic" else "labels_maps_decoded"),
            primary_suffixes=(".pgm", ".png"),
            fallback_suffixes=(".pgm", ".png"),
        )
        for camera_dir in discovered_camera_dirs
    )
    gazebo_instance_count_file_count = 0
    if mode == "panoptic":
        gazebo_instance_count_file_count = sum(
            count_message_files(
                camera_dir / "gazebo_instance_count",
                primary_suffixes=(".pgm", ".png"),
                fallback_suffixes=(".pgm", ".png"),
            )
            for camera_dir in discovered_camera_dirs
        )
    captured_colored_map_count = len(colored_rows) if colored_rows else colored_map_file_count
    summary = {
        "mode": mode,
        "output_root": project_rel(output_root),
        "topic_count": len(utility_summary.get("topics", [])),
        "camera_count": max(len(metadata_camera_ids), len(discovered_camera_dirs)),
        "max_messages_per_topic": max_messages_per_topic,
        "timeout_seconds": timeout_seconds,
        "any_message_received": bool(utility_summary.get("any_message_received", False)),
        "captured_metadata_count": len([row for row in rows if row.get("mode") == mode]),
        "captured_labels_map_count": len(labels_rows) if labels_rows else raw_label_file_count,
        "captured_labels_maps_decoded_count": len(decoded_rows) if decoded_rows else semantic_decoded_file_count,
        "captured_colored_map_count": captured_colored_map_count,
        "captured_colored_map_count_source": "metadata" if colored_rows else "filesystem",
        "utility_binary": project_rel(binary_path),
        "topics": utility_summary.get("topics", []),
        "warnings": [] if utility_summary.get("any_message_received", False) else [
            "No messages were captured. Ensure Gazebo native segmentation topics are publishing before running topic capture."
        ],
    }
    if mode == "panoptic":
        summary["captured_semantic_decoded_count"] = semantic_decoded_file_count
        summary["captured_gazebo_instance_count_count"] = gazebo_instance_count_file_count
        summary["raw_labels_dir"] = raw_label_dir_name
    return summary


def main() -> None:
    args = parse_args()
    if args.max_messages_per_topic <= 0:
        fail("--max-messages-per-topic must be positive.")
    if args.timeout_seconds <= 0:
        fail("--timeout-seconds must be positive.")
    if args.mode in DEBUG_SPLIT_MODES and not args.allow_debug_split_mode:
        fail(
            f"mode={args.mode} is a legacy split-world debug path. Re-run with --allow-debug-split-mode if you really want it."
        )

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    config = load_json(config_path, "perception dataset config")
    if not isinstance(config, dict):
        fail(f"Perception dataset config at {config_path} must be a JSON object.")

    experiment_root = config_path.resolve().parents[1]
    legacy_root = experiment_root / "legacy"
    camera_rig_path = experiment_root / "configs" / "camera_rig.json"
    cameras = load_camera_rig(camera_rig_path, config)
    topics = build_topics(args.mode, cameras)

    if args.mode == "panoptic":
        capture_root = experiment_root / "perception_raw" / "native"
    else:
        capture_root = legacy_root / "split_world_capture_outputs"
    output_root = capture_root / args.mode
    index_path = capture_root / "topic_capture_index.csv"
    summary_path = capture_root / "topic_capture_summary.json"

    ensure_outputs_writable([output_root, index_path, summary_path], args.force)
    binary_path = maybe_build_binary(args.no_build)
    utility_summary = run_utility(
        binary_path=binary_path,
        mode=args.mode,
        output_root=output_root,
        topics=topics,
        max_messages_per_topic=args.max_messages_per_topic,
        timeout_seconds=args.timeout_seconds,
    )

    rows = collect_metadata_rows(capture_root)
    write_index_csv(index_path, rows)
    summary = build_summary(
        utility_summary=utility_summary,
        rows=rows,
        output_root=output_root,
        mode=args.mode,
        max_messages_per_topic=args.max_messages_per_topic,
        timeout_seconds=args.timeout_seconds,
        binary_path=binary_path,
    )
    write_json(summary_path, summary)

    print(f"experiment_name={config.get('experiment_name', 'perception_rt_small_v0')}")
    print(f"mode={args.mode}")
    print(f"topic_count={len(topics)}")
    print(f"captured_metadata_count={summary['captured_metadata_count']}")
    print(f"captured_labels_map_count={summary['captured_labels_map_count']}")
    if args.mode == "panoptic":
        print(f"captured_semantic_decoded_count={summary['captured_semantic_decoded_count']}")
        print(f"captured_gazebo_instance_count_count={summary['captured_gazebo_instance_count_count']}")
    print(f"captured_colored_map_count={summary['captured_colored_map_count']}")
    print(f"topic_capture_index={project_rel(index_path)}")
    print(f"topic_capture_summary={project_rel(summary_path)}")


if __name__ == "__main__":
    main()
