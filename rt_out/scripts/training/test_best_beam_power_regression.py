import csv, json, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).parent))
import best_beam_power_regression as b
import run_best_beam_power_regression as runner

class BestBeamRegressionTests(unittest.TestCase):
 def make_run(self):
  temp=tempfile.TemporaryDirectory(); run=Path(temp.name)/'run'; root=run/'beam_results/canonical_4x4_dft16'; root.mkdir(parents=True); (root/'beam_experiment_manifest.json').write_text(json.dumps({'tx_power_dbm':30}))
  fields=['frame_id','timestamp','rx_id','received_powers_dbm','optimal_beam','best_power_dbm']; rows=[]; index=[]
  for frame in range(8):
   split='train' if frame < 4 else ('excluded' if frame == 4 else 'test')
   for rx_i,rx in enumerate(('a','b')):
    power=[-50.,-40.+frame+rx_i,-60.,-70.] + [-80.]*12; rows.append({'frame_id':frame,'timestamp':frame*.1,'rx_id':rx,'received_powers_dbm':json.dumps(power),'optimal_beam':1,'best_power_dbm':power[1]}); index.append({'row_index':len(index),'source_frame_id':frame,'rx_id':rx,'split':split})
  with (root/'beam_scores.csv').open('w',newline='') as h: w=csv.DictWriter(h,fieldnames=fields);w.writeheader();w.writerows(rows)
  d=run/'features/classical_ml_descriptor_v2'; d.mkdir(parents=True); b._write_csv(d/'row_index.csv',['row_index','source_frame_id','rx_id','split'],index); np.save(d/'G.npy',np.asarray([[r['source_frame_id'],i%2] for i,r in enumerate(index)],np.float32)); np.save(d/'GS.npy',np.ones((len(index),3),np.float32)); np.save(d/'GI.npy',np.ones((len(index),4),np.float32)); np.save(d/'GSI.npy',np.ones((len(index),5),np.float32))
  return temp,run
 def make_completed_smoke(self):
  temp,run=self.make_run(); b.build_targets(run); command=[sys.executable,str(Path(__file__).with_name('run_best_beam_power_regression.py')),'--experiment-root',str(run),'--smoke','--representation','G','--model','ridge']; completed=subprocess.run(command,capture_output=True,text=True); self.assertEqual(completed.returncode,0,completed.stderr); return temp,run,run/'results/best_beam_power_regression/smoke'
 def make_completed_full_fixture(self):
  temp,run,smoke=self.make_completed_smoke(); full=run/'results/best_beam_power_regression/full'; full.mkdir(parents=True); modelout=run/'models/best_beam_power_regression/full'; reportout=run/'reports/best_beam_power_regression/full'; modelout.mkdir(parents=True); reportout.mkdir(parents=True)
  arrays,aligned,alignment=b.load_aligned(run,['G','GS','GI','GSI']); runner._write_json(full/'target_alignment_report.json',alignment); runner._write_json(full/'resolved_split.json',runner.temporal_metadata(aligned))
  source_summary=json.loads((smoke/'validation_summary.json').read_text()); source_item=source_summary['runs'][0]; source_detail=b._read_csv(smoke/'detailed_run_results.csv')[0]; source_predictions=b._read_csv(smoke/'held_out_predictions.csv'); items=[]; details=[]; predictions=[]; representations=('G','GS','GI','GSI')
  for representation in representations:
   for model in runner.MODELS:
    item=json.loads(json.dumps(source_item)); item.update({'representation':representation,'model':model}); items.append(item)
    detail=dict(source_detail); detail.update({'representation':representation,'model':model}); details.append(detail)
    predictions.extend([{**row,'representation':representation,'model':model} for row in source_predictions])
    if model not in ('mean','per_rx_mean','persistence'):
     shutil.copyfile(run/'models/best_beam_power_regression/smoke/G_ridge.pkl',modelout/f'{representation}_{model}.pkl')
  jobs=[(representation,model) for representation in representations for model in runner.MODELS]; input_hashes=runner.regression_input_hashes(run,representations); source_hashes=runner._source_fingerprints(); dependencies=runner.regression_dependency_versions(); runner._write_json(full/'experiment_manifest.json',runner.canonical_manifest_for(run,'full',jobs,input_hashes,42)); canonical_hash=runner.stable_source_hash(full/'experiment_manifest.json'); invocation=runner.invocation_manifest_payload(invocation_id='full-fixture',requested_jobs=jobs,normalized_cli_args={},execution_source_hashes=source_hashes,dependency_versions=dependencies,command_mode='full',canonical_manifest_sha256=canonical_hash,input_hashes=input_hashes,timestamp_utc='2026-01-01T00:00:00+00:00',status='completed',completed_jobs=jobs); runner.write_invocation_manifest(full/'invocations',invocation); [item.update(runner.binding_metadata('full-fixture','full',(item['representation'],item['model']),'generated',invocation['timestamp_utc'],canonical_hash,input_hashes,source_hashes,dependencies)) for item in items]
  runner._write_json(full/'validation_summary.json',{'passed':True,'mode':'full','selection_metric':'validation_mae','runs':items})
  detail_fields=list(source_detail); runner._write_csv(full/'detailed_run_results.csv',detail_fields,details); runner._write_csv(full/'held_out_predictions.csv',list(source_predictions[0]),predictions)
  shutil.copyfile(run/'reports/best_beam_power_regression/smoke/best_beam_power_regression_report.json',reportout/'best_beam_power_regression_report.json')
  runner._write_json(full/'provenance_manifest.json',runner.provenance(run,input_hashes,{'mode':'full','jobs':runner.job_inventory(jobs)},42,runner.binding_metadata('full-fixture','full',('best_beam_power_regression','full'),'generated',invocation['timestamp_utc'],canonical_hash,input_hashes,source_hashes,dependencies))); runner.write_artifact_manifest(run,'full')
  return temp,run,full
 def test_derivation_and_unit(self):
  temp,run=self.make_run(); self.addCleanup(temp.cleanup); path,report=b.build_targets(run); self.assertEqual(report['target_unit'],'dBm'); self.assertEqual(b._read_csv(path)[0]['best_beam_index'],'1')
 def test_duplicate_rejected(self):
  temp,run=self.make_run(); self.addCleanup(temp.cleanup); p=run/'beam_results/canonical_4x4_dft16/beam_scores.csv'; rows=b._read_csv(p); rows.append(rows[0]); b._write_csv(p,list(rows[0]),rows)
  with self.assertRaises(b.RegressionInputError): b.build_targets(run)
 def test_incomplete_and_nonfinite_rejected(self):
  temp,run=self.make_run(); self.addCleanup(temp.cleanup); p=run/'beam_results/canonical_4x4_dft16/beam_scores.csv'; rows=b._read_csv(p); rows[0]['received_powers_dbm']='[-1]'; b._write_csv(p,list(rows[0]),rows)
  with self.assertRaises(b.RegressionInputError): b.build_targets(run)
 def test_alignment_includes_index_metadata(self):
  temp,run=self.make_run(); self.addCleanup(temp.cleanup); b.build_targets(run); arrays,rows,report=b.load_aligned(run,['G','GS']); self.assertEqual(report['aligned_rows'],16); self.assertEqual(arrays['G'].shape,(16,2)); self.assertEqual(rows[3]['row_index'],'3'); self.assertEqual(rows[3]['split'],'train'); self.assertEqual(rows[3]['source_frame_id'],'1')
 def test_metrics_contract(self): self.assertEqual(b.regression_metrics(np.array([1.,2.]),np.array([1.,2.]))['mae'],0.)
 def test_per_rx_mean_uses_fitting_rows_only(self):
  rows=[{'source_frame_id':'0','rx_id':'a'},{'source_frame_id':'0','rx_id':'b'},{'source_frame_id':'1','rx_id':'a'},{'source_frame_id':'1','rx_id':'b'}]; y=np.asarray([1.,10.,999.,999.]); self.assertTrue(np.array_equal(runner.baseline_prediction('per_rx_mean',rows,y,np.asarray([2,3]),np.asarray([0,1])),np.asarray([1.,10.])))
 def test_end_to_end_synthetic_smoke_cli(self):
  temp,run=self.make_run(); self.addCleanup(temp.cleanup); b.build_targets(run); runner=Path(__file__).with_name('run_best_beam_power_regression.py')
  completed=subprocess.run([sys.executable,str(runner),'--experiment-root',str(run),'--smoke','--representation','G','--model','ridge'],capture_output=True,text=True); self.assertEqual(completed.returncode,0,completed.stderr)
  self.assertIn('"passed": true',completed.stdout); out=run/'results/best_beam_power_regression/smoke'; self.assertTrue((out/'held_out_predictions.csv').is_file()); self.assertTrue((out/'validation_summary.json').is_file()); prediction=b._read_csv(out/'held_out_predictions.csv'); self.assertTrue(prediction); self.assertEqual(len(prediction),6); self.assertEqual({(r['source_frame_id'],r['rx_id']) for r in prediction},{('5','a'),('5','b'),('6','a'),('6','b'),('7','a'),('7','b')})
 def test_convergence_metadata_svr_and_force_cleanup(self):
  temp,run=self.make_run(); self.addCleanup(temp.cleanup); b.build_targets(run); command=[sys.executable,str(Path(__file__).with_name('run_best_beam_power_regression.py')),'--experiment-root',str(run),'--smoke','--representation','G','--model','rbf_svr']; self.assertEqual(subprocess.run(command,capture_output=True,text=True).returncode,0); out=run/'results/best_beam_power_regression/smoke'; meta=json.loads((out/'validation_summary.json').read_text())['runs'][0]['convergence']; self.assertTrue(meta['converged']); self.assertIn('fit_status',meta); (out/'stale').write_text('remove me'); self.assertEqual(subprocess.run(command+['--force'],capture_output=True,text=True).returncode,0); self.assertFalse((out/'stale').exists())
 def test_full_inventory_missing_is_rejected(self):
  temp,run=self.make_run(); self.addCleanup(temp.cleanup); base=run/'results/best_beam_power_regression/full'; base.mkdir(parents=True); [path.write_text('{}') for path in (base/'validation_summary.json',base/'resolved_split.json',base/'target_alignment_report.json')]; b._write_csv(base/'detailed_run_results.csv',['x'],[]); b._write_csv(base/'held_out_predictions.csv',['x'],[])
  with self.assertRaises(b.RegressionInputError): runner.validate_result_tree(base,'full')
 def test_full_28_job_provenance_passes(self):
  temp,run,full=self.make_completed_full_fixture(); self.addCleanup(temp.cleanup); report=runner.validate_result_tree(full,'full'); self.assertTrue(report['release_validation_passed']); self.assertEqual(report['provenance_status'],'exact_match'); self.assertEqual(report['runs'],28)
 def test_generated_result_has_append_only_invocation_binding(self):
  temp,run,out=self.make_completed_smoke(); self.addCleanup(temp.cleanup); item=json.loads((out/'validation_summary.json').read_text())['runs'][0]; self.assertTrue(item['invocation_id']); self.assertEqual(item['job_identity'],['G','ridge']); self.assertEqual(item['execution_status'],'generated'); self.assertTrue(item['created_at_utc']); self.assertEqual(item['canonical_manifest_sha256'],runner.stable_source_hash(out/'experiment_manifest.json')); invocation=json.loads((out/item['invocation_manifest']).read_text()); self.assertEqual(invocation['status'],'completed'); self.assertEqual(invocation['requested_jobs'],[['G','ridge']]); self.assertEqual(invocation['completed_jobs'],[['G','ridge']]); self.assertEqual(invocation['resumed_jobs'],[]); self.assertEqual(item['created_at_utc'],invocation['timestamp_utc'])
 def test_resumed_result_uses_new_completed_invocation(self):
  temp,run,out=self.make_completed_smoke(); self.addCleanup(temp.cleanup); original=json.loads((out/'validation_summary.json').read_text())['runs'][0]['invocation_id']; command=[sys.executable,str(Path(__file__).with_name('run_best_beam_power_regression.py')),'--experiment-root',str(run),'--smoke','--representation','G','--model','ridge']; completed=subprocess.run(command,capture_output=True,text=True); self.assertEqual(completed.returncode,0,completed.stderr); item=json.loads((out/'validation_summary.json').read_text())['runs'][0]; self.assertNotEqual(item['invocation_id'],original); self.assertEqual(item['execution_status'],'resumed'); invocation=json.loads((out/item['invocation_manifest']).read_text()); self.assertEqual(invocation['status'],'completed'); self.assertEqual(invocation['resumed_jobs'],[['G','ridge']]); self.assertTrue(runner.validate_result_tree(out,'smoke')['release_validation_passed'])
 def test_failed_invocation_manifest_records_uncompleted_jobs(self):
  temp,run=self.make_run(); self.addCleanup(temp.cleanup); out=run/'results/best_beam_power_regression/smoke'; out.mkdir(parents=True); runner._ACTIVE_INVOCATION={'out':out,'mode':'smoke','jobs':[('G','ridge')],'normalized_cli_args':{},'source_fingerprints':{'runner.py':'source'},'dependency_versions':{'numpy':'1'},'canonical_manifest_sha256':'canonical','input_hashes':{'input':'hash'},'invocation_id':'failed-test','timestamp_utc':'2026-01-01T00:00:00+00:00','completed_jobs':[],'resumed_jobs':[],'failed_jobs':[]}; runner._record_failed_invocation(); failed=json.loads((out/'invocations/failed-test.failed.json').read_text()); self.assertEqual(failed['status'],'failed'); self.assertEqual(failed['failed_jobs'],[['G','ridge']])
 def test_invocation_tampering_is_rejected(self):
  temp,run,full=self.make_completed_full_fixture(); self.addCleanup(temp.cleanup); summary_path=full/'validation_summary.json'; invocation_path=full/'invocations/full-fixture.json'; canonical_path=full/'experiment_manifest.json'; provenance_path=full/'provenance_manifest.json'; original={path:path.read_bytes() for path in (summary_path,invocation_path,canonical_path,provenance_path)}
  mutations=[]
  def mutate_summary(field,value):
   summary=json.loads(summary_path.read_text()); summary['runs'][0][field]=value; summary_path.write_text(json.dumps(summary,sort_keys=True,indent=2)+'\n')
  def mutate_provenance(field,value):
   provenance=json.loads(provenance_path.read_text()); provenance[field]=value; provenance_path.write_text(json.dumps(provenance,sort_keys=True,indent=2)+'\n')
  mutations.extend([('missing invocation manifest',lambda: invocation_path.unlink()),('wrong invocation id',lambda: mutate_summary('invocation_id','wrong')),('other regression job invocation',lambda: mutate_summary('job_identity',['GS','ridge'])),('timestamp mismatch',lambda: mutate_summary('created_at_utc','2026-01-01T00:00:01+00:00')),('input hash mismatch',lambda: mutate_provenance('input_hashes',{'changed':'hash'})),('source hash mismatch',lambda: mutate_provenance('execution_source_hashes',{'changed.py':'hash'})),('dependency hash mismatch',lambda: mutate_provenance('dependency_versions',{'numpy':'changed'})),('canonical manifest mismatch',lambda: canonical_path.write_text(canonical_path.read_text()+'\n')),('failed invocation',lambda: invocation_path.write_text(invocation_path.read_text().replace('"status": "completed"','"status": "failed"')))])
  for name,mutation in mutations:
   with self.subTest(name=name):
    mutation()
    with self.assertRaises(b.RegressionInputError): runner.validate_result_tree(full,'full')
    for path,data in original.items(): path.write_bytes(data)
 def test_summarize_completed_release_writes_summary_and_preserves_release_validation(self):
  temp,run,full=self.make_completed_full_fixture(); self.addCleanup(temp.cleanup)
  command=[sys.executable,str(Path(__file__).with_name('run_best_beam_power_regression.py')),'--experiment-root',str(run),'--summarize-results','--result-mode','full']
  completed=subprocess.run(command,capture_output=True,text=True)
  self.assertEqual(completed.returncode,0,completed.stderr)
  summary_path=full/'best_model_summary.csv'; self.assertTrue(summary_path.is_file())
  manifest=json.loads((full/'artifact_manifest.json').read_text())
  relative=str(summary_path.relative_to(run)); entry=next(item for item in manifest['files'] if item['path']==relative)
  self.assertEqual(entry['sha256'],runner.stable_source_hash(summary_path))
  report=runner.validate_result_tree(full,'full')
  self.assertTrue(report['release_validation_passed'])
 def test_job_inventory_is_sorted_unique_for_partial_selections(self):
  self.assertEqual(runner.job_inventory([('GS','ridge'),('G','ridge'),('G','ridge')]),[['G','ridge'],['GS','ridge']]); self.assertEqual(runner.job_inventory([('G','ridge'),('G','mean')]),[['G','mean'],['G','ridge']])
 def test_full_inventory_missing_duplicate_and_unexpected_jobs_are_rejected(self):
  for mutation in ('missing','duplicate','unexpected'):
   with self.subTest(mutation=mutation):
    temp,run,full=self.make_completed_full_fixture(); self.addCleanup(temp.cleanup); path=full/'validation_summary.json'; summary=json.loads(path.read_text())
    if mutation=='missing': summary['runs'].pop()
    elif mutation=='duplicate': summary['runs'].append(dict(summary['runs'][0]))
    else: summary['runs'].append({**summary['runs'][0],'representation':'BAD'})
    path.write_text(json.dumps(summary,sort_keys=True,indent=2)+'\n')
    with self.assertRaises(b.RegressionInputError): runner.validate_result_tree(full,'full')
 def test_legacy_result_is_structural_but_not_release_ready(self):
  temp,run,out=self.make_completed_smoke(); self.addCleanup(temp.cleanup); (out/'provenance_manifest.json').unlink(); (out/'artifact_manifest.json').unlink()
  report=runner.validate_result_tree(out,'smoke'); self.assertTrue(report['structural_validation_passed']); self.assertEqual(report['provenance_status'],'missing'); self.assertFalse(report['passed'])
 def test_prediction_target_tampering_is_rejected(self):
  temp,run,out=self.make_completed_smoke(); self.addCleanup(temp.cleanup); path=out/'held_out_predictions.csv'; rows=b._read_csv(path); rows[0]['y_true']=str(float(rows[0]['y_true'])+1.0); b._write_csv(path,list(rows[0]),rows)
  with self.assertRaises(b.RegressionInputError): runner.validate_result_tree(out,'smoke')
 def test_prediction_split_tampering_is_rejected(self):
  temp,run,out=self.make_completed_smoke(); self.addCleanup(temp.cleanup); path=out/'held_out_predictions.csv'; rows=b._read_csv(path); rows[0]['split']='training'; b._write_csv(path,list(rows[0]),rows)
  with self.assertRaises(b.RegressionInputError): runner.validate_result_tree(out,'smoke')
 def test_artifact_hash_tampering_is_rejected(self):
  temp,run,out=self.make_completed_smoke(); self.addCleanup(temp.cleanup); model=run/'models/best_beam_power_regression/smoke/G_ridge.pkl'; model.write_bytes(model.read_bytes()+b'corruption')
  with self.assertRaises(b.RegressionInputError): runner.validate_result_tree(out,'smoke')
 def test_input_tampering_is_behavior_affecting(self):
  temp,run,out=self.make_completed_smoke(); self.addCleanup(temp.cleanup); source=run/'beam_results/canonical_4x4_dft16/beam_experiment_manifest.json'; source.write_text(source.read_text()+'\n')
  report=runner.validate_result_tree(out,'smoke'); self.assertEqual(report['provenance_status'],'behavior_affecting'); self.assertFalse(report['passed']); self.assertTrue(report['structural_validation_passed'])
 def test_source_provenance_tampering_is_unknown(self):
  temp,run,out=self.make_completed_smoke(); self.addCleanup(temp.cleanup); provenance= json.loads((out/'provenance_manifest.json').read_text()); provenance['execution_source_hashes']={}; (out/'provenance_manifest.json').write_text(json.dumps(provenance,sort_keys=True,indent=2)+'\n'); artifact=json.loads((out/'artifact_manifest.json').read_text()); entry=next(item for item in artifact['files'] if item['path'].endswith('/provenance_manifest.json') or item['path']=='results/best_beam_power_regression/smoke/provenance_manifest.json'); entry['sha256']=runner.stable_source_hash(out/'provenance_manifest.json'); (out/'artifact_manifest.json').write_text(json.dumps(artifact,sort_keys=True,indent=2)+'\n')
  report=runner.validate_result_tree(out,'smoke'); self.assertEqual(report['provenance_status'],'unknown'); self.assertFalse(report['passed'])
 def test_summary_tampering_is_rejected(self):
  temp,run,out=self.make_completed_smoke(); self.addCleanup(temp.cleanup); path=out/'validation_summary.json'; summary=json.loads(path.read_text()); summary['runs'][0]['target_name']='wrong_target'; path.write_text(json.dumps(summary,sort_keys=True,indent=2)+'\n')
  with self.assertRaises(b.RegressionInputError): runner.validate_result_tree(out,'smoke')
 def test_prediction_tampering_with_updated_artifact_hash_is_rejected(self):
  temp,run,out=self.make_completed_smoke(); self.addCleanup(temp.cleanup); path=out/'held_out_predictions.csv'; rows=b._read_csv(path); rows[0]['y_pred']=str(float(rows[0]['y_pred'])+5.0); b._write_csv(path,list(rows[0]),rows); artifact=json.loads((out/'artifact_manifest.json').read_text()); entry=next(item for item in artifact['files'] if item['path'].endswith('/held_out_predictions.csv')); entry['sha256']=runner.stable_source_hash(path); (out/'artifact_manifest.json').write_text(json.dumps(artifact,sort_keys=True,indent=2)+'\n')
  with self.assertRaises(b.RegressionInputError): runner.validate_result_tree(out,'smoke')
 def test_summarize_does_not_modify_legacy_outputs(self):
  temp,run,out=self.make_completed_smoke(); self.addCleanup(temp.cleanup); (out/'provenance_manifest.json').unlink(); (out/'artifact_manifest.json').unlink(); command=[sys.executable,str(Path(__file__).with_name('run_best_beam_power_regression.py')),'--experiment-root',str(run),'--summarize-results','--result-mode','smoke']; completed=subprocess.run(command,capture_output=True,text=True); self.assertNotEqual(completed.returncode,0); self.assertFalse((out/'best_model_summary.csv').exists())
 def test_allow_legacy_summary_writes_non_release_metadata_without_artifact_manifest(self):
  temp,run,out=self.make_completed_smoke(); self.addCleanup(temp.cleanup); (out/'provenance_manifest.json').unlink(); (out/'artifact_manifest.json').unlink(); command=[sys.executable,str(Path(__file__).with_name('run_best_beam_power_regression.py')),'--experiment-root',str(run),'--summarize-results','--result-mode','smoke','--allow-legacy-summary']; completed=subprocess.run(command,capture_output=True,text=True); self.assertEqual(completed.returncode,0,completed.stderr); self.assertTrue((out/'best_model_summary.csv').is_file()); metadata=json.loads((out/'legacy_summary_metadata.json').read_text()); self.assertTrue(metadata['structural_validation_passed']); self.assertFalse(metadata['release_validation_passed']); self.assertEqual(metadata['provenance_status'],'missing'); source=out/'detailed_run_results.csv'; self.assertEqual(metadata['source_result_hashes'][str(source.relative_to(run))],runner.stable_source_hash(source)); self.assertFalse((out/'artifact_manifest.json').exists()); report=runner.validate_result_tree(out,'smoke'); self.assertTrue(report['structural_validation_passed']); self.assertFalse(report['release_validation_passed'])
if __name__=='__main__': unittest.main()
