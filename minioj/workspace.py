import base64, dataclasses, json, logging, os, signal, subprocess, threading, time
from . import db, config
from .docker_backend import available, create_container, docker, execute, files, read_file, remove_container, write_file, DockerError

class WorkspaceManager:
    MAX_ACTIVE=2
    WALL_SECONDS=900
    CPU_SECONDS=120
    MAX_COMMANDS=100
    OUTPUT_BUDGET=4*1024*1024
    def __init__(self):
        self.lock=threading.RLock(); self.busy=set(); self.stop=threading.Event(); self.thread=None
    def start(self):
        # Optional maintenance recovery preserves tmpfs files across an abrupt
        # server replacement, but interrupts old shells and command processes.
        recover=os.environ.get('MINIOJ_RECOVER_WORKSPACES')=='1'
        with db.connect() as c:
            candidates={r['container']:dict(r) for r in c.execute("SELECT id,container,expires_at FROM agent_runs WHERE status='Active' AND container IS NOT NULL")}
        retained=[]
        try:
            names=docker(['ps','-a','--filter','label=minioj.instance='+str(config.DB_PATH),'--format','{{.Names}}']).decode().splitlines()
            for name in names:
                r=candidates.get(name)
                if recover and r and r['expires_at']>time.time():
                    try:
                        if docker(['inspect','--format','{{.State.Running}}',name]).strip()==b'true':
                            docker(['exec',name,'python3','/opt/container_cleanup.py'])
                            retained.append(r['id']); continue
                    except DockerError: pass
                remove_container(name)
        except DockerError: pass
        with db.connect() as c:
            excluded=','.join('?' for _ in retained) or "''"
            c.execute("UPDATE agent_runs SET status='Interrupted',ended_at=?,container=NULL WHERE status IN ('Active','Created') AND id NOT IN ("+excluded+")",[db.now(),*retained])
        with db.connect() as c:
            c.execute("UPDATE agent_runs SET status='Finished',ended_at=? WHERE status='Judging' AND final_submission_id IN (SELECT id FROM submissions WHERE status='Finished')",(db.now(),))
        self.thread=threading.Thread(target=self.monitor,daemon=True,name='workspace-monitor'); self.thread.start()
    def create(self,pid,source,metadata,environment=True):
        snapshot=db.problem(pid,True)
        if not snapshot: raise KeyError(pid)
        if environment and not snapshot.get('allow_workspace',False): raise PermissionError('本题未允许启用工作台')
        with self.lock:
            if environment:
                if not available(): raise DockerError('Sandbox image/runtime unavailable. Run scripts/setup_sandbox.sh first.')
                with db.connect() as c: count=c.execute("SELECT COUNT(*) FROM agent_runs WHERE status='Active'").fetchone()[0]
                if count>=self.MAX_ACTIVE: raise OverflowError('At most two workspaces may be active')
            rid=db.create_run(pid,source,metadata,snapshot)
            if not environment: return rid
            name=None
            try:
                name=create_container('run')
                public={k:v for k,v in snapshot.items() if k not in ('testcases','deleted')}
                write_file(name,'problem.json',json.dumps(public,ensure_ascii=False,indent=2).encode())
                write_file(name,'main.cpp',b'')
                write_file(name,'sample.in',(snapshot['samples'][0]['input'] if snapshot['samples'] else '').encode())
                write_file(name,'sample.out',(snapshot['samples'][0]['expected_output'] if snapshot['samples'] else '').encode())
                db.update_run(rid,status='Active',container=name,expires_at=time.time()+self.WALL_SECONDS)
                return rid
            except Exception:
                if name: remove_container(name)
                db.update_run(rid,status='Failed',ended_at=db.now()); raise
    def active(self,rid):
        r=db.run(rid,True)
        if not r: raise KeyError(rid)
        if r['status']!='Active' or not r['container']: raise ValueError('Workspace is not active')
        if time.time()>r['expires_at']:
            self.destroy(rid,'Expired'); raise ValueError('Workspace expired')
        return r
    def reserve(self,rid):
        with self.lock:
            r=self.active(rid)
            if rid in self.busy: raise ValueError('Workspace already has an active command or terminal')
            self.busy.add(rid); return r
    def release(self,rid):
        with self.lock: self.busy.discard(rid)
    def file_action(self,rid,op,path=None,content=None):
        # Browsing is read-only and must remain available while a terminal owns
        # the execution reservation. The container helper prevents symlink races.
        if op in ('read','list'):
            r=self.active(rid)
            if op=='read': return {'path':path,'content':read_file(r['container'],path).decode(errors='replace')}
            return files(r['container'],{'op':'list'})
        if op!='write': raise ValueError('Unknown file operation')
        r=self.reserve(rid)
        try:
            if len(r['commands'])>=200: raise ValueError('File operation budget exhausted')
            result=write_file(r['container'],path,content.encode())
            cid=db.create_command(rid,'file_write',{'path':path,'content':content})
            db.update_command(cid,'Finished',result)
            return result
        finally: self.release(rid)
    def command(self,rid,command,timeout_ms,stdin):
        r=self.reserve(rid)
        try:
            if sum(c['kind'] in ('command','terminal') for c in r['commands'])>=self.MAX_COMMANDS: raise ValueError('Command budget exhausted')
            used=sum(len((c.get('result') or {}).get('stdout','').encode())+len((c.get('result') or {}).get('stderr','').encode()) for c in r['commands'])
            if used>=self.OUTPUT_BUDGET: raise ValueError('Run output budget exhausted')
            cid=db.create_command(rid,'command',{'command':command,'timeout_ms':timeout_ms,'stdin':stdin})
            thread=threading.Thread(target=self.execute_command,args=(rid,r['container'],cid,command,timeout_ms,stdin,min(config.OUTPUT_LIMIT,self.OUTPUT_BUDGET-used)),daemon=True)
            thread.start(); return cid
        except BaseException:
            self.release(rid); raise
    def execute_command(self,rid,name,cid,command,timeout_ms,stdin,output_limit):
        db.update_command(cid,'Running')
        try:
            r=execute(name,{'kind':'command','command':command,'time_limit_ms':timeout_ms,'memory_limit_mb':384,'output_limit':output_limit,'input_b64':base64.b64encode(stdin.encode()).decode()})
            result=dataclasses.asdict(r)
            result['stdout']=r.stdout.decode(errors='replace'); result['stderr']=r.stderr.decode(errors='replace')
            db.update_command(cid,'Finished',result)
        except Exception as e: db.update_command(cid,'Finished',{'error':str(e)[:2000]})
        finally: self.release(rid)
    def destroy(self,rid,status='Destroyed'):
        with self.lock:
            r=db.run(rid,True)
            if not r: raise KeyError(rid)
            if r['container']: remove_container(r['container'])
            fields={'container':None}
            if r['status'] in ('Active','Created'): fields.update(status=status,ended_at=db.now())
            db.update_run(rid,**fields)
    def finalize(self,rid,queue,path='main.cpp',code=None):
        with self.lock:
            r=db.run(rid,True)
            if not r: raise KeyError(rid)
            if r['status'] not in ('Active','Created'): raise ValueError('Run is not active')
            if rid in self.busy: raise ValueError('Close terminal or wait for command before submitting')
            if code is None:
                self.active(rid)
                code=read_file(r['container'],path).decode('utf-8')
            if len(code.encode())>config.SOURCE_LIMIT: raise ValueError('Source too large')
            if queue.queue.full(): raise OverflowError('Judge queue is full')
            # Publish to queue only after marking the run, so a quick judge cannot race finalization.
            sid=db.create_submission(r['problem_id'],code,r['source'],rid,r['snapshot'])
            db.update_run(rid,status='Judging',final_submission_id=sid)
            self.destroy(rid)
            try: queue.queue.put_nowait(sid)
            except __import__('queue').Full: pass
            return sid
    def monitor(self):
        while not self.stop.wait(3):
            with db.connect() as c: active=[dict(x) for x in c.execute("SELECT id,container,expires_at FROM agent_runs WHERE status='Active'")]
            for r in active:
                try:
                    if time.time()>r['expires_at']: self.destroy(r['id'],'Expired'); continue
                    stats=docker(['exec',r['container'],'cat','/sys/fs/cgroup/cpu.stat'],timeout=5).decode()
                    usage=next(int(line.split()[1]) for line in stats.splitlines() if line.startswith('usage_usec '))
                    if usage>self.CPU_SECONDS*1000000: self.destroy(r['id'],'BudgetExceeded')
                except Exception:
                    # Cleanup of a terminal may race a monitoring exec. Only mark
                    # failed if the container itself is no longer running.
                    try:
                        running=docker(['inspect','--format','{{.State.Running}}',r['container']],timeout=5).strip()
                        if running!=b'true': self.destroy(r['id'],'Failed')
                    except DockerError:
                        try: self.destroy(r['id'],'Failed')
                        except Exception: pass
    def close(self):
        self.stop.set()
        with db.connect() as c: ids=[r[0] for r in c.execute("SELECT id FROM agent_runs WHERE container IS NOT NULL")]
        for rid in ids: self.destroy(rid,'Interrupted')
        if self.thread: self.thread.join(timeout=6)
