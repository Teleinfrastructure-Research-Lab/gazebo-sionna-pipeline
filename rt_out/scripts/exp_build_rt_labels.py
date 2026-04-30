#!/usr/bin/env python3

"""Convert experiment-local RT batch outputs into frame-to-frame labels.

For each receiver independently, this script compares consecutive frames,
computes deltas for path count, delay spread, and received power, then derives
binary supervision targets for later feasibility studies. These RT-derived
columns are labels/targets, not proactive input features for the wireless
models.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class RtLabelBuildError(RuntimeError):
    pass


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build frame-to-frame RT labels from an experiment-local multi-RX RT CSV."
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to experiment_config.json",
    )
    parser.add_argument(
        "--eta-tau",
        type=float,
        default=None,
        help="Override the delay-spread increase threshold. Default: 0.25 * std(delay_spread).",
    )
    parser.add_argument(
        "--allow-failed",
        action="store_true",
        help="Allow rows with sanity_ok != True to be skipped instead of failing.",
    )
    return parser.parse_args()


def load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise RtLabelBuildError(f"Missing input file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RtLabelBuildError(f"Invalid JSON in {path}: {exc}") from exc


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RtLabelBuildError(f"{label} must be an object")
    return value


def require_non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RtLabelBuildError(f"{label} must be a non-empty string")
    return value.strip()


def require_positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RtLabelBuildError(f"{label} must be a positive integer")
    return value


def require_numeric(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise RtLabelBuildError(f"{label} must be numeric")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise RtLabelBuildError(f"{label} must be numeric") from exc


def rt_batch_csv_name(num_frames: int) -> str:
    return f"rt_{num_frames}frames_multi_rx.csv"


def rt_labeled_csv_name(num_frames: int) -> str:
    return f"rt_{num_frames}frames_multi_rx_labeled.csv"


def resolve_project_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def load_experiment_config(path: Path) -> dict[str, Any]:
    # Load only the experiment metadata needed for labeling: experiment name,
    # frame count, and the output root containing RT results.
    config = require_object(load_json(path), "experiment_config.json")
    experiment_name = require_non_empty_string(
        config.get("experiment_name"),
        "experiment_config.experiment_name",
    )
    num_frames = require_positive_int(
        config.get("num_frames"),
        "experiment_config.num_frames",
    )
    output_dir = require_non_empty_string(
        config.get("output_dir"),
        "experiment_config.output_dir",
    )
    output_root = resolve_project_path(output_dir)
    return {
        "experiment_name": experiment_name,
        "num_frames": num_frames,
        "output_root": output_root,
    }


def parse_bool_string(value: str, label: str) -> bool:
    text = value.strip().lower()
    if text == "true":
        return True
    if text == "false":
        return False
    raise RtLabelBuildError(f"{label} must be True/False, got {value!r}")


def load_rt_rows(path: Path, *, allow_failed: bool) -> list[dict[str, Any]]:
    # Parse the RT batch CSV into typed rows and, by default, require every RT
    # solve to have succeeded before supervision labels are built.
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except FileNotFoundError as exc:
        raise RtLabelBuildError(f"Missing RT results CSV: {path}") from exc

    if not rows:
        raise RtLabelBuildError(f"RT results CSV is empty: {path}")

    parsed: list[dict[str, Any]] = []
    failed_rows: list[str] = []
    for index, row in enumerate(rows):
        try:
            frame_id = int(row["frame_id"])
            source_sample_index = int(row["source_sample_index"])
            rx_id = require_non_empty_string(row.get("rx_id"), f"row[{index}].rx_id")
            xml_path = require_non_empty_string(row.get("xml_path"), f"row[{index}].xml_path")
            sanity_ok = parse_bool_string(row.get("sanity_ok", ""), f"row[{index}].sanity_ok")
            num_paths = int(row["num_paths"]) if row.get("num_paths", "") != "" else None
            delay_spread = (
                require_numeric(row["delay_spread"], f"row[{index}].delay_spread")
                if row.get("delay_spread", "") != ""
                else None
            )
            rx_power_dbm = (
                require_numeric(row["rx_power_dbm"], f"row[{index}].rx_power_dbm")
                if row.get("rx_power_dbm", "") != ""
                else None
            )
        except KeyError as exc:
            raise RtLabelBuildError(f"Missing required CSV column: {exc}") from exc

        if not sanity_ok:
            failed_rows.append(f"frame_id={frame_id}, rx_id={rx_id}, xml_path={xml_path}")
            if allow_failed:
                continue
            continue

        if num_paths is None:
            raise RtLabelBuildError(f"row[{index}] is missing num_paths")
        if delay_spread is None:
            raise RtLabelBuildError(f"row[{index}] is missing delay_spread")
        if rx_power_dbm is None:
            raise RtLabelBuildError(f"row[{index}] is missing rx_power_dbm")

        parsed_row = dict(row)
        parsed_row.update(
            {
                "frame_id": frame_id,
                "source_sample_index": source_sample_index,
                "rx_id": rx_id,
                "xml_path": xml_path,
                "sanity_ok": sanity_ok,
                "num_paths": num_paths,
                "delay_spread": delay_spread,
                "rx_power_dbm": rx_power_dbm,
            }
        )
        parsed.append(parsed_row)

    if failed_rows and not allow_failed:
        preview = "; ".join(failed_rows[:5])
        raise RtLabelBuildError(
            "RT results contain rows with sanity_ok != True. "
            f"Examples: {preview}. Re-run with --allow-failed to skip them."
        )
    if not parsed:
        raise RtLabelBuildError("No valid RT rows remain for labeling")
    return parsed


def compute_eta_tau(rows: list[dict[str, Any]], override: float | None) -> float:
    # The delay-spread trigger threshold is experiment-wide: either user-supplied
    # or derived from the global delay-spread variability.
    if override is not None:
        return float(override)
    values = [float(row["delay_spread"]) for row in rows]
    if len(values) < 2:
        return 0.0
    return 0.25 * statistics.pstdev(values)


def build_labeled_rows(rows: list[dict[str, Any]], eta_tau: float) -> list[dict[str, Any]]:
    # Label each RX independently so frame-to-frame deltas compare consecutive
    # observations from the same receiver position only.
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["rx_id"], []).append(row)

    labeled_rows: list[dict[str, Any]] = []
    for rx_id in sorted(grouped):
        ordered = sorted(grouped[rx_id], key=lambda item: (item["frame_id"], item["source_sample_index"]))
        previous: dict[str, Any] | None = None
        for row in ordered:
            if previous is None:
                # Drop the first frame per RX from supervision because there is
                # no previous frame to compare against.
                previous = row
                continue

            # Compare each frame against the immediately previous frame for the
            # same RX. Path-count change is a propagation-structure diagnostic,
            # while delay spread and received-power deltas are the ingredients
            # used by the downstream adaptation-trigger labels.
            delta_num_paths = int(row["num_paths"]) - int(previous["num_paths"])
            delta_delay_spread = float(row["delay_spread"]) - float(previous["delay_spread"])

            # dBm differences are already dB changes, so subtracting consecutive
            # received powers gives the exact drop/increase in dB.
            delta_rx_power_db = float(row["rx_power_dbm"]) - float(previous["rx_power_dbm"])

            labeled = dict(row)
            labeled.update(
                {
                    "prev_num_paths": previous["num_paths"],
                    "prev_delay_spread": previous["delay_spread"],
                    "prev_rx_power_dbm": previous["rx_power_dbm"],
                    "delta_num_paths": delta_num_paths,
                    "delta_delay_spread": delta_delay_spread,
                    "delta_rx_power_db": delta_rx_power_db,
                    "y_path_change": int(delta_num_paths != 0),
                    "y_path_drop": int(delta_num_paths < 0),
                    "y_rx_power_drop_0p5db": int(delta_rx_power_db < -0.5),
                    "y_rx_power_drop_1db": int(delta_rx_power_db < -1.0),
                    "y_rx_power_drop_2db": int(delta_rx_power_db < -2.0),
                    "y_delay_spread_increase": int(delta_delay_spread > eta_tau),
                }
            )
            # The adaptation-trigger labels intentionally stay simple: fire when
            # the received-power drop threshold is crossed and/or delay spread
            # increases beyond the experiment-level eta_tau threshold.
            labeled["y_adaptation_trigger_1db"] = int(
                labeled["y_rx_power_drop_1db"] == 1 or labeled["y_delay_spread_increase"] == 1
            )
            labeled["y_adaptation_trigger_2db"] = int(
                labeled["y_rx_power_drop_2db"] == 1 or labeled["y_delay_spread_increase"] == 1
            )
            labeled_rows.append(labeled)
            previous = row

    if not labeled_rows:
        raise RtLabelBuildError("No labeled rows were produced")
    return labeled_rows


def write_labeled_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def build_summary_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # Summarize class balance both overall and per RX so the later ablation
    # scripts can quickly assess class skew.
    summary_rows: list[dict[str, Any]] = []
    for label in LABEL_COLUMNS:
        positives = sum(int(row[label]) for row in rows)
        count = len(rows)
        summary_rows.append(
            {
                "label": label,
                "rx_id": "ALL",
                "num_rows": count,
                "num_positive": positives,
                "positive_ratio": positives / count if count else 0.0,
            }
        )

    rx_ids = sorted({str(row["rx_id"]) for row in rows})
    for rx_id in rx_ids:
        subset = [row for row in rows if row["rx_id"] == rx_id]
        count = len(subset)
        for label in LABEL_COLUMNS:
            positives = sum(int(row[label]) for row in subset)
            summary_rows.append(
                {
                    "label": label,
                    "rx_id": rx_id,
                    "num_rows": count,
                    "num_positive": positives,
                    "positive_ratio": positives / count if count else 0.0,
                }
            )
    return summary_rows


def write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["label", "rx_id", "num_rows", "num_positive", "positive_ratio"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def print_balance(summary_rows: list[dict[str, Any]]) -> None:
    print("Overall label balance")
    for row in summary_rows:
        if row["rx_id"] != "ALL":
            continue
        print(
            f"  {row['label']}: positives={row['num_positive']}/{row['num_rows']} "
            f"ratio={float(row['positive_ratio']):.4f}"
        )

    print("Per-RX label balance")
    for rx_id in sorted({row["rx_id"] for row in summary_rows if row["rx_id"] != "ALL"}):
        print(f"  {rx_id}")
        for row in summary_rows:
            if row["rx_id"] != rx_id:
                continue
            print(
                f"    {row['label']}: positives={row['num_positive']}/{row['num_rows']} "
                f"ratio={float(row['positive_ratio']):.4f}"
            )


def main() -> int:
    args = parse_args()
    config_path = args.config.expanduser().resolve()
    if not config_path.exists():
        raise RtLabelBuildError(f"Config file does not exist: {config_path}")

    experiment = load_experiment_config(config_path)
    rt_results_dir = experiment["output_root"] / "rt_results"
    input_csv = rt_results_dir / rt_batch_csv_name(experiment["num_frames"])
    labeled_csv = rt_results_dir / rt_labeled_csv_name(experiment["num_frames"])
    summary_csv = rt_results_dir / "rt_label_summary.csv"

    rows = load_rt_rows(input_csv, allow_failed=args.allow_failed)
    eta_tau = compute_eta_tau(rows, args.eta_tau)
    labeled_rows = build_labeled_rows(rows, eta_tau)

    # With N frames per RX, dropping the first frame should leave (N-1) labeled
    # rows per receiver.
    expected_labeled = experiment["num_frames"] - 1
    rx_ids = sorted({row["rx_id"] for row in labeled_rows})
    expected_total = expected_labeled * len(rx_ids)
    if len(labeled_rows) != expected_total:
        raise RtLabelBuildError(
            f"Expected {expected_total} labeled rows ({expected_labeled} per RX), got {len(labeled_rows)}"
        )

    write_labeled_csv(labeled_csv, labeled_rows)
    summary_rows = build_summary_rows(labeled_rows)
    write_summary_csv(summary_csv, summary_rows)

    print(f"experiment_name: {experiment['experiment_name']}")
    print(f"eta_tau: {eta_tau}")
    print(f"labeled_rows: {len(labeled_rows)}")
    print(f"labeled_csv: {labeled_csv}")
    print(f"summary_csv: {summary_csv}")
    print_balance(summary_rows)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RtLabelBuildError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
