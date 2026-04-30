# semantic_ablation_rigid_200f

This experiment uses simulated object annotations, not predicted 3D segmentation.

Dynamic scope: Panda + ur5_rg2 rigid motion.

Actors are excluded.

Purpose: generate RT labels and object-level semantic/material features for a small feasibility ablation.

The experiment does not evaluate the final HGNN/resource allocation model.

For the current end-to-end command flow, naming quirks, and generated-output
warnings, see:

- [`docs/semantic_ablation_200f_pipeline.md`](../../../docs/semantic_ablation_200f_pipeline.md)
