# Getting Started

This guide is the short entry point for the current Gazebo-to-Sionna RT
project. It focuses on prerequisites and the order of the major branches. For
script-by-script commands, use [Script Reference](script_reference.md), the
experiment guides, and the canonical perception sections in
[Pipeline Overview](pipeline_overview.md), [Configuration](configuration.md),
and [Troubleshooting](troubleshooting.md).

## Prerequisites

Run commands from the repository root. Keep these tools available:

- Python 3
- a Sionna RT + Mitsuba-capable Python environment
- Blender for mesh conversion and actor export
- Gazebo Sim plus the `gz` CLI
- `g++` or `clang++` for the perception topic-capture helper
- an NVIDIA-capable setup if you want Gazebo rendering or GPU-backed RT

Recommended shell setup:

```bash
export SIONNA_PYTHON="$HOME/miniconda3/envs/your_env_name/bin/python"
export COLLABPAPER_PYTHON="$SIONNA_PYTHON"
export BLENDER=blender
source rt_out/scripts/ops/setup_gazebo_env.sh
```


## Typical Tooling

These are current working examples rather than strict requirements:

- Blender 4.5.x
- Gazebo Sim with the `gz` CLI
- Mitsuba variant ending in `_ad_mono_polarized`
- a CUDA-capable environment for Sionna RT where applicable

## Workflow Map

1. Run or validate the static RT path.
2. Build the rigid Panda/UR5 dynamic branch.
3. Add the actor-aware branch if human motion is needed.
4. Run the semantic/object-aware experiment branches.
5. Optionally run the panoptic perception pilot.

## Core Inputs

The main project expects:

- `myworld_rt.sdf`
- `models/`
- `rt_out/config/dynamic_prototype_config.json`
- `rt_out/config/prototype_radio_sites.json`
- `rt_out/config/rt_material_mapping.json`
- `rt_out/materials/material_map.json`

Actor-aware work also expects:

- `rt_out/config/actor_dynamic_config.json`
- actor assets under `models/`
- Gazebo actor entries in `myworld_rt.sdf`

The perception pilot additionally uses:

- `rt_out/experiments/perception_rt_small_v0/configs/perception_dataset_config.json`
- `rt_out/experiments/perception_rt_small_v0/configs/camera_rig.json`
- `rt_out/experiments/perception_rt_small_v0/configs/semantic_label_map.json`

## Minimal Branch Order

Static RT foundation:

```bash
python3 rt_out/scripts/static_scene/00_extract_scene_manifests.py
python3 rt_out/scripts/static_scene/01_validate_scene_manifests.py
python3 rt_out/scripts/static_scene/02_build_scene_geometry_registry.py
python3 rt_out/scripts/static_scene/03_build_static_scene_registry.py
python3 rt_out/scripts/static_scene/20_merge_static_scene_by_material.py
python3 rt_out/scripts/static_scene/23_build_static_sionna_xml.py
python3 rt_out/scripts/static_scene/24_run_sionna_rt_sanity.py --xml rt_out/static_scene/export/static_scene_sionna.xml
```

Rigid prototype:

```bash
python3 rt_out/scripts/dynamic_rigid/30_build_prototype_dynamic_frames.py
python3 rt_out/scripts/dynamic_rigid/31_build_prototype_dynamic_visual_frames.py
python3 rt_out/scripts/dynamic_rigid/35_run_prototype_three_frame_rt_sanity.py
python3 rt_out/scripts/dynamic_rigid/36_run_three_frame_three_rx_rt_sanity.py
```

Actor-aware prototype:

```bash
python3 rt_out/scripts/dynamic_actor/40_extract_actor_manifest.py
python3 rt_out/scripts/dynamic_actor/41_build_actor_frame_samples.py
python3 rt_out/scripts/dynamic_rigid/35_run_prototype_three_frame_rt_sanity.py --include-actors
python3 rt_out/scripts/dynamic_rigid/36_run_three_frame_three_rx_rt_sanity.py --include-actors
```

## Experiment Branches

- `semantic_ablation_rigid_200f`: rigid 200-frame experiment
- `semantic_ablation_actor_200f`: actor-aware 200-frame experiment
- `perception_rt_small_v0`: optional Gazebo-native panoptic perception pilot

Use the dedicated experiment docs for long-form command sequences instead of
expanding everything in this page.

## Perception Pilot Pointer

For the finalized perception pilot, use these `docs/` pages together:

- [Pipeline Overview](pipeline_overview.md) for branch context and current
  pilot status
- [Script Reference](script_reference.md) for the active renamed perception
  scripts, utilities, and helpers
- [Configuration](configuration.md) for camera/world/config contracts
- [Troubleshooting](troubleshooting.md) for capture/validation pitfalls

## Basic Validation Checks

Useful quick checks:

```bash
python3 rt_out/scripts/static_scene/01_validate_scene_manifests.py
find rt_out/scripts -name '*.py' -print0 | xargs -0 python3 -m py_compile
bash -n rt_out/scripts/ops/setup_gazebo_env.sh
bash -n rt_out/scripts/ops/run_gazebo_gpu.sh
```

If Gazebo rendering is involved, it is worth watching:

```bash
watch -n 1 nvidia-smi
```

For branch-specific failures, use [Troubleshooting](troubleshooting.md).
