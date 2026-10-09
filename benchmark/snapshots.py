"""Trusted local-only termination capture. Never expose this as an Agent tool."""
import hashlib
import json
import time


def capture(run_id):
    """Freeze all sandbox processes before copying, then leave it for cleanup.

    A remote Runner without access to the owning DB/runtime returns unknown;
    it must not substitute a current file read for a termination snapshot.
    No path is supplied by the model and symlinks/nonregular files are refused.
    The trusted inspector runs in its own cgroup; sharing a PID namespace does not unpause or execute code in the target.
    """
    from minioj import db, config
    from minioj.docker_backend import docker
    try:
        run=db.run(run_id,True)
        if not run or run['status']!='Active' or not run.get('container'):
            return None
        name=run['container']
        # Verify the DB/instance association before controlling a container.
        instance=docker(['inspect','--format','{{index .Config.Labels "minioj.instance"}}',name],timeout=5).decode().strip()
        if instance!=str(config.DB_PATH):return None
        paused=docker(['inspect','--format','{{.State.Paused}}',name],timeout=5).strip()==b'true'
        if not paused:docker(['pause',name],timeout=5)
        frozen_at=time.time()
        # Docker archive-copy does not expose tmpfs content on all Engines.
        # A trusted short-lived inspector shares only the target PID namespace
        # and reads its root through /proc. Target stays paused throughout.
        # No user code runs in the inspector, no host mounts/socket/privileges.
        reader="""import base64,json,os,stat
fd=os.open('/proc/1/root/workspace/main.cpp',os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
try:
 s=os.fstat(fd)
 if not stat.S_ISREG(s.st_mode) or s.st_size>262144:raise ValueError('not small regular source')
 with os.fdopen(fd,'rb',closefd=False) as f:data=f.read(262145)
 if len(data)>262144:raise ValueError('source too large')
 print(json.dumps({'content_b64':base64.b64encode(data).decode()}))
finally:os.close(fd)
"""
        image=docker(['inspect','--format','{{.Image}}',name],timeout=5).decode().strip()
        labels=['--label','minioj.managed=1','--label','minioj.instance='+str(config.DB_PATH)]
        import os
        if os.environ.get('MINIOJ_TEST_SESSION'):labels+=['--label','minioj.test-session='+os.environ['MINIOJ_TEST_SESSION']]
        result=docker(['run','--rm',*labels,'--network','none','--read-only','--cap-drop','ALL',
                      '--security-opt','no-new-privileges','--user','1000:1000',
                      '--memory','64m','--memory-swap','64m','--pids-limit','8',
                      '--pid','container:'+name,image,'python3','-S','-c',reader],timeout=10)
        import base64
        raw=base64.b64decode(json.loads(result)['content_b64'],validate=True)
        if len(raw)>config.SOURCE_LIMIT:return None
        content=raw.decode('utf-8')
        return {'content':content,'sha256':hashlib.sha256(raw).hexdigest(),
                'captured_at':time.time(),'frozen_at':frozen_at,
                'provenance':'paused_container_copy_before_cleanup'}
    except Exception:
        # No invented contents on missing DB, pause/copy failure, or invalid UTF8.
        return None
