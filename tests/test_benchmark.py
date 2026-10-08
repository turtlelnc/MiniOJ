import json,time,unittest
from unittest.mock import patch
from test_judge import PROBLEM
from minioj import db
from benchmark import storage
from benchmark.metrics import summary
from benchmark.adapters import ModelFailure
from benchmark.adapters.deepseek import DeepSeekAdapter
from benchmark.runner import Runner
from test_judge import PROBLEM
class BenchmarkTests(unittest.TestCase):
 def setUp(self):
  db.initialize();self.pid=db.save_problem({**PROBLEM,'allow_workspace':True})
 def spec(self):return {'name':'unit-benchmark','problems':[self.pid],'models':[{'provider':'fake','model':'good'}],'seeds':[1,2,3]}
 def test_freeze_and_idempotent_terminal_records(self):
  bid=storage.create(self.spec());b=storage.get(bid,True);uid=b['units'][0]['id'];owner='runner';storage.acquire(bid,owner)
  db.save_problem({**PROBLEM,'testcases':[{'input':'x','expected_output':'y'}]},self.pid)
  self.assertNotEqual(storage.get(bid,True)['manifest']['problem_snapshots'][0]['testcases'],db.problem(self.pid,True)['testcases'])
  self.assertNotIn('testcases',storage.get(bid)['manifest']['problem_snapshots'][0])
  storage.update_unit(bid,uid,owner,'Finished',{'verdict':'AC'})
  storage.update_unit(bid,uid,owner,'Failed',{'error':'overwrite'})
  self.assertEqual(storage.get(bid)['units'][0]['record']['verdict'],'AC')
  storage.release(bid,owner);self.assertEqual(storage.get(bid)['status'],'Paused')
 def test_lease_prevents_duplicate_runners_and_recovery(self):
  bid=storage.create(self.spec());storage.acquire(bid,'one')
  with self.assertRaises(ValueError):storage.acquire(bid,'two')
  with db.connect() as c:c.execute('UPDATE benchmarks SET lease_expires_at=? WHERE id=?',(time.time()-1,bid))
  storage.acquire(bid,'two')
  with self.assertRaises(ValueError):storage.heartbeat(bid,'one')
 def test_metrics_missing_usage_and_first_seed(self):
  def unit(seed,status,verdict=None,category=None):return {'seed':seed,'model_index':0,'status':status,'record':{'verdict':verdict,'failure_category':category,'tool_calls':1,'usage':None}}
  b={'manifest':{'models':[{'provider':'fake','model':'test'}],'protocol':'final_only','seeds':[1,2,3]},'units':[unit(1,'Failed',category='model_failure'),unit(2,'Finished','AC'),unit(3,'Finished','WA')]}
  g=summary(b)['groups'][0];self.assertEqual(g['solve_rate'],.5);self.assertEqual(g['excluded'],1);self.assertIsNone(g['pass@1']);self.assertIsNone(g['mean_total_tokens']);self.assertIsNone(g['tokens_per_solved_problem'])
 def test_secrets_rejected_in_config(self):
  spec=self.spec();spec['models'][0]['api_key']='DO_NOT_STORE'
  with self.assertRaises(ValueError):storage.create(spec)
 def test_provider_missing_key(self):
  with patch.dict('os.environ',{},clear=True):
   with self.assertRaises(ModelFailure):DeepSeekAdapter({'model':'x'})
 def test_final_feedback_not_sent_to_model(self):
  from benchmark.adapters import Reply
  class Model:
   def complete(self,*args):return Reply({'role':'assistant','tool_calls':[{'id':'1','function':{'name':'final_submit','arguments':'{}'}},{'id':'2','function':{'name':'terminal','arguments':'{"command":"must never run"}'}}]},None)
  runner=Runner('http://127.0.0.1:8000','test');calls=[];stored=[]
  def api(method,path,**kwargs):
   calls.append(path)
   if path.endswith('/run'):return {'id':'run','problem':{'id':1}}
   if path.endswith('/final-submit'):return {'submission_id':1}
   return {}
  unit={'id':'unit','record':{'tool_calls':0,'model_calls':0},'run_id':None,'status':'Pending','model_index':0,'seed':1}
  manifest={'limits':{'max_wall_time_seconds':10,'max_model_calls':4,'max_tool_calls':4},'models':[{'provider':'fake'}],'system_prompt':'test','temperature':0,'max_tokens':10,'tool_schema':__import__('benchmark.protocol',fromlist=['tools']).tools('final_only')}
  with patch('benchmark.runner.adapter',return_value=Model()),patch.object(runner,'api',side_effect=api),patch.object(runner,'wait',return_value={'id':1,'verdict':'AC','passed_tests':1,'total_tests':1}),patch.object(runner,'checkpoint',side_effect=lambda *a,**k:stored.append((a,k))):runner.execute('b',unit,manifest)
  self.assertFalse(any(path.endswith('/commands') for path in calls));self.assertEqual(stored[-1][0][3],'Finished');self.assertEqual(stored[-1][0][2]['verdict'],'AC')
 def test_failure_categories_are_not_model_unsolved(self):
  from benchmark.runner import AgentFailure,JudgeFailure,InfrastructureFailure
  errors=[(ModelFailure('provider_timeout'),'model_failure'),(AgentFailure('tool_call_budget'),'agent_failure'),(JudgeFailure('SE'),'judge_failure'),(InfrastructureFailure('server_down'),'infrastructure_failure')]
  for error,category in errors:
   runner=Runner('http://127.0.0.1:8000','test');stored=[]
   unit={'id':'u','record':{'model_calls':0,'tool_calls':0},'run_id':None,'status':'Pending','model_index':0,'seed':1}
   manifest={'limits':{'max_wall_time_seconds':10},'models':[{'provider':'fake'}]}
   with patch('benchmark.runner.adapter',side_effect=error),patch.object(runner,'checkpoint',side_effect=lambda *a,**kw:stored.append(a)):
    runner.execute('b',unit,manifest)
   self.assertEqual(stored[-1][2]['failure_category'],category)
 def test_interrupted_unit_not_replayed(self):
  runner=Runner('http://127.0.0.1:8000','test');stored=[]
  unit={'id':'u','record':{'model_calls':1,'tool_calls':1},'run_id':None,'status':'Running','model_index':0,'seed':1}
  manifest={'limits':{'max_wall_time_seconds':10}}
  with patch('benchmark.runner.adapter') as model,patch.object(runner,'checkpoint',side_effect=lambda *a,**kw:stored.append(a)):
   runner.execute('b',unit,manifest)
  model.assert_not_called();self.assertEqual(stored[-1][2]['failure_category'],'infrastructure_failure');self.assertIsNone(stored[-1][2]['wall_time_seconds'])
