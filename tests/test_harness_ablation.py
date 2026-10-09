import copy
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from test_judge import PROBLEM
from benchmark import storage
from benchmark.ablation import build_plan, validate_plan, ExecutionGuard, authorize
from benchmark.adapters import Reply, ModelFailure
from benchmark.diagnostics import diagnostics
from benchmark.harness import CONDITIONS, request_messages, sandbox_policy, sha
from benchmark.protocol import SYSTEM_PROMPT, tools
from benchmark.runner import Runner, AgentFailure
from minioj import db


def call(name, args=None, index=0):
    return {'id':str(index), 'type':'function', 'function':{'name':name,'arguments':json.dumps(args or {})}}


class Model:
    def __init__(self, sequences): self.sequences=sequences;self.requests=[]
    def complete(self, messages, schema, *args):
        self.requests.append((copy.deepcopy(messages),copy.deepcopy(schema)))
        sequence=self.sequences[len(self.requests)-1]
        if isinstance(sequence,Exception):raise sequence
        return Reply({'role':'assistant','content':None,'tool_calls':sequence}, {'input_tokens':10,'output_tokens':5},'fake')


class HarnessTests(unittest.TestCase):
    def execute(self, condition, sequences, result=None, submission_verdict="AC", command_failure=None):
        policy=sandbox_policy(); definition=CONDITIONS[condition]
        manifest={'models':[{'provider':'fake','model':'fixture'}],'system_prompt':SYSTEM_PROMPT,
                  'tool_schema':tools('final_only'),'protocol':'final_only','temperature':.2,'max_tokens':2048,
                  'limits':{'max_model_calls':definition['max_model_calls'],'max_tool_calls':16,'max_wall_time_seconds':180},
                  'harness':{'condition':condition,'sandbox_policy':policy},
                  'problem_snapshots':[{'testcases':[{'input':'SECRET_HIDDEN','expected_output':'SECRET_EXPECTED'}]}]}
        unit={'id':'u','run_id':None,'status':'Pending','model_index':0,'seed':1,'record':{'model_calls':0,'tool_calls':0}}
        runner=Runner('http://127.0.0.1:1','test');saved=[];model=Model(sequences)
        def api(method,path,**kwargs):
            if path.endswith('/run'):return {'id':'r','problem':{**PROBLEM,'id':1,'testcases_removed':True}}
            if path.endswith('/file') and method=='GET':return {'content':'int main(){}'}
            if path.endswith('/file'):return {'size':12}
            if path.endswith('/commands'):return {'command_id':'c'}
            if path.endswith('/final-submit'):return {'submission_id':1}
            return {}
        def wait(path,*args):
            if path.startswith('/commands/') and command_failure:raise command_failure
            if path.startswith('/commands/'):return {'result':result or {'returncode':0,'reason':None,'stdout':'','stderr':''}}
            return {'id':1,'verdict':submission_verdict,'passed_tests':1,'total_tests':1,'source_code':'int main(){}'}
        with patch('benchmark.runner.adapter',return_value=model),patch('benchmark.runner.capture_snapshot',return_value=None if command_failure else {'content':'int main(){}','sha256':__import__('hashlib').sha256(b'int main(){}').hexdigest(),'provenance':'paused_container_copy_before_cleanup'}),patch.object(runner,'api',side_effect=api),patch.object(runner,'wait',side_effect=wait),patch.object(runner,'checkpoint',side_effect=lambda *a,**kw:saved.append(copy.deepcopy(a))):
            runner.execute('b',unit,manifest)
        runner.client.close()
        return model,saved[-1][2],saved[-1][3]

    def test_exact_visibility_matrix_and_no_hidden_feedback(self):
        for c in CONDITIONS:
            model,r,status=self.execute(c,[[call('final_submit')]])
            content='\n'.join(m.get('content') or '' for m in model.requests[0][0])
            self.assertEqual('[Agent Runtime Budget]' in content,CONDITIONS[c]['budget_visible'])
            self.assertEqual('[Sandbox Boundaries]' in content,CONDITIONS[c]['sandbox_visible'])
            self.assertNotIn('SECRET_HIDDEN',content);self.assertNotIn('SECRET_EXPECTED',content)
            self.assertEqual(model.requests[0][1],tools('final_only'))
            self.assertEqual(status,'Finished');self.assertTrue(r['final_submission_completed'])
            if c=='A':self.assertEqual(model.requests[0][0][0],{'role':'system','content':SYSTEM_PROMPT});self.assertEqual(len(model.requests[0][0]),2)

    def test_budget_monotonic_ephemeral_and_last_response_submission(self):
        for c,maximum in [('B',6),('E',12)]:
            sequences=[[call('terminal',{'command':'true'},i)] for i in range(maximum-1)]+[[call('final_submit',index=maximum)]]
            model,r,status=self.execute(c,sequences)
            self.assertEqual(len(model.requests),maximum);self.assertEqual(status,'Finished')
            budgets=[e['budget'] for e in r['harness_injections']]
            self.assertEqual([b['model_responses_remaining_including_current'] for b in budgets],list(range(maximum,0,-1)))
            self.assertTrue(all(b['tool_remaining']>=0 for b in budgets))
            self.assertEqual(r['model_calls_before_final_submit'],maximum)
            for messages,_ in model.requests:self.assertEqual(sum('[Agent Runtime Budget]' in (m.get('content') or '') for m in messages),1)
            self.assertFalse(any('[Agent Runtime Budget]' in (m.get('content') or '') for m in r['messages']))
            for e in r['harness_injections']:
                self.assertEqual(e['content_sha256'],__import__('hashlib').sha256(e['content'].encode()).hexdigest());self.assertIsNone(e['extra_tokens'])

    def test_exhaustion_never_calls_model_seventh_time(self):
        model,r,status=self.execute('D',[[call('terminal',{'command':'true'},i)] for i in range(6)])
        self.assertEqual(len(model.requests),6);self.assertEqual(status,'Failed');self.assertEqual(r['error'],'model_call_budget')
        self.assertFalse(r['final_submit_attempted']);self.assertEqual(r['termination_code']['provenance'],'paused_container_copy_before_cleanup')

    def test_multi_tool_response_pairing(self):
        seq=[[call('write_file',{'path':'main.cpp','content':'int main(){}'},1),call('terminal',{'command':'true'},2)],[call('final_submit',index=3)]]
        model,r,status=self.execute('B',seq)
        history=model.requests[1][0]
        assistant=next(m for m in history if m['role']=='assistant')
        tool_ids=[m['tool_call_id'] for m in history if m['role']=='tool']
        self.assertEqual([t['id'] for t in assistant['tool_calls']],tool_ids)
        self.assertEqual([e['budget']['tool_remaining'] for e in r['harness_injections']],[16,14])
        self.assertEqual(status,'Finished')

    def test_tool_budget_not_negative(self):
        model,r,status=self.execute('D',[[call('terminal',{'command':'true'},i) for i in range(17)]])
        self.assertEqual(r['tool_calls'],16);self.assertEqual(r['error'],'tool_call_budget');self.assertEqual(status,'Failed')

    def test_provider_failure_is_never_ac(self):
        model,r,status=self.execute('B',[ModelFailure('provider_failed')])
        self.assertEqual(status,'Failed');self.assertEqual(r['failure_category'],'model_failure');self.assertNotIn('verdict',r);self.assertIsNone(r['usage'])

    def test_final_judge_se_keeps_submission_completion_and_source(self):
        model,r,status=self.execute('D',[[call('final_submit')]],submission_verdict='SE')
        self.assertEqual(status,'Failed');self.assertEqual(r['failure_category'],'judge_failure')
        self.assertTrue(r['final_submit_attempted']);self.assertTrue(r['final_submission_completed'])
        self.assertEqual(r['termination_code']['provenance'],'final_submission_source')
        self.assertNotIn('verdict',r)

    def test_unresolved_command_does_not_capture_unstable_source(self):
        from benchmark.runner import InfrastructureFailure
        model,r,status=self.execute('D',[[call('terminal',{'command':'sleep 100'})]],command_failure=InfrastructureFailure('transport_lost'))
        self.assertEqual(status,'Failed');self.assertIsNone(r['termination_code'])

    def test_cleanup_attempted_when_terminal_checkpoint_loses_lease(self):
        from benchmark.runner import InfrastructureFailure
        runner=Runner('http://127.0.0.1:1','test');paths=[]
        manifest={'models':[{'provider':'fake'}],'system_prompt':SYSTEM_PROMPT,'tool_schema':tools('final_only'),
                  'temperature':0,'max_tokens':10,'limits':{'max_model_calls':6,'max_tool_calls':16,'max_wall_time_seconds':180}}
        unit={'id':'u','status':'Pending','model_index':0,'seed':1,'run_id':None,'record':{'model_calls':0,'tool_calls':0}}
        def api(method,path,**kw):
            paths.append(path)
            if path.endswith('/run'):return {'id':'r','problem':PROBLEM}
            if path.endswith('/final-submit'):return {'submission_id':1}
            return {}
        def checkpoint(*args,**kw):
            if len(args)>3:raise InfrastructureFailure('lease_lost')
        with patch('benchmark.runner.adapter',return_value=Model([[call('final_submit')]])),patch.object(runner,'api',side_effect=api),patch.object(runner,'wait',return_value={'id':1,'verdict':'AC','passed_tests':1,'total_tests':1}),patch.object(runner,'checkpoint',side_effect=checkpoint):
            with self.assertRaises(InfrastructureFailure):runner.execute('b',unit,manifest)
        self.assertIn('/agent-runs/r/environment',paths);runner.client.close()

    def test_frozen_harness_storage_and_public_redaction(self):
        db.initialize();pid=db.save_problem({**PROBLEM,'allow_workspace':True})
        spec={'name':'ablation-unit','problems':[pid],'models':[{'provider':'fake','model':'fixture'}],'seeds':[1],
              'limits':{'max_model_calls':6,'max_tool_calls':16,'max_wall_time_seconds':180},'harness':{'condition':'D','sandbox_policy':sandbox_policy()}}
        bid=storage.create(spec);internal=storage.get(bid,True);storage.acquire(bid,'owner')
        uid=internal['units'][0]['id'];storage.update_unit(bid,uid,'owner','Failed',{'termination_code':{'content':'private'},'tool_events':[{'args':{'content':'private'}}]})
        public=storage.get(bid);self.assertNotIn('termination_code',public['units'][0]['record']);self.assertNotIn('tool_events',public['units'][0]['record'])
        self.assertNotIn('testcases',public['manifest']['problem_snapshots'][0]);storage.release(bid,'owner')
        spec['harness']['sandbox_policy']['submission_source_bytes']+=1
        with self.assertRaises(ValueError):storage.create(spec)

    def test_guard_stops_without_credential_access(self):
        guard=ExecutionGuard(2,100);guard.before_model();guard.after_model({'input_tokens':30,'output_tokens':10});guard.before_model();guard.after_model(None)
        with self.assertRaises(AgentFailure):guard.before_model()
        self.assertEqual(guard.calls,2);self.assertEqual(guard.stop_reason,'usage_unavailable')
        guard=ExecutionGuard(5,20);guard.before_model();guard.after_model({'input_tokens':15,'output_tokens':6})
        with self.assertRaises(AgentFailure):guard.before_model()
        plan={'plan_id':'frozen','planned_units':25,'maximum_model_calls':180,'observed_token_stop_cap':350000}
        args=SimpleNamespace(authorize_paid=False,plan_id='frozen',max_runs=25,max_model_calls=180,max_observed_tokens=350000)
        with self.assertRaises(ValueError):authorize(args,plan)
        args.authorize_paid=True;self.assertEqual(authorize(args,plan).max_calls,180)

    def test_history_validation_accepts_null_assistant_content(self):
        from scripts.harness_ablation import validate_model_history
        validate_model_history([{'role':'user','content':'{"id":1}'}, {'role':'assistant','content':None,'tool_calls':[]}])
        with self.assertRaises(AssertionError):validate_model_history([{'role':'user','content':'{"testcases":[]}' }])

    def test_preregistered_plan_and_random_allocation(self):
        p=Path(__file__).resolve().parents[1]/'benchmark/experiments/harness_ablation_v1/execution_plan.json'
        plan=json.loads(p.read_text());self.assertEqual(validate_plan(plan)['maximum_model_calls'],180)
        self.assertNotEqual([x['condition'] for x in plan['schedule'][:5]],list('ABCDE'))
        bad=copy.deepcopy(plan);bad['schedule'][0]=bad['schedule'][1];bad['plan_id']=sha({k:v for k,v in bad.items() if k!='plan_id'})
        with self.assertRaises(ValueError):validate_plan(bad)


class DiagnosticTests(unittest.TestCase):
    def test_hand_calculated_counts_missing_usage_and_posthoc(self):
        def unit(i,status,verdict=None,category=None,error=None):
            r={'verdict':verdict,'failure_category':category,'error':error,
               'final_submit_attempted':verdict is not None,'final_submission_completed':status=='Finished',
               'usage':{'input_tokens':10,'output_tokens':5},'wall_time_seconds':i+1,'tool_events':[],
               'model_calls_before_final_submit':2,'tool_calls_before_final_submit':3}
            return {'id':str(i),'status':status,'record':r}
        units=[unit(0,'Finished','AC'),unit(1,'Finished','WA'),unit(2,'Failed',category='agent_failure',error='model_call_budget'),
               unit(3,'Failed',category='model_failure'),unit(4,'Failed',category='judge_failure'),unit(5,'Failed',category='infrastructure_failure'),
               unit(6,'Pending'),unit(7,'Running')]
        # 6 terminal, 1 E2E AC, 2 submitted, 1 budget, each provider/infra 1.
        d=diagnostics(units,{'2':{'status':'verified','verdict':'AC'}})
        self.assertEqual(d['terminal_denominator'],6);self.assertEqual(d['end_to_end_success_rate'],1/6)
        self.assertEqual(d['submission_completion_rate'],2/6);self.assertEqual(d['budget_exhaustion_rate'],1/6)
        self.assertEqual(d['provider_failure_rate'],1/6);self.assertEqual(d['infrastructure_failure_rate'],1/6)
        self.assertEqual(d['tokens_per_completed_run'],15);self.assertEqual(d['tokens_per_submission_completed_run'],45);self.assertEqual(d['tokens_per_successful_run'],90)
        self.assertEqual(d['valid_code_at_termination_rate'],1);self.assertEqual(d['valid_code_unknown_count'],5)
        units[3]['record']['usage']=None;d=diagnostics(units)
        self.assertIsNone(d['tokens_per_completed_run']);self.assertIsNone(d['valid_code_at_termination_rate']);self.assertEqual(d['valid_code_unknown_count'],6)
        self.assertEqual(d['observed_total_tokens'],75)

    def test_repeated_command_and_limit_tags_are_diagnostics_only(self):
        events=[{'name':'terminal','args':{'command':'generator'},'result':{'returncode':1,'stderr':'File too large'}}]*2
        u={'id':'x','status':'Failed','record':{'tool_events':events,'failure_category':'agent_failure','final_submission_completed':False}}
        d=diagnostics([u]);self.assertEqual(d['tool_limit_error_rate'],1);self.assertEqual(d['repeated_failed_command_rate'],1)
        self.assertEqual(d['end_to_end_success_rate'],0);self.assertEqual(u['record']['failure_category'],'agent_failure')
        del u['record']['final_submission_completed'];self.assertIsNone(diagnostics([u])['end_to_end_success_rate'])
