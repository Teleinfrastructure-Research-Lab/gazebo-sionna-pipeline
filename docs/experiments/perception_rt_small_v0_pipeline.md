# Perception and RT small-run runbook

## 1. Experiment purpose

This workflow captures Gazebo-native panoptic and synchronized RGB/point-cloud data, reconstructs labeled colorized point clouds, and indexes them against RT data.

## 2. Execution modes

- Inspect extracted capture, reconstruction, validation, and index outputs.
- Print the ordered command plan with `--dry-run`.
- Capture only while a compatible Gazebo world is already running.

## 3. Required source inputs

| Source input | Location | Consuming script | Validation |
|---|---|---|---|
| Perception configuration | `<RUN_ROOT>/config/perception_dataset_config.json` | all stages | JSON parse |
| Camera/semantic configuration | `<RUN_ROOT>/config/` | world/capture stages | JSON parse |
| Repository world and models | `myworld_rt.sdf`, `models/` | world and Gazebo | `test -f`, `test -d` |
| Source RT experiment named by configuration | configuration value | selection/index stages | `test -d` |
| Running Gazebo process | Terminal 1 | capture scripts | `gz topic -l` |

## 4. Generated artifact chain

| Generated artifact | Producing command | Output path | Consumed by |
|---|---|---|---|
| Selected frames | `select_perception_frames.py` | `frames/selected_frames.json` | registry |
| Instance registry | `build_perception_instance_registry.py` | `frames/instance_registry.json` | world/capture |
| Labeled SDF | `build_labeled_gazebo_world.py` | `perception_sdf/` | Gazebo |
| Panoptic/synchronized captures | capture scripts | `perception_raw/native/` | validators/reconstruction |
| Labeled PLYs | reconstruction builder | `reconstruction/labeled_colorized_pcl_sync/` | validator/index |
| Dataset index | index builder | `dataset_index/` | inspection |

## 5. Environment prerequisites

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"
python3 --version
command -v gz
command -v g++
command -v pkg-config
test -f myworld_rt.sdf
test -d models
df -h "$REPO_ROOT"
```

## 6. Run variables, 7. create the run root, and 8. configuration

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
REFERENCE_RUN_ROOT="$REPO_ROOT/rt_out/experiments/perception_rt_small_v0/run_20260522_133045"
SOURCE_EXPERIMENT_ROOT="$REPO_ROOT/rt_out/experiments/semantic_ablation_200f/run_20260522_143156/semantic_ablation/semantic_ablation_actor_200f"
RUN_ROOT="$REPO_ROOT/rt_out/experiments/perception_rt_small_v0/run_example"
SOURCE_CONFIG="$REFERENCE_RUN_ROOT/config/perception_dataset_config.json"
CONFIG="$RUN_ROOT/config/perception_dataset_config.json"
mkdir -p "$RUN_ROOT/config"
cp "$SOURCE_CONFIG" "$CONFIG"
cp "$REFERENCE_RUN_ROOT/config/camera_rig.json" "$RUN_ROOT/config/"
cp "$REFERENCE_RUN_ROOT/config/semantic_label_map.json" "$RUN_ROOT/config/"
python3 - "$CONFIG" "$REPO_ROOT" "$SOURCE_EXPERIMENT_ROOT" <<'PY'
import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
repo_root = Path(sys.argv[2]).resolve()
source_root = Path(sys.argv[3]).resolve()
payload = json.loads(config_path.read_text(encoding="utf-8"))
payload["source_experiment"] = str(source_root.relative_to(repo_root))
config_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
python3 -m json.tool "$CONFIG" >/dev/null
```

The actual perception config contains no `output_dir`, world-path, camera-rig-path, or semantic-map-path field: these scripts derive generated paths from `CONFIG.parent.parent`, which is `RUN_ROOT`, and load `config/camera_rig.json` and `config/semantic_label_map.json`. The rewrite changes the only stale path, `source_experiment`.

## 9. Preflight

```bash
set -euo pipefail
test -f "$CONFIG"
test -f "$REPO_ROOT/myworld_rt.sdf"
test -d "$REPO_ROOT/models"
test -d "$SOURCE_EXPERIMENT_ROOT"
test -f "$SOURCE_EXPERIMENT_ROOT/frames/sampled_frames.json"
test -f "$SOURCE_EXPERIMENT_ROOT/frames/dynamic_visual_frames.json"
test -f "$SOURCE_EXPERIMENT_ROOT/frames/actor_frame_samples.json"
test -f "$RUN_ROOT/config/camera_rig.json"
test -f "$RUN_ROOT/config/semantic_label_map.json"
python3 -m json.tool "$CONFIG" >/dev/null
python3 rt_out/scripts/perception/run_perception_pipeline.py --config "$CONFIG" --expected-cloud-count 24 --dry-run
```

## 10. Smoke workflow

```bash
python3 rt_out/scripts/perception/run_perception_pipeline.py --config "$CONFIG" --expected-cloud-count 24 --dry-run
```

## 11. Complete workflow

In Terminal 2, create the labeled world:

```bash
python3 rt_out/scripts/perception/capture/select_perception_frames.py --config "$CONFIG"
python3 rt_out/scripts/perception/capture/build_perception_instance_registry.py --config "$CONFIG"
python3 rt_out/scripts/perception/capture/build_labeled_gazebo_world.py --config "$CONFIG" --build-stable-instance-panoptic-world
```

In Terminal 1, start and verify Gazebo:

```bash
gz sim -r "$RUN_ROOT/perception_sdf/gazebo_native_stable_instance_panoptic_world.sdf"
gz topic -l | grep -E 'camera|panoptic|point'
```

Stop it with `Ctrl-C` after Terminal 2 completes capture. In Terminal 2, run each command only after its previous input exists:

```bash
python3 rt_out/scripts/perception/capture/capture_panoptic_topics.py --config "$CONFIG"
python3 rt_out/scripts/perception/capture/validate_panoptic_capture.py --config "$CONFIG" --write-diagnostics
python3 rt_out/scripts/perception/capture/capture_synchronized_stable_instance_rgb_pcl.py --config "$CONFIG"
python3 rt_out/scripts/perception/capture/validate_synchronized_stable_instance_rgb_pcl.py --config "$CONFIG"
python3 rt_out/scripts/perception/reconstruction/build_labeled_colorized_point_cloud.py --config "$CONFIG"
python3 rt_out/scripts/perception/reconstruction/validate_labeled_colorized_point_cloud.py --config "$CONFIG" --expected-cloud-count 24
python3 rt_out/scripts/perception/reconstruction/build_panoptic_dataset_index.py --config "$CONFIG"
```

The orchestrator is an ordered planner after Gazebo is available; it does not launch Gazebo.

## 12. Restart and overwrite behavior

Capture and reconstruction commands expose `--force` where overwriting is supported. Do not use it in the reference tree; generate into a separate run root.

## 13. Output inventory

The extracted tree contains selected-frame and registry JSON, SDF files, capture indexes, validation reports, final labeled PLYs, and dataset-index CSV/JSON. The final labeled PCL index has 24 rows.

## 14. Troubleshooting

- No capture topics: verify Terminal 1 and `gz topic -l`.
- Missing generated SDF: run the labeled-world builder before `gz sim`.
- Fewer than 24 clouds: run the synchronized and final-cloud validators before building the index.

## 15. Genuine limitations

The orchestrator does not start Gazebo. A copied configuration may name a source RT experiment that must exist for selection/index operations.

## 16. Related documentation

- [Actor-aware 2,446-frame runbook](semantic_ablation_actor_2446f_10hz_pipeline.md)
