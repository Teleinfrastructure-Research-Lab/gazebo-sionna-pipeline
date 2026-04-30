#!/usr/bin/env python3

"""Batch wrapper that composes static and dynamic frame manifests via script 33.

The heavy lifting still lives in the validated single-frame compose script. This
wrapper just reads the experiment index, loops over frames, and records where
each composed manifest ended up for later XML generation.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_SCRIPT = PROJECT_ROOT / "rt_out" / "scripts" / "33_compose_prototype_frame_scene.py"
DEFAULT_STATIC_MANIFEST = (
    PROJECT_ROOT / "rt_out" / "static_scene" / "export" / "merged_static_manifest.json"
)


class BatchComposeFrameManifestError(RuntimeError):
    pass


try:
    from tqdm.auto import tqdm
except Exception:  # pragma: no cover - optional dependency
    tqdm = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch-compose static + dynamic frame manifests using 33_compose_prototype_frame_scene.py."
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
        raise BatchComposeFrameManifestError(f"Missing input file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise BatchComposeFrameManifestError(f"Invalid JSON in {path}: {exc}") from exc


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BatchComposeFrameManifestError(f"{label} must be an object")
    return value


def require_non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BatchComposeFrameManifestError(f"{label} must be a non-empty string")
    return value.strip()


def require_positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise BatchComposeFrameManifestError(f"{label} must be a positive integer")
    return value


def require_non_negative_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise BatchComposeFrameManifestError(f"{label} must be a non-negative integer")
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


def load_dynamic_mesh_index(path: Path, expected_count: int) -> list[dict[str, Any]]:
    # Read the mesh-export index and reduce it to the fields needed by the
    # single-frame compose script.
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except FileNotFoundError as exc:
        raise BatchComposeFrameManifestError(f"Missing dynamic mesh index CSV: {path}") from exc

    if len(rows) != expected_count:
        raise BatchComposeFrameManifestError(
            f"dynamic_mesh_index.csv has {len(rows)} rows, expected {expected_count}"
        )

    records: list[dict[str, Any]] = []
    seen_frame_ids: set[int] = set()
    for index, row in enumerate(rows):
        frame_id = require_non_negative_int(
            int(row["frame_id"]) if row.get("frame_id") not in (None, "") else None,
            f"row[{index}].frame_id",
        )
        source_sample_index = require_non_negative_int(
            int(row["source_sample_index"]) if row.get("source_sample_index") not in (None, "") else None,
            f"row[{index}].source_sample_index",
        )
        dynamic_manifest_value = require_non_empty_string(
            row.get("manifest_path"),
            f"row[{index}].manifest_path",
        )
        dynamic_manifest_path = Path(dynamic_manifest_value).expanduser().resolve()
        if frame_id in seen_frame_ids:
            raise BatchComposeFrameManifestError(f"Duplicate frame_id in dynamic mesh index: {frame_id}")
        seen_frame_ids.add(frame_id)
        if not dynamic_manifest_path.exists():
            raise BatchComposeFrameManifestError(
                f"dynamic_manifest_path does not exist for frame_id={frame_id}: {dynamic_manifest_path}"
            )
        records.append(
            {
                "frame_id": frame_id,
                "source_sample_index": source_sample_index,
                "dynamic_manifest_path": dynamic_manifest_path,
            }
        )
    return records


def run_compose(
    *,
    frame_id: int,
    static_manifest_path: Path,
    dynamic_manifest_path: Path,
    output_manifest_path: Path,
) -> None:
    # Reuse the validated single-frame compose step unchanged. This wrapper only
    # supplies frame-specific paths and checks that output manifests appear.
    command = [
        sys.executable,
        str(COMPOSE_SCRIPT),
        "--frame-id",
        str(frame_id),
        "--static-manifest",
        str(static_manifest_path),
        "--dynamic-manifest",
        str(dynamic_manifest_path),
        "--output-manifest",
        str(output_manifest_path),
    ]
    result = subprocess.run(
        command,
        cwd=str(PROJECT_ROOT),
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
        raise BatchComposeFrameManifestError(
            f"Frame manifest composition failed for frame_id={frame_id} with exit code {result.returncode}"
        )


def write_index_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "frame_id",
        "source_sample_index",
        "dynamic_manifest_path",
        "composed_manifest_path",
    ]
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
        raise BatchComposeFrameManifestError(f"Config file does not exist: {config_path}")
    if not DEFAULT_STATIC_MANIFEST.exists():
        raise BatchComposeFrameManifestError(
            f"Frozen static manifest does not exist: {DEFAULT_STATIC_MANIFEST}"
        )

    experiment = load_experiment_config(config_path)
    dynamic_mesh_index_path = (
        experiment["output_root"] / "frames" / "dynamic_meshes" / "dynamic_mesh_index.csv"
    )
    records = load_dynamic_mesh_index(dynamic_mesh_index_path, experiment["num_frames"])

    output_root = experiment["output_root"] / "frames" / "composed_manifests"
    index_csv_path = output_root / "composed_manifest_index.csv"

    rows: list[dict[str, Any]] = []
    total = len(records)
    start_time = time.time()
    progress = None
    if not args.no_progress and tqdm is not None:
        progress = tqdm(total=total, desc="compose manifests", unit="frame", dynamic_ncols=True)
    for index, record in enumerate(records, start=1):
        frame_id = record["frame_id"]
        source_sample_index = record["source_sample_index"]
        dynamic_manifest_path = record["dynamic_manifest_path"]
        # Progress reporting stays at frame granularity because each subprocess
        # call below composes one full frame manifest.
        status = f"frame_id={frame_id} sample={source_sample_index}"
        if progress is None and (
            index == 1
            or index == total
            or (args.progress_every > 0 and index % args.progress_every == 0)
        ):
            print(
                f"[compose manifests] {index}/{total} {status} "
                f"elapsed={format_elapsed(time.time() - start_time)}"
            )
        composed_manifest_path = (
            output_root
            / frame_dir_name(frame_id)
            / f"composed_frame_{frame_id:03d}_manifest.json"
        )
        run_compose(
            frame_id=frame_id,
            static_manifest_path=DEFAULT_STATIC_MANIFEST,
            dynamic_manifest_path=dynamic_manifest_path,
            output_manifest_path=composed_manifest_path,
        )
        if not composed_manifest_path.exists():
            raise BatchComposeFrameManifestError(
                f"Expected composed manifest was not created for frame_id={frame_id}: {composed_manifest_path}"
            )
        rows.append(
            {
                "frame_id": frame_id,
                "source_sample_index": source_sample_index,
                "dynamic_manifest_path": str(dynamic_manifest_path),
                "composed_manifest_path": str(composed_manifest_path),
            }
        )
        if progress is not None:
            progress.set_postfix_str(status, refresh=False)
            progress.update(1)
    if progress is not None:
        progress.close()

    # Re-validate the index after the loop so later XML generation can trust the
    # composed manifest paths without rescanning the frame directories.
    for row in rows:
        if not Path(row["composed_manifest_path"]).exists():
            raise BatchComposeFrameManifestError(
                f"Indexed composed_manifest_path does not exist: {row['composed_manifest_path']}"
            )

    write_index_csv(index_csv_path, rows)

    first = rows[0]
    last = rows[-1]
    print(f"experiment_name: {experiment['experiment_name']}")
    print(f"number of frames: {len(rows)}")
    print(
        f"first: frame_id={first['frame_id']}, source_sample_index={first['source_sample_index']}, "
        f"composed_manifest_path={first['composed_manifest_path']}"
    )
    print(
        f"last: frame_id={last['frame_id']}, source_sample_index={last['source_sample_index']}, "
        f"composed_manifest_path={last['composed_manifest_path']}"
    )
    print(f"index CSV path: {index_csv_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BatchComposeFrameManifestError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
