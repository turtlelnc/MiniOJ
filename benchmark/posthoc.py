"""Read-only historical recovery and standalone rejudging, never DB updates."""
import hashlib
import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Harness-only changes need not invalidate the unchanged Judge implementation.
JUDGE_FILES = ('minioj/config.py', 'minioj/db.py', 'minioj/workspace.py', 'minioj/app.py', 'Dockerfile', 'minioj/judge.py', 'minioj/checker.py',
               'minioj/docker_backend.py', 'minioj/runner.py', 'minioj/launcher.py',
               'scripts/container_judge.py', 'scripts/container_exec.py',
               'scripts/container_files.py', 'scripts/container_idle.py', 'scripts/container_cleanup.py')


def code_sha(code): return hashlib.sha256(code.encode()).hexdigest()


def recover(unit, reviewed_sha=None):
    """Legacy last writes alone are NOT a trustworthy termination snapshot.

    For old data, a human-reviewed SHA acknowledges all subsequent commands
    were inspected. Future snapshots are captured by Runner before cleanup.
    No current workspace or candidate file is consulted here.
    """
    r = unit['record']; snap = r.get('termination_code')
    if snap and snap.get('provenance') in ('paused_container_copy_before_cleanup','final_submission_source') and code_sha(snap['content']) == snap.get('sha256'):
        return {**snap, 'status': 'available'}
    writes = []
    successful = {m.get('tool_call_id') for m in r.get('messages', []) if m.get('role')=='tool' and
                  isinstance((res:=_result(m)), dict) and 'size' in res and 'error' not in res}
    for m in r.get('messages', []):
        for tc in m.get('tool_calls', []):
            try: args = json.loads(tc['function']['arguments'])
            except (ValueError, KeyError, TypeError): continue
            if tc['function']['name']=='write_file' and args.get('path')=='main.cpp' and tc['id'] in successful:
                writes.append(args['content'])
    if writes and reviewed_sha and code_sha(writes[-1]) == reviewed_sha:
        return {'status':'available', 'content':writes[-1], 'sha256':reviewed_sha,
                'provenance':'last_successful_write_with_explicit_terminal_mutation_review'}
    return {'status':'unknown', 'reason':'no_reliable_termination_snapshot'}


def _result(message):
    try: return json.loads(message.get('content', 'null'))
    except (ValueError, TypeError): return None


def judge_compatibility(root, commit):
    root = Path(root); observations = {}
    for path in JUDGE_FILES:
        try:
            old = subprocess.check_output(['git','show',f'{commit}:{path}'],cwd=root,stderr=subprocess.DEVNULL)
            current = (root/path).read_bytes()
        except (OSError, subprocess.CalledProcessError):
            return {'compatible':False,'reason':'judge_source_unavailable'}
        observations[path] = hashlib.sha256(current).hexdigest()
        if old != current: return {'compatible':False,'reason':'judge_source_changed','file':path}
    return {'compatible':True,'files_sha256':observations}


def rejudge(experiment, unit, source, root, session_factory=None):
    result = {'id':uuid.uuid4().hex, 'created_at':datetime.now(timezone.utc).isoformat(),
              'unit_id':unit['id'], 'run_id':unit.get('run_id'), 'status':'unknown', 'verdict':None,
              'source_sha256':source.get('sha256'), 'source_provenance':source.get('provenance')}
    if source.get('status')!='available' or code_sha(source.get('content',''))!=source.get('sha256'):
        return {**result,'reason':'source_unavailable_or_hash_mismatch'}
    manifest = experiment['manifest']
    problem = next((p for p in manifest.get('problem_snapshots',[]) if p['id']==unit['problem_id']),None)
    if not problem or not problem.get('testcases'):return {**result,'reason':'frozen_tests_unavailable'}
    compatibility = judge_compatibility(root, manifest.get('git_commit'))
    result['judge_compatibility'] = compatibility
    if not compatibility['compatible']:return {**result,'reason':compatibility['reason']}
    image = manifest.get('environment_information',{}).get('image_id')
    if manifest.get('judge_backend')!='docker' or not image:return {**result,'reason':'original_docker_image_identity_unavailable'}
    result.update(image_id=image, original_judge_fingerprint=problem.get('_judge_fingerprint'),
                  tests_sha256=hashlib.sha256(json.dumps(problem['testcases'],sort_keys=True).encode()).hexdigest())
    if session_factory is None:
        from minioj.docker_backend import DockerJudgeSession
        session_factory = DockerJudgeSession
    from minioj.judge import execution_verdict
    try:
        with session_factory(image=image) as session:
            compiled = session.compile(source['content'])
            if compiled.infrastructure_error or compiled.returncode is None:
                return {**result,'reason':'compile_infrastructure_failure'}
            verdict = 'CE' if compiled.returncode or compiled.reason else 'AC'; passed=0
            if verdict=='AC':
                for tc in problem['testcases']:
                    verdict = execution_verdict(session.run(tc['input'].encode(),problem['time_limit_ms'],problem['memory_limit_mb']),tc['expected_output'].encode(),problem['checker'])
                    if verdict=='SE':return {**result,'reason':'judge_infrastructure_failure'}
                    if verdict!='AC':break
                    passed+=1
        return {**result,'status':'verified','verdict':verdict,'passed_tests':passed,'total_tests':len(problem['testcases'])}
    except Exception as exc:
        return {**result,'reason':'environment_unavailable','exception_type':type(exc).__name__}
