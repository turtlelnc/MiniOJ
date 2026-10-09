"""Standalone private diagnostic; never mutates MiniOJ database or old scores."""
import argparse
import hashlib
import json
import sys
import os
import tempfile
import uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from benchmark.posthoc import recover,rejudge


def main():
    p=argparse.ArgumentParser();p.add_argument('--experiment',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--review',type=Path);p.add_argument('--unit-id');a=p.parse_args()
    if a.output.resolve()==a.experiment.resolve():p.error('Output must be separate from input')
    before=a.experiment.read_bytes();e=json.loads(before)
    review=json.loads(a.review.read_text()) if a.review else {}
    shas=review.get('sources',{}) if review.get('trajectories_sha256')==hashlib.sha256(before).hexdigest() else {}
    results=[];session='posthoc-'+uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix='minioj-posthoc-') as private:
        os.environ.update(MINIOJ_DATA=private,MINIOJ_TEST_SESSION=session)
        try:
            for u in e['units']:
                if a.unit_id and u['id']!=a.unit_id:continue
                if u['status'] not in ('Finished','Failed'):continue
                source=recover(u,shas.get(str(u['ordinal'])))
                results.append(rejudge(e,u,source,ROOT))
        finally:
            if 'minioj.docker_backend' in sys.modules:
                from minioj.docker_backend import docker,remove_container,DockerError
                try:
                    for name in docker(['ps','-aq','--filter','label=minioj.test-session='+session]).decode().splitlines():remove_container(name)
                except DockerError:pass  # Results already record unavailable environment.
    assert a.experiment.read_bytes()==before,'Read-only evidence changed'
    a.output.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive output avoids overwriting an earlier independent diagnostic.
    from benchmark.diagnostics import diagnostics
    with a.output.open('x') as f:json.dump({'results':results,'original_unchanged':True,'diagnostics':diagnostics(e['units'],{r['unit_id']:r for r in results})},f,indent=2)
    print('verified',sum(r['status']=='verified' for r in results),'unknown',sum(r['status']=='unknown' for r in results))
if __name__=='__main__':main()
