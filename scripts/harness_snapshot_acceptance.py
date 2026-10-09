"""Real Docker proof that termination capture freezes concurrent source writers."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import uuid
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    session='snapshot-'+uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix='minioj-snapshot-') as data:
        os.environ.update(MINIOJ_DATA=data,MINIOJ_TEST_SESSION=session,MINIOJ_JUDGE_BACKEND='docker')
        from minioj import db
        from minioj.workspace import WorkspaceManager
        from minioj.docker_backend import docker
        from benchmark.snapshots import capture
        db.initialize();manager=WorkspaceManager();rid=None
        try:
            pid=db.save_problem({'title':'snapshot fixture','description':'','input_description':'','output_description':'','time_limit_ms':1000,'memory_limit_mb':64,'checker':'trimmed','samples':[],'testcases':[{'input':'','expected_output':''}],'allow_workspace':True})
            rid=manager.create(pid,'agent',{'feedback_policy':'final_only'})
            manager.file_action(rid,'write','main.cpp','int main(){return 0;}')
            name=db.run(rid,True)['container']
            # Trusted adversarial fixture, using the normal restricted container.
            writer="while true; do printf 'int main(){return 0;}' > replacement.cpp; mv replacement.cpp main.cpp; printf 'int main(){return 1;}' > replacement.cpp; mv replacement.cpp main.cpp; done"
            docker(['exec','-d',name,'/bin/sh','-c',writer]);time.sleep(.05)
            snap=capture(rid);assert snap and snap['provenance']=='paused_container_copy_before_cleanup'
            assert docker(['inspect','--format','{{.State.Paused}}',name]).strip()==b'true'
            time.sleep(.1)
            repeated=capture(rid)
            # Already paused containers are still readable through inspector;
            # capture() accepts pause idempotency below.
            assert repeated and repeated['sha256']==snap['sha256']
            manager.destroy(rid);rid=None
            assert not docker(['ps','-aq','--filter','label=minioj.test-session='+session]).strip()
            rid=manager.create(pid,'agent',{'feedback_policy':'final_only'})
            name=db.run(rid,True)['container'];docker(['exec',name,'ln','-s','/etc/passwd','malicious.cpp']);docker(['exec',name,'mv','malicious.cpp','main.cpp'])
            assert capture(rid) is None
            manager.destroy(rid);rid=None
            assert not docker(['ps','-aq','--filter','label=minioj.test-session='+session]).strip()
            report={'symlink_rejected':True,'status':'passed','real_docker':True,'concurrent_writer_frozen':True,'copy_hash_stable':True,'cleanup':True}
            a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,indent=2));print(json.dumps(report))
        finally:
            if rid:manager.destroy(rid)
if __name__=='__main__':main()
