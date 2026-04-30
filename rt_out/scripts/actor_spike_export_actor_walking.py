#!/usr/bin/env python3
"""Offline feasibility spike for true animated export of actor_walking.

This script is intentionally isolated from the validated Panda/UR5 pipeline.
It parses the Gazebo actor definition from the world, inspects the source DAE
animation/skeleton data, samples a tiny set of actor times, and asks Blender
to export posed meshes plus per-frame bone transforms into rt_out/actor_spike.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORLD_PATH = PROJECT_ROOT / "myworld_rt.sdf"
MODELS_ROOT = PROJECT_ROOT / "models"
OUTPUT_ROOT = PROJECT_ROOT / "rt_out" / "actor_spike" / "actor_walking"
HELPER_SCRIPT = PROJECT_ROOT / "rt_out" / "scripts" / "actor_spike_blender_sample_actor.py"
ACTOR_NAME = "actor_walking"
SAMPLE_TIMES_SECONDS = [1.99, 3.99, 5.08]
DAE_NS = {"c": "http://www.collada.org/2005/11/COLLADASchema"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build an isolated actor_walking export feasibility spike."
    )
    parser.add_argument(
        "--world",
        type=Path,
        default=WORLD_PATH,
        help="World SDF to read actor definitions from.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=OUTPUT_ROOT,
        help="Output directory for spike artifacts.",
    )
    return parser.parse_args()


def parse_pose6(text: str) -> list[float]:
    # Actor waypoints and poses in SDF use a simple pose6 string convention.
    values = [float(part) for part in text.split()]
    if len(values) != 6:
        raise ValueError(f"Expected pose6 string with 6 values, got {text!r}")
    return values


def pose6_to_matrix(pose6: list[float]) -> list[list[float]]:
    # Convert the sampled actor root pose into a homogeneous transform so the
    # spike artifacts carry an explicit world-space reference.
    x, y, z, roll, pitch, yaw = pose6
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)

    rot = [
        [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
        [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
        [-sp, cp * sr, cp * cr],
    ]
    return [
        [rot[0][0], rot[0][1], rot[0][2], x],
        [rot[1][0], rot[1][1], rot[1][2], y],
        [rot[2][0], rot[2][1], rot[2][2], z],
        [0.0, 0.0, 0.0, 1.0],
    ]


def find_blender() -> Path:
    # This feasibility spike uses Blender offline, independent of the validated
    # Panda/UR5 rigid path, so search the usual local install locations here.
    candidates: list[Path] = []
    if os.environ.get("BLENDER"):
        candidates.append(Path(os.environ["BLENDER"]))
    if blender_env := shutil.which("blender"):
        candidates.append(Path(blender_env))
    if blender_env := Path.cwd().joinpath("blender"):
        candidates.append(blender_env)
    if blender_env := PROJECT_ROOT.joinpath("tools", "blender", "blender"):
        candidates.append(blender_env)
    if blender_env := Path.home() / "Documents" / "blender-4.5.8-linux-x64" / "blender":
        candidates.append(blender_env)

    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "Blender executable not found. Set BLENDER or install Blender in a standard location."
    )


def resolve_model_uri(uri: str) -> Path:
    # Actor assets in the world file use model:// URIs, so resolve them against
    # the repository's models/ tree before handing anything to Blender.
    prefix = "model://"
    if not uri.startswith(prefix):
        raise ValueError(f"Unsupported actor asset URI {uri!r}")
    relative = uri[len(prefix) :]
    model_name, _, suffix = relative.partition("/")
    if not model_name or not suffix:
        raise ValueError(f"Malformed model URI {uri!r}")

    matches = sorted(MODELS_ROOT.glob(f"**/{model_name}/{suffix}"))
    if not matches:
        raise FileNotFoundError(f"Could not resolve {uri!r} under {MODELS_ROOT}")
    if len(matches) > 1:
        raise RuntimeError(f"Ambiguous actor asset URI {uri!r}: {matches}")
    return matches[0].resolve()


def load_actor_definition(world_path: Path, actor_name: str) -> dict[str, Any]:
    # Read the Gazebo actor definition directly from the world file so the spike
    # can compare script waypoints, skin assets, and animation clip metadata.
    tree = ET.parse(world_path)
    root = tree.getroot()
    world = root.find("world")
    if world is None:
        raise RuntimeError(f"{world_path} does not contain a <world> element")

    actor_elem = None
    for candidate in world.findall("actor"):
        if candidate.get("name") == actor_name:
            actor_elem = candidate
            break
    if actor_elem is None:
        raise RuntimeError(f"Actor {actor_name!r} not found in {world_path}")

    skin_elem = actor_elem.find("skin")
    anim_elem = actor_elem.find("animation")
    script_elem = actor_elem.find("script")
    traj_elem = script_elem.find("trajectory") if script_elem is not None else None
    if skin_elem is None or anim_elem is None or script_elem is None or traj_elem is None:
        raise RuntimeError(f"Actor {actor_name!r} is missing skin/animation/script data")

    waypoints = []
    for waypoint_elem in traj_elem.findall("waypoint"):
        time_text = waypoint_elem.findtext("time")
        pose_text = waypoint_elem.findtext("pose")
        if time_text is None or pose_text is None:
            raise RuntimeError(f"Malformed waypoint in actor {actor_name!r}")
        waypoints.append(
            {
                "time": float(time_text),
                "pose6": parse_pose6(pose_text),
            }
        )

    return {
        "actor_name": actor_name,
        "world_path": str(world_path.resolve()),
        "skin_uri": skin_elem.findtext("filename", "").strip(),
        "skin_scale": float(skin_elem.findtext("scale", "1.0")),
        "animation_name": anim_elem.get("name"),
        "animation_uri": anim_elem.findtext("filename", "").strip(),
        "animation_interpolate_x": anim_elem.findtext("interpolate_x", "false").strip().lower()
        == "true",
        "actor_pose6": parse_pose6(actor_elem.findtext("pose", "0 0 0 0 0 0")),
        "script": {
            "loop": script_elem.findtext("loop", "false").strip().lower() == "true",
            "delay_start": float(script_elem.findtext("delay_start", "0")),
            "auto_start": script_elem.findtext("auto_start", "false").strip().lower()
            == "true",
            "trajectory_id": traj_elem.get("id"),
            "trajectory_type": traj_elem.get("type"),
            "trajectory_tension": traj_elem.get("tension"),
            "waypoint_count": len(waypoints),
            "waypoints": waypoints,
        },
    }


def inspect_dae(dae_path: Path) -> dict[str, Any]:
    # Inspect the source DAE offline to verify that the actor really carries a
    # skeleton and animation data before asking Blender to export posed meshes.
    root = ET.parse(dae_path).getroot()

    joint_nodes = root.findall(".//c:node[@type='JOINT']", DAE_NS)
    joint_names = [node.get("name") or node.get("id") for node in joint_nodes]

    animation_inputs: list[list[float]] = []
    keyframe_counts: list[int] = []
    animation_channels = root.findall(".//c:library_animations/c:animation", DAE_NS)
    for anim in animation_channels:
        anim_id = anim.get("id")
        src = anim.find(f"c:source[@id='{anim_id}-input']", DAE_NS) if anim_id else None
        if src is None:
            src = anim.find("c:source", DAE_NS)
        float_array = src.find("c:float_array", DAE_NS) if src is not None else None
        if float_array is None or not float_array.text:
            continue
        values = [float(part) for part in float_array.text.split()]
        animation_inputs.append(values)
        keyframe_counts.append(len(values))

    if not animation_inputs:
        raise RuntimeError(f"No animation channels found in {dae_path}")

    controller_count = len(root.findall(".//c:library_controllers/c:controller", DAE_NS))
    vertex_weights = root.find(".//c:vertex_weights", DAE_NS)
    skeleton_refs = [elem.text.strip() for elem in root.findall(".//c:skeleton", DAE_NS) if elem.text]

    return {
        "dae_path": str(dae_path),
        "animation_channel_count": len(animation_channels),
        "joint_count": len(joint_names),
        "joint_names": joint_names,
        "clip_time_min_seconds": min(min(values) for values in animation_inputs),
        "clip_time_max_seconds": max(max(values) for values in animation_inputs),
        "keyframe_count_min": min(keyframe_counts),
        "keyframe_count_max": max(keyframe_counts),
        "controller_count": controller_count,
        "vertex_weight_count": int(vertex_weights.get("count")) if vertex_weights is not None else None,
        "skeleton_roots": skeleton_refs,
    }


def build_samples(actor_data: dict[str, Any]) -> list[dict[str, Any]]:
    # This spike samples a few exact actor script waypoints. It proves offline
    # posed export works, but does not solve Gazebo-runtime phase coupling.
    waypoints = actor_data["script"]["waypoints"]
    samples: list[dict[str, Any]] = []
    for sample_id, sample_time in enumerate(SAMPLE_TIMES_SECONDS):
        waypoint = next(
            (item for item in waypoints if math.isclose(item["time"], sample_time, abs_tol=1e-9)),
            None,
        )
        if waypoint is None:
            raise RuntimeError(f"Sample time {sample_time} is not an exact actor waypoint")
        root_pose6 = waypoint["pose6"]
        samples.append(
            {
                "sample_id": sample_id,
                "actor_time_seconds": sample_time,
                "animation_time_seconds": sample_time,
                "waypoint_exact_match": True,
                "root_pose6": root_pose6,
                "root_to_world": pose6_to_matrix(root_pose6),
                "note": (
                    "This spike samples the first animation clip directly at the same seconds as the "
                    "selected actor script waypoints. Exact Gazebo actor phase coupling beyond that "
                    "assumption is not observable from the current runtime topics."
                ),
            }
        )
    return samples


def ensure_clean_dirs(output_root: Path) -> dict[str, Path]:
    # Create a dedicated output tree for this isolated spike so it never touches
    # the validated rigid dynamic export directories.
    metadata_dir = output_root / "metadata"
    posed_mesh_dir = output_root / "posed_meshes"
    bone_dir = output_root / "bone_transforms"
    output_root.mkdir(parents=True, exist_ok=True)
    metadata_dir.mkdir(exist_ok=True)
    posed_mesh_dir.mkdir(exist_ok=True)
    bone_dir.mkdir(exist_ok=True)
    return {
        "metadata": metadata_dir,
        "posed_meshes": posed_mesh_dir,
        "bone_transforms": bone_dir,
    }


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def run_blender_export(blender_path: Path, spec_path: Path) -> None:
    # Hand the prepared sampling spec to the Blender helper, which performs the
    # actual skinned mesh evaluation and per-bone export.
    command = [
        str(blender_path),
        "--background",
        "--python",
        str(HELPER_SCRIPT),
        "--",
        "--spec",
        str(spec_path),
    ]
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(result.stdout.rstrip())
    if result.returncode != 0:
        if result.stderr:
            print(result.stderr.rstrip())
        raise RuntimeError(f"Blender actor export failed with exit code {result.returncode}")


def build_report(
    output_root: Path,
    actor_data: dict[str, Any],
    dae_data: dict[str, Any],
    samples: list[dict[str, Any]],
    blender_summary: dict[str, Any],
) -> str:
    lines = [
        "# actor_walking feasibility spike",
        "",
        "## What was sampled",
        f"- World file: `{actor_data['world_path']}`",
        f"- Actor: `{actor_data['actor_name']}`",
        f"- Skin asset: `{actor_data['skin_uri']}`",
        f"- Animation asset: `{actor_data['animation_uri']}`",
        f"- Skin scale: `{actor_data['skin_scale']}`",
        f"- Selected sample times (s): {', '.join(f'{item['actor_time_seconds']:.2f}' for item in samples)}",
        "",
        "## DAE inspection",
        f"- Animation channels: {dae_data['animation_channel_count']}",
        f"- Joint count: {dae_data['joint_count']}",
        f"- Clip time range: {dae_data['clip_time_min_seconds']:.6f}s to {dae_data['clip_time_max_seconds']:.6f}s",
        f"- Controller count: {dae_data['controller_count']}",
        f"- Vertex weight count: {dae_data['vertex_weight_count']}",
        "",
        "## Blender export result",
        f"- Armature: `{blender_summary['armature_name']}`",
        f"- Mesh: `{blender_summary['mesh_name']}`",
        f"- Exported posed meshes: {len(blender_summary['exports'])}",
        "",
        "## Caveat",
        (
            "This spike proves that the current actor assets are sufficient for offline skeleton "
            "evaluation and posed mesh export. It does not yet prove that the sampled animation "
            "phase exactly matches Gazebo runtime actor phase over looped playback, because the "
            "current Gazebo setup does not expose actor animation state on a clean topic."
        ),
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    output_root = args.output_root.resolve()
    dirs = ensure_clean_dirs(output_root)

    # Keep the spike self-contained: parse the actor from the world, inspect the
    # source animation, then ask Blender for a few posed mesh samples.
    actor_data = load_actor_definition(args.world.resolve(), ACTOR_NAME)
    actor_data["skin_path_resolved"] = str(resolve_model_uri(actor_data["skin_uri"]))
    actor_data["animation_path_resolved"] = str(resolve_model_uri(actor_data["animation_uri"]))
    dae_data = inspect_dae(Path(actor_data["animation_path_resolved"]))
    samples = build_samples(actor_data)

    metadata_path = dirs["metadata"] / "actor_walking_metadata.json"
    samples_path = dirs["metadata"] / "sampled_frames.json"
    spec_path = dirs["metadata"] / "blender_sampling_spec.json"

    write_json(metadata_path, {"actor": actor_data, "dae": dae_data})
    write_json(samples_path, {"actor_name": ACTOR_NAME, "samples": samples})
    write_json(
        spec_path,
        {
            "actor_name": ACTOR_NAME,
            "animation_path_resolved": actor_data["animation_path_resolved"],
            "skin_scale": actor_data["skin_scale"],
            "samples": samples,
            "output_root": str(output_root),
        },
    )

    blender_path = find_blender()
    print(f"Using Blender: {blender_path}")
    # The helper performs the heavy evaluation/export work inside Blender, while
    # this wrapper keeps the sampling and validation logic in plain Python.
    run_blender_export(blender_path, spec_path)

    blender_summary_path = dirs["metadata"] / "blender_export_summary.json"
    if not blender_summary_path.exists():
        raise RuntimeError(f"Expected Blender summary at {blender_summary_path}")
    blender_summary = json.loads(blender_summary_path.read_text(encoding="utf-8"))

    exports = blender_summary.get("exports", [])
    if len(exports) != len(samples):
        raise RuntimeError(
            f"Expected {len(samples)} exports, Blender summary only contains {len(exports)}"
        )
    for export in exports:
        # Verify that Blender really produced both the posed mesh and the
        # corresponding bone transform dump for every requested sample.
        mesh_path = Path(export["posed_mesh_path"])
        bone_path = Path(export["bone_transforms_path"])
        if not mesh_path.exists():
            raise RuntimeError(f"Missing posed mesh export {mesh_path}")
        if not bone_path.exists():
            raise RuntimeError(f"Missing bone transform export {bone_path}")

    report_text = build_report(output_root, actor_data, dae_data, samples, blender_summary)
    report_path = output_root / "actor_walking_spike_report.md"
    report_path.write_text(report_text + "\n", encoding="utf-8")

    print("\nActor spike complete")
    print(f"Metadata: {metadata_path}")
    print(f"Samples: {samples_path}")
    print(f"Blender summary: {blender_summary_path}")
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
