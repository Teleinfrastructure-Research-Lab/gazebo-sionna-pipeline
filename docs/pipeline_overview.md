# Pipeline overview

This page describes relationships between branches. It intentionally does not
contain a complete command sequence; use
[pipeline_execution_order.md](pipeline_execution_order.md) for execution.

## Generated files by stage

```text
Gazebo SDF + models + material rules
  -> static/dynamic manifests
  -> geometry registry and static registry
  -> converted/merged static meshes
  -> composed frame manifests
  -> per-frame Sionna XML
  -> multi-RX RT rows
  -> temporal labels and features
  -> optional models/evaluation
```

The rigid branch represents Panda and UR5 as pose-log-driven link transforms.
The actor branch is separate: actors are animated/skinned assets sampled and
baked by Blender, then added to the composed manifest.

## Branch relationships

- Static geometry is the reusable foundation. Final XML uses merged static
  meshes grouped by material; converted individual meshes remain support
  generated files.
- Rigid dynamic processing consumes pose logs, sampled frame records, dynamic
  visual metadata, and Blender-exported frame meshes.
- Actor-aware processing adds actor samples and one baked actor mesh per frame.
  Actor-free and actor-aware composition are alternatives for a given frame
  set.
- Sionna XML consumes composed manifests. RT rows contain compact path/delay/
  power summaries, not full path-level channel tensors.
- Temporal labels and feature arrays consume completed RT/scene products; they
  are not prerequisites for producing PCL or RT outputs.
- The perception branch is a separate Gazebo capture path. It produces RGB,
  panoptic labels, synchronized point clouds, labeled colorized PCLs, and a
  cross-modal index. It is not silently inserted into the RT generation path.

## Current validated run

`semantic_ablation_actor_2446f_10hz/run_20260710_172015` contains 2,446 frames,
six RX records per frame, 11 static/21 dynamic/one actor XML shapes per frame,
and 14,676 compact RT rows. Its reduced eight-directory dataset archive was
checked separately; that check is not included in this repository version. The
archive is not the same as the full local run, which also contains beam, model,
result, and report directories.

## What is and is not included

The repository contains small-test tools, validation tools, and previous
experiment archives. A script under `rt_out/scripts/` may still have old
default paths, and a full experiment should not be run as a smoke test. The
script reference explains these differences.
