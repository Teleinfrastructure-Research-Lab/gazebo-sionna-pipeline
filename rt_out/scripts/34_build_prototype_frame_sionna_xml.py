#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dynamic_prototype_config import load_dynamic_prototype_config
from rt_material_config import RtMaterialSpec, add_radio_material_xml, load_rt_material_specs


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COMPOSED_SCENE_ROOT = PROJECT_ROOT / "rt_out" / "composed_scene"

PROTOTYPE_CONFIG = load_dynamic_prototype_config()
DYNAMIC_MODEL_MATERIALS = {
    model_name: model_config["forced_material"]
    for model_name, model_config in PROTOTYPE_CONFIG["dynamic_models"].items()
}
ALLOWED_DYNAMIC_MODELS = set(DYNAMIC_MODEL_MATERIALS)


@dataclass(frozen=True)
class XmlConfig:
    frame_id: int
    input_manifest_path: Path
    output_xml_path: Path


class FrameSionnaXmlError(RuntimeError):
    pass


def frame_dir_name(frame_id: int) -> str:
    return f"frame_{frame_id:03d}"


def default_input_manifest_path(frame_id: int) -> Path:
    return (
        DEFAULT_COMPOSED_SCENE_ROOT
        / frame_dir_name(frame_id)
        / f"composed_frame_{frame_id:03d}_manifest.json"
    )


def default_output_xml_path(frame_id: int) -> Path:
    return (
        DEFAULT_COMPOSED_SCENE_ROOT
        / frame_dir_name(frame_id)
        / f"frame_{frame_id:03d}_sionna.xml"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a Sionna RT XML scene for one composed prototype frame."
    )
    parser.add_argument("--frame-id", type=int, default=0, help="Prototype frame id to emit")
    parser.add_argument(
        "--input-manifest",
        type=Path,
        default=None,
        help="composed_frame_XXX_manifest.json path",
    )
    parser.add_argument(
        "--output-xml",
        type=Path,
        default=None,
        help="Output frame_XXX_sionna.xml path",
    )
    return parser.parse_args()


def build_config(args: argparse.Namespace) -> XmlConfig:
    input_manifest_path = (
        default_input_manifest_path(args.frame_id)
        if args.input_manifest is None
        else args.input_manifest
    )
    output_xml_path = default_output_xml_path(args.frame_id) if args.output_xml is None else args.output_xml
    return XmlConfig(
        frame_id=args.frame_id,
        input_manifest_path=input_manifest_path.expanduser().resolve(),
        output_xml_path=output_xml_path.expanduser().resolve(),
    )


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise FrameSionnaXmlError(f"Missing input manifest: {path}") from exc
    except json.JSONDecodeError as exc:
        raise FrameSionnaXmlError(f"Invalid JSON in {path}: {exc}") from exc


def slugify(text: Any) -> str:
    chars = []
    for ch in str(text):
        chars.append(ch.lower() if ch.isalnum() else "_")
    slug = "".join(chars)
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


def mesh_path_for_xml(mesh_path: Path, xml_parent: Path) -> str:
    try:
        return os.path.relpath(mesh_path, xml_parent)
    except ValueError:
        return str(mesh_path)


def material_bsdf_id(material_class: str, frame_id: int) -> str:
    return f"mat-frame{frame_id}_{slugify(material_class)}"


def add_shape(scene: ET.Element, entry: dict[str, Any], xml_parent: Path, *, frame_id: int) -> None:
    material_class = entry["material_label_resolved"]
    shape = ET.SubElement(
        scene,
        "shape",
        {
            "type": "ply",
            "id": f"shape_{slugify(entry['id'])}",
        },
    )
    ET.SubElement(
        shape,
        "string",
        {
            "name": "filename",
            "value": mesh_path_for_xml(Path(entry["mesh_path"]), xml_parent),
        },
    )
    ET.SubElement(shape, "ref", {"name": "bsdf", "id": material_bsdf_id(material_class, frame_id)})


def require_non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FrameSionnaXmlError(f"{label} must be a non-empty string")
    return value.strip()


def resolve_entry_material(entry: dict[str, Any], warnings: list[str]) -> str:
    source = entry.get("source")
    entry_id = entry.get("id")

    if source == "static":
        return require_non_empty_string(entry.get("material_label"), f"Static entry {entry_id}.material_label")

    if source == "dynamic":
        model_name = entry.get("model_name")
        if model_name not in ALLOWED_DYNAMIC_MODELS:
            raise FrameSionnaXmlError(
                f"Dynamic entry {entry_id} has unsupported model_name={model_name!r}"
            )
        forced_material = DYNAMIC_MODEL_MATERIALS[model_name]
        original_label = entry.get("material_label")
        if original_label not in (None, "", forced_material):
            warnings.append(
                f"Dynamic entry {entry_id} had material_label={original_label!r}; "
                f"forced to {forced_material!r}"
            )
        return forced_material

    raise FrameSionnaXmlError(f"Entry {entry_id} has unsupported source={source!r}")


def validate_and_resolve_entries(
    data: dict[str, Any],
    *,
    frame_id: int,
    material_specs: dict[str, RtMaterialSpec],
) -> tuple[list[dict[str, Any]], list[str]]:
    if data.get("frame_id") != frame_id:
        raise FrameSionnaXmlError(f"frame_id={data.get('frame_id')}, expected {frame_id}")

    source_sample_index = data.get("source_sample_index")
    if not isinstance(source_sample_index, int):
        raise FrameSionnaXmlError(
            f"source_sample_index must be an integer, got {source_sample_index!r}"
        )

    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        raise FrameSionnaXmlError("Manifest entries must be a non-empty list")

    total_count = data.get("total_count")
    if not isinstance(total_count, int):
        raise FrameSionnaXmlError(f"total_count must be an integer, got {total_count!r}")
    if total_count != len(entries):
        raise FrameSionnaXmlError(f"total_count={total_count}, but len(entries)={len(entries)}")

    static_count = data.get("static_count")
    dynamic_count = data.get("dynamic_count")
    if not isinstance(static_count, int):
        raise FrameSionnaXmlError(f"static_count must be an integer, got {static_count!r}")
    if not isinstance(dynamic_count, int):
        raise FrameSionnaXmlError(f"dynamic_count must be an integer, got {dynamic_count!r}")
    if static_count + dynamic_count != total_count:
        raise FrameSionnaXmlError(
            f"static_count + dynamic_count = {static_count + dynamic_count}, "
            f"but total_count={total_count}"
        )

    warnings: list[str] = []
    resolved_entries: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for index, raw_entry in enumerate(entries):
        if not isinstance(raw_entry, dict):
            raise FrameSionnaXmlError(f"entries[{index}] must be an object")

        entry_id = require_non_empty_string(raw_entry.get("id"), f"entries[{index}].id")
        if entry_id in seen_ids:
            raise FrameSionnaXmlError(f"Duplicate entry id: {entry_id}")
        seen_ids.add(entry_id)

        require_non_empty_string(raw_entry.get("source"), f"Entry {entry_id}.source")
        mesh_path = Path(require_non_empty_string(raw_entry.get("mesh_path"), f"Entry {entry_id}.mesh_path"))
        if not mesh_path.is_absolute():
            mesh_path = PROJECT_ROOT / mesh_path
        mesh_path = mesh_path.resolve()
        if not mesh_path.exists():
            raise FrameSionnaXmlError(f"Entry {entry_id} mesh_path does not exist: {mesh_path}")

        if raw_entry.get("baked_world_geometry") is not True:
            raise FrameSionnaXmlError(f"Entry {entry_id} must have baked_world_geometry == true")

        material_class = resolve_entry_material(raw_entry, warnings)
        if material_class not in material_specs:
            known = ", ".join(sorted(material_specs))
            raise FrameSionnaXmlError(
                f"No Sionna radio-material mapping for material_class={material_class!r}. "
                f"Known classes: {known}"
            )

        entry = dict(raw_entry)
        entry["mesh_path"] = str(mesh_path)
        entry["material_label_resolved"] = material_class
        resolved_entries.append(entry)

    source_counts = Counter(entry["source"] for entry in resolved_entries)
    if source_counts.get("static", 0) != static_count:
        raise FrameSionnaXmlError(
            f"Manifest static_count={static_count}, but resolved static entries="
            f"{source_counts.get('static', 0)}"
        )
    if source_counts.get("dynamic", 0) != dynamic_count:
        raise FrameSionnaXmlError(
            f"Manifest dynamic_count={dynamic_count}, but resolved dynamic entries="
            f"{source_counts.get('dynamic', 0)}"
        )

    return resolved_entries, warnings


def build_xml(
    entries: list[dict[str, Any]],
    output_path: Path,
    *,
    frame_id: int,
    material_specs: dict[str, RtMaterialSpec],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    used_materials = sorted({entry["material_label_resolved"] for entry in entries})
    scene = ET.Element("scene", {"version": "3.0.0"})
    for material_class in used_materials:
        add_radio_material_xml(
            scene,
            material_specs[material_class],
            material_id=material_bsdf_id(material_class, frame_id),
        )

    for entry in entries:
        add_shape(scene, entry, output_path.parent, frame_id=frame_id)

    if len(scene.findall("shape")) != len(entries):
        raise FrameSionnaXmlError("Internal shape count mismatch before writing XML")

    prettify(scene)
    ET.ElementTree(scene).write(output_path, encoding="utf-8", xml_declaration=False)


def main() -> int:
    args = parse_args()
    config = build_config(args)
    try:
        data = load_json(config.input_manifest_path)
        if not isinstance(data, dict):
            raise FrameSionnaXmlError("Input manifest root must be an object")

        material_specs = load_rt_material_specs()
        entries, warnings = validate_and_resolve_entries(
            data,
            frame_id=config.frame_id,
            material_specs=material_specs,
        )
        build_xml(
            entries,
            config.output_xml_path,
            frame_id=config.frame_id,
            material_specs=material_specs,
        )
    except FrameSionnaXmlError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    material_counts = Counter(entry["material_label_resolved"] for entry in entries)
    source_counts = Counter(entry["source"] for entry in entries)
    dynamic_models = sorted({entry["model_name"] for entry in entries if entry["source"] == "dynamic"})
    source_sample_index = data["source_sample_index"]

    print(f"Frame-{config.frame_id} Sionna XML build")
    print(f"Input manifest: {config.input_manifest_path}")
    print(f"Frame: {config.frame_id}")
    print(f"Source sample: {source_sample_index}")
    print(f"Static entries: {source_counts.get('static', 0)}")
    print(f"Dynamic entries: {source_counts.get('dynamic', 0)}")
    print(f"Total entries: {len(entries)}")
    print("Used material classes: " + ", ".join(sorted(material_counts)))
    print("Dynamic material resolution:")
    for model_name in dynamic_models:
        print(f"  {model_name} -> {DYNAMIC_MODEL_MATERIALS[model_name]}")
    print("Shapes per material class:")
    for material_class in sorted(material_counts):
        print(f"  {material_class}: {material_counts[material_class]}")
    print(f"Warnings: {len(warnings)}")
    for warning in warnings:
        print(f"  WARNING: {warning}")
    print(f"XML written: {config.output_xml_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
