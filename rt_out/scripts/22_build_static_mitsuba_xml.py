#!/usr/bin/env python3
"""Build a Mitsuba XML scene from the merged static-scene outputs.

This script is mainly a renderer/debug companion to the RT flow: it reads the
same frozen static manifest and material assignments, then emits a Mitsuba scene
file that can be used to inspect geometry/material assumptions visually.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


DEBUG_COLORS = {
    "wood": "0.55, 0.34, 0.18",
    "metal": "0.62, 0.64, 0.67",
    "plastic": "0.30, 0.30, 0.35",
    "cardboard": "0.63, 0.50, 0.30",
    "textile": "0.20, 0.25, 0.45",
    "chipboard": "0.57, 0.42, 0.24",
    "human_skin": "0.72, 0.56, 0.50",
    "vinyl_tile": "0.40, 0.40, 0.42",
    "ceiling_board": "0.78, 0.78, 0.76",
    "panel_wall": "0.82, 0.84, 0.88",
    "glass": "0.72, 0.82, 0.92",
}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def slugify(text: str) -> str:
    out = []
    for ch in str(text):
        out.append(ch.lower() if ch.isalnum() else "_")
    slug = "".join(out)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "item"


def prettify(elem: ET.Element, level: int = 0) -> None:
    indent = "\n" + level * "    "
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = indent + "    "
        for child in elem:
            prettify(child, level + 1)
        if not elem[-1].tail or not elem[-1].tail.strip():
            elem[-1].tail = indent
    if level and (not elem.tail or not elem.tail.strip()):
        elem.tail = indent


def add_default_camera(
    scene: ET.Element,
    origin: str,
    target: str,
    up: str,
    width: int,
    height: int,
    spp: int,
) -> None:
    # Mitsuba output is primarily a visual debugging companion to the radio
    # pipeline, so provide a simple default camera/sampler when geometry-only
    # mode is not requested.
    sensor = ET.SubElement(scene, "sensor", {"type": "perspective"})
    transform = ET.SubElement(sensor, "transform", {"name": "to_world"})
    ET.SubElement(transform, "lookat", {"origin": origin, "target": target, "up": up})
    ET.SubElement(sensor, "float", {"name": "fov", "value": "45"})
    sampler = ET.SubElement(sensor, "sampler", {"type": "independent"})
    ET.SubElement(sampler, "integer", {"name": "sample_count", "value": str(spp)})
    film = ET.SubElement(sensor, "film", {"type": "hdrfilm"})
    ET.SubElement(film, "integer", {"name": "width", "value": str(width)})
    ET.SubElement(film, "integer", {"name": "height", "value": str(height)})


def add_bsdf(shape: ET.Element, material_class: str) -> None:
    # These are lightweight visual materials that mirror the semantic
    # radio-material groups, making grouping mistakes easy to spot in renders.
    if material_class == "glass":
        bsdf = ET.SubElement(shape, "bsdf", {"type": "dielectric"})
        ET.SubElement(bsdf, "string", {"name": "int_ior", "value": "bk7"})
        ET.SubElement(bsdf, "string", {"name": "ext_ior", "value": "air"})
        return

    twosided = ET.SubElement(shape, "bsdf", {"type": "twosided"})
    bsdf = ET.SubElement(twosided, "bsdf", {"type": "diffuse"})
    ET.SubElement(
        bsdf,
        "rgb",
        {
            "name": "reflectance",
            "value": DEBUG_COLORS.get(material_class, "0.60, 0.60, 0.60"),
        },
    )


def resolve_mesh_path(group: dict[str, Any], manifest_path: Path) -> Path:
    # Resolve merged mesh paths relative to the manifest so the whole static
    # export folder can be moved together without rewriting absolute paths.
    raw_path = group.get("merged_mesh_path")
    if not raw_path:
        raise ValueError(
            f"Merged group {group.get('material_class', '<unknown>')} is missing merged_mesh_path"
        )

    mesh_path = Path(str(raw_path)).expanduser()
    if not mesh_path.is_absolute():
        mesh_path = (manifest_path.parent / mesh_path).resolve()
    else:
        mesh_path = mesh_path.resolve()

    if not mesh_path.exists():
        raise FileNotFoundError(f"Merged mesh file does not exist: {mesh_path}")
    return mesh_path


def mesh_path_for_xml(mesh_path: Path, xml_parent: Path) -> str:
    # Prefer relative mesh references inside the XML so the export remains
    # portable between machines and experiment directories.
    try:
        return os.path.relpath(mesh_path, xml_parent)
    except ValueError:
        return str(mesh_path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a basic Mitsuba 3 XML scene from merged static geometry."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Path to merged_static_manifest.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output XML path",
    )
    parser.add_argument(
        "--geometry-only",
        action="store_true",
        help="Write only mesh shapes without camera, emitter, or integrator",
    )
    parser.add_argument("--camera-origin", default="12, 12, 8")
    parser.add_argument("--camera-target", default="0, 0, 1")
    parser.add_argument("--camera-up", default="0, 0, 1")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--spp", type=int, default=16)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Default to the frozen merged static manifest used by the validated
    # pipeline, but still allow explicit overrides for debugging.
    if args.manifest is None:
        root = Path(__file__).resolve().parents[2]
        manifest_path = root / "rt_out" / "static_scene" / "export" / "merged_static_manifest.json"
    else:
        manifest_path = args.manifest.expanduser().resolve()

    data = load_json(manifest_path)
    if not isinstance(data, dict):
        raise ValueError("merged_static_manifest.json must contain a JSON object")

    hard_errors = data.get("hard_errors", [])
    if hard_errors:
        raise RuntimeError(
            f"merged_static_manifest.json contains hard errors: {json.dumps(hard_errors, indent=2)}"
        )

    groups = data.get("merged_groups")
    if not isinstance(groups, list):
        raise ValueError("merged_static_manifest.json must contain merged_groups list")

    if args.output is None:
        output_path = manifest_path.parent / "static_scene_mitsuba.xml"
    else:
        output_path = args.output.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Build a minimal Mitsuba scene around the merged material groups. The
    # geometry matches the static Sionna scene, but the purpose here is visual
    # inspection of geometry and material grouping rather than RT itself.
    scene = ET.Element("scene", {"version": "3.0.0"})
    if not args.geometry_only:
        integrator = ET.SubElement(scene, "integrator", {"type": "path"})
        ET.SubElement(integrator, "integer", {"name": "max_depth", "value": "8"})
        add_default_camera(
            scene,
            args.camera_origin,
            args.camera_target,
            args.camera_up,
            args.width,
            args.height,
            args.spp,
        )
        ET.SubElement(scene, "emitter", {"type": "constant"})

    seen_materials: set[str] = set()
    for raw_group in groups:
        # Emit exactly one shape per merged material bucket so the Mitsuba scene
        # mirrors the frozen static baseline produced by the Blender merge step.
        if not isinstance(raw_group, dict):
            raise ValueError("Each merged group must be an object")

        material_class = str(raw_group.get("material_class", "")).strip()
        if not material_class:
            raise ValueError("Merged group is missing material_class")
        if material_class in seen_materials:
            raise ValueError(f"Duplicate material_class in merged manifest: {material_class}")
        seen_materials.add(material_class)

        mesh_path = resolve_mesh_path(raw_group, manifest_path)
        shape = ET.SubElement(
            scene,
            "shape",
            {
                "type": "ply",
                "id": f"merged_{slugify(material_class)}",
            },
        )
        ET.SubElement(
            shape,
            "string",
            {
                "name": "filename",
                "value": mesh_path_for_xml(mesh_path, output_path.parent),
            },
        )
        add_bsdf(shape, material_class)

    prettify(scene)
    tree = ET.ElementTree(scene)
    tree.write(output_path, encoding="utf-8", xml_declaration=False)

    print(f"Saved Mitsuba XML: {output_path}")
    print(f"Material groups   : {len(groups)}")


if __name__ == "__main__":
    main()
