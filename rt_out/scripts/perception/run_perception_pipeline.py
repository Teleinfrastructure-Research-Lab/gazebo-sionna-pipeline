#!/usr/bin/env python3
"""Run the perception pipeline in its explicit functional order.

The stage order is defined here rather than inferred from filenames. Each
stage remains an independent CLI entry point; this file only assembles those
entry points and forwards the common run configuration.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
PERCEPTION_ROOT = PROJECT_ROOT / "rt_out" / "scripts" / "perception"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="Run-local perception dataset config JSON.")
    parser.add_argument(
        "--expected-cloud-count",
        type=int,
        required=True,
        help="Expected final labeled point-cloud count for validation, e.g. 24 for the pilot.",
    )
    parser.add_argument("--min-points-per-cloud", type=int, default=1000)
    parser.add_argument("--force", action="store_true", help="Forward overwrite permission to stages that support it.")
    parser.add_argument("--dry-run", action="store_true", help="Print the ordered commands without executing them.")
    return parser.parse_args()


def stage_commands(args: argparse.Namespace) -> list[tuple[str, list[str]]]:
    config = str(args.config)
    python = sys.executable
    capture = PERCEPTION_ROOT / "capture"
    reconstruction = PERCEPTION_ROOT / "reconstruction"

    commands: list[tuple[str, list[str]]] = [
        ("select frames", [python, str(capture / "select_perception_frames.py"), "--config", config]),
        ("build instance registry", [python, str(capture / "build_perception_instance_registry.py"), "--config", config]),
        ("build labeled Gazebo world", [python, str(capture / "build_labeled_gazebo_world.py"), "--config", config]),
        ("capture panoptic data", [python, str(capture / "capture_panoptic_topics.py"), "--config", config]),
        ("validate panoptic data", [python, str(capture / "validate_panoptic_capture.py"), "--config", config]),
        (
            "capture synchronized RGB/depth/points",
            [python, str(capture / "capture_synchronized_stable_instance_rgb_pcl.py"), "--config", config],
        ),
        (
            "validate synchronized capture",
            [python, str(capture / "validate_synchronized_stable_instance_rgb_pcl.py"), "--config", config],
        ),
        (
            "reconstruct labeled colorized point clouds",
            [python, str(reconstruction / "build_labeled_colorized_point_cloud.py"), "--config", config],
        ),
        (
            "validate labeled colorized point clouds",
            [
                python,
                str(reconstruction / "validate_labeled_colorized_point_cloud.py"),
                "--config",
                config,
                "--expected-cloud-count",
                str(args.expected_cloud_count),
                "--min-points-per-cloud",
                str(args.min_points_per_cloud),
            ],
        ),
        (
            "build panoptic dataset index",
            [python, str(reconstruction / "build_panoptic_dataset_index.py"), "--config", config],
        ),
    ]

    force_stages = {
        "build labeled Gazebo world",
        "capture panoptic data",
        "capture synchronized RGB/depth/points",
        "reconstruct labeled colorized point clouds",
        "build panoptic dataset index",
    }
    if args.force:
        for name, command in commands:
            if name in force_stages:
                command.append("--force")
    return commands


def main() -> int:
    args = parse_args()
    config = args.config.expanduser().resolve()
    if not config.is_file():
        raise SystemExit(f"ERROR: missing perception config: {config}")

    commands = stage_commands(args)
    for index, (name, command) in enumerate(commands, start=1):
        print(f"stage_{index:02d}={name}")
        print("command=" + " ".join(command))
        if args.dry_run:
            continue
        subprocess.run(command, cwd=PROJECT_ROOT, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
