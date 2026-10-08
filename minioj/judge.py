import logging, queue, tempfile, threading, uuid
from pathlib import Path
from . import config, db
from .checker import compare
from .runner import LocalRunner
from .docker_backend import DockerJudgeSession

class LocalJudgeSession:
    def __enter__(self):
        root=Path(tempfile.gettempdir())/'minioj'; root.mkdir(mode=0o700,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(prefix='submission-',dir=root)
        self.path=Path(self.tmp.name); self.runner=LocalRunner(); return self
    def __exit__(self,*args): self.tmp.cleanup()
    def compile(self,code):
        if not config.COMPILER: raise RuntimeError('C++ compiler unavailable')
        (self.path/'main.cpp').write_text(code)
        return self.runner.run([config.COMPILER,'main.cpp','-O2','-std=c++17','-o','main'],self.path,time_limit_ms=30000,memory_limit_mb=640)
    def run(self,input_data,time_ms,memory_mb):
        return self.runner.run([str(self.path/'main')],self.path,input_data,time_ms,memory_mb)

def judge(sid,owner=None):
    if owner is None:
        owner=uuid.uuid4().hex
        if db.claim_submission(owner,sid) is None:return
    done=threading.Event()
    def heartbeat():
        while not done.wait(min(5,config.SUBMISSION_LEASE_SECONDS/3)):
            if not db.renew_submission(sid,owner):return
    threading.Thread(target=heartbeat,daemon=True).start()
    def update(**fields):return db.update_submission(sid,owner=owner,**fields)
    s=db.submission(sid,True); p=s['snapshot']; results=[]; passed=0
    update(status='Compiling')
    backend=DockerJudgeSession if config.JUDGE_BACKEND=='docker' else LocalJudgeSession
    try:
        if p.get('_judge_fingerprint',config.SOURCE_FINGERPRINT)!=config.SOURCE_FINGERPRINT: raise RuntimeError('judge_version_changed')
        with (backend(image=p.get('_judge_image')) if config.JUDGE_BACKEND=='docker' else backend()) as session:
            compiled=session.compile(s['source_code'])
            output=(compiled.stdout+compiled.stderr).decode(errors='replace')[:config.OUTPUT_LIMIT]
            update(compile_output=output)
            if compiled.returncode or compiled.reason:
                update(status='Finished',verdict='CE',reason=compiled.reason or 'compile_failed')
                return
            update(status='Running')
            verdict='AC'; reason=None
            for i,t in enumerate(p['testcases']):
                r=session.run(t['input'].encode(),p['time_limit_ms'],p['memory_limit_mb'])
                if r.reason in ('memory_limit','memory_allocation_failure'): v='MLE'
                elif r.reason=='timeout': v='TLE'
                elif r.reason or r.returncode: v='RE'
                elif compare(r.stdout,t['expected_output'].encode(),p['checker']): v='AC'
                else: v='WA'
                # Hidden stdout/stderr are not exposed: they can reveal test inputs.
                results.append({'test_index':i+1,'verdict':v,'runtime_ms':r.runtime_ms,'memory_kb':r.memory_kb if r.memory_method!='cgroup_oom_no_peak_available' else None,'memory_method':r.memory_method,'exit_code':r.returncode if r.termination_signal is None and (config.JUDGE_BACKEND!='docker' or r.returncode is not None and r.returncode<128) else None,'transport_exit_code':r.returncode if config.JUDGE_BACKEND=='docker' else None,'reason':r.reason,'wall_time_ms':r.runtime_ms,'cpu_time_ms':r.cpu_time_ms,'peak_memory_kb':r.memory_kb,'termination_signal':r.termination_signal,'termination_reason':r.reason or ('nonzero_exit' if r.returncode else None)})
                if v=='AC': passed+=1
                update(passed_tests=passed,results=results)
                if v!='AC': verdict=v; reason=r.reason; break
            memory=[r['memory_kb'] for r in results if r['memory_kb'] is not None]
            update(status='Finished',verdict=verdict,reason=reason,runtime_ms=max(r['runtime_ms'] for r in results),memory_kb=max(memory) if memory else None,passed_tests=passed,results=results)
    except Exception as e:
        logging.exception('Submission %s failed',sid)
        try: update(status='Finished',verdict='SE',reason=str(e)[:2000])
        except ValueError: logging.warning('Discarded result for expired submission %s',sid)
    finally: done.set()

class JudgeQueue:
    CAPACITY=100
    def __init__(self):
        # Compatibility hints only. SQLite determines eligibility and ordering.
        self.queue=queue.Queue(maxsize=100);self.wake=threading.Event();self.stop=threading.Event();self.thread=None
    def start(self):
        self.thread=threading.Thread(target=self.work,daemon=True,name='judge-worker');self.thread.start()
    def refill(self): self.wake.set()
    def submit(self,pid,code,source='human',run_id=None,snapshot=None,final=False):
        sid=db.create_submission(pid,code,source,run_id,snapshot,final=final,capacity=self.CAPACITY)
        self.wake.set();return sid
    def work(self):
        owner=uuid.uuid4().hex
        while not self.stop.is_set():
            try:
                sid=db.claim_submission(owner)
                if sid is not None: judge(sid,owner);continue
            except Exception:logging.exception('Judge worker recovered after error')
            self.wake.wait(.2);self.wake.clear()
    def close(self):
        self.stop.set();self.wake.set()
        if self.thread:self.thread.join(timeout=45)
