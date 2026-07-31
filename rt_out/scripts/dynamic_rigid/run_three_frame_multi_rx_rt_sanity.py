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
import math
import re
import subprocess
from pathlib import Path
from typing import Any

import sys

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from dynamic_prototype_config import load_dynamic_prototype_config
from experiment_paths import ExperimentPathError
from rt_material_config import load_rt_runtime_config
from three_frame_paths import (
    actor_frame_manifest_path as planned_actor_frame_manifest_path,
    dynamic_manifest_path as planned_dynamic_manifest_path,
    require_path_within_root,
    resolve_cli_path,
    resolve_three_frame_paths,
)
from runtime_config import (
    PROJECT_ROOT,
    SCRIPT_RUN_SIONNA_RT_SANITY,
    SCRIPT_COMPOSE_FRAME_SCENE,
    SCRIPT_BUILD_FRAME_SIONNA_XML,
    SCRIPT_EXPORT_ACTOR_FRAME_MESHES,
    SCRIPT_EXPORT_DYNAMIC_FRAME_MESHES,
    RuntimeConfigError,
    find_sionna_python,
    runtime_env,
)

ACTOR_EXPORT_SCRIPT = SCRIPT_EXPORT_ACTOR_FRAME_MESHES
DYNAMIC_EXPORT_SCRIPT = SCRIPT_EXPORT_DYNAMIC_FRAME_MESHES
COMPOSE_SCRIPT = SCRIPT_COMPOSE_FRAME_SCENE
SIONNA_XML_SCRIPT = SCRIPT_BUILD_FRAME_SIONNA_XML
SANITY_SCRIPT = SCRIPT_RUN_SIONNA_RT_SANITY

SUPPORTED_ACTOR_ALIGNMENT_POLICIES = ("none", "bounds_center_xy_to_root")
SUPPORTED_ACTOR_Z_ALIGNMENT_POLICIES = ("none", "bounds_min_z_to_floor")

PROTOTYPE_CONFIG: dict[str, Any] = {}
PROTOTYPE_FRAMES: list[tuple[int, int]] = []
EXPECTED_DYNAMIC_COUNT = 0
CARRIER_FREQUENCY_HZ: float | None = None
DYNAMIC_PROTOTYPE_CONFIG_PATH: Path | None = None
RT_RUNTIME_CONFIG_PATH: Path | None = None

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
        "--experiment-root",
        type=Path,
        default=None,
        help="Run root for all generated and default input paths.",
    )
    parser.add_argument(
        "--radio-sites",
        type=Path,
        default=None,
        help="Path to prototype_radio_sites.json",
    )
    parser.add_argument(
        "--static-manifest",
        type=Path,
        default=None,
        help="Static merged manifest path",
    )
    parser.add_argument(
        "--composed-root",
        type=Path,
        default=None,
        help="Composed scene root",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=None,
        help="Output CSV path",
    )
    parser.add_argument(
        "--dynamic-prototype-config",
        type=Path,
        default=None,
        help="Dynamic prototype configuration JSON; loaded after CLI parsing.",
    )
    parser.add_argument(
        "--rt-runtime-config",
        type=Path,
        default=None,
        help="RT material/runtime JSON; loaded after CLI parsing.",
    )
    parser.add_argument(
        "--include-actors",
        action="store_true",
        help=(
            "Export and compose the validated three-frame actor branch. "
            "Default behavior remains actor-free."
        ),
    )
    parser.add_argument(
        "--actor-samples",
        type=Path,
        default=None,
        help="Actor frame samples JSON used when --include-actors is passed.",
    )
    parser.add_argument(
        "--actor-manifest",
        type=Path,
        default=None,
        help="Actor manifest JSON used when --include-actors is passed.",
    )
    parser.add_argument(
        "--actor-alignment-policy",
        choices=SUPPORTED_ACTOR_ALIGNMENT_POLICIES,
        default="bounds_center_xy_to_root",
        help="Actor XY alignment policy passed to export_actor_frame_meshes.py when --include-actors is used.",
    )
    parser.add_argument(
        "--actor-z-alignment-policy",
        choices=SUPPORTED_ACTOR_Z_ALIGNMENT_POLICIES,
        default="bounds_min_z_to_floor",
        help="Actor Z alignment policy passed to export_actor_frame_meshes.py when --include-actors is used.",
    )
    parser.add_argument(
        "--actor-floor-z",
        type=float,
        default=0.1,
        help="Floor z passed to export_actor_frame_meshes.py when actor Z alignment requires it.",
    )
    parser.add_argument(
        "--sionna-python",
        type=Path,
        default=None,
        help=(
            "Optional explicit Python interpreter with Sionna RT/Mitsuba installed. "
            "Defaults to SIONNA_PYTHON, then the legacy COLLABPAPER_PYTHON, then "
            "the current interpreter if it already imports sionna.rt."
        ),
    )
    return parser.parse_args()


def configure_runtime(
    dynamic_prototype_config_path: Path | None,
    rt_runtime_config_path: Path | None,
) -> None:
    global PROTOTYPE_CONFIG, PROTOTYPE_FRAMES, EXPECTED_DYNAMIC_COUNT, CARRIER_FREQUENCY_HZ
    global DYNAMIC_PROTOTYPE_CONFIG_PATH, RT_RUNTIME_CONFIG_PATH
    DYNAMIC_PROTOTYPE_CONFIG_PATH = dynamic_prototype_config_path
    RT_RUNTIME_CONFIG_PATH = rt_runtime_config_path
    PROTOTYPE_CONFIG = load_dynamic_prototype_config(dynamic_prototype_config_path)
    PROTOTYPE_FRAMES = [
        (frame["frame_id"], frame["source_sample_index"])
        for frame in PROTOTYPE_CONFIG["prototype_frames"]
    ]
    EXPECTED_DYNAMIC_COUNT = PROTOTYPE_CONFIG["expected_renderable_visual_count_total"]
    CARRIER_FREQUENCY_HZ = load_rt_runtime_config(rt_runtime_config_path).carrier_frequency_hz


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


def format_command(command: list[str]) -> str:
    return " ".join(str(item) for item in command)


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


def validate_actor_frame_manifest(path: Path, frame_id: int, source_sample_index: int) -> int:
    data = load_json(path)
    if data.get("frame_id") != frame_id:
        raise ThreeFrameThreeRxError(f"{path} has frame_id={data.get('frame_id')}, expected {frame_id}")
    if data.get("source_sample_index") != source_sample_index:
        raise ThreeFrameThreeRxError(
            f"{path} has source_sample_index={data.get('source_sample_index')}, "
            f"expected {source_sample_index}"
        )

    actors = data.get("exported_actors")
    if not isinstance(actors, list):
        raise ThreeFrameThreeRxError(f"{path} must contain exported_actors list")
    if not actors:
        raise ThreeFrameThreeRxError(f"{path} contains no exported actors")

    missing: list[str] = []
    for index, actor in enumerate(actors):
        if not isinstance(actor, dict):
            raise ThreeFrameThreeRxError(f"{path} exported_actors[{index}] is not an object")
        actor_id = actor.get("id", f"exported_actors[{index}]")
        if actor.get("source") != "actor":
            raise ThreeFrameThreeRxError(f"{path} actor {actor_id} must have source == 'actor'")
        if actor.get("baked_world_geometry") is not True:
            raise ThreeFrameThreeRxError(f"{path} actor {actor_id} must have baked_world_geometry == true")
        if actor.get("source_sample_index") != source_sample_index:
            raise ThreeFrameThreeRxError(
                f"{path} actor {actor_id} has source_sample_index={actor.get('source_sample_index')}, "
                f"expected {source_sample_index}"
            )
        material_label = actor.get("material_label")
        if not isinstance(material_label, str) or not material_label.strip():
            raise ThreeFrameThreeRxError(f"{path} actor {actor_id} must have material_label")
        mesh_path = actor.get("exported_mesh_path")
        if not isinstance(mesh_path, str) or not Path(mesh_path).exists():
            missing.append(str(mesh_path))

    if missing:
        raise ThreeFrameThreeRxError(f"{path} references missing actor meshes: {missing[:5]}")
    return len(actors)


def export_actor_frame(
    frame_id: int,
    source_sample_index: int,
    *,
    actor_samples_path: Path,
    actor_manifest_path: Path,
    actor_alignment_policy: str,
    actor_z_alignment_policy: str,
    actor_floor_z: float,
    dynamic_output_root: Path,
) -> tuple[Path, int]:
    actor_export_command = [
        sys.executable,
        str(ACTOR_EXPORT_SCRIPT),
        "--frame-id",
        str(frame_id),
        "--actor-samples",
        str(actor_samples_path),
        "--actor-manifest",
        str(actor_manifest_path),
        "--output-root",
        str(dynamic_output_root),
        "--alignment-policy",
        actor_alignment_policy,
        "--z-alignment-policy",
        actor_z_alignment_policy,
    ]
    if actor_z_alignment_policy == "bounds_min_z_to_floor":
        actor_export_command.extend(["--floor-z", str(actor_floor_z)])

    run_command(actor_export_command)
    manifest_path = planned_actor_frame_manifest_path(dynamic_output_root, frame_id)
    actor_count = validate_actor_frame_manifest(manifest_path, frame_id, source_sample_index)
    return manifest_path, actor_count


def compose_and_emit_frame(
    frame_id: int,
    *,
    source_sample_index: int,
    static_manifest_path: Path,
    composed_root: Path,
    dynamic_manifest: Path,
    actor_frame_manifest_path: Path | None = None,
    expected_actor_count: int = 0,
) -> tuple[Path, int, int]:
    # Reuse the validated composition and XML builders to produce the per-frame
    # scene that will be evaluated from several RX viewpoints.
    output_manifest = composed_manifest_path(frame_id, composed_root)
    output_xml = xml_path(frame_id, composed_root)

    compose_command = [
        sys.executable,
        str(COMPOSE_SCRIPT),
        "--frame-id",
        str(frame_id),
        "--static-manifest",
        str(static_manifest_path),
        "--dynamic-manifest",
        str(dynamic_manifest),
        "--output-manifest",
        str(output_manifest),
    ]
    if DYNAMIC_PROTOTYPE_CONFIG_PATH is not None:
        compose_command.extend(["--dynamic-prototype-config", str(DYNAMIC_PROTOTYPE_CONFIG_PATH)])
    if actor_frame_manifest_path is not None:
        compose_command.extend(["--actor-frame-manifest", str(actor_frame_manifest_path)])
    run_command(compose_command)
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
        + (["--dynamic-prototype-config", str(DYNAMIC_PROTOTYPE_CONFIG_PATH)] if DYNAMIC_PROTOTYPE_CONFIG_PATH is not None else [])
        + (["--rt-material-config", str(RT_RUNTIME_CONFIG_PATH)] if RT_RUNTIME_CONFIG_PATH is not None else [])
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
    entries = data.get("entries")
    if not isinstance(entries, list) or len(entries) != data.get("total_count"):
        raise ThreeFrameThreeRxError(f"{output_manifest} has invalid entries/total_count")
    dynamic_entries = [entry for entry in entries if entry.get("source") == "dynamic"]
    if len(dynamic_entries) != EXPECTED_DYNAMIC_COUNT or data.get("dynamic_count") != EXPECTED_DYNAMIC_COUNT:
        raise ThreeFrameThreeRxError(
            f"{output_manifest} must contain exactly {EXPECTED_DYNAMIC_COUNT} dynamic entries"
        )
    actor_entries = [entry for entry in entries if entry.get("source") == "actor"]
    manifest_actor_count = data.get("actor_count", 0)
    if manifest_actor_count != len(actor_entries):
        raise ThreeFrameThreeRxError(
            f"{output_manifest} actor_count={manifest_actor_count}, "
            f"but found {len(actor_entries)} actor entries"
        )
    if len(actor_entries) != expected_actor_count:
        raise ThreeFrameThreeRxError(
            f"{output_manifest} contains {len(actor_entries)} actor entries, "
            f"expected {expected_actor_count}"
        )
    return output_xml, len(entries), len(actor_entries)


def parse_num_paths(output: str) -> int | None:
    match = re.search(r"paths_found\s*:\s*(\d+)", output)
    return int(match.group(1)) if match else None


def parse_int_output_field(output: str, field_name: str) -> int | None:
    match = re.search(rf"{re.escape(field_name)}\s*:\s*(\d+)", output)
    return int(match.group(1)) if match else None


def tail_lines(text: str, limit: int = 20) -> str:
    lines = text.splitlines()
    if len(lines) > limit:
        lines = lines[-limit:]
    return "\n".join(lines)


def error_message_from_result(result: subprocess.CompletedProcess[str]) -> str:
    combined = "\n".join(part for part in [result.stdout, result.stderr] if part)
    for line in combined.splitlines():
        if "ERROR:" in line:
            return line.strip()

    parts = [f"returncode={result.returncode}"]
    command = getattr(result, "args", None)
    if command:
        if isinstance(command, (list, tuple)):
            parts.append(f"command={format_command([str(item) for item in command])}")
        else:
            parts.append(f"command={command}")
    if result.stdout:
        parts.append("stdout_tail:\n" + tail_lines(result.stdout))
    if result.stderr:
        parts.append("stderr_tail:\n" + tail_lines(result.stderr))
    return "\n".join(parts)


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
    include_actors: bool,
    actor_count: int,
    actor_manifest_path: Path,
    actor_alignment_policy: str,
    actor_z_alignment_policy: str,
    actor_floor_z: float,
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
    scene_objects = parse_int_output_field(sanity_result.stdout, "scene_objects")
    radio_materials = parse_int_output_field(sanity_result.stdout, "radio_materials")
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
        "scene_objects": "" if scene_objects is None else scene_objects,
        "radio_materials": "" if radio_materials is None else radio_materials,
        "include_actors": include_actors,
        "actor_count": actor_count,
        "actor_manifest": str(actor_manifest_path) if include_actors else "",
        "actor_alignment_policy": actor_alignment_policy if include_actors else "",
        "actor_z_alignment_policy": actor_z_alignment_policy if include_actors else "",
        "actor_floor_z": actor_floor_z if include_actors else "",
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
        "scene_objects",
        "radio_materials",
        "include_actors",
        "actor_count",
        "actor_manifest",
        "actor_alignment_policy",
        "actor_z_alignment_policy",
        "actor_floor_z",
    ]
    with output_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    try:
        path_plan, legacy_default = resolve_three_frame_paths(args.experiment_root)
        experiment_root = path_plan.experiment_root
        dynamic_prototype_config_path = (
            resolve_cli_path(args.dynamic_prototype_config)
            if args.dynamic_prototype_config is not None
            else (path_plan.dynamic_prototype_config if args.experiment_root is not None else None)
        )
        rt_runtime_config_path = (
            resolve_cli_path(args.rt_runtime_config)
            if args.rt_runtime_config is not None
            else (path_plan.rt_runtime_config if args.experiment_root is not None else None)
        )
        for label, path in (
            ("Dynamic prototype config", dynamic_prototype_config_path),
            ("RT runtime config", rt_runtime_config_path),
        ):
            if args.experiment_root is not None and (path is None or not path.is_file()):
                raise ExperimentPathError(f"{label} does not exist or is not a file: {path}")
        static_manifest_path = (
            resolve_cli_path(args.static_manifest)
            if args.static_manifest is not None
            else path_plan.static_manifest
        )
        composed_root = (
            resolve_cli_path(args.composed_root)
            if args.composed_root is not None
            else path_plan.composed_root
        )
        output_csv = (
            resolve_cli_path(args.output_csv)
            if args.output_csv is not None
            else composed_root / "three_frame_three_rx_rt_summary.csv"
        )
        radio_sites_path = (
            resolve_cli_path(args.radio_sites)
            if args.radio_sites is not None
            else path_plan.radio_sites
        )
        actor_samples_path = (
            resolve_cli_path(args.actor_samples)
            if args.actor_samples is not None
            else path_plan.actor_samples
        )
        actor_manifest_path = (
            resolve_cli_path(args.actor_manifest)
            if args.actor_manifest is not None
            else path_plan.actor_manifest
        )
        if args.experiment_root is not None:
            composed_root = require_path_within_root(composed_root, experiment_root, "--composed-root")
            output_csv = require_path_within_root(output_csv, experiment_root, "--output-csv")
    except ExperimentPathError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    try:
        configure_runtime(dynamic_prototype_config_path, rt_runtime_config_path)
    except (RuntimeError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if legacy_default:
        print("WARNING: using legacy Factory run defaults; pass --experiment-root for a run-local flow.", file=sys.stderr)

    try:
        validate_static_manifest(static_manifest_path)
        tx_id, tx_position, rx_records = load_radio_sites(radio_sites_path)
        rt_python = find_sionna_python(args.sionna_python)
        if args.include_actors:
            if not actor_manifest_path.exists():
                raise ThreeFrameThreeRxError(f"Actor manifest does not exist: {actor_manifest_path}")
            if not actor_samples_path.exists():
                raise ThreeFrameThreeRxError(f"Actor samples do not exist: {actor_samples_path}")
            if args.actor_z_alignment_policy == "bounds_min_z_to_floor" and not math.isfinite(args.actor_floor_z):
                raise ThreeFrameThreeRxError("--actor-floor-z must be finite")
    except RuntimeConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
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
    print(f"Include actors  : {args.include_actors}")
    if args.include_actors:
        print(f"Actor manifest  : {actor_manifest_path}")
        print(f"Actor samples   : {actor_samples_path}")
        print(f"Actor alignment : {args.actor_alignment_policy}")
        print(f"Actor z align   : {args.actor_z_alignment_policy}")
        print(f"Actor floor z   : {args.actor_floor_z}")

    try:
        # Reuse the three validated prototype frames, then evaluate each one from
        # the approved receiver sites independently.
        for frame_id, source_sample_index in PROTOTYPE_FRAMES:
            dynamic_manifest = planned_dynamic_manifest_path(path_plan.dynamic_root, frame_id)
            dynamic_command = [
                sys.executable,
                str(DYNAMIC_EXPORT_SCRIPT),
                "--frame-id",
                str(frame_id),
                "--source-sample-index",
                str(source_sample_index),
                "--output-root",
                str(path_plan.dynamic_root),
            ]
            if DYNAMIC_PROTOTYPE_CONFIG_PATH is not None:
                dynamic_command.extend([
                    "--dynamic-prototype-config", str(DYNAMIC_PROTOTYPE_CONFIG_PATH)
                ])
            run_command(dynamic_command)
            if not dynamic_manifest.is_file():
                raise ThreeFrameThreeRxError(
                    f"Missing dynamic manifest after export: {dynamic_manifest}"
                )
            frame_actor_manifest_path = None
            expected_actor_count = 0
            if args.include_actors:
                frame_actor_manifest_path, expected_actor_count = export_actor_frame(
                    frame_id,
                    source_sample_index,
                    actor_samples_path=actor_samples_path,
                    actor_manifest_path=actor_manifest_path,
                    actor_alignment_policy=args.actor_alignment_policy,
                    actor_z_alignment_policy=args.actor_z_alignment_policy,
                    actor_floor_z=args.actor_floor_z,
                    dynamic_output_root=path_plan.dynamic_root,
                )

            xml, scene_object_count, actor_count = compose_and_emit_frame(
                frame_id,
                source_sample_index=source_sample_index,
                static_manifest_path=static_manifest_path,
                composed_root=composed_root,
                dynamic_manifest=dynamic_manifest,
                actor_frame_manifest_path=frame_actor_manifest_path,
                expected_actor_count=expected_actor_count,
            )
            print(
                f"\nFrame {frame_id} / sample {source_sample_index} "
                f"(scene_objects={scene_object_count}, actor_count={actor_count})"
            )
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
                    include_actors=args.include_actors,
                    actor_count=actor_count,
                    actor_manifest_path=actor_manifest_path,
                    actor_alignment_policy=args.actor_alignment_policy,
                    actor_z_alignment_policy=args.actor_z_alignment_policy,
                    actor_floor_z=args.actor_floor_z,
                )
                rows.append(row)
                print(
                    f"  {rx_id}: ok={row['sanity_ok']}, scene_objects={row['scene_objects']}, "
                    f"num_paths={row['num_paths']}, "
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
    print(
        "frame_id, source_sample_index, rx_id, scene_objects, actor_count, "
        "num_paths, tau_min, tau_max, sanity_ok"
    )
    for row in rows:
        print(
            f"{row['frame_id']}, {row['source_sample_index']}, {row['rx_id']}, "
            f"{row['scene_objects']}, {row['actor_count']}, {row['num_paths']}, "
            f"{row['tau_min']}, {row['tau_max']}, {row['sanity_ok']}"
        )
    print(f"CSV written: {output_csv}")

    if failed:
        print("ERROR: One or more sanity runs failed; see CSV error_message column.", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
