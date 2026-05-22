# Configuration

This document lists the main configuration files across the current
Gazebo-to-Sionna RT project. It focuses on what users are expected to edit and
what each file controls.

## Core Project Configs

| File | Controls | Edit when |
| --- | --- | --- |
| `rt_out/config/dynamic_prototype_config.json` | rigid Panda/UR5 model membership, pose logs, prototype frames, expected counts | changing rigid dynamic models, pose logs, or sampled rigid frames |
| `rt_out/config/actor_dynamic_config.json` | actor participation, sampling, and actor export defaults | enabling/disabling actors or changing actor timing/materials |
| `rt_out/config/prototype_radio_sites.json` | TX/RX positions used by the prototype RT harnesses | moving approved radio sites or renaming site IDs used by the scripts |
| `rt_out/config/rt_material_mapping.json` | Sionna radio materials and runtime RT defaults | changing carrier frequency or RT material behavior |
| `rt_out/materials/material_map.json` | semantic material labels for static scene assets | adding or correcting static asset material assignments |

## World And Asset Inputs

Important project files that behave like configuration:

- `myworld_rt.sdf`: main RT-oriented Gazebo world
- `myworld.sdf`: general Gazebo simulation world
- `models/`: Gazebo models, meshes, textures, actors, robots, and furniture
- `run_myworld_rt.sh`: RT-world launch helper

Changing world geometry or model assets usually means rerunning the static
manifest, registry, merge, XML, and RT sanity stages.

## `dynamic_prototype_config.json`

This is the main rigid-dynamic config. It controls:

- dynamic model names
- Panda and UR5 pose-log paths
- expected logged link counts
- expected renderable link/visual counts
- prototype frame IDs and sampled source indices
- forced material labels for rigid dynamic models

Downstream users include the static extract/validate flow, rigid-frame builders,
frame composition, XML generation, and the prototype RT sanity harnesses.

## `actor_dynamic_config.json`

This controls the optional actor-aware branch:

- enabled actor IDs or names
- actor frame sampling strategy
- actor material labels
- actor export defaults

The actor branch is separate from the rigid Panda/UR5 parser because Gazebo
actors are animated skinned meshes, not rigid link-pose records.

## `prototype_radio_sites.json`

This defines the current TX/RX positions used by the multi-RX rigid and
actor-aware sanity runners.

Current expected IDs include:

- `tx_sites.tx_ap`
- `rx_sites.rx_panda_base`
- `rx_sites.rx_ur5_base`
- `rx_sites.rx_cerberus_base`

If you rename site IDs, also update the code paths that expect them.

## `rt_material_mapping.json`

This file controls:

- carrier frequency
- Sionna radio-material definitions
- material properties written into generated XML
- shared RT runtime defaults

After changing it, rebuild the relevant XMLs and rerun RT sanity checks.

## `material_map.json`

This assigns semantic material labels to static scene objects. The static
registry and merge steps use these labels for both geometry grouping and RT
material assignment.

If you change it, rerun:

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

Common examples:

- `rt_out/experiments/semantic_ablation_rigid_200f/configs/experiment_config.json`
- `rt_out/experiments/semantic_ablation_actor_200f/configs/experiment_config.json`

These configs typically control:

- experiment name and output roots
- frame count and sampled-frame metadata
- dynamic model subset
- TX/RX set for batch RT
- label thresholds
- feature modes and ablation outputs
- optional actor blocks for actor-aware experiment branches

For the current actor-aware branch, the `actors` block includes timing,
alignment, floor alignment, and runtime-phase-claim settings. The current
export path uses approximate actor placement for RT and does not claim perfect
Gazebo runtime animation matching.

## Perception Pilot Configs

The panoptic perception pilot keeps its active configs under:

```text
rt_out/experiments/perception_rt_small_v0/configs/
```

### `perception_dataset_config.json`

Controls:

- experiment name
- source experiment path
- selected frame count
- expected camera count
- expected perception sample count
- output roots used by the perception scripts

Current active values include:

- `frame_count = 20`
- `expected_camera_count = 8`
- `expected_perception_samples = 160`

### `camera_rig.json`

Defines the 8 fixed panoptic camera viewpoints:

- `cam_corner_nw`
- `cam_corner_ne`
- `cam_corner_sw`
- `cam_corner_se`
- `cam_wall_north`
- `cam_wall_south`
- `cam_wall_east`
- `cam_wall_west`

Each entry contains pose, resolution, FOV, and clip settings for the fixed
capture rig.

### `semantic_label_map.json`

Defines the compact semantic taxonomy used by the perception pilot:

- `1 floor`
- `2 ceiling`
- `3 wall`
- `4 door`
- `5 window`
- `6 table`
- `7 chair`
- `8 robot`
- `9 human`
- `10 misc_object`

For the current panoptic capture, semantic labels are decoded from channel `2`
of the Gazebo panoptic labels map.

## Perception Metadata Files

Two generated perception metadata files are still important to interpret the
pilot outputs:

- `rt_out/experiments/perception_rt_small_v0/frames/instance_registry.json`
  keeps the stable object metadata used by the pilot scripts
- `rt_out/experiments/perception_rt_small_v0/perception_sdf/instance_label_map.json`
  describes Gazebo-side label assignments for world generation and debugging

`gazebo_instance_count` from the panoptic capture is not the stable dataset
instance ID.

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

If you changed rigid pose logs or rigid frame selection:

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

If you changed perception configs or camera rig settings:

```bash
python3 rt_out/scripts/perception/60_select_perception_frames.py \
  --config rt_out/experiments/perception_rt_small_v0/configs/perception_dataset_config.json
python3 rt_out/scripts/perception/61_build_perception_instance_registry.py \
  --config rt_out/experiments/perception_rt_small_v0/configs/perception_dataset_config.json
python3 rt_out/scripts/perception/62_build_labeled_gazebo_world.py \
  --config rt_out/experiments/perception_rt_small_v0/configs/perception_dataset_config.json \
  --force
```
