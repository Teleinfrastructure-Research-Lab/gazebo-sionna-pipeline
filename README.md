# Gazebo–Sionna RT pipeline

This repository contains a Gazebo scene-to-Sionna RT workflow, rigid and
actor-aware frame processing, labeled ground-truth scene point clouds, wireless
labels, feature builders, optional classical ML experiments, and a separate
Gazebo-native perception pilot.

Run commands from the repository root. Generated data belongs below a unique
run directory:

```text
rt_out/experiments/<experiment_name>/<run_id>/
```

The repository source tree contains the scripts, configuration templates,
Gazebo models, and documentation. Large meshes, XML batches, point clouds, RT
tables, features, models, and predictions are generated outputs. They are not
source-code inputs unless a guide explicitly names them.

## Documentation guides

- [Complete execution sequence](docs/pipeline_execution_order.md): one
  end-to-end workflow from a prepared Gazebo scene to PCL and RT products.
- [Getting started](docs/getting_started.md): prerequisites and navigation.
- [Pipeline overview](docs/pipeline_overview.md): architecture and workflow
  relationships only.
- [Configuration reference](docs/configuration.md): owners, fields, and rerun
  consequences.
- [Script reference](docs/script_reference.md): every file under
  `rt_out/scripts/` and `scripts/`, including arguments and roles.
- [Troubleshooting](docs/troubleshooting.md): safe checks and recovery.

Standalone experiment guides:

- [2,446-frame actor-aware semantic-ablation experiment](docs/experiments/semantic_ablation_actor_2446f_10hz_pipeline.md)
- [Three-frame actor prototype](docs/experiments/actor_aware_3frame_pipeline.md)
- [200-frame rigid semantic-ablation experiment](docs/experiments/semantic_ablation_200f_pipeline.md)
- [200-frame actor-aware semantic-ablation experiment](docs/experiments/semantic_ablation_actor_200f_pipeline.md)
- [Perception pilot](docs/experiments/perception_rt_small_v0_pipeline.md)

Recorded results are kept separate from execution instructions:

- [Actor versus rigid ablation results](docs/experiments/actor_vs_rigid_ablation_comparison.md)

## Minimal environment check

```bash
python3 --version
python3 -m compileall -q rt_out/scripts scripts
find rt_out/scripts -type f -name '*.sh' -print0 | xargs -0 -n1 bash -n
```

Gazebo, Blender, and Sionna RT are required only for the stages that use
them. Do not run the full RT or generation workflow as an installation test;
use the dry-run and validation commands in the complete execution guide first.

## Static registry interfaces

The static registry builders accept explicit input and output paths. Use
`build_scene_geometry_registry.py` with `--static-manifest`,
`--dynamic-manifest`, `--models-root`, and `--output`. Use
`build_static_scene_registry.py` with `--geometry-registry`, `--material-map`,
`--output`, `--project-root`, and `--converted-mesh-root`. The 2,446-frame and
200-frame results remain in archives; their guides document the available
processing stages and the input, path, and configuration adaptation required
before a clean rerun.

## Citation / Academic Use

If you use this repository, please cite the associated paper once available.

## License

This repository is licensed under the MIT License.
