# Actor-aware versus rigid ablation comparison

This document is a results/interpretation record only. It does not contain an
execution sequence. For reproduction instructions use
[semantic_ablation_actor_2446f_10hz_pipeline.md](semantic_ablation_actor_2446f_10hz_pipeline.md)
or the previous 200-frame guide.

Best rows are selected by `f1_mean` within task and feature mode. Actor values
come from the recorded actor-aware result CSVs; rigid values are the recorded
rigid baseline.

| Task | Feature mode | Rigid best/model | Rigid F1 | Actor best/model | Actor F1 | Δ F1 | Rigid balanced accuracy | Actor balanced accuracy |
| --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: |
| Adaptation trigger 1 dB | compact | compact_full_object_aware / RF | 0.393 | compact_full_object_aware / RF | 0.411 | +0.018 | 0.648 | 0.658 |
| Adaptation trigger 1 dB | raw | raw_occupancy / RBF-SVM | 0.261 | raw_occupancy / RBF-SVM | 0.272 | +0.011 | 0.606 | 0.611 |
| Path change | compact | compact_full_object_aware / RBF-SVM | 0.509 | compact_full_object_aware / RF | 0.582 | +0.073 | 0.625 | 0.659 |
| Path change | raw | raw_occupancy / RBF-SVM | 0.510 | raw_occupancy / logistic | 0.527 | +0.017 | 0.628 | 0.568 |

These are saved experiment results. The current repository version cannot
rerun the previous 200-frame runs. This document contains no command that is
required before running the main pipeline.
