import base64, dataclasses, io, json, math, os, selectors, signal, subprocess, tarfile, tempfile, time, uuid
from . import config
from .runner import Execution
from pathlib import Path

# Pin the same trusted source whose fingerprint config captured at startup.
SUPERVISOR_SOURCE=Path(__file__).resolve().parent.parent.joinpath('scripts/container_judge.py').read_text()

class DockerError(RuntimeError): pass

def docker(args, data=None, timeout=30):
    if not config.DOCKER: raise DockerError('Docker CLI unavailable; install Docker/Colima')
    argv=[config.DOCKER,*(['--context',config.DOCKER_CONTEXT] if config.DOCKER_CONTEXT else []),*args]
    p=None
    try:
        p=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        out=bytearray(); err=bytearray(); payload=memoryview(data or b''); offset=0
        start=time.monotonic()
        with selectors.DefaultSelector() as selector:
            for stream,target in ((p.stdout,out),(p.stderr,err)):
                os.set_blocking(stream.fileno(),False); selector.register(stream,selectors.EVENT_READ,target)
            if payload:
                os.set_blocking(p.stdin.fileno(),False); selector.register(p.stdin,selectors.EVENT_WRITE,None)
            else: p.stdin.close()
            while selector.get_map():
                if time.monotonic()-start>timeout: raise DockerError('Docker operation timed out')
                for key,_ in selector.select(.05):
                    if key.data is None:
                        try: offset+=os.write(key.fd,payload[offset:offset+65536])
                        except BrokenPipeError: offset=len(payload)
                        if offset>=len(payload): selector.unregister(key.fileobj); p.stdin.close()
                    else:
                        chunk=os.read(key.fd,65536)
                        if not chunk: selector.unregister(key.fileobj); continue
                        key.data.extend(chunk)
                        if len(out)>4*1024*1024 or len(err)>262144: raise DockerError('Docker transport output limit exceeded')
            p.wait(timeout=max(.1,timeout-(time.monotonic()-start)))
        if p.returncode:
            # Files helper emits a structured error on stdout.
            if '/opt/container_files.py' in args and out:
                try: raise ValueError(json.loads(out).get('error','File operation failed'))
                except json.JSONDecodeError: pass
            raise DockerError(err.decode(errors='replace')[-2000:] or 'Container exec failed')
        return bytes(out)
    except (OSError,subprocess.TimeoutExpired) as e: raise DockerError(str(e)) from e
    finally:
        if p:
            if p.poll() is None: p.kill()
            p.wait()
            for stream in (p.stdin,p.stdout,p.stderr): stream.close()

def available():
    try:
        docker(['image','inspect',config.IMAGE],timeout=5)
        docker(['info','--format','{{.ServerVersion}}'],timeout=5)
        return True
    except DockerError: return False

def create_container(prefix='run', memory=512, start=True,image=None):
    name='minioj-'+prefix+'-'+uuid.uuid4().hex
    docker((['run','-d'] if start else ['create'])+['--name',name,'--label','minioj.managed=1','--label','minioj.instance='+str(config.DB_PATH),
            *(['--label','minioj.test-session='+os.environ['MINIOJ_TEST_SESSION']] if os.environ.get('MINIOJ_TEST_SESSION') else []),
            '--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
            '--user','1000:1000','--memory',f'{memory}m','--memory-swap',f'{memory}m','--cpus','1',
            '--pids-limit','64','--ulimit','nofile=128:128','--ulimit','core=0:0','--log-driver','none',
            '--tmpfs','/workspace:rw,exec,nosuid,nodev,size=64m,uid=1000,gid=1000,mode=700',
            '--tmpfs','/tmp:rw,noexec,nosuid,nodev,size=16m,uid=1000,gid=1000,mode=700',*(['--init'] if prefix=='test' else []),image or config.IMAGE,*(['/bin/sleep','infinity'] if prefix=='test' else [])],timeout=60)
    return name

def remove_container(name):
    try: docker(['rm','-f',name],timeout=15)
    except DockerError: pass

def files(name,request):
    data=docker(['exec','-i',name,'python3','/opt/container_files.py'],json.dumps(request).encode(),timeout=10)
    return json.loads(data)

def write_file(name,path,content):
    return files(name,{'op':'write','path':path,'content_b64':base64.b64encode(content).decode()})

def read_file(name,path):
    return base64.b64decode(files(name,{'op':'read','path':path})['content_b64'])

def execute(name,request):
    start=time.monotonic()
    before=cgroup_metrics(name)
    try:
        data=docker(['exec','-i',name,'python3','/opt/container_exec.py'],json.dumps(request).encode(),timeout=request['time_limit_ms']/1000+15)
        result=json.loads(data)
        result['stdout']=base64.b64decode(result.pop('stdout_b64'))
        result['stderr']=base64.b64decode(result.pop('stderr_b64'))
        return Execution(**result)
    except DockerError:
        after=cgroup_metrics(name)
        try:state=json.loads(docker(['inspect','--format','{{json .State}}',name]))
        except (DockerError,ValueError):state={}
        if (metric_delta(before,after,'memory','oom_kill') or 0)>0 or state.get('OOMKilled') is True:
            result=classify_execution(None,resource_metrics(before,after),state,None)
            result.runtime_ms=round((time.monotonic()-start)*1000,3)
            return result
        remove_container(name)
        raise

# Each file has its own namespace. Partial/malformed files are unavailable,
# never silently interpreted as zero events.
CGROUP_FILES = {'memory_peak':'memory.peak','memory_current':'memory.current',
                'memory':'memory.events','cpu':'cpu.stat','pids':'pids.events'}
CGROUP_READER = '; '.join("printf '\\n@@"+key+"@@\\n'; cat /sys/fs/cgroup/"+filename+" 2>/dev/null || true" for key,filename in CGROUP_FILES.items())

def parse_cgroup_snapshot(raw):
    result={key:None for key in CGROUP_FILES}
    for key in result:
        marker='@@'+key+'@@'
        if raw.count(marker)!=1:continue
        body=raw.split(marker,1)[1].split('@@',1)[0].strip()
        try:
            if key.startswith('memory_'):
                value=int(body)
                if value<0:raise ValueError()
            else:
                value={}
                for line in body.splitlines():
                    k,v=line.split()
                    if k in value or int(v)<0:raise ValueError()
                    value[k]=int(v)
                if not value:raise ValueError()
            result[key]=value
        except (ValueError,TypeError):pass
    return result

def cgroup_metrics(name):
    try:
        raw=docker(['exec','--user','0:0',name,'/bin/sh','-c',CGROUP_READER],timeout=3).decode()
        return parse_cgroup_snapshot(raw)
    except (DockerError,ValueError):
        return {key:None for key in CGROUP_FILES}

def metric_delta(before,after,section,key):
    a=(before.get(section) or {}).get(key)
    b=(after.get(section) or {}).get(key)
    return b-a if a is not None and b is not None and b>=a else None

def resource_metrics(before,after):
    return {'before':before,'after':after,
            'memory':{'peak_bytes':after.get('memory_peak'),
                      'oom_kill_delta':metric_delta(before,after,'memory','oom_kill'),
                      'max_delta':metric_delta(before,after,'memory','max')},
            'cpu':{'usage_usec_delta':metric_delta(before,after,'cpu','usage_usec')},
            'pids':{'max_delta':metric_delta(before,after,'pids','max')}}

def classify_execution(report,metrics,state,transport_rc,stdout=b'',stderr=b''):
    oom=(metrics['memory']['oom_kill_delta'] or 0)>0 or state.get('OOMKilled') is True
    peak=metrics['memory']['peak_bytes']
    baseline=metrics['before'].get('memory_current')
    cpu=metrics['cpu']['usage_usec_delta']
    result=Execution(None,None,0,None,stdout,stderr,
                     'cgroup_v2_memory_peak_container' if peak is not None else 'container_hard_limit_peak_unavailable',
                     round(cpu/1000,3) if cpu is not None else None,
                     container_peak_memory_kb=math.ceil(peak/1024) if peak is not None else None,
                     container_memory_method='cgroup_v2_memory.peak' if peak is not None else 'unavailable',
                     container_baseline_memory_kb=math.ceil(baseline/1024) if baseline is not None else None,
                     cgroup=metrics,transport_exit_code=transport_rc,container_state=state,
                     cpu_time_method='cgroup_v2_cpu.stat_delta_including_observers' if cpu is not None else 'unavailable',
                     container_baseline_memory_method='cgroup_v2_memory.current_before_execution_including_reader' if baseline is not None else 'unavailable')
    result.memory_kb=result.container_peak_memory_kb # compatibility, explicitly container-wide
    if report is not None:
        result.returncode=report['returncode']
        result.termination_signal=report['termination_signal']
        result.reason=report['reason']
        result.runtime_ms=report['runtime_ms']
        result.stdout=base64.b64decode(report['stdout_b64'],validate=True)
        result.stderr=base64.b64decode(report['stderr_b64'],validate=True)
    if oom:
        result.reason='memory_limit'
        # OOM may have killed PID 1 or the supervisor. Never guess child signal.
    elif report is None or transport_rc!=0 or state.get('Running') is not True:
        result.reason='infrastructure_error'
        result.infrastructure_error='missing_or_failed_supervisor_or_container'
    return result

def parse_execution_report(raw):
    try:
        report=json.loads(raw)
        if not isinstance(report,dict) or type(report.get('version')) is not int or report['version']!=1:
            return None
        rc=report['returncode'];sig=report['termination_signal']
        if type(rc) is not int or not -64<=rc<=255:return None
        if (sig is not None and type(sig) is not int) or sig!=(-rc if rc<0 else None):return None
        if report['reason'] not in (None,'timeout','cpu_timeout','output_limit'):return None
        wall=report['runtime_ms']
        if type(wall) not in (int,float) or not math.isfinite(wall) or wall<0:return None
        for key in ('stdout_b64','stderr_b64'):base64.b64decode(report[key],validate=True)
        return report
    except (ValueError,TypeError,KeyError):return None

def hard_execute(name,input_data,time_ms,memory_mb,output_limit=1048576,*,wall_limit_ms=None):
    wall_limit_ms=time_ms if wall_limit_ms is None else wall_limit_ms
    before=cgroup_metrics(name)
    argv=[config.DOCKER,*(['--context',config.DOCKER_CONTEXT] if config.DOCKER_CONTEXT else []),
          'exec','-i',name,'python3','-S','-c',SUPERVISOR_SOURCE,str(time_ms),str(output_limit),str(wall_limit_ms)]
    start=time.monotonic();raw=bytearray();err=bytearray();watchdog=False
    with tempfile.TemporaryFile() as inp:
        inp.write(input_data);inp.seek(0)
        p=subprocess.Popen(argv,stdin=inp,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        try:
            with selectors.DefaultSelector() as selector:
                for pipe,target in ((p.stdout,raw),(p.stderr,err)):
                    os.set_blocking(pipe.fileno(),False);selector.register(pipe,selectors.EVENT_READ,target)
                while selector.get_map() or p.poll() is None:
                    # Supervisor owns contestant wall timeout. A failed/hung
                    # supervisor/transport is SE, not contestant TLE.
                    if (time.monotonic()-start)*1000>wall_limit_ms+5000:
                        watchdog=True;break
                    for key,_ in selector.select(.005):
                        chunk=os.read(key.fd,65536)
                        if not chunk:selector.unregister(key.fileobj);continue
                        key.data.extend(chunk)
                        if len(raw)>output_limit*2+65536 or len(err)>65536:
                            watchdog=True;break
                    if watchdog:break
            if watchdog and p.poll() is None:p.kill()
            rc=p.wait(timeout=2)
            after=cgroup_metrics(name)
            state=json.loads(docker(['inspect','--format','{{json .State}}',name]))
            report=None if watchdog else parse_execution_report(raw)
            result=classify_execution(report,resource_metrics(before,after),state,rc,stderr=bytes(err))
            if report is None:result.runtime_ms=round((time.monotonic()-start)*1000,3)
            return result
        finally:
            remove_container(name)
            if p.poll() is None:os.killpg(p.pid,signal.SIGKILL)
            p.wait();p.stdout.close();p.stderr.close()

class DockerJudgeSession:
    def __init__(self,image=None): self.name=None;self.binary=None;self.image=image
    def __enter__(self):
        self.name=create_container('compiler',768,image=self.image); return self
    def __exit__(self,*args):
        if self.name: remove_container(self.name)
    def compile(self,code):
        write_file(self.name,'main.cpp',code.encode())
        result=execute(self.name,{'kind':'compile','time_limit_ms':30000,'memory_limit_mb':640,'output_limit':1048576})
        if result.returncode==0 and result.reason is None:
            # Transport compiled executable in memory, never mount host paths.
            self.binary=docker(['exec',self.name,'head','-c','1048577','/workspace/main'])
            if len(self.binary)>1048576: raise DockerError('Compiler artifact exceeds 1 MiB')
        return result
    def run(self,input_data,time_ms,memory_mb,*,wall_limit_ms=None):
        name=create_container('test',memory_mb,image=self.image)
        try:
            docker(['exec','-i',name,'python3','-c',"import sys,os; b=sys.stdin.buffer.read(1048577); assert len(b)<=1048576; f=open('/workspace/main','wb'); f.write(b); f.close(); os.chmod('/workspace/main',0o555)"],self.binary)
            return hard_execute(name,input_data,time_ms,memory_mb,wall_limit_ms=wall_limit_ms)
        finally: remove_container(name)
