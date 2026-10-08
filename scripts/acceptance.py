"""Real HTTP + Linux container acceptance; leaves results as audit evidence."""
import os
import asyncio, json, time, sys
from pathlib import Path
import httpx, websockets
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
EVIDENCE=Path(os.environ.get('MINIOJ_EVIDENCE_DIR',ROOT/'evidence'))
from minioj import config
EVIDENCE.mkdir(parents=True,exist_ok=True)
TOKEN=config.TOKEN
c=httpx.Client(base_url='http://127.0.0.1:8000/api',headers={'X-MiniOJ-Token':TOKEN},timeout=90,trust_env=False)
report=[]
def call(method,path,**kw):
    r=c.request(method,path,**kw);r.raise_for_status();return r.json()
def wait_submission(sid):
    end=time.monotonic()+90
    while time.monotonic()<end:
        s=call('GET',f'/submissions/{sid}')
        if s['status']=='Finished': return s
        time.sleep(.2)
    raise AssertionError('Submission timed out')
def command(rid,cmd,timeout=30000):
    cid=call('POST',f'/agent-runs/{rid}/commands',json={'command':cmd,'timeout_ms':timeout})['command_id']
    end=time.monotonic()+timeout/1000+30
    while time.monotonic()<end:
        r=call('GET','/commands/'+cid)
        if r['status']=='Finished': return r['result']
        time.sleep(.2)
    raise AssertionError('Command timed out')
def record(name,**details):
    report.append({'test':name,'passed':True,**details});print(name,'OK',flush=True)

GOOD='#include <iostream>\nint main(){long long a,b;std::cin>>a>>b;std::cout<<a+b<<"\\n";}'
problem={'allow_workspace':True,'title':'Acceptance A+B','description':'sum','input_description':'two integers','output_description':'sum','time_limit_ms':500,'memory_limit_mb':64,'samples':[{'input':'1 2\n','expected_output':'3\n'}],'testcases':[{'input':'1 2\n','expected_output':'3\n'},{'input':'-5 8\n','expected_output':'3\n'}]}
def main():
    assert httpx.get('http://127.0.0.1:8000/api/problems',trust_env=False).status_code==401
    assert c.get('/problems',headers={'Origin':'http://evil.test'}).status_code==403
    assert c.get('/problems',headers={'Host':'evil.test'}).status_code==403
    record('auth_origin_host')
    pid=call('POST','/problems',json=problem)['id']
    public=call('GET',f'/problems/{pid}');assert 'testcases' not in public
    record('create_problem_hidden_data',problem_id=pid)
    programs=[('AC',GOOD),('WA','int main(){}'),('TLE','int main(){while(true){}}'),('RE','#include <cstdlib>\nint main(){abort();}'),('CE','not c++'),('output_limit','#include <cstdio>\nint main(){while(true)puts("xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx");}'),('MLE','#include <cstdlib>\n#include <cstring>\n#include <unistd.h>\nint main(){while(1){char*p=(char*)malloc(1048576);if(!p)abort();memset(p,1,1048576);usleep(1000);}}')]
    for expected,code in programs:
        sid=call('POST','/submissions',json={'problem_id':pid,'source_code':code})['submission_id']
        s=wait_submission(sid)
        assert s['verdict']==('RE' if expected=='output_limit' else expected),s
        if expected=='output_limit': assert s['reason']=='output_limit'
        assert 'snapshot' not in s and all('stdout' not in x for x in s['results'])
        record('docker_judge_'+expected,submission_id=sid,runtime_ms=s['runtime_ms'],memory_kb=s['memory_kb'])
    run=call('POST','/agent-runs',json={'problem_id':pid,'metadata':{'model_name':'acceptance','provider':'local'}});rid=run['id']
    try:
        fs=call('GET',f'/agent-runs/{rid}/files');assert any(f['path']=='main.cpp' for f in fs['files'])
        call('PUT',f'/agent-runs/{rid}/file',json={'path':'main.cpp','content':GOOD})
        sample=command(rid,'g++ main.cpp -O2 -std=c++17 -o main && ./main < sample.in')
        assert sample['returncode']==0 and sample['stdout']=='3\n',sample
        record('agent_files_compile_public_sample',run_id=rid)
        isolated=command(rid,'id; cat /proc/net/route; test ! -e /var/run/docker.sock; test ! -e /Users; test ! -e /workspace/testcases; touch /etc/minioj-no-write 2>/dev/null; test $? -ne 0')
        assert isolated['returncode']==0 and 'uid=1000' in isolated['stdout'],isolated
        record('nonroot_network_rootfs_no_mounts')
        cmd=command(rid,'ln -s /etc/passwd forbidden; ln -s /tmp linked; mkdir -p nest; ln -s /etc nest/link')
        for path in ('../etc/passwd','/etc/passwd','forbidden','linked/new','nest/link/passwd'):
            assert c.get(f'/agent-runs/{rid}/file',params={'path':path}).status_code>=400,path
            assert c.put(f'/agent-runs/{rid}/file',json={'path':path,'content':'bad'}).status_code>=400,path
        record('path_traversal_symlink_read_write')
        timeout=command(rid,'sleep 10',100);assert timeout['reason']=='timeout',timeout
        output=command(rid,'yes x',5000);assert output['reason']=='output_limit',output
        record('command_timeout_output_limit')
        asyncio.run(terminal_test(rid))
        record('websocket_interactive_terminal')
        call('PATCH',f'/agent-runs/{rid}',json={'token_input':100,'token_output':30,'tool_calls':8,'compile_attempts':1})
        sid=call('POST',f'/agent-runs/{rid}/final-submit',json={'path':'main.cpp'})['submission_id']
        assert wait_submission(sid)['verdict']=='AC'
        assert c.post(f'/agent-runs/{rid}/final-submit',json={'path':'main.cpp'}).status_code==409
        run=call('GET',f'/agent-runs/{rid}');assert run['status']=='Finished' and run['final_submission_id']==sid
        assert c.get(f'/agent-runs/{rid}/files').status_code==409
        record('final_snapshot_judge_cleanup',run_id=rid,submission_id=sid)
    finally: call('DELETE',f'/agent-runs/{rid}/environment')
    iterative=call('POST','/agent-runs',json={'problem_id':pid,'environment':False,'feedback_policy':'iterative','metadata':{'model_name':'iterative'}});rid=iterative['id']
    for code,v in [('int main(){}','WA'),(GOOD,'AC')]:
        sid=call('POST',f'/agent-runs/{rid}/submissions',json={'source_code':code})['submission_id'];assert wait_submission(sid)['verdict']==v
    r=call('POST',f'/agent-runs/{rid}/finish',json={'final_submission_id':sid});assert len(r['submissions'])==2
    record('run_multiple_attempts_final_link')
    edited={**problem,'title':'Edited Acceptance'};call('PUT',f'/problems/{pid}',json=edited)
    assert call('GET',f'/problems/{pid}')['title']==edited['title']
    call('DELETE',f'/problems/{pid}');assert c.get(f'/problems/{pid}').status_code==404
    assert call('GET',f'/submissions/{sid}')['verdict']=='AC'
    record('edit_soft_delete_history')
    (EVIDENCE/'acceptance.json').write_text(json.dumps(report,indent=2,ensure_ascii=False))

async def terminal_test(rid):
    async with websockets.connect(f'ws://127.0.0.1:8000/api/agent-runs/{rid}/terminal',additional_headers={'X-MiniOJ-Token':TOKEN},proxy=None) as ws:
        await ws.send(json.dumps({'type':'input','data':'printf "PTY_%s\\n" OK\r'}))
        received=''
        end=time.monotonic()+10
        while 'PTY_OK' not in received and time.monotonic()<end:
            received+=await asyncio.wait_for(ws.recv(),5)
        assert 'PTY_OK' in received,received
        await ws.send(json.dumps({'type':'input','data':'exit\r'}))
    # Wait until cleanup releases the environment's terminal reservation.
    for _ in range(50):
        r=c.get(f'/agent-runs/{rid}').json()
        if all(cmd['status']=='Finished' for cmd in r['commands'] if cmd['kind']=='terminal'): return
        time.sleep(.1)
    raise AssertionError('Terminal cleanup did not release workspace')
if __name__=='__main__': main()
