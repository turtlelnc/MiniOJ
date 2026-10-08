import sqlite3, json, time, uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from .config import DB_PATH, SUBMISSION_LEASE_SECONDS

def now():
    return datetime.now(timezone.utc).isoformat()

@contextmanager
def connect():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    try:
        with con:
            yield con
    finally:
        con.close()

def initialize():
    with connect() as c:
        c.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS problems (
          id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL,
          input_description TEXT NOT NULL, output_description TEXT NOT NULL,
          time_limit_ms INTEGER NOT NULL, memory_limit_mb INTEGER NOT NULL,
          checker TEXT NOT NULL, samples TEXT NOT NULL, deleted INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS testcases (
          id INTEGER PRIMARY KEY, problem_id INTEGER NOT NULL REFERENCES problems(id),
          input TEXT NOT NULL, expected_output TEXT NOT NULL, weight REAL NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS agent_runs (
          id TEXT PRIMARY KEY, problem_id INTEGER NOT NULL REFERENCES problems(id),
          source TEXT NOT NULL, created_at TEXT NOT NULL, ended_at TEXT,
          status TEXT NOT NULL, metadata TEXT NOT NULL, snapshot TEXT NOT NULL,
          container TEXT, expires_at REAL, final_submission_id INTEGER);
        CREATE TABLE IF NOT EXISTS submissions (
          id INTEGER PRIMARY KEY, problem_id INTEGER NOT NULL REFERENCES problems(id),
          run_id TEXT REFERENCES agent_runs(id), attempt INTEGER, source TEXT NOT NULL,
          language TEXT NOT NULL, source_code TEXT NOT NULL, created_at TEXT NOT NULL,
          status TEXT NOT NULL, verdict TEXT, compile_output TEXT NOT NULL DEFAULT '',
          runtime_ms REAL, memory_kb INTEGER, passed_tests INTEGER NOT NULL DEFAULT 0,
          total_tests INTEGER NOT NULL, results TEXT NOT NULL DEFAULT '[]',
          snapshot TEXT NOT NULL, reason TEXT);
        CREATE UNIQUE INDEX IF NOT EXISTS run_attempt ON submissions(run_id, attempt);
        CREATE INDEX IF NOT EXISTS submissions_created ON submissions(created_at);
        CREATE INDEX IF NOT EXISTS submissions_problem ON submissions(problem_id, id);
        CREATE INDEX IF NOT EXISTS runs_problem ON agent_runs(problem_id, created_at);
        CREATE TABLE IF NOT EXISTS commands (
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES agent_runs(id),
          created_at TEXT NOT NULL, kind TEXT NOT NULL, request TEXT NOT NULL,
          status TEXT NOT NULL, result TEXT);
        CREATE INDEX IF NOT EXISTS commands_run ON commands(run_id, created_at);
        ''')
        if 'allow_workspace' not in {row['name'] for row in c.execute('PRAGMA table_info(problems)')}:
            c.execute('ALTER TABLE problems ADD COLUMN allow_workspace INTEGER NOT NULL DEFAULT 0')
        if 'name' not in {row['name'] for row in c.execute('PRAGMA table_info(testcases)')}:
            c.execute('ALTER TABLE testcases ADD COLUMN name TEXT')
        columns={r['name'] for r in c.execute('PRAGMA table_info(submissions)')}
        for column,kind in [('lease_owner','TEXT'),('lease_expires_at','REAL'),('attempt_count','INTEGER NOT NULL DEFAULT 0')]:
            if column not in columns: c.execute(f'ALTER TABLE submissions ADD COLUMN {column} {kind}')
        c.execute("UPDATE submissions SET status='Finished', verdict='SE', reason='server_interrupted' WHERE status IN ('Compiling','Running') AND lease_owner IS NULL")
        from benchmark.storage import initialize as initialize_benchmarks
        initialize_benchmarks(c)
        c.execute('PRAGMA user_version=2')
        c.execute("UPDATE commands SET status='Finished', result=? WHERE status IN ('Pending','Running')", (json.dumps({'error':'server_interrupted'}),))

def problem(pid, hidden=False, include_deleted=False):
    with connect() as c:
        if hidden: c.execute('BEGIN')
        r = c.execute('SELECT * FROM problems WHERE id=?' + ('' if include_deleted else ' AND deleted=0'), (pid,)).fetchone()
        if not r: return None
        p = dict(r); p['samples'] = json.loads(p['samples'])
        if hidden:
            p['testcases'] = [dict(x) for x in c.execute('SELECT input, expected_output, weight, name FROM testcases WHERE problem_id=? ORDER BY id', (pid,))]
        return p

def problems():
    with connect() as c:
        return [dict(r) for r in c.execute('SELECT id,title,time_limit_ms,memory_limit_mb,allow_workspace FROM problems WHERE deleted=0 ORDER BY id')]

def save_problem(p, pid=None):
    fields = ['title','description','input_description','output_description','time_limit_ms','memory_limit_mb','checker','samples','allow_workspace']
    values = [json.dumps(p[k], ensure_ascii=False) if k=='samples' else (bool(p.get(k,False)) if k=='allow_workspace' else p[k]) for k in fields]
    with connect() as c:
        if pid is None:
            pid = c.execute('INSERT INTO problems ('+','.join(fields)+') VALUES ('+','.join('?' for _ in fields)+')', values).lastrowid
        else:
            if not c.execute('SELECT id FROM problems WHERE id=? AND deleted=0',(pid,)).fetchone(): raise KeyError(pid)
            c.execute('UPDATE problems SET '+','.join(k+'=?' for k in fields)+' WHERE id=?', values+[pid])
            c.execute('DELETE FROM testcases WHERE problem_id=?',(pid,))
        c.executemany('INSERT INTO testcases(problem_id,input,expected_output,weight,name) VALUES(?,?,?,?,?)',[(pid,t['input'],t['expected_output'],t.get('weight',1),t.get('name')) for t in p['testcases']])
    return pid

def delete_problem(pid):
    with connect() as c: return c.execute('UPDATE problems SET deleted=1 WHERE id=? AND deleted=0',(pid,)).rowcount

def create_submission(pid, code, source='human', run_id=None, snapshot=None, final=False, capacity=None):
    p = snapshot or problem(pid, True)
    if not p: raise KeyError(pid)
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if capacity is not None and c.execute("SELECT COUNT(*) FROM submissions WHERE status='Pending'").fetchone()[0]>=capacity: raise OverflowError('Judge queue is full')
        attempt = None
        if run_id:
            r = c.execute('SELECT status FROM agent_runs WHERE id=?',(run_id,)).fetchone()
            if not r or r['status'] not in ('Active','Created'): raise ValueError('Run is not active')
            attempt = c.execute('SELECT COUNT(*)+1 FROM submissions WHERE run_id=?',(run_id,)).fetchone()[0]
        sid = c.execute('''INSERT INTO submissions(problem_id,run_id,attempt,source,language,source_code,created_at,status,total_tests,snapshot)
          VALUES(?,?,?,?,?,?,?,?,?,?)''',(pid,run_id,attempt,source,'cpp17',code,now(),'Pending',len(p['testcases']),json.dumps(p))).lastrowid
        if final:
            if not run_id: raise ValueError('Final submission requires Run')
            c.execute("UPDATE agent_runs SET status='Judging',final_submission_id=? WHERE id=?",(sid,run_id))
    return sid

def submission(sid, internal=False):
    with connect() as c:
        r = c.execute('SELECT * FROM submissions WHERE id=?',(sid,)).fetchone()
    if not r: return None
    d = dict(r); d['results']=json.loads(d['results'])
    if internal: d['snapshot']=json.loads(d['snapshot'])
    else: d.pop('snapshot')
    return d

def submissions(limit=100):
    with connect() as c:
        return [dict(r) for r in c.execute('SELECT id,problem_id,run_id,attempt,source,created_at,status,verdict,runtime_ms,memory_kb,passed_tests,total_tests FROM submissions ORDER BY id DESC LIMIT ?',(limit,))]

def update_submission(sid, owner=None, **fields):
    if 'results' in fields: fields['results']=json.dumps(fields['results'])
    with connect() as c:
        where='id=?'+(' AND lease_owner=? AND status!=\'Finished\' AND lease_expires_at>=?' if owner else '')
        changed=c.execute('UPDATE submissions SET '+','.join(k+'=?' for k in fields)+' WHERE '+where,list(fields.values())+[sid]+([owner,time.time()] if owner else [])).rowcount
        if owner and not changed: raise ValueError('Submission lease lost')
        if fields.get('status')=='Finished':
            c.execute("UPDATE agent_runs SET status='Finished',ended_at=? WHERE final_submission_id=? AND status='Judging'",(now(),sid))

def pending():
    with connect() as c: return [r[0] for r in c.execute("SELECT id FROM submissions WHERE status='Pending' ORDER BY id")]

def create_run(pid, source, metadata, snapshot):
    rid = uuid.uuid4().hex
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        uid=metadata.get('benchmark_unit_id')
        if uid:
            existing=c.execute('SELECT run_id FROM benchmark_units WHERE id=?',(uid,)).fetchone()
            if not existing: raise KeyError(uid)
            if existing['run_id']: return existing['run_id']
        c.execute('INSERT INTO agent_runs(id,problem_id,source,created_at,status,metadata,snapshot) VALUES(?,?,?,?,?,?,?)',(rid,pid,source,now(),'Created',json.dumps(metadata),json.dumps(snapshot)))
        if uid:c.execute('UPDATE benchmark_units SET run_id=? WHERE id=?',(rid,uid))
    return rid

def run(rid, internal=False):
    with connect() as c:
        row = c.execute('SELECT * FROM agent_runs WHERE id=?',(rid,)).fetchone()
        if not row: return None
        d = dict(row); d['metadata']=json.loads(d['metadata'])
        d['submissions']=[dict(r) for r in c.execute('SELECT id,attempt,status,verdict,created_at FROM submissions WHERE run_id=? ORDER BY attempt',(rid,))]
        d['commands']=[dict(r) for r in c.execute('SELECT id,kind,created_at,status,request,result FROM commands WHERE run_id=? ORDER BY created_at',(rid,))]
    for cmd in d['commands']:
        cmd['request']=json.loads(cmd['request']); cmd['result']=json.loads(cmd['result']) if cmd['result'] else None
    if internal: d['snapshot']=json.loads(d['snapshot'])
    else:
        d['problem']={k:v for k,v in json.loads(d.pop('snapshot')).items() if k not in ('testcases','deleted')}
        d.pop('container')
    return d

def update_run(rid, **fields):
    if 'metadata' in fields: fields['metadata']=json.dumps(fields['metadata'])
    with connect() as c: c.execute('UPDATE agent_runs SET '+','.join(k+'=?' for k in fields)+' WHERE id=?',list(fields.values())+[rid])

def runs(problem_id=None, model_name=None, provider=None):
    with connect() as c:
        rows=[dict(r) for r in c.execute('SELECT id,problem_id,source,created_at,status,metadata,final_submission_id FROM agent_runs ORDER BY created_at DESC LIMIT 200')]
    for r in rows: r['metadata']=json.loads(r['metadata'])
    return [r for r in rows if (problem_id is None or r['problem_id']==problem_id) and (model_name is None or r['metadata'].get('model_name')==model_name) and (provider is None or r['metadata'].get('provider')==provider)]

def create_command(rid, kind, request):
    cid=uuid.uuid4().hex
    with connect() as c: c.execute('INSERT INTO commands VALUES(?,?,?,?,?,?,NULL)',(cid,rid,now(),kind,json.dumps(request),'Pending'))
    return cid

def update_command(cid, status, result=None):
    with connect() as c: c.execute('UPDATE commands SET status=?,result=? WHERE id=?',(status,json.dumps(result) if result is not None else None,cid))

def command(cid):
    with connect() as c: r=c.execute('SELECT * FROM commands WHERE id=?',(cid,)).fetchone()
    if not r: return None
    d=dict(r); d['request']=json.loads(d['request']); d['result']=json.loads(d['result']) if d['result'] else None
    return d


def claim_submission(owner,sid=None,lease_seconds=SUBMISSION_LEASE_SECONDS):
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        # Unknown execution after crash is terminal SE, not a silent model failure
        # and not an automatic re-run that could overwrite an existing result.
        c.execute("UPDATE submissions SET status='Finished',verdict='SE',reason='worker_lease_expired' WHERE status IN ('Compiling','Running') AND lease_expires_at<?",(time.time(),))
        c.execute("UPDATE agent_runs SET status='Finished',ended_at=? WHERE status='Judging' AND final_submission_id IN (SELECT id FROM submissions WHERE status='Finished')",(now(),))
        row=c.execute("SELECT id FROM submissions WHERE status='Pending'"+(' AND id=?' if sid is not None else '')+' ORDER BY id LIMIT 1',([sid] if sid is not None else [])).fetchone()
        if not row:return None
        c.execute("UPDATE submissions SET status='Compiling',lease_owner=?,lease_expires_at=?,attempt_count=attempt_count+1 WHERE id=?",(owner,time.time()+lease_seconds,row['id']))
        return row['id']

def renew_submission(sid,owner,lease_seconds=SUBMISSION_LEASE_SECONDS):
    with connect() as c:
        return c.execute("UPDATE submissions SET lease_expires_at=? WHERE id=? AND lease_owner=? AND status IN ('Compiling','Running') AND lease_expires_at>=?",(time.time()+lease_seconds,sid,owner,time.time())).rowcount
