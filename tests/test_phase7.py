import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from test_judge import PROBLEM
from benchmark.termination import (CONDITIONS,LIMITS,SYSTEM,REMINDER,STUDY,ROOT,
                                   frozen_policy,implementation_hashes,prompt_preview,validate_plan)
from benchmark.termination_metrics import trajectory,factorial,condition_metrics
from benchmark.protocol import tools,SYSTEM_PROMPT
from benchmark.harness import sha,validate_harness
from benchmark import storage
from minioj import db
from scripts.phase7 import load_plan,compare_prompts,dry_run

PLAN=ROOT/'benchmark/experiments'/STUDY/'execution_plan.json'

class Phase7Tests(unittest.TestCase):
    def execute(self,c,sequences,**kwargs):
        from test_harness_ablation import HarnessTests
        return HarnessTests().execute(c,sequences,phase7=True,**kwargs)

    def call(self,name,args=None,i=0):
        from test_harness_ablation import call
        return call(name,args,i)

    def test_frozen_allocation_and_immutable_legacy_plan(self):
        plan=load_plan(PLAN);self.assertEqual(validate_plan(plan)['planned_units'],40)
        ids=set()
        for c in CONDITIONS:
            units=[u for u in plan['schedule'] if u['condition']==c];self.assertEqual(len(units),10)
            for p in plan['problems']:
                repetitions=[u['repetition'] for u in units if u['problem_key']==p['problem_key']]
                self.assertEqual(sorted(repetitions),[1,2])
        for i,u in enumerate(plan['schedule']):
            ids.add(u['unit_id']);self.assertEqual(i,u['execution_ordinal'])
            self.assertEqual(u['max_model_calls'],6);self.assertEqual(u['max_tool_calls'],50)
            self.assertEqual(u['max_wall_time_seconds'],300);self.assertIsNone(u['seed_effective'])
        self.assertEqual(len(ids),40)
        old=json.loads((ROOT/'benchmark/experiments/harness_ablation_v1/execution_plan.json').read_text())
        self.assertEqual(old['plan_id'],'43c5fa6bf0d6064c6c16053d0e19d3e6f1e9d7ff6ba88eb478f08a9899679665')
        self.assertEqual(SYSTEM_PROMPT,'Solve the given algorithm problem in C++17 using the isolated Linux workspace. Read problem.json, write main.cpp, compile and test with sample.in, then final_submit. Hidden tests are unavailable until submission. Use only provided tools. Do not merely return source code.')

    def test_temporal_blocks_separate_same_problem_groups(self):
        plan=load_plan(PLAN)
        for r in (1,2):
            for p in plan['problems']:
                units=[u for u in plan['schedule'] if u['repetition']==r and u['problem_key']==p['problem_key']]
                self.assertEqual(len({u['temporal_block'] for u in units}),4)

    def test_real_message_factor_isolation_every_round(self):
        plan=load_plan(PLAN);comparison=compare_prompts(plan)
        self.assertEqual(len(comparison['rounds']),6)
        for round in comparison['rounds']:
            for c,messages in round['messages'].items():
                text=messages[1]['content'];self.assertIn('absolute paths are rejected',text)
                self.assertIn('Source file: main.cpp',text)
                self.assertEqual(text.count(REMINDER),int(CONDITIONS[c]['submit_reminder']))
                self.assertNotIn('SECRET_HIDDEN',text)
                self.assertEqual(messages[0]['content'],SYSTEM)
        self.assertNotIn('must',SYSTEM);self.assertNotIn('then final_submit',SYSTEM)

    def test_actual_runner_sends_same_schema_and_correct_interventions(self):
        for c in CONDITIONS:
            model,r,status=self.execute(c,[[self.call('read_file',{'path':'problem.json'})],[self.call('final_submit')]])
            self.assertEqual(status,'Finished');self.assertTrue(r['final_submit_completed'])
            for messages,schema in model.requests:
                self.assertEqual(schema,tools('final_only'))
                text=messages[1]['content']
                self.assertEqual('[Runtime Budget]' in text,CONDITIONS[c]['budget_visible'])
                self.assertEqual(REMINDER in text,CONDITIONS[c]['submit_reminder'])
                self.assertNotIn('SECRET_HIDDEN',str(messages));self.assertNotIn('SECRET_EXPECTED',str(messages))
            self.assertFalse(any('[Runtime Budget]' in str(m) for m in r['messages']))
            for event in r['harness_injections']:
                self.assertEqual(event['content_sha256'],hashlib.sha256(event['content'].encode()).hexdigest())
                self.assertIsNone(event['extra_tokens'])

    def test_last_response_tools_and_final_submit_are_within_budget(self):
        seq=[[self.call('terminal',{'command':'true'},i)] for i in range(5)]+[[self.call('final_submit',i=6)]]
        for c in CONDITIONS:
            model,r,status=self.execute(c,seq);self.assertEqual(status,'Finished');self.assertEqual(r['model_calls'],6)
            budgets=[e['budget'] for e in r['harness_injections']]
            if c in 'BD':self.assertEqual([b['model_responses_remaining_including_current'] for b in budgets],[6,5,4,3,2,1])
            else:self.assertEqual(budgets,[None]*6)

    def test_call_exhaustion_and_capture_keeps_original_failure(self):
        for c in CONDITIONS:
            model,r,status=self.execute(c,[[self.call('terminal',{'command':'true'},i)] for i in range(6)])
            self.assertEqual(len(model.requests),6);self.assertEqual(status,'Failed')
            self.assertEqual(r['failure_category'],'agent_failure');self.assertEqual(r['terminal_reason'],'model_call_budget')
            self.assertFalse(r['final_submit_attempted']);self.assertIsNotNone(r['termination_code'])
            self.assertIsNone(r['last_code_change_model_call'])

    def test_tool_budget_never_negative_and_pairing_retained(self):
        seq=[[self.call('read_file',{'path':'problem.json'},i) for i in range(49)],
             [self.call('read_file',{'path':'problem.json'},49),self.call('final_submit',i=50)]]
        model,r,status=self.execute('D',seq)
        self.assertEqual(status,'Failed');self.assertEqual(r['tool_calls'],50);self.assertEqual(r['error'],'tool_call_budget')
        self.assertEqual(r['harness_injections'][1]['budget']['tool_remaining'],1)
        messages=model.requests[1][0];assistant=next(m for m in messages if m['role']=='assistant')
        self.assertEqual([tc['id'] for tc in assistant['tool_calls']],[m['tool_call_id'] for m in messages if m['role']=='tool'])

    def test_provider_failure_keeps_attempt_count_and_unknown_usage(self):
        from benchmark.adapters import ModelFailure
        model,r,status=self.execute('B',[ModelFailure('offline_failure')])
        self.assertEqual(r['model_calls'],1);self.assertEqual(r['harness_injections'][0]['budget']['model_responses_remaining_including_current'],6)
        self.assertIsNone(r['usage']);self.assertEqual(r['failure_category'],'model_failure')

    def test_budget_clamped_and_reminder_independent_of_counters(self):
        for c in CONDITIONS:
            first=prompt_preview(c,frozen_policy(),1,0,300)[1]['content']
            last=prompt_preview(c,frozen_policy(),6,55,-1)[1]['content']
            if c in 'AC':self.assertEqual(first,last)
            else:self.assertIn('"tool_remaining": 0',last);self.assertIn('"run_wall_remaining_seconds": 0',last)
            if c in 'CD':self.assertEqual(last.split('\n\n')[-1],REMINDER)

    def test_trajectory_only_asserts_observable_changes(self):
        event={'name':'write_file','args':{'path':'main.cpp','content':'code'},'result':{'size':4},'model_call':2,'tool_call':3}
        r={'model_calls':6,'tool_calls':8,'tool_events':[event], 'final_submit_attempted':False,'error':'model_call_budget'}
        d=trajectory(r,LIMITS);self.assertEqual(d['last_code_change_model_call'],2)
        self.assertEqual(d['model_calls_after_last_code_change'],4);self.assertEqual(d['tool_calls_after_last_code_change'],5)
        self.assertEqual(d['remaining_calls_at_last_code_change'],4);self.assertIsNone(d['posthoc_rejudge_verdict'])
        r['tool_events'].append({**event,'model_call':5,'tool_call':7})
        self.assertEqual(trajectory(r,LIMITS)['last_code_change_model_call'],2)
        r['tool_events'].append({'name':'terminal','args':{'command':'background writer'}})
        self.assertIsNone(trajectory(r,LIMITS)['last_code_change_model_call'])
        r.pop('tool_events');self.assertIsNone(trajectory(r,LIMITS)['tool_calls_after_last_code_change'])

    def test_dry_run_does_not_construct_paid_adapter_or_read_config(self):
        with patch('benchmark.adapters.deepseek.DeepSeekAdapter',side_effect=AssertionError('paid adapter forbidden')):
            result=dry_run(load_plan(PLAN))
        self.assertEqual(result['constructed_units'],40);self.assertEqual(result['paid_calls'],0)
        for g in result['factorial']['groups'].values():
            self.assertEqual(g['counts']['completed_units'],10)
            self.assertEqual(g['diagnostics']['valid_code_unknown_count'],10)

    def test_storage_rejects_common_parameter_drift(self):
        db.initialize();pid=db.save_problem({**PROBLEM,'allow_workspace':True})
        spec={'name':'phase7','problems':[pid],'models':[{'provider':'fake','model':'phase7'}], 'seeds':[1,2],
              'system_prompt':SYSTEM,'limits':LIMITS,'temperature':0,'max_tokens':4096,
              'harness':{'study':STUDY,'condition':'B','sandbox_policy':frozen_policy(),'implementation_sha256':implementation_hashes()}}
        bid=storage.create(spec);e=storage.get(bid,True);self.assertEqual(len(e['units']),2)
        for key,value in [('temperature',.2),('max_tokens',2048),('system_prompt',SYSTEM_PROMPT),('seeds',[1])]:
            bad=copy.deepcopy(spec);bad[key]=value
            with self.assertRaises(ValueError):storage.create(bad)
        bad=copy.deepcopy(spec);bad['limits']['max_model_calls']=7
        with self.assertRaises(ValueError):storage.create(bad)

    def test_rehashed_plan_cannot_change_frozen_parameters(self):
        plan=load_plan(PLAN)
        for mutate in (lambda p:p['shared'].update(image_id='sha256:new'),lambda p:p['shared'].update(temperature=.2),
                       lambda p:p['schedule'][0].update(max_model_calls=12),lambda p:p['schedule'].reverse()):
            bad=copy.deepcopy(plan);mutate(bad);bad['plan_id']=sha({k:v for k,v in bad.items() if k!='plan_id'})
            with self.assertRaises(ValueError):validate_plan(bad)

    def test_offline_cli_has_no_production_config_or_paid_adapter(self):
        command="from scripts.phase7 import load_plan,PLAN,compare_prompts,dry_run; import sys; p=load_plan(PLAN); compare_prompts(p); dry_run(p); assert 'minioj.config' not in sys.modules; assert 'benchmark.adapters.deepseek' not in sys.modules"
        subprocess.run([sys.executable,'-c',command],cwd=ROOT,check=True,capture_output=True,timeout=30)

    def test_offline_validation_does_not_require_git_history(self):
        with patch('benchmark.posthoc.judge_compatibility',side_effect=AssertionError('shallow clone has no historical commit')):
            self.assertEqual(load_plan(PLAN)['planned_units'],40)

    def test_full_initial_request_hash_includes_public_problem(self):
        plan=load_plan(PLAN)
        for u in plan['schedule']:
            problem=plan['problems'][u['problem_index']]['public_snapshot']
            messages=prompt_preview(u['condition'],plan['sandbox_policy'],problem=problem)
            self.assertEqual(u['prompt_sha256'],sha(messages))
            self.assertEqual(json.loads(messages[-1]['content']),problem)
            self.assertNotIn('testcases',problem)

    def test_csv_phase7_fields_do_not_change_legacy_headers(self):
        from benchmark.reports import csv_text,FIELDS
        e={'manifest':{'harness':{'study':STUDY}},'units':[{'id':'u','run_id':'r','status':'Failed','record':{
            'last_code_change_model_call':None,'terminal_reason':'model_call_budget','final_submit_attempted':False}}]}
        rows=list(csv.DictReader(io.StringIO(csv_text(e))))
        self.assertEqual(rows[0]['unit_id'],'u');self.assertEqual(rows[0]['last_code_change_model_call'],'')
        self.assertEqual(rows[0]['terminal_reason'],'model_call_budget')
        e['manifest']={};self.assertEqual(next(csv.reader(io.StringIO(csv_text(e)))),FIELDS)

    def test_real_mode_without_authorization_stops_before_provider(self):
        with patch('benchmark.adapters.deepseek.DeepSeekAdapter',side_effect=AssertionError('paid adapter forbidden')):
            from scripts.phase7 import main
            with patch.object(sys,'argv',['phase7','--real']):
                with self.assertRaises(ValueError):main()

class Phase7MetricsTests(unittest.TestCase):
    def experiment(self,solved):
        units=[]
        for i in range(10):
            ok=i<solved
            units.append({'id':str(i),'problem_id':i//2+10,'model_index':0,'seed':i%2+1,'status':'Finished' if ok else 'Failed',
                          'record':{'verdict':'AC' if ok else None,'error':None if ok else 'model_call_budget',
                                    'failure_category':None if ok else 'agent_failure','final_submit_attempted':ok,
                                    'final_submission_completed':ok,'usage':{'input_tokens':10,'output_tokens':5}}})
        return {'manifest':{'seeds':[1,2],'models':[{'provider':'fake','model':'fixture'}]},'units':units}

    def test_hand_calculated_factorial_and_missing_observations(self):
        es={c:self.experiment(n) for c,n in zip('ABCD',[2,6,4,9])};f=factorial(es)
        self.assertAlmostEqual(f['descriptive_rate_differences']['budget_average_effect'],.45)
        self.assertAlmostEqual(f['descriptive_rate_differences']['reminder_average_effect'],.25)
        self.assertAlmostEqual(f['descriptive_rate_differences']['interaction'],.1)
        d=f['groups']['A']['diagnostics'];self.assertEqual(d['terminal_denominator'],10)
        self.assertEqual(d['submission_completion_rate'],.2);self.assertEqual(d['final_submit_attempt_rate'],.2)
        self.assertEqual(d['call_budget_exhaustion_rate'],.8);self.assertEqual(d['tokens_per_successful_run'],75)
        self.assertIsNone(d['posthoc_code_correctness']);self.assertEqual(d['valid_code_unknown_count'],10)
        es['A']['units'][0]['record']['usage']=None
        self.assertIsNone(factorial(es)['groups']['A']['diagnostics']['tokens_per_successful_run'])
        es['D']['units'][-1]['status']='Pending'
        self.assertIsNone(factorial(es)['descriptive_rate_differences']['interaction'])

    def test_posthoc_analysis_requires_source_tests_and_image_provenance(self):
        import tempfile
        from scripts.phase7 import analyze
        from benchmark.posthoc import code_sha
        with tempfile.TemporaryDirectory() as data:
            directory=Path(data);before={}
            for c in 'ABCD':
                e=self.experiment(1)
                e['manifest'].update(harness={'study':STUDY,'condition':c},environment_information={'image_id':'sha256:pinned'},
                                     problem_snapshots=[{**PROBLEM,'id':pid} for pid in range(10,15)])
                for u in e['units']:u['id']=c+u['id']
                unit=e['units'][0];unit['record']['termination_code']={'content':'code','sha256':code_sha('code'),'provenance':'final_submission_source'}
                (directory/c).mkdir();path=directory/c/'results.json';path.write_text(json.dumps(e));before[path]=path.read_bytes()
                (directory/'private').mkdir(exist_ok=True)
                (directory/'private'/(c+'-trajectories.json')).write_text(json.dumps(e))
                tests_hash=hashlib.sha256(json.dumps(PROBLEM['testcases'],sort_keys=True).encode()).hexdigest()
                observation={'unit_id':unit['id'],'status':'verified','verdict':'AC','source_sha256':code_sha('code'),
                             'tests_sha256':tests_hash,'image_id':'sha256:pinned','judge_compatibility':{'compatible':True}}
                if c=='B':observation['source_sha256']='wrong'
                (directory/(c+'-posthoc.json')).write_text(json.dumps({'results':[observation]}))
            result=analyze(directory)
            self.assertEqual(result['factorial']['groups']['A']['diagnostics']['valid_code_ac_count'],1)
            self.assertEqual(result['factorial']['groups']['B']['diagnostics']['valid_code_ac_count'],0)
            self.assertIsNone(result['factorial']['groups']['B']['diagnostics']['posthoc_code_correctness'])
            self.assertTrue(all(path.read_bytes()==raw for path,raw in before.items()))

    def test_failures_and_wall_budget_remain_separate(self):
        e=self.experiment(0)
        for u,category in zip(e['units'],['agent_failure','model_failure','judge_failure','infrastructure_failure']):
            u['record']['failure_category']=category;u['record']['error']=category
        e['units'][0]['record']['error']='wall_time_budget'
        d=condition_metrics(e['units'],{'0':{'status':'unknown','verdict':None},'1':{'status':'verified','verdict':'AC'}})
        self.assertEqual(d['call_budget_exhaustion_rate'],.6);self.assertEqual(d['wall_budget_exhaustion_count'],1)
        self.assertEqual(d['posthoc_code_correctness'],1);self.assertEqual(d['valid_code_unknown_count'],9)
        self.assertEqual(d['end_to_end_success_rate'],0)
