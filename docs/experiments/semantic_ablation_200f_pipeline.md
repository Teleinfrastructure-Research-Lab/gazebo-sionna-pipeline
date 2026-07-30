# Rigid semantic-ablation 200-frame experiment

> **Previous experiment.** The current repository version contains the saved
> rigid experiment inside the archive
> `rt_out/experiments/semantic_ablation_200f/run_20260522_143156/semantic_ablation.zip`,
> but it does not contain the old `exp_*` scripts used by that run. This page
> describes the saved file layout and its exact limitation; it is not a
> directly runnable replacement.

## 1. Experiment purpose

Compare raw occupancy and object-aware scene features for RT-derived temporal
labels with rigid Panda/UR5 motion and six RX sites. Actors are excluded.

## 2. Status

`Previous experiment`, recorded at 200 sampled frames. The source scripts are
absent, so this repository cannot rerun it from start to finish.

## 3. Differences from the main pipeline

The recorded run is rigid only, uses 200 frames and 1,200 raw RT rows, and
does not include the current 2,446-frame actor-aware source-tracking and archive
formats.

## 4. Exact experiment/archive layout

The archive contains the branch under:

```text
semantic_ablation_rigid_200f/
├── configs/experiment_config.json
├── frames/
├── rt_results/
├── features/
└── results/
```

The archive is the saved input. Do not unpack over a current run.

## 5. Required configuration and environment

The recorded config defines 200 frames, Panda/UR5, 28 GHz, six RX sites, RT
label thresholds, and rigid-only features. Reproduction would additionally
require the missing experiment scripts, Blender, Sionna RT/Mitsuba, and the
resolved static baseline. These requirements are not satisfied by source files
in the current repository version.

## 6. Recorded command order

The previous run used this order:

```text
sample frames
→ build rigid pose frames
→ resolve dynamic visuals
→ export dynamic meshes
→ compose manifests
→ build Sionna XML
→ run multi-RX RT
→ build labels
→ build object/raw features
→ run ablations
```

The old script filenames are intentionally not repeated as current commands.
Use [script_reference.md](../script_reference.md) for the current functional
names and [pipeline_execution_order.md](../pipeline_execution_order.md) for the
supported implementation.

## 7. Smoke/debug and full-run status

No current smoke/full command can rerun this branch without the archived
scripts and their run configuration. Inspection-only checks are safe:

```bash
unzip -l rt_out/experiments/semantic_ablation_200f/run_20260522_143156/semantic_ablation.zip
```

Do not run training or RT merely to test the archive.

## 8. Restart/resume status

Keep the saved results unchanged. They record the output of the original
experiment. Current restart-safe scripts target the 2,446-frame experiment and
must not be pointed at this older tree without checking whether the old files
work with the current scripts.

## 9. Recorded inputs, outputs, and counts

- sampled frames: 200;
- raw RT rows: 1,200 = 200 × 6 RX;
- horizon labels: 1,194 = 199 × 6 RX;
- downstream feature rows: 1,194 where recorded;
- actor rows: none.

## 10. Validation and limitations

Validate the archive and read the embedded reports before citing a result. The
current repository version does not provide a clean rerun, dependency lock, or
current CLI argument list for this experiment.

## 11. Links

- [Complete pipeline sequence](../pipeline_execution_order.md)
- [Current 2,446-frame guide](semantic_ablation_actor_2446f_10hz_pipeline.md)
- [Script reference](../script_reference.md)
