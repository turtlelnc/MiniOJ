"""A provider-independent example client; substitute any agent's generated code."""
import argparse, json, time
from pathlib import Path
import httpx
parser=argparse.ArgumentParser()
parser.add_argument('--problem',type=int,default=1)
parser.add_argument('--url',default='http://127.0.0.1:8000')
parser.add_argument('--source',type=Path)
args=parser.parse_args()
root=Path(__file__).resolve().parent.parent
client=httpx.Client(base_url=args.url,headers={'X-MiniOJ-Token':(root/'data/api-token').read_text().strip()},timeout=90,trust_env=False)
def call(method,path,**kw):
    r=client.request(method,'/api'+path,**kw);r.raise_for_status();return r.json()
run=call('POST','/agent-runs',json={'problem_id':args.problem,'source':'agent','metadata':{'model_name':'example-client','provider':'local','prompt':'Solve A+B with terminal access'}})
rid=run['id']
try:
    code=args.source.read_text() if args.source else '#include <iostream>\nint main(){long long a,b;std::cin>>a>>b;std::cout<<a+b<<"\\n";}\n'
    call('PUT',f'/agent-runs/{rid}/file',json={'path':'main.cpp','content':code})
    cmd=call('POST',f'/agent-runs/{rid}/commands',json={'command':'g++ main.cpp -O2 -std=c++17 -o main && ./main < sample.in'})
    while True:
        c=call('GET','/commands/'+cmd['command_id'])
        if c['status']=='Finished': break
        time.sleep(.2)
    print('Public sample:',json.dumps(c['result'],ensure_ascii=False))
    call('PATCH',f'/agent-runs/{rid}',json={'compile_attempts':1,'tool_calls':3,'patch_count':1})
    sid=call('POST',f'/agent-runs/{rid}/final-submit',json={'path':'main.cpp'})['submission_id']
    while True:
        s=call('GET','/submissions/'+str(sid))
        if s['status']=='Finished': break
        time.sleep(.2)
    print('Final:',json.dumps({'run_id':rid,'submission_id':sid,'verdict':s['verdict'],'passed_tests':s['passed_tests'],'total_tests':s['total_tests']}))
finally:
    call('DELETE',f'/agent-runs/{rid}/environment')
