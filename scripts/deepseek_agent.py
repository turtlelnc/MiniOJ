"""Bounded real model -> MiniOJ tool loop. Key from env or --key-stdin, never logged."""
import argparse,json,os,sys,time
from pathlib import Path
import httpx
parser=argparse.ArgumentParser();parser.add_argument('--key-stdin',action='store_true');parser.add_argument('--model',default='deepseek-flash');args=parser.parse_args()
key=sys.stdin.readline().strip() if args.key_stdin else os.environ['DEEPSEEK_API_KEY']
root=Path(__file__).resolve().parent.parent
local=httpx.Client(base_url='http://127.0.0.1:8000/api',headers={'X-MiniOJ-Token':(root/'data/api-token').read_text().strip()},trust_env=False,timeout=60)
remote=httpx.Client(base_url='https://api.deepseek.com',headers={'Authorization':'Bearer '+key},timeout=60)
def api(method,path,**kwargs):
 r=local.request(method,path,**kwargs);r.raise_for_status();return r.json()
def wait(path):
 end=time.monotonic()+60
 while time.monotonic()<end:
  r=api('GET',path)
  if r['status']=='Finished':return r
  time.sleep(.15)
 raise TimeoutError(path)
def tool(name,properties,required):return {'type':'function','function':{'name':name,'description':name,'parameters':{'type':'object','properties':properties,'required':required,'additionalProperties':False}}}
tools=[tool('read_file',{'path':{'type':'string'}},['path']),tool('write_file',{'path':{'type':'string'},'content':{'type':'string'}},['path','content']),tool('terminal',{'command':{'type':'string'}},['command']),tool('final_submit',{},[])]
fixture={'title':'Agent API verification: range sums','description':'给定 n 个整数和 q 次查询。每次查询给出 l,r（从 1 开始，闭区间），输出区间元素和。n,q <= 100000，元素绝对值 <= 1000000000。','input_description':'首行 n q；第二行 n 个整数；接下来 q 行 l r。','output_description':'每个查询输出一行区间和，使用 64 位整数。','time_limit_ms':1000,'memory_limit_mb':128,'checker':'trimmed','allow_workspace':True,'samples':[{'input':'5 3\n1 -2 3 4 5\n1 5\n2 4\n3 3\n','expected_output':'11\n5\n3\n'}],'testcases':[]}
for arr,qs in [([1,-2,3,4,5],[(1,5),(2,4),(3,3)]),([1000000000]*10,[(1,10),(4,9)]),([-7],[(1,1)]),([i%19-9 for i in range(30000)],[(1,30000),(199,29001),(30000,30000)])]:
 inp=f'{len(arr)} {len(qs)}\n'+' '.join(map(str,arr))+'\n'+''.join(f'{l} {r}\n' for l,r in qs)
 fixture['testcases'].append({'input':inp,'expected_output':''.join(str(sum(arr[l-1:r]))+'\n' for l,r in qs)})
fixture['samples']=[fixture['testcases'][0].copy()]
pid=rid=None;report={'model_requested':args.model,'events':[],'usage':{'prompt_tokens':0,'completion_tokens':0}};start=time.monotonic()
try:
 # Check provider before creating test data.
 r=remote.get('/models');r.raise_for_status();ids=[m['id'] for m in r.json()['data']]
 if args.model not in ids:args.model='deepseek-chat' if 'deepseek-chat' in ids else ids[0]
 report['model_requested']=args.model
 pid=api('POST','/problems',json=fixture)['id']
 rid=api('POST','/agent-runs',json={'problem_id':pid,'source':'agent','metadata':{'provider':'deepseek','model_name':args.model}})['id'];report.update(problem_id=pid,run_id=rid)
 public=api('GET',f'/problems/{pid}')
 messages=[{'role':'system','content':'Solve the algorithm problem using the isolated Linux terminal tools. Read problem.json, write your C++17 solution to main.cpp, compile and test by redirecting sample.in using terminal, then call final_submit exactly once. Hidden tests are unavailable. Do not merely output code.'},{'role':'user','content':json.dumps(public,ensure_ascii=False)}]
 for turn in range(16):
  r=remote.post('/chat/completions',json={'model':args.model,'messages':messages,'tools':tools,'max_tokens':4096,'thinking':{'type':'disabled'}});r.raise_for_status();d=r.json();report['model_returned']=d['model']
  for k in report['usage']:report['usage'][k]+=d.get('usage',{}).get(k,0)
  m=d['choices'][0]['message'];messages.append(m);calls=m.get('tool_calls') or []
  if not calls:messages.append({'role':'user','content':'Please use tools to solve and final_submit.'});continue
  done=False
  for tc in calls:
   name=tc['function']['name'];a=json.loads(tc['function']['arguments']);event={'tool':name,'arguments':a};report['events'].append(event);print('tool:',name,flush=True)
   try:
    if name=='read_file':result=api('GET',f'/agent-runs/{rid}/file',params=a)
    elif name=='write_file':result=api('PUT',f'/agent-runs/{rid}/file',json=a)
    elif name=='terminal':
     cid=api('POST',f'/agent-runs/{rid}/commands',json={**a,'timeout_ms':30000})['command_id'];result=wait('/commands/'+cid)['result']
    elif name=='final_submit':
     sid=api('POST',f'/agent-runs/{rid}/final-submit',json={'path':'main.cpp'})['submission_id'];s=wait('/submissions/'+str(sid));result={k:s[k] for k in ('verdict','passed_tests','total_tests','reason')};report.update(submission_id=sid,result=result);done=True
    else:raise ValueError('Unknown tool')
   except Exception as e:result={'error':type(e).__name__}
   event['result']=result;messages.append({'role':'tool','tool_call_id':tc['id'],'content':json.dumps(result,ensure_ascii=False)})
   if done:break
  if done:break
 else:raise RuntimeError('Agent exceeded 16 model calls')
 assert report.get('result',{}).get('verdict')=='AC',report.get('result')
 assert any(e['tool']=='terminal' for e in report['events'])
 print(json.dumps({k:v for k,v in report.items() if k!='events'},ensure_ascii=False),flush=True)
finally:
 report['wall_time_seconds']=round(time.monotonic()-start,2)
 if rid:
  api('PATCH',f'/agent-runs/{rid}',json={'token_input':report['usage']['prompt_tokens'],'token_output':report['usage']['completion_tokens'],'tool_calls':len(report['events']),'wall_time':report['wall_time_seconds']})
  api('DELETE',f'/agent-runs/{rid}/environment')
 if pid:api('DELETE',f'/problems/{pid}')
 (root/'evidence'/'deepseek-agent-api.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
