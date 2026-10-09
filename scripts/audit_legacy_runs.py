"""Read only private legacy evidence; output hashes/diagnostics, never test text."""
import argparse
import hashlib
import json
import sys
import sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from benchmark.posthoc import recover, code_sha, _result


def audit(directory, review_file=None):
    directory=Path(directory); path=directory/'trajectories.json'
    if not path.exists():return {'status':'unavailable','reason':'legacy_trajectories_missing','runs':[]}
    e=json.loads(path.read_text()); m=e['manifest']; post_path=directory/'posthoc-audit.json'
    post={r['ordinal']:r for r in json.loads(post_path.read_text())} if post_path.exists() else {}
    review=json.loads(Path(review_file).read_text()) if review_file and Path(review_file).exists() else {}
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    reviewed=review.get('sources',{}) if review.get('trajectories_sha256')==digest else {}
    rows=[]
    for u in e['units']:
        r=u['record']; msgs=r.get('messages',[]); calls={}; results={}; terminals=[]; last_compile=None
        for message in msgs:
            for tc in message.get('tool_calls',[]):calls[tc['id']]=tc
            if message.get('role')=='tool':results[message.get('tool_call_id')]=_result(message)
        for cid,tc in calls.items():
            if tc['function']['name']!='terminal':continue
            args=json.loads(tc['function']['arguments']); result=results.get(cid) or {}; command=args['command']
            terminals.append({'command_sha256':code_sha(command),'returncode':result.get('returncode'),
                              'reason':result.get('reason'),'file_limit_error':any(x in (result.get('stderr','')+result.get('stdout','')) for x in ('File too large','File size limit exceeded'))})
            # Explicit gated compilation success is high-confidence, not an
            # extracted compiler exit status: shell scripts can hide failures.
            if 'g++' in command and 'main.cpp' in command and '&&' in command and result.get('returncode')==0 and not result.get('reason'):
                last_compile={'tool_call_id':cid,'command_sha256':code_sha(command),'evidence':'gated compile chain exit 0; compiler status not separately logged','confidence':'high_inference'}
        source=recover(u,reviewed.get(str(u['ordinal']))); p=post.get(u['ordinal'],{})
        legacy_db=directory/'data/minioj.sqlite3'
        if u['status']=='Finished' and r.get('submission_id') and legacy_db.exists():
            with sqlite3.connect(legacy_db.resolve().as_uri()+'?mode=ro',uri=True) as c:
                submitted=c.execute('SELECT source_code,run_id FROM submissions WHERE id=?',(r['submission_id'],)).fetchone()
            if submitted and submitted[1]==u['run_id']:
                source={'status':'available','sha256':code_sha(submitted[0]),'provenance':'immutable_original_final_submission_source'}
        available=source['status']=='available'
        final_called=any(t['function']['name']=='final_submit' for t in calls.values())
        usage=r.get('usage') or {}
        row={'unit_id':u['id'],'run_id':u['run_id'],'ordinal':u['ordinal'],'problem_id':u['problem_id'],
             'requested_seed':u['seed'],'effective_seed':r.get('seed_effective'),
             'original_verdict':r.get('verdict'),'original_status':u['status'],
             'termination_category':r.get('failure_category'),'termination_reason':r.get('error'),
             'model_calls':r.get('model_calls'),'tool_calls':r.get('tool_calls'),
             'input_tokens':usage.get('input_tokens'),'output_tokens':usage.get('output_tokens'),
             'last_code_sha256':source.get('sha256'),'code_available_at_termination':True if available else None,
             'source_provenance':source.get('provenance'),'posthoc_rejudge_verdict':p.get('posthoc_verdict') if available else None,
             'posthoc_evidence':'legacy independent report; original rejudge ID/timestamp/fingerprint not recorded' if p.get('posthoc_verdict') else None,
             'last_successful_compile':last_compile,'final_submit_called':final_called,
             'remaining_budget_at_termination':{'model':max(0,m['limits']['max_model_calls']-r['model_calls']),'tool':max(0,m['limits']['max_tool_calls']-r['tool_calls'])},
             'sandbox_limit_errors':sum(t['file_limit_error'] for t in terminals),'terminal_observations':terminals,
             'confirmed':['original terminal category and counters']+(['file-size error observed before termination'] if any(t['file_limit_error'] for t in terminals) else []),
             'high_confidence_inference':['source formed before budget exhaustion and later commands do not modify main.cpp'] if available else [],
             'unconfirmed':['Whether awareness would cause earlier final_submit; counterfactual not observed',
                            'Whether the file error prevented submission rather than merely consumed remaining calls']}
        rows.append(row)
    return {'status':'available','experiment_id':e['id'],'trajectories_sha256':digest,
            'original_e2e_success':sum(u['status']=='Finished' and u['record'].get('verdict')=='AC' for u in e['units']),
            'independent_runs':len(rows),'legacy_posthoc_ac':sum(x['posthoc_rejudge_verdict']=='AC' for x in rows),
            'original_model_calls':sum(r['model_calls'] for r in rows),'original_tool_calls':sum(r['tool_calls'] for r in rows),
            'observed_tokens':sum((r['input_tokens'] or 0)+(r['output_tokens'] or 0) for r in rows),
            'manifest_sha256':code_sha(json.dumps(m,sort_keys=True)),
            'image_id':m['environment_information'].get('image_id'),
            'judge_fingerprint':m['environment_information'].get('source_fingerprint'),
            'runs':rows}


def main():
    p=argparse.ArgumentParser();p.add_argument('--legacy',type=Path,default=ROOT/'evidence/real-agent-20261008');p.add_argument('--output',type=Path,required=True)
    p.add_argument('--review',type=Path,default=ROOT/'benchmark/experiments/harness_ablation_v1/legacy_review.json');a=p.parse_args()
    result=audit(a.legacy,a.review);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2));print(result['status'],len(result['runs']))
if __name__=='__main__':main()
