# Gazebo-To-Sionna RT Pipeline

This repository builds a Gazebo-to-Sionna RT pipeline for generating object-aware wireless datasets from 3D simulation scenes. It connects Gazebo scene geometry, rigid and actor-aware dynamics, and perception-side artifacts to Sionna RT ray-tracing outputs, RT-derived wireless labels, semantic/object-aware descriptors, and pilot perception products that can support downstream wireless learning and control workflows.

## What the project does

The project turns Gazebo scene structure, dynamics, and selected perception outputs into Sionna RT wireless data, then derives labels and features that support object-aware wireless prediction, analysis, and control experiments.

## Main capabilities

- Static Gazebo/SDF scene export and Sionna RT validation
- Rigid Panda/UR5 dynamic frame export and multi-frame RT evaluation
- Actor-aware export for a moving human branch layered onto the rigid scene
- Semantic/object-aware feature generation
- Raw occupancy baseline generation
- RT-derived wireless labels
- Panoptic perception pilot on top of the actor-aware RT branch
- RGB-D, synchronized RGB/PCL, and final labeled colorized point-cloud products where currently implemented

## Current Validated Branches And Status

- Static scene branch
- Rigid Panda/UR5 branch
- Actor-aware branch
- `semantic_ablation_rigid_200f`
- `semantic_ablation_actor_200f`
- `perception_rt_small_v0` as a pilot extension, not a replacement for the validated RT baselines

## Current Results Snapshot

- Adaptation trigger F1: compact object-aware `0.411` vs raw occupancy `0.272`
- Path change F1: compact object-aware `0.582` vs raw occupancy `0.527`
- Actor-aware compact path-change F1 vs rigid compact baseline: `0.582` vs `0.509`

## Perception / Panoptic Pilot Status

- Experiment: `rt_out/experiments/perception_rt_small_v0`
- Selected frames: `20`
- Fixed cameras: `8`
- Expected perception samples: `160`
- Final useful output: synchronized, labeled, colorized point clouds with fields `x y z red green blue class_label instance_id`

The perception branch is a pilot extension layered on top of the actor-aware RT outputs. It extends the validated RT workflow with Gazebo-native panoptic capture and synchronized labeled point-cloud products, but it does not replace the validated RT baselines.

## Repository Structure

```text
docs/                    Canonical project documentation
models/                  Gazebo models, robots, actors, and scene assets
plugins/                 Gazebo plugin sources/build artifacts
rt_out/scripts/          Static, dynamic, experiment, ops, validation, and perception scripts
rt_out/experiments/      Experiment outputs, validation artifacts, and pilot branches
myworld.sdf              Main Gazebo world
myworld_rt.sdf           RT-oriented Gazebo world input
run_myworld.sh           Gazebo launch helper
run_myworld_rt.sh        RT-world launch helper
```

## Environment Setup

Run commands from the repository root with a manually prepared environment. At minimum, keep Python 3, a Sionna RT + Mitsuba-capable Python environment, Blender, Gazebo Sim with the `gz` CLI, and a C++ compiler such as `g++` or `clang++` available. If you plan to run Gazebo rendering or GPU-backed RT, use an NVIDIA-capable setup.

Typical shell setup:

```bash
export SIONNA_PYTHON="$HOME/miniconda3/envs/your_env_name/bin/python"
export COLLABPAPER_PYTHON="$SIONNA_PYTHON"
export BLENDER=blender
source rt_out/scripts/ops/setup_gazebo_env.sh
```

## Quick Start

Start with the canonical docs rather than treating this page as the full runbook:

- [Getting Started](docs/getting_started.md)
- [Pipeline Overview](docs/pipeline_overview.md)

Useful validated entry commands from the current docs include:

```bash
python3 rt_out/scripts/static_scene/00_extract_scene_manifests.py
python3 rt_out/scripts/static_scene/01_validate_scene_manifests.py
python3 rt_out/scripts/static_scene/23_build_static_sionna_xml.py
python3 rt_out/scripts/static_scene/24_run_sionna_rt_sanity.py --xml rt_out/static_scene/export/static_scene_sionna.xml
```

For rigid, actor-aware, experiment, and perception branches, follow the branch-specific documentation below.

## Documentation

- [Getting Started](docs/getting_started.md)
- [Pipeline Overview](docs/pipeline_overview.md)
- [Configuration](docs/configuration.md)
- [Script Reference](docs/script_reference.md)
- [Developer Guide](docs/developer_guide.md)
- [Actor-Aware 3-Frame Pipeline](docs/actor_aware_3frame_pipeline.md)
- [Semantic Ablation 200f Pipeline](docs/semantic_ablation_200f_pipeline.md)
- [Actor-Aware Semantic Ablation 200f Pipeline](docs/semantic_ablation_actor_200f_pipeline.md)
- [Actor vs Rigid Ablation Comparison](docs/actor_vs_rigid_ablation_comparison.md)
- [Troubleshooting](docs/troubleshooting.md)

## Citation / Academic Use

If you use this repository, please cite the associated paper once available.

## License

This repository is lincensed under the MIT(LICENSE) conditions.
