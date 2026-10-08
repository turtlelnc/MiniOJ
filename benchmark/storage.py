"""Server-owned immutable experiment manifests and unique, resumable units."""
import hashlib,json,subprocess,time,uuid
from minioj import db,config
from . import VERSION
from .protocol import SYSTEM_PROMPT,tools

def initialize(c):
 c.executescript('''
 CREATE TABLE IF NOT EXISTS benchmarks(id TEXT PRIMARY KEY,created_at TEXT NOT NULL,status TEXT NOT NULL,manifest TEXT NOT NULL,owner TEXT,lease_expires_at REAL);
 CREATE TABLE IF NOT EXISTS benchmark_units(id TEXT PRIMARY KEY,benchmark_id TEXT NOT NULL REFERENCES benchmarks(id),ordinal INTEGER NOT NULL,problem_id INTEGER NOT NULL,model_index INTEGER NOT NULL,seed INTEGER NOT NULL,status TEXT NOT NULL,run_id TEXT REFERENCES agent_runs(id),record TEXT NOT NULL,UNIQUE(benchmark_id,ordinal));
 CREATE INDEX IF NOT EXISTS units_benchmark ON benchmark_units(benchmark_id,ordinal);
 ''')

def create(spec):
 if not isinstance(spec,dict):raise ValueError('Configuration must be an object')
 allowed={'name','problems','models','seeds','protocol','limits','temperature','max_tokens','system_prompt'}
 if set(spec)-allowed:raise ValueError('Unknown benchmark configuration fields')
 name=spec.get('name');problems=spec.get('problems');models=spec.get('models');seeds=spec.get('seeds',[1]);protocol=spec.get('protocol','final_only')
 if not isinstance(name,str) or not 1<=len(name)<=200:raise ValueError('Invalid name')
 if not isinstance(problems,list) or not 1<=len(problems)<=100 or any(type(p)!=int for p in problems) or len(set(problems))!=len(problems):raise ValueError('Invalid problems')
 if not isinstance(seeds,list) or not 1<=len(seeds)<=20 or any(type(s)!=int for s in seeds) or len(set(seeds))!=len(seeds):raise ValueError('Invalid seeds')
 if not isinstance(models,list) or not 1<=len(models)<=10:raise ValueError('Invalid models')
 if protocol not in ('final_only','iterative'):raise ValueError('Invalid protocol')
 for m in models:
  if not isinstance(m,dict) or set(m)-{'provider','model','api_key_env','codes'}:raise ValueError('Invalid model configuration; keys must be environment references')
  if m.get('provider') not in ('fake','deepseek') or not isinstance(m.get('model'),str):raise ValueError('Unsupported provider/model')
  if 'api_key_env' in m and (not isinstance(m['api_key_env'],str) or not m['api_key_env'].isidentifier()):raise ValueError('Invalid key environment variable')
  if 'codes' in m and m['provider']!='fake':raise ValueError('codes are FakeAdapter fixtures only')
 limits={'max_model_calls':16,'max_tool_calls':50,'max_wall_time_seconds':300,**spec.get('limits',{})}
 for k,maximum in [('max_model_calls',100),('max_tool_calls',200),('max_wall_time_seconds',900)]:
  if type(limits.get(k))!=int or not 1<=limits[k]<=maximum:raise ValueError('Invalid '+k)
 if set(limits)-{'max_model_calls','max_tool_calls','max_wall_time_seconds'}:raise ValueError('Unknown limit')
 temperature=spec.get('temperature',0);max_tokens=spec.get('max_tokens',4096)
 if not isinstance(temperature,(float,int)) or not 0<=temperature<=2 or type(max_tokens)!=int or not 1<=max_tokens<=16384:raise ValueError('Invalid model parameters')
 snapshots=[]
 for pid in problems:
  p=db.problem(pid,True)
  if not p:raise KeyError(pid)
  if not p.get('allow_workspace'):raise ValueError(f'Problem {pid} must enable workspaces')
  snapshots.append(p)
 def git(*args):
  try:return subprocess.check_output(['git',*args],cwd=config.ROOT,stderr=subprocess.DEVNULL).decode().strip()
  except (OSError,subprocess.CalledProcessError):return None
 commit=git('rev-parse','HEAD');diff=git('diff','HEAD');bid=uuid.uuid4().hex
 manifest={'experiment_id':bid,'experiment_name':name,'created_at':db.now(),'git_commit':commit,'git_dirty':bool(diff),'source_diff_sha256':hashlib.sha256((diff or '').encode()).hexdigest(),'runner_version':VERSION,'judge_backend':config.JUDGE_BACKEND,'protocol':protocol,'models':models,'seeds':seeds,'temperature':temperature,'max_tokens':max_tokens,'limits':limits,'system_prompt':spec.get('system_prompt',SYSTEM_PROMPT),'tool_schema':tools(protocol),'problem_snapshots':snapshots,'environment_information':{'sandbox_image':config.IMAGE,'docker_context':config.DOCKER_CONTEXT,**config.RUNTIME_INFORMATION},'model_backend_version':'unknown'}
 from minioj.docker_backend import docker,DockerError
 if config.JUDGE_BACKEND=='docker':
  try:manifest['environment_information'].update(json.loads(docker(['image','inspect',config.IMAGE,'--format','{"image_id":{{json .Id}},"architecture":{{json .Architecture}},"os":{{json .Os}}}'])))
  except DockerError:raise ValueError('Sandbox image is unavailable')
 for p in snapshots:
  p['_judge_image']=manifest['environment_information'].get('image_id')
  p['_judge_fingerprint']=config.SOURCE_FINGERPRINT
 with db.connect() as c:
  c.execute('INSERT INTO benchmarks(id,created_at,status,manifest) VALUES(?,?,?,?)',(bid,manifest['created_at'],'Pending',json.dumps(manifest)))
  ordinal=0
  for mi in range(len(models)):
   for p in snapshots:
    for seed in seeds:
     uid=uuid.uuid4().hex
     record={'unit_id':uid,'problem_id':p['id'],'model_index':mi,'seed_requested':seed,'seed_effective':None,'deterministic':False,'model_backend_version':'unknown','protocol':protocol,'usage':None,'tool_calls':0,'model_calls':0}
     c.execute('INSERT INTO benchmark_units VALUES(?,?,?,?,?,?,?,?,?)',(uid,bid,ordinal,p['id'],mi,seed,'Pending',None,json.dumps(record)))
     ordinal+=1
 return bid

def get(bid,internal=False):
 with db.connect() as c:
  row=c.execute('SELECT * FROM benchmarks WHERE id=?',(bid,)).fetchone()
  if not row:raise KeyError(bid)
  result=dict(row);result['manifest']=json.loads(result['manifest']);result['units']=[{**dict(r),'record':json.loads(r['record'])} for r in c.execute('SELECT * FROM benchmark_units WHERE benchmark_id=? ORDER BY ordinal',(bid,))]
 if result['status']=='Running' and (result['lease_expires_at'] or 0)<time.time():result['status']='Interrupted'
 result.pop('owner');result.pop('lease_expires_at')
 if not internal:
  for p in result['manifest']['problem_snapshots']:
   hidden=p.pop('testcases');p['hidden_tests_sha256']=hashlib.sha256(json.dumps(hidden,sort_keys=True).encode()).hexdigest();p.pop('deleted',None)
  for u in result['units']:
   u['record'].pop('messages',None);u['record'].pop('pending_tool',None)
 from .metrics import summary
 result['summary']=summary(result)
 return result

def listing():
 with db.connect() as c:ids=[r[0] for r in c.execute('SELECT id FROM benchmarks ORDER BY created_at DESC')]
 return [{'id':bid,'name':(b:=get(bid))['manifest']['experiment_name'],'created_at':b['created_at'],'status':b['status'],'units':len(b['units']),'summary':b['summary']} for bid in ids]

def acquire(bid,owner):
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE')
  row=c.execute('SELECT * FROM benchmarks WHERE id=?',(bid,)).fetchone()
  if not row:raise KeyError(bid)
  if row['owner'] and row['lease_expires_at']>time.time() and row['owner']!=owner:raise ValueError('Experiment already has a runner')
  c.execute("UPDATE benchmarks SET owner=?,lease_expires_at=?,status=CASE WHEN status='Completed' THEN status ELSE 'Running' END WHERE id=?",(owner,time.time()+30,bid))

def owned(c,bid,owner):
 row=c.execute('SELECT owner,lease_expires_at FROM benchmarks WHERE id=?',(bid,)).fetchone()
 if not row or row['owner']!=owner or row['lease_expires_at']<time.time():raise ValueError('Experiment lease lost')

def heartbeat(bid,owner):
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');owned(c,bid,owner);c.execute('UPDATE benchmarks SET lease_expires_at=? WHERE id=?',(time.time()+30,bid))

def update_unit(bid,uid,owner,status,record,run_id=None):
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');owned(c,bid,owner)
  row=c.execute('SELECT * FROM benchmark_units WHERE id=? AND benchmark_id=?',(uid,bid)).fetchone()
  if not row:raise KeyError(uid)
  if row['status'] in ('Finished','Failed'):return # terminal records immutable
  if status not in ('Running','Finished','Failed'):raise ValueError('Invalid unit state')
  merged=json.loads(row['record']);merged.update(record)
  if status in ('Finished','Failed'):merged.pop('pending_tool',None)
  c.execute('UPDATE benchmark_units SET status=?,record=?,run_id=COALESCE(?,run_id) WHERE id=?',(status,json.dumps(merged),run_id,uid))

def release(bid,owner):
 with db.connect() as c:
  c.execute('BEGIN IMMEDIATE');owned(c,bid,owner)
  pending=c.execute("SELECT COUNT(*) FROM benchmark_units WHERE benchmark_id=? AND status NOT IN ('Finished','Failed')",(bid,)).fetchone()[0]
  c.execute('UPDATE benchmarks SET status=?,owner=NULL,lease_expires_at=NULL WHERE id=?',('Paused' if pending else 'Completed',bid))
