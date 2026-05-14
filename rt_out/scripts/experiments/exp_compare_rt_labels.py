#!/usr/bin/env python3

"""Compare rigid-baseline and actor-aware RT label tables."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[3]
EXPECTED_ROWS = 1194
JOIN_KEYS = ("frame_id", "source_sample_index", "rx_id")
LABEL_COLUMNS = [
    "y_path_change",
    "y_path_drop",
    "y_rx_power_drop_0p5db",
    "y_rx_power_drop_1db",
    "y_rx_power_drop_2db",
    "y_delay_spread_increase",
    "y_adaptation_trigger_1db",
    "y_adaptation_trigger_2db",
]
CONTINUOUS_COLUMNS = [
    "num_paths",
    "prev_num_paths",
    "delta_num_paths",
    "delay_spread",
    "prev_delay_spread",
    "delta_delay_spread",
    "rx_power_dbm",
    "prev_rx_power_dbm",
    "delta_rx_power_db",
]


class RtLabelComparisonError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare rigid and actor-aware experiment RT label tables.")
    parser.add_argument("--baseline-labels", type=Path, required=True)
    parser.add_argument("--actor-labels", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def resolve_path(path: Path) -> Path:
    path = path.expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def require_exists(path: Path, label: str) -> None:
    if not path.exists():
        raise RtLabelComparisonError(f"Missing {label}: {path}")


def parse_binary(value: str, label: str) -> int:
    text = value.strip()
    if text in {"0", "1"}:
        return int(text)
    raise RtLabelComparisonError(f"{label} must be 0/1, got {value!r}")


def parse_int_str(value: str, label: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise RtLabelComparisonError(f"{label} must be an integer, got {value!r}") from exc


def parse_float_optional(value: str) -> float | None:
    text = value.strip()
    if text == "":
        return None
    try:
        number = float(text)
    except ValueError as exc:
        raise RtLabelComparisonError(f"Expected numeric value, got {value!r}") from exc
    if not math.isfinite(number):
        raise RtLabelComparisonError(f"Expected finite numeric value, got {value!r}")
    return number


def load_csv_rows(path: Path, label: str) -> tuple[list[dict[str, str]], list[str]]:
    require_exists(path, label)
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise RtLabelComparisonError(f"{label} has no header row: {path}")
        rows = list(reader)
        return rows, list(reader.fieldnames)


def validate_schema(rows: list[dict[str, str]], fieldnames: list[str], label: str) -> None:
    required = set(JOIN_KEYS) | set(LABEL_COLUMNS)
    missing = sorted(required - set(fieldnames))
    if missing:
        raise RtLabelComparisonError(f"{label} is missing required columns: {missing}")
    if len(rows) != EXPECTED_ROWS:
        raise RtLabelComparisonError(f"{label} expected {EXPECTED_ROWS} rows, got {len(rows)}")


def key_for_row(row: dict[str, str]) -> tuple[str, str, str]:
    return tuple(row[column] for column in JOIN_KEYS)


def build_index(rows: list[dict[str, str]], label: str) -> dict[tuple[str, str, str], dict[str, str]]:
    index: dict[tuple[str, str, str], dict[str, str]] = {}
    duplicates: list[tuple[str, str, str]] = []
    for row in rows:
        key = key_for_row(row)
        if key in index:
            duplicates.append(key)
        index[key] = row
    if duplicates:
        raise RtLabelComparisonError(f"{label} has duplicate join keys, first examples: {duplicates[:5]}")
    return index


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def compare_labels(
    joined_rows: list[tuple[dict[str, str], dict[str, str]]],
    output_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    summary_rows: list[dict[str, Any]] = []
    by_rx_rows: list[dict[str, Any]] = []
    changed_count_by_label: dict[str, int] = {}

    changed_dir = output_dir
    rx_ids = sorted({baseline["rx_id"] for baseline, _ in joined_rows})

    for label in LABEL_COLUMNS:
        changed_rows: list[dict[str, Any]] = []
        baseline_positives = 0
        actor_positives = 0
        actor_new_positive = 0
        actor_lost_positive = 0
        unchanged_positive = 0
        unchanged_negative = 0

        for baseline, actor in joined_rows:
            b = parse_binary(baseline[label], f"baseline {label}")
            a = parse_binary(actor[label], f"actor {label}")
            baseline_positives += b
            actor_positives += a
            if b == 0 and a == 1:
                actor_new_positive += 1
            elif b == 1 and a == 0:
                actor_lost_positive += 1
            elif b == 1 and a == 1:
                unchanged_positive += 1
            else:
                unchanged_negative += 1
            if a != b:
                changed_rows.append(
                    {
                        "frame_id": baseline["frame_id"],
                        "source_sample_index": baseline["source_sample_index"],
                        "rx_id": baseline["rx_id"],
                        "label": label,
                        "baseline_value": b,
                        "actor_value": a,
                        "baseline_num_paths": baseline.get("num_paths", ""),
                        "actor_num_paths": actor.get("num_paths", ""),
                        "baseline_delay_spread": baseline.get("delay_spread", ""),
                        "actor_delay_spread": actor.get("delay_spread", ""),
                        "baseline_rx_power_dbm": baseline.get("rx_power_dbm", ""),
                        "actor_rx_power_dbm": actor.get("rx_power_dbm", ""),
                        "baseline_delta_num_paths": baseline.get("delta_num_paths", ""),
                        "actor_delta_num_paths": actor.get("delta_num_paths", ""),
                        "baseline_delta_delay_spread": baseline.get("delta_delay_spread", ""),
                        "actor_delta_delay_spread": actor.get("delta_delay_spread", ""),
                        "baseline_delta_rx_power_db": baseline.get("delta_rx_power_db", ""),
                        "actor_delta_rx_power_db": actor.get("delta_rx_power_db", ""),
                    }
                )

        changed_count = len(changed_rows)
        changed_count_by_label[label] = changed_count
        total_rows = len(joined_rows)
        summary_rows.append(
            {
                "label": label,
                "baseline_positives": baseline_positives,
                "actor_positives": actor_positives,
                "baseline_positive_ratio": ratio(baseline_positives, total_rows),
                "actor_positive_ratio": ratio(actor_positives, total_rows),
                "delta_positives": actor_positives - baseline_positives,
                "rows_changed": changed_count,
                "rows_changed_ratio": ratio(changed_count, total_rows),
                "actor_new_positive": actor_new_positive,
                "actor_lost_positive": actor_lost_positive,
                "unchanged_positive": unchanged_positive,
                "unchanged_negative": unchanged_negative,
            }
        )
        write_csv(
            changed_dir / f"changed_rows_{label}.csv",
            [
                "frame_id",
                "source_sample_index",
                "rx_id",
                "label",
                "baseline_value",
                "actor_value",
                "baseline_num_paths",
                "actor_num_paths",
                "baseline_delay_spread",
                "actor_delay_spread",
                "baseline_rx_power_dbm",
                "actor_rx_power_dbm",
                "baseline_delta_num_paths",
                "actor_delta_num_paths",
                "baseline_delta_delay_spread",
                "actor_delta_delay_spread",
                "baseline_delta_rx_power_db",
                "actor_delta_rx_power_db",
            ],
            changed_rows,
        )

        for rx_id in rx_ids:
            subset = [(baseline, actor) for baseline, actor in joined_rows if baseline["rx_id"] == rx_id]
            baseline_pos = 0
            actor_pos = 0
            new_pos = 0
            lost_pos = 0
            rows_changed = 0
            for baseline, actor in subset:
                b = parse_binary(baseline[label], f"baseline {label}")
                a = parse_binary(actor[label], f"actor {label}")
                baseline_pos += b
                actor_pos += a
                if b == 0 and a == 1:
                    new_pos += 1
                elif b == 1 and a == 0:
                    lost_pos += 1
                if a != b:
                    rows_changed += 1
            by_rx_rows.append(
                {
                    "rx_id": rx_id,
                    "label": label,
                    "baseline_positives": baseline_pos,
                    "actor_positives": actor_pos,
                    "actor_new_positive": new_pos,
                    "actor_lost_positive": lost_pos,
                    "rows_changed": rows_changed,
                }
            )

    return summary_rows, by_rx_rows, changed_count_by_label


def compare_continuous(joined_rows: list[tuple[dict[str, str], dict[str, str]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for column in CONTINUOUS_COLUMNS:
        deltas: list[float] = []
        baseline_values: list[float] = []
        actor_values: list[float] = []
        for baseline, actor in joined_rows:
            baseline_value = parse_float_optional(baseline.get(column, ""))
            actor_value = parse_float_optional(actor.get(column, ""))
            if baseline_value is None or actor_value is None:
                continue
            baseline_values.append(baseline_value)
            actor_values.append(actor_value)
            deltas.append(actor_value - baseline_value)
        if not deltas:
            continue
        rows.append(
            {
                "metric": column,
                "count": len(deltas),
                "mean_baseline": statistics.fmean(baseline_values),
                "mean_actor": statistics.fmean(actor_values),
                "mean_actor_minus_baseline": statistics.fmean(deltas),
                "median_actor_minus_baseline": median(deltas),
                "min_actor_minus_baseline": min(deltas),
                "max_actor_minus_baseline": max(deltas),
            }
        )
    return rows


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def build_markdown_report(
    *,
    baseline_path: Path,
    actor_path: Path,
    output_path: Path,
    validation_summary: dict[str, Any],
    summary_rows: list[dict[str, Any]],
    by_rx_rows: list[dict[str, Any]],
    changed_count_by_label: dict[str, int],
) -> None:
    top_labels = sorted(summary_rows, key=lambda row: int(row["rows_changed"]), reverse=True)[:5]
    rx_change_totals: dict[str, int] = {}
    for row in by_rx_rows:
        rx_change_totals[row["rx_id"]] = rx_change_totals.get(row["rx_id"], 0) + int(row["rows_changed"])
    top_rxs = sorted(rx_change_totals.items(), key=lambda item: item[1], reverse=True)

    overall_table = markdown_table(
        [
            "Label",
            "Baseline+",
            "Actor+",
            "Delta+",
            "Changed",
            "Changed Ratio",
            "New +",
            "Lost +",
        ],
        [
            [
                str(row["label"]),
                str(row["baseline_positives"]),
                str(row["actor_positives"]),
                str(row["delta_positives"]),
                str(row["rows_changed"]),
                f"{float(row['rows_changed_ratio']):.4f}",
                str(row["actor_new_positive"]),
                str(row["actor_lost_positive"]),
            ]
            for row in summary_rows
        ],
    )

    per_rx_table = markdown_table(
        ["RX", "Label", "Baseline+", "Actor+", "New +", "Lost +", "Changed"],
        [
            [
                str(row["rx_id"]),
                str(row["label"]),
                str(row["baseline_positives"]),
                str(row["actor_positives"]),
                str(row["actor_new_positive"]),
                str(row["actor_lost_positive"]),
                str(row["rows_changed"]),
            ]
            for row in by_rx_rows
        ],
    )

    increases = [row["label"] for row in summary_rows if int(row["delta_positives"]) > 0]
    decreases = [row["label"] for row in summary_rows if int(row["delta_positives"]) < 0]
    trigger_rows = [row for row in summary_rows if "adaptation_trigger" in str(row["label"])]
    path_rows = [row for row in summary_rows if "path" in str(row["label"])]

    md = f"""# Actor vs Rigid RT Label Comparison

## Inputs

- Baseline labels: `{baseline_path}`
- Actor labels: `{actor_path}`
- Join keys: `{", ".join(JOIN_KEYS)}`

## Validation Summary

- Baseline row count: `{validation_summary['baseline_rows']}`
- Actor row count: `{validation_summary['actor_rows']}`
- Expected row count: `{validation_summary['expected_rows']}`
- Matching joined rows: `{validation_summary['joined_rows']}`
- Missing baseline rows in actor: `{validation_summary['missing_in_actor']}`
- Missing actor rows in baseline: `{validation_summary['missing_in_baseline']}`
- Duplicate join violations: `{validation_summary['duplicate_violations']}`

## Overall Label Comparison

{overall_table}

## Per-RX Label Comparison

{per_rx_table}

## Most Changed Labels

{markdown_table(["Label", "Rows Changed"], [[str(row["label"]), str(row["rows_changed"])] for row in top_labels])}

## Most Affected RXs

{markdown_table(["RX", "Total Changed Labels"], [[rx, str(count)] for rx, count in top_rxs])}

## Interpretation

- Labels with higher positive counts in the actor-aware branch: `{", ".join(increases) if increases else "none"}`.
- Labels with lower positive counts in the actor-aware branch: `{", ".join(decreases) if decreases else "none"}`.
- Adaptation-trigger labels changed as follows: `{", ".join(f"{row['label']}={row['rows_changed']} changed rows" for row in trigger_rows)}`.
- Path-related labels changed as follows: `{", ".join(f"{row['label']}={row['rows_changed']} changed rows" for row in path_rows)}`.
- RXs with the largest total number of label flips: `{", ".join(f"{rx}={count}" for rx, count in top_rxs[:3])}`.

## Caveat

Actor timing is offline sampled and not Gazebo-runtime-perfect phase.
"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(md, encoding="utf-8")


def main() -> int:
    args = parse_args()
    baseline_path = resolve_path(args.baseline_labels)
    actor_path = resolve_path(args.actor_labels)
    output_dir = resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    baseline_rows, baseline_fields = load_csv_rows(baseline_path, "baseline labels CSV")
    actor_rows, actor_fields = load_csv_rows(actor_path, "actor labels CSV")
    validate_schema(baseline_rows, baseline_fields, "baseline labels CSV")
    validate_schema(actor_rows, actor_fields, "actor labels CSV")
    if len(baseline_rows) != len(actor_rows):
        raise RtLabelComparisonError(
            f"Row count mismatch: baseline={len(baseline_rows)} actor={len(actor_rows)}"
        )

    baseline_index = build_index(baseline_rows, "baseline labels CSV")
    actor_index = build_index(actor_rows, "actor labels CSV")
    missing_in_actor = sorted(set(baseline_index) - set(actor_index))
    missing_in_baseline = sorted(set(actor_index) - set(baseline_index))
    if missing_in_actor:
        raise RtLabelComparisonError(f"Baseline rows missing in actor labels, first examples: {missing_in_actor[:5]}")
    if missing_in_baseline:
        raise RtLabelComparisonError(
            f"Actor rows missing in baseline labels, first examples: {missing_in_baseline[:5]}"
        )

    joined_keys = sorted(baseline_index)
    joined_rows = [(baseline_index[key], actor_index[key]) for key in joined_keys]

    summary_rows, by_rx_rows, changed_count_by_label = compare_labels(joined_rows, output_dir)
    continuous_rows = compare_continuous(joined_rows)

    write_csv(
        output_dir / "label_comparison_summary.csv",
        [
            "label",
            "baseline_positives",
            "actor_positives",
            "baseline_positive_ratio",
            "actor_positive_ratio",
            "delta_positives",
            "rows_changed",
            "rows_changed_ratio",
            "actor_new_positive",
            "actor_lost_positive",
            "unchanged_positive",
            "unchanged_negative",
        ],
        summary_rows,
    )
    write_csv(
        output_dir / "label_comparison_by_rx.csv",
        [
            "rx_id",
            "label",
            "baseline_positives",
            "actor_positives",
            "actor_new_positive",
            "actor_lost_positive",
            "rows_changed",
        ],
        by_rx_rows,
    )
    if continuous_rows:
        write_csv(
            output_dir / "continuous_metric_comparison.csv",
            [
                "metric",
                "count",
                "mean_baseline",
                "mean_actor",
                "mean_actor_minus_baseline",
                "median_actor_minus_baseline",
                "min_actor_minus_baseline",
                "max_actor_minus_baseline",
            ],
            continuous_rows,
        )
    else:
        write_csv(
            output_dir / "continuous_metric_comparison.csv",
            [
                "metric",
                "count",
                "mean_baseline",
                "mean_actor",
                "mean_actor_minus_baseline",
                "median_actor_minus_baseline",
                "min_actor_minus_baseline",
                "max_actor_minus_baseline",
            ],
            [],
        )

    validation_summary = {
        "baseline_rows": len(baseline_rows),
        "actor_rows": len(actor_rows),
        "expected_rows": EXPECTED_ROWS,
        "joined_rows": len(joined_rows),
        "missing_in_actor": len(missing_in_actor),
        "missing_in_baseline": len(missing_in_baseline),
        "duplicate_violations": 0,
    }
    save_path = output_dir / "actor_vs_rigid_label_comparison.md"
    build_markdown_report(
        baseline_path=baseline_path,
        actor_path=actor_path,
        output_path=save_path,
        validation_summary=validation_summary,
        summary_rows=summary_rows,
        by_rx_rows=by_rx_rows,
        changed_count_by_label=changed_count_by_label,
    )

    top_labels = sorted(summary_rows, key=lambda row: int(row["rows_changed"]), reverse=True)
    rx_change_totals: dict[str, int] = {}
    for row in by_rx_rows:
        rx_change_totals[row["rx_id"]] = rx_change_totals.get(row["rx_id"], 0) + int(row["rows_changed"])
    top_rxs = sorted(rx_change_totals.items(), key=lambda item: item[1], reverse=True)

    print("Validation summary")
    print(f"  baseline_rows: {len(baseline_rows)}")
    print(f"  actor_rows: {len(actor_rows)}")
    print(f"  expected_rows: {EXPECTED_ROWS}")
    print(f"  joined_rows: {len(joined_rows)}")
    print(f"  missing_in_actor: {len(missing_in_actor)}")
    print(f"  missing_in_baseline: {len(missing_in_baseline)}")
    print("Overall comparison summary")
    for row in summary_rows:
        print(
            f"  {row['label']}: baseline+={row['baseline_positives']} actor+={row['actor_positives']} "
            f"delta={row['delta_positives']} changed={row['rows_changed']}"
        )
    print("Labels with largest changed-row count")
    for row in top_labels[:5]:
        print(f"  {row['label']}: {row['rows_changed']}")
    print("RXs with largest changed-row count")
    for rx_id, count in top_rxs:
        print(f"  {rx_id}: {count}")
    print(f"markdown_report: {save_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RtLabelComparisonError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
