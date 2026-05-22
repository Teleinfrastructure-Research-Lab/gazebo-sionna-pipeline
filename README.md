# Gazebo-To-Sionna RT Pipeline

This repository provides a Gazebo-to-Sionna RT pipeline for building
object-aware wireless datasets from 3D simulation scenes. The core project is
the validated RT stack: static scene export, rigid Panda/UR5 dynamics,
actor-aware extensions, and the semantic/object-aware experiment branches. The
new `perception_rt_small_v0` branch is a pilot extension that adds Gazebo-native
panoptic perception capture; it does not replace the existing RT baselines.

## Current Validated Branches

- Static scene branch: Gazebo/SDF scene extraction, mesh/material export, and
  Sionna RT validation.
- Rigid Panda/UR5 branch: frame-wise rigid robot placement and RT generation
  from pose logs.
- Actor-aware branch: static scene + Panda/UR5 + moving human actor, with
  actor handling kept separate from rigid dynamics because Gazebo actors are
  animated skinned meshes.
- `semantic_ablation_rigid_200f`: validated 200-frame rigid experiment with
  RT outputs, labels, object-aware features, and raw occupancy features.
- `semantic_ablation_actor_200f`: validated 200-frame actor-aware experiment
  with RT outputs, labels, object-aware features, and raw occupancy features.
- `perception_rt_small_v0`: pilot Gazebo-native panoptic perception branch
  built on top of the actor-aware experiment outputs.

## Current Branch Snapshot

- Stable foundation: the static, rigid, and actor-aware RT branches.
- Important current actor-aware pilot result:
  - adaptation trigger F1: compact object-aware `0.411` vs raw occupancy `0.272`
  - path change F1: compact object-aware `0.582` vs raw occupancy `0.527`
  - actor-aware compact path-change F1 vs rigid compact baseline:
    `0.582` vs `0.509`
- Panoptic perception pilot:
  - experiment: `rt_out/experiments/perception_rt_small_v0`
  - selected frames: `20`
  - fixed cameras: `8`
  - expected perception samples: `160`
  - primary world:
    `rt_out/experiments/perception_rt_small_v0/perception_sdf/gazebo_native_panoptic_world.sdf`
  - primary raw output:
    `rt_out/experiments/perception_rt_small_v0/perception_raw/native/panoptic/`

## Environment Setup

The repository expects a manually prepared environment. At minimum, keep these
tools available:

- Python 3 for orchestration, manifests, features, and validation
- a Sionna RT + Mitsuba-capable Python interpreter
- Blender for mesh conversion and actor export helpers
- Gazebo Sim plus the `gz` CLI
- a C++ compiler such as `g++` or `clang++` for the panoptic topic-capture helper
- an NVIDIA-capable setup if you plan to run Gazebo rendering or GPU-backed RT

Typical shell setup:

```bash
export SIONNA_PYTHON="$HOME/miniconda3/envs/your_env_name/bin/python"
export COLLABPAPER_PYTHON="$SIONNA_PYTHON"
export BLENDER=blender
```

For Gazebo launches:

```bash
source rt_out/scripts/ops/setup_gazebo_env.sh
bash run_myworld_rt.sh
bash rt_out/scripts/ops/run_gazebo_gpu.sh \
  rt_out/experiments/perception_rt_small_v0/perception_sdf/gazebo_native_panoptic_world.sdf
```

## Workflow Map

1. Validate the static scene export path.
2. Build and validate the rigid Panda/UR5 dynamic branch.
3. Add the actor-aware branch when human motion is needed.
4. Run the semantic/object-aware experiment branches for RT, labels, and
   features.
5. Optionally run the `perception_rt_small_v0` panoptic pilot.

Detailed command sequences live in the docs listed below rather than in this
top-level README.

## Documentation

- [Getting Started](docs/getting_started.md): prerequisites, setup, and the
  high-level workflow map.
- [Pipeline Overview](docs/pipeline_overview.md): the whole-project pipeline,
  repository structure, and validated branches.
- [Configuration](docs/configuration.md): main configs for static, dynamic,
  actor-aware, experiment, and perception branches.
- [Script Reference](docs/script_reference.md): compact reference for the main
  script groups.
- [Developer Guide](docs/developer_guide.md): internal contracts and extension
  guidance.
- [Actor-Aware 3-Frame Pipeline](docs/actor_aware_3frame_pipeline.md): actor
  prototype details and alignment caveats.
- [Semantic Ablation 200f Pipeline](docs/semantic_ablation_200f_pipeline.md):
  rigid experiment workflow.
- [Actor-Aware Semantic Ablation 200f Pipeline](docs/semantic_ablation_actor_200f_pipeline.md):
  actor-aware experiment workflow.
- [Perception Script README](rt_out/scripts/perception/README.md): active
  panoptic perception workflow.
- [Perception Pilot README](rt_out/experiments/perception_rt_small_v0/README.md):
  experiment-local perception status.
- [Troubleshooting](docs/troubleshooting.md): environment, Gazebo, actor, RT,
  and perception issues.

## Limitations

- The rigid dynamic branch is configured around the current Panda/UR5 setup and
  pose-log format.
- Actor handling is intentionally separate from rigid dynamics because Gazebo
  actors are animated skinned meshes rather than rigid link-pose records.
- The actor-aware export path uses approximate offline actor mesh placement and
  should not be described as perfect Gazebo runtime animation-phase matching.
