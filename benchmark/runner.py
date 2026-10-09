"""python -m benchmark.runner --config config.json / --resume EXPERIMENT_ID."""
import argparse,json,os,threading,time,uuid
from pathlib import Path
import httpx
from .adapters import adapter,ModelFailure
from .reports import export
from .harness import request_messages
from .snapshots import capture as capture_snapshot
import hashlib
class InfrastructureFailure(RuntimeError):pass
class AgentFailure(RuntimeError):pass
class JudgeFailure(RuntimeError):pass

class Runner:
 def __init__(self,url,token,execution_guard=None):
  self.client=httpx.Client(base_url=url+'/api',headers={'X-MiniOJ-Token':token},trust_env=False,timeout=30)
  self.execution_guard=execution_guard
  self.owner=uuid.uuid4().hex;self.stop=threading.Event();self.lease_lost=False
 def api(self,method,path,_tool=False,**kw):
  try:
   r=self.client.request(method,path,**kw);r.raise_for_status();return r.json()
  except httpx.HTTPStatusError as exc:
   if _tool and exc.response.status_code in (400,403,404,409,413,422):raise AgentFailure('tool_request_rejected_'+str(exc.response.status_code)) from None
   raise InfrastructureFailure('MiniOJ request failed: HTTP '+str(exc.response.status_code)) from None
  except (httpx.HTTPError,ValueError) as exc:raise InfrastructureFailure('MiniOJ request failed: '+type(exc).__name__) from None
 def wait(self,path,deadline):
  while time.monotonic()<deadline:
   self.check(deadline);r=self.api('GET',path)
   if r['status']=='Finished':return r
   time.sleep(.1)
  if path.startswith('/submissions/'):raise InfrastructureFailure('judge_wait_timeout')
  raise AgentFailure('wall_time_budget')
 def check(self,deadline):
  if self.lease_lost:raise InfrastructureFailure('experiment_lease_lost')
  if time.monotonic()>=deadline:raise AgentFailure('wall_time_budget')
 def checkpoint(self,bid,unit,record,status='Running',rid=None):
  self.api('PUT',f'/benchmarks/{bid}/units/{unit["id"]}',json={'owner':self.owner,'record':record,'status':status,'run_id':rid})
 def execute(self,bid,unit,manifest):
  record=unit['record'].copy();start=time.monotonic();deadline=start+manifest['limits']['max_wall_time_seconds'];rid=unit['run_id'];final=False
  try:
   # A surviving final submission can be reconciled without model/tool replay.
   if unit['status']=='Running':
    if rid:
     run=self.api('GET','/agent-runs/'+rid)
     if run.get('final_submission_id'):
      s=self.wait('/submissions/'+str(run['final_submission_id']),deadline)
      record.update(submission_id=s['id'],verdict=s['verdict'])
      if manifest.get('harness'):
       record.update(final_submit_attempted=True,final_submission_completed=True,final_submission_id=s['id'])
       if isinstance(s.get('source_code'),str):
        source=s['source_code'];record['termination_code']={'content':source,'sha256':hashlib.sha256(source.encode()).hexdigest(),'captured_at':time.time(),'provenance':'final_submission_source'}
      if s['verdict']=='SE':raise JudgeFailure(s.get('reason') or 'SE')
      final=True;return
    raise InfrastructureFailure('interrupted_execution_not_replayed')
   if manifest.get('harness'):record.update(final_submit_attempted=False,final_submission_completed=False,tool_events=[])
   record['started_at']=time.time();self.checkpoint(bid,unit,record)
   model=adapter(manifest['models'][unit['model_index']])
   run=self.api('POST',f'/benchmarks/{bid}/units/{unit["id"]}/run',json={'owner':self.owner});rid=run['id'];record['run_id']=rid
   problem=run['problem'];messages=[{'role':'system','content':manifest['system_prompt']},{'role':'user','content':json.dumps(problem,ensure_ascii=False)}]
   usage={'input_tokens':0,'output_tokens':0};record['usage']=usage
   while record['model_calls']<manifest['limits']['max_model_calls']:
    self.check(deadline)
    if self.execution_guard:self.execution_guard.before_model()
    record['model_calls']+=1;record['messages']=messages
    request=request_messages(messages,manifest,record,problem,deadline-time.monotonic())
    self.checkpoint(bid,unit,record,rid=rid)
    reply=model.complete(request,manifest['tool_schema'],manifest['temperature'],unit['seed'],manifest['max_tokens'],max(.1,min(60,deadline-time.monotonic())),problem)
    record.update(model_returned=reply.model,seed_effective=reply.effective_seed,deterministic=manifest['models'][unit['model_index']]['provider']=='fake')
    if reply.usage is None or any(reply.usage.get(k) is None for k in usage):record['usage']=None
    elif record['usage'] is not None:
     for k in usage:usage[k]+=reply.usage[k]
    if self.execution_guard:self.execution_guard.after_model(reply.usage)
    message=reply.message;messages.append(message);calls=message.get('tool_calls') or []
    if not calls:raise AgentFailure('model_ended_without_final_submission')
    for tc in calls:
     self.check(deadline)
     if record['tool_calls']>=manifest['limits']['max_tool_calls']:raise AgentFailure('tool_call_budget')
     record['tool_calls']+=1;record['pending_tool']=tc;self.checkpoint(bid,unit,record,rid=rid)
     try:
      name=tc['function']['name'];args=json.loads(tc['function']['arguments'])
      schema=next(t['function']['parameters'] for t in manifest['tool_schema'] if t['function']['name']==name)
      if not isinstance(args,dict) or set(args)-set(schema['properties']) or set(schema['required'])-set(args):raise ValueError()
      for k,v in args.items():
       if not isinstance(v,str):raise ValueError()
     except (ValueError,KeyError,StopIteration,TypeError):raise AgentFailure('invalid_tool_call') from None
     base=f'/agent-runs/{rid}'
     event={'name':name,'args':args,'model_call':record['model_calls'],'tool_call':record['tool_calls'],'at_unix':time.time()}
     record.setdefault('tool_events',[]).append(event)
     if name=='read_file':result=self.api('GET',base+'/file',params=args,_tool=True)
     elif name=='write_file':result=self.api('PUT',base+'/file',json=args,_tool=True)
     elif name=='terminal':
      timeout=max(100,min(30000,int((deadline-time.monotonic())*1000)))
      c=self.api('POST',base+'/commands',json={**args,'timeout_ms':timeout},_tool=True);result=self.wait('/commands/'+c['command_id'],deadline)['result']
      event['result']=result
      if result.get('error'):raise InfrastructureFailure('command_execution_failed')
     elif name in ('submit_attempt','final_submit'):
      endpoint='/submissions' if name=='submit_attempt' else '/final-submit'
      if name=='final_submit':
       record.update(final_submit_attempted=True,model_calls_before_final_submit=record['model_calls'],tool_calls_before_final_submit=record['tool_calls'])
      s=self.api('POST',base+endpoint,json={'path':'main.cpp'},_tool=True);sid=s['submission_id'];record['submission_id']=sid
      event['submission_id']=sid
      if name=='final_submit':record['final_submission_id']=sid
      # Persist submission identity before polling, then never feed a final
      # hidden result into another tool/model round.
      self.checkpoint(bid,unit,record,rid=rid)
      s=self.wait('/submissions/'+str(sid),deadline)
      if name=='final_submit':
       record['final_submission_completed']=True
       if manifest.get('harness') and isinstance(s.get('source_code'),str):
        source=s['source_code'];record['termination_code']={'content':source,'sha256':hashlib.sha256(source.encode()).hexdigest(),'captured_at':time.time(),'provenance':'final_submission_source'}
      if s['verdict']=='SE':raise JudgeFailure(s.get('reason') or 'SE')
      result={'verdict':s['verdict'],'passed_tests':s['passed_tests'],'total_tests':s['total_tests']}
      if name=='final_submit':
       event['result']=result;record.update(result,final_submission_completed=True)
       final=True;return
     event['result']=result
     record.pop('pending_tool',None);messages.append({'role':'tool','tool_call_id':tc['id'],'content':json.dumps(result,ensure_ascii=False)});self.checkpoint(bid,unit,record,rid=rid)
   raise AgentFailure('model_call_budget')
  except (ModelFailure,AgentFailure,JudgeFailure,InfrastructureFailure) as exc:
   category={ModelFailure:'model_failure',AgentFailure:'agent_failure',JudgeFailure:'judge_failure',InfrastructureFailure:'infrastructure_failure'}[type(exc)]
   record.update(failure_category=category,error=str(exc)[:200]);final=False
   if record.get('tool_events') and 'result' not in record['tool_events'][-1]:record['tool_events'][-1]['error']=str(exc)[:200]
   if isinstance(exc,ModelFailure):
    record['usage']=None
    if self.execution_guard:self.execution_guard.stop_reason='provider_failure'
  except Exception as exc:
   record.update(failure_category='infrastructure_failure',error='runner_error:'+type(exc).__name__);final=False
  finally:
   record['termination_detected_at']=time.time()
   record['wall_time_seconds']=round(time.monotonic()-start,3) if unit['status']!='Running' else None
   record.pop('pending_tool',None)
   # Freeze before capture: background writers must not race a diagnostic read.
   # Local DB/runtime access is mandatory; unavailable remote capture is unknown.
   if rid and manifest.get('harness') and not final and not record.get('termination_code'):
    record['termination_code']=capture_snapshot(rid)
   if manifest.get('harness',{}).get('study')=='termination_ablation_v1':
    from .termination_metrics import trajectory
    record.update(trajectory(record,manifest['limits']))
   try:
    self.checkpoint(bid,unit,record,'Finished' if final else 'Failed',rid)
   finally:
    if rid:
     try:
      self.api('PATCH','/agent-runs/'+rid,json={'benchmark_id':bid,'unit_id':unit['id'],'token_input':(record.get('usage') or {}).get('input_tokens'),'token_output':(record.get('usage') or {}).get('output_tokens'),'tool_calls':record['tool_calls'],'model_calls':record['model_calls']})
     except InfrastructureFailure:pass
     finally:
      try:self.api('DELETE','/agent-runs/'+rid+'/environment')
      except InfrastructureFailure:pass

 def run(self,bid,max_units=None,unit_ids=None):
  self.stop.clear();self.lease_lost=False
  self.api('POST',f'/benchmarks/{bid}/acquire',json={'owner':self.owner})
  def heartbeat():
   while not self.stop.wait(5):
    try:self.api('POST',f'/benchmarks/{bid}/heartbeat',json={'owner':self.owner})
    except InfrastructureFailure:self.lease_lost=True;return
  thread=threading.Thread(target=heartbeat,daemon=True);thread.start()
  try:
   experiment=self.api('GET','/benchmarks/'+bid);done=0
   for unit in experiment['units']:
    if unit['status'] in ('Finished','Failed') or unit_ids is not None and unit['id'] not in unit_ids:continue
    if max_units is not None and done>=max_units:break
    self.execute(bid,unit,experiment['manifest']);done+=1
    print('unit',unit['ordinal'],'stored',flush=True)
  finally:
   self.stop.set();thread.join(timeout=35)
   self.api('POST',f'/benchmarks/{bid}/release',json={'owner':self.owner})
  return self.api('GET','/benchmarks/'+bid)

def main():
 parser=argparse.ArgumentParser();g=parser.add_mutually_exclusive_group(required=True);g.add_argument('--config',type=Path);g.add_argument('--resume');parser.add_argument('--url',default='http://127.0.0.1:8000');parser.add_argument('--token-file',type=Path,default=Path(__file__).resolve().parent.parent/'data/api-token');parser.add_argument('--output',type=Path,default=Path('evidence/benchmark'));parser.add_argument('--max-units',type=int);args=parser.parse_args()
 runner=Runner(args.url,args.token_file.read_text().strip());bid=args.resume or runner.api('POST','/benchmarks',json=json.loads(args.config.read_text()))['id'];print('experiment',bid,flush=True)
 result=runner.run(bid,args.max_units);export(result,args.output/bid);print(json.dumps(result['summary'],ensure_ascii=False,indent=2))
if __name__=='__main__':main()
