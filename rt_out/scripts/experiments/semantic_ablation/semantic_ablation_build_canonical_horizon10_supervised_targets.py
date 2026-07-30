#!/usr/bin/env python3
"""Build and validate leakage-safe horizon-10 beam-management targets."""
from __future__ import annotations
import argparse, csv, hashlib, json, math, os
from collections import Counter
from pathlib import Path
from typing import Any
import numpy as np
RX = ('rx_panda_base', 'rx_ur5_base', 'rx_cerberus_base', 'rx_nao_chest', 'rx_human_chest', 'rx_x500_body')
(N_SOURCE, HORIZON) = (2436, 10)
SPLITS = {'train': 10170, 'excluded': 120, 'test': 4326}
BEAM_BINARY = ('beam_switch_1s', 'beam_reselection_05db_1s', 'beam_reselection_1db_1s', 'beam_reselection_3db_1s')
BEAM_FIELDS = ('source_frame_id', 'target_frame_id', 'source_timestamp', 'target_timestamp', 'rx_id', 'split', 'current_optimal_beam', 'future_optimal_beam_1s', 'beam_switch_1s', 'current_beam_in_future_top3', 'current_beam_power_at_future_dbm', 'future_oracle_beam_power_dbm', 'stale_beam_loss_db_1s', 'future_beam_margin_db', 'beam_reselection_05db_1s', 'beam_reselection_1db_1s', 'beam_reselection_3db_1s')
TARGET_FIELDS = ('source_frame_id', 'target_frame_id', 'source_timestamp', 'target_timestamp', 'rx_id', 'split', 'y_path_change', 'y_adaptation_trigger_1db', 'future_optimal_beam_1s', 'beam_switch_1s', 'beam_reselection_05db_1s', 'beam_reselection_1db_1s', 'beam_reselection_3db_1s', 'stale_beam_loss_db_1s', 'future_beam_margin_db')
EXPECTED_RT = {'y_adaptation_trigger_1db': {'train': {0: 9694, 1: 476}, 'excluded': {0: 111, 1: 9}, 'test': {0: 4201, 1: 125}}, 'y_path_change': {'train': {0: 6589, 1: 3581}, 'excluded': {0: 56, 1: 64}, 'test': {0: 3202, 1: 1124}}}

class Error(RuntimeError):
    pass

def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise Error(f'missing input: {path}')
    with path.open(newline='') as h:
        return list(csv.DictReader(h))

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def atomic_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    tmp = path.with_suffix(path.suffix + '.tmp')
    with tmp.open('w', newline='') as h:
        w = csv.DictWriter(h, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)

def atomic_json(path: Path, value: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    os.replace(tmp, path)

def counts(rows: list[dict[str, Any]], field: str, by: str | None=None) -> dict[str, Any]:
    groups = ['global'] if by is None else list(SPLITS) if by == 'split' else list(RX)
    return {g: {str(k): int(v) for (k, v) in sorted(Counter((int(r[field]) for r in rows if by is None or r[by] == g)).items())} for g in groups}

def stats(values: np.ndarray) -> dict[str, float]:
    return {k: float(v) for (k, v) in zip(('min', 'mean', 'median', 'p90', 'p95', 'p99', 'max'), (values.min(), values.mean(), np.median(values), np.quantile(values, 0.9), np.quantile(values, 0.95), np.quantile(values, 0.99), values.max()), strict=True)}

def binary_column(rows: list[dict[str, Any]], field: str) -> np.ndarray:
    """Parse CSV binary text explicitly; never rely on Python string truthiness."""
    try:
        values = np.asarray([int(r[field]) for r in rows], dtype=np.int8)
    except (KeyError, TypeError, ValueError) as exc:
        raise Error(f'invalid binary column {field}') from exc
    if not np.isin(values, (0, 1)).all():
        raise Error(f'non-binary values in {field}')
    return values

def paths(root: Path) -> dict[str, Path]:
    exp = root / 'rt_out/experiments/semantic_ablation_actor_2446f_10hz/run_20260710_172015'
    beam = exp / 'beam_results/canonical_4x4_dft16'
    return {'beam': beam, 'scores': beam / 'beam_scores.csv', 'powers': beam / 'beam_powers.npy', 'rt': exp / 'rt_results/rt_2446frames_multi_rx_horizon10_labeled.csv', 'paired': exp / 'features/segmentation_ablation_voxels/voxel_0.04m/paired_index.csv', 'labels': beam / 'beam_labels_horizon10.csv', 'targets': beam / 'supervised_targets_horizon10.csv', 'summary': beam / 'beam_label_validation_summary.json', 'manifest': beam / 'supervised_target_manifest.json'}

def expected(p: dict[str, Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    (paired, rt, scores) = (read_csv(p['paired']), read_csv(p['rt']), read_csv(p['scores']))
    powers = np.load(p['powers'], mmap_mode='r')
    canonical = [(str(f), rx) for f in range(N_SOURCE) for rx in RX]
    if [(r.get('source_frame_id'), r.get('rx_id')) for r in paired] != canonical:
        raise Error('paired_index is not canonical source-frame/RX order')
    if [(r.get('source_frame_id'), r.get('rx_id')) for r in rt] != canonical:
        raise Error('RT labels are not canonical source-frame/RX order')
    if [(r.get('frame_id'), r.get('rx_id')) for r in scores] != [(str(f), rx) for f in range(2446) for rx in RX]:
        raise Error('beam_scores is not canonical frame/RX order')
    if tuple(powers.shape) != (2446, 6, 16) or not np.isfinite(powers).all():
        raise Error('beam_powers must be finite 2446x6x16')
    if Counter((r['split'] for r in paired)) != SPLITS or any(((r['split'], r['y_path_change'], r['y_adaptation_trigger_1db']) != (q['split'], q['y_path_change'], q['y_adaptation_trigger_1db']) for (r, q) in zip(paired, rt, strict=True))):
        raise Error('paired_index and immutable RT labels disagree')
    rt_counts = {label: {split: dict(Counter((int(r[label]) for r in rt if r['split'] == split))) for split in SPLITS} for label in EXPECTED_RT}
    if rt_counts != EXPECTED_RT:
        raise Error(f'immutable RT label counts changed: {rt_counts}')
    (beam_rows, target_rows) = ([], [])
    for f in range(N_SOURCE):
        for (ri, rx) in enumerate(RX):
            (source, target) = (powers[f, ri], powers[f + HORIZON, ri])
            (current, future) = (int(np.argmax(source)), int(np.argmax(target)))
            order = np.argsort(-target, kind='stable')
            stale = float(target[future] - target[current])
            if stale < -1e-09:
                raise Error('negative stale-beam loss')
            stale = max(0.0, stale)
            (rtrow, score_source, score_target) = (rt[f * 6 + ri], scores[f * 6 + ri], scores[(f + HORIZON) * 6 + ri])
            if float(rtrow['source_timestamp']) != float(score_source['timestamp']) or float(rtrow['target_timestamp']) != float(score_target['timestamp']):
                raise Error('RT/beam timestamp mismatch')
            row = {'source_frame_id': f, 'target_frame_id': f + HORIZON, 'source_timestamp': float(score_source['timestamp']), 'target_timestamp': float(score_target['timestamp']), 'rx_id': rx, 'split': rtrow['split'], 'current_optimal_beam': current, 'future_optimal_beam_1s': future, 'beam_switch_1s': int(current != future), 'current_beam_in_future_top3': int(current in order[:3]), 'current_beam_power_at_future_dbm': float(target[current]), 'future_oracle_beam_power_dbm': float(target[future]), 'stale_beam_loss_db_1s': stale, 'future_beam_margin_db': float(target[order[0]] - target[order[1]]), 'beam_reselection_05db_1s': int(stale >= 0.5), 'beam_reselection_1db_1s': int(stale >= 1.0), 'beam_reselection_3db_1s': int(stale >= 3.0)}
            beam_rows.append(row)
            target_rows.append({k: row[k] if k in row else int(rtrow[k]) for k in TARGET_FIELDS})
    return (beam_rows, target_rows, {'rt_label_counts': rt_counts})

def audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    binary = {field: binary_column(rows, field) for field in BEAM_BINARY}
    stale = np.asarray([r['stale_beam_loss_db_1s'] for r in rows], float)
    margin = np.asarray([r['future_beam_margin_db'] for r in rows], float)
    switch = binary['beam_switch_1s']
    if not np.isfinite(stale).all() or not np.isfinite(margin).all():
        raise Error('non-finite audit values')
    for field in BEAM_BINARY[1:]:
        if np.any((binary[field] == 1) & (switch != 1)):
            raise Error(f'{field} positive without a beam switch')
    switch_count = int(np.count_nonzero(switch))
    if switch_count == 0:
        raise Error('unexpectedly zero beam switches')
    train = [r for r in rows if r['split'] == 'train']
    future_majority = Counter((r['future_optimal_beam_1s'] for r in train)).most_common(1)[0][0]
    rx_majority = {rx: Counter((r['future_optimal_beam_1s'] for r in train if r['rx_id'] == rx)).most_common(1)[0][0] for rx in RX}
    total = len(rows)
    always_no = {field: {'correct_count': int(np.count_nonzero(values == 0)), 'total': total, 'accuracy': float(np.count_nonzero(values == 0) / total)} for (field, values) in binary.items()}
    thresholds = {str(t): {'count': int(np.count_nonzero((switch == 1) & (stale < t))), 'switch_count': switch_count, 'fraction': float(np.count_nonzero((switch == 1) & (stale < t)) / switch_count)} for t in (0.5, 1.0, 3.0)}
    baselines = {'future_beam_persistence_accuracy': float(np.mean([r['current_optimal_beam'] == r['future_optimal_beam_1s'] for r in rows])), 'global_train_majority_future_beam': {'beam': future_majority, 'accuracy': float(np.mean([r['future_optimal_beam_1s'] == future_majority for r in rows]))}, 'train_only_per_rx_majority_future_beam': {'beams': rx_majority, 'accuracy': float(np.mean([r['future_optimal_beam_1s'] == rx_majority[r['rx_id']] for r in rows]))}, 'always_no_reselection': always_no}
    return {'beam_binary_class_counts': {x: {'global': counts(rows, x), 'by_split': counts(rows, x, 'split'), 'by_rx': counts(rows, x, 'rx_id')} for x in BEAM_BINARY}, 'future_beam_class_counts': {'global': counts(rows, 'future_optimal_beam_1s'), 'by_split': counts(rows, 'future_optimal_beam_1s', 'split'), 'by_rx': counts(rows, 'future_optimal_beam_1s', 'rx_id')}, 'beam_switch_count': switch_count, 'reselection_positive_counts': {field: int(np.count_nonzero(binary[field])) for field in BEAM_BINARY[1:]}, 'stale_loss_db': stats(stale), 'beam_switch_stale_loss_below_db': thresholds, 'future_margin_near_tie_counts': {str(t): int(np.count_nonzero(margin < t)) for t in (0.1, 0.5, 1.0)}, 'baselines': baselines}

def validate(p: dict[str, Path], beam_expected: list[dict[str, Any]], target_expected: list[dict[str, Any]], extra: dict[str, Any]) -> dict[str, Any]:
    (beam, targets) = (read_csv(p['labels']), read_csv(p['targets']))
    if list(beam[0]) != list(BEAM_FIELDS) or list(targets[0]) != list(TARGET_FIELDS):
        raise Error('generated CSV schema mismatch')
    if len(beam) != 14616 or len(targets) != 14616:
        raise Error('generated row count is not 14616')
    for (actual, wanted) in ((beam, beam_expected), (targets, target_expected)):
        for (a, b) in zip(actual, wanted, strict=True):
            for (k, v) in b.items():
                if k in ('source_timestamp', 'target_timestamp', 'current_beam_power_at_future_dbm', 'future_oracle_beam_power_dbm', 'stale_beam_loss_db_1s', 'future_beam_margin_db'):
                    if not math.isclose(float(a[k]), float(v), abs_tol=1e-09):
                        raise Error(f'numeric mismatch {k}')
                elif str(a[k]) != str(v):
                    raise Error(f'mismatch {k}')
    report = {'passed': True, 'rows': 14616, 'split_rows': dict(Counter((r['split'] for r in beam))), 'source_frame_range': [0, 2435], 'target_offset_frames': 10, 'receiver_order': list(RX), 'validation': {'canonical_order': True, 'target_frame_id_equals_source_plus_10': True, 'future_optimal_beam_equals_target_argmax': True, 'stale_loss_finite_nonnegative': True, 'beam_binary_formulas': True, 'immutable_rt_labels_copied_validated': True}, **extra, **audit(beam)}
    if report['split_rows'] != SPLITS:
        raise Error('generated split counts mismatch')
    return report

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', type=Path, default=Path.cwd())
    modes = ap.add_mutually_exclusive_group()
    modes.add_argument('--validate-only', action='store_true')
    modes.add_argument('--refresh-audit', action='store_true')
    a = ap.parse_args()
    p = paths(a.root.resolve())
    (beam, targets, extra) = expected(p)
    if a.validate_only:
        report = validate(p, beam, targets, extra)
        print(json.dumps({'result': 'PASS', 'rows': report['rows'], 'split_rows': report['split_rows']}, sort_keys=True))
        return
    if a.refresh_audit:
        if not p['summary'].is_file() or not p['manifest'].is_file():
            raise Error('--refresh-audit requires existing summary and manifest')
        report = validate(p, beam, targets, extra)
        atomic_json(p['summary'], report)
        try:
            manifest = json.loads(p['manifest'].read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise Error('invalid existing supervised target manifest') from exc
        manifest.setdefault('outputs', {})['summary'] = sha(p['summary'])
        atomic_json(p['manifest'], manifest)
        print(json.dumps({'result': 'PASS', 'beam_switch_count': report['beam_switch_count'], 'reselection_positive_counts': report['reselection_positive_counts'], 'summary': str(p['summary'])}, sort_keys=True))
        return
    if any((p[x].exists() for x in ('labels', 'targets', 'summary', 'manifest'))):
        raise Error('refusing to overwrite generated target artifacts')
    atomic_csv(p['labels'], BEAM_FIELDS, beam)
    atomic_csv(p['targets'], TARGET_FIELDS, targets)
    report = validate(p, beam, targets, extra)
    atomic_json(p['summary'], report)
    atomic_json(p['manifest'], {'passed': True, 'generator': Path(__file__).name, 'horizon_frames': 10, 'source_frames': [0, 2435], 'rows': 14616, 'split_rows': SPLITS, 'beam_label_schema': list(BEAM_FIELDS), 'supervised_target_schema': list(TARGET_FIELDS), 'inputs': {k: sha(p[k]) for k in ('scores', 'powers', 'rt', 'paired')}, 'outputs': {k: sha(p[k]) for k in ('labels', 'targets', 'summary')}, 'model_feature_policy': 'Targets are labels only; voxel loader uses source-frame sparse scene tensors and static link context only.'})
    print(json.dumps({'result': 'PASS', 'beam_labels': str(p['labels']), 'supervised_targets': str(p['targets']), 'rows': 14616, 'split_rows': SPLITS}, sort_keys=True))
if __name__ == '__main__':
    try:
        main()
    except Error as e:
        raise SystemExit(f'ERROR: {e}')
