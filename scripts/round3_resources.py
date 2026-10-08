"""Real cgroup event/exit evidence and container memory scope regressions."""
import base64
import dataclasses
import json
import os
from pathlib import Path
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
_data=tempfile.TemporaryDirectory(prefix='minioj-round3-resources-')
os.environ['MINIOJ_DATA']=_data.name
from minioj.docker_backend import (DockerJudgeSession,create_container,docker,
                                  hard_execute,remove_container)
from minioj import config

evidence=Path(os.environ.get('MINIOJ_EVIDENCE_DIR','evidence/round3'))
evidence.mkdir(parents=True,exist_ok=True)
results=[]

def run(code,prepare=None,memory=64):
    with DockerJudgeSession() as session:
        r=session.compile(code)
        assert r.returncode==0 and r.reason is None, r
        name=create_container('test',memory)
        try:
            docker(['exec','-i',name,'python3','-c',"import sys,os; p='/workspace/main';open(p,'wb').write(sys.stdin.buffer.read());os.chmod(p,0o555)"],session.binary)
            if prepare:prepare(name)
            settings=json.loads(docker(['inspect',name]))[0]
            hc=settings['HostConfig']
            assert hc['Memory']==memory*1024*1024 and hc['MemorySwap']==hc['Memory']
            assert hc['PidsLimit']==64 and hc['ReadonlyRootfs'] and hc['NetworkMode']=='none'
            assert hc['CapDrop']==['ALL'] and hc['Init'] and not hc['Privileged'] and not hc['Binds']
            assert settings['Config']['User']=='1000:1000'
            return hard_execute(name,b'',500,memory)
        finally:remove_container(name)

def record(name,r):
    d=dataclasses.asdict(r);d['stdout_b64']=base64.b64encode(d.pop('stdout')).decode();d['stderr_b64']=base64.b64encode(d.pop('stderr')).decode()
    results.append({'case':name,**d})
    print(name,r.reason,r.returncode,r.container_peak_memory_kb,flush=True)
    (evidence/'round3-resources.json').write_text(json.dumps(results,indent=2))

normal=run('int main(){}')
assert normal.returncode==0 and normal.reason is None
assert normal.container_baseline_memory_kb>0
assert normal.container_peak_memory_kb>=normal.container_baseline_memory_kb
assert normal.process_peak_rss_kb is None and normal.process_memory_method=='unavailable'
record('normal_baseline',normal)

for name,code in [
 ('sustained_16mb','#include <cstring>\n#include <sys/mman.h>\n#include <unistd.h>\nint main(){auto p=mmap(0,16*1024*1024,3,0x22,-1,0);memset(p,1,16*1024*1024);asm volatile(""::"r"(p):"memory");usleep(100000);munmap(p,16*1024*1024);}'),
 ('short_16mb','#include <cstring>\n#include <sys/mman.h>\nint main(){auto p=mmap(0,16*1024*1024,3,0x22,-1,0);memset(p,1,16*1024*1024);asm volatile(""::"r"(p):"memory");munmap(p,16*1024*1024);}'),
 ('child_16mb','#include <cstring>\n#include <sys/mman.h>\n#include <sys/wait.h>\n#include <unistd.h>\nint main(){if(fork()==0){auto p=mmap(0,16*1024*1024,3,0x22,-1,0);memset(p,1,16*1024*1024);asm volatile(""::"r"(p):"memory");_exit(0);}wait(0);}')]:
    r=run(code)
    assert r.returncode==0 and r.reason is None,r
    assert r.container_peak_memory_kb>16*1024,r
    assert r.process_peak_rss_kb is None,r
    record(name,r)

r=run('int main(){}',lambda name:docker(['exec',name,'/bin/sh','-c','dd if=/dev/zero of=/workspace/baseline.tmp bs=1M count=8 2>/dev/null']))
assert r.reason is None and r.returncode==0,r
assert r.container_baseline_memory_kb>normal.container_baseline_memory_kb+7*1024,r
assert r.container_peak_memory_kb>normal.container_peak_memory_kb+6*1024,r
record('tmpfs_counted_as_container_memory',r)

forks='#include <unistd.h>\n#include <sys/wait.h>\n#include <cerrno>\nint main(){int gate[2];if(pipe(gate))return 2;int failed=0;for(int i=0;i<100;i++){int p=fork();if(p==0){close(gate[1]);char c;read(gate[0],&c,1);_exit(0);}if(p<0)failed++;}close(gate[0]);close(gate[1]);while(wait(0)>0){}return failed>0?0:1;}'
r=run(forks)
assert r.returncode==0 and r.reason is None,r
assert r.cgroup['pids']['max_delta']>0,r
record('new_pid_failure_with_successful_exit',r)

prepare=lambda name:docker(['exec',name,'python3','-S','-c',"import os\nr,w=os.pipe()\nfor i in range(100):\n try:\n  pid=os.fork()\n except OSError:continue\n if pid==0:os.close(w);os.read(r,1);os._exit(0)\nos.close(r);os.close(w)\nwhile True:\n try:os.wait()\n except ChildProcessError:break"],timeout=5)
r=run('int main(){}',prepare)
assert r.reason is None and r.returncode==0,r
assert r.cgroup['before']['pids']['max']>0,r
assert r.cgroup['pids']['max_delta']==0,r
record('historical_pid_failure_with_successful_exit',r)

r=run('#include <unistd.h>\n#include <signal.h>\nint main(){kill(getppid(),SIGKILL);usleep(10000);}')
assert r.reason=='infrastructure_error' and r.infrastructure_error,r
assert r.returncode is None and r.termination_signal is None,r
record('supervisor_killed_is_se',r)

r=run('#include <signal.h>\nint main(){raise(SIGXCPU);}')
assert r.reason is None and r.termination_signal==24 and r.returncode==-24,r
record('self_sent_sigxcpu_is_re',r)

r=run('#include <cstdio>\n#include <unistd.h>\n#include <fcntl.h>\nint main(){char p[80];sprintf(p,"/proc/%d/fd/1",getppid());int fd=open(p,O_WRONLY);if(fd>=0)return 1;puts("protected");}')
assert r.returncode==0 and r.stdout==b'protected\n' and r.reason is None,r
record('supervisor_report_pipe_protected',r)

# Raise PID 1's OOM score (no added capability). Kernel killing namespace
# init stops the container, so post-mortem cgroup reads must be null.
r=run('#include <sys/mman.h>\n#include <cstring>\nint main(){auto p=mmap(0,128*1024*1024,3,0x22,-1,0);memset(p,1,128*1024*1024);asm volatile(""::"r"(p):"memory");}',
      lambda name:docker(['exec',name,'/bin/sh','-c','echo 1000 > /proc/1/oom_score_adj']),32)
assert r.reason=='memory_limit',r
assert r.cgroup['after']['memory'] is None,r
assert r.container_peak_memory_kb is None and r.process_peak_rss_kb is None,r
assert r.termination_signal is None and r.returncode is None,r
record('oomkilled_container_metrics_unavailable',r)

leftovers=docker(['ps','-a','--filter','label=minioj.instance='+str(config.DB_PATH),'--format','{{.Names}}'])
assert not leftovers,leftovers
print('ALL',len(results),'PASSED',flush=True)
