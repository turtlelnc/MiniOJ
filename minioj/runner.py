import dataclasses, json, math, os, signal, subprocess, sys, tempfile, time
from pathlib import Path
import psutil

@dataclasses.dataclass
class Execution:
    returncode: int | None
    reason: str | None
    runtime_ms: float
    memory_kb: int | None
    stdout: bytes
    stderr: bytes
    memory_method: str = 'sampled_process_tree_rss'
    cpu_time_ms: float | None = None
    termination_signal: int | None = None

class LocalRunner:
    """Resource-limited backend, not a filesystem/network security sandbox."""
    def run(self, argv, cwd, input_data=b'', time_limit_ms=1000, memory_limit_mb=128, output_limit=1048576):
        limits={'cpu':max(1,math.ceil(time_limit_ms/1000)), 'memory_mb':memory_limit_mb, 'output':output_limit}
        launcher=Path(__file__).with_name('launcher.py')
        start=time.monotonic(); peak=0; reason=None; known={}
        cgroup=Path('/sys/fs/cgroup')
        def cgroup_values():
            try:
                memory=int((cgroup/'memory.current').read_text())
                cpu=int(next(line.split()[1] for line in (cgroup/'cpu.stat').read_text().splitlines() if line.startswith('usage_usec ')))
                return memory,cpu
            except (OSError,ValueError,StopIteration): return None
        baseline=cgroup_values() if sys.platform.startswith('linux') else None
        def oom_count():
            try:
                return int(next(line.split()[1] for line in (cgroup/'memory.events').read_text().splitlines() if line.startswith('oom_kill ')))
            except (OSError,ValueError,StopIteration): return 0
        initial_oom=oom_count() if baseline else 0
        with tempfile.TemporaryFile() as stdin, tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            stdin.write(input_data); stdin.seek(0)
            p=subprocess.Popen([sys.executable,str(launcher),json.dumps(limits),*argv],cwd=cwd,stdin=stdin,stdout=stdout,stderr=stderr,start_new_session=True)
            root=psutil.Process(p.pid)
            try:
                while True:
                    live=p.poll() is None
                    try:
                        children=root.children(recursive=True)
                    except psutil.Error: children=[]
                    for child in children: known[child.pid]=child
                    rss=0; cpu=0
                    for proc in [root,*known.values()]:
                        try:
                            rss+=proc.memory_info().rss
                            ct=proc.cpu_times(); cpu+=ct.user+ct.system
                        except psutil.Error: pass
                    if baseline:
                        current=cgroup_values()
                        if current:
                            rss=max(rss,max(0,current[0]-baseline[0]))
                            cpu=max(cpu,max(0,current[1]-baseline[1])/1000000)
                    peak=max(peak,rss)
                    size=os.fstat(stdout.fileno()).st_size+os.fstat(stderr.fileno()).st_size
                    elapsed=(time.monotonic()-start)*1000
                    if rss>memory_limit_mb*1024*1024: reason='memory_limit'
                    elif size>=output_limit: reason='output_limit'
                    elif live and (elapsed>time_limit_ms or cpu*1000>time_limit_ms): reason='timeout'
                    if reason or not live: break
                    time.sleep(0.01)
            finally:
                try: os.killpg(p.pid,signal.SIGKILL)
                except ProcessLookupError: pass
                for child in known.values():
                    try: child.kill()
                    except psutil.Error: pass
                p.wait()
            stdout.seek(0); stderr.seek(0)
            out=stdout.read(output_limit); err=stderr.read(output_limit)
            if baseline and oom_count()>initial_oom: reason='memory_limit'
            if reason is None and p.returncode == -signal.SIGXCPU: reason='timeout'
            if reason is None and p.returncode == -signal.SIGXFSZ: reason='output_limit'
            if reason is None and p.returncode and (b'bad_alloc' in err or b'Cannot allocate memory' in err): reason='memory_allocation_failure'
            return Execution(p.returncode,reason,round((time.monotonic()-start)*1000,3),math.ceil(peak/1024),out,err,'sampled_tree_rss_and_cgroup_delta' if baseline else 'sampled_process_tree_rss',None,-p.returncode if p.returncode<0 else None)
