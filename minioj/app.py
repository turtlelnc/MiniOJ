import asyncio, contextlib, fcntl, hmac, json, os, pty, signal, struct, subprocess, termios
from contextlib import asynccontextmanager
from typing import Literal
from urllib.parse import urlsplit
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
from . import config, db
from .docker_backend import DockerError, available, docker
from .judge import JudgeQueue
from .workspace import WorkspaceManager
judge_queue=JudgeQueue(); workspaces=WorkspaceManager()

@asynccontextmanager
async def lifespan(app):
    db.initialize(); workspaces.start(); judge_queue.start()
    yield
    workspaces.close(); judge_queue.close()
app=FastAPI(title='MiniOJ',version='0.1.0',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url='/api/openapi.json')
ALLOWED_HOSTS={'127.0.0.1','localhost','::1'}
def valid_host(host):
    try: return urlsplit('http://'+host).hostname in ALLOWED_HOSTS
    except ValueError: return False

def same_origin(origin,host):
    try:
        u=urlsplit(origin)
        return u.scheme in ('http','https') and u.netloc==host and u.hostname in ALLOWED_HOSTS
    except ValueError: return False

def authenticated(headers,cookies):
    token=headers.get('x-minioj-token') or cookies.get('minioj_token','')
    return hmac.compare_digest(token,config.TOKEN)

@app.middleware('http')
async def protect(request:Request,call_next):
    host=request.headers.get('host','')
    if not valid_host(host): return JSONResponse({'detail':'Invalid Host'},status_code=403)
    origin=request.headers.get('origin')
    if origin and not same_origin(origin,host): return JSONResponse({'detail':'Cross-origin access denied'},status_code=403)
    if request.url.path.startswith('/api/'):
        if not authenticated(request.headers,request.cookies): return JSONResponse({'detail':'API token required'},status_code=401)
        if request.method in ('POST','PUT','PATCH'):
            body=bytearray()
            async for chunk in request.stream():
                body+=chunk
                if len(body)>2*1024*1024: return JSONResponse({'detail':'Request too large'},status_code=413)
            request._body=bytes(body)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Cache-Control']='no-store'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self' ws://127.0.0.1:* ws://localhost:*; frame-ancestors 'none'"
    return response

@app.exception_handler(DockerError)
async def docker_error(request,exc): return JSONResponse({'detail':str(exc)},status_code=503)
@app.exception_handler(PermissionError)
async def denied(request,exc): return JSONResponse({'detail':str(exc)},status_code=403)
@app.exception_handler(KeyError)
async def missing(request,exc): return JSONResponse({'detail':'Not found'},status_code=404)
@app.exception_handler(ValueError)
async def bad_value(request,exc): return JSONResponse({'detail':str(exc)},status_code=409)
@app.exception_handler(OverflowError)
async def overloaded(request,exc): return JSONResponse({'detail':str(exc)},status_code=429)

class Case(BaseModel):
    name:str|None=Field(default=None,max_length=512)
    input:str=Field(max_length=131072)
    expected_output:str=Field(max_length=131072)
    weight:float=Field(default=1,gt=0,le=1000)
class ProblemInput(BaseModel):
    title:str=Field(min_length=1,max_length=200)
    description:str=Field(default='',max_length=32768)
    input_description:str=Field(default='',max_length=8192)
    output_description:str=Field(default='',max_length=8192)
    time_limit_ms:int=Field(default=1000,ge=100,le=10000)
    memory_limit_mb:int=Field(default=128,ge=32,le=256)
    checker:Literal['exact','trimmed']='trimmed'
    allow_workspace:bool=False
    samples:list[Case]=Field(default_factory=list,max_length=10)
    testcases:list[Case]=Field(min_length=1,max_length=100)
    @model_validator(mode='after')
    def total(self):
        if sum(len(t.input.encode())+len(t.expected_output.encode()) for t in [*self.testcases,*self.samples])>1024*1024: raise ValueError('Test data exceeds 1 MiB')
        return self
class SubmissionInput(BaseModel):
    problem_id:int
    language:Literal['cpp17']='cpp17'
    source_code:str=Field(min_length=1,max_length=config.SOURCE_LIMIT)
class RunInput(BaseModel):
    problem_id:int
    source:Literal['human','agent']='agent'
    environment:bool=True
    feedback_policy:Literal['final_only','iterative']='final_only'
    metadata:dict=Field(default_factory=dict)
    @model_validator(mode='after')
    def bound(self):
        if len(json.dumps(self.metadata).encode())>65536: raise ValueError('Metadata too large')
        return self
class CommandInput(BaseModel):
    command:str=Field(min_length=1,max_length=8192)
    timeout_ms:int=Field(default=30000,ge=100,le=120000)
    stdin:str=Field(default='',max_length=131072)
class FileInput(BaseModel):
    path:str=Field(default='main.cpp',min_length=1,max_length=512)
    content:str=Field(max_length=config.SOURCE_LIMIT)
class RunSubmission(BaseModel):
    path:str=Field(default='main.cpp',max_length=512)
    source_code:str|None=Field(default=None,max_length=config.SOURCE_LIMIT)
class FinishInput(BaseModel): final_submission_id:int

@app.get('/api/health')
def health(): return {'status':'ok','judge_backend':config.JUDGE_BACKEND,'sandbox_available':available(),'workspace_limits':{'wall_seconds':900,'cpu_seconds':120,'memory_mb':512,'workspace_mb':64,'pids':64,'network':False},'feedback_default':'final_only'}
@app.get('/api/problems')
def list_problems(): return db.problems()
@app.get('/api/problems/{pid}')
def get_problem(pid:int):
    p=db.problem(pid)
    if not p: raise KeyError(pid)
    return p
@app.post('/api/admin/testcases/import-zip')
async def import_zip(request:Request):
    from .zip_import import import_cases,ZipImportError
    try: return {'testcases':import_cases(await request.body())}
    except ZipImportError as e: raise HTTPException(422,str(e))

@app.get('/api/admin/problems/{pid}')
def admin_problem(pid:int):
    p=db.problem(pid,True)
    if not p: raise KeyError(pid)
    return p
@app.post('/api/problems',status_code=201)
def create_problem(p:ProblemInput): return {'id':db.save_problem(p.model_dump())}
@app.put('/api/problems/{pid}')
def edit_problem(pid:int,p:ProblemInput): return {'id':db.save_problem(p.model_dump(),pid)}
@app.delete('/api/problems/{pid}')
def delete_problem(pid:int):
    if not db.delete_problem(pid): raise KeyError(pid)
    return {'deleted':True}
@app.post('/api/submissions',status_code=202)
def submit(s:SubmissionInput):
    if len(s.source_code.encode())>config.SOURCE_LIMIT: raise HTTPException(413,'Source too large')
    return {'submission_id':judge_queue.submit(s.problem_id,s.source_code)}
@app.get('/api/submissions')
def list_submissions(): return db.submissions()
@app.get('/api/submissions/{sid}')
def get_submission(sid:int):
    s=db.submission(sid)
    if not s: raise KeyError(sid)
    return s
@app.post('/api/agent-runs',status_code=201)
def create_run(r:RunInput):
    metadata=r.metadata.copy(); metadata['feedback_policy']=r.feedback_policy
    return db.run(workspaces.create(r.problem_id,r.source,metadata,r.environment))
@app.get('/api/agent-runs')
def list_runs(problem_id:int|None=None,model_name:str|None=None,provider:str|None=None): return db.runs(problem_id,model_name,provider)
@app.get('/api/agent-runs/{rid}')
def get_run(rid:str):
    r=db.run(rid)
    if not r: raise KeyError(rid)
    return r
@app.patch('/api/agent-runs/{rid}')
def patch_run(rid:str,metadata:dict):
    r=db.run(rid)
    if not r: raise KeyError(rid)
    if len(json.dumps(metadata).encode())>65536: raise HTTPException(413,'Metadata too large')
    merged={**r['metadata'],**metadata}; merged['feedback_policy']=r['metadata']['feedback_policy']
    if len(json.dumps(merged).encode())>65536: raise HTTPException(413,'Metadata too large')
    db.update_run(rid,metadata=merged); return db.run(rid)
@app.post('/api/agent-runs/{rid}/commands',status_code=202)
def run_command(rid:str,c:CommandInput): return {'command_id':workspaces.command(rid,c.command,c.timeout_ms,c.stdin)}
@app.get('/api/commands/{cid}')
def command_result(cid:str):
    c=db.command(cid)
    if not c: raise KeyError(cid)
    return c
@app.get('/api/agent-runs/{rid}/files')
def list_files(rid:str): return workspaces.file_action(rid,'list')
@app.get('/api/agent-runs/{rid}/file')
def get_file(rid:str,path:str='main.cpp'): return workspaces.file_action(rid,'read',path)
@app.put('/api/agent-runs/{rid}/file')
def put_file(rid:str,f:FileInput):
    if len(f.content.encode())>config.SOURCE_LIMIT: raise HTTPException(413,'File too large')
    return workspaces.file_action(rid,'write',f.path,f.content)
@app.post('/api/agent-runs/{rid}/submissions',status_code=202)
def run_submit(rid:str,s:RunSubmission):
    r=db.run(rid,True)
    if not r: raise KeyError(rid)
    if r['metadata']['feedback_policy']=='final_only': return {'submission_id':workspaces.finalize(rid,judge_queue,s.path,s.source_code)}
    with workspaces.lock:
        if rid in workspaces.busy: raise ValueError('Workspace busy')
        code=s.source_code
        if code is None: code=workspaces.file_action(rid,'read',s.path)['content']
        if not code or len(code.encode())>config.SOURCE_LIMIT: raise ValueError('Invalid source')
        return {'submission_id':judge_queue.submit(r['problem_id'],code,r['source'],rid,r['snapshot'])}
@app.post('/api/agent-runs/{rid}/final-submit',status_code=202)
def final_submit(rid:str,s:RunSubmission): return {'submission_id':workspaces.finalize(rid,judge_queue,s.path,s.source_code)}
@app.post('/api/agent-runs/{rid}/finish')
def finish_run(rid:str,f:FinishInput):
    with workspaces.lock:
        r=db.run(rid)
        if not r: raise KeyError(rid)
        s=db.submission(f.final_submission_id)
        if not s or s['run_id']!=rid or s['status']!='Finished': raise ValueError('Choose a finished submission belonging to this run')
        if r['status'] not in ('Active','Created'): raise ValueError('Run is not active')
        if rid in workspaces.busy: raise ValueError('Workspace busy')
        workspaces.destroy(rid)
        db.update_run(rid,status='Finished',final_submission_id=s['id'],ended_at=db.now())
        return db.run(rid)
@app.delete('/api/agent-runs/{rid}/environment')
def destroy_environment(rid:str):
    workspaces.destroy(rid); return db.run(rid)

@app.websocket('/api/agent-runs/{rid}/terminal')
async def terminal(ws:WebSocket,rid:str):
    host=ws.headers.get('host',''); origin=ws.headers.get('origin')
    if not valid_host(host) or (origin and not same_origin(origin,host)) or not authenticated(ws.headers,ws.cookies):
        await ws.close(code=1008); return
    try: r=await asyncio.to_thread(workspaces.reserve,rid)
    except Exception:
        await ws.close(code=1008); return
    used=sum(len((c.get('result') or {}).get('stdout','').encode())+len((c.get('result') or {}).get('stderr','').encode()) for c in r['commands'])
    if sum(c['kind'] in ('command','terminal') for c in r['commands'])>=100 or used>=workspaces.OUTPUT_BUDGET:
        workspaces.release(rid); await ws.close(code=1008); return
    output_limit=min(config.OUTPUT_LIMIT,workspaces.OUTPUT_BUDGET-used)
    cid=db.create_command(rid,'terminal',{'terminal':'bash','protocol':'json input/resize, text output'})
    db.update_command(cid,'Running')
    master=slave=None; p=None; transcript=bytearray(); inputs=bytearray(); reason='closed'
    try:
        master,slave=pty.openpty()
        fcntl.ioctl(slave,termios.TIOCSWINSZ,struct.pack('HHHH',24,100,0,0))
        p=subprocess.Popen([config.DOCKER,*(['--context',config.DOCKER_CONTEXT] if config.DOCKER_CONTEXT else []),'exec','-it','-e','TERM=xterm',r['container'],'/bin/bash','--noprofile','--norc'],stdin=slave,stdout=slave,stderr=slave,start_new_session=True)
        os.close(slave); slave=None; os.set_blocking(master,False)
        await ws.accept()
        decoder=__import__('codecs').getincrementaldecoder('utf-8')('replace')
        async def output():
            nonlocal reason
            while True:
                try: data=os.read(master,8192)
                except BlockingIOError:
                    if p.poll() is not None: break
                    await asyncio.sleep(.02); continue
                except OSError: break
                if not data: break
                if len(transcript)+len(data)>output_limit:
                    reason='output_limit'; await ws.send_text('\r\n[Terminal output limit reached]\r\n'); break
                transcript.extend(data); await ws.send_text(decoder.decode(data))
        async def incoming():
            while True:
                data=json.loads(await ws.receive_text())
                if data.get('type')=='input':
                    encoded=str(data.get('data','')).encode()
                    if len(encoded)>8192 or len(inputs)+len(encoded)>config.SOURCE_LIMIT: raise ValueError('Terminal input limit exceeded')
                    inputs.extend(encoded)
                    offset=0
                    while offset<len(encoded):
                        try: offset+=os.write(master,encoded[offset:])
                        except BlockingIOError: await asyncio.sleep(.01)
                elif data.get('type')=='resize':
                    rows=max(5,min(100,int(data.get('rows',24)))); cols=max(20,min(240,int(data.get('cols',100))))
                    fcntl.ioctl(master,termios.TIOCSWINSZ,struct.pack('HHHH',rows,cols,0,0))
        tasks=[asyncio.create_task(output()),asyncio.create_task(incoming())]
        try:
            done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED,timeout=300)
            if not done: reason='terminal_timeout'
            for task in done: task.result()
        finally:
            for task in tasks: task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
    except (WebSocketDisconnect,ValueError,json.JSONDecodeError): pass
    except Exception as e: reason=str(e)[:1000]
    finally:
        if p:
            try: os.killpg(p.pid,signal.SIGKILL)
            except ProcessLookupError: pass
            await asyncio.to_thread(p.wait)
        if master is not None: os.close(master)
        if slave is not None: os.close(slave)
        if r['container']:
            try:
                await asyncio.to_thread(docker,['exec',r['container'],'python3','/opt/container_cleanup.py'],None,5)
            except Exception: pass
        db.update_command(cid,'Finished',{'stdout':transcript.decode(errors='replace'),'stdin':inputs.decode(errors='replace'),'reason':reason})
        workspaces.release(rid)
        with contextlib.suppress(Exception): await ws.close()

app.mount('/static',StaticFiles(directory=config.ROOT/'static'),name='static')
@app.get('/{path:path}',include_in_schema=False)
def page(path:str,request:Request):
    if path.startswith('api/'): raise HTTPException(404,'Not found')
    response=FileResponse(config.ROOT/'static'/'index.html')
    response.set_cookie('minioj_token',config.TOKEN,httponly=True,samesite='strict',path='/')
    return response
