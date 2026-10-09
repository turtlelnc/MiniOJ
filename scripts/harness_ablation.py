"""Offline by default. Real execution requires explicit plan ID and three caps."""
import argparse
import csv
import io
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import uuid
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from benchmark.ablation import validate_plan,authorize
from benchmark.harness import CONDITIONS,sha
PLAN=ROOT/'benchmark/experiments/harness_ablation_v1/execution_plan.json'


def validate_model_history(messages):
    """Check structured public problem disclosures, not arbitrary source text."""
    calls={}
    for message in messages:
        for tc in message.get('tool_calls',[]):calls[tc['id']]=tc
        if message['role']=='user':
            public=json.loads(message['content']);assert 'testcases' not in public
        elif message['role']=='tool':
            tc=calls.get(message.get('tool_call_id'))
            if tc and tc['function']['name']=='read_file' and json.loads(tc['function']['arguments']).get('path')=='problem.json':
                public=json.loads(json.loads(message['content'])['content']);assert 'testcases' not in public


def run(plan, legacy, output, real=False, guard=None, max_runs=25):
    from benchmark.posthoc import judge_compatibility
    e=json.loads((legacy/'trajectories.json').read_text())
    phase7=plan.get('study')=='termination_ablation_v1'
    if phase7:
        from benchmark.termination import validate_plan as validate, SYSTEM as system_prompt
        validate(plan,e)
    else:
        validate_plan(plan,e)
        from benchmark.protocol import SYSTEM_PROMPT as system_prompt
    conditions=plan['conditions'];planned=plan['planned_units'];shared=plan['shared']
    seeds=[1,2] if phase7 else [1]
    per_group=planned//len(conditions)
    compatible=judge_compatibility(ROOT,plan['original_commit'])
    if not compatible['compatible']:raise RuntimeError('Frozen Judge cannot be reproduced: '+compatible['reason'])
    if output.exists():raise ValueError('Use a new output directory; previous experiments are never overwritten')
    output.mkdir(parents=True,mode=0o700);private=output/'private';private.mkdir(mode=0o700)
    # Private, disjoint DB; no production DB imports before installing isolation.
    session=uuid.uuid4().hex
    env={k:os.environ[k] for k in os.environ if not any(x in k.upper() for x in ('KEY','TOKEN','SECRET'))}
    env.update(MINIOJ_DATA=str(private/'data'),MINIOJ_JUDGE_BACKEND='docker',
               MINIOJ_IMAGE=plan['shared']['image_id'],MINIOJ_TEST_SESSION=session,
               PYTHONUNBUFFERED='1')
    os.environ.pop('MINIOJ_TOKEN',None)
    os.environ.update({k:v for k,v in env.items() if k.startswith('MINIOJ_')})
    from minioj import config
    from minioj.docker_backend import available,docker,remove_container
    from benchmark.harness import sandbox_policy
    from benchmark.protocol import SYSTEM_PROMPT
    from benchmark.runner import Runner
    from benchmark import storage
    from benchmark.reports import csv_text,export
    from benchmark.diagnostics import diagnostics
    if not available():raise RuntimeError('Real Docker/image required; fake-smoke does not substitute a mock Judge')
    policy=sandbox_policy()
    if phase7 and config.SOURCE_FINGERPRINT!=plan['runtime_fingerprint']:raise RuntimeError('Phase 7 runtime fingerprint drift')
    freeze={'plan_id':plan['plan_id'],'policy':policy,'judge_compatibility':compatible,
            'runtime_fingerprint':config.SOURCE_FINGERPRINT,'image_id':config.IMAGE,
            'paid':real,'authorized_max_runs':max_runs,
            'authorized_max_model_calls':guard.max_calls if guard else None,
            'authorized_observed_token_cap':guard.max_tokens if guard else None}
    (output/'runtime_freeze.json').write_text(json.dumps(freeze,indent=2))
    with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    server=None;runner=None;results={};started=time.monotonic()
    log=(private/'server.log').open('wb')
    try:
        server=subprocess.Popen([sys.executable,'-m','uvicorn','minioj.app:app','--host','127.0.0.1','--port',str(port)],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
        runner=Runner(f'http://127.0.0.1:{port}',config.TOKEN,execution_guard=guard)
        for _ in range(300):
            if server.poll() is not None:raise RuntimeError('Server startup failed')
            try:
                runner.api('GET','/health');break
            except Exception:time.sleep(.1)
        else:raise RuntimeError('Server readiness timeout')
        fixtures=json.loads((legacy/'fixtures.json').read_text());pids=[];codes={}
        for old,fixture in zip(e['manifest']['problem_snapshots'],fixtures):
            if [{k:t[k] for k in ('input','expected_output')} for t in old['testcases']]!=fixture['problem']['testcases']:raise ValueError('Reference fixture drift')
            fields=('title','description','input_description','output_description','time_limit_ms','memory_limit_mb','checker','samples','testcases','allow_workspace')
            pid=runner.api('POST','/problems',json={k:old[k] for k in fields})['id'];pids.append(pid);codes[str(pid)]=fixture['reference']
        bids={}
        for condition,definition in conditions.items():
            model={'provider':'deepseek','model':plan['shared']['model']} if real else {'provider':'fake','model':'harness-smoke','codes':codes}
            spec={'name':f"{plan['study']}-{condition}",'problems':pids,'models':[model],'seeds':seeds,
                  'protocol':'final_only','temperature':plan['shared']['temperature'],'max_tokens':plan['shared']['max_tokens'],
                  'limits':{'max_model_calls':shared['max_model_calls'] if phase7 else definition['max_model_calls'],'max_tool_calls':shared['max_tool_calls'],'max_wall_time_seconds':shared['max_wall_time_seconds']},
                  'system_prompt':system_prompt,'harness':{'condition':condition,'sandbox_policy':policy}}
            if phase7:spec['harness'].update(study=plan['study'],implementation_sha256=plan['implementation_sha256'])
            elif plan['version']==2:spec['harness']['disclosure_version']=2
            bids[condition]=runner.api('POST','/benchmarks',json=spec)['id']
        (output/'experiment_ids.json').write_text(json.dumps(bids,indent=2))
        executed=0;unit_mapping=[]
        for allocation in plan['schedule']:
            if executed>=max_runs or guard and (guard.stop_reason or guard.calls>=guard.max_calls):break
            if time.monotonic()-started>max_runs*shared['max_wall_time_seconds']+60:raise RuntimeError('Global wall deadline')
            condition=allocation['condition'];bid=bids[condition]
            public=runner.api('GET','/benchmarks/'+bid)
            unit=next(u for u in public['units'] if u['problem_id']==pids[allocation['problem_index']] and u['seed']==allocation['requested_seed'])
            if phase7:unit_mapping.append({'planned_unit_id':allocation['unit_id'],'unit_id':unit['id'],'benchmark_id':bid,'execution_ordinal':allocation['execution_ordinal'],'problem_key':allocation['problem_key'],'condition':condition,'requested_seed':unit['seed']})
            result=runner.run(bid,unit_ids=[unit['id']]);results[condition]=result;executed+=1
            current=next(u for u in result['units'] if u['id']==unit['id'])
            if guard and current['record'].get('failure_category') in ('infrastructure_failure','judge_failure'):
                guard.stop_reason=current['record']['failure_category']
        for condition,bid in bids.items():
            result=runner.api('GET','/benchmarks/'+bid);results[condition]=result
            actual=result['manifest']
            assert actual['environment_information']['source_fingerprint']==freeze['runtime_fingerprint']
            assert actual['environment_information']['image_id']==plan['shared']['image_id']
            assert actual['tool_schema']==__import__('benchmark.protocol',fromlist=['tools']).tools('final_only')
            assert actual['harness']['sandbox_policy']==policy
            if not phase7:assert actual['harness'].get('disclosure_version',1)==plan['version']
            else:
                assert actual['system_prompt']==system_prompt and actual['limits']=={k:shared[k] for k in ('max_model_calls','max_tool_calls','max_wall_time_seconds')}
                assert actual['harness']['implementation_sha256']==plan['implementation_sha256']
                assert actual['temperature']==shared['temperature'] and actual['max_tokens']==shared['max_tokens'] and actual['models']==[model]
                for original,created in zip(plan['problems'],storage.get(bid,True)['manifest']['problem_snapshots']):
                    public={k:v for k,v in created.items() if k not in ('testcases','deleted')}
                    public['id']=original['original_problem_id']
                    assert public==original['public_snapshot']
            export(result,output/condition)
            assert runner.api('GET',f'/benchmarks/{bid}/export/json')==result
            response=runner.client.get(f'/benchmarks/{bid}/export/csv');response.raise_for_status()
            assert response.text==csv_text(result)
            assert len(list(csv.DictReader(io.StringIO(response.text))))==per_group
            internal=storage.get(bid,True)
            (private/(condition+'-trajectories.json')).write_text(json.dumps(internal,ensure_ascii=False,indent=2))
            for u in internal['units']:
                for event in u['record'].get('harness_injections',[]):
                    assert event['content_sha256']==__import__('hashlib').sha256(event['content'].encode()).hexdigest()
                validate_model_history(u['record'].get('messages',[]))
        if phase7:
            from benchmark.termination_metrics import factorial
            (output/'unit_mapping.json').write_text(json.dumps(unit_mapping,indent=2))
            (output/'factorial_summary.json').write_text(json.dumps(factorial(results),indent=2))
        completed=sum(r['summary']['overall']['completed_units'] for r in results.values())
        solved=sum(r['summary']['overall']['solved'] for r in results.values())
        if not real:
            assert completed==planned and solved==planned,[(c,r['summary']['overall']) for c,r in results.items()]
            assert all(r['summary']['diagnostics']['submission_completion_rate']==1 for r in results.values())
        report={'status':'passed' if not real else 'completed' if completed==planned else 'stopped',
                'mode':'real' if real else 'fake-real-docker','plan_id':plan['plan_id'],
                'planned_units':planned,'completed_units':completed,'AC':solved,
                'model_calls':sum(u['record']['model_calls'] for r in results.values() for u in r['units']),
                'observed_tokens':guard.tokens if guard else sum(r['summary']['diagnostics']['observed_total_tokens'] for r in results.values()),
                'stop_reason':guard.stop_reason if guard else None,
                'groups':{c:r['summary'] for c,r in results.items()},
                'json_csv_consistent':True,'private_trajectories_retained':True,
                'interpretation':('Exploratory independent real Runs; descriptive differences do not establish causal or significant effects.' if real else 'Fake verifies implementation; it provides no evidence for transparency improving a real model.')}
        (output/'fake_smoke.json' if not real else output/'real_results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
        return report
    except BaseException as exc:
        failed={'status':'failed','exception_type':type(exc).__name__,'plan_id':plan['plan_id'],'groups':{}}
        for condition,bid in locals().get('bids',{}).items():
            try:failed['groups'][condition]=storage.get(bid)['summary']
            except Exception:failed['groups'][condition]={'status':'unavailable'}
        (output/'failure_report.json').write_text(json.dumps(failed,indent=2))
        raise
    finally:
        if server:
            try:os.killpg(server.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(server.pid,signal.SIGKILL);server.wait(timeout=5)
        log.close()
        names=docker(['ps','-aq','--filter','label=minioj.test-session='+session]).decode().splitlines()
        for name in names:remove_container(name)
        remaining=docker(['ps','-aq','--filter','label=minioj.test-session='+session]).strip()
        (output/'cleanup.json').write_text(json.dumps({'server_stopped':server is None or server.poll() is not None,'remaining_containers':bool(remaining)}))
        if remaining:raise RuntimeError('Sandbox cleanup incomplete')


def main():
    p=argparse.ArgumentParser();mode=p.add_mutually_exclusive_group(required=True)
    for flag in ('validate','dry-run','fake-smoke','real'):mode.add_argument('--'+flag,action='store_true')
    p.add_argument('--plan',type=Path,default=PLAN);p.add_argument('--legacy',type=Path,default=ROOT/'evidence/real-agent-20261008')
    p.add_argument('--output',type=Path);p.add_argument('--authorize-paid',action='store_true')
    p.add_argument('--plan-id');p.add_argument('--max-runs',type=int,default=0);p.add_argument('--max-model-calls',type=int,default=0);p.add_argument('--max-observed-tokens',type=int,default=0)
    a=p.parse_args()
    def interrupted(signum,frame):raise RuntimeError('study_interrupted')
    signal.signal(signal.SIGTERM,interrupted)
    plan=json.loads(a.plan.read_text());validation=validate_plan(plan)
    if json.loads((a.plan.parent/'conditions.json').read_text())!=plan['conditions']:raise ValueError('Conditions file differs from frozen plan')
    if a.validate:
        if a.output:a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(validation,indent=2))
        print(json.dumps(validation,indent=2));return
    if a.dry_run:
        print(json.dumps({'validation':validation,'schedule':plan['schedule'],'paid_calls':0},indent=2));return
    guard=authorize(a,plan) if a.real else None
    if not a.output:p.error('--output must be a new, private directory')
    result=run(plan,a.legacy,a.output,real=a.real,guard=guard,max_runs=a.max_runs if a.real else 25)
    print(json.dumps({k:v for k,v in result.items() if k!='groups'},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
