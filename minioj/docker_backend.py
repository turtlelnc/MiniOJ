import base64, dataclasses, json, os, selectors, subprocess, time, uuid
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

def create_container(prefix='run', memory=512):
    name='minioj-'+prefix+'-'+uuid.uuid4().hex
    docker(['run','-d','--name',name,'--label','minioj.managed=1','--label','minioj.instance='+str(config.DB_PATH),
            '--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
            '--user','1000:1000','--memory',f'{memory}m','--memory-swap',f'{memory}m','--cpus','1',
            '--pids-limit','64','--ulimit','nofile=128:128','--ulimit','core=0:0','--log-driver','none',
            '--tmpfs','/workspace:rw,exec,nosuid,nodev,size=64m,uid=1000,gid=1000,mode=700',
            '--tmpfs','/tmp:rw,noexec,nosuid,nodev,size=16m,uid=1000,gid=1000,mode=700',config.IMAGE],timeout=60)
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

class DockerJudgeSession:
    def __init__(self): self.name=None
    def __enter__(self):
        self.name=create_container('judge',768); return self
    def __exit__(self,*args): remove_container(self.name)
    def compile(self,code):
        write_file(self.name,'main.cpp',code.encode())
        return execute(self.name,{'kind':'compile','time_limit_ms':30000,'memory_limit_mb':640,'output_limit':1048576})
    def run(self,input_data,time_ms,memory_mb):
        result=execute(self.name,{'kind':'judge','time_limit_ms':time_ms,'memory_limit_mb':memory_mb,'input_b64':base64.b64encode(input_data).decode()})
        # Remove all remaining descendants, including daemonized processes.
        docker(['exec',self.name,'python3','/opt/container_cleanup.py'])
        return result
