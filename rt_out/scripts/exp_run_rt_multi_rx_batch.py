#!/usr/bin/env python3

"""Run multi-RX RT evaluation over an experiment XML batch.

This wrapper keeps the validated single-scene Sionna sanity script untouched and
adds experiment-level iteration, richer path/delay/gain summaries, and CSV
logging across many frame/RX combinations.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SANITY_SCRIPT = PROJECT_ROOT / "rt_out" / "scripts" / "24_run_sionna_rt_sanity.py"

TAU_STATS_SCRIPT = r"""
import json
import sys
from pathlib import Path

import numpy as np
import sionna.rt  # noqa: F401
import mitsuba as mi
from sionna.rt import PlanarArray, Receiver, Transmitter, PathSolver, load_scene


def parse_vec3(text):
    parts = [float(item) for item in text.split(",")]
    if len(parts) != 3:
        raise ValueError("expected x,y,z")
    return tuple(parts)


def load_sionna_scene(xml_path):
    try:
        return load_scene(str(xml_path), merge_shapes=False)
    except TypeError as exc:
        if "merge_shapes" not in str(exc):
            raise
        return load_scene(str(xml_path))


xml = Path(sys.argv[1]).resolve()
scene = load_sionna_scene(xml)
scene.frequency = float(sys.argv[2])
tx_pos = parse_vec3(sys.argv[3])
rx_pos = parse_vec3(sys.argv[4])

scene.tx_array = PlanarArray(
    num_rows=1,
    num_cols=1,
    vertical_spacing=0.5,
    horizontal_spacing=0.5,
    pattern="iso",
    polarization="V",
)
scene.rx_array = PlanarArray(
    num_rows=1,
    num_cols=1,
    vertical_spacing=0.5,
    horizontal_spacing=0.5,
    pattern="iso",
    polarization="V",
)
tx = Transmitter(name="tx_static_sanity", position=mi.Point3f(*tx_pos))
rx = Receiver(name="rx_static_sanity", position=mi.Point3f(*rx_pos))
scene.add(tx)
scene.add(rx)
tx.look_at(rx)

paths = PathSolver()(
    scene=scene,
    max_depth=2,
    max_num_paths_per_src=10_000,
    samples_per_src=20_000,
    synthetic_array=True,
    los=True,
    specular_reflection=True,
    diffuse_reflection=False,
    refraction=False,
    seed=42,
)
valid = np.asarray(paths.valid.numpy()).astype(bool)
tau = np.asarray(paths.tau.numpy())
tau_values = tau[valid]

path_gain_sum = None
path_gain_db = None
gain_method = None
gain_error = None
gain_debug = None
a_shape = None
tau_cir_shape = None
valid_shape = list(np.asarray(paths.valid.numpy()).shape)
tau_shape = list(np.asarray(paths.tau.numpy()).shape)

try:
    cir_result = paths.cir(
        sampling_frequency=1.0,
        num_time_steps=1,
        normalize_delays=False,
        out_type="numpy",
    )
    if not isinstance(cir_result, (tuple, list)) or len(cir_result) < 2:
        raise ValueError("paths.cir(...) did not return a (a, tau) pair")

    a_raw = cir_result[0]
    tau_cir = cir_result[1]

    if isinstance(a_raw, (tuple, list)) and len(a_raw) == 2:
        a_real = np.asarray(a_raw[0])
        a_imag = np.asarray(a_raw[1])
        a_complex = a_real + 1j * a_imag
        gain_method = "cir_real_imag"
    else:
        a_complex = np.asarray(a_raw)
        gain_method = "cir_coefficients"

    tau_cir = np.asarray(tau_cir)
    a_shape = list(np.asarray(a_complex).shape)
    tau_cir_shape = list(np.asarray(tau_cir).shape)
    if a_complex.size == 0:
        raise ValueError("paths.cir(...) returned empty coefficients")

    try:
        valid_cir = np.asarray(tau_cir >= 0)
        valid_mask = valid_cir
        if (
            valid_cir.ndim <= a_complex.ndim
            and valid_cir.shape
            and len(a_complex.shape) >= 2
            and valid_cir.shape[-1] == a_complex.shape[-2]
        ):
            leading_shape = list(valid_cir.shape[:-1])
            path_axis = a_complex.ndim - 2
            extra_before = path_axis - len(leading_shape)
            if extra_before < 0:
                raise ValueError(
                    f"Cannot align valid_cir shape {valid_cir.shape} to path axis "
                    f"{path_axis} in coefficient shape {a_complex.shape}"
                )
            extra_after = a_complex.ndim - (
                len(leading_shape) + extra_before + 1
            )
            if extra_after < 0:
                raise ValueError(
                    f"Computed negative extra_after while aligning valid_cir shape "
                    f"{valid_cir.shape} to coefficient shape {a_complex.shape}"
                )
            valid_mask = valid_cir.reshape(
                leading_shape
                + [1] * extra_before
                + [valid_cir.shape[-1]]
                + [1] * extra_after
            )
        else:
            while valid_mask.ndim < a_complex.ndim:
                valid_mask = np.expand_dims(valid_mask, axis=0)
        if valid_mask.shape != a_complex.shape:
            valid_mask = np.broadcast_to(valid_mask, a_complex.shape)
        gain = float(np.sum(np.abs(a_complex[valid_mask]) ** 2))
        path_gain_sum = gain
        path_gain_db = float(10.0 * np.log10(gain + 1e-30))
        gain_method = f"{gain_method}_tau_mask"
    except Exception as exc:
        gain_debug = f"{type(exc).__name__}: {exc}"
        coeff = np.asarray(a_complex)
        finite = np.isfinite(np.real(coeff)) & np.isfinite(np.imag(coeff))
        gain = float(np.sum(np.abs(coeff[finite]) ** 2))
        path_gain_sum = gain
        path_gain_db = float(10.0 * np.log10(gain + 1e-30))
        gain_method = f"{gain_method}_finite_fallback"
except Exception as exc:
    gain_error = f"{type(exc).__name__}: {exc}"

result = {
    "num_paths": int(np.count_nonzero(valid)),
    "tau_min": float(tau_values.min()) if tau_values.size else None,
    "tau_max": float(tau_values.max()) if tau_values.size else None,
    "path_gain_sum": path_gain_sum,
    "path_gain_db": path_gain_db,
    "gain_method": gain_method,
    "gain_error": gain_error,
    "a_shape": a_shape,
    "tau_cir_shape": tau_cir_shape,
    "valid_shape": valid_shape,
    "tau_shape": tau_shape,
    "gain_debug": gain_debug,
}
print("RESULT_JSON " + json.dumps(result, sort_keys=True))
"""


class ExperimentRtBatchError(RuntimeError):
    pass


try:
    from tqdm.auto import tqdm
except Exception:  # pragma: no cover - optional dependency
    tqdm = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run multi-RX RT sanity across experiment-local Sionna XML files."
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to experiment_config.json",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue collecting rows after a failing XML/RX run instead of failing fast.",
    )
    parser.add_argument(
        "--max-frames",
        type=int,
        default=None,
        help="Optional debug limit on the number of XML frames to process.",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=None,
        help="Optional debug limit on the total number of XML/RX rows to process.",
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
        raise ExperimentRtBatchError(f"Missing input file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ExperimentRtBatchError(f"Invalid JSON in {path}: {exc}") from exc


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ExperimentRtBatchError(f"{label} must be an object")
    return value


def require_non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExperimentRtBatchError(f"{label} must be a non-empty string")
    return value.strip()


def require_positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ExperimentRtBatchError(f"{label} must be a positive integer")
    return value


def require_numeric(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ExperimentRtBatchError(f"{label} must be numeric")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ExperimentRtBatchError(f"{label} must be numeric") from exc


def resolve_project_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def parse_position(value: Any, label: str) -> tuple[float, float, float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ExperimentRtBatchError(f"{label} must be a list of 3 numbers")
    return (
        require_numeric(value[0], f"{label}[0]"),
        require_numeric(value[1], f"{label}[1]"),
        require_numeric(value[2], f"{label}[2]"),
    )


def vec3_arg(value: tuple[float, float, float]) -> str:
    return f"{value[0]},{value[1]},{value[2]}"


def runtime_env() -> dict[str, str]:
    # Give Mitsuba/Dr.Jit stable cache/config directories so long RT batches do
    # not depend on whatever per-user state happens to exist already.
    env = os.environ.copy()
    mpl_config = Path("/tmp/matplotlib-collabpaper")
    drjit_cache = Path("/tmp/drjit-collabpaper")
    mpl_config.mkdir(parents=True, exist_ok=True)
    drjit_cache.mkdir(parents=True, exist_ok=True)
    env["MPLCONFIGDIR"] = str(mpl_config)
    env["DRJIT_CACHE_DIR"] = str(drjit_cache)
    return env


def run_command(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    # Centralize subprocess execution so every helper runs from the repository
    # root and reports stdout/stderr consistently on failure.
    result = subprocess.run(
        command,
        cwd=str(PROJECT_ROOT),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode != 0:
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        raise ExperimentRtBatchError(
            f"Command failed with exit code {result.returncode}: {' '.join(command)}"
        )
    return result


def parse_num_paths(output: str) -> int | None:
    # Reuse the same stdout parsing convention as the validated sanity scripts:
    # a single `paths_found : N` line from 24_run_sionna_rt_sanity.py.
    match = re.search(r"paths_found\s*:\s*(\d+)", output)
    return int(match.group(1)) if match else None


def error_message_from_result(result: subprocess.CompletedProcess[str]) -> str:
    # Prefer the explicit ERROR line from the child script when available so the
    # batch CSV records a human-meaningful failure reason.
    combined = "\n".join(part for part in [result.stdout, result.stderr] if part)
    for line in combined.splitlines():
        if "ERROR:" in line:
            return line.strip()
    return f"returncode={result.returncode}"


def extract_tau_stats(
    *,
    xml_path: Path,
    frequency_hz: float,
    tx_position: tuple[float, float, float],
    rx_position: tuple[float, float, float],
    env: dict[str, str],
) -> tuple[
    int | None,
    float | None,
    float | None,
    float | None,
    float | None,
    str | None,
    str | None,
    list[int] | None,
    list[int] | None,
    list[int] | None,
    list[int] | None,
    str | None,
    str | None,
]:
    # Launch the embedded helper under the active Python environment so we can
    # inspect the Sionna Paths object directly without modifying script 24.
    result = run_command(
        [
            sys.executable,
            "-c",
            TAU_STATS_SCRIPT,
            str(xml_path),
            str(frequency_hz),
            vec3_arg(tx_position),
            vec3_arg(rx_position),
        ],
        env=env,
        check=False,
    )
    if result.returncode != 0:
        return None, None, None, None, None, None, None, None, None, None, None, None, error_message_from_result(result)

    for line in result.stdout.splitlines():
        if line.startswith("RESULT_JSON "):
            # The helper prints exactly one JSON payload line so the wrapper can
            # keep using plain subprocess calls instead of shared imports.
            payload = json.loads(line.removeprefix("RESULT_JSON "))
            return (
                payload["num_paths"],
                payload["tau_min"],
                payload["tau_max"],
                payload.get("path_gain_sum"),
                payload.get("path_gain_db"),
                payload.get("gain_method"),
                payload.get("gain_error"),
                payload.get("a_shape"),
                payload.get("tau_cir_shape"),
                payload.get("valid_shape"),
                payload.get("tau_shape"),
                payload.get("gain_debug"),
                None,
            )

    return None, None, None, None, None, None, None, None, None, None, None, None, "tau statistics helper did not print RESULT_JSON"


def load_experiment_config(path: Path) -> dict[str, Any]:
    # Load only the experiment settings needed for RT: frame count, frequency,
    # TX power, one TX position, the RX list, and the output root.
    data = require_object(load_json(path), "experiment_config.json")
    experiment_name = require_non_empty_string(
        data.get("experiment_name"),
        "experiment_config.experiment_name",
    )
    num_frames = require_positive_int(
        data.get("num_frames"),
        "experiment_config.num_frames",
    )
    frequency_ghz = require_numeric(
        data.get("frequency_ghz"),
        "experiment_config.frequency_ghz",
    )
    raw_tx_power_dbm = data.get("tx_power_dbm", 30.0)
    tx_power_dbm = require_numeric(
        raw_tx_power_dbm,
        "experiment_config.tx_power_dbm",
    )
    tx = require_object(data.get("tx"), "experiment_config.tx")
    tx_position = parse_position(tx.get("position"), "experiment_config.tx.position")

    raw_rx_list = data.get("rx_list")
    if not isinstance(raw_rx_list, list) or not raw_rx_list:
        raise ExperimentRtBatchError("experiment_config.rx_list must be a non-empty list")
    rx_list: list[dict[str, Any]] = []
    seen_rx_ids: set[str] = set()
    for index, item in enumerate(raw_rx_list):
        # Keep RX validation strict because the batch loops over every RX for
        # every frame and a malformed entry would cascade into many failures.
        rx = require_object(item, f"experiment_config.rx_list[{index}]")
        rx_id = require_non_empty_string(rx.get("id"), f"experiment_config.rx_list[{index}].id")
        if rx_id in seen_rx_ids:
            raise ExperimentRtBatchError(f"Duplicate rx_list id: {rx_id}")
        seen_rx_ids.add(rx_id)
        rx_list.append(
            {
                "id": rx_id,
                "position": parse_position(
                    rx.get("position"),
                    f"experiment_config.rx_list[{index}].position",
                ),
            }
        )

    output_dir = require_non_empty_string(
        data.get("output_dir"),
        "experiment_config.output_dir",
    )
    output_root = resolve_project_path(output_dir)
    return {
        "experiment_name": experiment_name,
        "num_frames": num_frames,
        "frequency_hz": frequency_ghz * 1e9,
        "tx_power_dbm": tx_power_dbm,
        "tx_position": tx_position,
        "rx_list": rx_list,
        "output_root": output_root,
    }


def load_xml_index(path: Path, expected_count: int) -> list[dict[str, Any]]:
    # Read the XML index produced by the batch XML builder and reduce it to the
    # frame/sample/XML triples needed by this RT wrapper.
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except FileNotFoundError as exc:
        raise ExperimentRtBatchError(f"Missing sionna_xml_index.csv: {path}") from exc

    if len(rows) != expected_count:
        raise ExperimentRtBatchError(
            f"sionna_xml_index.csv has {len(rows)} rows, expected {expected_count}"
        )

    frame_rows: list[dict[str, Any]] = []
    seen_frame_ids: set[int] = set()
    for index, row in enumerate(rows):
        # Validate every frame row before the RT loop starts so failures surface
        # early and do not waste time halfway through the batch.
        try:
            frame_id = int(row["frame_id"])
            source_sample_index = int(row["source_sample_index"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ExperimentRtBatchError(f"Invalid frame row at index {index}") from exc
        xml_value = require_non_empty_string(row.get("xml_path"), f"row[{index}].xml_path")
        xml_path = Path(xml_value).expanduser().resolve()
        if frame_id in seen_frame_ids:
            raise ExperimentRtBatchError(f"Duplicate frame_id in sionna_xml_index.csv: {frame_id}")
        seen_frame_ids.add(frame_id)
        if not xml_path.exists():
            raise ExperimentRtBatchError(
                f"XML path does not exist for frame_id={frame_id}: {xml_path}"
            )
        frame_rows.append(
            {
                "frame_id": frame_id,
                "source_sample_index": source_sample_index,
                "xml_path": xml_path,
            }
        )
    return frame_rows


def run_one_row(
    *,
    frame_id: int,
    source_sample_index: int,
    xml_path: Path,
    tx_power_dbm: float,
    tx_position: tuple[float, float, float],
    rx_id: str,
    rx_position: tuple[float, float, float],
    frequency_hz: float,
    env: dict[str, str],
) -> dict[str, Any]:
    # Run one XML scene for one TX/RX pair. The wrapper keeps the validated RT
    # sanity script untouched and only adds row-level bookkeeping plus helpers.
    sanity_result = run_command(
        [
            sys.executable,
            str(SANITY_SCRIPT),
            "--xml",
            str(xml_path),
            f"--tx={vec3_arg(tx_position)}",
            f"--rx={vec3_arg(rx_position)}",
            f"--frequency-hz={frequency_hz}",
        ],
        env=env,
        check=False,
    )

    sanity_ok = sanity_result.returncode == 0
    num_paths = parse_num_paths(sanity_result.stdout)
    tau_min = None
    tau_max = None
    delay_spread = None
    path_gain_sum = None
    path_gain_db = None
    rx_power_dbm = None
    gain_method = ""
    gain_error = ""
    a_shape = ""
    tau_cir_shape = ""
    valid_shape = ""
    tau_shape = ""
    gain_debug = ""
    error_message = ""

    if sanity_ok:
        # Re-run the same scene through the embedded helper so we can extract
        # path-count, delay, and gain diagnostics directly from the Paths object.
        (
            helper_num_paths,
            tau_min,
            tau_max,
            path_gain_sum,
            path_gain_db,
            gain_method,
            helper_gain_error,
            helper_a_shape,
            helper_tau_cir_shape,
            helper_valid_shape,
            helper_tau_shape,
            helper_gain_debug,
            helper_error,
        ) = extract_tau_stats(
            xml_path=xml_path,
            frequency_hz=frequency_hz,
            tx_position=tx_position,
            rx_position=rx_position,
            env=env,
        )
        if helper_error is None:
            # The helper is the authoritative source for tau/gain metrics, while
            # the outer sanity script still provides the operational pass/fail check.
            num_paths = helper_num_paths
            if tau_min is not None and tau_max is not None:
                delay_spread = float(tau_max - tau_min)
            if path_gain_db is not None:
                rx_power_dbm = float(tx_power_dbm + path_gain_db)
            gain_method = "" if gain_method is None else str(gain_method)
            gain_error = "" if helper_gain_error is None else str(helper_gain_error)
            a_shape = "" if helper_a_shape is None else json.dumps(helper_a_shape)
            tau_cir_shape = "" if helper_tau_cir_shape is None else json.dumps(helper_tau_cir_shape)
            valid_shape = "" if helper_valid_shape is None else json.dumps(helper_valid_shape)
            tau_shape = "" if helper_tau_shape is None else json.dumps(helper_tau_shape)
            gain_debug = "" if helper_gain_debug is None else str(helper_gain_debug)
        else:
            # Treat helper failure as a row failure because this experiment wants
            # a complete metrics record for every successful RT solve.
            sanity_ok = False
            error_message = helper_error
    else:
        error_message = error_message_from_result(sanity_result)

    # Write one flat CSV row per frame/RX pair so later label-generation and
    # ablation scripts can operate without reopening XML or re-running Sionna.
    return {
        "frame_id": frame_id,
        "source_sample_index": source_sample_index,
        "rx_id": rx_id,
        "xml_path": str(xml_path),
        "tx_power_dbm": tx_power_dbm,
        "tx_x": tx_position[0],
        "tx_y": tx_position[1],
        "tx_z": tx_position[2],
        "rx_x": rx_position[0],
        "rx_y": rx_position[1],
        "rx_z": rx_position[2],
        "frequency_hz": frequency_hz,
        "num_paths": "" if num_paths is None else num_paths,
        "tau_min": "" if tau_min is None else tau_min,
        "tau_max": "" if tau_max is None else tau_max,
        "delay_spread": "" if delay_spread is None else delay_spread,
        "path_gain_sum": "" if path_gain_sum is None else path_gain_sum,
        "path_gain_db": "" if path_gain_db is None else path_gain_db,
        "rx_power_dbm": "" if rx_power_dbm is None else rx_power_dbm,
        "gain_method": gain_method,
        "gain_error": gain_error,
        "a_shape": a_shape,
        "tau_cir_shape": tau_cir_shape,
        "valid_shape": valid_shape,
        "tau_shape": tau_shape,
        "gain_debug": gain_debug,
        "sanity_ok": sanity_ok,
        "error_message": error_message,
    }


def write_summary(path: Path, rows: list[dict[str, Any]]) -> None:
    # Persist the full per-row table so later labeling and ablation steps never
    # need to rerun RT just to recover metrics.
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "frame_id",
        "source_sample_index",
        "rx_id",
        "xml_path",
        "tx_power_dbm",
        "tx_x",
        "tx_y",
        "tx_z",
        "rx_x",
        "rx_y",
        "rx_z",
        "frequency_hz",
        "num_paths",
        "tau_min",
        "tau_max",
        "delay_spread",
        "path_gain_sum",
        "path_gain_db",
        "rx_power_dbm",
        "gain_method",
        "gain_error",
        "a_shape",
        "tau_cir_shape",
        "valid_shape",
        "tau_shape",
        "gain_debug",
        "sanity_ok",
        "error_message",
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


def print_rx_summary(rows: list[dict[str, Any]], rx_list: list[dict[str, Any]]) -> None:
    # Summarize path counts and any gain/power metrics per receiver so a batch
    # run can be sanity-checked without opening the CSV manually.
    print("summary by rx_id:")
    for rx in rx_list:
        rx_id = rx["id"]
        successful_paths = [
            int(row["num_paths"])
            for row in rows
            if row["rx_id"] == rx_id and row["sanity_ok"] and row["num_paths"] != ""
        ]
        successful_gains = [
            float(row["path_gain_db"])
            for row in rows
            if row["rx_id"] == rx_id and row["sanity_ok"] and row["path_gain_db"] != ""
        ]
        successful_rx_powers = [
            float(row["rx_power_dbm"])
            for row in rows
            if row["rx_id"] == rx_id and row["sanity_ok"] and row["rx_power_dbm"] != ""
        ]
        if not successful_paths:
            print(f"  {rx_id}: no successful rows")
            continue
        summary = (
            f"  {rx_id}: mean={statistics.mean(successful_paths):.3f}, "
            f"min={min(successful_paths)}, max={max(successful_paths)}"
        )
        if successful_gains:
            summary += (
                f", gain_db_mean={statistics.mean(successful_gains):.3f}, "
                f"gain_db_min={min(successful_gains):.3f}, gain_db_max={max(successful_gains):.3f}"
            )
        if successful_rx_powers:
            summary += (
                f", rx_power_dbm_mean={statistics.mean(successful_rx_powers):.3f}, "
                f"rx_power_dbm_min={min(successful_rx_powers):.3f}, "
                f"rx_power_dbm_max={max(successful_rx_powers):.3f}"
            )
        print(summary)


def main() -> int:
    args = parse_args()
    config_path = args.config.expanduser().resolve()
    if not config_path.exists():
        raise ExperimentRtBatchError(f"Config file does not exist: {config_path}")

    experiment = load_experiment_config(config_path)
    xml_index_path = experiment["output_root"] / "sionna_xml" / "sionna_xml_index.csv"
    frame_rows = load_xml_index(xml_index_path, experiment["num_frames"])
    if args.max_frames is not None:
        # Debug mode can clip the XML list before the RX expansion so a short run
        # still exercises the same inner logic as the full batch.
        if args.max_frames <= 0:
            raise ExperimentRtBatchError("--max-frames must be a positive integer")
        frame_rows = frame_rows[: args.max_frames]
    if args.max_rows is not None and args.max_rows <= 0:
        raise ExperimentRtBatchError("--max-rows must be a positive integer")

    output_csv_path = experiment["output_root"] / "rt_results" / "rt_100frames_multi_rx.csv"
    env = runtime_env()
    rows: list[dict[str, Any]] = []
    # Progress is counted at XML/RX row granularity because each row corresponds
    # to one actual Sionna solve and one helper pass.
    expected_rows = len(frame_rows) * len(experiment["rx_list"])
    if args.max_rows is not None:
        expected_rows = min(expected_rows, args.max_rows)
    progress = None
    start_time = time.time()
    if not args.no_progress and tqdm is not None:
        progress = tqdm(total=expected_rows, desc="run rt multi-rx", unit="row", dynamic_ncols=True)

    for frame in frame_rows:
        frame_id = frame["frame_id"]
        source_sample_index = frame["source_sample_index"]
        xml_path = frame["xml_path"]
        # Expand each frame-level XML into one RT row per configured receiver.
        for rx in experiment["rx_list"]:
            if args.max_rows is not None and len(rows) >= args.max_rows:
                break
            row_index = len(rows) + 1
            status = f"frame_id={frame_id} sample={source_sample_index} rx_id={rx['id']}"
            if progress is None and (
                row_index == 1
                or row_index == expected_rows
                or (args.progress_every > 0 and row_index % args.progress_every == 0)
            ):
                # Fallback progress printing keeps long non-tqdm runs observable
                # in plain terminals and log files.
                print(
                    f"[run rt multi-rx] {row_index}/{expected_rows} {status} "
                    f"elapsed={format_elapsed(time.time() - start_time)}"
                )
            row = run_one_row(
                frame_id=frame_id,
                source_sample_index=source_sample_index,
                xml_path=xml_path,
                tx_power_dbm=experiment["tx_power_dbm"],
                tx_position=experiment["tx_position"],
                rx_id=rx["id"],
                rx_position=rx["position"],
                frequency_hz=experiment["frequency_hz"],
                env=env,
            )
            rows.append(row)
            if progress is not None:
                progress.set_postfix_str(status, refresh=False)
                progress.update(1)
            if not row["sanity_ok"] and not args.continue_on_error:
                # Fail fast by default, but still flush the partial CSV so the
                # failing frame/RX combination can be inspected immediately.
                write_summary(output_csv_path, rows)
                print(
                    f"FAIL: frame_id={frame_id} rx_id={rx['id']} xml_path={xml_path} "
                    f"error={row['error_message']}",
                    file=sys.stderr,
                )
                raise ExperimentRtBatchError(
                    "RT run failed for "
                    f"frame_id={frame_id}, rx_id={rx['id']}, xml_path={xml_path}: "
                    f"{row['error_message']}"
                )
        if args.max_rows is not None and len(rows) >= args.max_rows:
            # Stop cleanly once the requested debug row budget is reached.
            break
    if progress is not None:
        progress.close()

    write_summary(output_csv_path, rows)

    # Print a compact batch summary so the user can confirm row counts and per-RX
    # path behavior without opening the CSV immediately.
    print(f"experiment_name: {experiment['experiment_name']}")
    print(f"num_frames: {len(frame_rows)}")
    print(f"num_rx: {len(experiment['rx_list'])}")
    print(f"tx_power_dbm: {experiment['tx_power_dbm']}")
    print(f"expected_rows: {expected_rows}")
    print(f"actual_rows: {len(rows)}")
    print(f"output CSV path: {output_csv_path}")
    print_rx_summary(rows, experiment["rx_list"])

    if not args.continue_on_error:
        failed = [row for row in rows if not row["sanity_ok"]]
        if failed:
            raise ExperimentRtBatchError("One or more RT runs failed; see output CSV.")

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ExperimentRtBatchError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
