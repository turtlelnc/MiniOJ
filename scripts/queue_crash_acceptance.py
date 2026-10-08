"""SIGKILL isolated real server during compile/run; restart, fence, reconcile."""
import os
import json,signal,subprocess,sys,tempfile,time
from pathlib import Path
import httpx
root=Path(__file__).resolve().parent.parent
evidence=Path(os.environ.get('MINIOJ_EVIDENCE_DIR',root/'evidence'))
evidence.mkdir(parents=True,exist_ok=True)
report=[]
with tempfile.TemporaryDirectory(prefix='minioj-crash-') as directory:
 env={**os.environ,'MINIOJ_DATA':directory,'MINIOJ_JUDGE_BACKEND':'docker','MINIOJ_SUBMISSION_LEASE_SECONDS':'10'}
 server=None;log=open(evidence/'queue-crash-server.log','wb')
 def start():
  p=subprocess.Popen([sys.executable,'-m','uvicorn','minioj.app:app','--host','127.0.0.1','--port','8001'],cwd=root,env=env,stdout=log,stderr=log,start_new_session=True)
  end=time.monotonic()+20
  while time.monotonic()<end:
   token=Path(directory)/'api-token'
   if token.exists():
    c=httpx.Client(base_url='http://127.0.0.1:8001/api',headers={'X-MiniOJ-Token':token.read_text().strip()},trust_env=False,timeout=15)
    try:
     if c.get('/health').status_code==200:return p,c
    except httpx.HTTPError:pass
    c.close()
   time.sleep(.1)
  raise RuntimeError('Server did not start')
 try:
  server,c=start()
  p={'title':'crash acceptance','time_limit_ms':10000,'memory_limit_mb':64,'testcases':[{'input':'','expected_output':''}]}
  pid=c.post('/problems',json=p).json()['id']
  for stage in ('Compiling','Running'):
   rid=c.post('/agent-runs',json={'problem_id':pid,'environment':False}).json()['id']
   code='#include <bits/stdc++.h>\nint main(){while(1){}}'
   sid=c.post(f'/agent-runs/{rid}/final-submit',json={'source_code':code}).json()['submission_id']
   deadline=time.monotonic()+20
   while time.monotonic()<deadline:
    s=c.get('/submissions/'+str(sid)).json()
    if s['status']==stage:break
    time.sleep(.01)
   else:raise AssertionError(('stage missed',stage,s))
   os.killpg(server.pid,signal.SIGKILL);server.wait();c.close();server,c=start()
   deadline=time.monotonic()+20
   while time.monotonic()<deadline:
    s=c.get('/submissions/'+str(sid)).json()
    if s['status']=='Finished':break
    time.sleep(.1)
   assert s['verdict']=='SE' and s['reason']=='worker_lease_expired',s
   assert s['attempt_count']==1,s
   assert c.get('/agent-runs/'+rid).json()['status']=='Finished'
   report.append({'killed_during':stage,'verdict':s['verdict'],'reason':s['reason'],'attempt_count':s['attempt_count'],'run_status':'Finished'});print(report[-1],flush=True)
  sid=c.post('/submissions',json={'problem_id':pid,'source_code':'int main(){}'}).json()['submission_id']
  deadline=time.monotonic()+10
  while time.monotonic()<deadline:
   s=c.get('/submissions/'+str(sid)).json()
   if s['status']=='Finished':break
   time.sleep(.1)
  assert s['verdict']=='AC',s
  report.append({'post_recovery_submission':'AC'})
 finally:
  if server and server.poll() is None:
   server.terminate();server.wait(timeout=50)
  log.close()
(evidence/'queue-crash-acceptance.json').write_text(json.dumps(report,indent=2))
