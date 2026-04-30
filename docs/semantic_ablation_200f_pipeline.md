# Semantic Ablation 200f Pipeline

## Scope and limitations

- Experiment branch: `semantic_ablation_rigid_200f`
- Static scene: frozen validated rigid baseline
- Dynamic scope: rigid `Panda` + `ur5_rg2` only
- Actors are not integrated into this experiment path
- Point-cloud generation is not part of the current branch
- No no-go-zone logic is implemented here
- No full beamforming or resource-allocation implementation is claimed here
- The current study evaluates adaptation-trigger and propagation-change prediction as an intermediate feasibility task

This branch should be read as an experiment-local extension of the validated
Gazebo-to-Sionna prototype. It reuses the frozen static baseline and the
validated Panda/UR5 dynamic path, then scales that workflow to 200 sampled
frames and 6 receiver locations.

## Generated-output hygiene

- Do not commit dynamic mesh exports, per-frame XMLs, RT CSVs, feature tables, or result CSVs unless you intentionally mean to version a small text artifact
- The experiment wrappers are designed to reuse the validated low-level scripts without rewriting the frozen static baseline
- The historical filename `rt_100frames_multi_rx.csv` is kept for downstream compatibility even in the 200-frame branch

## Current radio setup

- Frequency: `28 GHz`
- `tx_power_dbm`: defaults to `30 dBm` unless overridden in `experiment_config.json`

### TX

- `tx_ap = [0.0, 0.0, 2.4]`

### RXs

- `rx_panda_base = [0.582, 0.888, 1.195]`
- `rx_ur5_base = [0.497, -0.841, 0.995]`
- `rx_cerberus_base = [4.074, -1.779, 0.81]`
- `rx_nao_chest = [-0.1337, 2.748, 0.7]`
- `rx_human_chest = [-1.4605, -0.8406, 1.6421]`
- `rx_x500_body = [-3.9279, 3.2024, 1.3944]`

## End-to-end commands for `semantic_ablation_rigid_200f`

Run these from the repository root.

### 1. Validate config

```bash
python3 -m json.tool rt_out/experiments/semantic_ablation_rigid_200f/configs/experiment_config.json > /tmp/checked_experiment_config_200f.json
```

### 2. Sample frames

```bash
python3 rt_out/scripts/exp_sample_frames.py \
  --config rt_out/experiments/semantic_ablation_rigid_200f/configs/experiment_config.json
```

### 3. Build dynamic frames

```bash
python3 rt_out/scripts/30_build_prototype_dynamic_frames.py \
  --frames-json rt_out/experiments/semantic_ablation_rigid_200f/frames/sampled_frames.json \
  --output rt_out/experiments/semantic_ablation_rigid_200f/frames/dynamic_frames.json
```

### 4. Build dynamic visual frames

```bash
python3 rt_out/scripts/31_build_prototype_dynamic_visual_frames.py \
  --frames-json rt_out/experiments/semantic_ablation_rigid_200f/frames/sampled_frames.json \
  --dynamic-frames rt_out/experiments/semantic_ablation_rigid_200f/frames/dynamic_frames.json \
  --output rt_out/experiments/semantic_ablation_rigid_200f/frames/dynamic_visual_frames.json
```

### 5. Export dynamic meshes

```bash
BLENDER="$HOME/Documents/blender-4.5.8-linux-x64/blender" \
python3 rt_out/scripts/exp_export_dynamic_meshes_batch.py \
  --config rt_out/experiments/semantic_ablation_rigid_200f/configs/experiment_config.json
```

### 6. Compose frame manifests

```bash
python3 rt_out/scripts/exp_compose_frame_manifests_batch.py \
  --config rt_out/experiments/semantic_ablation_rigid_200f/configs/experiment_config.json
```

### 7. Build Sionna XMLs

```bash
python3 rt_out/scripts/exp_build_sionna_xml_batch.py \
  --config rt_out/experiments/semantic_ablation_rigid_200f/configs/experiment_config.json
```

### 8. Debug RT

```bash
python3 rt_out/scripts/exp_run_rt_multi_rx_batch.py \
  --config rt_out/experiments/semantic_ablation_rigid_200f/configs/experiment_config.json \
  --max-frames 1
```

### 9. Full RT

```bash
python3 rt_out/scripts/exp_run_rt_multi_rx_batch.py \
  --config rt_out/experiments/semantic_ablation_rigid_200f/configs/experiment_config.json
```

### 10. Build labels

```bash
python3 rt_out/scripts/exp_build_rt_labels.py \
  --config rt_out/experiments/semantic_ablation_rigid_200f/configs/experiment_config.json
```

### 11. Build object features

```bash
python3 rt_out/scripts/exp_build_object_features.py \
  --config rt_out/experiments/semantic_ablation_rigid_200f/configs/experiment_config.json
```

### 12. Build raw occupancy features

```bash
python3 rt_out/scripts/exp_build_raw_occupancy_features.py \
  --config rt_out/experiments/semantic_ablation_rigid_200f/configs/experiment_config.json
```

### 13. Main compact ablation

```bash
python3 rt_out/scripts/exp_run_semantic_ablation.py \
  --config rt_out/experiments/semantic_ablation_rigid_200f/configs/experiment_config.json \
  --target y_adaptation_trigger_1db \
  --rx-filter rx_panda_base,rx_ur5_base \
  --feature-mode compact \
  --models logistic,rf,svm
```

### 14. Supporting compact ablation

```bash
python3 rt_out/scripts/exp_run_semantic_ablation.py \
  --config rt_out/experiments/semantic_ablation_rigid_200f/configs/experiment_config.json \
  --target y_path_change \
  --rx-filter rx_panda_base,rx_ur5_base,rx_nao_chest \
  --feature-mode compact \
  --models logistic,rf,svm
```

### 15. Main raw occupancy ablation

```bash
python3 rt_out/scripts/exp_run_semantic_ablation.py \
  --config rt_out/experiments/semantic_ablation_rigid_200f/configs/experiment_config.json \
  --target y_adaptation_trigger_1db \
  --rx-filter rx_panda_base,rx_ur5_base \
  --feature-mode raw \
  --models logistic,rf,svm
```

### 16. Supporting raw occupancy ablation

```bash
python3 rt_out/scripts/exp_run_semantic_ablation.py \
  --config rt_out/experiments/semantic_ablation_rigid_200f/configs/experiment_config.json \
  --target y_path_change \
  --rx-filter rx_panda_base,rx_ur5_base,rx_nao_chest \
  --feature-mode raw \
  --models logistic,rf,svm
```

## Expected row counts

- sampled frames: `200`
- Sionna XMLs: `200`
- RT rows: `1200 = 200 frames x 6 RXs`
- labeled rows: `1194 = 199 transitions x 6 RXs`
- main adaptation ML subset: `398 = 199 transitions x 2 RXs`
- supporting path-change subset: `597 = 199 transitions x 3 RXs`

## Output files

- `rt_out/experiments/semantic_ablation_rigid_200f/frames/sampled_frames.json`
- `rt_out/experiments/semantic_ablation_rigid_200f/frames/dynamic_frames.json`
- `rt_out/experiments/semantic_ablation_rigid_200f/frames/dynamic_visual_frames.json`
- `rt_out/experiments/semantic_ablation_rigid_200f/frames/dynamic_meshes/dynamic_mesh_index.csv`
- `rt_out/experiments/semantic_ablation_rigid_200f/frames/composed_manifests/composed_manifest_index.csv`
- `rt_out/experiments/semantic_ablation_rigid_200f/sionna_xml/sionna_xml_index.csv`
- `rt_out/experiments/semantic_ablation_rigid_200f/rt_results/rt_100frames_multi_rx.csv`
- `rt_out/experiments/semantic_ablation_rigid_200f/rt_results/rt_100frames_multi_rx_labeled.csv`
- `rt_out/experiments/semantic_ablation_rigid_200f/rt_results/rt_label_summary.csv`
- `rt_out/experiments/semantic_ablation_rigid_200f/features/object_features_rt_labels.csv`
- `rt_out/experiments/semantic_ablation_rigid_200f/features/raw_occupancy_features_rt_labels.csv`
- `rt_out/experiments/semantic_ablation_rigid_200f/features/semantic_ablation_results_compact_y_adaptation_trigger_1db_panda_ur5_models_logistic_rf_svm.csv`
- `rt_out/experiments/semantic_ablation_rigid_200f/features/semantic_ablation_results_compact_y_path_change_panda_ur5_nao_chest_models_logistic_rf_svm.csv`
- `rt_out/experiments/semantic_ablation_rigid_200f/features/semantic_ablation_results_raw_y_adaptation_trigger_1db_panda_ur5_models_logistic_rf_svm.csv`
- `rt_out/experiments/semantic_ablation_rigid_200f/features/semantic_ablation_results_raw_y_path_change_panda_ur5_nao_chest_models_logistic_rf_svm.csv`

### Naming wart

`rt_100frames_multi_rx.csv` currently contains 200-frame data under
`semantic_ablation_rigid_200f`. The filename is historical. Do not rename it
unless all downstream scripts are updated together.

Older local runs may also leave result snapshots under `results/` in some
experiment folders. The current `exp_run_semantic_ablation.py` writes its
result CSVs under `features/`.

## Label definitions

- `rx_power_dbm = tx_power_dbm + path_gain_db`
- dBm differences produce dB changes
- `y_rx_power_drop_1db` fires when `previous_rx_power_dbm - current_rx_power_dbm >= 1.0`
- `y_rx_power_drop_2db` fires when `previous_rx_power_dbm - current_rx_power_dbm >= 2.0`
- `delay_spread = tau_max - tau_min`
- `y_delay_spread_increase` fires when delay-spread increase exceeds the experiment-level `eta_tau`
- `y_adaptation_trigger_1db` fires on a 1 dB received-power drop and/or a delay-spread increase
- `y_adaptation_trigger_2db` is the stricter 2 dB variant plus the delay-spread increase criterion
- `y_path_change` marks any change in valid path count between consecutive frames
- `y_path_drop` marks a reduction in valid path count between consecutive frames

## Feature modes

### raw

- unsegmented mesh vertex / occupancy descriptors
- no object identity, semantics, or material labels as features
- approximates raw 3D / LiDAR / occupancy-style baselines

### compact

- object-level descriptors intended to map to object masks / instances
- `compact_geometry`
- `compact_geometry_material`
- `compact_geometry_semantic`
- `compact_full_object_aware`

### wide

- broader object/material/semantic feature families selected by prefix
- mostly diagnostic, not the preferred paper-facing table

## Recommended paper-facing results

### Main adaptation-trigger task

- target: `y_adaptation_trigger_1db`
- RX filter: `rx_panda_base,rx_ur5_base`
- raw occupancy best: SVM-RBF, `F1 ~ 0.261`, `balanced accuracy ~ 0.606`
- compact full object-aware best: Random Forest, `F1 ~ 0.393`, `balanced accuracy ~ 0.648`

### Supporting propagation-change task

- target: `y_path_change`
- RX filter: `rx_panda_base,rx_ur5_base,rx_nao_chest`
- raw occupancy best: SVM-RBF, `F1 ~ 0.510`, `balanced accuracy ~ 0.628`
- compact full object-aware best: SVM-RBF, `F1 ~ 0.509`, `balanced accuracy ~ 0.625`

### Interpretation

- Object-aware features improve adaptation-trigger prediction over raw occupancy
- Propagation-change prediction is mostly geometry-driven because raw occupancy and object-aware features are similar
- This is a feasibility result, not a full beamforming or resource-allocation result
