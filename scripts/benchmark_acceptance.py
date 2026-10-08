"""18 independent real MiniOJ Runs, no external model API required."""
import csv,io,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from benchmark.runner import Runner
from benchmark.reports import export
root=Path(__file__).resolve().parent.parent
(root/'evidence').mkdir(exist_ok=True)
r=Runner('http://127.0.0.1:8000',(root/'data/api-token').read_text().strip());pids=[];specs=[];correct={}
expressions=['a+b','a*b','(a>b?a:b)']
try:
 for i,expression in enumerate(expressions):
  def answer(a,b):return [a+b,a*b,max(a,b)][i]
  cases=[{'input':f'{a} {b}\n','expected_output':f'{answer(a,b)}\n'} for a,b in [(2,3),(-7,4),(100000,100000)]]
  p={'title':f'Benchmark acceptance {i}','description':['计算 a+b','计算 a*b','输出 a,b 中较大者'][i],'input_description':'两个整数 a,b','output_description':'一个整数','time_limit_ms':1000,'memory_limit_mb':64,'checker':'trimmed','samples':[cases[0]],'testcases':cases,'allow_workspace':True}
  pid=r.api('POST','/problems',json=p)['id'];pids.append(pid);specs.append(p)
  correct[str(pid)]='#include <iostream>\nint main(){long long a,b;std::cin>>a>>b;std::cout<<'+expression+'<<"\\n";}'
 spec={'name':'fake-3-problems-2-models-3-seeds','problems':pids,'models':[{'provider':'fake','model':'correct','codes':correct},{'provider':'fake','model':'wrong','codes':{str(p):'int main(){}' for p in pids}}],'seeds':[1,2,3],'protocol':'final_only'}
 bid=r.api('POST','/benchmarks',json=spec)['id'];print('benchmark',bid,flush=True)
 first=r.run(bid,max_units=4);assert first['status']=='Paused';assert sum(u['status']=='Finished' for u in first['units'])==4
 before=[u for u in first['units'] if u['status']=='Finished']
 # Mutating live题目 must not change the frozen benchmark judging inputs.
 modified={**specs[0],'testcases':[{'input':'2 3\n','expected_output':'WRONG\n'}]};r.api('PUT','/problems/'+str(pids[0]),json=modified)
 r=Runner('http://127.0.0.1:8000',(root/'data/api-token').read_text().strip());result=r.run(bid)
 assert result['status']=='Completed',result
 assert len(result['units'])==18
 assert all(u['status']=='Finished' for u in result['units']),[(u['ordinal'],u['record']) for u in result['units'] if u['status']!='Finished']
 groups=result['summary']['groups'];assert [g['solved'] for g in groups]==[9,0],groups
 assert [g['pass@1'] for g in groups]==[1,0],groups
 assert all(g['pass@1_denominator']==3 for g in groups)
 assert [u['run_id'] for u in result['units'][:4]]==[u['run_id'] for u in before]
 for u in result['units']:
  run=r.api('GET','/agent-runs/'+u['run_id']);assert run['status']=='Finished';assert len(run['submissions'])==1;assert len([c for c in run['commands'] if c['kind']=='command'])==1
  assert all(m['role']!='tool' or '"verdict"' not in m.get('content','') for m in u['record'].get('messages',[]))
 export(result,root/'evidence'/'benchmark-acceptance'/bid)
 assert len(list(csv.DictReader(io.StringIO(r.api('GET','/benchmarks/'+bid+'/export/json') and __import__('benchmark.reports',fromlist=['csv_text']).csv_text(result)))))==18
 again=Runner('http://127.0.0.1:8000',(root/'data/api-token').read_text().strip()).run(bid)
 assert [u['run_id'] for u in again['units']]==[u['run_id'] for u in result['units']]
 print(json.dumps({'benchmark_id':bid,'units':18,'groups':groups,'pause_resume':True,'frozen_snapshot':True,'idempotent_rerun':True},indent=2),flush=True)
finally:
 for pid in pids:r.api('DELETE','/problems/'+str(pid))
