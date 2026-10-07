import logging, queue, tempfile, threading
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

def judge(sid):
    s=db.submission(sid,True); p=s['snapshot']; results=[]; passed=0
    db.update_submission(sid,status='Compiling')
    backend=DockerJudgeSession if config.JUDGE_BACKEND=='docker' else LocalJudgeSession
    try:
        with backend() as session:
            compiled=session.compile(s['source_code'])
            output=(compiled.stdout+compiled.stderr).decode(errors='replace')[:config.OUTPUT_LIMIT]
            db.update_submission(sid,compile_output=output)
            if compiled.returncode or compiled.reason:
                db.update_submission(sid,status='Finished',verdict='CE',reason=compiled.reason or 'compile_failed')
                return
            db.update_submission(sid,status='Running')
            verdict='AC'; reason=None
            for i,t in enumerate(p['testcases']):
                r=session.run(t['input'].encode(),p['time_limit_ms'],p['memory_limit_mb'])
                if r.reason in ('memory_limit','memory_allocation_failure'): v='MLE'
                elif r.reason=='timeout': v='TLE'
                elif r.reason or r.returncode: v='RE'
                elif compare(r.stdout,t['expected_output'].encode(),p['checker']): v='AC'
                else: v='WA'
                # Hidden stdout/stderr are not exposed: they can reveal test inputs.
                results.append({'test_index':i+1,'verdict':v,'runtime_ms':r.runtime_ms,'memory_kb':r.memory_kb if r.memory_method!='cgroup_oom_no_peak_available' else None,'memory_method':r.memory_method,'exit_code':r.returncode,'reason':r.reason})
                if v=='AC': passed+=1
                db.update_submission(sid,passed_tests=passed,results=results)
                if v!='AC': verdict=v; reason=r.reason; break
            memory=[r['memory_kb'] for r in results if r['memory_kb'] is not None]
            db.update_submission(sid,status='Finished',verdict=verdict,reason=reason,runtime_ms=max(r['runtime_ms'] for r in results),memory_kb=max(memory) if memory else None,passed_tests=passed,results=results)
    except Exception as e:
        logging.exception('Submission %s failed',sid)
        db.update_submission(sid,status='Finished',verdict='SE',reason=str(e)[:2000])

class JudgeQueue:
    def __init__(self):
        self.queue=queue.Queue(maxsize=100); self.stop=threading.Event(); self.thread=None
    def start(self):
        self.thread=threading.Thread(target=self.work,daemon=True,name='judge-worker'); self.thread.start()
        self.refill()
    def refill(self):
        for sid in db.pending():
            if self.queue.full(): break
            self.queue.put_nowait(sid)
    def submit(self,pid,code,source='human',run_id=None,snapshot=None):
        if self.queue.full(): raise OverflowError('Judge queue is full')
        sid=db.create_submission(pid,code,source,run_id,snapshot)
        try: self.queue.put_nowait(sid)
        except queue.Full: pass # durable Pending row is picked up by the worker
        return sid
    def work(self):
        while not self.stop.is_set():
            try: sid=self.queue.get(timeout=1)
            except queue.Empty:
                self.refill(); continue
            try:
                if db.submission(sid)['status']=='Pending':
                    judge(sid)
                    submission=db.submission(sid)
                    if submission['run_id']:
                        run=db.run(submission['run_id'])
                        if run['status']=='Judging' and run['final_submission_id']==sid:
                            db.update_run(run['id'],status='Finished',ended_at=db.now())
            finally: self.queue.task_done()
    def close(self):
        self.stop.set()
        if self.thread: self.thread.join(timeout=45)
