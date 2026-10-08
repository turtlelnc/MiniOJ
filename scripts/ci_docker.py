"""Docker Engine integration CI. Never starts Colima or reads the real database.

Private databases/raw logs/exports are deleted. Only the explicit public JSON
schema below can become CI artifacts; raw logs and manifests are never copied.
"""
import argparse
import json
import os
import re
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import tempfile
import time
import uuid

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
RESOURCE_NUMBERS=('returncode','transport_exit_code','termination_signal','runtime_ms',
                  'memory_kb','container_peak_memory_kb','process_peak_rss_kb',
                  'container_baseline_memory_kb','cpu_time_ms','observed_forks')
RESOURCE_REASONS={None,'timeout','cpu_timeout','memory_limit','output_limit','infrastructure_error'}
RESOURCE_CASES=set(('normal infinite_cpu allocation short_peak fork_limit detached_child infinite_output crash memory_and_timeout near_deadline_memory under_limit_peak normal_baseline sustained_16mb short_16mb child_16mb tmpfs_counted_as_container_memory new_pid_failure_with_successful_exit historical_pid_failure_with_successful_exit supervisor_killed_is_se self_sent_sigxcpu_is_re supervisor_report_pipe_protected oomkilled_container_metrics_unavailable exit_zero exit_one exit_137 self_sigxcpu self_sigkill self_sigxfsz exact_output abnormal_crash cpu_deadline wall_deadline output_deadline stderr_not_memory_evidence supervisor_failure docker_cli_failure completed_signal_before_delayed_observation').split())
METRIC_NUMBERS=('planned_units','completed_units','pending_units','running_units',
                'evaluable','excluded','solved','solve_rate','evaluable_solve_rate',
                'end_to_end_success_rate','end_to_end_success_rate_denominator',
                'final_end_to_end_success_rate','pass@1','pass@1_denominator',
                'mean_total_tokens','usage_observed_units','tokens_per_solved_problem')


def number(value):
    import math
    return value if type(value) in (int,float) and math.isfinite(value) else None


def safe_resource(row):
    # Never retain stdout/stderr, arbitrary errors, container names or paths.
    case=row.get('case','unknown')
    case=case if isinstance(case,str) and case in RESOURCE_CASES else 'unknown'
    reason=row.get('reason')
    out={'case':case,'reason':reason if (reason is None or isinstance(reason,str)) and reason in RESOURCE_REASONS else 'unknown'}
    out.update({key:number(row.get(key)) for key in RESOURCE_NUMBERS})
    state=row.get('container_state') or {}
    out['oom_killed']=state.get('OOMKilled') if type(state.get('OOMKilled')) is bool else None
    metrics=row.get('cgroup') or {}
    out['event_deltas']={group:{key:number((metrics.get(group) or {}).get(key)) for key in fields}
                         for group,fields in [('memory',('oom_kill_delta','max_delta')),('pids',('max_delta',)),('cpu',('usage_usec_delta',))]}
    return out


def safe_benchmark(experiment):
    # No manifest, public samples, model codes, messages, identity or errors.
    summary=experiment.get('summary',{})
    out={'protocol':summary.get('protocol') if summary.get('protocol') in ('final_only','iterative') else 'unknown'}
    overall=summary.get('overall',{})
    out.update({key:number(overall.get(key)) for key in METRIC_NUMBERS})
    out['verdict_counts']={key:number((overall.get('verdict_counts') or {}).get(key)) for key in ('AC','WA','RE','CE','TLE','MLE','SE')}
    out['failure_breakdown']={category:{key:number(((overall.get('failure_breakdown') or {}).get(category) or {}).get(key)) for key in ('count','rate','share_of_failures')}
                              for category in ('solution_failure','agent_failure','model_failure','judge_failure','infrastructure_failure')}
    return out


def diagnostics(log):
    # Assertion values and exception messages may contain private input. Keep
    # only existing repository source locations and standard exception types.
    frames=[]
    for filename,line in re.findall(r'File "([^"\n]+)", line (\d+)',log):
        path=Path(filename)
        try:relative=path.resolve().relative_to(ROOT)
        except ValueError:continue
        if path.is_file() and relative.parts[0] in ('scripts','tests','minioj','benchmark'):
            frames.append({'file':str(relative),'line':int(line)})
    types=re.findall(r'^(AssertionError|RuntimeError|TimeoutError|HTTPStatusError|DockerError|OSError|ValueError|KeyError|TypeError|ImportError|ModuleNotFoundError)(?::|$)',log,re.MULTILINE)
    return {'frames':frames[-8:],'exception_type':types[-1] if types else None}


def stop_process(p):
    if p is None:return
    try:os.killpg(p.pid,signal.SIGTERM)
    except ProcessLookupError:pass
    try:p.wait(timeout=15)
    except subprocess.TimeoutExpired:
        try:os.killpg(p.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        p.wait(timeout=5)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output=args.output.resolve();args.output.mkdir(parents=True,exist_ok=True)
    report={'status':'running','checks':[],'resources':[],'benchmarks':[],'capabilities':{},'cleanup':{}}
    session=uuid.uuid4().hex;server=None;server_ready=False
    started=time.monotonic();deadline=started+900
    def save():
        (args.output/'docker-results.json').write_text(json.dumps(report,indent=2))
    def interrupt(signum,frame):raise RuntimeError('integration_interrupted')
    signal.signal(signal.SIGTERM,interrupt)
    with tempfile.TemporaryDirectory(prefix='minioj-docker-ci-') as private_dir:
        private=Path(private_dir);data=private/'data';evidence=private/'evidence';data.mkdir();evidence.mkdir()
        # Explicitly disjoint from the upload directory.
        if args.output==private or args.output.is_relative_to(private):raise ValueError('artifact directory cannot be private')
        token=secrets.token_urlsafe(32)
        fd=os.open(data/'api-token',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:f.write(token)
        if os.environ.get('GITHUB_ACTIONS')=='true':print('::add-mask::'+token,flush=True)
        env={**os.environ,'MINIOJ_DATA':str(data),'MINIOJ_EVIDENCE_DIR':str(evidence),
             'MINIOJ_JUDGE_BACKEND':'docker','MINIOJ_TEST_SESSION':session,
             'MINIOJ_TOKEN':token,'PYTHONUNBUFFERED':'1'}
        # Config is loaded only after test isolation is installed.
        os.environ.update({k:v for k,v in env.items() if k.startswith('MINIOJ_')})
        from minioj.docker_backend import docker,create_container,remove_container,cgroup_metrics
        import httpx
        def check(name,script,seconds=180,extra=None):
            start=time.monotonic();row={'name':name,'status':'running'};report['checks'].append(row);save()
            with open(private/(name+'.log'),'wb') as log:
                p=subprocess.Popen([sys.executable,str(ROOT/'scripts'/script)],cwd=ROOT,env={**env,**(extra or {})},stdout=log,stderr=log,start_new_session=True)
                try:
                    p.wait(timeout=max(.1,min(seconds,deadline-time.monotonic())))
                    row['returncode']=p.returncode;row['status']='passed' if p.returncode==0 else 'failed'
                except subprocess.TimeoutExpired:
                    row.update(status='failed',timed_out=True);stop_process(p)
                finally:row['seconds']=round(time.monotonic()-start,3);save()
            if row['status']!='passed':row['diagnostics']=diagnostics((private/(name+'.log')).read_text(errors='replace'));save()
            print(name,row['status'],flush=True)
            if row['status']!='passed':raise RuntimeError(name+'_failed')
        def collect():
            for filename in ('stage2-resources.json','round3-resources.json','round4-boundaries.json'):
                path=evidence/filename
                if path.exists():report['resources'].extend(safe_resource(r) for r in json.loads(path.read_text()))
            benchmarks=[]
            if server_ready and server.poll() is None:
                try:
                    with httpx.Client(base_url='http://127.0.0.1:8000/api',headers={'X-MiniOJ-Token':token},trust_env=False,timeout=5) as client:
                        response=client.get('/benchmarks');response.raise_for_status();benchmarks=response.json()
                except (httpx.HTTPError,ValueError):pass
            report['benchmarks']=[safe_benchmark(b) for b in benchmarks]
            report['evidence_counts']={}
            for filename in ('acceptance.json','resource-acceptance.json','queue-crash-acceptance.json'):
                path=evidence/filename
                if path.exists():report['evidence_counts'][filename]=len(json.loads(path.read_text()))
        preflight={'name':'environment_preflight','status':'running'}
        report['checks'].append(preflight)
        try:
            # Fixed ports are used by existing scripts. Refuse collisions before
            # launching services, rather than interacting with a user's server.
            for port in (8000,8001):
                with socket.socket() as s:
                    s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
                    s.bind(('127.0.0.1',port))
            name=create_container('test',64)
            try:
                snapshot=cgroup_metrics(name)
                controllers=docker(['exec',name,'cat','/sys/fs/cgroup/cgroup.controllers']).decode()
                report['capabilities']={'cgroup_v2':bool(controllers.strip()),
                    'memory_peak':snapshot['memory_peak'] is not None,
                    'memory_oom_events':(snapshot['memory'] or {}).get('oom_kill') is not None,
                    'pids_events':(snapshot['pids'] or {}).get('max') is not None,
                    'cpu_stat':(snapshot['cpu'] or {}).get('usage_usec') is not None}
                save()
                if not all(report['capabilities'].values()):raise RuntimeError('required_cgroup_capabilities_unavailable')
                docker(['exec',name,'/bin/sh','-c','echo 1000 > /proc/1/oom_score_adj'])
                report['capabilities']['oom_score_adjustment']=True
            finally:remove_container(name)
            preflight['status']='passed'
            check('resource_limits','stage2_resources.py')
            check('cgroup_memory_security','round3_resources.py')
            check('runner_boundaries','round4_boundaries.py')
            check('queue_recovery','queue_crash_acceptance.py',120)
            with open(private/'server.log','wb') as log:
                server=subprocess.Popen([sys.executable,'-m','uvicorn','minioj.app:app','--host','127.0.0.1','--port','8000','--ws-max-size','65536','--ws-max-queue','8'],cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
            end=time.monotonic()+30
            with httpx.Client(base_url='http://127.0.0.1:8000/api',headers={'X-MiniOJ-Token':token},trust_env=False,timeout=2) as client:
                while time.monotonic()<end:
                    if server.poll() is not None:raise RuntimeError('server_start_failed')
                    try:
                        if client.get('/health').status_code==200:server_ready=True;break
                    except httpx.HTTPError:pass
                    time.sleep(.1)
            if not server_ready:raise RuntimeError('server_readiness_timeout')
            check('judge_acceptance','acceptance.py')
            check('sandbox_security','resource_acceptance.py',120)
            check('benchmark_final_only','benchmark_acceptance.py',240)
            check('benchmark_iterative','benchmark_acceptance.py',300,{'MINIOJ_BENCHMARK_PROTOCOL':'iterative'})
            report['status']='passed'
        except Exception as exc:
            # Exceptions can embed request bodies/tokens. Report only type and
            # current allowlisted phase, never str(exc) or raw traceback.
            report['status']='failed';report['failure_type']=type(exc).__name__
            if preflight['status']=='running':preflight['status']='failed'
            if isinstance(exc,OSError):report['failure_errno']=exc.errno
        finally:
            try:
                collect()
                if report['status']=='passed':
                    assert len(report['benchmarks'])==2
                    assert {b['protocol'] for b in report['benchmarks']}=={'final_only','iterative'}
                    for b in report['benchmarks']:
                        assert b['planned_units']==b['completed_units']==18
                        assert b['verdict_counts']['AC']==b['verdict_counts']['WA']==9
                        assert b['end_to_end_success_rate']==.5
                        assert b['pending_units']==b['running_units']==0
            except Exception as exc:report['collection_error_type']=type(exc).__name__;report['status']='failed'
            stop_process(server)
            # The exact random session label includes orphaned containers from
            # timed-out scripts and killed servers, but never other instances.
            try:
                names=docker(['ps','-aq','--filter','label=minioj.test-session='+session]).decode().split()
                if names:docker(['rm','-f',*names],timeout=30)
                remaining=docker(['ps','-aq','--filter','label=minioj.test-session='+session]).decode().strip()
                report['cleanup']['containers_removed']=len(names)
                report['cleanup']['containers_remaining']=bool(remaining)
                if remaining:report['status']='failed'
            except Exception as exc:report['cleanup']['error_type']=type(exc).__name__;report['status']='failed'
            report['cleanup']['service_stopped']=server is None or server.poll() is not None
            report['cleanup']['ports_released']=True
            for port in (8000,8001):
                with socket.socket() as sock:
                    if sock.connect_ex(('127.0.0.1',port))==0:report['cleanup']['ports_released']=False
            if not report['cleanup']['ports_released']:report['status']='failed'
            report['seconds']=round(time.monotonic()-started,3);save()
    report['cleanup']['private_directory_removed']=not private.exists();save()
    text='| Docker Integration | status |\n|---|---|\n'
    for row in report['checks']:text+=f"| {row['name']} | {row['status']} |\n"
    text+=f"\nOverall: **{report['status']}**. Required cgroup capabilities: `{report['capabilities']}`.\n"
    text+='\n| Benchmark protocol | planned | completed | AC | WA | other failures | metrics validation |\n|---|---:|---:|---:|---:|---:|---|\n'
    for b in report['benchmarks']:
        counts=b['verdict_counts'];ac=counts['AC'] or 0;wa=counts['WA'] or 0
        text+=f"| {b['protocol']} | {b['planned_units']} | {b['completed_units']} | {ac} | {wa} | {(b['completed_units'] or 0)-ac-wa} | {'passed' if report['status']=='passed' else 'see failed phase'} |\n"
    (args.output/'docker-summary.md').write_text(text)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as summary:summary.write(text)
    print(text,flush=True)
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':sys.exit(main())
