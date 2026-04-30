#!/usr/bin/env python3
"""Run the validated three-frame sanity flow against multiple RX positions.

This wrapper keeps the same frame/XML logic as the prototype sanity path but
expands the evaluation to several approved receiver sites so we can compare
path-count and delay behavior across different static viewpoints.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from dynamic_prototype_config import load_dynamic_prototype_config
from rt_material_config import load_rt_runtime_config


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = PROJECT_ROOT / "rt_out" / "scripts"

COMPOSE_SCRIPT = SCRIPT_DIR / "33_compose_prototype_frame_scene.py"
SIONNA_XML_SCRIPT = SCRIPT_DIR / "34_build_prototype_frame_sionna_xml.py"
SANITY_SCRIPT = SCRIPT_DIR / "24_run_sionna_rt_sanity.py"

DEFAULT_STATIC_MANIFEST_PATH = (
    PROJECT_ROOT / "rt_out" / "static_scene" / "export" / "merged_static_manifest.json"
)
DEFAULT_COMPOSED_ROOT = PROJECT_ROOT / "rt_out" / "composed_scene"
DEFAULT_OUTPUT_CSV = DEFAULT_COMPOSED_ROOT / "three_frame_three_rx_rt_summary.csv"
DEFAULT_RADIO_SITES_PATH = PROJECT_ROOT / "rt_out" / "config" / "prototype_radio_sites.json"

PROTOTYPE_CONFIG = load_dynamic_prototype_config()
PROTOTYPE_FRAMES = [
    (frame["frame_id"], frame["source_sample_index"])
    for frame in PROTOTYPE_CONFIG["prototype_frames"]
]
CARRIER_FREQUENCY_HZ = load_rt_runtime_config().carrier_frequency_hz

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
result = {
    "num_paths": int(np.count_nonzero(valid)),
    "tau_min": float(tau_values.min()) if tau_values.size else None,
    "tau_max": float(tau_values.max()) if tau_values.size else None,
}
print("RESULT_JSON " + json.dumps(result, sort_keys=True))
"""


class ThreeFrameThreeRxError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the 3-frame x 3-RX RT sanity evaluation on the current prototype branch."
    )
    parser.add_argument(
        "--radio-sites",
        type=Path,
        default=DEFAULT_RADIO_SITES_PATH,
        help="Path to prototype_radio_sites.json",
    )
    parser.add_argument(
        "--static-manifest",
        type=Path,
        default=DEFAULT_STATIC_MANIFEST_PATH,
        help="Static merged manifest path",
    )
    parser.add_argument(
        "--composed-root",
        type=Path,
        default=DEFAULT_COMPOSED_ROOT,
        help="Composed scene root",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=DEFAULT_OUTPUT_CSV,
        help="Output CSV path",
    )
    return parser.parse_args()


def collabpaper_python_executable() -> Path:
    # Sionna/Mitsuba live in the dedicated collabpaper environment, so locate
    # that interpreter explicitly instead of assuming the current shell Python.
    candidates: list[Path] = []

    env_path = os.environ.get("COLLABPAPER_PYTHON")
    if env_path:
        candidates.append(Path(env_path).expanduser())

    candidates.extend(
        [
            Path.home() / "miniconda3" / "envs" / "collabpaper" / "bin" / "python",
            Path.home() / "anaconda3" / "envs" / "collabpaper" / "bin" / "python",
        ]
    )

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()

    raise ThreeFrameThreeRxError(
        "Could not find collabpaper Python. Set COLLABPAPER_PYTHON or install "
        f"the environment in a standard conda location. Checked: {[str(c) for c in candidates]}"
    )


def runtime_env() -> dict[str, str]:
    # Give long-running RT helpers stable cache/config directories that are safe
    # to create on shared systems.
    env = os.environ.copy()
    mpl_config = Path("/tmp/matplotlib-collabpaper")
    drjit_cache = Path("/tmp/drjit-collabpaper")
    mpl_config.mkdir(parents=True, exist_ok=True)
    drjit_cache.mkdir(parents=True, exist_ok=True)
    env["MPLCONFIGDIR"] = str(mpl_config)
    env["DRJIT_CACHE_DIR"] = str(drjit_cache)
    return env


def frame_dir_name(frame_id: int) -> str:
    return f"frame_{frame_id:03d}"


def composed_manifest_path(frame_id: int, composed_root: Path) -> Path:
    return composed_root / frame_dir_name(frame_id) / f"composed_frame_{frame_id:03d}_manifest.json"


def xml_path(frame_id: int, composed_root: Path) -> Path:
    return composed_root / frame_dir_name(frame_id) / f"frame_{frame_id:03d}_sionna.xml"


def run_command(
    command: list[str],
    *,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
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
        raise ThreeFrameThreeRxError(
            f"Command failed with exit code {result.returncode}: {' '.join(command)}"
        )
    return result


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise ThreeFrameThreeRxError(f"Missing JSON file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ThreeFrameThreeRxError(f"Invalid JSON in {path}: {exc}") from exc


def parse_vec3_list(value: Any, *, label: str) -> tuple[float, float, float]:
    if not isinstance(value, list) or len(value) != 3:
        raise ThreeFrameThreeRxError(f"{label} must be a list of 3 numbers")
    out: list[float] = []
    for index, item in enumerate(value):
        try:
            out.append(float(item))
        except (TypeError, ValueError) as exc:
            raise ThreeFrameThreeRxError(f"{label}[{index}] must be numeric") from exc
    return (out[0], out[1], out[2])


def vec3_arg(value: tuple[float, float, float]) -> str:
    return f"{value[0]},{value[1]},{value[2]}"


def vec3_json(value: tuple[float, float, float]) -> str:
    return json.dumps([value[0], value[1], value[2]])


def load_radio_sites(config_path: Path) -> tuple[str, tuple[float, float, float], list[tuple[str, tuple[float, float, float]]]]:
    # Load the validated multi-RX sanity layout. This script intentionally
    # reuses fixed sites rather than inventing new positions on the fly.
    data = load_json(config_path)
    if not isinstance(data, dict):
        raise ThreeFrameThreeRxError("prototype_radio_sites.json root must be an object")

    tx_sites = data.get("tx_sites")
    rx_sites = data.get("rx_sites")
    if not isinstance(tx_sites, dict) or not tx_sites:
        raise ThreeFrameThreeRxError("prototype_radio_sites.json must contain a non-empty tx_sites object")
    if not isinstance(rx_sites, dict) or not rx_sites:
        raise ThreeFrameThreeRxError("prototype_radio_sites.json must contain a non-empty rx_sites object")

    if "tx_ap" not in tx_sites:
        raise ThreeFrameThreeRxError("prototype_radio_sites.json is missing tx_sites.tx_ap")

    required_rx_ids = ["rx_panda_base", "rx_ur5_base", "rx_cerberus_base"]
    missing_rx = [rx_id for rx_id in required_rx_ids if rx_id not in rx_sites]
    if missing_rx:
        raise ThreeFrameThreeRxError(
            f"prototype_radio_sites.json is missing rx_sites entries: {missing_rx}"
        )

    tx_id = "tx_ap"
    tx_position = parse_vec3_list(tx_sites[tx_id], label=f"tx_sites.{tx_id}")
    rx_records = [
        (rx_id, parse_vec3_list(rx_sites[rx_id], label=f"rx_sites.{rx_id}"))
        for rx_id in required_rx_ids
    ]
    return tx_id, tx_position, rx_records


def validate_static_manifest(path: Path) -> None:
    data = load_json(path)
    if not isinstance(data, dict):
        raise ThreeFrameThreeRxError("Static manifest root must be an object")
    groups = data.get("merged_groups")
    if not isinstance(groups, list) or not groups:
        raise ThreeFrameThreeRxError("Static manifest must contain merged_groups")


def compose_and_emit_frame(
    frame_id: int,
    *,
    source_sample_index: int,
    static_manifest_path: Path,
    composed_root: Path,
) -> Path:
    # Reuse the validated composition and XML builders to produce the per-frame
    # scene that will be evaluated from several RX viewpoints.
    output_manifest = composed_manifest_path(frame_id, composed_root)
    output_xml = xml_path(frame_id, composed_root)

    run_command(
        [
            sys.executable,
            str(COMPOSE_SCRIPT),
            "--frame-id",
            str(frame_id),
            "--static-manifest",
            str(static_manifest_path),
            "--output-manifest",
            str(output_manifest),
        ]
    )
    run_command(
        [
            sys.executable,
            str(SIONNA_XML_SCRIPT),
            "--frame-id",
            str(frame_id),
            "--input-manifest",
            str(output_manifest),
            "--output-xml",
            str(output_xml),
        ]
    )

    if not output_manifest.exists():
        raise ThreeFrameThreeRxError(f"Missing composed manifest after generation: {output_manifest}")
    if not output_xml.exists():
        raise ThreeFrameThreeRxError(f"Missing frame XML after generation: {output_xml}")

    data = load_json(output_manifest)
    if data.get("frame_id") != frame_id:
        raise ThreeFrameThreeRxError(
            f"{output_manifest} has frame_id={data.get('frame_id')}, expected {frame_id}"
        )
    if data.get("source_sample_index") != source_sample_index:
        raise ThreeFrameThreeRxError(
            f"{output_manifest} has source_sample_index={data.get('source_sample_index')}, "
            f"expected {source_sample_index}"
        )
    return output_xml


def parse_num_paths(output: str) -> int | None:
    match = re.search(r"paths_found\s*:\s*(\d+)", output)
    return int(match.group(1)) if match else None


def error_message_from_result(result: subprocess.CompletedProcess[str]) -> str:
    combined = "\n".join(part for part in [result.stdout, result.stderr] if part)
    for line in combined.splitlines():
        if "ERROR:" in line:
            return line.strip()
    return f"returncode={result.returncode}"


def extract_tau_stats(
    xml: Path,
    *,
    tx_position: tuple[float, float, float],
    rx_position: tuple[float, float, float],
    env: dict[str, str],
    rt_python: Path,
) -> tuple[int | None, float | None, float | None, str | None]:
    # Re-run the same frame through a tiny embedded helper so tau statistics are
    # extracted directly from the Sionna Paths object.
    result = run_command(
        [
            str(rt_python),
            "-c",
            TAU_STATS_SCRIPT,
            str(xml),
            str(CARRIER_FREQUENCY_HZ),
            vec3_arg(tx_position),
            vec3_arg(rx_position),
        ],
        env=env,
        check=False,
    )
    if result.returncode != 0:
        return None, None, None, error_message_from_result(result)

    for line in result.stdout.splitlines():
        if line.startswith("RESULT_JSON "):
            payload = json.loads(line.removeprefix("RESULT_JSON "))
            return payload["num_paths"], payload["tau_min"], payload["tau_max"], None

    return None, None, None, "tau statistics helper did not print RESULT_JSON"


def run_one_row(
    *,
    frame_id: int,
    source_sample_index: int,
    xml: Path,
    tx_id: str,
    tx_position: tuple[float, float, float],
    rx_id: str,
    rx_position: tuple[float, float, float],
    env: dict[str, str],
    rt_python: Path,
) -> dict[str, Any]:
    # Run one XML scene for one TX/RX pair and collect compact path-count plus
    # delay statistics for the summary CSV.
    sanity_result = run_command(
        [
            str(rt_python),
            str(SANITY_SCRIPT),
            "--xml",
            str(xml),
            "--tx",
            vec3_arg(tx_position),
            "--rx",
            vec3_arg(rx_position),
            "--frequency-hz",
            str(CARRIER_FREQUENCY_HZ),
        ],
        env=env,
        check=False,
    )

    sanity_ok = sanity_result.returncode == 0
    num_paths = parse_num_paths(sanity_result.stdout)
    tau_min = None
    tau_max = None
    error_message = ""

    if sanity_ok:
        helper_num_paths, tau_min, tau_max, helper_error = extract_tau_stats(
            xml,
            tx_position=tx_position,
            rx_position=rx_position,
            env=env,
            rt_python=rt_python,
        )
        if helper_error is None:
            num_paths = helper_num_paths
        else:
            sanity_ok = False
            error_message = helper_error
    else:
        error_message = error_message_from_result(sanity_result)

    return {
        "frame_id": frame_id,
        "source_sample_index": source_sample_index,
        "tx_id": tx_id,
        "tx_position": vec3_json(tx_position),
        "rx_id": rx_id,
        "rx_position": vec3_json(rx_position),
        "xml_path": str(xml),
        "num_paths": "" if num_paths is None else num_paths,
        "tau_min": "" if tau_min is None else tau_min,
        "tau_max": "" if tau_max is None else tau_max,
        "sanity_ok": sanity_ok,
        "error_message": error_message,
        "scene_frequency_hz": CARRIER_FREQUENCY_HZ,
    }


def write_summary(rows: list[dict[str, Any]], output_csv: Path) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "frame_id",
        "source_sample_index",
        "tx_id",
        "tx_position",
        "rx_id",
        "rx_position",
        "xml_path",
        "num_paths",
        "tau_min",
        "tau_max",
        "sanity_ok",
        "error_message",
        "scene_frequency_hz",
    ]
    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    static_manifest_path = args.static_manifest.expanduser().resolve()
    composed_root = args.composed_root.expanduser().resolve()
    output_csv = args.output_csv.expanduser().resolve()
    radio_sites_path = args.radio_sites.expanduser().resolve()

    try:
        validate_static_manifest(static_manifest_path)
        tx_id, tx_position, rx_records = load_radio_sites(radio_sites_path)
        rt_python = collabpaper_python_executable()
    except ThreeFrameThreeRxError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    env = runtime_env()
    rows: list[dict[str, Any]] = []

    print("Three-frame x three-RX RT sanity")
    print(f"Static manifest : {static_manifest_path}")
    print(f"Radio sites     : {radio_sites_path}")
    print(f"Carrier freq    : {CARRIER_FREQUENCY_HZ:.6g} Hz")
    print(f"TX              : {tx_id} {vec3_json(tx_position)}")

    try:
        # Reuse the three validated prototype frames, then evaluate each one from
        # the approved receiver sites independently.
        for frame_id, source_sample_index in PROTOTYPE_FRAMES:
            xml = compose_and_emit_frame(
                frame_id,
                source_sample_index=source_sample_index,
                static_manifest_path=static_manifest_path,
                composed_root=composed_root,
            )
            print(f"\nFrame {frame_id} / sample {source_sample_index}")
            for rx_id, rx_position in rx_records:
                row = run_one_row(
                    frame_id=frame_id,
                    source_sample_index=source_sample_index,
                    xml=xml,
                    tx_id=tx_id,
                    tx_position=tx_position,
                    rx_id=rx_id,
                    rx_position=rx_position,
                    env=env,
                    rt_python=rt_python,
                )
                rows.append(row)
                print(
                    f"  {rx_id}: ok={row['sanity_ok']}, num_paths={row['num_paths']}, "
                    f"tau_min={row['tau_min']}, tau_max={row['tau_max']}"
                )
    except ThreeFrameThreeRxError as exc:
        if rows:
            write_summary(rows, output_csv)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if len(rows) != len(PROTOTYPE_FRAMES) * len(rx_records):
        write_summary(rows, output_csv)
        print(
            f"ERROR: Expected {len(PROTOTYPE_FRAMES) * len(rx_records)} rows, got {len(rows)}",
            file=sys.stderr,
        )
        return 1

    write_summary(rows, output_csv)

    failed = [row for row in rows if not row["sanity_ok"]]
    print("\nSummary")
    print("frame_id, source_sample_index, rx_id, num_paths, tau_min, tau_max, sanity_ok")
    for row in rows:
        print(
            f"{row['frame_id']}, {row['source_sample_index']}, {row['rx_id']}, "
            f"{row['num_paths']}, {row['tau_min']}, {row['tau_max']}, {row['sanity_ok']}"
        )
    print(f"CSV written: {output_csv}")

    if failed:
        print("ERROR: One or more sanity runs failed; see CSV error_message column.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
