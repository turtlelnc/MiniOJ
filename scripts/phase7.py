"""Offline by default: Phase 7 validation and explicitly guarded future execution."""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import sys
import signal
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from benchmark.termination import (CONDITIONS, LIMITS, SYSTEM, REMINDER, prompt_preview,
                                   validate_plan, STUDY)
from benchmark.harness import sha
PLAN=ROOT/'benchmark/experiments'/STUDY/'execution_plan.json'


def load_plan(path):
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=(path.parent/'manifest.sha256').read_text().strip():
        raise ValueError('Frozen manifest checksum mismatch')
    plan=json.loads(raw);validate_plan(plan)
    if json.loads((path.parent/'conditions.json').read_text())!=CONDITIONS:raise ValueError('Conditions drift')
    return plan


def compare_prompts(plan):
    comparisons=[]
    for call in range(1,7):
        tool_used=(call-1)*3;wall=300-(call-1)*10
        messages={c:prompt_preview(c,plan['sandbox_policy'],call,tool_used,wall,plan['problems'][0]['public_snapshot']) for c in CONDITIONS}
        common=messages['A'][1]['content']
        for c in CONDITIONS:
            text=messages[c][1]['content'];parts=text.split('\n\n')
            assert parts[0]==common and messages[c][0]=={'role':'system','content':SYSTEM}
            assert ('[Runtime Budget]' in text)==CONDITIONS[c]['budget_visible']
            assert text.count('[Task Completion Reminder]')==int(CONDITIONS[c]['submit_reminder'])
            if CONDITIONS[c]['budget_visible']:
                budget_section=next(part for part in parts if part.startswith('[Runtime Budget]'))
                assert 'final_submit' not in budget_section and 'submit' not in budget_section.lower()
                budget=json.loads(budget_section.splitlines()[1])
                assert budget['model_responses_remaining_including_current']==7-call
                assert budget['tool_remaining']==50-tool_used
            if CONDITIONS[c]['submit_reminder']:assert parts[-1]==REMINDER
        comparisons.append({'model_call':call,'simulated_tool_calls':tool_used,'remaining_wall':wall,
                            'messages':messages,'message_sha256':{c:sha(m) for c,m in messages.items()},
                            'diff_from_A':{c:'\n'.join(difflib.unified_diff(common.splitlines(),messages[c][1]['content'].splitlines(),fromfile='A',tofile=c,lineterm='')) for c in 'BCD'}})
    return {'status':'passed','role':'ephemeral system message after initial system, before unchanged history',
            'counter_rule':'Current model call already counted; remaining responses include current. Tools count before dispatch.',
            'rounds':comparisons,'paid_calls':0}


def dry_run(plan):
    from benchmark.adapters.fake import FakeModelAdapter
    from benchmark.protocol import tools
    from benchmark.metrics import summary
    from benchmark.termination_metrics import factorial,trajectory
    from benchmark.reports import csv_text
    import csv,io
    experiments={c:{'manifest':{'seeds':[1,2],'models':[{'provider':'fake','model':'phase7-dry'}],
                              'protocol':'final_only','harness':{'study':STUDY,'condition':c}},'units':[]} for c in CONDITIONS}
    for allocation in plan['schedule']:
        c=allocation['condition'];r={'model_calls':0,'tool_calls':0,'usage':{'input_tokens':0,'output_tokens':0},
                                    'final_submit_attempted':False,'final_submission_completed':False,'tool_events':[]}
        messages=[{'role':'system','content':SYSTEM},{'role':'user','content':'{"id":123}'}]
        model=FakeModelAdapter({'model':'phase7-dry','codes':{'123':'int main(){}'}})
        for call in range(1,7):
            from benchmark.termination import request_messages
            r['model_calls']+=1
            request=request_messages(messages,{'harness':{'condition':c,'sandbox_policy':plan['sandbox_policy']},'limits':LIMITS},r,{},300-call)
            reply=model.complete(request,tools('final_only'),0,allocation['requested_seed'],4096,60,{'id':123})
            messages.append(reply.message);tc=reply.message['tool_calls'][0];name=tc['function']['name'];r['tool_calls']+=1
            for key in r['usage']:r['usage'][key]+=reply.usage[key]
            if name=='final_submit':r.update(final_submit_attempted=True,final_submission_completed=True,verdict='AC');break
            messages.append({'role':'tool','tool_call_id':tc['id'],'content':'{}'})
        r.update(trajectory(r,LIMITS))
        # No live workspace/source snapshot was acquired in a dry-run.
        r.update(termination_code=None,code_change_observation='dry-run: no filesystem execution')
        experiments[c]['units'].append({'id':allocation['unit_id'],'problem_id':allocation['original_problem_id'],
                                       'model_index':0,'seed':allocation['requested_seed'],'status':'Finished','run_id':None,'record':r})
    for e in experiments.values():
        e['summary']=summary(e)
        rows=list(csv.DictReader(io.StringIO(csv_text(e))))
        assert [row['unit_id'] for row in rows]==[u['id'] for u in e['units']]
        assert all(row['status']=='Finished' and row['verdict']=='AC' for row in rows)
    stats=factorial(experiments)
    assert stats['complete'] and all(g['counts']['solved']==10 for g in stats['groups'].values())
    assert all(g['diagnostics']['valid_code_unknown_count']==10 for g in stats['groups'].values())
    return {'status':'passed','planned_units':40,'constructed_units':40,'simulation_only':True,
            'fake_model_calls':160,'paid_calls':0,'snapshots':'unavailable: no workspace executed',
            'factorial':stats,'schedule':plan['schedule']}


def analyze(directory):
    from benchmark.termination_metrics import factorial
    from benchmark.posthoc import recover
    experiments={};posthoc={};rows=[]
    for c in CONDITIONS:
        e=json.loads((directory/c/'results.json').read_text())
        if e['manifest']['harness'].get('study')!=STUDY or e['manifest']['harness']['condition']!=c:
            raise ValueError('Wrong study/condition')
        experiments[c]=e
        path=directory/(c+'-posthoc.json')
        if path.exists():
            private=directory/'private'/(c+'-trajectories.json')
            internal=json.loads(private.read_text()) if private.exists() else None
            for observation in json.loads(path.read_text())['results']:
                if observation['unit_id'] not in {u['id'] for u in e['units']}:raise ValueError('Posthoc unit mismatch')
                verified=observation.get('status')=='verified'
                if verified:
                    if internal is None:observation={**observation,'status':'unknown','verdict':None,'reason':'private_provenance_unavailable'}
                    else:
                        unit=next(u for u in internal['units'] if u['id']==observation['unit_id'])
                        source=recover(unit)
                        problem=next(p for p in internal['manifest']['problem_snapshots'] if p['id']==unit['problem_id'])
                        tests_hash=hashlib.sha256(json.dumps(problem['testcases'],sort_keys=True).encode()).hexdigest()
                        if (source.get('status')!='available' or source.get('sha256')!=observation.get('source_sha256')
                            or tests_hash!=observation.get('tests_sha256')
                            or internal['manifest']['environment_information']['image_id']!=observation.get('image_id')
                            or not observation.get('judge_compatibility',{}).get('compatible')):
                            observation={**observation,'status':'unknown','verdict':None,'reason':'posthoc_provenance_mismatch'}
                posthoc[observation['unit_id']]=observation
        for u in e['units']:
            r=u['record'];observation=posthoc.get(u['id'],{})
            rows.append({'condition':c,'unit_id':u['id'],'status':u['status'],
                         **{key:r.get(key) for key in ('model_calls','tool_calls','last_code_change_model_call',
                            'model_calls_after_last_code_change','tool_calls_after_last_code_change',
                            'remaining_calls_at_last_code_change','final_submit_attempted','final_submit_completed','terminal_reason')},
                         'posthoc_rejudge_verdict':observation.get('verdict') if observation.get('status')=='verified' else None})
    return {'factorial':factorial(experiments,posthoc),'trajectory_diagnostics':rows,
            'original_records_modified':False,'paid_calls':0}


def main():
    p=argparse.ArgumentParser();g=p.add_mutually_exclusive_group(required=True)
    for mode in ('validate','compare-prompts','dry-run','fake-smoke','real','analyze'):g.add_argument('--'+mode,action='store_true')
    p.add_argument('--evidence',type=Path)
    p.add_argument('--plan',type=Path,default=PLAN);p.add_argument('--output',type=Path)
    p.add_argument('--legacy',type=Path,default=ROOT/'evidence/real-agent-20261008')
    p.add_argument('--authorize-paid',action='store_true');p.add_argument('--plan-id')
    p.add_argument('--max-runs',type=int,default=0);p.add_argument('--max-model-calls',type=int,default=0)
    p.add_argument('--max-observed-tokens',type=int,default=0)
    a=p.parse_args()
    def interrupted(signum,frame):raise RuntimeError('study_interrupted')
    signal.signal(signal.SIGTERM,interrupted)
    plan=load_plan(a.plan)
    if a.real:
        from benchmark.ablation import authorize
        guard=authorize(a,plan)  # Checked before adapter construction/credential access.
    else:guard=None
    if a.validate:result=validate_plan(plan)
    elif a.compare_prompts:result=compare_prompts(plan)
    elif a.dry_run:result=dry_run(plan)
    elif a.analyze:
        if not a.evidence:p.error('--analyze requires --evidence')
        result=analyze(a.evidence)
    else:
        if not a.output:p.error('--output must be a new private directory')
        from scripts.harness_ablation import run
        result=run(plan,a.legacy,a.output,real=a.real,guard=guard,max_runs=a.max_runs if a.real else 40)
    if a.output and not (a.fake_smoke or a.real):
        a.output.parent.mkdir(parents=True,exist_ok=True)
        with a.output.open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps(result if not(a.fake_smoke or a.real) else {k:v for k,v in result.items() if k!='groups'},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
