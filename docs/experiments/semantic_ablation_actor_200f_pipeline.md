# Actor-aware semantic-ablation 200-frame experiment

> **Previous experiment.** The saved branch is inside
> `rt_out/experiments/semantic_ablation_200f/run_20260522_143156/semantic_ablation.zip`.
> The old experiment scripts are not present in the current repository version.
> This document describes the saved experiment; it cannot be rerun from start
> to finish with the current files.

## 1. Experiment purpose

Measure the effect of one moving human actor on RT-derived path-change and
adaptation labels and compare object-aware features with raw occupancy.

## 2. Status

`Previous experiment`, recorded at 200 frames with actor-aware composition.

## 3. Differences from the main pipeline

The branch adds one actor mesh per selected frame, uses approximate offline
actor sampling, and reports the saved 200-frame ablations. The current
supported actor-aware implementation is the 2,446-frame guide.

## 4. Archive layout

```text
semantic_ablation_actor_200f/
├── configs/experiment_config.json
├── frames/sampled_frames.json
├── frames/actor_frame_samples.json
├── frames/actor_meshes/
├── rt_results/
├── features/
└── results/
```

The recorded actor policy was `bounds_center_xy_to_root`,
`bounds_min_z_to_floor`, `floor_z=0.1`, with `runtime_phase_claim=false`.

## 5. Required configuration/environment

The embedded config, static baseline, actor assets, Blender, Sionna RT/Mitsuba,
and the missing old scripts are all required to rerun it. The current source
tree supplies functional actor helpers but not the old 200-frame experiment
orchestrator.

## 6. Recorded end-to-end order

```text
sample rigid frames
→ build rigid pose and visual records
→ build experiment actor samples
→ export rigid + actor meshes
→ compose actor-aware manifests
→ build frame XML
→ run six-RX RT
→ build labels
→ build object/raw features
→ run ablations
```

Use [actor_aware_3frame_pipeline.md](actor_aware_3frame_pipeline.md) for the
current actor helper inputs and outputs. Do not substitute old numeric names
for the current script paths.

## 7. Smoke/debug/full status

The current repository version cannot provide a verified 200-frame smoke or
full command sequence. Safe archive inspection is:

```bash
unzip -l rt_out/experiments/semantic_ablation_200f/run_20260522_143156/semantic_ablation.zip \
  | grep 'semantic_ablation_actor_200f/' | head
```

Do not launch RT, Blender, or training against the archive as a documentation
check.

## 8. Restart/resume status

Keep the saved outputs unchanged. The current restart-safe script is hard-coded
for the 2,446-frame reference layout and does not establish that this archive
works with the current files.

## 9. Recorded counts and outputs

- 200 rigid frame records;
- 200 actor mesh exports and actor-composed manifests;
- 1,200 RT rows;
- 1,194 horizon-label rows;
- recorded object/raw feature rows and ablation results.

## 10. Known limitations

Actor placement is an RT-oriented approximation, not runtime animation-phase
reproduction. The saved branch has no current source-tracking format and must
not be presented as a newly reproducible archive.

## 11. Links

- [Complete pipeline sequence](../pipeline_execution_order.md)
- [Current 2,446-frame guide](semantic_ablation_actor_2446f_10hz_pipeline.md)
- [Script reference](../script_reference.md)
