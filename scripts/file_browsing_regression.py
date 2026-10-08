import asyncio,json,time
from pathlib import Path
import httpx,websockets
root=Path(__file__).resolve().parent.parent
(root/'evidence').mkdir(exist_ok=True)
token=(root/'data/api-token').read_text().strip()
c=httpx.Client(base_url='http://127.0.0.1:8000/api',headers={'X-MiniOJ-Token':token},timeout=60,trust_env=False)
r=c.post('/agent-runs',json={'problem_id':1,'source':'human','metadata':{'test':'file browsing regression'}});r.raise_for_status();rid=r.json()['id']
report={'run_id':rid,'read_while_terminal':[]}
async def test():
    async with websockets.connect(f'ws://127.0.0.1:8000/api/agent-runs/{rid}/terminal',additional_headers={'X-MiniOJ-Token':token},proxy=None) as ws:
        await ws.send(json.dumps({'type':'input','data':'printf "browse-ready\\n"\r'}))
        received=''
        while 'browse-ready' not in received: received+=await asyncio.wait_for(ws.recv(),5)
        r=c.get(f'/agent-runs/{rid}/files');r.raise_for_status()
        for path in ['main.cpp','problem.json','sample.in','sample.out']:
            r=c.get(f'/agent-runs/{rid}/file',params={'path':path});r.raise_for_status()
            assert r.json()['content']=='' if path=='main.cpp' else r.json()['content'],path
            report['read_while_terminal'].append(path)
        assert c.put(f'/agent-runs/{rid}/file',json={'path':'main.cpp','content':'must not write'}).status_code==409
        assert c.post(f'/agent-runs/{rid}/commands',json={'command':'true'}).status_code==409
        report['writes_and_commands_remain_exclusive']=True
        await ws.send(json.dumps({'type':'input','data':'exit\r'}))
    for _ in range(100):
        r=c.get(f'/agent-runs/{rid}').json()
        if all(cmd['status']=='Finished' for cmd in r['commands'] if cmd['kind']=='terminal'): break
        await asyncio.sleep(.05)
    r=c.put(f'/agent-runs/{rid}/file',json={'path':'main.cpp','content':'// saved after terminal closed\n'});r.raise_for_status()
    report['write_after_close']=True
try:
    asyncio.run(test())
    (root/'evidence'/'file-browsing-regression.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
finally: c.delete(f'/agent-runs/{rid}/environment').raise_for_status()
