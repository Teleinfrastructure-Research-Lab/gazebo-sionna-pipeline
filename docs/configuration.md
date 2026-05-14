# Configuration

This document lists the files users are expected to edit and what each one
controls. For internal contracts and extension advice, see
[Developer Guide](developer_guide.md).

| File | Controls | Edit when |
| --- | --- | --- |
| `rt_out/config/dynamic_prototype_config.json` | rigid Panda/UR5 model membership, pose logs, prototype frames, expected counts | changing rigid dynamic models, pose logs, frame selection, or renderable counts |
| `rt_out/config/actor_dynamic_config.json` | optional actor participation, actor sampling, actor material labels | enabling/disabling actors or changing three-frame actor timing/materials |
| `rt_out/config/prototype_radio_sites.json` | TX/RX positions used by `36` | moving approved radio sites or adding code-supported site IDs |
| `rt_out/config/rt_material_mapping.json` | carrier frequency and Sionna radio-material definitions | changing RT frequency or material assumptions |
| `rt_out/materials/material_map.json` | semantic material labels for static scene objects | adding static assets or correcting material assignments |
| `rt_out/experiments/<experiment>/configs/experiment_config.json` | experiment frame count, output root, TX/RX list, labels/features | changing experiment scope or output location |

## `rt_out/config/dynamic_prototype_config.json`

Controls the rigid Panda/UR5 prototype branch.

Typical contents:

- dynamic model names
- pose-log paths
- expected logged link counts
- expected renderable link and visual counts
- prototype frame IDs and source sample indices
- forced material labels for rigid dynamic models

Edit this when:

- changing Panda/UR5 pose log locations
- selecting different three-frame samples
- adapting the rigid branch to a different dynamic model set
- changing expected renderable counts after model asset changes

Downstream users include `00`, `01`, `30`, `31`, `32`, `33`, `34`, `35`, `36`,
and experiment wrappers.

## `rt_out/config/actor_dynamic_config.json`

Controls which extracted Gazebo actors participate in the optional three-frame
actor branch.

Typical contents:

- enabled actor IDs or names
- frame sampling strategy and timing policy
- material labels for actor exports
- actor-specific export defaults

Edit this when:

- enabling or disabling actor participation
- changing actor sampling times for the three prototype frames
- changing actor material labels

The actor branch is separate from the rigid Panda/UR5 parser because Gazebo
actors are skinned animated meshes, not rigid link-pose records.

## `rt_out/config/prototype_radio_sites.json`

Defines the current TX/RX positions used by `36`.

The current multi-RX runner expects:

- `tx_sites.tx_ap`
- `rx_sites.rx_panda_base`
- `rx_sites.rx_ur5_base`
- `rx_sites.rx_cerberus_base`

Edit numeric positions freely when evaluating different approved locations. If
you rename site IDs, update the runner or extension code that currently expects
those names.

## `rt_out/config/rt_material_mapping.json`

Maps semantic labels to Sionna radio-material settings and runtime defaults.

It controls:

- carrier frequency used by sanity scripts
- Sionna radio-material definitions
- material properties used in emitted XML
- runtime parameters shared by static and frame XML generation

Edit this when changing material assumptions or frequency/material behavior.
Then rebuild the relevant XMLs and rerun RT sanity checks.

## `rt_out/materials/material_map.json`

Assigns semantic material labels to static scene objects. The static registry
and merge steps use these labels to group geometry and choose RT materials.

Edit this when:

- adding static assets
- changing object names or model names
- correcting semantic material labels

After edits, rerun the static registry and merge path:

```bash
python3 rt_out/scripts/static_scene/03_build_static_scene_registry.py
python3 rt_out/scripts/static_scene/20_merge_static_scene_by_material.py
python3 rt_out/scripts/static_scene/23_build_static_sionna_xml.py
```

## Experiment Configs

Experiment-local configs live under:

```text
rt_out/experiments/<experiment_name>/configs/
```

For `semantic_ablation_rigid_200f`, the key config is typically:

```text
rt_out/experiments/semantic_ablation_rigid_200f/configs/experiment_config.json
```

For the actor-aware variant, the parallel config is:

```text
rt_out/experiments/semantic_ablation_actor_200f/configs/experiment_config.json
```

It controls:

- experiment name and output roots
- frame count and sampled-frame JSON
- dynamic model subset
- TX/RX set for batch RT
- label thresholds
- feature modes and ablation outputs
- optional `actors` block for experiment-local actor sampling/export

For `semantic_ablation_actor_200f`, the `actors` block includes:

- `enabled`
- `actor_manifest`
- `actor_name`
- `material_label`
- `actor_time_policy`
- `trajectory_duration_seconds`
- `animation_time_policy`
- `animation_loop_duration_seconds`
- `alignment_policy`
- `z_alignment_policy`
- `floor_z`
- `runtime_phase_claim`

The actor-aware branch currently uses:

- `alignment_policy = bounds_center_xy_to_root`
- `z_alignment_policy = bounds_min_z_to_floor`
- `floor_z = 0.1`

Compact example:

```json
"actors": {
  "enabled": true,
  "actor_manifest": "rt_out/manifests/actor_manifest.json",
  "actor_name": "actor_walking",
  "material_label": "human_skin",
  "actor_time_policy": "uniform_over_actor_trajectory",
  "trajectory_duration_seconds": 29.58,
  "animation_time_policy": "mod_clip_duration",
  "animation_loop_duration_seconds": 5.79,
  "alignment_policy": "bounds_center_xy_to_root",
  "z_alignment_policy": "bounds_min_z_to_floor",
  "floor_z": 0.1,
  "runtime_phase_claim": false
}
```

If actor material features are desired, include `human_skin` in
`materials_of_interest`.

## World And Asset Inputs

Important project files that behave like configuration:

- `myworld_rt.sdf`: RT extraction world
- `myworld.sdf`: general Gazebo simulation world
- `models/`: model SDFs, meshes, textures, actors, robots, and furniture assets
- `run_myworld_rt.sh`: launch helper for the RT-oriented world

Changing world geometry or model assets usually requires rerunning the static
manifest, registry, merge, XML, and sanity steps.

## What To Rerun

If you changed static geometry or materials:

```bash
python3 rt_out/scripts/static_scene/00_extract_scene_manifests.py
python3 rt_out/scripts/static_scene/01_validate_scene_manifests.py
python3 rt_out/scripts/static_scene/02_build_scene_geometry_registry.py
python3 rt_out/scripts/static_scene/03_build_static_scene_registry.py
python3 rt_out/scripts/static_scene/20_merge_static_scene_by_material.py
python3 rt_out/scripts/static_scene/23_build_static_sionna_xml.py
```

If you changed rigid pose logs or prototype frame selection:

```bash
python3 rt_out/scripts/dynamic_rigid/30_build_prototype_dynamic_frames.py
python3 rt_out/scripts/dynamic_rigid/31_build_prototype_dynamic_visual_frames.py
python3 rt_out/scripts/dynamic_rigid/35_run_prototype_three_frame_rt_sanity.py
```

If you changed actor config or actor assets:

```bash
python3 rt_out/scripts/dynamic_actor/40_extract_actor_manifest.py
python3 rt_out/scripts/dynamic_actor/41_build_actor_frame_samples.py
python3 rt_out/scripts/dynamic_rigid/35_run_prototype_three_frame_rt_sanity.py --include-actors
```
