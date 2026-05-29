#!/usr/bin/env python3
"""Build Gazebo-native labeled perception worlds for the pilot dataset.

This script preserves the original Gazebo scene structure from ``myworld_rt.sdf``
and adds segmentation labels plus the fixed perception camera rig. It does not
run Gazebo.

The active output is ``gazebo_native_panoptic_world.sdf``. Its panoptic
``labels_map`` stores semantic labels in channel 2 and Gazebo runtime instance
counts in channels 1 and 0. The same fixed rig also gets optional RGB and
depth sensors so RGB-D can be captured without changing the panoptic topics.

An optional sibling world can also be generated for stable-instance panoptic
labeling. That world preserves the same scene and camera rig, but writes compact
stable instance labels into channel 2 while keeping Gazebo runtime instance
counts in channels 1 and 0 for diagnostics only.

Legacy split semantic / instance worlds can still be rebuilt for debugging with
``--build-debug-split-worlds``. When requested, they are written under the
experiment-local ``legacy/`` tree, not the active ``perception_sdf/`` folder.

The compact instance labels are translated back to stable dataset instance IDs
through ``instance_label_map.json``. That map remains useful for stable object
metadata and debugging, but it is not the primary panoptic instance encoding.
"""

from __future__ import annotations

import argparse
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = PROJECT_ROOT / "rt_out/experiments/perception_rt_small_v0/configs/perception_dataset_config.json"
DEFAULT_WORLD = PROJECT_ROOT / "myworld_rt.sdf"
DEFAULT_FACTORY_SHELL = PROJECT_ROOT / "models/factory_shell/model.sdf"
REQUIRED_SEMANTIC_IDS = {str(index) for index in range(1, 11)}
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the Gazebo-native panoptic primary world for the perception pilot."
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Perception dataset config JSON.")
    parser.add_argument(
        "--build-stable-instance-panoptic-world",
        action="store_true",
        help="Build an additional stable-instance panoptic world without changing the primary semantic panoptic world behavior.",
    )
    parser.add_argument(
        "--build-debug-split-worlds",
        action="store_true",
        help="Also rebuild legacy semantic/instance split worlds under the experiment's legacy/ tree.",
    )
    parser.add_argument(
        "--debug-camera-visuals",
        action="store_true",
        help="Also generate a debug-only native world with visible camera helpers for rig inspection.",
    )
    parser.add_argument(
        "--camera-tuning-world",
        action="store_true",
        help="Also generate a movable camera-tuning world with real segmentation sensors plus visible helpers.",
    )
    parser.add_argument(
        "--camera-helper-scale",
        type=float,
        default=1.0,
        help="Scale factor for debug camera helper geometry. Default keeps helpers visible at room scale.",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite generated native-world outputs.")
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


def normalize_name(value: str | None) -> str:
    return (value or "").strip().lower()


def copy_element(element: ET.Element) -> ET.Element:
    return ET.fromstring(ET.tostring(element, encoding="unicode"))


def parse_pose6(value: Any, label: str) -> list[float]:
    if value is None:
        return [0.0] * 6
    if isinstance(value, str):
        parts = value.split()
    elif isinstance(value, list):
        parts = value
    else:
        fail(f"Unsupported pose format for {label}: {value!r}")
    if len(parts) != 6:
        fail(f"Expected 6 pose values for {label}, got {len(parts)}: {value!r}")
    try:
        return [float(part) for part in parts]
    except ValueError as exc:
        fail(f"Non-numeric pose values for {label}: {value!r} ({exc})")


def pose_text(value: Any, label: str) -> str:
    pose = parse_pose6(value, label)
    return " ".join(f"{item:.12g}" for item in pose)


def compose_pose6(parent: Any, child: Any, label: str) -> str:
    parent_pose = parse_pose6(parent, f"{label} parent")
    child_pose = parse_pose6(child, f"{label} child")
    return " ".join(f"{parent_item + child_item:.12g}" for parent_item, child_item in zip(parent_pose, child_pose))


def append_text(parent: ET.Element, tag: str, text: str) -> ET.Element:
    child = ET.SubElement(parent, tag)
    child.text = text
    return child


def add_label_plugin(parent: ET.Element, label_value: int) -> None:
    plugin = ET.SubElement(
        parent,
        "plugin",
        {"filename": "gz-sim-label-system", "name": "gz::sim::systems::Label"},
    )
    append_text(plugin, "label", str(label_value))


def remove_existing_outputs(paths: list[Path], force: bool) -> None:
    existing = [path for path in paths if path.exists()]
    if existing and not force:
        fail(
            "Output already exists. Re-run with --force to overwrite: "
            + ", ".join(str(path) for path in existing)
        )
    if force:
        for path in existing:
            if path.is_dir():
                for child in sorted(path.rglob("*"), reverse=True):
                    if child.is_file():
                        child.unlink()
                    elif child.is_dir():
                        child.rmdir()
                path.rmdir()
            else:
                path.unlink()


def validate_semantic_map(data: Any, path: Path) -> dict[int, str]:
    if not isinstance(data, dict):
        fail(f"Semantic label map at {path} must be a JSON object.")
    keys = set(data.keys())
    if keys != REQUIRED_SEMANTIC_IDS:
        fail(
            f"Semantic label map at {path} must contain exactly IDs 1..10. "
            f"Found keys: {sorted(keys)}"
        )
    semantic_map: dict[int, str] = {}
    for raw_key, raw_value in sorted(data.items(), key=lambda item: int(item[0])):
        if not isinstance(raw_value, str) or not raw_value.strip():
            fail(f"Semantic label map value for ID {raw_key} must be a non-empty string.")
        semantic_map[int(raw_key)] = raw_value
    return semantic_map


def load_camera_rig(path: Path, config: dict[str, Any]) -> list[dict[str, Any]]:
    payload = load_json(path, "camera rig")
    if not isinstance(payload, dict) or not isinstance(payload.get("cameras"), list):
        fail(f"Camera rig file at {path} must contain a 'cameras' list.")
    cameras = payload["cameras"]
    camera_map: dict[str, dict[str, Any]] = {}
    for camera in cameras:
        if not isinstance(camera, dict):
            fail(f"Camera rig entry is not an object: {camera!r}")
        camera_id = camera.get("camera_id")
        if not isinstance(camera_id, str) or not camera_id.strip():
            fail(f"Camera rig entry missing a valid camera_id: {camera!r}")
        camera_map[camera_id] = camera

    requested_ids = config.get("camera_ids")
    if not isinstance(requested_ids, list) or not requested_ids or not all(isinstance(item, str) for item in requested_ids):
        fail("Config field 'camera_ids' must be a non-empty list of camera IDs.")

    ordered: list[dict[str, Any]] = []
    for required_id in requested_ids:
        if required_id not in camera_map:
            fail(f"Camera rig missing required camera '{required_id}'.")
        ordered.append(camera_map[required_id])
    return ordered


def load_instance_registry(path: Path) -> list[dict[str, Any]]:
    payload = load_json(path, "instance registry")
    if not isinstance(payload, dict) or not isinstance(payload.get("instances"), list):
        fail(f"Instance registry at {path} must contain an 'instances' list.")
    instances = payload["instances"]
    if not instances:
        fail(f"Instance registry at {path} contains no instances.")
    return instances


def attach_label_to_entity(entity: ET.Element, label_value: int) -> int:
    visuals = list(entity.findall(".//visual"))
    if visuals:
        for visual in visuals:
            add_label_plugin(visual, label_value)
        return len(visuals)
    add_label_plugin(entity, label_value)
    return 1


def add_segmentation_sensor(
    link: ET.Element,
    camera: dict[str, Any],
    topic: str,
    save_dir: Path,
    segmentation_mode: str,
) -> None:
    sensor = ET.SubElement(link, "sensor", {"name": f"{camera['camera_id']}_segmentation", "type": "segmentation"})
    append_text(sensor, "topic", topic)
    camera_elem = ET.SubElement(sensor, "camera")
    append_text(camera_elem, "segmentation_type", segmentation_mode)
    append_text(camera_elem, "horizontal_fov", str(camera["horizontal_fov"]))
    image = ET.SubElement(camera_elem, "image")
    append_text(image, "width", str(camera["width"]))
    append_text(image, "height", str(camera["height"]))
    clip = ET.SubElement(camera_elem, "clip")
    append_text(clip, "near", str(camera["near_clip"]))
    append_text(clip, "far", str(camera["far_clip"]))
    save = ET.SubElement(camera_elem, "save", {"enabled": "true"})
    append_text(save, "path", str(save_dir.resolve()))
    append_text(sensor, "always_on", "1")
    append_text(sensor, "update_rate", "30")
    append_text(sensor, "visualize", "true")


def add_camera_core(
    camera_elem: ET.Element,
    camera: dict[str, Any],
    *,
    image_format: str | None,
    save_dir: Path,
) -> None:
    append_text(camera_elem, "horizontal_fov", str(camera["horizontal_fov"]))
    image = ET.SubElement(camera_elem, "image")
    append_text(image, "width", str(camera["width"]))
    append_text(image, "height", str(camera["height"]))
    if image_format:
        append_text(image, "format", image_format)
    clip = ET.SubElement(camera_elem, "clip")
    append_text(clip, "near", str(camera["near_clip"]))
    append_text(clip, "far", str(camera["far_clip"]))
    save = ET.SubElement(camera_elem, "save", {"enabled": "true"})
    append_text(save, "path", str(save_dir.resolve()))


def add_rgb_sensor(
    link: ET.Element,
    camera: dict[str, Any],
    topic: str,
    save_dir: Path,
) -> None:
    sensor = ET.SubElement(link, "sensor", {"name": f"{camera['camera_id']}_rgb", "type": "camera"})
    append_text(sensor, "topic", topic)
    camera_elem = ET.SubElement(sensor, "camera")
    add_camera_core(camera_elem, camera, image_format="R8G8B8", save_dir=save_dir)
    append_text(sensor, "always_on", "1")
    append_text(sensor, "update_rate", "30")
    append_text(sensor, "visualize", "false")


def add_depth_sensor(
    link: ET.Element,
    camera: dict[str, Any],
    topic: str,
    save_dir: Path,
) -> None:
    sensor = ET.SubElement(link, "sensor", {"name": f"{camera['camera_id']}_depth", "type": "depth_camera"})
    append_text(sensor, "topic", topic)
    camera_elem = ET.SubElement(sensor, "camera")
    add_camera_core(camera_elem, camera, image_format="R_FLOAT32", save_dir=save_dir)
    depth_camera = ET.SubElement(camera_elem, "depth_camera")
    append_text(depth_camera, "output", "depths")
    depth_clip = ET.SubElement(depth_camera, "clip")
    append_text(depth_clip, "near", str(camera["near_clip"]))
    append_text(depth_clip, "far", str(camera["far_clip"]))
    append_text(sensor, "always_on", "1")
    append_text(sensor, "update_rate", "30")
    append_text(sensor, "visualize", "false")


def add_rgbd_sensors(
    link: ET.Element,
    camera: dict[str, Any],
    output_root: Path,
) -> None:
    camera_id = str(camera["camera_id"])
    camera_root = output_root / camera_id
    add_rgb_sensor(
        link,
        camera,
        f"/perception/native/rgbd/{camera_id}/rgb",
        camera_root / "rgb",
    )
    add_depth_sensor(
        link,
        camera,
        f"/perception/native/rgbd/{camera_id}/depth",
        camera_root / "depth",
    )


def add_camera_rig(
    world: ET.Element,
    cameras: list[dict[str, Any]],
    output_root: Path,
    world_kind: str,
    segmentation_mode: str,
) -> int:
    if world_kind == "panoptic":
        note = (
            "panoptic camera rig: labels_map stores semantic IDs in channel 2 and "
            "Gazebo runtime instance counts in channels 1 and 0. "
            "Each fixed pose also carries optional RGB and depth sensors for RGB-D capture."
        )
    elif world_kind == "stable_instance_panoptic":
        note = (
            "stable-instance panoptic camera rig: labels_map stores compact stable instance labels "
            "in channel 2 and Gazebo runtime instance counts in channels 1 and 0. "
            "Each fixed pose also carries optional RGB and depth sensors for synchronized RGB/PCL capture."
        )
    elif world_kind == "semantic":
        note = "debug semantic camera rig: labels_map stores class labels 1..10."
    else:
        note = "debug instance camera rig: labels_map stores compact per-instance labels mapped by instance_label_map.json."
    world.append(ET.Comment(note))
    model = ET.SubElement(world, "model", {"name": f"perception_native_camera_rig_{world_kind}"})
    append_text(model, "static", "true")
    append_text(model, "pose", "0 0 0 0 0 0")
    for camera in cameras:
        link = ET.SubElement(model, "link", {"name": camera["camera_id"]})
        append_text(link, "pose", pose_text(camera["pose_xyz_rpy"], f"camera {camera['camera_id']}"))
        add_segmentation_sensor(
            link,
            camera,
            f"/perception/native/{world_kind}/{camera['camera_id']}",
            output_root / camera["camera_id"],
            segmentation_mode,
        )
        if world_kind in {"panoptic", "stable_instance_panoptic"}:
            add_rgbd_sensors(
                link,
                camera,
                output_root.parent / "rgbd",
            )
    return len(cameras)


def populate_debug_camera_helper_link(link: ET.Element, scale: float = 1.0) -> int:
    if scale <= 0.0:
        fail(f"--camera-helper-scale must be positive, got {scale}.")

    axis_specs = (
        ("forward", 0.6 * scale, "0 1.57079632679 0", 1.2 * scale, 0.035 * scale, "1 0 0 1"),
        ("left", 0.3 * scale, "-1.57079632679 0 0", 0.6 * scale, 0.035 * scale, "0 1 0 1"),
        ("up", 0.3 * scale, "0 0 0", 0.6 * scale, 0.035 * scale, "0 0.35 1 1"),
    )
    frustum_specs = (
        ("frustum_upper_left", 0.9 * scale, 0.3825 * scale, 0.27 * scale, "0.29145679448 1.14416883367 0.41151684607"),
        ("frustum_upper_right", 0.9 * scale, -0.3825 * scale, 0.27 * scale, "-0.29145679448 1.14416883367 -0.41151684607"),
        ("frustum_lower_left", 0.9 * scale, 0.3825 * scale, -0.27 * scale, "-0.29145679448 1.14416883367 0.41151684607"),
        ("frustum_lower_right", 0.9 * scale, -0.3825 * scale, -0.27 * scale, "0.29145679448 1.14416883367 -0.41151684607"),
    )

    helper_geometry_count = 0
    body_visual = ET.SubElement(link, "visual", {"name": "origin_marker"})
    append_text(body_visual, "pose", "0 0 0 0 0 0")
    body_geometry = ET.SubElement(body_visual, "geometry")
    sphere = ET.SubElement(body_geometry, "sphere")
    append_text(sphere, "radius", f"{0.18 * scale:.12g}")
    body_material = ET.SubElement(body_visual, "material")
    body_ambient = ET.SubElement(body_material, "ambient")
    body_ambient.text = "1 1 0 1"
    body_diffuse = ET.SubElement(body_material, "diffuse")
    body_diffuse.text = "1 1 0 1"
    body_emissive = ET.SubElement(body_material, "emissive")
    body_emissive.text = "0.9 0.9 0 1"
    helper_geometry_count += 1

    for axis_name, offset, rotation, length, radius, axis_color in axis_specs:
        visual = ET.SubElement(link, "visual", {"name": axis_name})
        if axis_name == "forward":
            pose = f"{offset:.12g} 0 0 {rotation}"
        elif axis_name == "left":
            pose = f"0 {offset:.12g} 0 {rotation}"
        else:
            pose = f"0 0 {offset:.12g} {rotation}"
        append_text(visual, "pose", pose)
        geometry = ET.SubElement(visual, "geometry")
        cylinder = ET.SubElement(geometry, "cylinder")
        append_text(cylinder, "length", f"{length:.12g}")
        append_text(cylinder, "radius", f"{radius:.12g}")
        material = ET.SubElement(visual, "material")
        ambient = ET.SubElement(material, "ambient")
        ambient.text = axis_color
        diffuse = ET.SubElement(material, "diffuse")
        diffuse.text = axis_color
        emissive = ET.SubElement(material, "emissive")
        emissive.text = axis_color
        helper_geometry_count += 1

    for ray_name, x, y, z, rotation in frustum_specs:
        visual = ET.SubElement(link, "visual", {"name": ray_name})
        append_text(visual, "pose", f"{x:.12g} {y:.12g} {z:.12g} {rotation}")
        geometry = ET.SubElement(visual, "geometry")
        cylinder = ET.SubElement(geometry, "cylinder")
        append_text(cylinder, "length", f"{1.8 * scale:.12g}")
        append_text(cylinder, "radius", f"{0.025 * scale:.12g}")
        material = ET.SubElement(visual, "material")
        ambient = ET.SubElement(material, "ambient")
        ambient.text = "1 0.5 0 1"
        diffuse = ET.SubElement(material, "diffuse")
        diffuse.text = "1 0.5 0 1"
        emissive = ET.SubElement(material, "emissive")
        emissive.text = "1 0.35 0 1"
        helper_geometry_count += 1
    return helper_geometry_count


def add_debug_camera_visuals(world: ET.Element, cameras: list[dict[str, Any]], scale: float) -> tuple[int, list[dict[str, Any]]]:
    world.append(
        ET.Comment(
            "Debug camera visuals for rig inspection only. "
            "source=debug_camera_visual; not part of dataset capture."
        )
    )
    helper_geometry_count = 0
    camera_summaries: list[dict[str, Any]] = []

    for camera in cameras:
        camera_id = str(camera["camera_id"])
        model = ET.SubElement(world, "model", {"name": f"debug_{camera_id}"})
        append_text(model, "static", "true")
        append_text(model, "pose", pose_text(camera["pose_xyz_rpy"], f"debug camera {camera_id}"))
        append_text(model, "self_collide", "false")

        body_link = ET.SubElement(model, "link", {"name": "camera_helper"})
        append_text(body_link, "pose", "0 0 0 0 0 0")
        helper_geometry_count += populate_debug_camera_helper_link(body_link, scale)

        camera_summaries.append(
            {
                "camera_id": camera_id,
                "pose_xyz_rpy": parse_pose6(camera["pose_xyz_rpy"], f"camera {camera_id}"),
                "helper_geometry_count": 8,
                "source": "debug_camera_visual",
                "note": "not part of dataset capture",
            }
        )

    return helper_geometry_count, camera_summaries


def remove_named_model(world: ET.Element, model_name: str) -> None:
    removed = False
    for model in list(world.findall("model")):
        if model.get("name") == model_name:
            world.remove(model)
            removed = True
    if not removed:
        fail(f"Expected model '{model_name}' was not found in the world.")


def add_movable_camera_tuning_models(
    world: ET.Element,
    cameras: list[dict[str, Any]],
    output_root: Path,
    scale: float,
    segmentation_mode: str,
) -> tuple[int, list[dict[str, Any]]]:
    world.append(
        ET.Comment(
            "Camera tuning world for visual rig adjustment only. "
            "source=debug_camera_visual; not part of dataset capture."
        )
    )
    helper_geometry_count = 0
    camera_summaries: list[dict[str, Any]] = []

    for camera in cameras:
        camera_id = str(camera["camera_id"])
        model = ET.SubElement(world, "model", {"name": f"debug_{camera_id}"})
        append_text(model, "static", "true")
        append_text(model, "pose", pose_text(camera["pose_xyz_rpy"], f"tuning camera {camera_id}"))
        append_text(model, "self_collide", "false")

        link = ET.SubElement(model, "link", {"name": "camera_body"})
        append_text(link, "pose", "0 0 0 0 0 0")
        add_segmentation_sensor(
            link,
            camera,
            f"/perception/native/tuning/{camera_id}",
            output_root / camera_id,
            segmentation_mode,
        )
        helper_geometry_count += populate_debug_camera_helper_link(link, scale)

        camera_summaries.append(
            {
                "camera_id": camera_id,
                "model_name": f"debug_{camera_id}",
                "pose_xyz_rpy": parse_pose6(camera["pose_xyz_rpy"], f"camera {camera_id}"),
                "helper_geometry_count": 8,
                "source": "debug_camera_visual",
                "note": "static tuning handle; not part of dataset capture",
            }
        )

    return len(cameras), camera_summaries


def classify_factory_shell_visual(submodel_name: str, visual_name: str, semantic_map: dict[int, str]) -> tuple[str, int, int, str]:
    if visual_name in {"floor_visual", "floor_surface_visual"}:
        return "factory_shell_floor", 4000, 1, semantic_map[1]
    if visual_name in {"ceiling_visual", "ceiling_surface_visual"}:
        return "factory_shell_ceiling", 4001, 2, semantic_map[2]
    if visual_name.startswith("north_window_left_"):
        return "factory_shell_north_window_left", 4100, 5, semantic_map[5]
    if visual_name.startswith("north_window_right_"):
        return "factory_shell_north_window_right", 4101, 5, semantic_map[5]
    if submodel_name == "north_wall" and "wall" in visual_name:
        return "factory_shell_north_wall", 4002, 3, semantic_map[3]
    if submodel_name == "south_wall":
        return "factory_shell_south_wall", 4003, 3, semantic_map[3]
    if submodel_name == "east_wall" and visual_name == "east_wall_visual":
        return "factory_shell_east_wall", 4004, 3, semantic_map[3]
    if submodel_name == "west_wall" and visual_name == "west_wall_visual":
        return "factory_shell_west_wall", 4005, 3, semantic_map[3]
    if "door" in visual_name or "gate" in visual_name:
        return "factory_shell_misc", 4900, 4, semantic_map[4]
    if "window" in visual_name:
        return "factory_shell_misc", 4900, 5, semantic_map[5]
    return "factory_shell_misc", 4900, 10, semantic_map[10]


def parse_factory_shell(
    factory_shell_path: Path,
    include_pose: str,
    semantic_map: dict[int, str],
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    if not factory_shell_path.is_file():
        fail(f"Factory shell SDF not found: {factory_shell_path}")
    try:
        root = ET.parse(factory_shell_path).getroot()
    except ET.ParseError as exc:
        fail(f"Failed to parse factory shell SDF {factory_shell_path}: {exc}")

    top_model = root.find("model")
    if top_model is None:
        fail(f"Factory shell SDF {factory_shell_path} does not contain a top-level model.")

    groups: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []
    for submodel in sorted(top_model.findall("model"), key=lambda elem: elem.get("name", "")):
        submodel_name = submodel.get("name", "")
        submodel_pose = submodel.findtext("pose") or "0 0 0 0 0 0"
        for link in sorted(submodel.findall("link"), key=lambda elem: elem.get("name", "")):
            link_name = link.get("name", "")
            local_link_pose = compose_pose6(submodel_pose, link.findtext("pose") or "0 0 0 0 0 0", f"{submodel_name}/{link_name}")
            world_link_pose = compose_pose6(include_pose, local_link_pose, f"factory_shell {submodel_name}/{link_name}")
            for visual in sorted(link.findall("visual"), key=lambda elem: elem.get("name", "")):
                visual_name = visual.get("name", "")
                geometry_elem = visual.find("geometry")
                if geometry_elem is None:
                    warnings.append(f"Factory shell visual {submodel_name}/{link_name}/{visual_name} is missing geometry.")
                    continue
                instance_name, stable_instance_id, semantic_id, semantic_name = classify_factory_shell_visual(
                    submodel_name,
                    visual_name,
                    semantic_map,
                )
                if instance_name == "factory_shell_misc":
                    warnings.append(
                        f"Factory shell visual {submodel_name}/{link_name}/{visual_name} fell back to {semantic_name}."
                    )
                group = groups.setdefault(
                    instance_name,
                    {
                        "instance_name": instance_name,
                        "stable_instance_id": stable_instance_id,
                        "semantic_id": semantic_id,
                        "semantic_name": semantic_name,
                        "links": {},
                    },
                )
                group_link_name = f"{submodel_name}__{link_name}"
                link_entry = group["links"].setdefault(
                    group_link_name,
                    {
                        "name": group_link_name,
                        "pose": world_link_pose,
                        "visuals": [],
                    },
                )
                link_entry["visuals"].append(
                    {
                        "name": visual_name,
                        "pose": visual.findtext("pose") or "0 0 0 0 0 0",
                        "geometry": copy_element(geometry_elem),
                        "material": copy_element(visual.find("material")) if visual.find("material") is not None else None,
                        "cast_shadows": visual.findtext("cast_shadows"),
                    }
                )
    return groups, warnings


def build_factory_shell_models(
    world: ET.Element,
    groups: dict[str, dict[str, Any]],
    label_mode: str,
    compact_lookup: dict[int, int],
) -> int:
    geometry_count = 0
    for group_name in sorted(groups):
        group = groups[group_name]
        label_value = group["semantic_id"] if label_mode == "semantic" else compact_lookup[group["stable_instance_id"]]
        model = ET.SubElement(world, "model", {"name": group["instance_name"]})
        append_text(model, "static", "true")
        append_text(model, "pose", "0 0 0 0 0 0")
        for link_name in sorted(group["links"]):
            link_data = group["links"][link_name]
            link = ET.SubElement(model, "link", {"name": link_data["name"]})
            append_text(link, "pose", link_data["pose"])
            for visual_data in link_data["visuals"]:
                visual = ET.SubElement(link, "visual", {"name": visual_data["name"]})
                append_text(visual, "pose", visual_data["pose"])
                visual.append(copy_element(visual_data["geometry"]))
                if visual_data["material"] is not None:
                    visual.append(copy_element(visual_data["material"]))
                if visual_data["cast_shadows"] is not None:
                    append_text(visual, "cast_shadows", visual_data["cast_shadows"])
                add_label_plugin(visual, label_value)
                geometry_count += 1
    return geometry_count


def build_compact_instance_label_map(
    registry_instances: list[dict[str, Any]],
    factory_shell_groups: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[int, int], list[dict[str, Any]], int, int]:
    entries: list[dict[str, Any]] = []
    structural_entries = [
        {
            "stable_instance_id": int(group["stable_instance_id"]),
            "instance_name": str(group["instance_name"]),
            "semantic_id": int(group["semantic_id"]),
            "semantic_name": str(group["semantic_name"]),
            "source": "factory_shell_structure",
        }
        for _, group in sorted(
            factory_shell_groups.items(),
            key=lambda item: (int(item[1]["stable_instance_id"]), item[0]),
        )
    ]
    entries.extend(structural_entries)

    for instance in sorted(registry_instances, key=lambda item: (int(item["instance_id"]), str(item["instance_name"]))):
        if normalize_name(str(instance["instance_name"])) == "factory_shell" or normalize_name(str(instance.get("model"))) == "factory_shell":
            continue
        entries.append(
            {
                "stable_instance_id": int(instance["instance_id"]),
                "instance_name": str(instance["instance_name"]),
                "semantic_id": int(instance["semantic_id"]),
                "semantic_name": str(instance["semantic_name"]),
                "source": str(instance.get("source", "registry")),
            }
        )

    label_map: dict[str, dict[str, Any]] = {}
    lookup: dict[int, int] = {}
    numbered_entries: list[dict[str, Any]] = []
    for compact_label, entry in enumerate(entries, start=1):
        if compact_label >= 255:
            fail(
                "Compact instance labels exceeded the supported range. "
                f"max_compact_instance_label would be {compact_label}, but it must stay < 255."
            )
        label_map[str(compact_label)] = entry
        lookup[int(entry["stable_instance_id"])] = compact_label
        numbered_entries.append(
            {
                "compact_instance_label": compact_label,
                **entry,
            }
        )

    if not label_map:
        fail("Compact instance label map is empty.")
    max_label = max(int(key) for key in label_map)
    if max_label >= 255:
        fail(f"max_compact_instance_label={max_label} must stay < 255.")
    return label_map, lookup, numbered_entries, len(label_map), max_label


def build_stable_instance_label_map_payload(
    numbered_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    reverse_lookup = {
        str(int(entry["stable_instance_id"])): int(entry["compact_instance_label"])
        for entry in numbered_entries
    }
    return {
        "label_mode": "compact_stable_instance",
        "label_channel": "panoptic_rgb_channel_2",
        "gazebo_instance_count_channels": "rgb[1] * 256 + rgb[0]",
        "gazebo_instance_count_is_stable_instance_id": False,
        "compact_instance_label_count": len(numbered_entries),
        "max_compact_instance_label": max(
            (int(entry["compact_instance_label"]) for entry in numbered_entries),
            default=0,
        ),
        "stable_instance_id_to_compact_instance_label": reverse_lookup,
        "entries": numbered_entries,
    }


def build_registry_lookups(registry_instances: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_instance_name: dict[str, dict[str, Any]] = {}
    by_model_name: dict[str, dict[str, Any]] = {}
    for instance in registry_instances:
        instance_name = normalize_name(str(instance["instance_name"]))
        model_name = normalize_name(str(instance.get("model")))
        if instance_name == "factory_shell" or model_name == "factory_shell":
            continue
        by_instance_name[instance_name] = instance
        if model_name:
            by_model_name[model_name] = instance
    return by_instance_name, by_model_name


def match_registry_instance(
    name: str,
    by_instance_name: dict[str, dict[str, Any]],
    by_model_name: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    normalized = normalize_name(name)
    return by_instance_name.get(normalized) or by_model_name.get(normalized)


def label_native_entities(
    world: ET.Element,
    label_mode: str,
    compact_lookup: dict[int, int],
    registry_instances: list[dict[str, Any]],
) -> tuple[int, int, int, list[dict[str, Any]], list[str]]:
    by_instance_name, by_model_name = build_registry_lookups(registry_instances)
    matched_stable_ids: set[int] = set()
    labeled_static_ids: set[int] = set()
    labeled_robot_ids: set[int] = set()
    labeled_human_ids: set[int] = set()
    skipped_unmatched: list[dict[str, Any]] = []
    warnings: list[str] = []

    for model in list(world.findall("model")):
        model_name = model.get("name", "")
        instance = match_registry_instance(model_name, by_instance_name, by_model_name)
        if instance is None:
            skipped_unmatched.append({"entity": "model", "name": model_name, "reason": "not found in instance registry"})
            continue
        stable_instance_id = int(instance["instance_id"])
        label_value = int(instance["semantic_id"]) if label_mode == "semantic" else compact_lookup[stable_instance_id]
        visual_count = attach_label_to_entity(model, label_value)
        if visual_count == 0:
            warnings.append(f"Model {model_name} had no visuals; applied label at model scope.")
        matched_stable_ids.add(stable_instance_id)
        if normalize_name(str(instance.get("source"))) == "static":
            labeled_static_ids.add(stable_instance_id)
        if int(instance["semantic_id"]) == 8:
            labeled_robot_ids.add(stable_instance_id)
        if int(instance["semantic_id"]) == 9:
            labeled_human_ids.add(stable_instance_id)

    for actor in list(world.findall("actor")):
        actor_name = actor.get("name", "")
        instance = match_registry_instance(actor_name, by_instance_name, by_model_name)
        if instance is None:
            skipped_unmatched.append({"entity": "actor", "name": actor_name, "reason": "not found in instance registry"})
            continue
        stable_instance_id = int(instance["instance_id"])
        label_value = int(instance["semantic_id"]) if label_mode == "semantic" else compact_lookup[stable_instance_id]
        attach_label_to_entity(actor, label_value)
        matched_stable_ids.add(stable_instance_id)
        if int(instance["semantic_id"]) == 8:
            labeled_robot_ids.add(stable_instance_id)
        if int(instance["semantic_id"]) == 9:
            labeled_human_ids.add(stable_instance_id)

    for instance in sorted(registry_instances, key=lambda item: int(item["instance_id"])):
        stable_instance_id = int(instance["instance_id"])
        if normalize_name(str(instance["instance_name"])) == "factory_shell" or normalize_name(str(instance.get("model"))) == "factory_shell":
            continue
        if stable_instance_id in matched_stable_ids:
            continue
        skipped_unmatched.append(
            {
                "entity": str(instance.get("source", "registry")),
                "name": str(instance["instance_name"]),
                "reason": "instance registry entry not found in native world",
            }
        )

    return len(labeled_static_ids), len(labeled_robot_ids), len(labeled_human_ids), skipped_unmatched, warnings


def clone_world_tree(root: ET.Element) -> ET.ElementTree:
    return ET.ElementTree(ET.fromstring(ET.tostring(root, encoding="unicode")))


def remove_factory_shell_include(world: ET.Element) -> str:
    include_pose = "0 0 0 0 0 0"
    removed = False
    for include in list(world.findall("include")):
        include_name = include.findtext("name")
        include_uri = include.findtext("uri")
        if normalize_name(include_name) == "factory_shell" or normalize_name(include_uri) == "model://factory_shell":
            include_pose = include.findtext("pose") or "0 0 0 0 0 0"
            world.remove(include)
            removed = True
    if not removed:
        fail("Original world does not contain the expected factory_shell include.")
    return include_pose


def build_world_variant(
    base_root: ET.Element,
    world_kind: str,
    label_mode: str,
    segmentation_mode: str,
    factory_shell_groups: dict[str, dict[str, Any]],
    registry_instances: list[dict[str, Any]],
    cameras: list[dict[str, Any]],
    compact_lookup: dict[int, int],
    native_raw_root: Path,
) -> tuple[ET.ElementTree, dict[str, Any]]:
    tree = clone_world_tree(base_root)
    root = tree.getroot()
    world = root.find("world")
    if world is None:
        fail("Original world SDF does not contain a <world> element.")

    remove_factory_shell_include(world)
    labeled_static_count, labeled_robot_count, labeled_human_count, skipped_unmatched, warnings = label_native_entities(
        world,
        label_mode,
        compact_lookup,
        registry_instances,
    )
    if world_kind == "panoptic":
        world.append(
            ET.Comment(
                "Primary native perception world: semantic labels use the compact taxonomy 1..10; "
                "panoptic labels_map stores semantic IDs in channel 2 and Gazebo runtime instance counts in channels 1 and 0."
            )
        )
    elif world_kind == "stable_instance_panoptic":
        world.append(
            ET.Comment(
                "Stable-instance panoptic native perception world: labels_map stores compact stable "
                "instance labels in channel 2 and Gazebo runtime instance counts in channels 1 and 0."
            )
        )
    elif world_kind == "semantic":
        world.append(ET.Comment("Debug semantic native perception world: labels_map stores class labels 1..10."))
    else:
        world.append(
            ET.Comment(
                "Debug instance native perception world: labels_map stores compact per-instance labels 1..N mapped by instance_label_map.json."
            )
        )
    structural_geometry_count = build_factory_shell_models(world, factory_shell_groups, label_mode, compact_lookup)
    camera_count = add_camera_rig(world, cameras, native_raw_root / world_kind, world_kind, segmentation_mode)

    summary = {
        "world_kind": world_kind,
        "label_mode": label_mode,
        "segmentation_mode": segmentation_mode,
        "camera_count": camera_count,
        "rgbd_enabled": world_kind in {"panoptic", "stable_instance_panoptic"},
        "rgbd_sensor_count": camera_count * 2 if world_kind in {"panoptic", "stable_instance_panoptic"} else 0,
        "rgbd_output_root": project_rel(native_raw_root / "rgbd") if world_kind in {"panoptic", "stable_instance_panoptic"} else "",
        "labeled_static_count": labeled_static_count,
        "labeled_robot_count": labeled_robot_count,
        "labeled_human_count": labeled_human_count,
        "labeled_factory_shell_structural_count": len(factory_shell_groups),
        "structural_geometry_count": structural_geometry_count,
        "warnings": warnings,
        "skipped_unmatched_models": skipped_unmatched,
    }
    ET.indent(tree, space="  ")
    return tree, summary


def build_camera_debug_world(
    semantic_tree: ET.ElementTree,
    cameras: list[dict[str, Any]],
    scale: float,
) -> tuple[ET.ElementTree, dict[str, Any]]:
    tree = clone_world_tree(semantic_tree.getroot())
    root = tree.getroot()
    world = root.find("world")
    if world is None:
        fail("Debug world source does not contain a <world> element.")
    helper_geometry_count, camera_summaries = add_debug_camera_visuals(world, cameras, scale)
    ET.indent(tree, space="  ")
    return tree, {
        "camera_count": len(cameras),
        "helper_geometry_count": helper_geometry_count,
        "cameras": camera_summaries,
    }


def build_camera_tuning_world(
    source_tree: ET.ElementTree,
    cameras: list[dict[str, Any]],
    native_raw_root: Path,
    scale: float,
    source_world_kind: str,
    segmentation_mode: str,
) -> tuple[ET.ElementTree, dict[str, Any]]:
    tree = clone_world_tree(source_tree.getroot())
    root = tree.getroot()
    world = root.find("world")
    if world is None:
        fail("Camera tuning world source does not contain a <world> element.")
    remove_named_model(world, f"perception_native_camera_rig_{source_world_kind}")
    camera_count, camera_summaries = add_movable_camera_tuning_models(
        world,
        cameras,
        native_raw_root / "tuning",
        scale,
        segmentation_mode,
    )
    ET.indent(tree, space="  ")
    return tree, {
        "camera_count": camera_count,
        "helper_geometry_count": sum(int(item["helper_geometry_count"]) for item in camera_summaries),
        "cameras": camera_summaries,
    }


def main() -> None:
    args = parse_args()
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    config = load_json(config_path, "perception dataset config")
    if not isinstance(config, dict):
        fail(f"Perception dataset config at {config_path} must be a JSON object.")

    experiment_root = config_path.resolve().parents[1]
    legacy_root = experiment_root / "legacy"
    split_world_debug_root = legacy_root / "split_world_debug_sdfs"
    split_world_capture_root = legacy_root / "split_world_capture_outputs"
    semantic_map_path = experiment_root / "configs" / "semantic_label_map.json"
    registry_path = experiment_root / "frames" / "instance_registry.json"
    camera_rig_path = experiment_root / "configs" / "camera_rig.json"
    output_root = experiment_root / "perception_sdf"
    native_raw_root = experiment_root / "perception_raw" / "native"

    panoptic_world_path = output_root / "gazebo_native_panoptic_world.sdf"
    stable_instance_panoptic_world_path = output_root / "gazebo_native_stable_instance_panoptic_world.sdf"
    semantic_world_path = split_world_debug_root / "gazebo_native_semantic_world.sdf"
    instance_world_path = split_world_debug_root / "gazebo_native_instance_world.sdf"
    debug_world_path = output_root / "gazebo_native_camera_debug_world.sdf"
    tuning_world_path = output_root / "gazebo_native_camera_tuning_world.sdf"
    instance_label_map_path = output_root / "instance_label_map.json"
    stable_instance_label_map_path = output_root / "stable_instance_label_map.json"
    summary_path = output_root / "gazebo_native_world_summary.json"
    stable_instance_summary_path = output_root / "gazebo_native_stable_instance_panoptic_world_summary.json"
    debug_summary_path = output_root / "camera_debug_world_summary.json"
    tuning_summary_path = output_root / "camera_tuning_world_summary.json"

    build_primary_panoptic = (
        not args.build_stable_instance_panoptic_world
        or args.build_debug_split_worlds
        or args.debug_camera_visuals
        or args.camera_tuning_world
    )
    build_stable_instance_world = bool(args.build_stable_instance_panoptic_world)

    overwrite_targets = [
    ]
    if build_primary_panoptic:
        overwrite_targets.extend(
            [
                panoptic_world_path,
                instance_label_map_path,
                summary_path,
            ]
        )
    if build_stable_instance_world:
        overwrite_targets.extend(
            [
                stable_instance_panoptic_world_path,
                stable_instance_label_map_path,
                stable_instance_summary_path,
            ]
        )
    if args.build_debug_split_worlds:
        overwrite_targets.extend([semantic_world_path, instance_world_path])
    if args.debug_camera_visuals:
        overwrite_targets.extend([debug_world_path, debug_summary_path])
    if args.camera_tuning_world:
        overwrite_targets.extend([tuning_world_path, tuning_summary_path])
    remove_existing_outputs(overwrite_targets, args.force)

    semantic_map = validate_semantic_map(load_json(semantic_map_path, "semantic label map"), semantic_map_path)
    registry_instances = load_instance_registry(registry_path)
    cameras = load_camera_rig(camera_rig_path, config)

    if not DEFAULT_WORLD.is_file():
        fail(f"Original Gazebo world not found: {DEFAULT_WORLD}")
    try:
        base_tree = ET.parse(DEFAULT_WORLD)
    except ET.ParseError as exc:
        fail(f"Failed to parse original world SDF at {DEFAULT_WORLD}: {exc}")
    base_root = base_tree.getroot()
    base_world = base_root.find("world")
    if base_world is None:
        fail(f"Original world SDF at {DEFAULT_WORLD} does not contain a <world> element.")
    include_pose = "0 0 0 0 0 0"
    for include in base_world.findall("include"):
        if normalize_name(include.findtext("name")) == "factory_shell" or normalize_name(include.findtext("uri")) == "model://factory_shell":
            include_pose = include.findtext("pose") or include_pose
            break

    factory_shell_groups, factory_shell_warnings = parse_factory_shell(DEFAULT_FACTORY_SHELL, include_pose, semantic_map)
    instance_label_map, compact_lookup, numbered_compact_entries, compact_instance_label_count, max_compact_instance_label = (
        build_compact_instance_label_map(registry_instances, factory_shell_groups)
    )
    stable_instance_label_map = build_stable_instance_label_map_payload(numbered_compact_entries)

    panoptic_tree: ET.ElementTree | None = None
    panoptic_summary: dict[str, Any] | None = None
    if build_primary_panoptic:
        panoptic_tree, panoptic_summary = build_world_variant(
            base_root,
            "panoptic",
            "semantic",
            "panoptic",
            factory_shell_groups,
            registry_instances,
            cameras,
            compact_lookup,
            native_raw_root,
        )
    stable_instance_tree: ET.ElementTree | None = None
    stable_instance_summary: dict[str, Any] | None = None
    if build_stable_instance_world:
        stable_instance_tree, stable_instance_summary = build_world_variant(
            base_root,
            "stable_instance_panoptic",
            "instance",
            "panoptic",
            factory_shell_groups,
            registry_instances,
            cameras,
            compact_lookup,
            native_raw_root,
        )
    semantic_tree: ET.ElementTree | None = None
    semantic_summary: dict[str, Any] | None = None
    instance_tree: ET.ElementTree | None = None
    instance_summary: dict[str, Any] | None = None
    if args.build_debug_split_worlds:
        semantic_tree, semantic_summary = build_world_variant(
            base_root,
            "semantic",
            "semantic",
            "semantic",
            factory_shell_groups,
            registry_instances,
            cameras,
            compact_lookup,
            split_world_capture_root,
        )
        instance_tree, instance_summary = build_world_variant(
            base_root,
            "instance",
            "instance",
            "semantic",
            factory_shell_groups,
            registry_instances,
            cameras,
            compact_lookup,
            split_world_capture_root,
        )

    output_root.mkdir(parents=True, exist_ok=True)
    if panoptic_tree is not None:
        panoptic_tree.write(panoptic_world_path, encoding="unicode")
        write_json(instance_label_map_path, instance_label_map)
    if stable_instance_tree is not None:
        stable_instance_tree.write(stable_instance_panoptic_world_path, encoding="unicode")
        write_json(stable_instance_label_map_path, stable_instance_label_map)
    if args.build_debug_split_worlds:
        split_world_debug_root.mkdir(parents=True, exist_ok=True)
        assert semantic_tree is not None
        assert instance_tree is not None
        semantic_tree.write(semantic_world_path, encoding="unicode")
        instance_tree.write(instance_world_path, encoding="unicode")

    if args.debug_camera_visuals:
        if panoptic_tree is None:
            fail("--debug-camera-visuals requires the primary panoptic world build path.")
        debug_tree, debug_world_summary = build_camera_debug_world(panoptic_tree, cameras, args.camera_helper_scale)
        debug_tree.write(debug_world_path, encoding="unicode")
        write_json(
            debug_summary_path,
            {
                "debug_world": project_rel(debug_world_path),
                "camera_count": debug_world_summary["camera_count"],
                "cameras": debug_world_summary["cameras"],
                "helper_geometry_count": debug_world_summary["helper_geometry_count"],
            },
        )

    if args.camera_tuning_world:
        if panoptic_tree is None:
            fail("--camera-tuning-world requires the primary panoptic world build path.")
        tuning_tree, tuning_world_summary = build_camera_tuning_world(
            panoptic_tree,
            cameras,
            native_raw_root,
            args.camera_helper_scale,
            "panoptic",
            "panoptic",
        )
        tuning_tree.write(tuning_world_path, encoding="unicode")
        write_json(
            tuning_summary_path,
            {
                "tuning_world": project_rel(tuning_world_path),
                "camera_count": tuning_world_summary["camera_count"],
                "cameras": tuning_world_summary["cameras"],
                "helper_geometry_count": tuning_world_summary["helper_geometry_count"],
            },
        )

    warnings = list(factory_shell_warnings)
    if panoptic_summary is not None:
        warnings.extend(panoptic_summary["warnings"])
    if stable_instance_summary is not None:
        warnings.extend(stable_instance_summary["warnings"])
    if semantic_summary is not None:
        warnings.extend(semantic_summary["warnings"])
    if instance_summary is not None:
        warnings.extend(instance_summary["warnings"])
    if panoptic_summary is not None:
        warnings.extend(
            f"Skipped/unmatched {item['entity']} {item['name']}: {item['reason']}"
            for item in panoptic_summary["skipped_unmatched_models"]
        )

        summary = {
            "primary_mode": "panoptic",
            "primary_world": project_rel(panoptic_world_path),
            "panoptic_world": project_rel(panoptic_world_path),
            "instance_label_map": project_rel(instance_label_map_path),
            "instance_label_map_role": "stable metadata/debug compact-instance lookup; not the primary panoptic instance encoding",
            "build_debug_split_worlds": bool(args.build_debug_split_worlds),
            "camera_count": panoptic_summary["camera_count"],
            "rgbd_enabled": panoptic_summary["rgbd_enabled"],
            "rgbd_sensor_count": panoptic_summary["rgbd_sensor_count"],
            "rgbd_output_root": panoptic_summary["rgbd_output_root"],
            "labeled_static_count": panoptic_summary["labeled_static_count"],
            "labeled_robot_count": panoptic_summary["labeled_robot_count"],
            "labeled_human_count": panoptic_summary["labeled_human_count"],
            "labeled_factory_shell_structural_count": panoptic_summary["labeled_factory_shell_structural_count"],
            "compact_instance_label_count": compact_instance_label_count,
            "max_compact_instance_label": max_compact_instance_label,
            "warnings": warnings,
            "skipped_unmatched_models": panoptic_summary["skipped_unmatched_models"],
            "legacy_split_world_debug_root": project_rel(split_world_debug_root),
            "debug_worlds": {},
        }
        if args.build_debug_split_worlds:
            summary["debug_worlds"]["semantic_world"] = project_rel(semantic_world_path)
            summary["debug_worlds"]["instance_world"] = project_rel(instance_world_path)
        if debug_world_path.exists():
            summary["debug_worlds"]["camera_debug_world"] = project_rel(debug_world_path)
        if tuning_world_path.exists():
            summary["debug_worlds"]["camera_tuning_world"] = project_rel(tuning_world_path)
        write_json(summary_path, summary)

    if stable_instance_summary is not None:
        stable_summary = {
            "primary_mode": "stable_instance_panoptic",
            "stable_instance_panoptic_world": project_rel(stable_instance_panoptic_world_path),
            "stable_instance_label_map": project_rel(stable_instance_label_map_path),
            "camera_count": stable_instance_summary["camera_count"],
            "rgbd_enabled": stable_instance_summary["rgbd_enabled"],
            "rgbd_sensor_count": stable_instance_summary["rgbd_sensor_count"],
            "rgbd_output_root": stable_instance_summary["rgbd_output_root"],
            "label_mode": "compact_stable_instance",
            "label_channel": "panoptic_rgb_channel_2",
            "gazebo_instance_count_encoding": "rgb[1] * 256 + rgb[0]",
            "gazebo_instance_count_is_stable_instance_id": False,
            "labeled_static_count": stable_instance_summary["labeled_static_count"],
            "labeled_robot_count": stable_instance_summary["labeled_robot_count"],
            "labeled_human_count": stable_instance_summary["labeled_human_count"],
            "labeled_factory_shell_structural_count": stable_instance_summary["labeled_factory_shell_structural_count"],
            "compact_instance_label_count": compact_instance_label_count,
            "max_compact_instance_label": max_compact_instance_label,
            "warnings": list(factory_shell_warnings) + stable_instance_summary["warnings"],
            "skipped_unmatched_models": stable_instance_summary["skipped_unmatched_models"],
        }
        write_json(stable_instance_summary_path, stable_summary)

    print(f"experiment_name={config.get('experiment_name', 'perception_rt_small_v0')}")
    print_summary = panoptic_summary or stable_instance_summary
    if panoptic_summary is not None:
        print("primary_mode=panoptic")
        print(f"primary_world={project_rel(panoptic_world_path)}")
        print(f"panoptic_world={project_rel(panoptic_world_path)}")
        print(f"instance_label_map={project_rel(instance_label_map_path)}")
        print(f"camera_count={panoptic_summary['camera_count']}")
    if stable_instance_summary is not None:
        print("stable_instance_mode=compact_stable_instance")
        print(f"stable_instance_panoptic_world={project_rel(stable_instance_panoptic_world_path)}")
        print(f"stable_instance_label_map={project_rel(stable_instance_label_map_path)}")
        print(f"stable_instance_camera_count={stable_instance_summary['camera_count']}")
    if print_summary is not None:
        print(f"rgbd_enabled={print_summary['rgbd_enabled']}")
        print(f"rgbd_sensor_count={print_summary['rgbd_sensor_count']}")
        print(f"labeled_static_count={print_summary['labeled_static_count']}")
        print(f"labeled_robot_count={print_summary['labeled_robot_count']}")
        print(f"labeled_human_count={print_summary['labeled_human_count']}")
        print(f"labeled_factory_shell_structural_count={print_summary['labeled_factory_shell_structural_count']}")
    print(f"compact_instance_label_count={compact_instance_label_count}")
    print(f"max_compact_instance_label={max_compact_instance_label}")
    if args.build_debug_split_worlds:
        print(f"semantic_world={project_rel(semantic_world_path)}")
        print(f"instance_world={project_rel(instance_world_path)}")
        print(f"legacy_split_world_debug_root={project_rel(split_world_debug_root)}")
    if args.debug_camera_visuals:
        print(f"debug_world={project_rel(debug_world_path)}")
        print(f"debug_world_summary={project_rel(debug_summary_path)}")
    if args.camera_tuning_world:
        print(f"tuning_world={project_rel(tuning_world_path)}")
        print(f"tuning_world_summary={project_rel(tuning_summary_path)}")
    print(f"warning_count={len(warnings)}")


if __name__ == "__main__":
    main()
