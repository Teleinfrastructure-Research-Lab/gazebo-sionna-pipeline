#!/usr/bin/env python3
"""Extract camera rig entries from copied Gazebo pose topic output."""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = PROJECT_ROOT / "rt_out/experiments/perception_rt_small_v0/configs/perception_dataset_config.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract camera_rig.json-compatible entries from Gazebo pose topic output."
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Perception dataset config JSON.")
    parser.add_argument("--pose-log", required=True, help="Text file copied from gz topic pose output.")
    parser.add_argument("--template-rig", help="Optional camera rig JSON used as the output template.")
    parser.add_argument("--output-json", help="Optional output JSON path for the extracted camera rig snippet.")
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


def load_camera_ids(config: dict[str, Any]) -> list[str]:
    camera_ids = config.get("camera_ids")
    if not isinstance(camera_ids, list) or not camera_ids or not all(isinstance(item, str) and item.strip() for item in camera_ids):
        fail("Config field 'camera_ids' must be a non-empty list of camera IDs.")
    return camera_ids


def build_target_models(camera_ids: list[str]) -> list[tuple[str, str]]:
    return [(f"debug_{camera_id}", camera_id) for camera_id in camera_ids]


def quaternion_to_rpy(x: float, y: float, z: float, w: float) -> list[float]:
    sinr_cosp = 2.0 * (w * x + y * z)
    cosr_cosp = 1.0 - 2.0 * (x * x + y * y)
    roll = math.atan2(sinr_cosp, cosr_cosp)

    sinp = 2.0 * (w * y - z * x)
    if abs(sinp) >= 1.0:
        pitch = math.copysign(math.pi / 2.0, sinp)
    else:
        pitch = math.asin(sinp)

    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    yaw = math.atan2(siny_cosp, cosy_cosp)

    return [roll, pitch, yaw]


def load_pose_log(path: Path) -> str:
    if not path.is_file():
        fail(f"Missing pose log: {path}")
    return path.read_text(encoding="utf-8")


def extract_model_pose_block(content: str, model_name: str) -> dict[str, float] | None:
    number = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
    pattern = re.compile(
        rf'name:\s*"{re.escape(model_name)}".*?position\s*\{{\s*x:\s*(?P<px>{number})\s*y:\s*(?P<py>{number})\s*z:\s*(?P<pz>{number})\s*\}}.*?orientation\s*\{{\s*x:\s*(?P<qx>{number})\s*y:\s*(?P<qy>{number})\s*z:\s*(?P<qz>{number})\s*w:\s*(?P<qw>{number})\s*\}}',
        re.DOTALL,
    )
    match = pattern.search(content)
    if match is None:
        return None
    return {key: float(value) for key, value in match.groupdict().items()}


def build_camera_entries(
    extracted: dict[str, dict[str, float]],
    template_rig: dict[str, Any],
    target_models: list[tuple[str, str]],
    template_rig_path: Path,
) -> list[dict[str, Any]]:
    template_by_id = {}
    cameras = template_rig.get("cameras")
    if not isinstance(cameras, list):
        fail(f"Template camera rig at {template_rig_path} must contain a 'cameras' list.")
    for camera in cameras:
        if isinstance(camera, dict) and isinstance(camera.get("camera_id"), str):
            template_by_id[camera["camera_id"]] = camera

    results: list[dict[str, Any]] = []
    for model_name, camera_id in target_models:
        pose = extracted.get(model_name)
        if pose is None:
            fail(f"Did not find pose entry for {model_name} in the pose log.")
        if camera_id not in template_by_id:
            fail(f"Template camera rig is missing camera_id '{camera_id}'.")
        rpy = quaternion_to_rpy(pose["qx"], pose["qy"], pose["qz"], pose["qw"])
        template = template_by_id[camera_id]
        results.append(
            {
                "camera_id": camera_id,
                "pose_xyz_rpy": [
                    round(pose["px"], 6),
                    round(pose["py"], 6),
                    round(pose["pz"], 6),
                    round(rpy[0], 6),
                    round(rpy[1], 6),
                    round(rpy[2], 6),
                ],
                "width": template["width"],
                "height": template["height"],
                "horizontal_fov": template["horizontal_fov"],
                "near_clip": template["near_clip"],
                "far_clip": template["far_clip"],
            }
        )
    return results


def main() -> None:
    args = parse_args()
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    pose_log_path = Path(args.pose_log)
    if not pose_log_path.is_absolute():
        pose_log_path = PROJECT_ROOT / pose_log_path

    config = load_json(config_path, "perception dataset config")
    if not isinstance(config, dict):
        fail(f"Perception dataset config at {config_path} must be a JSON object.")
    camera_ids = load_camera_ids(config)
    target_models = build_target_models(camera_ids)
    experiment_root = config_path.resolve().parents[1]
    template_rig_path = Path(args.template_rig) if args.template_rig else experiment_root / "configs" / "camera_rig.json"
    if not template_rig_path.is_absolute():
        template_rig_path = PROJECT_ROOT / template_rig_path

    content = load_pose_log(pose_log_path)
    extracted: dict[str, dict[str, float]] = {}
    for model_name, _camera_id in target_models:
        pose = extract_model_pose_block(content, model_name)
        if pose is not None:
            extracted[model_name] = pose

    template_rig = load_json(template_rig_path, "template camera rig")
    if not isinstance(template_rig, dict):
        fail(f"Template camera rig at {template_rig_path} must be a JSON object.")

    payload = {"cameras": build_camera_entries(extracted, template_rig, target_models, template_rig_path)}

    if args.output_json:
        output_path = Path(args.output_json)
        if not output_path.is_absolute():
            output_path = PROJECT_ROOT / output_path
        write_json(output_path, payload)

    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
