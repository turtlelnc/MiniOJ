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
    container_peak_memory_kb: int | None = None
    process_peak_rss_kb: int | None = None
    container_memory_method: str | None = None
    process_memory_method: str = 'unavailable'
    container_baseline_memory_kb: int | None = None
    cgroup: dict | None = None
    transport_exit_code: int | None = None
    infrastructure_error: str | None = None
    container_state: dict | None = None
    cpu_time_method: str | None = None
    container_baseline_memory_method: str | None = None

class LocalRunner:
    """Sampled process-tree limits; no filesystem/network security sandbox.

    Wall time includes launcher startup. Never attribute the caller's shared
    cgroup to this child. wait4 preserves actual exit/signal and CPU evidence
    even when the process disappears between samples.
    """
    def run(self, argv, cwd, input_data=b'', time_limit_ms=1000, memory_limit_mb=128,
            output_limit=1048576, *, wall_limit_ms=None):
        wall_limit_ms=time_limit_ms if wall_limit_ms is None else wall_limit_ms
        # The sampled CPU deadline owns classification. A later kernel guard
        # avoids RLIMIT_CPU's tick accounting firing just below that deadline.
        limits={'cpu':max(1,math.ceil(time_limit_ms/1000))+1, 'memory_mb':memory_limit_mb, 'output':output_limit}
        launcher=Path(__file__).with_name('launcher.py')
        start=time.monotonic(); peak=None; reason=None; known={}; cpu_samples={}; usage=None
        # -S keeps site customization out of the trusted exec-only launcher.
        with tempfile.TemporaryFile() as stdin, tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            stdin.write(input_data); stdin.seek(0)
            p=subprocess.Popen([sys.executable,'-S',str(launcher),json.dumps(limits),*argv],cwd=cwd,stdin=stdin,stdout=stdout,stderr=stderr,start_new_session=True)
            root=psutil.Process(p.pid)
            def reap(block=False):
                nonlocal usage
                if p.returncode is None:
                    pid,status,ru=os.wait4(p.pid,0 if block else os.WNOHANG)
                    if pid:
                        p.returncode=os.waitstatus_to_exitcode(status); usage=ru
                return p.returncode is None
            try:
                while True:
                    live=reap()
                    try: children=root.children(recursive=True) if live else []
                    except psutil.Error: children=[]
                    for child in children: known[child.pid]=child
                    rss=0; observed=False
                    for proc in [root,*known.values()]:
                        try:
                            rss+=proc.memory_info().rss; observed=True
                            ct=proc.cpu_times();cpu_samples[proc.pid]=max(cpu_samples.get(proc.pid,0),ct.user+ct.system)
                        except psutil.Error: pass
                    if observed:peak=max(peak or 0,rss)
                    cpu=max(sum(cpu_samples.values()),usage.ru_utime+usage.ru_stime if usage else 0)
                    size=os.fstat(stdout.fileno()).st_size+os.fstat(stderr.fileno()).st_size
                    elapsed=(time.monotonic()-start)*1000
                    if observed and rss>memory_limit_mb*1024*1024: reason='memory_limit'
                    elif size>output_limit: reason='output_limit'
                    # Resource evidence is checked before wall; exit is reaped
                    # before sampling, so a completed signal isn't overwritten
                    # by time spent looking up an already-exited process.
                    elif cpu*1000>time_limit_ms: reason='timeout'
                    elif live and elapsed>wall_limit_ms:
                        if reap():reason='timeout'
                    if reason or p.returncode is not None:break
                    time.sleep(.005)
            finally:
                try:os.killpg(p.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                for child in known.values():
                    try:child.kill()
                    except psutil.Error:pass
                reap(block=True)
                p.wait() # already reaped; Popen uses the recorded actual status
            stdout.seek(0);stderr.seek(0)
            out=stdout.read(output_limit);err=stderr.read(output_limit)
            cpu=max(sum(cpu_samples.values()),usage.ru_utime+usage.ru_stime if usage else 0)
            if reason is None and p.returncode==-signal.SIGXCPU and usage and (usage.ru_utime+usage.ru_stime)*1000>=time_limit_ms:
                reason='cpu_timeout'
            if reason is None and p.returncode==-signal.SIGXFSZ and os.fstat(stdout.fileno()).st_size+os.fstat(stderr.fileno()).st_size>=output_limit:
                reason='output_limit'
            return Execution(p.returncode,reason,round((time.monotonic()-start)*1000,3),
                             math.ceil(peak/1024) if peak is not None else None,out,err,
                             'sampled_process_tree_rss',round(cpu*1000,3),
                             -p.returncode if p.returncode<0 else None,
                             cpu_time_method='max_wait4_primary_and_sampled_tree_cpu_lower_bound')
