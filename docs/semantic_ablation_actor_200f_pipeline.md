# Actor-Aware Semantic Ablation 200f Pipeline

This document describes the validated `semantic_ablation_actor_200f` experiment
branch. It reuses the rigid 200-frame branch structure but adds a moving human
actor to the composed scene.

## Scope

- static scene: same frozen validated static baseline as the rigid branch
- rigid dynamics: same Panda/UR5 motion and TX/RX setup as the rigid branch
- actor dynamics: one moving human actor baked into each selected frame
- RT setup: same 28 GHz multi-RX batch runner and label definitions
- features: object-aware compact features and raw occupancy features
- outputs: experiment-local meshes, composed manifests, XML, RT, labels, and features

## How It Differs From The Rigid Branch

- rigid branch: static scene + Panda/UR5 only
- actor-aware branch: static scene + Panda/UR5 + moving human actor
- actor sampling is offline and frame-list based
- actor export uses:
  - `alignment_policy = bounds_center_xy_to_root`
  - `z_alignment_policy = bounds_min_z_to_floor`
  - `floor_z = 0.1`

This branch is a stress test for object-aware side information under human
motion, not a different radio stack.

## Validation Status

The actor-aware 200-frame branch has been validated through:

- `200` rigid mesh exports
- `200` actor mesh exports
- `200` actor-composed manifests
- `200` Sionna XMLs
- `1200` RT rows = `200` frames x `6` RX
- all RT rows `sanity_ok=True`
- zero missing tau/gain rows
- `1194` labeled rows = `199` transitions x `6` RX
- `1194` object-feature rows with actor objects included
- `1194` raw occupancy feature rows

## End-To-End Commands

```bash
CONFIG=rt_out/experiments/semantic_ablation_actor_200f/configs/experiment_config.json

python3 rt_out/scripts/experiments/exp_sample_frames.py --config "$CONFIG"

python3 rt_out/scripts/dynamic_rigid/30_build_prototype_dynamic_frames.py \
  --frames-json rt_out/experiments/semantic_ablation_actor_200f/frames/sampled_frames.json \
  --output rt_out/experiments/semantic_ablation_actor_200f/frames/dynamic_frames.json

python3 rt_out/scripts/dynamic_rigid/31_build_prototype_dynamic_visual_frames.py \
  --frames-json rt_out/experiments/semantic_ablation_actor_200f/frames/sampled_frames.json \
  --dynamic-frames rt_out/experiments/semantic_ablation_actor_200f/frames/dynamic_frames.json \
  --output rt_out/experiments/semantic_ablation_actor_200f/frames/dynamic_visual_frames.json

python3 rt_out/scripts/experiments/exp_build_actor_frame_samples.py \
  --config "$CONFIG"

BLENDER=blender \
python3 rt_out/scripts/experiments/exp_export_dynamic_meshes_batch.py \
  --config "$CONFIG" \
  --include-actors

python3 rt_out/scripts/experiments/exp_compose_frame_manifests_batch.py \
  --config "$CONFIG" \
  --include-actors

python3 rt_out/scripts/experiments/exp_build_sionna_xml_batch.py \
  --config "$CONFIG"

Replace `/path/to/your/sionna/python` with the Python interpreter from an
environment where Sionna RT and Mitsuba are installed. You can also set SIONNA_PYTHON 
to that interpreter path; COLLABPAPER_PYTHON remains supported as a legacy alias.

/path/to/your/sionna/python \
  rt_out/scripts/experiments/exp_run_rt_multi_rx_batch.py \
  --config "$CONFIG"

python3 rt_out/scripts/experiments/exp_build_rt_labels.py \
  --config "$CONFIG"

python3 rt_out/scripts/experiments/exp_build_object_features.py \
  --config "$CONFIG"

python3 rt_out/scripts/experiments/exp_build_raw_occupancy_features.py \
  --config "$CONFIG"
```

## Debug Examples

Use the same config with `--max-frames 3` or `--max-frames 20` for debug runs:

```bash
BLENDER=blender \
python3 rt_out/scripts/experiments/exp_export_dynamic_meshes_batch.py \
  --config "$CONFIG" \
  --include-actors \
  --max-frames 3

python3 rt_out/scripts/experiments/exp_compose_frame_manifests_batch.py \
  --config "$CONFIG" \
  --include-actors \
  --max-frames 3

python3 rt_out/scripts/experiments/exp_build_sionna_xml_batch.py \
  --config "$CONFIG" \
  --max-frames 3

/path/to/your/sionna/python \
  rt_out/scripts/experiments/exp_run_rt_multi_rx_batch.py \
  --config "$CONFIG" \
  --max-frames 3
```

```bash
BLENDER=blender \
python3 rt_out/scripts/experiments/exp_export_dynamic_meshes_batch.py \
  --config "$CONFIG" \
  --include-actors \
  --max-frames 20

python3 rt_out/scripts/experiments/exp_compose_frame_manifests_batch.py \
  --config "$CONFIG" \
  --include-actors \
  --max-frames 20

python3 rt_out/scripts/experiments/exp_build_sionna_xml_batch.py \
  --config "$CONFIG" \
  --max-frames 20

/path/to/your/sionna/python \
  rt_out/scripts/experiments/exp_run_rt_multi_rx_batch.py \
  --config "$CONFIG" \
  --max-frames 20
```

## Expected Counts

- sampled frames: `200`
- RT rows: `1200`
- labeled rows: `1194`

Debug RT runs still write to `rt_200frames_multi_rx.csv`, so verify the row
count before building labels or features.

## Label Comparison Against The Rigid Branch

- `y_path_change`: rigid `213` positives, actor `314` positives, `107` changed rows
- `y_path_drop`: rigid `102` positives, actor `150` positives, `52` changed rows
- `y_adaptation_trigger_1db`: rigid `46` positives, actor `52` positives, `6` changed rows
- actor motion affects path-structure labels much more than the power-drop and adaptation-trigger labels

## Ablation Commands

```bash
python3 rt_out/scripts/experiments/exp_run_semantic_ablation.py \
  --config "$CONFIG" \
  --target y_adaptation_trigger_1db \
  --rx-filter rx_panda_base,rx_ur5_base \
  --feature-mode compact \
  --models logistic,rf,svm

python3 rt_out/scripts/experiments/exp_run_semantic_ablation.py \
  --config "$CONFIG" \
  --target y_adaptation_trigger_1db \
  --rx-filter rx_panda_base,rx_ur5_base \
  --feature-mode raw \
  --models logistic,rf,svm

python3 rt_out/scripts/experiments/exp_run_semantic_ablation.py \
  --config "$CONFIG" \
  --target y_path_change \
  --rx-filter rx_panda_base,rx_ur5_base,rx_nao_chest \
  --feature-mode compact \
  --models logistic,rf,svm

python3 rt_out/scripts/experiments/exp_run_semantic_ablation.py \
  --config "$CONFIG" \
  --target y_path_change \
  --rx-filter rx_panda_base,rx_ur5_base,rx_nao_chest \
  --feature-mode raw \
  --models logistic,rf,svm
```

## Ablation Snapshot

Results are presented below:

| Task | Feature Mode / Model | F1 | Balanced Accuracy |
| --- | --- | --- | --- |
| adaptation trigger | compact full object-aware + RF | `41.1%` | `65.8%` |
| adaptation trigger | raw occupancy + RBF-SVM | `27.2%` | `61.1%` |
| path change | compact full object-aware + RF | `58.2%` | `65.9%` |
| path change | raw occupancy + LR | `52.7%` | `56.8%` |

Compared with the rigid branch:

- compact object-aware adaptation-trigger F1 improved from `39.3` to `41.1`
- compact object-aware path-change F1 improved from `50.9` to `58.2`
- raw occupancy improved only slightly, while compact object-aware features became clearly stronger in the actor-aware branch

