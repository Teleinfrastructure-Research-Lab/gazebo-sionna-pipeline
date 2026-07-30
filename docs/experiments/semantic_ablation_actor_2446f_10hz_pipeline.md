# Current actor-aware 2,446-frame semantic-ablation experiment

## 1. Experiment purpose

`semantic_ablation_actor_2446f_10hz` is the current actor-aware experiment. It
contains 2,446 time-indexed scenes, rigid Panda/UR5 geometry, one offline-baked
human actor, six RX sites, compact Sionna RT summaries, horizon-10 targets,
0.04 m voxel products, descriptor v2 features, and downstream classification
and received-power regression experiments.

The experiment compares compact geometry, semantic, instance, and link-context
representations while preserving the temporal ordering of the recorded scene
and wireless data.

## 2. Status

`Current experiment`. The recorded run is:

```text
rt_out/experiments/semantic_ablation_actor_2446f_10hz/run_20260710_172015/
```

The run records 2,446 frames at 28 GHz with six RXs. The full local run
contains geometry, XML, RT, feature, beam, result, model, and report trees. It
is a recorded output tree, not a clean-environment rerun.

The repository does not provide one generic command that regenerates every
2,446 GT scene point cloud. Do not describe the recorded run as a fresh rerun
merely because read-only validators pass.

## 3. Differences from the main pipeline

This experiment uses the specialized restart-safe script
`semantic_ablation_run_sionna_rt_restart_safe.py`, fixed `N=2446`, six RXs,
actor-aware counts, and run-local generated files. The main guide also
documents generic batch alternatives and the static/GT limitations.

Actor geometry is offline baked. The run records an explicit alignment policy
but does not claim equality with a runtime animation phase.

## 4. Experiment and run layout

```text
<run>/
├── config/                         experiment and taxonomy JSON used by the run
├── frames/                         sampled, dynamic, actor, composed manifests/meshes
├── geometry/                       packaged static/dynamic/source support assets
├── gt_scene_pointclouds/           2,446 labeled ASCII PLYs and index
├── sionna_xml/                     2,446 package-relative XMLs and index
├── rt_results/                     raw/staged RT summaries and horizon labels
├── features/                       voxel products and descriptor v1/v2 families
├── beam_results/                   optional canonical beam products
├── results/                        optional downstream ML and regression outputs
├── models/                         optional trained model files
└── reports/                        validation and benchmark summaries
```

The saved run's old `output_dir: "."` is a detail of the old script. A new
batch run must use a repository-relative run path in
`config/experiment_config.json`; otherwise current batch scripts can resolve
outputs at the repository root.

## 5. Required configuration and environment

The recorded workflow requires:

- `config/experiment_config.json`: 2,446 frames, 28 GHz, TX `tx_ap`, six RXs,
  Panda/UR5, and actor policy;
- `config/dynamic_prototype_config.json`: dynamic link counts and frozen pose
  log requirements;
- `config/fine_panoptic_taxonomy.json` and
  `config/fine_to_coarse_mapping.json`;
- a static merged manifest and object-level/frame-local mesh inputs;
- pose logs and copied dynamic/actor inputs;
- Blender for mesh export and Sionna RT/Mitsuba for RT, unless recorded RT
  rows are reused.

The downstream ML experiments additionally require the descriptor v2 arrays,
their validation metadata, the canonical horizon-10 supervised target rows,
and the current-beam one-hot array for the classification task that uses it.

## 6. Environment setup

Use a separate writable root for a new run and keep the recorded run read-only:

```bash
REPO_ROOT="$(pwd)"
REFERENCE_RUN_ROOT="$REPO_ROOT/rt_out/experiments/semantic_ablation_actor_2446f_10hz/run_20260710_172015"
RUN_ROOT="$REPO_ROOT/rt_out/experiments/semantic_ablation_actor_2446f_10hz/<new_run_id>"
SIONNA_PYTHON="<path-to-sionna-python>"
BLENDER="<path-to-blender>"
export PIPELINE_RUN_DIR="$RUN_ROOT" SIONNA_PYTHON BLENDER
source rt_out/scripts/ops/setup_gazebo_env.sh
```

`REFERENCE_RUN_ROOT` is read-only and is used only to inspect or validate the
recorded run. `RUN_ROOT` is writable and is used for frame generation, mesh
export, scene composition, XML generation, RT probes, debug runs, and new
executions. Before using `RUN_ROOT`, copy and resolve the required
configuration, manifests, pose inputs, and geometry according to this guide
and the canonical runbook. Do not point generation commands at
`REFERENCE_RUN_ROOT`.

## 7. Generation sequence and commands

The recorded sequence was:

```text
input files and sampled frames
→ rigid dynamic frame geometry
→ actor frame samples and baked actor geometry
→ composed frame manifests
→ GT scene point clouds
→ Sionna XML
→ six-RX RT summaries
→ horizon-10 labels
→ voxel products
→ descriptor v2
→ optional beam targets, ML, and regression
```

For a new run with the same layout, use these functional stages:

```bash
python3 rt_out/scripts/dynamic_rigid/sample_experiment_frames.py \
  --config "$RUN_ROOT/config/experiment_config.json"
python3 rt_out/scripts/dynamic_rigid/build_dynamic_pose_frames.py \
  --experiment-root "$RUN_ROOT" \
  --dynamic-prototype-config "$RUN_ROOT/config/dynamic_prototype_config.json" \
  --dynamic-manifest "$RUN_ROOT/manifests/dynamic_manifest.json" \
  --frames-json "$RUN_ROOT/frames/sampled_frames.json" \
  --output "$RUN_ROOT/frames/dynamic_frames.json"
python3 rt_out/scripts/dynamic_rigid/resolve_dynamic_visual_frames.py \
  --experiment-root "$RUN_ROOT" \
  --dynamic-manifest "$RUN_ROOT/manifests/dynamic_manifest.json" \
  --frames-json "$RUN_ROOT/frames/sampled_frames.json" \
  --dynamic-frames "$RUN_ROOT/frames/dynamic_frames.json" \
  --output "$RUN_ROOT/frames/dynamic_visual_frames.json"
python3 rt_out/scripts/dynamic_actor/build_experiment_actor_frame_samples.py \
  --config "$RUN_ROOT/config/experiment_config.json"
python3 rt_out/scripts/dynamic/export_dynamic_meshes_batch.py \
  --config "$RUN_ROOT/config/experiment_config.json" \
  --include-actors --blender "$BLENDER"
python3 rt_out/scripts/composition/compose_frame_manifests_batch.py \
  --config "$RUN_ROOT/config/experiment_config.json" --include-actors
python3 rt_out/scripts/rt/build_sionna_xml_batch.py \
  --config "$RUN_ROOT/config/experiment_config.json"
```

GT generation remains an implementation gap. The experiment-local script
supports a small test or a full-layout output, while the benchmark script is a
separate 100-frame workflow. Neither is a generic 2,446-frame GT producer. Use
the exact commands in the canonical execution guide; the saved outputs do not
establish a full regeneration command.

The restart-safe RT stage is:

```bash
python3 rt_out/scripts/experiments/semantic_ablation/semantic_ablation_run_sionna_rt_restart_safe.py \
  --root "$RUN_ROOT" --preflight
python3 rt_out/scripts/experiments/semantic_ablation/semantic_ablation_run_sionna_rt_restart_safe.py \
  --root "$RUN_ROOT" --probe-frame 0 --probe-rx rx_panda_base \
  --sionna-python "$SIONNA_PYTHON"
python3 rt_out/scripts/experiments/semantic_ablation/semantic_ablation_run_sionna_rt_restart_safe.py \
  --root "$RUN_ROOT" --run --sionna-python "$SIONNA_PYTHON"
```

The generic `rt/run_rt_multi_rx_batch.py` is an alternative; do not run it
after the restart-safe script in the same tree.

## 8. Smoke, full-run, restart, and validation

### Smoke and debug

Run `--preflight` and one RT probe first. For mesh/XML debugging, use the
lower-level batch stages with `--max-frames 1` in a separate debug run. Do not
point a small test at the completed recorded tree.

### Full recorded-run validation

Inspect the recorded run through `REFERENCE_RUN_ROOT` only:

```bash
python3 rt_out/scripts/experiments/semantic_ablation/semantic_ablation_build_canonical_horizon10_supervised_targets.py \
  --root "$REFERENCE_RUN_ROOT/../../../.." --validate-only
python3 -m json.tool "$REFERENCE_RUN_ROOT/config/experiment_config.json" >/dev/null
python3 -m json.tool "$REFERENCE_RUN_ROOT/rt_results/rt_validation_summary.json" >/dev/null
python3 -m json.tool "$REFERENCE_RUN_ROOT/features/segmentation_ablation_voxels/voxel_0.04m/validation_summary.json" >/dev/null
python3 rt_out/scripts/features/build_classical_ml_descriptors.py \
  --root "$REFERENCE_RUN_ROOT/../../../.." --validate-only
python3 rt_out/scripts/experiments/semantic_ablation/semantic_ablation_run_sionna_rt_restart_safe.py \
  --root "$REFERENCE_RUN_ROOT" --preflight
```

For a new run, validate only after copying and resolving its configuration,
manifests, pose inputs, and geometry:

```bash
python3 -m compileall -q rt_out/scripts scripts
python3 -m json.tool "$RUN_ROOT/config/experiment_config.json" >/dev/null
python3 -m json.tool "$RUN_ROOT/rt_results/rt_validation_summary.json" >/dev/null
python3 -m json.tool "$RUN_ROOT/features/segmentation_ablation_voxels/voxel_0.04m/validation_summary.json" >/dev/null
python3 rt_out/scripts/experiments/semantic_ablation/semantic_ablation_run_sionna_rt_restart_safe.py \
  --root "$RUN_ROOT" --preflight
```

### Restart and resume

The RT script validates composed manifests, XMLs, and per-frame RT chunks.
Valid chunks are reused; invalid chunks fail; the final CSV is not
overwritten. The limited GT output check validates existing temporary PLYs
before moving validated files to the final directory. Keep beam, ML, and
regression outputs in their own subtrees.

## 9. Recorded products and counts

The recorded run contains:

- 2,446 sampled frames with IDs `0..2445`;
- six RXs and 14,676 raw RT rows (`2446 × 6`);
- 14,616 horizon-10 source/RX rows over source frames `0..2435`;
- a 120-row train/test exclusion gap;
- 2,446 GT scene point clouds, each with 100,000 points and fields
  `x y z class_label instance_id material_id object_type_id source_type_id`;
- 2,446 Sionna XML files, each validated with 11 static, 21 rigid dynamic,
  and 1 actor shape (33 shapes per frame);
- canonical beam products for 2,446 frames, 14,676 rows, and beam arrays
  shaped `2446×6×16`;
- a 0.04 m voxel product with grid `[250,250,88]`;
- descriptor v2 validation metadata reporting 14,616 rows;
- optional classification, regression, model, and report trees.

The downstream classification artifacts are under:

```text
results/classical_ml_ablation_v4/
results/classical_ml_rbf_svm_v1/
results/classical_ml_xgboost_v1/
results/classical_ml_combined_v1/
```

The three source families contain 45, 15, and 15 task/view/model results. The
combined release contains 75 validated entries and provides
`combined_manifest.json`, `run_summary.csv`, `per_rx_metrics.csv`,
`selected_hyperparameters.json`, and `validation_summary.json`.

## 10. Compact representations and supervised targets

Descriptor v2 stores raw scene-derived arrays with dimensions G 65, GI 715,
GS 1,430, and GSI 2,080, together with two 16-wide context arrays. These raw
scene dimensions are not the final regression dimensions; the CTX-integrated
regression input dimensions are documented in Section 12.

The canonical supervised rows are produced from the horizon-10 RT/beam
artifacts. Training rows cover source frames `0..1694`, the excluded temporal
gap covers `1695..1714`, and test rows cover `1715..2435`. The classification
and regression experiments use the same row alignment and do not use excluded
rows for fitting or validation.

## 11. One-second-ahead classification experiment

The classification experiment evaluates three one-second-ahead targets:

- Beam reselection: `beam_reselection_1db_1s`;
- Propagation-path change: `y_path_change`;
- Adaptation trigger: `y_adaptation_trigger_1db`.

All five representations are evaluated: CTX, G, GS, GI, and GSI. For beam
reselection only, the current-beam 16-dimensional one-hot vector is appended
to the representation. Therefore its feature dimensions are CTX 32, G 97,
GS 1,462, GI 747, and GSI 2,112. The other tasks use CTX 16, G 81, GS 1,446,
GI 731, and GSI 2,096.

The temporal protocol is:

- training frames `0..1694`: 10,170 examples;
- three temporal cross-validation folds, each with a 10-frame gap;
- excluded train/test gap `1695..1714`: 120 examples;
- test frames `1715..2435`: 4,326 examples.

For each task and input representation, select the classifier and
hyperparameters by mean validation average precision. Select the threshold
from the combined out-of-fold validation scores by maximizing F1; break ties
by higher recall and then lower threshold. Refit the selected classifier on the
complete training interval and evaluate it once on the held-out test interval.
Test F1 is not used for selection.

The candidate classifiers are Logistic Regression, Linear SVM, RBF SVM,
Random Forest, and XGBoost. The source entry points are
`rt_out/scripts/experiments/semantic_ablation/semantic_ablation_run_classical_ml_ablation.py`
and its RBF-specific companion
`rt_out/scripts/experiments/semantic_ablation/semantic_ablation_run_rbf_svm_ablation.py`.
The source family trees contain per-job `runs/`, `predictions/`, and
`oof_predictions/` artifacts, manifests, and summaries. The combined manifest
records their identities and hashes. The table in Section 13 selects one row
per task/representation from the generated
`results/classical_ml_combined_v1/run_summary.csv` by the recorded
validation-AP rule.

## 12. CTX-integrated best-beam received-power regression

This optional experiment estimates same-frame
`best_beam_received_power_dbm`. It does not predict future received power and
it does not estimate RSRP.

The five representations are:

- `CTX`: link context;
- `G`: CTX + geometry;
- `GS`: CTX + geometry + semantics;
- `GI`: CTX + geometry + instances;
- `GSI`: CTX + geometry + semantics + instances.

The canonical input artifacts are:

```text
features/classical_ml_descriptor_v2/link_context.npy
features/classical_ml_descriptor_v2/G.npy
features/classical_ml_descriptor_v2/GS.npy
features/classical_ml_descriptor_v2/GI.npy
features/classical_ml_descriptor_v2/GSI.npy
beam_results/canonical_4x4_dft16/best_beam_received_power_targets.csv
```

The runner joins rows on `source_frame_id` and `rx_id`. The complete aligned
set contains 14,616 samples. The 60 unmatched target rows are the final 10
frames for six RXs. There are no duplicate aligned keys and no missing feature
values in the aligned set.

CTX contains 16 features: TX position (3), RX position (3), RX-minus-TX
displacement (3), TX-RX distance (1), and a six-dimensional RX identity
one-hot vector (6). The final model-input dimensions are CTX 16, G 81, GS
1,446, GI 731, and GSI 2,096. There is no current-beam one-hot vector in the
regression input, and current or future beam powers are not input features.

The temporal regression protocol is:

- fit: frames `0..1355`, 8,136 samples;
- validation: frames `1356..1694`, 2,034 samples;
- temporal gap: frames `1695..1714`;
- test: frames `1715..2435`, 4,326 samples.

Hyperparameters are selected using validation MAE. After selection, the model
is refitted on frames `0..1694` and evaluated once on the held-out test
interval.

The methods are Per-RX median, Persistence, Elastic Net, Random Forest
Regressor, and RBF SVR. Per-RX median is a static receiver-conditioned
baseline. Persistence is a measurement-aided baseline using the preceding
wireless measurement, not a scene-only competitor. Elastic Net, Random
Forest, and RBF SVR are learned estimators.

Run a clean full regression with:

```bash
/home/telilab4090/miniconda3/envs/collabpaper/bin/python \
  rt_out/scripts/training/run_best_beam_power_regression_ctx.py \
  --experiment-root rt_out/experiments/semantic_ablation_actor_2446f_10hz/run_20260710_172015 \
  --full --force
```

Resume an interrupted regression with:

```bash
/home/telilab4090/miniconda3/envs/collabpaper/bin/python \
  rt_out/scripts/training/run_best_beam_power_regression_ctx.py \
  --experiment-root rt_out/experiments/semantic_ablation_actor_2446f_10hz/run_20260710_172015 \
  --full --resume
```

`--force` deletes and recreates only the CTX-regression result, model, and
report trees. It must not be used when the intention is to continue a partial
run.

The intended current output trees are:

```text
results/best_beam_power_regression_ctx/full/
models/best_beam_power_regression_ctx/full/
reports/best_beam_power_regression_ctx/full/
```

The result tree contains `summary.csv`, `results.json`,
`test_predictions.csv`, `progress.json`, `checkpoints/`, and `grid_*.json`.
The full run contains 25 representation-method entries (5 × 5). Each pair
has an independent checkpoint. Resume validates pair checkpoints and rebuilds
the aggregate JSON, prediction CSV, and summary CSV from validated
checkpoints. Representation-independent baselines can have identical values
in presentation tables, but they are not separate scene-trained models.

### Current output-tree evidence

In the current checkout, the CTX model and report trees exist, but
`results/best_beam_power_regression_ctx/full/summary.csv` does not. The
complete 25-row summary, manifest, and 25 pair checkpoints are under the
legacy-named path:

```text
results/best_beam_power_regression/full/
```

The manifest uses schema `ctx_regression_checkpoint_v1`, records
CTX-integrated input dimensions, and has the same forbidden-input contract as
the current CTX runner. The available result content is therefore
CTX-integrated despite the legacy directory name. The `_ctx` result path
remains the implementation's canonical destination, but it is absent from this
checkout. No result tree was moved or regenerated for this documentation
update.

## 13. Recorded results and interpretation

### Classification results

The following table is generated from
`results/classical_ml_combined_v1/run_summary.csv`. AP and other metrics are
percentages. The selected row for each task/representation is the row with
the highest recorded mean validation AP across the five candidate classifier
families.

| Task | Representation | Selected classifier | Mean validation AP (%) | Test AP (%) | Test BAcc (%) | Test F1 (%) | Test precision (%) | Test recall (%) |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Beam reselection | CTX | Linear SVM | 15.616 | 14.763 | 62.6 | 26.4 | 26.4 | 26.4 |
| Beam reselection | G | Linear SVM | 20.925 | 13.885 | 71.8 | 8.2 | 4.3 | 69.4 |
| Beam reselection | GS | XGBoost | 16.720 | 15.105 | 60.1 | 18.3 | 15.5 | 22.2 |
| Beam reselection | GI | RBF SVM | 19.260 | 31.060 | 69.2 | 31.7 | 26.1 | 40.3 |
| Beam reselection | GSI | RBF SVM | 16.398 | 26.910 | 71.8 | 26.6 | 18.5 | 47.2 |
| Propagation-path change | CTX | RBF SVM | 49.745 | 35.990 | 58.2 | 35.0 | 44.8 | 28.7 |
| Propagation-path change | G | Random Forest | 60.786 | 56.720 | 71.3 | 55.8 | 42.7 | 80.7 |
| Propagation-path change | GS | XGBoost | 61.339 | 53.918 | 69.3 | 53.7 | 40.7 | 79.2 |
| Propagation-path change | GI | XGBoost | 62.179 | 55.353 | 70.6 | 55.0 | 41.5 | 81.3 |
| Propagation-path change | GSI | XGBoost | 61.553 | 59.174 | 72.0 | 56.3 | 42.1 | 85.1 |
| Adaptation trigger | CTX | XGBoost | 15.175 | 4.856 | 50.5 | 5.2 | 3.1 | 17.6 |
| Adaptation trigger | G | XGBoost | 20.816 | 6.968 | 57.4 | 11.4 | 7.6 | 23.2 |
| Adaptation trigger | GS | XGBoost | 24.637 | 12.447 | 58.0 | 9.8 | 5.9 | 30.4 |
| Adaptation trigger | GI | Random Forest | 23.855 | 24.731 | 61.9 | 15.6 | 10.3 | 32.0 |
| Adaptation trigger | GSI | XGBoost | 26.082 | 20.953 | 65.1 | 12.9 | 7.5 | 48.0 |

Test positive prevalence is 1.66% for beam reselection, 25.98% for
propagation-path change, and 2.89% for adaptation triggering. Propagation-path
change is primarily geometry-driven. Beam reselection and adaptation
triggering benefit more from instance-aware descriptors, but GSI is not
uniformly superior and GS is not the strongest representation for any task.
Adaptation triggering remains difficult because it is rare and has a composite
target definition. Classifier selection is task- and representation-dependent;
no classifier family is universally dominant.

### Regression results

Because the canonical `_ctx` summary is absent, the table below uses the
available complete CTX-integrated `summary.csv` under the legacy-named result
tree described in Section 12. Recheck it against
`results/best_beam_power_regression_ctx/full/summary.csv` when that path is
restored. Values are MAE/RMSE.

| Representation | Method | Validation MAE | Validation RMSE | Test MAE | Test RMSE |
| --- | --- | ---: | ---: | ---: | ---: |
| CTX | Per-RX median | 2.213 | 5.826 | 0.786 | 2.931 |
| CTX | Persistence | 0.233 | 1.820 | 0.106 | 1.245 |
| CTX | Elastic Net | 2.282 | 5.098 | 1.470 | 3.025 |
| CTX | Random Forest | 2.281 | 5.098 | 1.466 | 3.020 |
| CTX | RBF SVR | 2.219 | 5.759 | 0.843 | 2.894 |
| G | Per-RX median | 2.213 | 5.826 | 0.786 | 2.931 |
| G | Persistence | 0.233 | 1.820 | 0.106 | 1.245 |
| G | Elastic Net | 3.150 | 6.267 | 2.861 | 5.090 |
| G | Random Forest | 2.087 | 5.036 | 1.375 | 3.354 |
| G | RBF SVR | 2.284 | 5.125 | 2.642 | 5.519 |
| GS | Per-RX median | 2.213 | 5.826 | 0.786 | 2.931 |
| GS | Persistence | 0.233 | 1.820 | 0.106 | 1.245 |
| GS | Elastic Net | 3.149 | 5.844 | 3.134 | 5.170 |
| GS | Random Forest | 2.072 | 4.738 | 1.293 | 3.173 |
| GS | RBF SVR | 2.469 | 5.024 | 2.862 | 5.690 |
| GI | Per-RX median | 2.213 | 5.826 | 0.786 | 2.931 |
| GI | Persistence | 0.233 | 1.820 | 0.106 | 1.245 |
| GI | Elastic Net | 2.622 | 5.711 | 2.221 | 4.397 |
| GI | Random Forest | 2.456 | 5.526 | 0.947 | 2.570 |
| GI | RBF SVR | 2.427 | 5.048 | 2.675 | 5.254 |
| GSI | Per-RX median | 2.213 | 5.826 | 0.786 | 2.931 |
| GSI | Persistence | 0.233 | 1.820 | 0.106 | 1.245 |
| GSI | Elastic Net | 2.585 | 5.637 | 2.559 | 4.358 |
| GSI | Random Forest | 2.450 | 5.551 | 0.941 | 2.586 |
| GSI | RBF SVR | 2.391 | 4.946 | 2.741 | 5.332 |

Among learned estimators, CTX-RBF SVR has the lowest test MAE. GI-RF and
GSI-RF have lower RMSE than CTX-RBF SVR, so instance-aware information appears
useful mainly for reducing larger errors rather than uniformly reducing MAE.
The Per-RX median has lower MAE than the scene-aware learned estimators, while
GI and GSI have lower RMSE. Persistence operates under a different,
measurement-aided information setting. GI and GSI are in the same performance
range; these values do not establish statistical superiority between them.
Adding semantics to the instance-aware representation does not provide a
consistent improvement. Higher validation than test errors may reflect a less
variable test temporal segment; it is a limitation, not proof of a particular
distribution shift.

## 14. Dataset archive scope

The reduced Zenodo dataset archive contains only:

```text
sionna_xml/
rt_results/
inputs/
gt_scene_pointclouds/
frames/
features/
config/
geometry/
```

It intentionally excludes `beam_results/`, `models/`, `results/`, and some run
source and log files. Beam, classification, and regression outputs therefore
exist in the full local run but are not part of the reduced eight-directory
archive. The archive is not a self-contained Gazebo/Sionna rerun environment.

## 15. Known limitations

- Descriptor v1 is partial; descriptor v2 is the complete descriptor result.
- Compact RT output does not include full path-level channel tensors.
- The GT branch has no generic full 2,446-frame producer; see Section 7.
- Actor geometry is offline baked and does not claim runtime animation-phase
  equality; see Section 3.
- The perception pilot is a separate partial 24/160 dataset and is not part
  of this mandatory RT scene-generation sequence.
- Classification targets are imbalanced, especially beam reselection and
  adaptation triggering; their held-out scores should be read with prevalence
  and balanced accuracy.

## 16. Related documentation

- [Complete pipeline sequence](../pipeline_execution_order.md)
- [Configuration](../configuration.md)
- [Script reference](../script_reference.md)
