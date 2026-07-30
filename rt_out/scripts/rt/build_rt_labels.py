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
import sys
from pathlib import Path
from typing import Any
PROJECT_ROOT = Path(__file__).resolve().parents[3]

class RtLabelBuildError(RuntimeError):
    pass
LABEL_COLUMNS = ['y_path_change', 'y_path_drop', 'y_rx_power_drop_0p5db', 'y_rx_power_drop_1db', 'y_rx_power_drop_2db', 'y_delay_spread_increase', 'y_adaptation_trigger_1db', 'y_adaptation_trigger_2db']
CANONICAL_RX_IDS = ('rx_panda_base', 'rx_ur5_base', 'rx_cerberus_base', 'rx_nao_chest', 'rx_human_chest', 'rx_x500_body')

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Build frame-to-frame RT labels from an experiment-local multi-RX RT CSV.')
    parser.add_argument('--config', type=Path, required=True, help='Path to experiment_config.json')
    parser.add_argument('--eta-tau', type=float, default=None, help='Override the delay-spread increase threshold. Default: 0.25 * std(delay_spread).')
    parser.add_argument('--allow-failed', action='store_true', help='Allow rows with sanity_ok != True to be skipped instead of failing.')
    parser.add_argument('--horizon-frames', type=int, default=1, help='Temporal target horizon; default preserves consecutive-frame labels.')
    parser.add_argument('--one-second-split', action='store_true', help='Apply the fixed 2446-frame chronological split for a 10-frame horizon.')
    parser.add_argument('--validate-only', action='store_true', help='Validate the canonical 1-second input/output contract without writing files.')
    return parser.parse_args()

def load_json(path: Path) -> Any:
    try:
        with path.open('r', encoding='utf-8') as handle:
            return json.load(handle)
    except FileNotFoundError as exc:
        raise RtLabelBuildError(f'Missing input file: {path}') from exc
    except json.JSONDecodeError as exc:
        raise RtLabelBuildError(f'Invalid JSON in {path}: {exc}') from exc

def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RtLabelBuildError(f'{label} must be an object')
    return value

def require_non_empty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RtLabelBuildError(f'{label} must be a non-empty string')
    return value.strip()

def require_positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RtLabelBuildError(f'{label} must be a positive integer')
    return value

def require_numeric(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise RtLabelBuildError(f'{label} must be numeric')
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise RtLabelBuildError(f'{label} must be numeric') from exc

def rt_batch_csv_name(num_frames: int) -> str:
    return f'rt_{num_frames}frames_multi_rx.csv'

def rt_labeled_csv_name(num_frames: int) -> str:
    return f'rt_{num_frames}frames_multi_rx_labeled.csv'

def resolve_project_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()

def load_experiment_config(path: Path) -> dict[str, Any]:
    config = require_object(load_json(path), 'experiment_config.json')
    experiment_name = require_non_empty_string(config.get('experiment_name'), 'experiment_config.experiment_name')
    num_frames = require_positive_int(config.get('num_frames'), 'experiment_config.num_frames')
    output_dir = require_non_empty_string(config.get('output_dir'), 'experiment_config.output_dir')
    output_root = resolve_project_path(output_dir)
    rx_list = config.get('rx_list')
    if not isinstance(rx_list, list) or [item.get('id') if isinstance(item, dict) else None for item in rx_list] != list(CANONICAL_RX_IDS):
        raise RtLabelBuildError('experiment_config.rx_list is not the exact canonical receiver list/order')
    return {'experiment_name': experiment_name, 'num_frames': num_frames, 'output_root': output_root, 'rx_ids': CANONICAL_RX_IDS}

def parse_bool_string(value: str, label: str) -> bool:
    text = value.strip().lower()
    if text == 'true':
        return True
    if text == 'false':
        return False
    raise RtLabelBuildError(f'{label} must be True/False, got {value!r}')

def load_rt_rows(path: Path, *, allow_failed: bool) -> list[dict[str, Any]]:
    try:
        with path.open('r', encoding='utf-8', newline='') as handle:
            rows = list(csv.DictReader(handle))
    except FileNotFoundError as exc:
        raise RtLabelBuildError(f'Missing RT results CSV: {path}') from exc
    if not rows:
        raise RtLabelBuildError(f'RT results CSV is empty: {path}')
    parsed: list[dict[str, Any]] = []
    failed_rows: list[str] = []
    for (index, row) in enumerate(rows):
        try:
            frame_id = int(row['frame_id'])
            source_sample_index = int(row['source_sample_index'])
            rx_id = require_non_empty_string(row.get('rx_id'), f'row[{index}].rx_id')
            xml_path = require_non_empty_string(row.get('xml_path'), f'row[{index}].xml_path')
            sanity_ok = parse_bool_string(row.get('sanity_ok', ''), f'row[{index}].sanity_ok')
            num_paths = int(row['num_paths']) if row.get('num_paths', '') != '' else None
            delay_spread = require_numeric(row['delay_spread'], f'row[{index}].delay_spread') if row.get('delay_spread', '') != '' else None
            rx_power_dbm = require_numeric(row['rx_power_dbm'], f'row[{index}].rx_power_dbm') if row.get('rx_power_dbm', '') != '' else None
        except KeyError as exc:
            raise RtLabelBuildError(f'Missing required CSV column: {exc}') from exc
        if not sanity_ok:
            failed_rows.append(f'frame_id={frame_id}, rx_id={rx_id}, xml_path={xml_path}')
            if allow_failed:
                continue
            continue
        if num_paths is None:
            raise RtLabelBuildError(f'row[{index}] is missing num_paths')
        if delay_spread is None:
            raise RtLabelBuildError(f'row[{index}] is missing delay_spread')
        if rx_power_dbm is None:
            raise RtLabelBuildError(f'row[{index}] is missing rx_power_dbm')
        parsed_row = dict(row)
        parsed_row.update({'frame_id': frame_id, 'source_sample_index': source_sample_index, 'rx_id': rx_id, 'xml_path': xml_path, 'sanity_ok': sanity_ok, 'num_paths': num_paths, 'delay_spread': delay_spread, 'rx_power_dbm': rx_power_dbm})
        parsed.append(parsed_row)
    if failed_rows and (not allow_failed):
        preview = '; '.join(failed_rows[:5])
        raise RtLabelBuildError(f'RT results contain rows with sanity_ok != True. Examples: {preview}. Re-run with --allow-failed to skip them.')
    if not parsed:
        raise RtLabelBuildError('No valid RT rows remain for labeling')
    return parsed

def compute_eta_tau(rows: list[dict[str, Any]], override: float | None) -> float:
    if override is not None:
        return float(override)
    values = [float(row['delay_spread']) for row in rows]
    if len(values) < 2:
        return 0.0
    return 0.25 * statistics.pstdev(values)

def build_labeled_rows(rows: list[dict[str, Any]], eta_tau: float) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row['rx_id'], []).append(row)
    labeled_rows: list[dict[str, Any]] = []
    for rx_id in sorted(grouped):
        ordered = sorted(grouped[rx_id], key=lambda item: (item['frame_id'], item['source_sample_index']))
        previous: dict[str, Any] | None = None
        for row in ordered:
            if previous is None:
                previous = row
                continue
            delta_num_paths = int(row['num_paths']) - int(previous['num_paths'])
            delta_delay_spread = float(row['delay_spread']) - float(previous['delay_spread'])
            delta_rx_power_db = float(row['rx_power_dbm']) - float(previous['rx_power_dbm'])
            labeled = dict(row)
            labeled.update({'prev_num_paths': previous['num_paths'], 'prev_delay_spread': previous['delay_spread'], 'prev_rx_power_dbm': previous['rx_power_dbm'], 'delta_num_paths': delta_num_paths, 'delta_delay_spread': delta_delay_spread, 'delta_rx_power_db': delta_rx_power_db, 'y_path_change': int(delta_num_paths != 0), 'y_path_drop': int(delta_num_paths < 0), 'y_rx_power_drop_0p5db': int(delta_rx_power_db < -0.5), 'y_rx_power_drop_1db': int(delta_rx_power_db < -1.0), 'y_rx_power_drop_2db': int(delta_rx_power_db < -2.0), 'y_delay_spread_increase': int(delta_delay_spread > eta_tau)})
            labeled['y_adaptation_trigger_1db'] = int(labeled['y_rx_power_drop_1db'] == 1 or labeled['y_delay_spread_increase'] == 1)
            labeled['y_adaptation_trigger_2db'] = int(labeled['y_rx_power_drop_2db'] == 1 or labeled['y_delay_spread_increase'] == 1)
            labeled_rows.append(labeled)
            previous = row
    if not labeled_rows:
        raise RtLabelBuildError('No labeled rows were produced')
    return labeled_rows

def write_labeled_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys())
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

def build_summary_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary_rows: list[dict[str, Any]] = []
    for label in LABEL_COLUMNS:
        positives = sum((int(row[label]) for row in rows))
        count = len(rows)
        summary_rows.append({'label': label, 'rx_id': 'ALL', 'num_rows': count, 'num_positive': positives, 'positive_ratio': positives / count if count else 0.0})
    rx_ids = sorted({str(row['rx_id']) for row in rows})
    for rx_id in rx_ids:
        subset = [row for row in rows if row['rx_id'] == rx_id]
        count = len(subset)
        for label in LABEL_COLUMNS:
            positives = sum((int(row[label]) for row in subset))
            summary_rows.append({'label': label, 'rx_id': rx_id, 'num_rows': count, 'num_positive': positives, 'positive_ratio': positives / count if count else 0.0})
    return summary_rows

def write_summary_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ['label', 'rx_id', 'num_rows', 'num_positive', 'positive_ratio']
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

def print_balance(summary_rows: list[dict[str, Any]]) -> None:
    print('Overall label balance')
    for row in summary_rows:
        if row['rx_id'] != 'ALL':
            continue
        print(f"  {row['label']}: positives={row['num_positive']}/{row['num_rows']} ratio={float(row['positive_ratio']):.4f}")
    print('Per-RX label balance')
    for rx_id in sorted({row['rx_id'] for row in summary_rows if row['rx_id'] != 'ALL'}):
        print(f'  {rx_id}')
        for row in summary_rows:
            if row['rx_id'] != rx_id:
                continue
            print(f"    {row['label']}: positives={row['num_positive']}/{row['num_rows']} ratio={float(row['positive_ratio']):.4f}")

def write_atomic_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if path.exists():
        raise RtLabelBuildError(f'Refusing to overwrite existing output: {path}')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)

def write_atomic_json(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise RtLabelBuildError(f'Refusing to overwrite existing output: {path}')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)

def compute_training_eta_tau(rows: list[dict[str, Any]], override: float | None) -> float:
    if override is not None:
        return float(override)
    values = [float(row['delay_spread']) for row in rows if 0 <= int(row['frame_id']) <= 1704]
    if len(values) != 1705 * len(CANONICAL_RX_IDS):
        raise RtLabelBuildError('eta_tau training-state span is incomplete')
    return 0.25 * statistics.pstdev(values)

def build_one_second_rows(rows: list[dict[str, Any]], eta_tau: float, rx_ids: tuple[str, ...]) -> list[dict[str, Any]]:
    required_metrics = ('num_paths', 'tau_min', 'tau_max', 'delay_spread', 'path_gain_sum', 'path_gain_db', 'rx_power_dbm')
    index: dict[tuple[int, str], dict[str, Any]] = {}
    for row in rows:
        key = (int(row['frame_id']), str(row['rx_id']))
        if key in index:
            raise RtLabelBuildError(f'Duplicate RT key: {key}')
        if key[0] not in range(2446):
            raise RtLabelBuildError(f'Out-of-range RT frame: {key[0]}')
        if int(row['source_sample_index']) != key[0]:
            raise RtLabelBuildError(f'source_sample_index mismatch for {key}')
        if 'timestamp' not in row:
            raise RtLabelBuildError('RT CSV lacks timestamp required for 1-second labels')
        for metric in required_metrics:
            try:
                value = float(row[metric])
            except (KeyError, TypeError, ValueError) as exc:
                raise RtLabelBuildError(f'Missing required RT metric {metric} for {key}') from exc
            if not math.isfinite(value):
                raise RtLabelBuildError(f'Non-finite required RT metric {metric} for {key}')
        index[key] = row
    found_rx_ids = {key[1] for key in index}
    if len(index) != 2446 * 6 or found_rx_ids != set(rx_ids) or any(((frame, rx) not in index for frame in range(2446) for rx in rx_ids)):
        raise RtLabelBuildError('RT input is not a complete 2446-frame, six-RX table')
    output = []
    for source_frame in range(2436):
        split = 'train' if source_frame <= 1694 else 'excluded' if source_frame <= 1714 else 'test'
        for rx_id in rx_ids:
            (source, target) = (index[source_frame, rx_id], index[source_frame + 10, rx_id])
            (source_ts, target_ts) = (float(source['timestamp']), float(target['timestamp']))
            if abs(target_ts - source_ts - 1.0) > 1e-09:
                raise RtLabelBuildError(f'Timestamp horizon is not 1.0 seconds for frame={source_frame}, rx={rx_id}')
            delta_paths = int(target['num_paths']) - int(source['num_paths'])
            delta_delay = float(target['delay_spread']) - float(source['delay_spread'])
            delta_power = float(target['rx_power_dbm']) - float(source['rx_power_dbm'])
            labeled = {'source_frame_id': source_frame, 'target_frame_id': source_frame + 10, 'source_source_sample_index': int(source['source_sample_index']), 'target_source_sample_index': int(target['source_sample_index']), 'source_timestamp': source_ts, 'target_timestamp': target_ts, 'rx_id': rx_id, 'split': split}
            for (prefix, record) in (('source', source), ('target', target)):
                for (key, value) in record.items():
                    if key not in {'frame_id', 'source_sample_index', 'timestamp', 'rx_id'}:
                        labeled[f'{prefix}_{key}'] = value
            labeled.update({'delta_num_paths': delta_paths, 'delta_delay_spread': delta_delay, 'delta_rx_power_db': delta_power, 'y_path_change': int(delta_paths != 0), 'y_path_drop': int(delta_paths < 0), 'y_rx_power_drop_0p5db': int(delta_power < -0.5), 'y_rx_power_drop_1db': int(delta_power < -1.0), 'y_rx_power_drop_2db': int(delta_power < -2.0), 'y_delay_spread_increase': int(delta_delay > eta_tau)})
            labeled['y_adaptation_trigger_1db'] = int(labeled['y_rx_power_drop_1db'] or labeled['y_delay_spread_increase'])
            labeled['y_adaptation_trigger_2db'] = int(labeled['y_rx_power_drop_2db'] or labeled['y_delay_spread_increase'])
            output.append(labeled)
    if len(output) != 14616:
        raise RtLabelBuildError(f'Expected 14616 one-second rows, got {len(output)}')
    return output

def one_second_validation(rows: list[dict[str, Any]], eta_tau: float) -> dict[str, Any]:
    counts = {name: sum((row['split'] == name for row in rows)) for name in ('train', 'excluded', 'test')}
    if counts != {'train': 10170, 'excluded': 120, 'test': 4326}:
        raise RtLabelBuildError(f'Split counts incorrect: {counts}')
    if len(rows) != 14616 or len({(row['source_frame_id'], row['rx_id']) for row in rows}) != 14616:
        raise RtLabelBuildError('Labeled rows are not unique source-frame/RX pairs')
    for frame in range(2436):
        group = [row for row in rows if row['source_frame_id'] == frame]
        if [row['rx_id'] for row in group] != list(CANONICAL_RX_IDS):
            raise RtLabelBuildError(f'Frame {frame} lacks canonical RX ordering')
        for row in group:
            if row['target_frame_id'] != frame + 10 or abs(float(row['target_timestamp']) - float(row['source_timestamp']) - 1.0) > 1e-09:
                raise RtLabelBuildError(f'Invalid temporal pair at frame {frame}')
            for prefix in ('source', 'target'):
                for metric in ('num_paths', 'tau_min', 'tau_max', 'delay_spread', 'path_gain_sum', 'path_gain_db', 'rx_power_dbm'):
                    if not math.isfinite(float(row[f'{prefix}_{metric}'])):
                        raise RtLabelBuildError(f'Non-finite {prefix}_{metric}')
    return {'passed': True, 'temporal_horizon_frames': 10, 'temporal_horizon_seconds': 1.0, 'pairs': 2436, 'rows': 14616, 'evaluated_rows': 14496, 'split_rows': counts, 'required_labels': ['y_adaptation_trigger_1db', 'y_path_change'], 'unique_key': 'source_frame_id+rx_id', 'receiver_order': list(CANONICAL_RX_IDS), 'eta_tau': eta_tau, 'eta_tau_formula': '0.25 * population_std(delay_spread)', 'eta_tau_estimation_frames': [0, 1704], 'train_source_frames': [0, 1694], 'boundary_target_only_states': [1695, 1704], 'embargo_source_frames': [1705, 1714], 'test_source_frames': [1715, 2435]}

def main() -> int:
    args = parse_args()
    config_path = args.config.expanduser().resolve()
    if not config_path.exists():
        raise RtLabelBuildError(f'Config file does not exist: {config_path}')
    experiment = load_experiment_config(config_path)
    rt_results_dir = experiment['output_root'] / 'rt_results'
    input_csv = rt_results_dir / rt_batch_csv_name(experiment['num_frames'])
    labeled_csv = rt_results_dir / rt_labeled_csv_name(experiment['num_frames'])
    summary_csv = rt_results_dir / 'rt_label_summary.csv'
    rows = load_rt_rows(input_csv, allow_failed=args.allow_failed)
    if args.one_second_split or args.horizon_frames == 10:
        if args.horizon_frames != 10 or not args.one_second_split:
            raise RtLabelBuildError('Canonical 1-second labels require --horizon-frames 10 --one-second-split')
        eta_tau = compute_training_eta_tau(rows, args.eta_tau)
        labeled_rows = build_one_second_rows(rows, eta_tau, experiment['rx_ids'])
        validation = one_second_validation(labeled_rows, eta_tau)
        if args.validate_only:
            print(json.dumps(validation, sort_keys=True))
            return 0
        labeled_csv = rt_results_dir / 'rt_2446frames_multi_rx_horizon10_labeled.csv'
        split_json = rt_results_dir / 'rt_horizon10_split_manifest.json'
        prevalence_json = rt_results_dir / 'rt_horizon10_label_prevalence.json'
        structural_json = rt_results_dir / 'rt_horizon10_structural_validation.json'
        prevalence = {label: {split: {'rows': sum((row['split'] == split for row in labeled_rows)), 'positive': sum((int(row[label]) for row in labeled_rows if row['split'] == split))} for split in ('train', 'excluded', 'test')} for label in LABEL_COLUMNS}
        split_manifest = {'source_frame_ranges': {'train': [0, 1694], 'excluded': [1695, 1714], 'test': [1715, 2435]}, 'target_offset_frames': 10, 'rows': validation['split_rows'], 'evaluated_rows': 14496, 'eta_tau': eta_tau, 'eta_tau_formula': validation['eta_tau_formula'], 'eta_tau_estimation_frames': validation['eta_tau_estimation_frames']}
        write_atomic_csv(labeled_csv, labeled_rows)
        write_atomic_json(split_json, split_manifest)
        write_atomic_json(prevalence_json, prevalence)
        write_atomic_json(structural_json, validation)
        print(json.dumps({'result': 'PASS', 'labeled_csv': str(labeled_csv), 'validation': validation}, sort_keys=True))
        return 0
    if args.validate_only:
        raise RtLabelBuildError('--validate-only is supported for the canonical 1-second mode only')
    eta_tau = compute_eta_tau(rows, args.eta_tau)
    labeled_rows = build_labeled_rows(rows, eta_tau)
    expected_labeled = experiment['num_frames'] - 1
    rx_ids = sorted({row['rx_id'] for row in labeled_rows})
    expected_total = expected_labeled * len(rx_ids)
    if len(labeled_rows) != expected_total:
        raise RtLabelBuildError(f'Expected {expected_total} labeled rows ({expected_labeled} per RX), got {len(labeled_rows)}')
    write_labeled_csv(labeled_csv, labeled_rows)
    summary_rows = build_summary_rows(labeled_rows)
    write_summary_csv(summary_csv, summary_rows)
    print(f"experiment_name: {experiment['experiment_name']}")
    print(f'eta_tau: {eta_tau}')
    print(f'labeled_rows: {len(labeled_rows)}')
    print(f'labeled_csv: {labeled_csv}')
    print(f'summary_csv: {summary_csv}')
    print_balance(summary_rows)
    return 0
if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except RtLabelBuildError as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        raise SystemExit(1)
