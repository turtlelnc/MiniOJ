"""18 independent real MiniOJ Runs, no external model API required."""
import os
import csv,io,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from benchmark.runner import Runner
from minioj import config
from benchmark.reports import export
root=Path(__file__).resolve().parent.parent
evidence=Path(os.environ.get('MINIOJ_EVIDENCE_DIR',root/'evidence'))
evidence.mkdir(parents=True,exist_ok=True)
r=Runner('http://127.0.0.1:8000',config.TOKEN);pids=[];specs=[];correct={}
expressions=['a+b','a*b','(a>b?a:b)']
try:
 for i,expression in enumerate(expressions):
  def answer(a,b):return [a+b,a*b,max(a,b)][i]
  cases=[{'input':f'{a} {b}\n','expected_output':f'{answer(a,b)}\n'} for a,b in [(2,3),(-7,4),(100000,100000)]]
  p={'title':f'Benchmark acceptance {i}','description':['计算 a+b','计算 a*b','输出 a,b 中较大者'][i],'input_description':'两个整数 a,b','output_description':'一个整数','time_limit_ms':1000,'memory_limit_mb':64,'checker':'trimmed','samples':[cases[0]],'testcases':cases,'allow_workspace':True}
  pid=r.api('POST','/problems',json=p)['id'];pids.append(pid);specs.append(p)
  correct[str(pid)]='#include <iostream>\nint main(){long long a,b;std::cin>>a>>b;std::cout<<'+expression+'<<"\\n";}'
 spec={'name':'fake-3-problems-2-models-3-seeds','problems':pids,'models':[{'provider':'fake','model':'correct','codes':correct},{'provider':'fake','model':'wrong','codes':{str(p):'int main(){}' for p in pids}}],'seeds':[1,2,3],'protocol':os.environ.get('MINIOJ_BENCHMARK_PROTOCOL','final_only')}
 bid=r.api('POST','/benchmarks',json=spec)['id'];print('benchmark',bid,flush=True)
 first=r.run(bid,max_units=4);assert first['status']=='Paused';assert sum(u['status']=='Finished' for u in first['units'])==4
 before=[u for u in first['units'] if u['status']=='Finished']
 # Mutating live题目 must not change the frozen benchmark judging inputs.
 modified={**specs[0],'testcases':[{'input':'2 3\n','expected_output':'WRONG\n'}]};r.api('PUT','/problems/'+str(pids[0]),json=modified)
 r=Runner('http://127.0.0.1:8000',config.TOKEN);result=r.run(bid)
 assert result['status']=='Completed',result
 assert len(result['units'])==18
 assert all(u['status']=='Finished' for u in result['units']),[(u['ordinal'],u['record']) for u in result['units'] if u['status']!='Finished']
 groups=result['summary']['groups'];assert [g['solved'] for g in groups]==[9,0],groups
 assert [g['pass@1'] for g in groups]==[1,0],groups
 assert all(g['pass@1_denominator']==3 for g in groups)
 assert [u['run_id'] for u in result['units'][:4]]==[u['run_id'] for u in before]
 for u in result['units']:
  run=r.api('GET','/agent-runs/'+u['run_id']);assert run['status']=='Finished';assert len(run['submissions'])==(2 if spec['protocol']=='iterative' else 1);assert len([c for c in run['commands'] if c['kind']=='command'])==1
  # Check the internal checkpoint too: public export strips messages.
  from benchmark import storage
  internal=next(x for x in storage.get(bid,True)['units'] if x['id']==u['id'])
  feedback=[m for m in internal['record'].get('messages',[]) if m['role']=='tool' and '"verdict"' in m.get('content','')]
  assert len(feedback)==(1 if spec['protocol']=='iterative' else 0),feedback
 export(result,evidence/'benchmark-acceptance'/bid)
 download=r.api('GET','/benchmarks/'+bid+'/export/json')
 assert download==result
 response=r.client.get('/benchmarks/'+bid+'/export/csv');response.raise_for_status()
 rows=list(csv.DictReader(io.StringIO(response.text)));assert len(rows)==18
 assert response.text==__import__('benchmark.reports',fromlist=['csv_text']).csv_text(result)
 assert result['summary']['overall']['end_to_end_success_rate']==.5
 assert result['summary']['overall']['completed_units']==18
 assert result['summary']['overall']['final_end_to_end_success_rate']==.5
 assert result['summary']['overall']['pending_units']==0
 assert result['summary']['overall']['running_units']==0
 for row,u in zip(rows,result['units']):
  assert row['unit_id']==u['id'] and row['run_id']==u['run_id']
  assert row['status']==u['status'] and row['verdict']==u['record']['verdict']
  assert row['seed_requested']==str(u['seed'])
  usage=u['record']['usage'];assert int(row['total_tokens'])==usage['input_tokens']+usage['output_tokens']
  run=r.api('GET','/agent-runs/'+u['run_id'])
  assert run['final_submission_id']==int(row['submission_id'])
  submission=r.api('GET','/submissions/'+row['submission_id'])
  assert submission['verdict']==row['verdict']
 for g in groups:
  assert g['end_to_end_success_rate_denominator']==9
  assert g['evaluable_solve_rate']==g['solve_rate']
  assert g['end_to_end_success_rate']==g['solve_rate']
  assert g['usage_complete']
 again=Runner('http://127.0.0.1:8000',config.TOKEN).run(bid)
 assert [u['run_id'] for u in again['units']]==[u['run_id'] for u in result['units']]
 print(json.dumps({'benchmark_id':bid,'units':18,'groups':groups,'pause_resume':True,'frozen_snapshot':True,'idempotent_rerun':True},indent=2),flush=True)
finally:
 for pid in pids:r.api('DELETE','/problems/'+str(pid))
