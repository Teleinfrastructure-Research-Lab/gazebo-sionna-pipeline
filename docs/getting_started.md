# Getting started

This page helps you choose the right guide. The executable workflow is
[pipeline_execution_order.md](pipeline_execution_order.md).

## Prerequisites

Run from the repository root with:

- Python 3 with `numpy`; add `scikit-learn`, PyTorch, or XGBoost only for the
  optional later stages that use them.
- Gazebo Sim and the `gz` CLI for world execution and pose/topic capture.
- Blender for mesh conversion, rigid export, actor export, and Blender
  inspection workers.
- A Sionna RT/Mitsuba Python environment for XML/RT stages. Set
  `SIONNA_PYTHON`; the code also accepts the older `COLLABPAPER_PYTHON` variable.
- A C++17 compiler and `pkg-config` entries for `gz-transport` and `gz-msgs`
  for the perception capture helpers. OpenCV4 is optional in the build
  helpers.

The repository does not contain a pinned lockfile or a complete environment
manifest. Record the interpreter, Blender, Gazebo, Sionna, Mitsuba, compiler,
and package versions in the run metadata when publishing a result.

## Environment setup

```bash
REPO_ROOT="$(pwd)"
EXPERIMENT_NAME="<experiment_name>"
RUN_ID="run_$(date +%Y%m%d_%H%M%S)"
RUN_ROOT="$REPO_ROOT/rt_out/experiments/$EXPERIMENT_NAME/$RUN_ID"
SIONNA_PYTHON="<path-to-sionna-python>"
BLENDER="<path-to-blender>"

export PIPELINE_RUN_DIR="$RUN_ROOT"
export SIONNA_PYTHON BLENDER
source rt_out/scripts/ops/setup_gazebo_env.sh
mkdir -p "$RUN_ROOT"
```

The current code requires an explicit run root for generated-output helpers;
it rejects `rt_out` itself and the obsolete `current_experiment` convention.
There is no generic run-initialization CLI, so configuration files must be
copied or prepared in `"$RUN_ROOT/config"` by the user.

## Shortest safe validation

```bash
python3 -m compileall -q rt_out/scripts scripts
find rt_out/scripts -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n
python3 rt_out/scripts/perception/run_perception_pipeline.py \
  --config rt_out/experiments/perception_rt_small_v0/run_20260522_133045/config/perception_dataset_config.json \
  --expected-cloud-count 24 --dry-run
```

The last command reads the saved pilot path only if that run has been
unpacked. It prints commands and performs no capture.

## Choose a workflow

- Use [pipeline_execution_order.md](pipeline_execution_order.md) for the
  complete prepared-Gazebo-scene workflow.
- Use [semantic_ablation_actor_2446f_10hz_pipeline.md](experiments/semantic_ablation_actor_2446f_10hz_pipeline.md)
  for the current validated experiment.
- Use [actor_aware_3frame_pipeline.md](experiments/actor_aware_3frame_pipeline.md) for the
  three-frame actor test.
- Use the 200-frame guides only to inspect the archives or older results; their
  required scripts are not present in this repository version.
- Use [perception_rt_small_v0_pipeline.md](experiments/perception_rt_small_v0_pipeline.md)
  for the separate partial-coverage perception pilot.

The complete command and argument lists are in
[script_reference.md](script_reference.md).
