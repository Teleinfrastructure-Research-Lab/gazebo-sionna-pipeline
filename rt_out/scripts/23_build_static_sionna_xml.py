#!/usr/bin/env python3
"""Build a static-only Sionna XML scene from the merged static manifest.

This is the radio-facing XML emitter for the frozen baseline scene. It maps the
project's semantic material classes onto Sionna radio materials and writes the
static scene file used by sanity runs and later frame composition stages.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

from rt_material_config import RtMaterialSpec, add_radio_material_xml, load_rt_material_specs


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


def resolve_mesh_path(group: dict[str, Any], manifest_path: Path) -> Path:
    # Resolve merged mesh paths relative to the manifest so the static scene can
    # be copied together with its exported assets.
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
    # Prefer relative paths in the XML because the static export folder is often
    # moved intact into experiment-specific directories.
    try:
        return os.path.relpath(mesh_path, xml_parent)
    except ValueError:
        return str(mesh_path)


def add_shape(
    scene: ET.Element,
    *,
    material_class: str,
    mesh_path: Path,
    xml_parent: Path,
    material_id: str,
) -> None:
    # Each merged static material group becomes one Sionna shape that simply
    # references a previously declared radio material by id.
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
            "value": mesh_path_for_xml(mesh_path, xml_parent),
        },
    )
    ET.SubElement(shape, "ref", {"name": "bsdf", "id": material_id})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a Sionna RT XML scene from merged static geometry."
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
        help="Output Sionna XML path",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Default to the frozen merged static manifest, which is the validated
    # baseline reused by every later dynamic composition stage.
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
        output_path = manifest_path.parent / "static_scene_sionna.xml"
    else:
        output_path = args.output.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    seen_materials: set[str] = set()
    material_specs = load_rt_material_specs()
    used_radio_materials: dict[str, RtMaterialSpec] = {}
    shape_records: list[tuple[str, Path, str]] = []

    # First validate every merged material bucket and collect which radio
    # materials are actually needed in this scene.
    for raw_group in groups:
        if not isinstance(raw_group, dict):
            raise ValueError("Each merged group must be an object")

        material_class = str(raw_group.get("material_class", "")).strip()
        if not material_class:
            raise ValueError("Merged group is missing material_class")
        if material_class in seen_materials:
            raise ValueError(f"Duplicate material_class in merged manifest: {material_class}")
        seen_materials.add(material_class)

        material_spec = material_specs.get(material_class)
        if material_spec is None:
            known = ", ".join(sorted(material_specs))
            raise ValueError(
                f"No Sionna radio-material mapping for material_class={material_class!r}. "
                f"Known classes: {known}"
            )

        mesh_path = resolve_mesh_path(raw_group, manifest_path)
        material_id = material_spec.default_material_id
        used_radio_materials[material_id] = material_spec
        shape_records.append((material_class, mesh_path, material_id))

    scene = ET.Element("scene", {"version": "3.0.0"})
    # Declare radio materials before shapes so each mesh can attach to one of
    # the shared electromagnetic material definitions.
    for material_id, material_spec in sorted(used_radio_materials.items()):
        add_radio_material_xml(scene, material_spec, material_id=material_id)

    # Then emit one mesh shape per merged static group, preserving the semantic
    # material partition established by the static merge stage.
    for material_class, mesh_path, material_id in shape_records:
        add_shape(
            scene,
            material_class=material_class,
            mesh_path=mesh_path,
            xml_parent=output_path.parent,
            material_id=material_id,
        )

    prettify(scene)
    ET.ElementTree(scene).write(output_path, encoding="utf-8", xml_declaration=False)

    print(f"Saved Sionna XML: {output_path}")
    print(f"Material groups : {len(shape_records)}")
    print(f"Radio materials : {len(used_radio_materials)}")
    print("Mapping:")
    for material_class in sorted(seen_materials):
        spec = material_specs[material_class]
        if spec.model == "itu":
            detail = f"itu_type={spec.itu_type}, thickness={spec.thickness:g}"
        else:
            detail = (
                f"custom eps_r={spec.relative_permittivity:g}, "
                f"sigma={spec.conductivity:g}, thickness={spec.thickness:g}"
            )
        print(f"  {material_class:14s} -> {spec.default_material_id} ({detail})")


if __name__ == "__main__":
    main()
