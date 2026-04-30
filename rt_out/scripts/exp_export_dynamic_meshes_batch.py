#!/usr/bin/env python3

"""Batch wrapper that exports dynamic meshes for all sampled experiment frames.

It reuses the validated one-frame exporter unchanged, adds Blender availability
checks, iterates over the experiment's visual-frame list, and writes an index so
later stages know where each frame-local dynamic manifest lives.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
EXPORT_SCRIPT = PROJECT_ROOT / "rt_out" / "scripts" / "32_export_dynamic_frame_meshes.py"


class BatchDynamicMeshExportError(RuntimeError):
    pass


try:
    from tqdm.auto import tqdm
except Exception:  # pragma: no cover - optional dependency
    tqdm = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch-export dynamic meshes for an experiment using 32_export_dynamic_frame_meshes.py."
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to experiment_config.json",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable progress bars / periodic progress prints.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=10,
        help="Fallback text progress print frequency when tqdm is unavailable.",
    )
    return parser.parse_args()


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise BatchDynamicMeshExportError(f"Missing input file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BatchDynamicMeshExportError(f"Invalid JSON in {path}: {exc}") from exc


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BatchDynamicMeshExportError(f"{label} must be an object")
    return value


def require_non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BatchDynamicMeshExportError(f"{label} must be a non-empty string")
    return value.strip()


def require_positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BatchDynamicMeshExportError(f"{label} must be a positive integer")
    return value


def require_non_negative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BatchDynamicMeshExportError(f"{label} must be a non-negative integer")
    return value


def resolve_project_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def frame_dir_name(frame_id: int) -> str:
    return f"frame_{frame_id:03d}"


def load_experiment_config(path: Path) -> dict[str, Any]:
    # Only the experiment metadata needed by this wrapper is loaded here:
    # experiment name, expected frame count, and output root.
    config = require_object(load_json(path), "experiment_config.json")
    experiment_name = require_non_empty_string(
        config.get("experiment_name"),
        "experiment_config.experiment_name",
    )
    num_frames = require_positive_int(
        config.get("num_frames"),
        "experiment_config.num_frames",
    )
    output_dir = require_non_empty_string(
        config.get("output_dir"),
        "experiment_config.output_dir",
    )
    output_root = resolve_project_path(output_dir)
    return {
        "config_path": path.resolve(),
        "experiment_name": experiment_name,
        "num_frames": num_frames,
        "output_dir": output_dir,
        "output_root": output_root,
    }


def load_frame_records(path: Path, expected_count: int) -> list[dict[str, int]]:
    # Read the visual-frame metadata produced by script 31 and reduce it to the
    # frame/sample pairs this batch wrapper iterates over.
    data = require_object(load_json(path), "dynamic_visual_frames.json")
    frames = data.get("frames")
    if not isinstance(frames, list):
        raise BatchDynamicMeshExportError("dynamic_visual_frames.json must contain a frames list")
    if len(frames) != expected_count:
        raise BatchDynamicMeshExportError(
            f"dynamic_visual_frames.json has {len(frames)} frames, expected {expected_count}"
        )

    records: list[dict[str, int]] = []
    seen_frame_ids: set[int] = set()
    for index, frame in enumerate(frames):
        if not isinstance(frame, dict):
            raise BatchDynamicMeshExportError(f"frames[{index}] must be an object")
        frame_id = require_non_negative_int(frame.get("frame_id"), f"frames[{index}].frame_id")
        source_sample_index = require_non_negative_int(
            frame.get("source_sample_index"),
            f"frames[{index}].source_sample_index",
        )
        if frame_id in seen_frame_ids:
            raise BatchDynamicMeshExportError(f"Duplicate frame_id in dynamic_visual_frames.json: {frame_id}")
        seen_frame_ids.add(frame_id)
        records.append(
            {
                "frame_id": frame_id,
                "source_sample_index": source_sample_index,
            }
        )
    return records


def require_blender_from_env() -> Path:
    # Keep Blender selection outside the wrapper logic so experiment runs can
    # reuse the exact Blender binary already validated for mesh export.
    blender_value = os.environ.get("BLENDER")
    if not blender_value:
        raise BatchDynamicMeshExportError("BLENDER environment variable is not set")
    blender_path = Path(blender_value).expanduser().resolve()
    if not blender_path.exists():
        raise BatchDynamicMeshExportError(f"BLENDER path does not exist: {blender_path}")
    if not blender_path.is_file():
        raise BatchDynamicMeshExportError(f"BLENDER path is not a file: {blender_path}")
    return blender_path


def run_export(
    *,
    frame_id: int,
    visual_frames_path: Path,
    output_root: Path,
    env: dict[str, str],
) -> Path:
    # Reuse the validated single-frame mesh exporter unchanged. This wrapper only
    # supplies frame-specific arguments and checks that the manifest was written.
    command = [
        sys.executable,
        str(EXPORT_SCRIPT),
        "--frame-id",
        str(frame_id),
        "--visual-frames-json",
        str(visual_frames_path),
        "--output-root",
        str(output_root),
    ]
    result = subprocess.run(
        command,
        cwd=str(PROJECT_ROOT),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        raise BatchDynamicMeshExportError(
            f"Dynamic mesh export failed for frame_id={frame_id} with exit code {result.returncode}"
        )

    manifest_path = output_root / frame_dir_name(frame_id) / f"dynamic_frame_{frame_id:03d}_manifest.json"
    if not manifest_path.exists():
        raise BatchDynamicMeshExportError(
            f"Expected export manifest was not created for frame_id={frame_id}: {manifest_path}"
        )
    return manifest_path


def write_index_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["frame_id", "source_sample_index", "manifest_path", "output_dir"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def format_elapsed(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    minutes, secs = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def main() -> int:
    args = parse_args()
    config_path = args.config.expanduser().resolve()
    if not config_path.exists():
        raise BatchDynamicMeshExportError(f"Config file does not exist: {config_path}")

    blender_path = require_blender_from_env()
    experiment = load_experiment_config(config_path)
    visual_frames_path = experiment["output_root"] / "frames" / "dynamic_visual_frames.json"
    if not visual_frames_path.exists():
        raise BatchDynamicMeshExportError(
            f"dynamic_visual_frames.json does not exist: {visual_frames_path}"
        )

    frame_records = load_frame_records(visual_frames_path, experiment["num_frames"])
    output_root = experiment["output_root"] / "frames" / "dynamic_meshes"
    index_csv_path = output_root / "dynamic_mesh_index.csv"

    # Pass the same BLENDER environment setting through to every subprocess so
    # all frames are exported with the same validated Blender build.
    env = os.environ.copy()
    env["BLENDER"] = str(blender_path)

    rows: list[dict[str, Any]] = []
    total = len(frame_records)
    start_time = time.time()
    progress = None
    if not args.no_progress and tqdm is not None:
        progress = tqdm(total=total, desc="dynamic meshes", unit="frame", dynamic_ncols=True)
    for index, frame in enumerate(frame_records, start=1):
        frame_id = frame["frame_id"]
        source_sample_index = frame["source_sample_index"]
        # Progress reporting stays at frame granularity because each subprocess
        # call below exports one complete dynamic frame.
        status = f"frame_id={frame_id} sample={source_sample_index}"
        if progress is None and (
            index == 1
            or index == total
            or (args.progress_every > 0 and index % args.progress_every == 0)
        ):
            print(
                f"[dynamic meshes] {index}/{total} {status} "
                f"elapsed={format_elapsed(time.time() - start_time)}"
            )
        manifest_path = run_export(
            frame_id=frame_id,
            visual_frames_path=visual_frames_path,
            output_root=output_root,
            env=env,
        )
        rows.append(
            {
                "frame_id": frame_id,
                "source_sample_index": source_sample_index,
                "manifest_path": str(manifest_path),
                "output_dir": str(manifest_path.parent),
            }
        )
        if progress is not None:
            progress.set_postfix_str(status, refresh=False)
            progress.update(1)
    if progress is not None:
        progress.close()

    # Validate the index once more after the loop so later stages can trust that
    # every indexed manifest path exists on disk.
    for row in rows:
        if not Path(row["manifest_path"]).exists():
            raise BatchDynamicMeshExportError(
                f"Indexed manifest_path does not exist: {row['manifest_path']}"
            )

    write_index_csv(index_csv_path, rows)

    first = rows[0]
    last = rows[-1]
    print(f"experiment_name: {experiment['experiment_name']}")
    print(f"number of frames: {len(rows)}")
    print(
        f"first: frame_id={first['frame_id']}, source_sample_index={first['source_sample_index']}, "
        f"manifest_path={first['manifest_path']}"
    )
    print(
        f"last: frame_id={last['frame_id']}, source_sample_index={last['source_sample_index']}, "
        f"manifest_path={last['manifest_path']}"
    )
    print(f"index CSV path: {index_csv_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BatchDynamicMeshExportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
