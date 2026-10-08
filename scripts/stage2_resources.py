"""Actual Docker hard-limit acceptance, independent of the HTTP server."""
import dataclasses,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from minioj.docker_backend import DockerJudgeSession,docker
cases={
 'normal':('int main(){}',None),
 'infinite_cpu':('int main(){while(1){}}','timeout'),
 'allocation':('#include <cstdlib>\n#include <cstring>\nint main(){while(1){auto p=malloc(1048576);if(!p)abort();memset(p,1,1048576);asm volatile(""::"r"(p):"memory");}}','memory_limit'),
 'short_peak':('#include <sys/mman.h>\n#include <cstring>\nint main(){auto p=mmap(0,96*1024*1024,3,0x22,-1,0);memset(p,1,96*1024*1024);munmap(p,96*1024*1024);}', 'memory_limit'),
 'fork_limit':('#include <unistd.h>\n#include <cstdio>\nint main(){int n=0;for(int i=0;i<100;i++){auto p=fork();if(p==0){sleep(2);return 0;}if(p>0)n++;}printf("%d\n",n);fflush(stdout);sleep(2);}', 'timeout'),
 'detached_child':('#include <unistd.h>\nint main(){if(fork()==0){setsid();close(0);close(1);close(2);while(1){}}}',None),
 'infinite_output':('#include <cstdio>\nint main(){while(1)puts("xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx");}','output_limit'),
 'crash':('#include <cstdlib>\nint main(){abort();}',None),
 'memory_and_timeout':('#include <cstdlib>\n#include <cstring>\nint main(){while(1){auto p=malloc(1048576);if(!p)abort();memset(p,1,1048576);asm volatile(""::"r"(p):"memory");}}','memory_limit'),
 'near_deadline_memory':('#include <unistd.h>\n#include <sys/mman.h>\n#include <cstring>\nint main(){usleep(450000);auto p=mmap(0,96*1024*1024,3,0x22,-1,0);memset(p,1,96*1024*1024);asm volatile(""::"r"(p):"memory");while(1){}}', 'race'),
 'under_limit_peak':('#include <sys/mman.h>\n#include <cstring>\nint main(){auto p=mmap(0,16*1024*1024,3,0x22,-1,0);memset(p,1,16*1024*1024);asm volatile(""::"r"(p):"memory");munmap(p,16*1024*1024);}',None),
}
Path('evidence').mkdir(exist_ok=True)
report=[]
for name,(code,expected) in cases.items():
 with DockerJudgeSession() as session:
  r=session.compile(code);assert r.returncode==0,(name,r.stderr)
  r=session.run(b'',500,32)
  if name=='fork_limit':
   assert r.reason in ('process_limit','timeout'),r
   assert 0<int(r.stdout.strip())<64,r.stdout
  elif expected=='race':assert r.reason in ('timeout','memory_limit'),r
  elif expected:assert r.reason==expected,(name,r)
  elif name=='crash':assert r.returncode!=0,r
  else:assert not r.reason and r.returncode==0,(name,r)
  # Compiler/supervisor must survive contestant OOM/PID pressure.
  assert docker(['exec',session.name,'true'])==b''
  if name=='under_limit_peak':assert r.memory_kb is not None and r.memory_kb>16*1024,r
  d=dataclasses.asdict(r)
  if name=='fork_limit':d['observed_forks']=int(r.stdout.strip())
  if name=='infinite_output':assert r.runtime_ms<2000,r
  d.pop('stdout');d.pop('stderr');report.append({'case':name,**d});print(name,d,flush=True)
 leftovers=docker(['ps','-a','--filter','name=minioj-test-','--format','{{.Names}}']);assert not leftovers,leftovers
Path('evidence/stage2-resources.json').write_text(json.dumps(report,indent=2))
