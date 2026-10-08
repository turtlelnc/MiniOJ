"""Native target: signal classification tests don't benchmark interpreter startup."""
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from test_judge import COMPILER
from minioj.runner import LocalRunner

_fixture=None
_source=r'''
#include <csignal>
#include <cstdio>
#include <cstring>
#include <ctime>
#include <unistd.h>
int main(int argc,char**argv){
 const char* mode=argv[1];
 if(!strcmp(mode,"0"))return 0;
 if(!strcmp(mode,"1"))return 1;
 if(!strcmp(mode,"137"))return 137;
 if(!strcmp(mode,"sigxfsz")){raise(SIGXFSZ);return 1;}
 if(!strcmp(mode,"crash")){raise(SIGABRT);return 1;}
 if(!strcmp(mode,"cpu")){volatile unsigned long long n=0;for(;;)n++;}
 if(!strcmp(mode,"wall")){sleep(30);return 0;}
 if(!strcmp(mode,"output")){for(;;)puts("xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx");}
 if(!strcmp(mode,"exact_output")){char b[4096]={};for(int i=0;i<256;i++)if(write(1,b,sizeof b)!=sizeof b)return 2;return 0;}
 if(!strcmp(mode,"bad_alloc")){fputs("bad_alloc Cannot allocate memory",stderr);return 1;}
 if(!strcmp(mode,"sigxcpu") || !strcmp(mode,"sigkill")){
  FILE* f=fopen(argv[2],"w");if(!f)return 2;
  fprintf(f,"%.3f",1000.0*clock()/CLOCKS_PER_SEC);fclose(f);
  while(access(argv[3],F_OK)!=0)usleep(1000);
  raise(!strcmp(mode,"sigxcpu")?SIGXCPU:SIGKILL);return 1;
 }
 return 2;
}
'''


def executable():
    global _fixture
    if _fixture is None:
        _fixture=tempfile.TemporaryDirectory(prefix='minioj-runner-fixture-')
        source=Path(_fixture.name)/'target.cpp';source.write_text(_source)
        subprocess.run([COMPILER,str(source),'-O2','-o',str(Path(_fixture.name)/'target')],check=True,capture_output=True,timeout=30)
    return str(Path(_fixture.name)/'target')


def signaled_run(mode='sigxcpu'):
    exe=executable()
    with tempfile.TemporaryDirectory(prefix='minioj-signal-sync-') as directory:
        ready=Path(directory)/'ready';ack=Path(directory)/'ack';observed={}
        def controller():
            deadline=time.monotonic()+8
            while time.monotonic()<deadline:
                if ready.exists():
                    # Existence can precede fclose; ack requires a full record.
                    try:observed['ready_cpu_ms']=float(ready.read_text())
                    except ValueError:time.sleep(.001);continue
                    ack.write_text('ack');return
                time.sleep(.001)
            observed['setup_error']='target did not become ready before setup deadline'
        thread=threading.Thread(target=controller,daemon=True);thread.start()
        result=LocalRunner().run([exe,mode,str(ready),str(ack)],directory,time_limit_ms=10000)
        thread.join(timeout=9)
        if thread.is_alive() or observed.get('setup_error'):raise AssertionError(observed)
        if not result.runtime_ms<10000 or not result.cpu_time_ms<10000:raise AssertionError('signal test reached its resource budget')
        return result,observed
