"""Additional container resource, daemon cleanup, and expiry verification."""
import os
import json, subprocess, sys, time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import httpx
from minioj import db, config
from minioj.docker_backend import DockerJudgeSession,docker
root=Path(__file__).resolve().parent.parent
evidence=Path(os.environ.get('MINIOJ_EVIDENCE_DIR',root/'evidence'))
evidence.mkdir(parents=True,exist_ok=True)
c=httpx.Client(base_url='http://127.0.0.1:8000/api',headers={'X-MiniOJ-Token':config.TOKEN},timeout=90,trust_env=False)
report=[]
def call(method,path,**kw):
    r=c.request(method,path,**kw);r.raise_for_status();return r.json()
def cmd(rid,command,timeout_ms=5000):
    cid=call('POST',f'/agent-runs/{rid}/commands',json={'command':command,'timeout_ms':timeout_ms})['command_id']
    for _ in range(150):
        r=call('GET','/commands/'+cid)
        if r['status']=='Finished': return r['result']
        time.sleep(.1)
    raise AssertionError('command timeout')
def record(name,**fields):
    report.append({'test':name,'passed':True,**fields});print(name,'OK',flush=True)

with DockerJudgeSession() as session:
    compiled=session.compile('#include <unistd.h>\n#include <iostream>\nint main(){if(fork()==0){setsid();if(fork()==0){while(1){}}_exit(0);}std::cout<<3<<"\\n";}')
    assert compiled.returncode==0,compiled
    result=session.run(b'',500,64);assert result.stdout==b'3\n',result
    processes=json.loads(docker(['exec',session.name,'python3','-c','import os,json;print(json.dumps([int(p) for p in os.listdir("/proc") if p.isdigit() and int(p) not in (1,os.getpid())]))']))
    assert not processes,processes
    record('daemonized_fork_cleanup')

pid=call('POST','/problems',json={'title':'Resource acceptance fixture','allow_workspace':True,'testcases':[{'input':'','expected_output':''}]})['id']
r=call('POST','/agent-runs',json={'problem_id':pid,'source':'agent','metadata':{'model_name':'resource-acceptance'}});rid=r['id']
try:
    name=db.run(rid,True)['container']
    settings=json.loads(docker(['inspect',name]))[0]
    hc=settings['HostConfig']
    assert hc['Memory']==512*1024*1024 and hc['MemorySwap']==hc['Memory']
    assert hc['PidsLimit']==64 and hc['NanoCpus']==1000000000 and hc['ReadonlyRootfs']
    assert hc['NetworkMode']=='none' and hc['CapDrop']==['ALL'] and not hc['Binds']
    assert settings['Config']['User']=='1000:1000'
    record('docker_enforced_resource_configuration')
    result=cmd(rid,'for i in $(seq 1 90); do sleep 30 & done; wait',500)
    assert result['reason']=='timeout' or result['returncode']!=0,result
    # Explicitly clear children which daemonized away from the shell.
    docker(['exec',name,'python3','/opt/container_cleanup.py'])
    assert cmd(rid,'printf recovered')['stdout']=='recovered'
    record('pid_exhaustion_and_recovery')
    result=cmd(rid,"python3 -c 'from pathlib import Path; [Path(\"fill-\"+str(i)).write_bytes(b\"x\"*524288) for i in range(160)]'",10000)
    assert result['returncode']!=0 and 'No space left on device' in result['stderr'],result
    assert cmd(rid,'rm -f fill-*; printf disk-recovered')['stdout']=='disk-recovered'
    record('workspace_disk_limit_and_recovery')
    db.update_run(rid,expires_at=time.time()-1)
    for _ in range(100):
        r=call('GET','/agent-runs/'+rid)
        if r['status']=='Expired': break
        time.sleep(.1)
    assert r['status']=='Expired',r
    assert name not in docker(['ps','-a','--format','{{.Names}}']).decode().splitlines()
    record('expiry_removes_container')
finally:
 call('DELETE',f'/agent-runs/{rid}/environment')
 call('DELETE',f'/problems/{pid}')
(evidence/'resource-acceptance.json').write_text(json.dumps(report,indent=2))
