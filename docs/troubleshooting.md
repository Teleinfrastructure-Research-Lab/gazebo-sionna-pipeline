# Troubleshooting

Common issues and where to look first.

## Sionna Import Fails

Symptoms:

- `Could not import Sionna RT`
- Mitsuba variant errors
- `PathSolver` import errors

Checks:

```bash
echo "$SIONNA_PYTHON"
$SIONNA_PYTHON -c "import sionna.rt, mitsuba as mi; print(mi.variant())"
```

Use the same Sionna/Mitsuba-capable environment for `24`, `35`, `36`, and the
experiment RT wrappers. If an older wrapper flow still refers to
`COLLABPAPER_PYTHON`, point it at the same interpreter as `SIONNA_PYTHON`.

## Blender Not Found

Symptoms:

- static merge fails before launching worker
- dynamic mesh export cannot find Blender
- actor export fails before writing PLYs

Set:

```bash
export BLENDER=blender
```

Then rerun the failing stage. Scripts also search `PATH` and common local
Blender locations, but explicit configuration is clearer. Use
`export BLENDER=/path/to/blender` if Blender is installed outside `PATH`.

## Missing Converted Static Meshes

Symptoms:

- `20_merge_static_scene_by_material.py` reports missing source meshes
- static registry has entries that cannot be imported by Blender

Checks:

```bash
python3 rt_out/scripts/static_scene/01_validate_scene_manifests.py
python3 rt_out/scripts/static_scene/02_build_scene_geometry_registry.py
python3 rt_out/scripts/static_scene/03_build_static_scene_registry.py
```

If a model asset changed, rebuild converted meshes or update material/geometry
mapping before rerunning the static merge.

## Missing Pose Logs

Symptoms:

- `30_build_prototype_dynamic_frames.py` cannot find Panda or UR5 logs
- source sample indices are out of range

Generate fresh logs by launching the RT world, then running:

```bash
bash rt_out/scripts/ops/run_all.sh
```

Confirm paths in `rt_out/config/dynamic_prototype_config.json` match the log
locations.

## Actor Deviates From Path

Actor path drift usually means the baked mesh bounds do not visually align with
the sampled root pose.

Prerequisites:

- `40` and `41` have produced actor manifest and actor frame samples
- at least one actor frame has been exported with `42` or `35 --include-actors`
- for composed-frame inspection, a composed frame manifest exists

Use:

```bash
python3 rt_out/scripts/validation/53_diagnose_actor_validation_alignment.py
python3 rt_out/scripts/validation/56_build_composed_frame_blender_scene.py \
  --composed-manifest rt_out/composed_scene/frame_000/composed_frame_000_manifest.json
```

The current actor export uses `bounds_center_xy_to_root` to align horizontal
bounds to the sampled root pose.

## Actor Floats Above Or Sinks Below Floor

Prerequisites:

- actor manifest and actor frame samples exist
- actor meshes have been exported with the intended vertical alignment policy
- static floor context is available from the current scene outputs

Use the floor diagnostic:

```bash
python3 rt_out/scripts/validation/55_diagnose_actor_floor_alignment.py
```

The current export-time vertical correction is `bounds_min_z_to_floor` with
`floor_z = 0.1`. This is a geometry correction for RT export, not a claim about
perfect Gazebo runtime animation phase.

Validation mesh exports can use the same XY and Z alignment policies as the
production actor exporter. For parity checks, `51_export_actor_validation_meshes.py`
supports:

- `--alignment-policy bounds_center_xy_to_root`
- `--z-alignment-policy bounds_min_z_to_floor`
- `--floor-z 0.1`

The production defaults remain:

- `alignment_policy = bounds_center_xy_to_root`
- `z_alignment_policy = bounds_min_z_to_floor`
- `floor_z = 0.1`

## Zero Paths With Actor/RX Overlap

Zero paths are not automatically a failed run. The `35` and `36` harnesses treat
a zero-path solve as valid if scene load and path computation complete. Check:

- TX/RX positions in `rt_out/config/prototype_radio_sites.json`
- actor position relative to the RX
- whether the actor mesh blocks line-of-sight in the current frame
- `num_paths`, `tau_min`, and `tau_max` in the summary CSV

When `num_paths == 0`, tau columns are expected to be empty.

## Actor 200-Frame Experiment Got Only 18 Or 120 RT Rows

The actor-aware 200-frame experiment supports debug runs such as
`--max-frames 3` and `--max-frames 20`. Those debug runs still write to
`rt_200frames_multi_rx.csv`.

Checks:

- `18` rows means `3` frames x `6` RX
- `120` rows means `20` frames x `6` RX
- full labels/features require the full `1200` RT rows before running
  `exp_build_rt_labels.py`, `exp_build_object_features.py`, or
  `exp_build_raw_occupancy_features.py`

Do not build labels or features from a debug RT CSV unless that is explicitly
what you want for a local debug-only branch.

## Actor-Aware Object Features Do Not Show Actor

The actor-aware object-feature branch should include actor entries from composed
manifests.

Checks:

- `mat_human_skin_dynamic_count` should be present when `human_skin` is in
  `materials_of_interest`
- `geom_dynamic_count` should be `22` per row in the actor-aware branch rather
  than `21`
- `frames_with_actor_objects` and `actor_objects_extracted` from
  `exp_build_object_features.py` should both be non-zero

If those checks fail, confirm the actor-aware branch used
`exp_compose_frame_manifests_batch.py --include-actors` and that the composed
manifests actually contain `source == "actor"` entries.

## Verify Actor-Aware Composed Manifests

```bash
python3 - <<'PY'
import csv, json
from pathlib import Path

idx = Path("rt_out/experiments/semantic_ablation_actor_200f/frames/composed_manifests/composed_manifest_index.csv")
rows = list(csv.DictReader(idx.open()))
bad = []
for row in rows:
    p = Path(row["composed_manifest_path"])
    data = json.load(p.open())
    if data.get("actor_count") != 1 or data.get("total_count") != 33:
        bad.append((row["frame_id"], data.get("actor_count"), data.get("total_count")))
print("rows", len(rows))
print("bad_actor_counts", bad[:10], "count", len(bad))
PY
```

For the current actor-aware 200f branch, the expected counts are
`actor_count == 1` and `total_count == 33`. If `actor_count` is `0`, the batch
composition likely ran without `--include-actors`.



