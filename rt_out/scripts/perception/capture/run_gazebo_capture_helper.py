#!/usr/bin/env python3
"""Run Gazebo-native perception worlds for the pilot dataset.

This optional helper launches either the semantic panoptic world or the
stable-instance panoptic world. It is an operations helper, not an active
pipeline generation step.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[4]
SCRIPTS_ROOT = PROJECT_ROOT / "rt_out" / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))
from experiment_paths import experiment_log_path, resolve_experiment_root  # noqa: E402

DEFAULT_CONFIG = PROJECT_ROOT / "rt_out/experiments/perception_rt_small_v0/run_20260522_133045/config/perception_dataset_config.json"
DEFAULT_MOTION_SCRIPT = PROJECT_ROOT / "rt_out/scripts/ops/run_all.sh"
VALID_MODES = ("panoptic", "stable_instance_panoptic")
TAIL_SECONDS = 3.0
RESOURCE_PATHS = [
    PROJECT_ROOT / "models",
    PROJECT_ROOT / "models/furniture",
    PROJECT_ROOT / "models/humans",
    PROJECT_ROOT / "models/parts",
    PROJECT_ROOT / "models/robots",
    PROJECT_ROOT / "models/UAVs",
]


def unique_joined_paths(preferred: list[Path], existing: str | None) -> str:
    ordered: list[str] = []
    seen: set[str] = set()
    for path in preferred:
        resolved = str(path.resolve())
        if path.is_dir() and resolved not in seen:
            ordered.append(resolved)
            seen.add(resolved)
    if existing:
        for part in existing.split(":"):
            if part and part not in seen:
                ordered.append(part)
                seen.add(part)
    return ":".join(ordered)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Gazebo Sim against the panoptic or stable-instance panoptic world."
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Perception dataset config JSON.")
    parser.add_argument(
        "--mode",
        choices=VALID_MODES,
        default="panoptic",
        help="Which native world variant to run.",
    )
    parser.add_argument("--run-motion", action="store_true", help="Run the configured motion script while Gazebo is alive.")
    parser.add_argument("--motion-script", default=str(DEFAULT_MOTION_SCRIPT), help="Motion script to run when --run-motion is enabled.")
    parser.add_argument("--gazebo-bin", default="gz", help="Gazebo executable to invoke.")
    parser.add_argument("--gui", action="store_true", help="Run Gazebo with the GUI path instead of server-only mode.")
    parser.add_argument("--timeout-seconds", type=int, default=240, help="Maximum duration for each capture run.")
    parser.add_argument("--force", action="store_true", help="Overwrite selected capture outputs and logs.")
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


def shell_join(parts: list[str]) -> str:
    def quote(value: str) -> str:
        if not value or any(ch in value for ch in " \t\n'\"\\$`()[]{}|&;<>*?!"):
            return "'" + value.replace("'", "'\"'\"'") + "'"
        return value

    return " ".join(quote(part) for part in parts)


def clear_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def ensure_paths_writable(paths: list[Path], force: bool) -> None:
    existing = [path for path in paths if path.exists()]
    if existing and not force:
        fail(
            "Output already exists. Re-run with --force to overwrite: "
            + ", ".join(str(path) for path in existing)
        )
    if force:
        for path in existing:
            clear_path(path)


def build_gazebo_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GZ_SIM_RESOURCE_PATH"] = unique_joined_paths(RESOURCE_PATHS, env.get("GZ_SIM_RESOURCE_PATH"))
    env["IGN_GAZEBO_RESOURCE_PATH"] = unique_joined_paths(RESOURCE_PATHS, env.get("IGN_GAZEBO_RESOURCE_PATH"))
    env["__NV_PRIME_RENDER_OFFLOAD"] = "1"
    env["__GLX_VENDOR_LIBRARY_NAME"] = "nvidia"
    env["__VK_LAYER_NV_optimus"] = "NVIDIA_only"
    env.pop("LIBGL_ALWAYS_SOFTWARE", None)
    env.pop("MESA_LOADER_DRIVER_OVERRIDE", None)
    return env


def count_files(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for item in path.rglob("*") if item.is_file())


def build_command(gazebo_bin: str, world_sdf: Path, gui: bool) -> list[str]:
    command = [gazebo_bin, "sim", "-v", "4", "-r"]
    if not gui:
        command.append("-s")
    command.append(str(world_sdf.resolve()))
    return command


def read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def stderr_indicates_world_load_failure(stderr_text: str) -> bool:
    lowered = stderr_text.lower()
    return "failed to load a world" in lowered or "unable to find world with name" in lowered


def terminate_process(process: subprocess.Popen[Any] | None, grace_seconds: float = 5.0) -> int | None:
    if process is None:
        return None
    if process.poll() is not None:
        return process.returncode
    process.terminate()
    deadline = time.monotonic() + grace_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return process.returncode
        time.sleep(0.1)
    process.kill()
    return process.wait()


def run_single_capture(
    command: list[str],
    env: dict[str, str],
    timeout_seconds: int,
    stdout_log: Path,
    stderr_log: Path,
    run_motion: bool,
    motion_script: Path,
    motion_stdout_log: Path,
    motion_stderr_log: Path,
) -> dict[str, Any]:
    stdout_log.parent.mkdir(parents=True, exist_ok=True)
    stderr_log.parent.mkdir(parents=True, exist_ok=True)
    motion_stdout_log.parent.mkdir(parents=True, exist_ok=True)
    motion_stderr_log.parent.mkdir(parents=True, exist_ok=True)

    start_time = time.monotonic()
    timed_out = False
    motion_timed_out = False
    motion_return_code: int | None = None

    with stdout_log.open("w", encoding="utf-8") as stdout_handle, stderr_log.open("w", encoding="utf-8") as stderr_handle:
        gazebo_proc = subprocess.Popen(
            command,
            cwd=str(PROJECT_ROOT),
            stdout=stdout_handle,
            stderr=stderr_handle,
            env=env,
        )
        motion_proc: subprocess.Popen[Any] | None = None
        motion_tail_deadline: float | None = None

        if run_motion:
            with motion_stdout_log.open("w", encoding="utf-8") as motion_stdout_handle, motion_stderr_log.open(
                "w", encoding="utf-8"
            ) as motion_stderr_handle:
                motion_proc = subprocess.Popen(
                    ["bash", str(motion_script.resolve())],
                    cwd=str(PROJECT_ROOT),
                    stdout=motion_stdout_handle,
                    stderr=motion_stderr_handle,
                    env=env,
                )

                while True:
                    if gazebo_proc.poll() is not None:
                        break
                    elapsed = time.monotonic() - start_time
                    if elapsed >= timeout_seconds:
                        timed_out = True
                        break
                    if motion_proc is not None and motion_proc.poll() is not None and motion_tail_deadline is None:
                        motion_tail_deadline = time.monotonic() + TAIL_SECONDS
                    if motion_tail_deadline is not None and time.monotonic() >= motion_tail_deadline:
                        break
                    time.sleep(0.25)

                if timed_out and motion_proc is not None and motion_proc.poll() is None:
                    motion_timed_out = True
                motion_return_code = terminate_process(motion_proc)
        else:
            while True:
                if gazebo_proc.poll() is not None:
                    break
                if time.monotonic() - start_time >= timeout_seconds:
                    timed_out = True
                    break
                time.sleep(0.25)

        return_code = terminate_process(gazebo_proc)

    stderr_text = read_text(stderr_log)
    stdout_text = read_text(stdout_log)
    return {
        "return_code": return_code,
        "timed_out": timed_out,
        "motion_return_code": motion_return_code,
        "motion_timed_out": motion_timed_out,
        "stderr_text": stderr_text,
        "stdout_text": stdout_text,
    }


def main() -> None:
    args = parse_args()
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    config = load_json(config_path, "perception dataset config")
    if not isinstance(config, dict):
        fail(f"Perception dataset config at {config_path} must be a JSON object.")

    experiment_root = resolve_experiment_root(
        config_path.resolve().parents[1],
        create=False,
        require_existing=True,
    )
    print(f"experiment_root={experiment_root}")
    perception_sdf_root = experiment_root / "perception_sdf"
    panoptic_world_path = perception_sdf_root / "gazebo_native_panoptic_world.sdf"
    stable_instance_world_path = perception_sdf_root / "gazebo_native_stable_instance_panoptic_world.sdf"
    world_paths = {
        "panoptic": panoptic_world_path,
        "stable_instance_panoptic": stable_instance_world_path,
    }
    capture_root = experiment_root / "perception_raw" / "native"
    capture_index_path = capture_root / "capture_index.csv"
    capture_summary_path = capture_root / "capture_summary.json"

    motion_script_path = Path(args.motion_script)
    if not motion_script_path.is_absolute():
        motion_script_path = PROJECT_ROOT / motion_script_path
    if args.run_motion and not motion_script_path.is_file():
        fail(f"Requested motion script does not exist: {motion_script_path}")

    world_path = world_paths[args.mode]
    if not world_path.is_file():
        fail(f"Missing {args.mode} native world: {world_path}")
    overwrite_targets = [capture_index_path, capture_summary_path]
    output_dir = capture_root / args.mode
    stdout_log = experiment_log_path(experiment_root, f"perception/{args.mode}.stdout.log")
    stderr_log = experiment_log_path(experiment_root, f"perception/{args.mode}.stderr.log")
    motion_stdout_log = experiment_log_path(experiment_root, f"perception/{args.mode}.motion.stdout.log")
    motion_stderr_log = experiment_log_path(experiment_root, f"perception/{args.mode}.motion.stderr.log")
    overwrite_targets.append(output_dir)
    run_specs: list[dict[str, Any]] = [
        {
            "mode": args.mode,
            "world_sdf": world_path,
            "output_dir": output_dir,
            "stdout_log": stdout_log,
            "stderr_log": stderr_log,
            "motion_stdout_log": motion_stdout_log,
            "motion_stderr_log": motion_stderr_log,
        }
    ]

    ensure_paths_writable(overwrite_targets, args.force)
    capture_root.mkdir(parents=True, exist_ok=True)
    print(f"stdout_log={stdout_log}")
    print(f"stderr_log={stderr_log}")
    if args.run_motion:
        print(f"motion_stdout_log={motion_stdout_log}")
        print(f"motion_stderr_log={motion_stderr_log}")
    gazebo_env = build_gazebo_env()
    warnings: list[str] = []
    capture_rows: list[dict[str, Any]] = []

    for spec in run_specs:
        mode = spec["mode"]
        world_sdf = spec["world_sdf"]
        output_dir = spec["output_dir"]
        output_dir.mkdir(parents=True, exist_ok=True)

        command = build_command(args.gazebo_bin, world_sdf, args.gui)
        run_result = run_single_capture(
            command=command,
            env=gazebo_env,
            timeout_seconds=args.timeout_seconds,
            stdout_log=spec["stdout_log"],
            stderr_log=spec["stderr_log"],
            run_motion=args.run_motion,
            motion_script=motion_script_path,
            motion_stdout_log=spec["motion_stdout_log"],
            motion_stderr_log=spec["motion_stderr_log"],
        )
        discovered_file_count = count_files(output_dir)
        failed_world_load = stderr_indicates_world_load_failure(run_result["stderr_text"])

        if run_result["timed_out"]:
            status = "timed_out"
        elif failed_world_load:
            status = "failed_world_load"
        elif run_result["return_code"] not in (0, None):
            status = "failed"
        elif args.run_motion and run_result["motion_return_code"] not in (0, None):
            status = "motion_failed"
        elif discovered_file_count > 0:
            status = "success"
        else:
            status = "no_outputs"

        if failed_world_load:
            warnings.append(f"Gazebo reported world load failure for mode={mode}.")
        if discovered_file_count == 0:
            warnings.append(f"No files discovered under {project_rel(output_dir)} after mode={mode}.")
        if args.run_motion and run_result["motion_return_code"] not in (0, None):
            warnings.append(
                f"Motion script {project_rel(motion_script_path)} exited with code {run_result['motion_return_code']} for mode={mode}."
            )

        capture_rows.append(
            {
                "mode": mode,
                "world_sdf": project_rel(world_sdf),
                "command": shell_join(command),
                "return_code": "" if run_result["return_code"] is None else run_result["return_code"],
                "timed_out": str(bool(run_result["timed_out"])).lower(),
                "stdout_log": project_rel(spec["stdout_log"]),
                "stderr_log": project_rel(spec["stderr_log"]),
                "output_dir": project_rel(output_dir),
                "discovered_file_count": discovered_file_count,
                "status": status,
                "run_motion": str(bool(args.run_motion)).lower(),
                "gui": str(bool(args.gui)).lower(),
                "motion_script": project_rel(motion_script_path) if args.run_motion else "",
                "motion_return_code": "" if run_result["motion_return_code"] is None else run_result["motion_return_code"],
                "motion_stdout_log": project_rel(spec["motion_stdout_log"]) if args.run_motion else "",
                "motion_stderr_log": project_rel(spec["motion_stderr_log"]) if args.run_motion else "",
            }
        )

    with capture_index_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "mode",
            "world_sdf",
            "command",
            "return_code",
            "timed_out",
            "stdout_log",
            "stderr_log",
            "output_dir",
            "discovered_file_count",
            "status",
            "run_motion",
            "gui",
            "motion_script",
            "motion_return_code",
            "motion_stdout_log",
            "motion_stderr_log",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(capture_rows)

    success_count = sum(1 for row in capture_rows if row["status"] == "success")
    timed_out_count = sum(1 for row in capture_rows if row["status"] == "timed_out")
    failed_count = len(capture_rows) - success_count - timed_out_count
    total_discovered_files = sum(int(row["discovered_file_count"]) for row in capture_rows)

    summary = {
        "attempted_run_count": len(capture_rows),
        "success_count": success_count,
        "failed_count": failed_count,
        "timed_out_count": timed_out_count,
        "total_discovered_files": total_discovered_files,
        "modes": [args.mode],
        "primary_mode": "panoptic",
        "run_motion": bool(args.run_motion),
        "gui": bool(args.gui),
        "motion_script": project_rel(motion_script_path) if args.run_motion else None,
        "gz_sim_resource_path": gazebo_env["GZ_SIM_RESOURCE_PATH"],
        "ign_gazebo_resource_path": gazebo_env["IGN_GAZEBO_RESOURCE_PATH"],
        "capture_root": project_rel(capture_root),
        "warnings": warnings,
    }
    write_json(capture_summary_path, summary)

    print(f"experiment_name={config.get('experiment_name', 'perception_rt_small_v0')}")
    print(f"selected_run_count={len(capture_rows)}")
    print(f"mode={args.mode}")
    print(f"run_motion={bool(args.run_motion)}")
    print(f"gui={bool(args.gui)}")
    print(f"capture_index={project_rel(capture_index_path)}")
    print(f"capture_summary={project_rel(capture_summary_path)}")


if __name__ == "__main__":
    main()
