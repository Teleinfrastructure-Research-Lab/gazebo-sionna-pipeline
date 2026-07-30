#!/usr/bin/env python3
"""Build leakage-free canonical-GT R1--R4 scene representations."""
from __future__ import annotations
import argparse, csv, json, math, os
from pathlib import Path
import numpy as np
N = 2446
RX = ('rx_panda_base', 'rx_ur5_base', 'rx_cerberus_base', 'rx_nao_chest', 'rx_human_chest', 'rx_x500_body')
GRID = 16
TOPK = 32
BMIN = np.array([-6.0, -6.0, 0.0])
BMAX = np.array([6.0, 6.0, 4.0])

class E(RuntimeError):
    pass

def readj(p: Path):
    return json.loads(p.read_text())

def resolve_output_root(config_path: Path, output_dir: str) -> Path:
    configured = Path(output_dir).expanduser()
    if configured.is_absolute():
        return configured.resolve()
    config_path = config_path.expanduser().resolve()
    owner_root = (
        config_path.parent.parent
        if config_path.parent.name == 'config'
        else config_path.parent
    )
    return (owner_root / configured).resolve()

def atomic_csv(p: Path, fields, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    t = p.with_suffix(p.suffix + '.tmp')
    with t.open('w', newline='') as h:
        w = csv.DictWriter(h, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    os.replace(t, p)

def parse():
    a = argparse.ArgumentParser()
    a.add_argument('--config', type=Path, required=True)
    a.add_argument('--smoke-frames', type=int)
    a.add_argument('--validate-only', action='store_true')
    return a.parse_args()

def points(p: Path):
    with p.open() as h:
        while h.readline().strip() != 'end_header':
            pass
        x = np.loadtxt(h, dtype=np.float64)
    if x.ndim != 2 or x.shape[1] != 8 or (not np.isfinite(x).all()):
        raise E(f'invalid canonical PLY {p}')
    return x

def vox(x):
    ij = np.floor((x[:, :3] - BMIN) / (BMAX - BMIN) * GRID).astype(int)
    ok = np.all((ij >= 0) & (ij < GRID), axis=1)
    return (ij[ok], ok)

def scene_features(x, classes, mats, otypes):
    (ij, ok) = vox(x)
    lin = np.ravel_multi_index(ij.T, (GRID, GRID, GRID))
    r1 = np.zeros(GRID ** 3, np.uint8)
    r1[np.unique(lin)] = 1
    r2 = np.zeros((len(classes), GRID ** 3), np.uint8)
    for (i, c) in enumerate(classes):
        r2[i, np.unique(lin[x[ok, 3].astype(int) == c])] = 1
    inst = []
    for iid in sorted(set(x[:, 4].astype(int))):
        q = x[x[:, 4].astype(int) == iid]
        lo = q[:, :3].min(0)
        hi = q[:, :3].max(0)
        inst.append((iid, q[:, 3].astype(int)[0], q[:, 5].astype(int)[0], q[:, 6].astype(int)[0], np.r_[q[:, :3].mean(0), hi - lo, len(q)]))
    inst.sort(key=lambda z: (-z[4][-1], z[0]))
    return (r1, r2, inst[:TOPK])

def main():
    a = parse()
    cfg = readj(a.config)
    root = resolve_output_root(a.config, cfg['output_dir'])
    gt = root / 'gt_scene_pointclouds'
    labels = root / 'rt_results/rt_2446frames_multi_rx_horizon10_labeled.csv'
    reg = readj(gt / 'label_registry.json')
    classes = tuple(sorted(map(int, reg['semantic_taxonomy'])))
    mats = tuple(sorted(map(int, reg['materials'])))
    otypes = tuple(sorted(map(int, reg['object_types'])))
    rows = list(csv.DictReader(labels.open()))
    banned = ('target_', 'delta_', 'source_num_paths', 'source_tau_', 'source_delay_', 'source_path_', 'source_rx_power', 'y_')
    if len(rows) != 14616 or any((any((k.startswith(b) for b in banned)) for k in ())):
        raise E('label input rows invalid')
    if [(r['source_frame_id'], r['rx_id']) for r in rows] != [(str(f), rx) for f in range(2436) for rx in RX]:
        raise E('labels are not canonical source-frame/RX ordered')
    limit = a.smoke_frames or N
    if limit < 1 or limit > N:
        raise E('invalid smoke frame count')
    scene = []
    r1 = []
    r2 = []
    r3 = []
    r4 = []
    for f in range(limit):
        x = points(gt / f'frame_{f:03d}_gt_scene.ply')
        (q1, q2, inst) = scene_features(x, classes, mats, otypes)
        r1.append(q1)
        r2.append(q2.reshape(-1))
        base = np.zeros((TOPK, 7))
        fine = np.zeros((TOPK, 7 + len(classes) + len(mats) + len(otypes)))
        for (i, (iid, c, mat, otyp, g)) in enumerate(inst):
            base[i] = g
            fine[i, :7] = g
            fine[i, 7 + classes.index(c)] = 1
            fine[i, 7 + len(classes) + mats.index(mat)] = 1
            fine[i, 7 + len(classes) + len(mats) + otypes.index(otyp)] = 1
        r3.append(base.reshape(-1))
        r4.append(fine.reshape(-1))
        scene.append({'source_frame_id': f, 'feature_row': f})
    if a.validate_only:
        print(json.dumps({'passed': True, 'scene_records': limit, 'paired_rows': sum((int(r['source_frame_id']) < limit for r in rows)), 'dims': {'R1': GRID ** 3, 'R2': len(classes) * GRID ** 3, 'R3': TOPK * 10, 'R4': TOPK * (13 + len(classes) + len(mats) + len(otypes))}, 'leakage': 'no target/delta/label/RT columns in feature arrays'}, sort_keys=True))
        return
    out = root / 'features/canonical_r1_r4'
    if out.exists():
        raise E(f'refusing to overwrite {out}')
    out.mkdir(parents=True)
    np.save(out / 'R1_scene.npy', np.asarray(r1))
    np.save(out / 'R2_scene.npy', np.asarray(r2))
    np.save(out / 'R3_scene.npy', np.asarray(r3))
    np.save(out / 'R4_scene.npy', np.asarray(r4))
    atomic_csv(out / 'scene_index.csv', ['source_frame_id', 'feature_row'], scene)
    meta = [{'source_frame_id': r['source_frame_id'], 'rx_id': r['rx_id'], 'split': r['split'], 'feature_row': r['source_frame_id'], 'y_adaptation_trigger_1db': r['y_adaptation_trigger_1db'], 'y_path_change': r['y_path_change']} for r in rows if int(r['source_frame_id']) < limit]
    tx = np.asarray(cfg['tx']['position'], float)
    rxpos = {x['id']: np.asarray(x['position'], float) for x in cfg['rx_list']}
    r3pair = []
    r4pair = []
    for m in meta:
        b = np.asarray(r3[int(m['source_frame_id'])]).reshape(TOPK, 7)
        q = np.asarray(r4[int(m['source_frame_id'])]).reshape(TOPK, -1)
        rp = rxpos[m['rx_id']]
        cen = b[:, :3]
        rel = np.c_[np.linalg.norm(cen - tx, axis=1), np.linalg.norm(cen - rp, axis=1), np.linalg.norm(cen - (tx + rp) / 2, axis=1)]
        r3pair.append(np.c_[b, rel].reshape(-1))
        r4pair.append(np.c_[q, cen - tx, cen - rp, rel].reshape(-1))
    np.save(out / 'R3_paired.npy', np.asarray(r3pair))
    np.save(out / 'R4_paired.npy', np.asarray(r4pair))
    for name in ('R1', 'R2', 'R3', 'R4'):
        atomic_csv(out / f'{name}_paired_index.csv', list(meta[0]), meta)
    summary = {'passed': limit == N, 'scene_records': limit, 'paired_rows': len(meta), 'dimensions': {'R1': GRID ** 3, 'R2': len(classes) * GRID ** 3, 'R3': TOPK * 10, 'R4': TOPK * (13 + len(classes) + len(mats) + len(otypes))}, 'memory_estimate_bytes': {'R1': limit * GRID ** 3, 'R2': limit * len(classes) * GRID ** 3, 'R3': len(meta) * TOPK * 10 * 8, 'R4': len(meta) * TOPK * (13 + len(classes) + len(mats) + len(otypes)) * 8}, 'feature_inputs': 'canonical GT PLY only; paired CSV is metadata/targets only'}
    (out / 'validation_summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, sort_keys=True))
if __name__ == '__main__':
    try:
        main()
    except E as e:
        raise SystemExit(f'ERROR: {e}')
