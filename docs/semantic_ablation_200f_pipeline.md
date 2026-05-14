# Semantic Ablation 200f Pipeline

For the actor-aware variant, see
[semantic_ablation_actor_200f_pipeline.md](semantic_ablation_actor_200f_pipeline.md).

This document describes the `semantic_ablation_rigid_200f` experiment branch.
It is a rigid Panda/UR5 experiment only. Actors are not included in this branch.

The experiment reuses the frozen static baseline and validated rigid dynamic
scripts, then scales the workflow to sampled frames, multiple RX sites,
RT-derived labels, feature tables, and classical ablation models.

## Scope

- Static scene: frozen validated static baseline.
- Dynamic scene: rigid Panda/UR5 only.
- Frames: 200 sampled source frames.
- Receivers: experiment-configured multi-RX setup.
- Labels: derived from RT path-count and delay changes.
- Features: object-aware compact/wide modes plus raw occupancy baseline.

Do not pass actor assumptions from the three-frame prototype into this branch
unless the experiment wrappers are explicitly extended and revalidated later.

## Generated-Output Hygiene

Most experiment outputs are generated and can be large:

- frame manifests
- dynamic meshes
- Sionna XML batches
- RT result CSVs
- label CSVs
- feature tables
- ablation result tables

Do not commit these unless they are intentionally curated results or fixtures.

## Radio Setup

The experiment reads TX/RX settings from its config. The current branch uses the
same low-level RT sanity logic as the validated prototype wrappers, but runs it
in batch form across sampled frames and RX locations.

## End-To-End Commands

Set the config path once:

```bash
CONFIG=rt_out/experiments/semantic_ablation_rigid_200f/configs/experiment_config.json
```

### 1. Sample Frames

```bash
python3 rt_out/scripts/experiments/exp_sample_frames.py --config "$CONFIG"
```

### 2. Build Rigid Dynamic Frames

```bash
python3 rt_out/scripts/dynamic_rigid/30_build_prototype_dynamic_frames.py \
  --frames-json rt_out/experiments/semantic_ablation_rigid_200f/frames/sampled_frames.json \
  --output rt_out/experiments/semantic_ablation_rigid_200f/frames/dynamic_frames.json
```

### 3. Build Rigid Dynamic Visual Frames

```bash
python3 rt_out/scripts/dynamic_rigid/31_build_prototype_dynamic_visual_frames.py \
  --frames-json rt_out/experiments/semantic_ablation_rigid_200f/frames/sampled_frames.json \
  --dynamic-frames rt_out/experiments/semantic_ablation_rigid_200f/frames/dynamic_frames.json \
  --output rt_out/experiments/semantic_ablation_rigid_200f/frames/dynamic_visual_frames.json
```

### 4. Export Dynamic Meshes

```bash
python3 rt_out/scripts/experiments/exp_export_dynamic_meshes_batch.py --config "$CONFIG"
```

### 5. Compose Frame Manifests

```bash
python3 rt_out/scripts/experiments/exp_compose_frame_manifests_batch.py --config "$CONFIG"
```

### 6. Build Sionna XMLs

```bash
python3 rt_out/scripts/experiments/exp_build_sionna_xml_batch.py --config "$CONFIG"
```

### 7. Debug RT

```bash
python3 rt_out/scripts/experiments/exp_run_rt_multi_rx_batch.py \
  --config "$CONFIG" \
  --max-frames 1
```

### 8. Full RT

```bash
python3 rt_out/scripts/experiments/exp_run_rt_multi_rx_batch.py --config "$CONFIG"
```

### 9. Build Labels

```bash
python3 rt_out/scripts/experiments/exp_build_rt_labels.py --config "$CONFIG"
```

### 10. Build Object Features

```bash
python3 rt_out/scripts/experiments/exp_build_object_features.py --config "$CONFIG"
```

### 11. Build Raw Occupancy Features

```bash
python3 rt_out/scripts/experiments/exp_build_raw_occupancy_features.py --config "$CONFIG"
```

### 12. Run Compact Ablation

```bash
python3 rt_out/scripts/experiments/exp_run_semantic_ablation.py \
  --config "$CONFIG" \
  --target y_adaptation_trigger_1db \
  --rx-filter rx_panda_base,rx_ur5_base \
  --feature-mode compact \
  --models logistic,rf,svm
```

### 13. Run Raw Occupancy Ablation

```bash
python3 rt_out/scripts/experiments/exp_run_semantic_ablation.py \
  --config "$CONFIG" \
  --target y_adaptation_trigger_1db \
  --rx-filter rx_panda_base,rx_ur5_base \
  --feature-mode raw \
  --models logistic,rf,svm
```

## Expected Row Counts

For the current default `semantic_ablation_rigid_200f` setup, expected counts
are:

- sampled frames: `200`
- RT rows: `1200` (`200` frames x `6` RX sites)
- labeled rows: `1194` (`199` frame transitions x `6` RX sites)
- main adaptation subset: `398` (`199` transitions x `2` RX sites)
- supporting path-change subset: `597` (`199` transitions x `3` RX sites)

These are current defaults, not universal truths. If the experiment config
changes frame count, RX set, or filters, the counts should change accordingly.

If counts diverge, inspect the frame JSON, RT CSV, and label CSV before trusting
ablation results.

## Main Output Areas

```text
rt_out/experiments/semantic_ablation_rigid_200f/frames/
rt_out/experiments/semantic_ablation_rigid_200f/sionna_xml/
rt_out/experiments/semantic_ablation_rigid_200f/rt_results/
rt_out/experiments/semantic_ablation_rigid_200f/features/
rt_out/experiments/semantic_ablation_rigid_200f/results/
```

## Label Definitions

Labels are derived from RT outputs rather than hand-authored scene semantics.
The current branch uses path-count and delay behavior to build supervised tasks,
such as:

- adaptation-trigger classification
- propagation-change classification

Thresholds and task settings should be read from the experiment config and the
label builder arguments.

## Feature Modes

### Raw

Low-level or lightly processed features. Useful as a baseline but harder to
interpret.

### Compact

Object/material-aware features intended to support paper-facing interpretation.
This is the primary mode for semantic ablation comparisons.

### Wide

Expanded object/material feature sets. Useful for exploratory checks and
supporting analysis.

## Recommended Paper-Facing Results

Primary results should emphasize:

- compact semantic/object-aware features
- adaptation-trigger task behavior
- comparison against raw occupancy baseline

Supporting results can include propagation-change tasks and wider feature modes,
but should clearly state that the branch is rigid Panda/UR5 only.
