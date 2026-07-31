# Actor-aware three-frame RT runbook

## 1. Experiment purpose

This workflow composes three rigid Panda/UR5 frames with a frozen static scene and, when requested, baked actor meshes. It evaluates the resulting Sionna XML scenes with one RX or three RX sites.

## 2. Execution modes

- Inspect the recorded Factory run and its two summary CSVs.
- Run the single-RX or three-RX harness against a separate run root containing the required inputs.
- Run an actor-free harness, or add `--include-actors` when actor inputs are present.

## 3. Required source inputs

| Source input | Location | Consuming script | Validation |
|---|---|---|---|
| Dynamic prototype configuration | `<RUN_ROOT>/config/dynamic_prototype_config.json` | Both harnesses and rigid export | `python3 -m json.tool` |
| RT material/runtime configuration | `<RUN_ROOT>/config/rt_material_mapping.json` | Both harnesses and XML builder | `python3 -m json.tool` |
| Radio-site configuration | `<RUN_ROOT>/config/prototype_radio_sites.json` | Three-RX harness | `python3 -m json.tool` |
| Static merged manifest | `<RUN_ROOT>/static_scene/export/merged_static_manifest.json` | Both harnesses | `test -f` |
| Dynamic model assets | `models/` in the Git repository | Rigid mesh export | `test -d` |
| Actor samples and manifest, only with actors | `<RUN_ROOT>/dynamic_frames/actor_frame_samples.json`, `<RUN_ROOT>/manifests/actor_manifest.json` | Actor export | `test -f` |
| Panda and UR5 pose logs named by the dynamic prototype configuration | repository/extracted supporting input referenced by that configuration | Rigid mesh export | inspect the configuration and `test -f` each path |

The extracted reference tree is `rt_out/experiments/factory_panda_ur5/legacy_run_20260522_133045/`. It is an optional recorded reference. Its `config/`, `manifests/`, static export, pose logs, and actor files can be copied into a new run only when the scientific setup is intended to match that reference.

## 4. Generated artifact chain

| Generated artifact | Producing command | Output path | Consumed by |
|---|---|---|---|
| Rigid frame meshes and manifests | Three-frame harness → `export_dynamic_frame_meshes.py` | `<RUN_ROOT>/dynamic_scene/frame_XXX/` | Composition |
| Actor frame meshes and manifests | Harness with `--include-actors` | `<RUN_ROOT>/dynamic_scene/frame_XXX/` | Composition |
| Composed manifests | Harness → `compose_frame_scene.py` | `<RUN_ROOT>/composed_scene/frame_XXX/` | XML builder |
| Sionna XML | Harness → `build_frame_sionna_xml.py` | `<RUN_ROOT>/composed_scene/frame_XXX/` | Sionna RT |
| Single-RX summary | Single-RX harness | `<RUN_ROOT>/composed_scene/three_frame_rt_summary.csv` | Inspection |
| Three-RX summary | Three-RX harness | `<RUN_ROOT>/composed_scene/three_frame_three_rx_rt_summary.csv` | Inspection |

## 5. Environment prerequisites

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"
python3 --version
test -d models
command -v blender || test -n "${BLENDER:-}"
test -n "${SIONNA_PYTHON:-}" || python3 -c 'import sionna.rt, mitsuba'
df -h "$REPO_ROOT"
python3 rt_out/scripts/dynamic_rigid/run_three_frame_rt_sanity.py --help
python3 rt_out/scripts/dynamic_rigid/run_three_frame_multi_rx_rt_sanity.py --help
```

Set `SIONNA_PYTHON` to an interpreter that imports both `sionna.rt` and `mitsuba`; set `BLENDER` when Blender is not on `PATH`.

## 6. Run variables and 7. create the run root

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
SOURCE_ROOT="$REPO_ROOT/rt_out/experiments/factory_panda_ur5/legacy_run_20260522_133045"
RUN_ROOT="$REPO_ROOT/rt_out/experiments/actor_aware_3frame/run_example"
SIONNA_PYTHON="${SIONNA_PYTHON:-python3}"
mkdir -p "$RUN_ROOT"/{config,inputs/poses,manifests,static_scene/export,dynamic_frames}
```

## 8. Configuration

The following concrete copy commands populate a run that intentionally uses the extracted reference inputs. They do not modify the reference tree.

```bash
cp "$SOURCE_ROOT/config/dynamic_prototype_config.json" "$RUN_ROOT/config/"
cp "$SOURCE_ROOT/config/rt_material_mapping.json" "$RUN_ROOT/config/"
cp "$SOURCE_ROOT/config/prototype_radio_sites.json" "$RUN_ROOT/config/"
cp "$SOURCE_ROOT/static_scene/export/merged_static_manifest.json" "$RUN_ROOT/static_scene/export/"
cp "$SOURCE_ROOT/inputs/poses/panda_pose.log" "$RUN_ROOT/inputs/poses/panda_pose.log"
cp "$SOURCE_ROOT/inputs/poses/ur5_pose.log" "$RUN_ROOT/inputs/poses/ur5_pose.log"
CONFIG="$RUN_ROOT/config/dynamic_prototype_config.json"
python3 - "$CONFIG" <<'PY'
import json
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
payload = json.loads(config_path.read_text(encoding="utf-8"))
models = payload["dynamic_models"]
models["Panda"]["pose_log"] = "inputs/poses/panda_pose.log"
models["ur5_rg2"]["pose_log"] = "inputs/poses/ur5_pose.log"
config_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY
python3 -m json.tool "$CONFIG" >/dev/null
python3 -m json.tool "$RUN_ROOT/config/rt_material_mapping.json" >/dev/null
python3 -m json.tool "$RUN_ROOT/config/prototype_radio_sites.json" >/dev/null
```

For `--include-actors` only, copy the two additional inputs:

```bash
cp "$SOURCE_ROOT/manifests/actor_manifest.json" "$RUN_ROOT/manifests/"
cp "$SOURCE_ROOT/dynamic_frames/actor_frame_samples.json" "$RUN_ROOT/dynamic_frames/"
test -f "$RUN_ROOT/manifests/actor_manifest.json"
test -f "$RUN_ROOT/dynamic_frames/actor_frame_samples.json"
```

The rewrite preserves the prototype frame selection and model checks; it changes only the two copied pose-log locations to the files present in the extracted source tree.

## 9. Preflight

```bash
set -euo pipefail
for p in \
  "$RUN_ROOT/config/dynamic_prototype_config.json" \
  "$RUN_ROOT/config/rt_material_mapping.json" \
  "$RUN_ROOT/config/prototype_radio_sites.json" \
  "$RUN_ROOT/static_scene/export/merged_static_manifest.json"; do test -f "$p"; done
test -d "$REPO_ROOT/models"
"$SIONNA_PYTHON" -c 'import sionna.rt, mitsuba'
python3 -m json.tool "$RUN_ROOT/config/dynamic_prototype_config.json" >/dev/null
test -f "$RUN_ROOT/inputs/poses/panda_pose.log"
test -f "$RUN_ROOT/inputs/poses/ur5_pose.log"
```

With `--include-actors`, also run the two actor-file checks from the configuration section. Stop here if any selected pose log or required configuration input is absent.

## 10. Smoke workflow

The smallest solver-backed workflow is the fixed three-frame single-RX harness:

```bash
"$SIONNA_PYTHON" rt_out/scripts/dynamic_rigid/run_three_frame_rt_sanity.py \
  --experiment-root "$RUN_ROOT" \
  --sionna-python "$SIONNA_PYTHON"
```

For actors, add `--include-actors`; the two actor source files then become required.

## 11. Complete workflow

1. Input: the preflight inputs. Command: run the single-RX command above. Output: three composed manifests, XML files, and `three_frame_rt_summary.csv`. Validation: `python3 -c 'import csv; print(sum(1 for _ in csv.DictReader(open("'"$RUN_ROOT"'/composed_scene/three_frame_rt_summary.csv"))))'` must print `3`. Stop on any non-zero harness exit.
2. Input: the same static, dynamic, and radio-site inputs. Command:

```bash
"$SIONNA_PYTHON" rt_out/scripts/dynamic_rigid/run_three_frame_multi_rx_rt_sanity.py \
  --experiment-root "$RUN_ROOT" \
  --sionna-python "$SIONNA_PYTHON"
```

Output: `three_frame_three_rx_rt_summary.csv`. Validation: the CSV has nine rows (`3` frames × `3` RXs). Stop on a failed RT row.

## 12. Restart and overwrite behavior

The harnesses invoke mesh export, composition, XML emission, and summary writing. Use a newly created `RUN_ROOT` for a clean execution. They do not provide a `--force` option; inspect or preserve an existing run rather than assuming outputs will be replaced safely.

## 13. Output inventory

The extracted reference contains three dynamic manifests, three actor manifests, three composed manifests, three XML files, one single-RX summary, and one three-RX summary.

## 14. Troubleshooting

- `Dynamic prototype config does not exist`: verify `<RUN_ROOT>/config/dynamic_prototype_config.json`.
- Missing mesh/pose input: inspect the source paths with `python3 -m json.tool "$RUN_ROOT/config/dynamic_prototype_config.json"` and stop before the harness.
- Sionna import failure: run `"$SIONNA_PYTHON" -c 'import sionna.rt, mitsuba'`.
- Missing actor input: omit `--include-actors` or provide both actor files.

## 15. Related documentation

- [Rigid 200-frame runbook](semantic_ablation_200f_pipeline.md)
- [Actor-aware 200-frame runbook](semantic_ablation_actor_200f_pipeline.md)
