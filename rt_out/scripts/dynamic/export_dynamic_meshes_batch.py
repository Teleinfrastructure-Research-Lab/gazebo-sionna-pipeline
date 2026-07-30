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

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from runtime_config import (  # noqa: E402
    PROJECT_ROOT,
    RuntimeConfigError,
    SCRIPT_EXPORT_DYNAMIC_FRAME_MESHES,
    SCRIPT_EXPORT_ACTOR_FRAME_MESHES,
    find_blender,
)

EXPORT_SCRIPT = SCRIPT_EXPORT_DYNAMIC_FRAME_MESHES
ACTOR_EXPORT_SCRIPT = SCRIPT_EXPORT_ACTOR_FRAME_MESHES


class BatchDynamicMeshExportError(RuntimeError):
    pass


try:
    from tqdm.auto import tqdm
except Exception:  # pragma: no cover - optional dependency
    tqdm = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch-export dynamic meshes for an experiment using dynamic_rigid/export_dynamic_frame_meshes.py."
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
    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Optional debug limit on the number of frames to export.",
    )
    parser.add_argument(
        "--include-actors",
        action="store_true",
        help="Also export actor meshes into <output_root>/frames/actor_meshes and write actor_mesh_index.csv.",
    )
    parser.add_argument(
        "--blender",
        type=Path,
        default=None,
        help=(
            "Optional explicit Blender executable. Defaults to BLENDER, then "
            "the blender executable on PATH, then common local install layouts."
        ),
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
    # experiment name, expected frame count, output root, and optional actor settings.
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
    actors = config.get("actors")
    if actors is not None and not isinstance(actors, dict):
        raise BatchDynamicMeshExportError("experiment_config.actors must be an object when present")
    return {
        "config_path": path.resolve(),
        "experiment_name": experiment_name,
        "num_frames": num_frames,
        "output_dir": output_dir,
        "output_root": output_root,
        "actors": actors,
    }


def load_frame_records(path: Path, expected_count: int) -> list[dict[str, int]]:
    # Read the visual-frame metadata produced by resolve_dynamic_visual_frames.py and reduce it to the
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


def resolve_blender_or_raise(explicit: Path | None) -> Path:
    try:
        return find_blender(explicit)
    except RuntimeConfigError as exc:
        raise BatchDynamicMeshExportError(str(exc)) from exc


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


def actor_options_from_experiment(experiment: dict[str, Any]) -> dict[str, Any]:
    actors = experiment.get("actors")
    if not isinstance(actors, dict):
        raise BatchDynamicMeshExportError("--include-actors requires experiment_config.actors")
    enabled = actors.get("enabled")
    if enabled is not True:
        raise BatchDynamicMeshExportError("--include-actors requires experiment_config.actors.enabled == true")

    actor_manifest = resolve_project_path(
        require_non_empty_string(
            actors.get("actor_manifest"),
            "experiment_config.actors.actor_manifest",
        )
    )
    alignment_policy = require_non_empty_string(
        actors.get("alignment_policy"),
        "experiment_config.actors.alignment_policy",
    )
    z_alignment_policy = require_non_empty_string(
        actors.get("z_alignment_policy"),
        "experiment_config.actors.z_alignment_policy",
    )
    floor_z = actors.get("floor_z")
    if z_alignment_policy == "bounds_min_z_to_floor":
        if isinstance(floor_z, bool):
            raise BatchDynamicMeshExportError("experiment_config.actors.floor_z must be numeric")
        try:
            floor_z = float(floor_z)
        except (TypeError, ValueError) as exc:
            raise BatchDynamicMeshExportError("experiment_config.actors.floor_z must be numeric") from exc
    actor_samples_path = experiment["output_root"] / "frames" / "actor_frame_samples.json"
    if not actor_samples_path.exists():
        raise BatchDynamicMeshExportError(
            f"--include-actors requires actor samples file: {actor_samples_path}"
        )
    if not actor_manifest.exists():
        raise BatchDynamicMeshExportError(f"Actor manifest does not exist: {actor_manifest}")
    return {
        "actor_manifest_path": actor_manifest,
        "actor_samples_path": actor_samples_path,
        "alignment_policy": alignment_policy,
        "z_alignment_policy": z_alignment_policy,
        "floor_z": floor_z,
    }


def run_actor_export(
    *,
    frame_id: int,
    actor_samples_path: Path,
    actor_manifest_path: Path,
    output_root: Path,
    alignment_policy: str,
    z_alignment_policy: str,
    floor_z: float | None,
    env: dict[str, str],
) -> Path:
    command = [
        sys.executable,
        str(ACTOR_EXPORT_SCRIPT),
        "--frame-id",
        str(frame_id),
        "--actor-samples",
        str(actor_samples_path),
        "--actor-manifest",
        str(actor_manifest_path),
        "--output-root",
        str(output_root),
        "--alignment-policy",
        alignment_policy,
        "--z-alignment-policy",
        z_alignment_policy,
    ]
    if floor_z is not None:
        command.extend(["--floor-z", str(floor_z)])
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
            f"Actor mesh export failed for frame_id={frame_id} with exit code {result.returncode}"
        )

    manifest_path = output_root / frame_dir_name(frame_id) / f"actor_frame_{frame_id:03d}_manifest.json"
    if not manifest_path.exists():
        raise BatchDynamicMeshExportError(
            f"Expected actor manifest was not created for frame_id={frame_id}: {manifest_path}"
        )
    return manifest_path


def validate_actor_manifest(
    *,
    manifest_path: Path,
    frame_id: int,
    source_sample_index: int,
) -> int:
    data = require_object(load_json(manifest_path), f"actor manifest {manifest_path}")
    manifest_frame_id = require_non_negative_int(data.get("frame_id"), f"{manifest_path}.frame_id")
    if manifest_frame_id != frame_id:
        raise BatchDynamicMeshExportError(
            f"Actor manifest frame_id mismatch: expected {frame_id}, got {manifest_frame_id}"
        )
    manifest_source_sample_index = require_non_negative_int(
        data.get("source_sample_index"),
        f"{manifest_path}.source_sample_index",
    )
    if manifest_source_sample_index != source_sample_index:
        raise BatchDynamicMeshExportError(
            "Actor manifest source_sample_index mismatch: "
            f"expected {source_sample_index}, got {manifest_source_sample_index}"
        )
    exported_actors = data.get("exported_actors")
    if not isinstance(exported_actors, list):
        raise BatchDynamicMeshExportError(f"{manifest_path} must contain exported_actors list")
    actor_count = len(exported_actors)
    if actor_count <= 0:
        raise BatchDynamicMeshExportError(f"{manifest_path} exported_actors must be non-empty")
    for index, raw_actor in enumerate(exported_actors):
        actor = require_object(raw_actor, f"{manifest_path}.exported_actors[{index}]")
        mesh_path = resolve_project_path(
            require_non_empty_string(
                actor.get("exported_mesh_path"),
                f"{manifest_path}.exported_actors[{index}].exported_mesh_path",
            )
        )
        if not mesh_path.exists():
            raise BatchDynamicMeshExportError(f"Actor mesh path does not exist: {mesh_path}")
    return actor_count


def write_index_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["frame_id", "source_sample_index", "manifest_path", "output_dir"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_actor_index_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "frame_id",
        "source_sample_index",
        "actor_frame_manifest_path",
        "output_dir",
        "actor_count",
        "alignment_policy",
        "z_alignment_policy",
        "floor_z",
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
        raise BatchDynamicMeshExportError(f"Config file does not exist: {config_path}")

    blender_path = resolve_blender_or_raise(args.blender)
    experiment = load_experiment_config(config_path)
    visual_frames_path = experiment["output_root"] / "frames" / "dynamic_visual_frames.json"
    if not visual_frames_path.exists():
        raise BatchDynamicMeshExportError(
            f"dynamic_visual_frames.json does not exist: {visual_frames_path}"
        )

    frame_records = load_frame_records(visual_frames_path, experiment["num_frames"])
    if args.max_frames is not None:
        if args.max_frames <= 0:
            raise BatchDynamicMeshExportError("--max-frames must be a positive integer")
        frame_records = frame_records[: args.max_frames]
    output_root = experiment["output_root"] / "frames" / "dynamic_meshes"
    index_csv_path = output_root / "dynamic_mesh_index.csv"
    actor_output_root = experiment["output_root"] / "frames" / "actor_meshes"
    actor_index_csv_path = actor_output_root / "actor_mesh_index.csv"

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

    actor_rows: list[dict[str, Any]] = []
    if args.include_actors:
        actor_options = actor_options_from_experiment(experiment)
        actor_start_time = time.time()
        actor_progress = None
        if not args.no_progress and tqdm is not None:
            actor_progress = tqdm(total=total, desc="actor meshes", unit="frame", dynamic_ncols=True)
        for index, frame in enumerate(frame_records, start=1):
            frame_id = frame["frame_id"]
            source_sample_index = frame["source_sample_index"]
            status = f"frame_id={frame_id} sample={source_sample_index}"
            if actor_progress is None and (
                index == 1
                or index == total
                or (args.progress_every > 0 and index % args.progress_every == 0)
            ):
                print(
                    f"[actor meshes] {index}/{total} {status} "
                    f"elapsed={format_elapsed(time.time() - actor_start_time)}"
                )
            manifest_path = run_actor_export(
                frame_id=frame_id,
                actor_samples_path=actor_options["actor_samples_path"],
                actor_manifest_path=actor_options["actor_manifest_path"],
                output_root=actor_output_root,
                alignment_policy=actor_options["alignment_policy"],
                z_alignment_policy=actor_options["z_alignment_policy"],
                floor_z=actor_options["floor_z"],
                env=env,
            )
            actor_count = validate_actor_manifest(
                manifest_path=manifest_path,
                frame_id=frame_id,
                source_sample_index=source_sample_index,
            )
            actor_rows.append(
                {
                    "frame_id": frame_id,
                    "source_sample_index": source_sample_index,
                    "actor_frame_manifest_path": str(manifest_path),
                    "output_dir": str(manifest_path.parent),
                    "actor_count": actor_count,
                    "alignment_policy": actor_options["alignment_policy"],
                    "z_alignment_policy": actor_options["z_alignment_policy"],
                    "floor_z": actor_options["floor_z"],
                }
            )
            if actor_progress is not None:
                actor_progress.set_postfix_str(status, refresh=False)
                actor_progress.update(1)
        if actor_progress is not None:
            actor_progress.close()

        for row in actor_rows:
            if not Path(row["actor_frame_manifest_path"]).exists():
                raise BatchDynamicMeshExportError(
                    "Indexed actor_frame_manifest_path does not exist: "
                    f"{row['actor_frame_manifest_path']}"
                )

        write_actor_index_csv(actor_index_csv_path, actor_rows)

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
    if args.include_actors:
        actor_first = actor_rows[0]
        actor_last = actor_rows[-1]
        print(f"actor frames: {len(actor_rows)}")
        print(
            f"actor first: frame_id={actor_first['frame_id']}, "
            f"source_sample_index={actor_first['source_sample_index']}, "
            f"actor_frame_manifest_path={actor_first['actor_frame_manifest_path']}"
        )
        print(
            f"actor last: frame_id={actor_last['frame_id']}, "
            f"source_sample_index={actor_last['source_sample_index']}, "
            f"actor_frame_manifest_path={actor_last['actor_frame_manifest_path']}"
        )
        print(f"actor index CSV path: {actor_index_csv_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BatchDynamicMeshExportError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
