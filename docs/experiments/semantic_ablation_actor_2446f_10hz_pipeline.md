# Actor-aware 2,446-frame semantic-ablation runbook

## 1. Experiment purpose

This recorded 10 Hz experiment contains 2,446 actor-aware frames, six RX sites, Sionna XML, RT rows, GT point clouds, voxel/descriptor products, classification outputs, beam products, and received-power regression outputs.

## 2. Execution modes

- Validate the recorded run without writing it.
- Restart or regenerate RT in a separate writable root containing all run-local inputs.
- Validate existing GT PLYs.
- Generate/validate voxel and descriptor products from existing GT and RT inputs.
- Run classification, beam, and regression commands from their documented inputs.

## 3. Required source inputs

| Source input | Location | Consuming script | Validation |
|---|---|---|---|
| Run configuration | `<RUN_ROOT>/config/experiment_config.json` | RT/features | JSON parse |
| Pose inputs | `<RUN_ROOT>/inputs/poses/` | RT regeneration | manifest and file checks |
| Geometry/static/dynamic/actor inputs | `<RUN_ROOT>/geometry/`, `<RUN_ROOT>/frames/` | RT/GT stages | directory checks |
| Recorded XML index | `<RUN_ROOT>/sionna_xml/sionna_xml_index.csv` | generic RT batch | CSV header |
| Recorded RT CSV | `<RUN_ROOT>/rt_results/rt_2446frames_multi_rx.csv` | labels/features | CSV header |
| GT PLYs | `<RUN_ROOT>/gt_scene_pointclouds/` | voxel and descriptor builders | count/checksum validators |

## 4. Generated artifact chain

| Generated artifact | Producing command | Output path | Consumed by |
|---|---|---|---|
| RT staging/aggregate | restart-safe RT runner | `rt_results/` | labels/features |
| GT PLY validation | GT smoke builder without `--generate` | existing `gt_scene_pointclouds/` | voxel/features |
| Voxel primitives | segmentation voxel builder | `features/segmentation_ablation_voxels/` | descriptors/classification |
| R1–R4 products | canonical feature builder | `features/` | downstream models |
| Classical descriptors | descriptor builder | `features/classical_ml_descriptor_v2/` | classification/regression |
| Classification results | classical ML ablation runner | `results/` | aggregate validation |
| Regression results | best-beam regression runner | `results/` | summary/validation |

## 5. Environment prerequisites

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"; cd "$REPO_ROOT"
python3 --version
python3 rt_out/scripts/experiments/semantic_ablation/semantic_ablation_run_sionna_rt_restart_safe.py --help
python3 rt_out/scripts/features/build_segmentation_ablation_voxels.py --help
python3 rt_out/scripts/features/build_classical_ml_descriptors.py --help
python3 rt_out/scripts/experiments/semantic_ablation/semantic_ablation_run_classical_ml_ablation.py --help
python3 rt_out/scripts/training/run_best_beam_power_regression.py --help
df -h "$REPO_ROOT"
```

Sionna RT/Mitsuba is required only for RT execution: `${SIONNA_PYTHON:-python3} -c 'import sionna.rt, mitsuba'`.

## 6. Run variables, 7. create the run root, and 8. configuration

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
REFERENCE_RUN_ROOT="$REPO_ROOT/rt_out/experiments/semantic_ablation_actor_2446f_10hz/run_20260710_172015"
RUN_ROOT="$REPO_ROOT/rt_out/experiments/semantic_ablation_actor_2446f_10hz/run_example"
CONFIG="$REFERENCE_RUN_ROOT/config/experiment_config.json"
SIONNA_PYTHON="${SIONNA_PYTHON:-python3}"
python3 -m json.tool "$CONFIG" >/dev/null
```

Create a new run only after supplying its own resolved configuration and inputs:

```bash
mkdir -p "$RUN_ROOT/config"
cp "$REFERENCE_RUN_ROOT/config/experiment_config.json" "$RUN_ROOT/config/experiment_config.json"
python3 -m json.tool "$RUN_ROOT/config/experiment_config.json" >/dev/null
```

The copied configuration is not a replacement for geometry, pose, manifests, and other source inputs.

## 9. Preflight

```bash
set -euo pipefail
for p in "$REFERENCE_RUN_ROOT/config/experiment_config.json" \
         "$REFERENCE_RUN_ROOT/rt_results/rt_2446frames_multi_rx.csv" \
         "$REFERENCE_RUN_ROOT/sionna_xml/sionna_xml_index.csv"; do test -f "$p"; done
test -d "$REFERENCE_RUN_ROOT/gt_scene_pointclouds"
python3 -m json.tool "$REFERENCE_RUN_ROOT/rt_results/rt_validation_summary.json" >/dev/null
python3 - <<'PY' "$REFERENCE_RUN_ROOT"
from pathlib import Path
import sys
r=Path(sys.argv[1])
assert len(list((r/'gt_scene_pointclouds').glob('frame_*.ply')))==2446
assert len(list((r/'sionna_xml').glob('frame_*_sionna.xml')))==2446
PY
```

## 10. Smoke workflow

Read-only validation commands:

```bash
python3 rt_out/scripts/experiments/semantic_ablation/semantic_ablation_run_sionna_rt_restart_safe.py --root "$REFERENCE_RUN_ROOT" --preflight
python3 rt_out/scripts/features/build_segmentation_ablation_voxels.py --config "$CONFIG" --validate-only
python3 rt_out/scripts/features/build_classical_ml_descriptors.py --root "$REFERENCE_RUN_ROOT" --validate-only
python3 rt_out/scripts/training/run_best_beam_power_regression.py --experiment-root "$REFERENCE_RUN_ROOT" --validate-inputs
```

## 11. Complete workflow

1. Recorded RT validation: `semantic_ablation_run_sionna_rt_restart_safe.py --root "$REFERENCE_RUN_ROOT" --preflight`; output is a pass/fail diagnostic, stop on failure.
2. RT restart/regeneration in a writable root: `"$SIONNA_PYTHON" rt_out/scripts/experiments/semantic_ablation/semantic_ablation_run_sionna_rt_restart_safe.py --root "$RUN_ROOT" --run --sionna-python "$SIONNA_PYTHON"`; output: `rt_results/`; stop if preflight inputs are missing.
3. GT validation: `python3 rt_out/scripts/experiments/semantic_ablation/semantic_ablation_build_gt_scene_pointcloud_smoke.py --experiment-root "$REFERENCE_RUN_ROOT" --expected-frame-count 2446`; this validates topology only. Do not add `--generate` for a full-run claim.
4. Voxel and canonical features: `python3 rt_out/scripts/features/build_segmentation_ablation_voxels.py --config "$CONFIG" --validate-only` and `python3 rt_out/scripts/features/build_canonical_r1_r4_features.py --config "$CONFIG" --validate-only`; remove `--validate-only` only in a writable run.
5. Descriptor generation: `python3 rt_out/scripts/features/build_classical_ml_descriptors.py --root "$RUN_ROOT"`.
6. Beam products and supervised targets: from `REPO_ROOT`, validate recorded beam scores with `python3 rt_out/scripts/experiments/semantic_ablation/semantic_ablation_extract_canonical_beam_scores.py --validate-only`; validate the horizon-10 target contract with `python3 rt_out/scripts/experiments/semantic_ablation/semantic_ablation_build_canonical_horizon10_supervised_targets.py --root "$REFERENCE_RUN_ROOT" --validate-only`. The beam-score extractor has no root argument and uses its recorded repository-relative root.
7. Classification: `python3 rt_out/scripts/experiments/semantic_ablation/semantic_ablation_run_classical_ml_ablation.py --experiment-root "$RUN_ROOT" --smoke`; use `--run-all` only after validation of all feature inputs.
8. Regression: `python3 rt_out/scripts/training/run_best_beam_power_regression.py --experiment-root "$RUN_ROOT" --smoke`; inspect with `--validate-results` or `--summarize-results`.

## 12. Restart and overwrite behavior

The restart-safe RT CLI has `--preflight` and `--run`; it validates run-local state before solver work. Classification has `--force` only for an explicit job. Regression has `--force`; CTX regression supports `--resume` and `--force`. Use a separate writable root for any generating mode.

## 13. Output inventory

The recorded tree contains 2,446 GT PLYs, 2,446 XML files, 14,676 raw RT rows (2,446 × 6), voxel `.npz` products, descriptor arrays, model files, beam products, and result tables.

## 14. Troubleshooting

- RT preflight failure: inspect `config/`, `inputs/poses/`, `geometry/`, and `frames/` under the selected root.
- GT validation failure: inspect `gt_scene_pointclouds/` and its index/registry files.
- Feature failure: validate `rt_results/` and GT input counts before writing features.

## 15. Genuine limitations

The recorded GT PLY batch exists, but there is no generic complete 2,446-frame GT producer. The fixed 100-frame benchmark is a separate workload and is not a full-run producer.

## 16. Related documentation

- [Three-frame RT runbook](actor_aware_3frame_pipeline.md)
- [Actor-aware 200-frame runbook](semantic_ablation_actor_200f_pipeline.md)
