#!/usr/bin/env python3
"""Create append-only per-RX median baseline artifacts from an existing full run.

This does not fit or rerun scene-based models and never edits their artifacts.
"""
from __future__ import annotations
import argparse, csv, json, math
from pathlib import Path
from collections import defaultdict
import numpy as np

TARGET='best_beam_received_power_dbm'; REPRESENTATIONS=('G','GS','GI','GSI'); TRAIN=range(0,1356); DEV=range(0,1695); VALIDATION=range(1356,1695); TEST=range(1715,2436)
def read_csv(path):
 with path.open(newline='') as h: return list(csv.DictReader(h))
def write_csv(path,fields,rows):
 with path.open('x',newline='') as h: w=csv.DictWriter(h,fieldnames=fields);w.writeheader();w.writerows(rows)
def metrics(rows):
 error=np.asarray([r['absolute_error'] for r in rows],float); squared=np.asarray([r['squared_error'] for r in rows],float)
 return {'mae':float(error.mean()),'rmse':float(np.sqrt(squared.mean())),'sample_count':len(rows)}
def main():
 p=argparse.ArgumentParser();p.add_argument('--experiment-root',type=Path,required=True);args=p.parse_args();run=args.experiment_root.resolve(); base=run/'results/best_beam_power_regression/full'; target_path=run/'beam_results/canonical_4x4_dft16/best_beam_received_power_targets.csv'
 outputs=[base/'per_rx_median_predictions.csv',base/'per_rx_median_rxwise_metrics.csv',base/'regression_results_with_per_rx_median.csv',base/'per_rx_median_summary.md']
 if any(x.exists() for x in outputs): raise RuntimeError('refusing to overwrite an existing per_rx_median artifact')
 rows=read_csv(target_path); keys=[(int(r['source_frame_id']),r['rx_id']) for r in rows]
 if len(keys)!=len(set(keys)): raise RuntimeError('duplicate target keys')
 if any(not math.isfinite(float(r[TARGET])) for r in rows): raise RuntimeError('non-finite target value')
 by_frame={int(r['source_frame_id']):[] for r in rows}
 for r in rows: by_frame[int(r['source_frame_id'])].append(r)
 for frame in (*VALIDATION,*TEST):
  if len(by_frame.get(frame,[]))!=6: raise RuntimeError(f'missing frame-RX pair at frame {frame}')
 rx=sorted({r['rx_id'] for r in rows}); fit={u:float(np.median([float(r[TARGET]) for r in rows if int(r['source_frame_id']) in TRAIN and r['rx_id']==u])) for u in rx}; dev={u:float(np.median([float(r[TARGET]) for r in rows if int(r['source_frame_id']) in DEV and r['rx_id']==u])) for u in rx}
 prediction=[]
 for split,frames,medians in (('validation',VALIDATION,fit),('test',TEST,dev)):
  for frame in frames:
   for r in by_frame[frame]:
    target=float(r[TARGET]); pred=medians[r['rx_id']]; err=target-pred; prediction.append({'source_frame_id':frame,'rx_id':r['rx_id'],'split':split,'target':target,'prediction':pred,'absolute_error':abs(err),'squared_error':err*err})
 if len([r for r in prediction if r['split']=='test'])!=4326 or len({r['source_frame_id'] for r in prediction if r['split']=='test'})!=721: raise RuntimeError('test partition count failure')
 for u in rx:
  if sum(r['split']=='test' and r['rx_id']==u for r in prediction)!=721: raise RuntimeError(f'test RX coverage failure: {u}')
 write_csv(outputs[0],['source_frame_id','rx_id','split','target','prediction','absolute_error','squared_error'],prediction)
 rxmetrics=[]
 for split,medians in (('validation',fit),('test',dev)):
  for u in rx: rxmetrics.append({'split':split,'rx_id':u,'sample_count':sum(r['split']==split and r['rx_id']==u for r in prediction),'median_fitted_value_dbm':medians[u],'mae_db':metrics([r for r in prediction if r['split']==split and r['rx_id']==u])['mae'],'rmse_db':metrics([r for r in prediction if r['split']==split and r['rx_id']==u])['rmse']})
 write_csv(outputs[1],['split','rx_id','sample_count','median_fitted_value_dbm','mae_db','rmse_db'],rxmetrics)
 existing=read_csv(base/'detailed_run_results.csv'); combined=[]
 for r in existing:
  va=json.loads(r['validation_metrics']); te=json.loads(r['aggregate_metrics']); combined.append({'representation':r['representation'],'method':r['model'],'validation_mae':va['mae'],'validation_rmse':va['rmse'],'test_mae':te['mae'],'test_rmse':te['rmse'],'sample_count':te['sample_count'],'measurement_aided':'true' if r['model']=='persistence' else 'false','scene_based':'true' if r['model'] in ('ridge','elastic_net','random_forest','rbf_svr') else 'false','notes':'existing final artifact'})
 va,te=metrics([r for r in prediction if r['split']=='validation']),metrics([r for r in prediction if r['split']=='test'])
 for rep in REPRESENTATIONS: combined.append({'representation':rep,'method':'per_rx_median','validation_mae':va['mae'],'validation_rmse':va['rmse'],'test_mae':te['mae'],'test_rmse':te['rmse'],'sample_count':te['sample_count'],'measurement_aided':'false','scene_based':'false','notes':'receiver-conditioned static baseline: RX identity only; no frame-dependent scene information or previous wireless measurement'})
 write_csv(outputs[2],['representation','method','validation_mae','validation_rmse','test_mae','test_rmse','sample_count','measurement_aided','scene_based','notes'],combined)
 mean=next(r for r in combined if r['representation']=='G' and r['method']=='per_rx_mean'); global_mean=next(r for r in combined if r['representation']=='G' and r['method']=='mean'); best={rep:min((r for r in combined if r['representation']==rep and r['scene_based']=='true'),key=lambda r:float(r['test_mae'])) for rep in REPRESENTATIONS}
 reduction=lambda baseline,model:100*(float(baseline)-float(model))/float(baseline)
 lines=['# Per-RX median baseline','','Target: `best_beam_received_power_dbm`, absolute simulated received power in dBm (not RSRP).','','## Leakage checks','', '- Validation medians use only frames 0--1355.', '- Test medians use only frames 0--1694; frames 1695--1714 are excluded.', '- No test target was used to estimate a median.', '- Test set: 4,326 rows, 721 frames, 721 rows per RX.','','## Receiver-conditioned medians (dBm)','', '| RX | fitting 0--1355 | development 0--1694 |','|---|---:|---:|']+[f'| {u} | {fit[u]:.9f} | {dev[u]:.9f} |' for u in rx]
 lines+=['','## Aggregate metrics','','| split | MAE (dB) | RMSE (dB) | samples |','|---|---:|---:|---:|',f"| validation | {va['mae']:.9f} | {va['rmse']:.9f} | {va['sample_count']} |",f"| test | {te['mae']:.9f} | {te['rmse']:.9f} | {te['sample_count']} |",'','## Per-RX metrics','','| split | RX | MAE (dB) | RMSE (dB) | samples |','|---|---|---:|---:|---:|']+[f"| {r['split']} | {r['rx_id']} | {float(r['mae_db']):.9f} | {float(r['rmse_db']):.9f} | {r['sample_count']} |" for r in rxmetrics]
 stronger='per_rx_median' if te['mae']<float(mean['test_mae']) else 'per_rx_mean'
 lines+=['','## Comparison','',f"Global mean test MAE: {float(global_mean['test_mae']):.9f} dB. Per-RX mean improves on it by {reduction(global_mean['test_mae'],mean['test_mae']):.3f}%; per-RX median improves on it by {reduction(global_mean['test_mae'],te['mae']):.3f}%.",f"Per-RX mean test MAE: {float(mean['test_mae']):.9f} dB. Per-RX median test MAE: {te['mae']:.9f} dB. Median relative to mean: {reduction(mean['test_mae'],te['mae']):.3f}%.",f"The stronger receiver-conditioned static baseline by test MAE is **{stronger}**. Persistence remains a separate previous-measurement-aided reference.",'','| representation | best scene-only method | test MAE | reduction vs per-RX mean | reduction vs per-RX median |','|---|---|---:|---:|---:|']+[f"| {rep} | {r['method']} | {float(r['test_mae']):.9f} | {reduction(mean['test_mae'],r['test_mae']):.3f}% | {reduction(te['mae'],r['test_mae']):.3f}% |" for rep,r in best.items()]
 lines+=['',f"Geometry-only G {'outperforms' if float(best['G']['test_mae'])<min(float(mean['test_mae']),te['mae']) else 'does not outperform'} the stronger static baseline. GS, GI, and GSI respectively {'outperform' if float(best['GS']['test_mae'])<min(float(mean['test_mae']),te['mae']) else 'do not outperform'}, {'outperform' if float(best['GI']['test_mae'])<min(float(mean['test_mae']),te['mae']) else 'do not outperform'}, and {'outperform' if float(best['GSI']['test_mae'])<min(float(mean['test_mae']),te['mae']) else 'do not outperform'} it.",f"Recommendation for the main paper: use **{stronger}** as the primary receiver-conditioned static baseline because it has lower test MAE; report the other alongside it for interpretability."]
 outputs[3].write_text('\n'.join(lines)+'\n'); print('\n'.join(str(x) for x in outputs))
if __name__=='__main__': main()
