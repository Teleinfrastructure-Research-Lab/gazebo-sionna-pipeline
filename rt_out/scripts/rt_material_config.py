"""Load and validate the RT material/radio-material configuration.

XML builders and RT sanity scripts all need the same frequency and material
mapping rules. This helper centralizes that schema validation and exposes the
derived structures those scripts consume.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RT_MATERIAL_CONFIG_PATH = PROJECT_ROOT / "rt_out" / "config" / "rt_material_mapping.json"


class RtMaterialConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class RtMaterialSpec:
    """One semantic material-class specification for XML/RT emission."""
    material_class: str
    model: str
    thickness: float
    itu_type: str | None = None
    relative_permittivity: float | None = None
    conductivity: float | None = None
    scattering_coefficient: float = 0.0
    xpd_coefficient: float = 0.0
    frequency_hz: float | None = None

    @property
    def default_material_id(self) -> str:
        """Return the stable XML identifier used when no explicit ID is given."""
        return f"mat-{slugify(self.material_class)}"


@dataclass(frozen=True)
class RtRuntimeConfig:
    """Runtime-wide RT settings shared across material-aware scripts."""
    carrier_frequency_hz: float
    config_path: Path


def slugify(text: Any) -> str:
    """Create stable XML-safe identifiers from free-form material labels."""
    chars = []
    for ch in str(text):
        chars.append(ch.lower() if ch.isalnum() else "_")
    slug = "".join(chars)
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "item"


def load_json(path: Path) -> Any:
    """Read the raw RT material mapping JSON file."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise RtMaterialConfigError(f"Missing RT material config: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RtMaterialConfigError(f"Invalid RT material config JSON: {exc}") from exc


def numeric(value: Any, label: str, *, minimum: float | None = None) -> float:
    """Parse numeric material parameters and enforce optional lower bounds."""
    if isinstance(value, bool):
        raise RtMaterialConfigError(f"{label} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise RtMaterialConfigError(f"{label} must be numeric") from exc
    if minimum is not None and number < minimum:
        raise RtMaterialConfigError(f"{label} must be >= {minimum}")
    return number


def non_empty_string(value: Any, label: str) -> str:
    """Normalize required string-valued material config fields."""
    if not isinstance(value, str) or not value.strip():
        raise RtMaterialConfigError(f"{label} must be a non-empty string")
    return value.strip()


def load_rt_material_specs(
    config_path: Path | None = None,
) -> dict[str, RtMaterialSpec]:
    """Load semantic-material specs used when building Sionna/Mitsuba scenes.

    The project maps semantic classes such as metal or glass onto either ITU or
    custom radio-material parameters. This function validates that mapping.
    """
    path = (config_path or DEFAULT_RT_MATERIAL_CONFIG_PATH).expanduser().resolve()
    data = load_json(path)
    if not isinstance(data, dict):
        raise RtMaterialConfigError("rt_material_mapping.json root must be an object")

    materials = data.get("materials")
    if not isinstance(materials, dict) or not materials:
        raise RtMaterialConfigError("rt_material_mapping.json must contain a materials object")

    specs: dict[str, RtMaterialSpec] = {}
    for material_class, raw_spec in materials.items():
        material_class = non_empty_string(material_class, "material class")
        if not isinstance(raw_spec, dict):
            raise RtMaterialConfigError(f"{material_class} material spec must be an object")

        model = non_empty_string(raw_spec.get("model"), f"{material_class}.model").lower()
        thickness = numeric(raw_spec.get("thickness", 0.1), f"{material_class}.thickness", minimum=0.0)
        scattering_coefficient = numeric(
            raw_spec.get("scattering_coefficient", 0.0),
            f"{material_class}.scattering_coefficient",
            minimum=0.0,
        )
        xpd_coefficient = numeric(
            raw_spec.get("xpd_coefficient", 0.0),
            f"{material_class}.xpd_coefficient",
            minimum=0.0,
        )

        if model == "itu":
            specs[material_class] = RtMaterialSpec(
                material_class=material_class,
                model=model,
                itu_type=non_empty_string(raw_spec.get("itu_type"), f"{material_class}.itu_type"),
                thickness=thickness,
                scattering_coefficient=scattering_coefficient,
                xpd_coefficient=xpd_coefficient,
            )
        elif model == "custom":
            specs[material_class] = RtMaterialSpec(
                material_class=material_class,
                model=model,
                relative_permittivity=numeric(
                    raw_spec.get("relative_permittivity"),
                    f"{material_class}.relative_permittivity",
                    minimum=1.0,
                ),
                conductivity=numeric(
                    raw_spec.get("conductivity"),
                    f"{material_class}.conductivity",
                    minimum=0.0,
                ),
                thickness=thickness,
                scattering_coefficient=scattering_coefficient,
                xpd_coefficient=xpd_coefficient,
                frequency_hz=(
                    numeric(raw_spec["frequency_hz"], f"{material_class}.frequency_hz", minimum=0.0)
                    if "frequency_hz" in raw_spec
                    else None
                ),
            )
        else:
            raise RtMaterialConfigError(
                f"{material_class}.model must be either 'itu' or 'custom', got {model!r}"
            )

    return specs


def load_rt_runtime_config(config_path: Path | None = None) -> RtRuntimeConfig:
    """Load the experiment-wide RT carrier-frequency metadata."""
    path = (config_path or DEFAULT_RT_MATERIAL_CONFIG_PATH).expanduser().resolve()
    data = load_json(path)
    if not isinstance(data, dict):
        raise RtMaterialConfigError("rt_material_mapping.json root must be an object")

    metadata = data.get("metadata")
    if not isinstance(metadata, dict):
        raise RtMaterialConfigError("rt_material_mapping.json must contain a metadata object")

    carrier_frequency_hz = numeric(
        metadata.get("carrier_frequency_hz"),
        "metadata.carrier_frequency_hz",
        minimum=0.0,
    )

    return RtRuntimeConfig(
        carrier_frequency_hz=carrier_frequency_hz,
        config_path=path,
    )


def add_radio_material_xml(
    scene: ET.Element,
    spec: RtMaterialSpec,
    *,
    material_id: str | None = None,
) -> str:
    """Append one Sionna radio-material XML node and return its ID.

    This keeps the semantic-to-radio material assumption explicit in the emitted
    XML so later RT sanity runs use the same mapping as the rest of the project.
    """
    bsdf_id = material_id or spec.default_material_id

    if spec.model == "itu":
        bsdf = ET.SubElement(
            scene,
            "bsdf",
            {
                "type": "itu-radio-material",
                "id": bsdf_id,
            },
        )
        ET.SubElement(bsdf, "string", {"name": "type", "value": str(spec.itu_type)})
    elif spec.model == "custom":
        bsdf = ET.SubElement(
            scene,
            "bsdf",
            {
                "type": "radio-material",
                "id": bsdf_id,
            },
        )
        ET.SubElement(
            bsdf,
            "float",
            {"name": "relative_permittivity", "value": f"{spec.relative_permittivity:g}"},
        )
        ET.SubElement(
            bsdf,
            "float",
            {"name": "conductivity", "value": f"{spec.conductivity:g}"},
        )
    else:
        raise RtMaterialConfigError(f"Unsupported RT material model: {spec.model}")

    ET.SubElement(bsdf, "float", {"name": "thickness", "value": f"{spec.thickness:g}"})
    ET.SubElement(
        bsdf,
        "float",
        {"name": "scattering_coefficient", "value": f"{spec.scattering_coefficient:g}"},
    )
    ET.SubElement(
        bsdf,
        "float",
        {"name": "xpd_coefficient", "value": f"{spec.xpd_coefficient:g}"},
    )
    return bsdf_id
