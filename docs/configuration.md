# Configuration reference

Configuration is split between repository inputs, copies used by a run, and
generated manifests. To rerun a change, copy the configuration used by the run
into the run directory and rerun every stage that depends on it.

## Repository and static inputs

| File | Owner/consumer | Important fields | Safe edits and rerun consequence |
| --- | --- | --- | --- |
| `myworld_rt.sdf` | Gazebo and static extraction | world models, poses, static flags, actor declarations | Geometry/model changes require manifest validation, registry, conversion/merge, XML, then RT rerun. |
| `models/` | Gazebo, registry, Blender | model SDF/config, mesh URIs, actor assets | Asset changes invalidate static/dynamic/actor products that reference them. |
| `rt_out/materials/material_map.json` | `build_static_scene_registry.py` | model/link/visual matching rules and material classes | Rerun static registry, merge, and XML. Check that every emitted material has RT mapping. |
| `rt_out/config/*` when present | prototype helpers | reusable material/site templates | Treat as templates; copy the resolved version into `<run>/config/`. |

The current repository does not expose one complete generic static-config CLI.
`build_scene_geometry_registry.py` and `build_static_scene_registry.py` retain
old default locations. The user must use the explicit paths supported by
`extract_scene_manifests.py` and `merge_static_scene_by_material.py`, and must
not assume that `--experiment-root` is accepted by every static stage.

## Run-local experiment configuration

The current reference file is:

```text
rt_out/experiments/semantic_ablation_actor_2446f_10hz/run_20260710_172015/config/experiment_config.json
```

It defines:

- `experiment_name`, `num_frames`, and `output_dir`;
- Panda and `ur5_rg2` dynamic model names;
- carrier frequency (`28` GHz);
- TX `tx_ap` and six RX IDs/positions;
- material and semantic classes of interest;
- actor `actor_walking`, `human_skin`, `human`, trajectory/animation policies,
  XY/Z alignment, floor Z, and `runtime_phase_claim: false`.

The file is used by frame sampling, batch mesh export, composition, XML, RT,
labels, feature builders, and experiment wrappers. Changing frame count,
receiver order, actor policy, or output root invalidates all downstream
products.

## Dynamic prototype configuration

`config/dynamic_prototype_config.json` is consumed by rigid and prototype
helpers. It contains:

- `prototype_frames` with `frame_id` and `source_sample_index`;
- `dynamic_models.Panda` and `dynamic_models.ur5_rg2`;
- pose-log paths;
- expected link counts (12 and 11);
- non-renderable links (`panda_link8`, `tool0`);
- forced material (`metal`).

The validated 2,446-frame run uses a separate sampled-frame config with
`source_sample_index == frame_id`; the three-frame prototype uses the
prototype sample indices. Do not reuse one as the other.

## RT material/runtime configuration

`rt_material_mapping.json` is read by `rt_material_config.py`, static/frame XML
builders, and RT sanity scripts. It owns the carrier frequency metadata and
semantic radio-material definitions (`itu` or `custom`, thickness, scattering,
XPD, and custom electromagnetic parameters). After changing it, regenerate
affected XML and rerun RT validation.

## Radio-site configuration

`prototype_radio_sites.json` is used by the three-frame multi-RX harness. The
2,446-frame experiment stores the resolved TX/RX positions directly in its
`experiment_config.json`. RX identifiers are case-sensitive and must remain
consistent across XML/CSV/label/feature records.

## Actor configuration

`actor_dynamic_config.json` and the run-local `actors` block control actor
selection, actor name, material, time policy, animation loop, XY/Z alignment,
and floor Z. The current actor export is approximate and explicitly does not
claim Gazebo runtime animation-phase equivalence.

## Perception configuration

The perception pilot configuration is stored inside the archived run
`rt_out/experiments/perception_rt_small_v0/run_20260522_133045.zip` under
`run_20260522_133045/config/`. After extraction, the active files are:

- `perception_dataset_config.json`: source experiment, selected frame count,
  camera count, sample counts, image/clip settings, and expected RT/label rows;
- `camera_rig.json`: eight fixed camera IDs, poses, resolution, FOV, and clips;
- `semantic_label_map.json`: compact semantic IDs 1–10.

The active world builder writes semantic panoptic labels in channel 2 and
Gazebo runtime instance counts in channels 1 and 0. Stable dataset instance
IDs are defined by a separate registry format.

## Generated file formats

- `manifests/static_manifest.json`, `dynamic_manifest.json`, and
  `geometry_registry.json` describe source scene structure.
- `static_scene/export/merged_static_manifest.json` is the material-merged
  static baseline consumed by static XML and composition.
- `frames/dynamic_frames.json` and `dynamic_visual_frames.json` map frame IDs
  to poses and visual records.
- `frames/composed_manifests/frame_XXX_manifest.json` is the XML input. The
  validated actor-aware run has 11 static, 21 dynamic, and 1 actor entry.
- `rt_results/rt_2446frames_multi_rx.csv` has 2,446 × 6 compact RT rows;
  horizon-10 labels have 14,616 source/RX rows.
- GT scene PLYs use exactly `x y z class_label instance_id material_id
  object_type_id source_type_id`; they are not RGB perception PCLs.

## What to rerun

| Changed input | Rerun from | Then rerun |
| --- | --- | --- |
| SDF/model/static material | `extract_scene_manifests.py` | validate → geometry/static registries → conversion/merge → XML → RT |
| Pose logs or sampled frames | `sample_experiment_frames.py` or explicit frame JSON | dynamic poses → visual frames → mesh export → composition → XML → RT |
| Actor assets/policy | `extract_actor_manifest.py`/`build_experiment_actor_frame_samples.py` | actor export → actor-aware composition → XML → RT → labels/features |
| RT material/TX/RX | resolved config and XML stage | RT and every RT-derived label/feature/model stage |
| GT point-cloud sampling/taxonomy | GT script | GT validation → voxel/descriptors and any dependent check |
| Horizon or label thresholds | `build_rt_labels.py` or canonical target builder | paired index/targets → descriptors and all downstream experiments |
| Perception camera/label config | perception selection/registry/world builder | live capture → validators → reconstruction → dataset index |

Do not overwrite a completed run in place when changing an experiment
definition. Allocate a new run directory and preserve the old run as saved
results.
