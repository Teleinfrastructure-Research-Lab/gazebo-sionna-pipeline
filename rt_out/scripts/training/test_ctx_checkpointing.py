import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import run_best_beam_power_regression_ctx as ctx
from best_beam_power_regression import RegressionInputError

class CheckpointTests(unittest.TestCase):
 def checkpoint(self,out,predictions):
  cfg=ctx.config(('CTX',)); h=ctx.manifest_hash(cfg); pair=('CTX','per_rx_median'); result={'representation':'CTX','method':'per_rx_median','validation_metrics':{'mae':1,'rmse':1},'test_metrics':{'mae':1,'rmse':1},'input_dimension':16,'measurement_aided':False,'scene_based':False}
  ctx._write_json(out/'manifest.json',cfg); ctx._write_json(ctx.checkpoint_path(out,pair),{'status':'complete','representation':pair[0],'method':pair[1],'expected_test_row_count':4326,'manifest_hash':h,'completion_timestamp_utc':'now','result':result,'test_predictions':predictions}); return cfg,h,pair
 def predictions(self,duplicate=False):
  rows=[{'representation':'CTX','method':'per_rx_median','source_frame_id':str(1715+i//6),'rx_id':f'rx_{i%6}','target':-30.,'prediction':-31.} for i in range(4326)]
  if duplicate:rows[-1]=dict(rows[0])
  return rows
 def test_atomic_pair_checkpoint_and_resume_state(self):
  with tempfile.TemporaryDirectory() as directory:
   out=Path(directory); result={'representation':'CTX','method':'per_rx_median','validation_metrics':{'mae':1,'rmse':1},'test_metrics':{'mae':1,'rmse':1},'input_dimension':16,'measurement_aided':False,'scene_based':False}
   prediction={'representation':'CTX','method':'per_rx_median','source_frame_id':'1715','rx_id':'rx_a','target':-30,'prediction':-31}
   ctx.write_outputs(out,[result],[prediction]); ctx.status(out,'start',[('CTX','per_rx_median')],None,[('CTX','persistence')])
   self.assertEqual(json.loads((out/'results.json').read_text())[0]['method'],'per_rx_median')
   progress=json.loads((out/'progress.json').read_text()); self.assertEqual(progress['completed_pairs'],[['CTX','per_rx_median']]); self.assertEqual(progress['pending_pairs'],[['CTX','persistence']])
   self.assertFalse(list(out.glob('*.tmp')))
 def test_resume_manifest_mismatch_is_detectable(self):
  with tempfile.TemporaryDirectory() as directory:
   out=Path(directory); ctx._write_json(out/'manifest.json',{'bad':True})
   self.assertNotEqual(json.loads((out/'manifest.json').read_text()),ctx.config(('CTX','G')))
 def test_partial_checkpoint_is_rejected_and_not_resumed(self):
  with tempfile.TemporaryDirectory() as directory:
   out=Path(directory); cfg,h,pair=self.checkpoint(out,self.predictions()[:-1])
   with self.assertRaises(RegressionInputError):ctx.discover_checkpoints(out,h,[pair])
 def test_duplicate_prediction_checkpoint_is_rejected(self):
  with tempfile.TemporaryDirectory() as directory:
   out=Path(directory); cfg,h,pair=self.checkpoint(out,self.predictions(True))
   with self.assertRaises(RegressionInputError):ctx.validate_pair_checkpoint(ctx.checkpoint_path(out,pair),h,pair)
 def test_valid_checkpoint_skips_and_rebuilds_aggregates(self):
  with tempfile.TemporaryDirectory() as directory:
   out=Path(directory); cfg,h,pair=self.checkpoint(out,self.predictions()); found=ctx.rebuild_aggregates(out,h,[pair]); self.assertEqual(len(found),1); self.assertEqual(json.loads((out/'results.json').read_text())[0]['method'],pair[1]); self.assertEqual(len((out/'test_predictions.csv').read_text().splitlines()),4327)
 def test_stale_aggregate_does_not_mark_pair_complete(self):
  with tempfile.TemporaryDirectory() as directory:
   out=Path(directory); cfg=ctx.config(('CTX',));h=ctx.manifest_hash(cfg);ctx._write_json(out/'results.json',[{'representation':'CTX','method':'per_rx_median'}]); self.assertEqual(ctx.discover_checkpoints(out,h,[('CTX','per_rx_median')]),[])
if __name__=='__main__': unittest.main()
