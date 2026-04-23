#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path
from typing import Any

from rt_material_config import load_rt_runtime_config


DEFAULT_XML = (
    Path(__file__).resolve().parents[2]
    / "rt_out"
    / "static_scene"
    / "export"
    / "static_scene_sionna.xml"
)
DEFAULT_TX_POSITION = (-0.3, -3.8, 1.3)
DEFAULT_RX_POSITION = (2.5, -3.1, 1.3)
REQUIRED_VARIANT_SUFFIX = "_ad_mono_polarized"
FALLBACK_VARIANT = "cuda_ad_mono_polarized"
DEFAULT_RT_RUNTIME_CONFIG = load_rt_runtime_config()


def parse_vec3(value: str, *, field: str) -> tuple[float, float, float]:
    parts = [item.strip() for item in value.split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(f"{field} must have format x,y,z")
    try:
        return tuple(float(item) for item in parts)  # type: ignore[return-value]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{field} must contain numeric values") from exc


def format_vec3(value: tuple[float, float, float]) -> str:
    return f"({value[0]:.3f}, {value[1]:.3f}, {value[2]:.3f})"


def shape_of(value: Any) -> Any:
    if isinstance(value, (list, tuple)):
        return [shape_of(item) for item in value]
    shape = getattr(value, "shape", None)
    if shape is not None:
        return tuple(int(dim) for dim in shape)
    return "<shape unavailable>"


def format_scalar(value: Any) -> str:
    if value is None:
        return "<unset>"
    try:
        array = to_numpy(value)
        if array is not None:
            flat = array.reshape(-1)
            if flat.size:
                return f"{float(flat[0]):.6g}"
    except Exception:
        pass
    return str(value)


def to_numpy(value: Any) -> Any | None:
    if value is None:
        return None
    if hasattr(value, "numpy"):
        return value.numpy()
    try:
        import numpy as np

        return np.asarray(value)
    except Exception:
        return None


def count_paths(paths: Any) -> tuple[int | None, str]:
    valid = getattr(paths, "valid", None)
    valid_np = to_numpy(valid)
    if valid_np is not None:
        try:
            import numpy as np

            return int(np.count_nonzero(valid_np)), "valid path mask"
        except Exception:
            pass

    interactions = getattr(paths, "interactions", None)
    interactions_shape = getattr(interactions, "shape", None)
    if interactions_shape is not None and len(interactions_shape) > 0:
        return int(interactions_shape[-1]), "interaction path slots"

    tau = getattr(paths, "tau", None)
    tau_shape = getattr(tau, "shape", None)
    if tau_shape is not None and len(tau_shape) > 0:
        return int(tau_shape[-1]), "delay tensor path slots"

    return None, "unavailable"


def summarize_paths(paths: Any) -> None:
    num_paths, source = count_paths(paths)
    if num_paths is None:
        print("paths_found        : <unavailable>")
    else:
        print(f"paths_found        : {num_paths} ({source})")

    for attr in ["a", "tau", "interactions", "valid"]:
        value = getattr(paths, attr, None)
        if value is not None:
            print(f"paths.{attr:<12}: shape={shape_of(value)}")

    try:
        cir = paths.cir()
    except Exception as exc:
        print(f"cir_summary        : unavailable ({type(exc).__name__}: {exc})")
        return

    if isinstance(cir, (tuple, list)):
        print(f"cir_summary        : tuple/list with {len(cir)} item(s)")
        for index, item in enumerate(cir):
            print(f"cir[{index}] shape    : {shape_of(item)}")
    else:
        print(f"cir_summary        : shape={shape_of(cir)}")


def print_material_summary(scene: Any, *, limit: int = 12) -> None:
    objects = getattr(scene, "objects", {})
    materials = getattr(scene, "radio_materials", {})
    print(f"scene_objects      : {len(objects) if hasattr(objects, '__len__') else '<unknown>'}")
    print(
        "radio_materials    : "
        f"{len(materials) if hasattr(materials, '__len__') else '<unknown>'}"
    )

    if isinstance(objects, dict):
        for index, (name, obj) in enumerate(objects.items()):
            if index >= limit:
                remaining = len(objects) - limit
                if remaining > 0:
                    print(f"  ... {remaining} more object(s)")
                break
            material = getattr(obj, "radio_material", None)
            mat_name = getattr(material, "name", None)
            eps = format_scalar(getattr(material, "relative_permittivity", None))
            sigma = format_scalar(getattr(material, "conductivity", None))
            thickness = format_scalar(getattr(material, "thickness", None))
            print(
                "  object_material  : "
                f"{name} -> {type(material).__name__}"
                f"{f' ({mat_name})' if mat_name else ''}"
                f" eps_r={eps} sigma={sigma} thickness={thickness}"
            )


def print_run_command(script_path: Path) -> None:
    try:
        rel = script_path.resolve().relative_to(Path.cwd().resolve())
    except ValueError:
        rel = script_path.resolve()
    print()
    print("Run command:")
    print(f"  python3 {rel}")


def load_sionna_scene(load_scene: Any, xml_path: Path) -> Any:
    try:
        return load_scene(str(xml_path), merge_shapes=False)
    except TypeError as exc:
        if "merge_shapes" not in str(exc):
            raise
        return load_scene(str(xml_path))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Minimal Sionna RT sanity check for the validated static scene."
    )
    parser.add_argument(
        "--xml",
        type=Path,
        default=DEFAULT_XML,
        help="Path to static_scene_sionna.xml",
    )
    parser.add_argument(
        "--tx",
        type=lambda value: parse_vec3(value, field="--tx"),
        default=DEFAULT_TX_POSITION,
        help="Transmitter position as x,y,z in meters",
    )
    parser.add_argument(
        "--rx",
        type=lambda value: parse_vec3(value, field="--rx"),
        default=DEFAULT_RX_POSITION,
        help="Receiver position as x,y,z in meters",
    )
    parser.add_argument("--max-depth", type=int, default=2)
    parser.add_argument("--samples-per-src", type=int, default=20_000)
    parser.add_argument("--max-num-paths-per-src", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--frequency-hz",
        type=float,
        default=DEFAULT_RT_RUNTIME_CONFIG.carrier_frequency_hz,
        help=(
            "Carrier frequency in Hz. Defaults to rt_out/config/rt_material_mapping.json "
            "metadata.carrier_frequency_hz."
        ),
    )
    parser.add_argument(
        "--enable-refraction",
        action="store_true",
        help="Enable refraction. Disabled by default for this first sanity check.",
    )
    parser.add_argument(
        "--use-fallback-variant",
        action="store_true",
        help=f"If Sionna does not select a polarized mono variant, try {FALLBACK_VARIANT}.",
    )
    return parser.parse_args()


def main() -> int:
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    args = parse_args()
    script_path = Path(__file__)
    xml_path = args.xml.expanduser().resolve()

    print("Sionna static sanity check")
    print("==========================")
    print(f"xml                : {xml_path}")
    print(f"tx_position        : {format_vec3(args.tx)}")
    print(f"rx_position        : {format_vec3(args.rx)}")
    print(f"carrier_frequency_hz: {args.frequency_hz:.6g}")
    print(
        "path_settings      : "
        f"max_depth={args.max_depth}, "
        f"los=True, specular_reflection=True, diffuse_reflection=False, "
        f"refraction={args.enable_refraction}, seed={args.seed}"
    )

    if not xml_path.exists():
        print(f"\nERROR: XML scene does not exist: {xml_path}", file=sys.stderr)
        print_run_command(script_path)
        return 2

    try:
        import sionna.rt  # noqa: F401
        from sionna.rt import PlanarArray, Receiver, Transmitter, PathSolver, load_scene
    except Exception as exc:
        print(f"\nERROR: Could not import Sionna RT: {exc}", file=sys.stderr)
        print_run_command(script_path)
        return 2

    try:
        import mitsuba as mi
    except Exception as exc:
        print(f"\nERROR: Could not import Mitsuba after Sionna RT: {exc}", file=sys.stderr)
        print("Install/use the Python environment where Mitsuba is available.", file=sys.stderr)
        print_run_command(script_path)
        return 2

    selected_variant = str(mi.variant())
    if (
        not selected_variant.endswith(REQUIRED_VARIANT_SUFFIX)
        and args.use_fallback_variant
    ):
        try:
            mi.set_variant(FALLBACK_VARIANT)
            selected_variant = str(mi.variant())
            print(f"mitsuba_fallback   : {FALLBACK_VARIANT}")
        except Exception as exc:
            print(
                f"\nERROR: Could not switch Mitsuba to {FALLBACK_VARIANT}: {exc}",
                file=sys.stderr,
            )
            print_run_command(script_path)
            return 2

    print(f"mitsuba_variant    : {selected_variant}")
    if not selected_variant.endswith(REQUIRED_VARIANT_SUFFIX):
        print(
            "\nERROR: Sionna RT requires a Mitsuba variant ending in "
            f"{REQUIRED_VARIANT_SUFFIX!r}; got {selected_variant!r}.",
            file=sys.stderr,
        )
        print(
            f"Try rerunning with --use-fallback-variant to request {FALLBACK_VARIANT}.",
            file=sys.stderr,
        )
        print_run_command(script_path)
        return 2

    try:
        mi.load_file(str(xml_path))
        print("mitsuba_load       : OK")
    except Exception as exc:
        print(f"\nERROR: Mitsuba could not load the XML scene: {exc}", file=sys.stderr)
        print(
            "For Sionna XML files, this check is run after importing Sionna RT so "
            "radio-material plugins are registered.",
            file=sys.stderr,
        )
        print_run_command(script_path)
        return 2

    try:
        scene = load_sionna_scene(load_scene, xml_path)
        scene.frequency = float(args.frequency_hz)
        print("sionna_load        : OK")
        print(f"scene_frequency_hz : {format_scalar(getattr(scene, 'frequency', None))}")
    except Exception as exc:
        print(f"\nERROR: Sionna RT could not load the XML scene: {exc}", file=sys.stderr)
        print(
            "Possible blocker: the XML currently contains visual Mitsuba BSDFs "
            "rather than explicit Sionna radio materials.",
            file=sys.stderr,
        )
        print_run_command(script_path)
        return 2

    print_material_summary(scene)

    if getattr(scene, "transmitters", None) and len(scene.transmitters) != 0:
        print("\nERROR: Scene already contains transmitters; expected none.", file=sys.stderr)
        print_run_command(script_path)
        return 2
    if getattr(scene, "receivers", None) and len(scene.receivers) != 0:
        print("\nERROR: Scene already contains receivers; expected none.", file=sys.stderr)
        print_run_command(script_path)
        return 2

    try:
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

        tx = Transmitter(name="tx_static_sanity", position=mi.Point3f(*args.tx))
        rx = Receiver(name="rx_static_sanity", position=mi.Point3f(*args.rx))
        scene.add(tx)
        scene.add(rx)
        tx.look_at(rx)

        print("tx_name            : tx_static_sanity")
        print(f"tx_position        : {format_vec3(args.tx)}")
        print("rx_name            : rx_static_sanity")
        print(f"rx_position        : {format_vec3(args.rx)}")
        print("tx_look_at_rx      : OK")
    except Exception as exc:
        print(f"\nERROR: Could not configure TX/RX devices: {exc}", file=sys.stderr)
        print_run_command(script_path)
        return 2

    try:
        solver = PathSolver()
        paths = solver(
            scene=scene,
            max_depth=args.max_depth,
            max_num_paths_per_src=args.max_num_paths_per_src,
            samples_per_src=args.samples_per_src,
            synthetic_array=True,
            los=True,
            specular_reflection=True,
            diffuse_reflection=False,
            refraction=args.enable_refraction,
            # Currently, disabling diffraction and edge diffraction for this 
            # first sanity check, as they are more complex and less commonly 
            # used than the other path interactions. Enabling them here would be a 
            # blocker for this stage, and they can be added in future iterations of 
            # the sanity checks.
            # diffraction=False,
            # edge_diffraction=False,
            seed=args.seed,
        )
        print("path_compute       : OK")
        summarize_paths(paths)
    except Exception as exc:
        print(f"\nERROR: Path computation failed: {exc}", file=sys.stderr)
        print("Traceback:", file=sys.stderr)
        traceback.print_exc()
        print(
            "\nIf the traceback refers to radio materials, the exact blocker is "
            "that this visual-debug XML is not yet a Sionna radio-material scene.",
            file=sys.stderr,
        )
        print_run_command(script_path)
        return 2

    print_run_command(script_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
