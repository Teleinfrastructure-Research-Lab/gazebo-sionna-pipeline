# Rigid versus actor-aware 200-frame comparison

This document compares recorded label and result products. It is not an execution procedure.

## Compared inputs

- Rigid result tree: `rt_out/experiments/semantic_ablation_200f/run_20260522_143156/semantic_ablation/semantic_ablation_rigid_200f/`
- Actor-aware result tree: `rt_out/experiments/semantic_ablation_200f/run_20260522_143156/semantic_ablation/semantic_ablation_actor_200f/`
- Comparison package: `rt_out/experiments/label_comparisons/run_20260514_141847/rigid_vs_actor_200f/`

The comparison package contains 11 CSV tables and this interpretation document.

## Metric definitions

The CSVs compare labels and RT-derived quantities by frame/RX identity. Inspect a table header before combining or plotting values:

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
head -n 2 "$REPO_ROOT/rt_out/experiments/label_comparisons/run_20260514_141847/rigid_vs_actor_200f/continuous_metric_comparison.csv"
```

## Technical interpretation

Differences in labels or continuous metrics are properties of the stored comparison inputs and matching frame/RX rows. They do not demonstrate that absent upstream source inputs can be regenerated.

## Related documentation

- [Rigid 200-frame runbook](semantic_ablation_200f_pipeline.md)
- [Actor-aware 200-frame runbook](semantic_ablation_actor_200f_pipeline.md)
