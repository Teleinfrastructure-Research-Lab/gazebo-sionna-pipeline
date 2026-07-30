# Troubleshooting

Start with the smallest relevant check. Each section names the problem, cause,
check, and solution. Do not repair a failed result by deleting generated files
or regenerating scientific data without preserving the failed run.

## Problem: run root is missing or wrong

Symptoms include `No experiment run directory was provided`, refusal to use
`rt_out`, or output appearing under a different experiment.

```bash
test -d "$PIPELINE_RUN_DIR"
python3 rt_out/scripts/experiment_paths.py \
  --experiment-root "$PIPELINE_RUN_DIR" \
  --log-name diagnostics/path-check.log
```

Set `PIPELINE_RUN_DIR` to one unique
`rt_out/experiments/<experiment>/<run_id>/` directory. Do not use
`current_experiment`.

## Problem: configuration is missing

Batch scripts require `--config` and resolve output paths from the config's
run root. Confirm:

```bash
python3 -m json.tool "$PIPELINE_RUN_DIR/config/experiment_config.json" >/dev/null
test -f "$PIPELINE_RUN_DIR/config/dynamic_prototype_config.json"
```

The current 2,446-frame run keeps the configuration used by the run under
`run_20260710_172015/config`. The reduced dataset archive does not contain every
source input used by the full run.

## Problem: an old absolute path remains

Search the run and manifests before moving a run:

```bash
rg -n '/home/|/mnt/|/tmp/|static_scene|dynamic_scene|composed_scene' \
  "$PIPELINE_RUN_DIR"
```

XML should use paths that remain valid after moving the dataset archive. A path
that points outside the run or repository is a portability defect; do not
silently rewrite it in generated scientific data.

## Problem: an XML mesh target is missing

Validate the composed manifests first, then XML paths:

```bash
python3 rt_out/scripts/rt/build_sionna_xml_batch.py \
  --config "$PIPELINE_RUN_DIR/config/experiment_config.json" \
  --max-frames 1
```

Check that every `entries[].mesh_path` exists and every XML `<string
name="filename">` resolves relative to the XML directory. Static XML uses
merged material meshes; dynamic and actor XML references are frame-local.

## Problem: static registry or merge fails

The current geometry/static registry builders still have old default paths
and no complete run-root CLI. Verify their actual input constants before
running them:

```bash
python3 rt_out/scripts/static_scene/extract_scene_manifests.py --help
python3 rt_out/scripts/static_scene/merge_static_scene_by_material.py --help
```

Use explicit `--registry`, `--out-dir`, `--blender`, and `--helper` for the
merge stage. Do not assume that the no-argument registry scripts operate on the
run selected by `PIPELINE_RUN_DIR`.

## Problem: pose logs are missing

`run_all.sh` requires a running Gazebo world and `PIPELINE_RUN_DIR`; it creates
unique timestamped `logs/ops/panda_pose.log` and `ur5_pose.log` files. It stops
both subscribers on exit.

```bash
source rt_out/scripts/ops/setup_gazebo_env.sh
bash rt_out/scripts/ops/run_gazebo_gpu.sh myworld_rt.sdf
bash rt_out/scripts/ops/run_all.sh
```

The pose logs are raw Gazebo topic streams, not CSV files. Check their sample
counts and timestamps before building frames. A frozen run may instead use
copied pose logs; record that choice in the run metadata.

## Problem: Blender or Sionna is not found

```bash
BLENDER=blender
SIONNA_PYTHON=/path/to/sionna/python
export BLENDER SIONNA_PYTHON
python3 rt_out/scripts/rt/run_rt_multi_rx_batch.py --help
```

The runtime helper searches explicit arguments, `BLENDER`/`SIONNA_PYTHON`, the
legacy `COLLABPAPER_PYTHON`, and limited local fallbacks. It must not be treated
as proof that the required scientific environment is installed.

## Problem: actor alignment looks wrong

Use the actor mesh index, worker summary, and alignment diagnostics. The
current export may use XY bounds-to-root and Z bounds-to-floor corrections. It
does not claim exact Gazebo animation phase.

```bash
python3 rt_out/scripts/validation/diagnose_actor_validation_alignment.py --help
python3 rt_out/scripts/validation/diagnose_actor_floor_alignment.py --help
```

## Problem: descriptor v1 is partial

The current 2,446-frame run contains a v1 schema/index for 14,616 rows but only
three staging NPZ files. Treat it as partial staging data. Use complete v2
consolidated arrays for descriptor experiments; do not advertise v1 as a
complete released feature family.

## Problem: an RT run stops or must continue

The restart-safe 2,446-frame script validates existing dynamic, actor,
composed, XML, and per-frame RT shard files before reusing them. Invalid or
configuration-mismatched shards fail rather than being silently accepted.
The generic batch runner supports bounded `--max-frames`/`--max-rows` and
`--continue-on-error`; use those only for a distinct debug output root.

## Problem: perception capture has no data

The perception pilot is separate from RT generation. Confirm that Gazebo is
running the generated labeled world and that the expected topics exist:

```bash
gz topic -l | grep -E 'panoptic|stable_instance|rgb|depth'
```

The C++ build scripts require `pkg-config`, Gazebo transport/message packages,
and a C++17 compiler. The current pilot has partial coverage (`24/160` final
frame-camera PCL rows); a passing validator for available rows does not imply
complete coverage.

## Problem: perception validation fails

After unpacking the archived pilot run, use the functional names:

```bash
python3 rt_out/scripts/perception/capture/validate_panoptic_capture.py --help
python3 rt_out/scripts/perception/capture/validate_synchronized_stable_instance_rgb_pcl.py --help
python3 rt_out/scripts/perception/reconstruction/validate_labeled_colorized_point_cloud.py --help
```

The final perception PLY format is `x y z red green blue class_label
instance_id`. Do not confuse it with the GT scene PLY format.

## Problem: generated data is tracked by Git

Before a release review:

```bash
git status --short
git ls-files 'rt_out/experiments/**' | sed -n '1,80p'
```

Generated data may be intentionally curated, but large run directories must
not become tracked merely because a command wrote them in the repository.

## Problem: an archive may be incomplete

Validate a package in a temporary directory, not over the source run:

```bash
tar -tzf <archive>.tar.gz >/dev/null
tmp_dir="$(mktemp -d)"
tar -xzf <archive>.tar.gz -C "$tmp_dir"
find "$tmp_dir" -type f | sort | sed -n '1,40p'
rm -rf "$tmp_dir"
```

Check JSON/CSV parsing, XML mesh references, PLY headers, frame/RX counts, and
absence of absolute machine paths after extraction.
