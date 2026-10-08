import base64, dataclasses, io, json, math, os, selectors, signal, subprocess, tarfile, tempfile, time, uuid
from . import config
from .runner import Execution

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
            '--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
            '--user','1000:1000','--memory',f'{memory}m','--memory-swap',f'{memory}m','--cpus','1',
            '--pids-limit','64','--ulimit','nofile=128:128','--ulimit','core=0:0','--log-driver','none',
            '--tmpfs','/workspace:rw,exec,nosuid,nodev,size=64m,uid=1000,gid=1000,mode=700',
            '--tmpfs','/tmp:rw,noexec,nosuid,nodev,size=16m,uid=1000,gid=1000,mode=700',image or config.IMAGE],timeout=60)
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
    try:
        data=docker(['exec','-i',name,'python3','/opt/container_exec.py'],json.dumps(request).encode(),timeout=request['time_limit_ms']/1000+15)
        result=json.loads(data)
        result['stdout']=base64.b64decode(result.pop('stdout_b64'))
        result['stderr']=base64.b64decode(result.pop('stderr_b64'))
        return Execution(**result)
    except DockerError:
        # A cgroup OOM can kill the trusted exec supervisor as well as its child.
        try:
            oom=docker(['exec',name,'cat','/sys/fs/cgroup/memory.events']).decode()
            if any(line.startswith('oom_kill ') and int(line.split()[1])>0 for line in oom.splitlines()):
                return Execution(-9,'memory_limit',0,0,b'',b'', 'cgroup_oom_no_peak_available')
        except DockerError: pass
        remove_container(name)
        raise

def cgroup_metrics(name):
    # Kernel-owned read-only files, separate from contestant stdout. May be
    # unavailable after container OOM/PID exhaustion; never invent a peak.
    try:
        raw=docker(['exec',name,'cat','/sys/fs/cgroup/memory.peak','/sys/fs/cgroup/memory.events','/sys/fs/cgroup/cpu.stat','/sys/fs/cgroup/pids.events'],timeout=3).decode().splitlines()
        return {'peak':int(raw[0]),**{line.split()[0]:int(line.split()[1]) for line in raw[1:] if len(line.split())==2}}
    except (DockerError,ValueError): return None

def hard_execute(name,input_data,time_ms,memory_mb,output_limit=1048576):
    before=cgroup_metrics(name)
    limits={'cpu':max(1,math.ceil(time_ms/1000)),'memory_mb':memory_mb,'output':output_limit}
    argv=[config.DOCKER,*(['--context',config.DOCKER_CONTEXT] if config.DOCKER_CONTEXT else []),'exec','-i',name,'prlimit','--cpu='+str(limits['cpu'])+':'+str(limits['cpu']+1),'--fsize='+str(output_limit)+':'+str(output_limit),'--nofile=64:64','--core=0:0','--','/workspace/main']
    reason=None; rc=None; signal_number=None
    with tempfile.TemporaryFile() as inp:
        inp.write(input_data);inp.seek(0);start=time.monotonic()
        p=subprocess.Popen(argv,stdin=inp,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
        stdout=bytearray();stderr=bytearray();after=None
        try:
            # Bounded pipes avoid writing unlimited contestant output to disk.
            with selectors.DefaultSelector() as selector:
                for pipe,target in ((p.stdout,stdout),(p.stderr,stderr)):
                    os.set_blocking(pipe.fileno(),False);selector.register(pipe,selectors.EVENT_READ,target)
                while selector.get_map() or p.poll() is None:
                    if (time.monotonic()-start)*1000>time_ms:reason='timeout';break
                    for key,_ in selector.select(.005):
                        chunk=os.read(key.fd,65536)
                        if not chunk:selector.unregister(key.fileobj);continue
                        remaining=output_limit-len(stdout)-len(stderr)
                        key.data.extend(chunk[:remaining])
                        if len(chunk)>=remaining:reason='output_limit';break
                    if reason:break
            rc=p.poll()
            if reason:
                # Stop the cgroup before any potentially slow accounting query.
                # Kernel counters may then be unavailable, which is recorded null.
                if p.poll() is None:p.kill()
                p.wait(timeout=2);p.stdout.close();p.stderr.close()
                try:docker(['kill',name],timeout=5)
                except DockerError:pass
            else:after=cgroup_metrics(name)
            wall=round((time.monotonic()-start)*1000,3)
            if after and after.get('oom_kill',0)>(before or {}).get('oom_kill',0):reason='memory_limit';signal_number=9
            if not after:
                state=json.loads(docker(['inspect','--format','{{json .State}}',name]))
                if state.get('OOMKilled'):reason='memory_limit';signal_number=9
            if reason is None and after and after.get('max',0)>0:reason='process_limit'
        finally:
            remove_container(name)
            if p.poll() is None:os.killpg(p.pid,signal.SIGKILL)
            p.wait();p.stdout.close();p.stderr.close()
        if reason is None and rc and (b'bad_alloc' in stderr or b'Cannot allocate memory' in stderr):reason='memory_allocation_failure'
        return Execution(rc,reason,wall,math.ceil(after['peak']/1024) if after else None,bytes(stdout),bytes(stderr),'cgroup_v2_memory_peak_container' if after else 'container_hard_limit_peak_unavailable',round(max(0,after['usage_usec']-before['usage_usec'])/1000,3) if before and after else None,signal_number)

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
    def run(self,input_data,time_ms,memory_mb):
        name=create_container('test',memory_mb,image=self.image)
        try:
            docker(['exec','-i',name,'python3','-c',"import sys,os; b=sys.stdin.buffer.read(1048577); assert len(b)<=1048576; f=open('/workspace/main','wb'); f.write(b); f.close(); os.chmod('/workspace/main',0o555)"],self.binary)
            return hard_execute(name,input_data,time_ms,memory_mb)
        finally: remove_container(name)
