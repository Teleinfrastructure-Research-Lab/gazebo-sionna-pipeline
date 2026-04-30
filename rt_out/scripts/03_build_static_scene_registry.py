"""Filter the geometry registry down to merge-ready static scene records.

The goal here is to keep only frozen renderable geometry, assign semantic
material classes from the project rules, and write the normalized static
registry that drives material-wise static mesh merging.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = ROOT / "rt_out/manifests/geometry_registry.json"
MATERIAL_MAP_PATH = ROOT / "rt_out/materials/material_map.json"
OUTPUT_PATH = ROOT / "rt_out/manifests/static_registry.json"

SUPPORTED_GEOMETRY = {"mesh", "box", "sphere", "cylinder"}
MESH_EXTENSIONS = {".ply", ".obj", ".dae", ".stl", ".glb"}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def safe_str(x: Any) -> str:
    return "" if x is None else str(x)


def slugify(text: str) -> str:
    allowed = []
    for ch in text:
        if ch.isalnum():
            allowed.append(ch.lower())
        else:
            allowed.append("_")
    slug = "".join(allowed)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "item"


def pose6_to_matrix(pose: List[float]) -> List[List[float]]:
    """Convert xyz+rpy into a 4x4 transform for static-scene baking."""
    import math

    if len(pose) != 6:
        raise ValueError(f"Expected pose with 6 elements, got {pose}")
    x, y, z, roll, pitch, yaw = pose

    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)

    # ZYX = yaw-pitch-roll
    r00 = cy * cp
    r01 = cy * sp * sr - sy * cr
    r02 = cy * sp * cr + sy * sr

    r10 = sy * cp
    r11 = sy * sp * sr + cy * cr
    r12 = sy * sp * cr - cy * sr

    r20 = -sp
    r21 = cp * sr
    r22 = cp * cr

    return [
        [r00, r01, r02, x],
        [r10, r11, r12, y],
        [r20, r21, r22, z],
        [0.0, 0.0, 0.0, 1.0],
    ]


def matmul4(a: List[List[float]], b: List[List[float]]) -> List[List[float]]:
    out = [[0.0] * 4 for _ in range(4)]
    for i in range(4):
        for j in range(4):
            out[i][j] = sum(a[i][k] * b[k][j] for k in range(4))
    return out


def diagonal_scale(scale: List[float]) -> List[List[float]]:
    sx, sy, sz = scale
    return [
        [sx, 0.0, 0.0, 0.0],
        [0.0, sy, 0.0, 0.0],
        [0.0, 0.0, sz, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def normalize_pose(raw_pose: Any) -> List[float]:
    if raw_pose is None:
        return [0.0] * 6
    if isinstance(raw_pose, list) and len(raw_pose) == 6:
        return [float(v) for v in raw_pose]
    raise ValueError(f"Unsupported pose format: {raw_pose}")


def load_material_rules(path: Path) -> Dict[str, Any]:
    """Load semantic material rules used by the frozen static baseline."""
    data = load_json(path)
    if not isinstance(data, dict):
        raise ValueError("material_map.json must be an object")

    # Preferred schema: explicit rule objects with match type, pattern, and
    # resulting semantic material class.
    # {
    #   "default_material": "composite",
    #   "model_rules": [
    #     {"match_type": "contains", "pattern": "floor_visual", "material": "vinyl_tile"}
    #   ]
    # }
    if "model_rules" in data:
        return data

    # Fallback schema: simple exact-name to material mappings.
    # {"factory_shell": "panel_wall", "person_standing": "human_skin"}
    return {
        "default_material": data.get("default_material", "composite"),
        "model_rules": [
            {"match_type": "exact", "pattern": k, "material": v}
            for k, v in data.items()
            if k != "default_material"
        ],
    }


def pick_material(match_text: str, rules: Dict[str, Any]) -> str:
    """Map model/link/visual names onto the project's semantic material class."""
    default_material = rules.get("default_material", "composite")
    model_rules = rules.get("model_rules", [])

    match_text_lower = match_text.lower()

    for rule in model_rules:
        match_type = safe_str(rule.get("match_type", "exact")).lower()
        pattern = safe_str(rule.get("pattern"))
        material = safe_str(rule.get("material"))

        if not pattern or not material:
            continue

        pattern_lower = pattern.lower()

        if match_type == "exact" and match_text == pattern:
            return material
        if match_type == "contains" and pattern_lower in match_text_lower:
            return material
        if match_type == "startswith" and match_text_lower.startswith(pattern_lower):
            return material

    return default_material


def build_converted_mesh_path(src_path: Path, root: Path) -> Path:
    try:
        rel = src_path.relative_to(root)
    except ValueError:
        rel = Path(src_path.name)
    return root / "rt_out/static_scene/converted_meshes" / rel.with_suffix(".ply")


def record_status_for_mesh(src_path: Optional[Path], dst_path: Optional[Path]) -> str:
    if src_path is None:
        return "missing_source_path"
    if src_path.suffix.lower() not in MESH_EXTENSIONS:
        return "unsupported_mesh_extension"
    if dst_path is None:
        return "missing_target_path"
    if src_path.suffix.lower() in {".ply", ".obj"} and src_path.exists():
        return "ready"
    return "ready" if dst_path.exists() else "missing_converted_mesh"


def build_entry(raw: Dict[str, Any], material_rules: Dict[str, Any], root: Path) -> Optional[Dict[str, Any]]:
    """Convert one geometry-registry row into a merge-ready static record.

    The final world transform here follows the validated static transform chain:
    model_to_world * link_pose * visual_pose * scale.
    """
    geometry_type = safe_str(raw.get("geometry_type")).lower()
    model_name = safe_str(raw.get("model_name"))
    link_name = safe_str(raw.get("link_name"))
    visual_name = safe_str(raw.get("visual_name"))

    model_pose = normalize_pose(raw.get("model_pose"))
    link_pose = normalize_pose(raw.get("link_pose"))
    visual_pose = normalize_pose(raw.get("visual_pose"))
    scale = [float(v) for v in raw.get("scale", [1.0, 1.0, 1.0])]

    t_model = pose6_to_matrix(model_pose)
    t_link = pose6_to_matrix(link_pose)
    t_visual = pose6_to_matrix(visual_pose)
    t_scale = diagonal_scale(scale)
    to_world = matmul4(matmul4(matmul4(t_model, t_link), t_visual), t_scale)

    # Match by model, link, and visual together so scene-specific rules can
    # distinguish different parts inside the same Gazebo model.
    match_text = " | ".join([model_name, link_name, visual_name])
    material_class = pick_material(match_text, material_rules)

    # Some rules intentionally remove geometry from the frozen static baseline.
    if material_class == "__skip__":
        return None

    entry: Dict[str, Any] = {
        "id": slugify(f"{model_name}__{link_name}__{visual_name}"),
        "model_name": model_name,
        "link_name": link_name,
        "visual_name": visual_name,
        "geometry_type": geometry_type,
        "static": True,
        "source_manifest": raw.get("source_manifest", "static_manifest"),
        "material_class": material_class,
        "model_pose": model_pose,
        "link_pose": link_pose,
        "visual_pose": visual_pose,
        "scale": scale,
        "to_world": to_world,
        "merge_group": None,
        "status": "unknown",
        "notes": [],
    }

    if geometry_type == "mesh":
        resolved_path = raw.get("resolved_path")
        src_path = Path(resolved_path) if resolved_path else None
        dst_path = build_converted_mesh_path(src_path, root) if src_path else None

        entry.update(
            {
                "uri": raw.get("uri"),
                "resolved_path": str(src_path) if src_path else None,
                "scene_mesh_path": str(dst_path) if dst_path else None,
                "mesh_extension": src_path.suffix.lower() if src_path else None,
                "status": record_status_for_mesh(src_path, dst_path),
            }
        )

        # Reuse already-renderable mesh formats directly when possible so the
        # static merge stage does not depend on an extra conversion output.
        if src_path and src_path.suffix.lower() in {".ply", ".obj"} and src_path.exists():
            entry["scene_mesh_path"] = str(src_path)

        if entry["status"] != "ready":
            entry["notes"].append(f"Mesh not ready: {entry['status']}")

    elif geometry_type == "box":
        entry["size"] = [float(v) for v in raw.get("size", [1.0, 1.0, 1.0])]
        entry["status"] = "ready"

    elif geometry_type == "cylinder":
        entry["radius"] = float(raw.get("radius", 0.0))
        entry["length"] = float(raw.get("length", 0.0))
        entry["status"] = "ready"

    elif geometry_type == "sphere":
        entry["radius"] = float(raw.get("radius", 0.0))
        entry["status"] = "ready"

    else:
        entry["status"] = "unsupported_geometry"
        entry["notes"].append(f"Unsupported geometry_type={geometry_type}")

    return entry


def build_static_registry(root: Path, registry_path: Path, material_map_path: Path) -> Dict[str, Any]:
    """Filter the geometry registry down to ready static records plus summary."""
    raw_registry = load_json(registry_path)
    material_rules = load_material_rules(material_map_path)

    if not isinstance(raw_registry, list):
        raise ValueError("geometry_registry.json must contain a list of entries")

    entries: List[Dict[str, Any]] = []
    summary = {
        "total_input_records": 0,
        "total_static_records": 0,
        "kept_records": 0,
        "skipped_non_static": 0,
        "skipped_unsupported_geometry": 0,
        "skipped_by_rule": 0,
        "ready": 0,
        "missing_converted_mesh": 0,
        "unsupported_mesh_extension": 0,
        "missing_source_path": 0,
        "missing_target_path": 0,
        "by_geometry_type": {},
        "by_material_class": {},
    }

    for raw in raw_registry:
        summary["total_input_records"] += 1

        if not raw.get("static", False):
            summary["skipped_non_static"] += 1
            continue

        summary["total_static_records"] += 1

        geometry_type = safe_str(raw.get("geometry_type")).lower()
        if geometry_type not in SUPPORTED_GEOMETRY:
            summary["skipped_unsupported_geometry"] += 1
            continue

        entry = build_entry(raw, material_rules, root)
        if entry is None:
            summary["skipped_by_rule"] += 1
            continue

        entries.append(entry)
        summary["kept_records"] += 1

        summary["by_geometry_type"][geometry_type] = summary["by_geometry_type"].get(geometry_type, 0) + 1

        mat = entry["material_class"]
        summary["by_material_class"][mat] = summary["by_material_class"].get(mat, 0) + 1

        status = entry["status"]
        summary[status] = summary.get(status, 0) + 1

    return {
        "root": str(root),
        "inputs": {
            "geometry_registry": str(registry_path),
            "material_map": str(material_map_path),
        },
        "summary": summary,
        "entries": entries,
    }


def main() -> None:
    """Write the static registry that drives the material-wise merge stage."""
    registry = build_static_registry(ROOT, REGISTRY_PATH, MATERIAL_MAP_PATH)
    save_json(OUTPUT_PATH, registry)
    s = registry["summary"]

    print(f"Saved: {OUTPUT_PATH}")
    print(f"Input records: {s['total_input_records']}")
    print(f"Static records: {s['total_static_records']}")
    print(f"Kept records: {s['kept_records']}")
    print(f"Skipped by rule: {s.get('skipped_by_rule', 0)}")
    print(f"Ready: {s.get('ready', 0)}")
    print(f"Missing converted mesh: {s.get('missing_converted_mesh', 0)}")
    print(f"Unsupported mesh extension: {s.get('unsupported_mesh_extension', 0)}")
    print(f"Missing source path: {s.get('missing_source_path', 0)}")
    print(f"Missing target path: {s.get('missing_target_path', 0)}")


if __name__ == "__main__":
    main()
