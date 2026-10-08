"""Real Docker wait-status, deadline and transport-failure regressions."""
import dataclasses
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
_data=tempfile.TemporaryDirectory(prefix='minioj-round4-')
os.environ['MINIOJ_DATA']=_data.name
from minioj.docker_backend import DockerJudgeSession,create_container,docker,hard_execute,remove_container
from minioj.judge import execution_verdict
from minioj import config

results=[]
evidence=Path(os.environ.get('MINIOJ_EVIDENCE_DIR','evidence/round4'))
evidence.mkdir(parents=True,exist_ok=True)

def record(case,r):
    d=dataclasses.asdict(r);d.pop('stdout');d.pop('stderr')
    results.append({'case':case,**d})
    (evidence/'round4-boundaries.json').write_text(json.dumps(results,indent=2))
    print(case,r.reason,r.returncode,r.termination_signal,flush=True)

cases=[
 ('exit_zero','int main(){}',0,None,None,500,500),
 ('exit_one','int main(){return 1;}',1,None,None,500,500),
 ('exit_137','int main(){return 137;}',137,None,None,500,500),
 ('self_sigxcpu','#include <signal.h>\nint main(){raise(SIGXCPU);}',-signal.SIGXCPU,signal.SIGXCPU,None,1000,5000),
 ('self_sigkill','#include <signal.h>\nint main(){raise(SIGKILL);}',-signal.SIGKILL,signal.SIGKILL,None,1000,5000),
 ('self_sigxfsz','#include <signal.h>\nint main(){raise(SIGXFSZ);}',-signal.SIGXFSZ,signal.SIGXFSZ,None,500,500),
 ('exact_output','#include <unistd.h>\nint main(){char b[4096]={};for(int i=0;i<256;i++){int n=0;while(n<4096){auto r=write(1,b+n,4096-n);if(r<=0)return 1;n+=r;}}}',0,None,None,1000,5000),
 ('abnormal_crash','#include <signal.h>\nint main(){raise(SIGABRT);}',-signal.SIGABRT,signal.SIGABRT,None,500,500),
 ('cpu_deadline','int main(){while(1){}}',-signal.SIGKILL,signal.SIGKILL,'cpu_timeout',1000,5000),
 ('wall_deadline','#include <unistd.h>\nint main(){sleep(10);}',-signal.SIGKILL,signal.SIGKILL,'timeout',500,500),
 ('output_deadline','#include <cstdio>\nint main(){while(1)puts("xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx");}',None,None,'output_limit',1000,5000),
 ('stderr_not_memory_evidence','#include <cstdio>\nint main(){fputs("bad_alloc: out of memory",stderr);return 1;}',1,None,None,500,500),
 ('supervisor_failure','#include <unistd.h>\n#include <signal.h>\nint main(){kill(getppid(),SIGKILL);usleep(10000);}',None,None,'infrastructure_error',500,500),
]
for case,code,rc,sig,reason,cpu,wall in cases:
    with DockerJudgeSession() as session:
        compiled=session.compile(code);assert compiled.returncode==0 and compiled.reason is None,compiled
        r=session.run(b'',cpu,64,wall_limit_ms=wall)
        record(case,r)
        assert r.reason==reason,r
        if case!='output_deadline':assert (r.returncode,r.termination_signal)==(rc,sig),r
        if case=='exact_output':assert len(r.stdout)==1048576,r
        if case=='cpu_deadline':assert r.runtime_ms<wall and r.cpu_time_ms>=cpu,r
        if case=='supervisor_failure':assert r.infrastructure_error and execution_verdict(r,"","trimmed")=='SE',r
        if case in ('self_sigxcpu','self_sigkill','self_sigxfsz','exit_137','abnormal_crash'):assert execution_verdict(r,"","trimmed")=='RE',r
        if reason in ('timeout','cpu_timeout'):assert execution_verdict(r,"","trimmed")=='TLE',r

# Deschedule the real supervisor until after its wall deadline while the
# contestant has already exited by SIGXCPU. Its exit must win over the
# supervisor's delayed observation; this deterministically tests the race.
with DockerJudgeSession() as session:
    code='#include <cstdio>\n#include <unistd.h>\n#include <signal.h>\nint main(){auto f=fopen("/workspace/supervisor.pid","w");fprintf(f,"%d",getppid());fclose(f);kill(getppid(),SIGSTOP);raise(SIGXCPU);}'
    assert session.compile(code).returncode==0
    name=create_container('test',64);helper=None
    try:
        docker(['exec','-i',name,'python3','-c',"import sys,os;p='/workspace/main';open(p,'wb').write(sys.stdin.buffer.read());os.chmod(p,0o555)"],session.binary)
        command="import os,time,signal\nfrom pathlib import Path\np=Path('/workspace/supervisor.pid')\nend=time.monotonic()+4\nwhile not p.exists() and time.monotonic()<end:time.sleep(.001)\npid=int(p.read_text());time.sleep(.3);os.kill(pid,signal.SIGCONT)"
        argv=[config.DOCKER,*(['--context',config.DOCKER_CONTEXT] if config.DOCKER_CONTEXT else []),'exec',name,'python3','-S','-c',command]
        helper=subprocess.Popen(argv,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        r=hard_execute(name,b'',5000,64,wall_limit_ms=100)
        record('completed_signal_before_delayed_observation',r)
        assert helper.wait(timeout=5)==0
        assert r.returncode==-signal.SIGXCPU and r.termination_signal==signal.SIGXCPU,r
        assert r.reason is None and execution_verdict(r,b'','exact')=='RE',r
        assert r.runtime_ms>=300,r
    finally:
        remove_container(name)
        if helper is not None:
            if helper.poll() is None:helper.kill()
            helper.wait(timeout=5)

# A paused real container rejects docker exec. No mock CLI, stderr-based
# inference or fabricated contestant exit/signal is involved.
name=create_container('test',64)
try:
    docker(['pause',name])
    r=hard_execute(name,b'',500,64)
    record('docker_cli_failure',r)
    assert r.infrastructure_error and execution_verdict(r,"","trimmed")=='SE',r
    assert r.transport_exit_code!=0 and r.returncode is None and r.termination_signal is None,r
    assert r.cpu_time_ms is None and r.container_peak_memory_kb is None,r
finally:remove_container(name)
print('ALL',len(results),'PASSED',flush=True)
