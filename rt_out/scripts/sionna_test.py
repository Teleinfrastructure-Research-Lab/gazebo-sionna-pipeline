"""Small ad hoc Sionna sandbox used for local scene/path experiments.

This file is not part of the validated pipeline stages. It exists as a quick
scratchpad for loading scenes, placing radios, and checking basic Sionna RT
behavior while developing or debugging the main scripts.
"""

import csv
from pathlib import Path
import numpy as np

import sionna.rt
import mitsuba as mi
from sionna.rt import PlanarArray, Receiver, Transmitter, PathSolver, load_scene

from rt_material_config import load_rt_runtime_config

print("variant:", mi.variant())

XML = "rt_out/static_scene/export/static_scene_sionna.xml"
OUT = Path("rt_out/static_scene/export/static_multi_rx_sanity.csv")
CARRIER_FREQUENCY_HZ = load_rt_runtime_config().carrier_frequency_hz

tx_pos = (-0.3, -3.8, 1.3)

rx_positions = [
    ( 2.5, -3.1, 1.3),
    ( 1.5, -1.0, 1.3),
    ( 0.0,  0.0, 1.3),
    (-1.5,  1.5, 1.3),
    ( 3.0,  2.0, 1.3),
]

def to_np(x):
    if hasattr(x, "numpy"):
        return x.numpy()
    return np.asarray(x)

rows = []

for i, rx_pos in enumerate(rx_positions):
    scene = load_scene(XML, merge_shapes=False)
    scene.frequency = CARRIER_FREQUENCY_HZ

    scene.tx_array = PlanarArray(
        num_rows=1, num_cols=1,
        vertical_spacing=0.5, horizontal_spacing=0.5,
        pattern="iso", polarization="V"
    )
    scene.rx_array = PlanarArray(
        num_rows=1, num_cols=1,
        vertical_spacing=0.5, horizontal_spacing=0.5,
        pattern="iso", polarization="V"
    )

    tx = Transmitter(name=f"tx_{i}", position=mi.Point3f(*tx_pos))
    rx = Receiver(name=f"rx_{i}", position=mi.Point3f(*rx_pos))
    scene.add(tx)
    scene.add(rx)
    tx.look_at(rx)

    solver = PathSolver()
    paths = solver(
        scene=scene,
        max_depth=2,
        max_num_paths_per_src=10000,
        samples_per_src=20000,
        synthetic_array=True,
        los=True,
        specular_reflection=True,
        diffuse_reflection=False,
        refraction=False,
        seed=42,
    )

    valid = to_np(paths.valid).astype(bool).reshape(-1)
    tau = to_np(paths.tau).reshape(-1)

    valid_tau = tau[valid] if valid.size == tau.size else tau[:np.count_nonzero(valid)]

    row = {
        "rx_id": i,
        "tx_x": tx_pos[0], "tx_y": tx_pos[1], "tx_z": tx_pos[2],
        "rx_x": rx_pos[0], "rx_y": rx_pos[1], "rx_z": rx_pos[2],
        "num_paths": int(np.count_nonzero(valid)),
        "tau_min": float(valid_tau.min()) if valid_tau.size else None,
        "tau_max": float(valid_tau.max()) if valid_tau.size else None,
    }
    rows.append(row)
    print(row)

OUT.parent.mkdir(parents=True, exist_ok=True)
with OUT.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)

print(f"\nWrote {OUT}")
