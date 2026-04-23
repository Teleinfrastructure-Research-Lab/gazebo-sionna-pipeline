import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np

from dynamic_prototype_config import load_dynamic_prototype_config

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROTOTYPE_CONFIG = load_dynamic_prototype_config(PROJECT_ROOT / "rt_out" / "config" / "dynamic_prototype_config.json")

root_dir = PROJECT_ROOT
sdf_path = root_dir / "myworld_rt.sdf"
models_dir = root_dir / "models"

dynamic_models = set(PROTOTYPE_CONFIG["model_names"])

# --------------------------------------------------
# Pose helpers
# --------------------------------------------------

def pose_str_to_list(pose_str: str):
    vals = [float(x) for x in pose_str.strip().split()]
    if len(vals) != 6:
        raise ValueError(f"Expected 6 pose values, got {len(vals)} from: {pose_str}")
    return vals

def pose_list_to_matrix(p):
    x, y, z, roll, pitch, yaw = p

    cx, sx = math.cos(roll), math.sin(roll)
    cy, sy = math.cos(pitch), math.sin(pitch)
    cz, sz = math.cos(yaw), math.sin(yaw)

    # R = Rz(yaw) @ Ry(pitch) @ Rx(roll)
    Rz = np.array([[cz, -sz, 0],
                   [sz,  cz, 0],
                   [ 0,   0, 1]])
    Ry = np.array([[ cy, 0, sy],
                   [  0, 1,  0],
                   [-sy, 0, cy]])
    Rx = np.array([[1,  0,   0],
                   [0, cx, -sx],
                   [0, sx,  cx]])

    R = Rz @ Ry @ Rx

    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = [x, y, z]
    return T

def matrix_to_pose_list(T):
    x, y, z = T[:3, 3]
    R = T[:3, :3]

    # Recover roll, pitch, yaw from R = Rz Ry Rx
    sy = -R[2, 0]
    cy = math.sqrt(max(0.0, 1 - sy * sy))

    singular = cy < 1e-9
    if not singular:
        roll = math.atan2(R[2, 1], R[2, 2])
        pitch = math.asin(sy)
        yaw = math.atan2(R[1, 0], R[0, 0])
    else:
        roll = math.atan2(-R[1, 2], R[1, 1])
        pitch = math.asin(sy)
        yaw = 0.0

    return [x, y, z, roll, pitch, yaw]

def compose_pose_strings(parent_pose: str, child_pose: str) -> str:
    Tp = pose_list_to_matrix(pose_str_to_list(parent_pose))
    Tc = pose_list_to_matrix(pose_str_to_list(child_pose))
    Tout = Tp @ Tc
    vals = matrix_to_pose_list(Tout)
    return " ".join(f"{v:.15g}" for v in vals)

ZERO_POSE = "0 0 0 0 0 0"

# --------------------------------------------------
# Geometry extraction
# --------------------------------------------------

def extract_visual_geometry(visual):
    visual_pose = visual.findtext("pose", default=ZERO_POSE).strip()

    mesh_uri = visual.findtext("./geometry/mesh/uri")
    if mesh_uri:
        scale = visual.findtext("./geometry/mesh/scale", default="1 1 1").strip()
        return {
            "visual_name": visual.get("name"),
            "visual_pose": visual_pose,
            "geometry_type": "mesh",
            "uri": mesh_uri.strip(),
            "scale": scale
        }

    box_size = visual.findtext("./geometry/box/size")
    if box_size:
        return {
            "visual_name": visual.get("name"),
            "visual_pose": visual_pose,
            "geometry_type": "box",
            "size": box_size.strip()
        }

    cylinder_radius = visual.findtext("./geometry/cylinder/radius")
    cylinder_length = visual.findtext("./geometry/cylinder/length")
    if cylinder_radius and cylinder_length:
        return {
            "visual_name": visual.get("name"),
            "visual_pose": visual_pose,
            "geometry_type": "cylinder",
            "radius": float(cylinder_radius),
            "length": float(cylinder_length)
        }

    sphere_radius = visual.findtext("./geometry/sphere/radius")
    if sphere_radius:
        return {
            "visual_name": visual.get("name"),
            "visual_pose": visual_pose,
            "geometry_type": "sphere",
            "radius": float(sphere_radius)
        }

    return None

# --------------------------------------------------
# SDF model parsing
# --------------------------------------------------

def resolve_model_sdf(uri: str) -> Path | None:
    if not uri.startswith("model://"):
        return None
    rel = uri[len("model://"):]
    model_name = rel.split("/")[0]
    candidate = models_dir / model_name / "model.sdf"
    return candidate if candidate.exists() else None

def collect_links_recursive(model_elem, parent_pose=ZERO_POSE, scope=""):
    """
    Returns flattened links from this model and nested models.
    link_pose is composed relative to the top-level model root.
    """
    links_out = []

    this_model_pose = model_elem.findtext("pose", default=ZERO_POSE).strip()
    accumulated_model_pose = compose_pose_strings(parent_pose, this_model_pose)

    model_name = model_elem.get("name", "")
    scope_prefix = f"{scope}::{model_name}" if scope and model_name else (model_name if model_name else scope)

    # Direct links of this model
    for link in model_elem.findall("link"):
        link_name = link.get("name")
        link_pose_local = link.findtext("pose", default=ZERO_POSE).strip()
        link_pose_composed = compose_pose_strings(accumulated_model_pose, link_pose_local)

        visuals = []
        for visual in link.findall("visual"):
            geom = extract_visual_geometry(visual)
            if geom:
                visuals.append(geom)

        links_out.append({
            "link": f"{scope_prefix}::{link_name}" if scope_prefix else link_name,
            "link_pose": link_pose_composed,
            "visuals": visuals
        })

    # Nested submodels
    for submodel in model_elem.findall("model"):
        links_out.extend(
            collect_links_recursive(
                submodel,
                parent_pose=accumulated_model_pose,
                scope=scope_prefix
            )
        )

    return links_out

def build_model_entry_from_world_model(model_elem):
    model_name = model_elem.get("name")
    model_pose = model_elem.findtext("pose", default=ZERO_POSE).strip()
    is_static = model_elem.findtext("static", default="false").strip().lower() == "true"

    entry = {
        "model": model_name,
        "model_pose": model_pose,
        "static": is_static,
        "links": []
    }

    # direct links
    for link in model_elem.findall("link"):
        link_name = link.get("name")
        link_pose = link.findtext("pose", default=ZERO_POSE).strip()

        visuals = []
        for visual in link.findall("visual"):
            geom = extract_visual_geometry(visual)
            if geom:
                visuals.append(geom)

        entry["links"].append({
            "link": link_name,
            "link_pose": link_pose,
            "visuals": visuals
        })

    # nested submodels inside a world model, if any
    for submodel in model_elem.findall("model"):
        entry["links"].extend(
            collect_links_recursive(submodel, parent_pose=ZERO_POSE, scope="")
        )

    return entry

def build_model_entry_from_include(include_elem):
    include_name = include_elem.findtext("name")
    include_uri = include_elem.findtext("uri")
    include_pose = include_elem.findtext("pose", default=ZERO_POSE).strip()

    if not include_name or not include_uri:
        return None

    model_sdf_path = resolve_model_sdf(include_uri.strip())
    if model_sdf_path is None:
        print(f"[WARN] Could not resolve include URI: {include_uri}")
        return None

    model_tree = ET.parse(model_sdf_path)
    model_root = model_tree.getroot()
    model_elem = model_root.find("model")
    if model_elem is None:
        print(f"[WARN] No <model> in {model_sdf_path}")
        return None

    is_static = model_elem.findtext("static", default="true").strip().lower() == "true"

    entry = {
        "model": include_name.strip(),
        "model_pose": include_pose,
        "static": is_static,
        "source_type": "include",
        "source_uri": include_uri.strip(),
        "links": []
    }

    # direct links of included model
    for link in model_elem.findall("link"):
        link_name = link.get("name")
        link_pose = link.findtext("pose", default=ZERO_POSE).strip()

        visuals = []
        for visual in link.findall("visual"):
            geom = extract_visual_geometry(visual)
            if geom:
                visuals.append(geom)

        entry["links"].append({
            "link": link_name,
            "link_pose": link_pose,
            "visuals": visuals
        })

    # nested models of included model, for example factory_floor, north_wall, etc.
    for submodel in model_elem.findall("model"):
        entry["links"].extend(
            collect_links_recursive(submodel, parent_pose=ZERO_POSE, scope="")
        )

    return entry

# --------------------------------------------------
# Main
# --------------------------------------------------

tree = ET.parse(sdf_path)
root = tree.getroot()
world = root.find("world")

static_manifest = []
dynamic_manifest = []

# World <model>
for model in world.findall("model"):
    model_entry = build_model_entry_from_world_model(model)
    if model_entry["model"] in dynamic_models:
        dynamic_manifest.append(model_entry)
    else:
        static_manifest.append(model_entry)

# World <include>
for include in world.findall("include"):
    model_entry = build_model_entry_from_include(include)
    if model_entry is None:
        continue

    if model_entry["model"] in dynamic_models:
        dynamic_manifest.append(model_entry)
    else:
        static_manifest.append(model_entry)

out_dir = root_dir / "rt_out/manifests"
out_dir.mkdir(parents=True, exist_ok=True)

static_path = out_dir / "static_manifest.json"
dynamic_path = out_dir / "dynamic_manifest.json"

static_path.write_text(json.dumps(static_manifest, indent=2), encoding="utf-8")
dynamic_path.write_text(json.dumps(dynamic_manifest, indent=2), encoding="utf-8")

print("Saved:")
print(static_path)
print(dynamic_path)
