#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from dynamic_prototype_config import load_dynamic_prototype_config
from rt_material_config import load_rt_runtime_config


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = PROJECT_ROOT / "rt_out" / "scripts"

DYNAMIC_EXPORT_SCRIPT = SCRIPT_DIR / "32_export_dynamic_frame_meshes.py"
COMPOSE_SCRIPT = SCRIPT_DIR / "33_compose_prototype_frame_scene.py"
SIONNA_XML_SCRIPT = SCRIPT_DIR / "34_build_prototype_frame_sionna_xml.py"
SANITY_SCRIPT = SCRIPT_DIR / "24_run_sionna_rt_sanity.py"

DEFAULT_STATIC_MANIFEST_PATH = (
    PROJECT_ROOT / "rt_out" / "static_scene" / "export" / "merged_static_manifest.json"
)
DEFAULT_COMPOSED_SCENE_ROOT = PROJECT_ROOT / "rt_out" / "composed_scene"

PROTOTYPE_CONFIG = load_dynamic_prototype_config()
PROTOTYPE_FRAMES = [
    (frame["frame_id"], frame["source_sample_index"])
    for frame in PROTOTYPE_CONFIG["prototype_frames"]
]
EXPECTED_DYNAMIC_COUNT = PROTOTYPE_CONFIG["expected_renderable_visual_count_total"]
CARRIER_FREQUENCY_HZ = load_rt_runtime_config().carrier_frequency_hz

TAU_STATS_SCRIPT = r"""
import json
import sys
from pathlib import Path

import numpy as np
import sionna.rt  # noqa: F401
import mitsuba as mi
from sionna.rt import PlanarArray, Receiver, Transmitter, PathSolver, load_scene


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
tx = Transmitter(name="tx_static_sanity", position=mi.Point3f(-0.3, -3.8, 1.3))
rx = Receiver(name="rx_static_sanity", position=mi.Point3f(2.5, -3.1, 1.3))
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


class ThreeFrameRtError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the three-frame prototype RT sanity flow."
    )
    parser.add_argument(
        "--static-manifest",
        type=Path,
        default=DEFAULT_STATIC_MANIFEST_PATH,
        help="Static merged manifest to compose with each prototype frame.",
    )
    parser.add_argument(
        "--composed-root",
        type=Path,
        default=DEFAULT_COMPOSED_SCENE_ROOT,
        help="Root directory for composed manifests, XML files, and summary CSV.",
    )
    parser.add_argument(
        "--output-suffix",
        default="",
        help="Optional suffix added before .json/.xml/.csv.",
    )
    parser.add_argument(
        "--summary-csv",
        type=Path,
        default=None,
        help="Optional explicit output CSV path.",
    )
    return parser.parse_args()


def collabpaper_python_executable() -> Path:
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

    raise ThreeFrameRtError(
        "Could not find collabpaper Python. Set COLLABPAPER_PYTHON or install "
        f"the environment in a standard conda location. Checked: {[str(c) for c in candidates]}"
    )


def frame_dir_name(frame_id: int) -> str:
    return f"frame_{frame_id:03d}"


def dynamic_manifest_path(frame_id: int) -> Path:
    return (
        PROJECT_ROOT
        / "rt_out"
        / "dynamic_scene"
        / frame_dir_name(frame_id)
        / f"dynamic_frame_{frame_id:03d}_manifest.json"
    )


def suffix_filename(base: str, suffix: str, ext: str) -> str:
    return f"{base}{suffix}{ext}" if suffix else f"{base}{ext}"


def composed_manifest_path(frame_id: int, composed_root: Path, output_suffix: str) -> Path:
    return (
        composed_root
        / frame_dir_name(frame_id)
        / suffix_filename(f"composed_frame_{frame_id:03d}_manifest", output_suffix, ".json")
    )


def xml_path(frame_id: int, composed_root: Path, output_suffix: str) -> Path:
    return (
        composed_root
        / frame_dir_name(frame_id)
        / suffix_filename(f"frame_{frame_id:03d}_sionna", output_suffix, ".xml")
    )


def runtime_env() -> dict[str, str]:
    env = os.environ.copy()
    mpl_config = Path("/tmp/matplotlib-collabpaper")
    drjit_cache = Path("/tmp/drjit-collabpaper")
    mpl_config.mkdir(parents=True, exist_ok=True)
    drjit_cache.mkdir(parents=True, exist_ok=True)
    env["MPLCONFIGDIR"] = str(mpl_config)
    env["DRJIT_CACHE_DIR"] = str(drjit_cache)
    return env


def format_command(command: list[str]) -> str:
    return " ".join(str(item) for item in command)


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
        raise ThreeFrameRtError(
            f"Command failed with exit code {result.returncode}: {format_command(command)}"
        )
    return result


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise ThreeFrameRtError(f"Missing JSON file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ThreeFrameRtError(f"Invalid JSON in {path}: {exc}") from exc


def validate_dynamic_manifest(path: Path, frame_id: int, source_sample_index: int) -> None:
    data = load_json(path)
    if data.get("frame_id") != frame_id:
        raise ThreeFrameRtError(f"{path} has frame_id={data.get('frame_id')}, expected {frame_id}")
    if data.get("source_sample_index") != source_sample_index:
        raise ThreeFrameRtError(
            f"{path} has source_sample_index={data.get('source_sample_index')}, "
            f"expected {source_sample_index}"
        )
    visuals = data.get("exported_visuals")
    if not isinstance(visuals, list) or len(visuals) != EXPECTED_DYNAMIC_COUNT:
        raise ThreeFrameRtError(
            f"{path} must contain exactly {EXPECTED_DYNAMIC_COUNT} exported visuals"
        )
    mesh_paths = [Path(item.get("exported_mesh_path", "")) for item in visuals]
    missing = [str(item) for item in mesh_paths if not item.exists()]
    if missing:
        raise ThreeFrameRtError(f"{path} references missing dynamic meshes: {missing[:5]}")


def validate_composed_manifest(path: Path, frame_id: int, source_sample_index: int) -> int:
    data = load_json(path)
    if data.get("frame_id") != frame_id:
        raise ThreeFrameRtError(f"{path} has frame_id={data.get('frame_id')}, expected {frame_id}")
    if data.get("source_sample_index") != source_sample_index:
        raise ThreeFrameRtError(
            f"{path} has source_sample_index={data.get('source_sample_index')}, "
            f"expected {source_sample_index}"
        )
    entries = data.get("entries")
    if not isinstance(entries, list) or len(entries) != data.get("total_count"):
        raise ThreeFrameRtError(f"{path} has invalid entries/total_count")
    dynamic_entries = [entry for entry in entries if entry.get("source") == "dynamic"]
    if len(dynamic_entries) != EXPECTED_DYNAMIC_COUNT or data.get("dynamic_count") != EXPECTED_DYNAMIC_COUNT:
        raise ThreeFrameRtError(
            f"{path} must contain exactly {EXPECTED_DYNAMIC_COUNT} dynamic entries"
        )
    missing = [
        str(entry.get("mesh_path"))
        for entry in entries
        if not isinstance(entry.get("mesh_path"), str) or not Path(entry["mesh_path"]).exists()
    ]
    if missing:
        raise ThreeFrameRtError(f"{path} references missing composed mesh paths: {missing[:5]}")
    return len(entries)


def validate_xml(path: Path, expected_shapes: int) -> None:
    if not path.exists():
        raise ThreeFrameRtError(f"Missing XML: {path}")
    root = ET.parse(path).getroot()
    shapes = root.findall("shape")
    if len(shapes) != expected_shapes:
        raise ThreeFrameRtError(
            f"{path} has {len(shapes)} shapes, expected {expected_shapes}"
        )
    missing = []
    for shape in shapes:
        filename = shape.find("string")
        if filename is None or filename.attrib.get("name") != "filename":
            raise ThreeFrameRtError(f"{path} contains a shape without filename string")
        mesh_path = path.parent / filename.attrib["value"]
        if not mesh_path.exists():
            missing.append(str(mesh_path))
    if missing:
        raise ThreeFrameRtError(f"{path} references missing XML mesh paths: {missing[:5]}")


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
    path: Path,
    env: dict[str, str],
    rt_python: Path,
) -> tuple[int | None, float | None, float | None, str | None]:
    result = run_command(
        [str(rt_python), "-c", TAU_STATS_SCRIPT, str(path), str(CARRIER_FREQUENCY_HZ)],
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


def run_frame(
    frame_id: int,
    source_sample_index: int,
    env: dict[str, str],
    rt_python: Path,
    *,
    static_manifest_path: Path,
    composed_root: Path,
    output_suffix: str,
) -> dict[str, Any]:
    print(f"\n=== Frame {frame_id} / sample {source_sample_index} ===")
    output_manifest = composed_manifest_path(frame_id, composed_root, output_suffix)
    output_xml = xml_path(frame_id, composed_root, output_suffix)

    run_command(
        [
            sys.executable,
            str(DYNAMIC_EXPORT_SCRIPT),
            "--frame-id",
            str(frame_id),
            "--source-sample-index",
            str(source_sample_index),
        ]
    )
    validate_dynamic_manifest(dynamic_manifest_path(frame_id), frame_id, source_sample_index)

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
    expected_shapes = validate_composed_manifest(
        output_manifest,
        frame_id,
        source_sample_index,
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
    validate_xml(output_xml, expected_shapes=expected_shapes)

    sanity_result = run_command(
        [
            str(rt_python),
            str(SANITY_SCRIPT),
            "--xml",
            str(output_xml),
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
            output_xml,
            env,
            rt_python,
        )
        if helper_error is None:
            num_paths = helper_num_paths
        else:
            sanity_ok = False
            error_message = helper_error
    else:
        error_message = error_message_from_result(sanity_result)

    print(
        "RT sanity: "
        f"ok={sanity_ok}, num_paths={num_paths}, tau_min={tau_min}, tau_max={tau_max}"
    )
    if error_message:
        print(f"RT sanity error: {error_message}")

    return {
        "frame_id": frame_id,
        "source_sample_index": source_sample_index,
        "xml_path": str(output_xml),
        "num_paths": "" if num_paths is None else num_paths,
        "tau_min": "" if tau_min is None else tau_min,
        "tau_max": "" if tau_max is None else tau_max,
        "sanity_ok": sanity_ok,
        "error_message": error_message,
    }


def write_summary(rows: list[dict[str, Any]], summary_csv_path: Path) -> None:
    summary_csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "frame_id",
        "source_sample_index",
        "xml_path",
        "num_paths",
        "tau_min",
        "tau_max",
        "sanity_ok",
        "error_message",
    ]
    with summary_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    try:
        rt_python = collabpaper_python_executable()
    except ThreeFrameRtError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    static_manifest_path = args.static_manifest.expanduser().resolve()
    if not static_manifest_path.exists():
        print(f"ERROR: Static manifest does not exist: {static_manifest_path}", file=sys.stderr)
        return 1

    output_suffix = str(args.output_suffix or "")
    if any(sep in output_suffix for sep in ("/", "\\")):
        print("ERROR: --output-suffix must not contain path separators", file=sys.stderr)
        return 1

    composed_root = args.composed_root.expanduser().resolve()
    summary_csv_path = (
        args.summary_csv.expanduser().resolve()
        if args.summary_csv is not None
        else composed_root / suffix_filename("three_frame_rt_summary", output_suffix, ".csv")
    )

    env = runtime_env()
    print(f"Prototype three-frame RT sanity @ {CARRIER_FREQUENCY_HZ:.6g} Hz")
    print(f"RT python: {rt_python}")
    print(f"Static manifest: {static_manifest_path}")
    print(f"Composed root: {composed_root}")
    rows: list[dict[str, Any]] = []
    try:
        for frame_id, source_sample_index in PROTOTYPE_FRAMES:
            rows.append(
                run_frame(
                    frame_id,
                    source_sample_index,
                    env,
                    rt_python,
                    static_manifest_path=static_manifest_path,
                    composed_root=composed_root,
                    output_suffix=output_suffix,
                )
            )
    except ThreeFrameRtError as exc:
        if rows:
            write_summary(rows, summary_csv_path)
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if len(rows) != 3:
        write_summary(rows, summary_csv_path)
        print(f"ERROR: Expected {len(PROTOTYPE_FRAMES)} summary rows, wrote {len(rows)}", file=sys.stderr)
        return 1

    write_summary(rows, summary_csv_path)

    print("\nThree-frame RT sanity summary")
    print("frame_id, source_sample_index, num_paths, tau_min, tau_max, sanity_ok")
    for row in rows:
        print(
            f"{row['frame_id']}, {row['source_sample_index']}, {row['num_paths']}, "
            f"{row['tau_min']}, {row['tau_max']}, {row['sanity_ok']}"
        )
    print(f"CSV written: {summary_csv_path}")

    failed = [row for row in rows if not row["sanity_ok"]]
    if failed:
        print("ERROR: One or more sanity runs failed; see CSV error_message column.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
