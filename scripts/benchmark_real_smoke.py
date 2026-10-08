"""One authorized provider smoke run; environment key only, no bulk API spend."""
import json,os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from benchmark.runner import Runner
from benchmark.reports import export
root=Path(__file__).resolve().parent.parent
(root/'evidence').mkdir(exist_ok=True)
if not os.environ.get('DEEPSEEK_API_KEY'):
 print('SKIPPED: DEEPSEEK_API_KEY absent');raise SystemExit(0)
r=Runner('http://127.0.0.1:8000',(root/'data/api-token').read_text().strip())
p={'title':'DeepSeek benchmark smoke: absolute difference','description':'给定两个整数 a,b，输出它们差的绝对值。绝对值不超过 10^12。','input_description':'两个整数','output_description':'一个非负整数','time_limit_ms':1000,'memory_limit_mb':64,'allow_workspace':True,'samples':[{'input':'3 8\n','expected_output':'5\n'}],'testcases':[{'input':'3 8\n','expected_output':'5\n'},{'input':'1000000000000 -1000000000000\n','expected_output':'2000000000000\n'},{'input':'-5 -5\n','expected_output':'0\n'}]}
pid=r.api('POST','/problems',json=p)['id']
try:
 bid=r.api('POST','/benchmarks',json={'name':'deepseek-single-unit-smoke','problems':[pid],'models':[{'provider':'deepseek','model':'deepseek-flash'}],'seeds':[1],'protocol':'final_only','max_tokens':2048,'limits':{'max_model_calls':8,'max_tool_calls':20,'max_wall_time_seconds':180}})['id'];print('benchmark',bid,flush=True)
 result=r.run(bid);export(result,root/'evidence'/'benchmark-real'/bid)
 print(json.dumps({'id':bid,'status':result['status'],'units':[{k:v for k,v in u['record'].items() if k!='messages'} for u in result['units']]},ensure_ascii=False,indent=2))
finally:r.api('DELETE','/problems/'+str(pid))
