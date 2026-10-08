import base64
import json
import signal
import unittest
from unittest.mock import patch
from test_judge import PROBLEM  # initialize isolated test config before production imports
from minioj import db
from minioj.docker_backend import (DockerError, cgroup_metrics, parse_cgroup_snapshot,
                                  resource_metrics, classify_execution, parse_execution_report)
from minioj.judge import execution_verdict, judge
from minioj.runner import Execution


def snapshot(oom=0, memory_max=0, pids_max=0, cpu=100, peak=4096):
    return {'memory_peak': peak, 'memory_current': 2048,
            'memory': {'oom_kill': oom, 'max': memory_max},
            'pids': {'max': pids_max}, 'cpu': {'usage_usec': cpu}}


def report(rc=0, reason=None, out=b'3\n', err=b''):
    return {'version': 1, 'returncode': rc, 'termination_signal': -rc if rc<0 else None,
            'runtime_ms': 1, 'reason': reason,
            'stdout_b64': base64.b64encode(out).decode(),
            'stderr_b64': base64.b64encode(err).decode()}


class ResourceMetricsTests(unittest.TestCase):
    def result(self, before=None, after=None, record=None, state=None, transport=0):
        return classify_execution(record or report(), resource_metrics(before or snapshot(), after or snapshot()),
                                  state or {'Running': True, 'OOMKilled': False}, transport)

    def test_namespaces_do_not_overwrite_max(self):
        raw='@@memory_peak@@\n4096\n@@memory_current@@\n2048\n@@memory@@\nmax 7\noom_kill 1\n@@cpu@@\nusage_usec 100\n@@pids@@\nmax 23\n'
        s=parse_cgroup_snapshot(raw)
        self.assertEqual(s['memory']['max'], 7)
        self.assertEqual(s['pids']['max'], 23)
        m=resource_metrics(snapshot(memory_max=5,pids_max=20),s)
        self.assertEqual(m['memory']['max_delta'],2)
        self.assertEqual(m['pids']['max_delta'],3)
        self.assertEqual(m['before']['memory']['max'],5)
        self.assertEqual(m['after']['pids']['max'],23)

    def test_historical_pid_events_do_not_fail_normal_program(self):
        r=self.result(snapshot(pids_max=7),snapshot(pids_max=7))
        self.assertIsNone(r.reason)
        self.assertEqual(r.cgroup['pids']['max_delta'],0)
        self.assertEqual(execution_verdict(r,b'3\n','exact'),'AC')

    def test_new_pid_event_alone_does_not_fail_normal_program(self):
        r=self.result(snapshot(pids_max=7),snapshot(pids_max=8))
        self.assertEqual(r.cgroup['pids']['max_delta'],1)
        self.assertIsNone(r.reason)
        self.assertEqual(execution_verdict(r,b'3\n','exact'),'AC')

    def test_new_pid_event_does_not_replace_actual_exit(self):
        r=self.result(snapshot(),snapshot(pids_max=1),report(1))
        self.assertEqual(r.returncode,1)
        self.assertIsNone(r.reason)
        self.assertEqual(execution_verdict(r,b'3\n','exact'),'RE')

    def test_historical_oom_does_not_fail(self):
        r=self.result(snapshot(oom=2),snapshot(oom=2))
        self.assertIsNone(r.reason)

    def test_memory_max_without_oom_is_not_mle(self):
        r=self.result(snapshot(),snapshot(memory_max=20))
        self.assertEqual(r.cgroup['memory']['max_delta'],20)
        self.assertIsNone(r.reason)

    def test_new_oom_with_actual_sigkill(self):
        r=self.result(snapshot(),snapshot(oom=1),report(-9))
        self.assertEqual(r.reason,'memory_limit')
        self.assertEqual(r.termination_signal,9)
        self.assertEqual(execution_verdict(r,b'3\n','exact'),'MLE')

    def test_oomkilled_container_without_report_or_metrics(self):
        missing={k:None for k in snapshot()}
        r=classify_execution(None,resource_metrics(missing,missing),{'Running':False,'OOMKilled':True},137)
        self.assertEqual(r.reason,'memory_limit')
        self.assertIsNone(r.returncode)
        self.assertIsNone(r.termination_signal)
        self.assertIsNone(r.container_peak_memory_kb)
        self.assertIsNone(r.process_peak_rss_kb)
        self.assertEqual(execution_verdict(r,b'','exact'),'MLE')

    def test_missing_metrics_do_not_invent_zero(self):
        with patch('minioj.docker_backend.docker',side_effect=DockerError('not available')):
            s=cgroup_metrics('test')
        self.assertTrue(all(x is None for x in s.values()))
        r=self.result(s,s)
        self.assertIsNone(r.memory_kb)
        self.assertEqual(r.container_memory_method,'unavailable')
        self.assertIsNone(r.cpu_time_ms)
        self.assertIsNone(r.cgroup['memory']['oom_kill_delta'])
        self.assertIsNone(r.cgroup['pids']['max_delta'])
        self.assertIsNone(r.reason)

    def test_partial_and_malformed_files(self):
        for body in ('max nope', 'max 1\nmax 2', 'max -1', 'max 1 unexpected', ''):
            s=parse_cgroup_snapshot('@@memory@@\n'+body+'\n@@pids@@\nmax 8\n@@memory_peak@@\n1024\n')
            self.assertIsNone(s['memory'])
            self.assertEqual(s['pids']['max'],8)
            self.assertEqual(s['memory_peak'],1024)
        s=parse_cgroup_snapshot('@@memory_peak@@\nbad\n@@cpu@@\nusage_usec 500\n')
        self.assertIsNone(s['memory_peak'])
        self.assertEqual(s['cpu']['usage_usec'],500)

    def test_reset_counter_is_unavailable(self):
        m=resource_metrics(snapshot(oom=5,pids_max=4,cpu=100),snapshot(oom=1,pids_max=2,cpu=50))
        self.assertIsNone(m['memory']['oom_kill_delta'])
        self.assertIsNone(m['cpu']['usage_usec_delta'])
        self.assertIsNone(m['pids']['max_delta'])

    def test_container_peak_is_not_process_rss(self):
        r=self.result(snapshot(peak=2048),snapshot(peak=16385,cpu=1100))
        self.assertEqual(r.container_peak_memory_kb,17)
        self.assertEqual(r.memory_kb,17)
        self.assertEqual(r.container_baseline_memory_kb,2)
        self.assertIsNone(r.process_peak_rss_kb)
        self.assertEqual(r.process_memory_method,'unavailable')
        self.assertEqual(r.cpu_time_ms,1)

    def test_cpu_counter_not_timeout_evidence(self):
        r=self.result(snapshot(),snapshot(cpu=10000000))
        self.assertIsNone(r.reason)

    def test_exit_137_is_not_signal_9(self):
        r=self.result(record=report(137),transport=0)
        self.assertEqual(r.returncode,137)
        self.assertIsNone(r.termination_signal)
        self.assertEqual(r.transport_exit_code,0)

    def test_signal_timeout_and_output_limit(self):
        for rc,reason,expected in ((-signal.SIGXCPU,'cpu_timeout','TLE'),(-9,'timeout','TLE'),(-signal.SIGXFSZ,'output_limit','RE'),(-6,None,'RE')):
            r=self.result(record=report(rc,reason))
            self.assertEqual(r.termination_signal,-rc)
            self.assertEqual(execution_verdict(r,b'3\n','exact'),expected)

    def test_bad_alloc_text_is_not_mle_evidence(self):
        r=self.result(record=report(-6,err=b'bad_alloc Cannot allocate memory'))
        self.assertIsNone(r.reason)
        self.assertEqual(execution_verdict(r,b'3\n','exact'),'RE')

    def test_missing_report_and_transport_errors_are_se(self):
        for rc in (0,1,125,137,-9):
            r=classify_execution(None,resource_metrics(snapshot(),snapshot()),{'Running':True},rc)
            self.assertEqual(execution_verdict(r,b'','exact'),'SE')
            self.assertIsNone(r.returncode)
            self.assertIsNone(r.termination_signal)
        r=self.result(record=report(),transport=125)
        self.assertEqual(execution_verdict(r,b'3\n','exact'),'SE')
        self.assertEqual(r.transport_exit_code,125)

    def test_container_stopped_without_oom_is_se(self):
        r=self.result(state={'Running':False,'OOMKilled':False})
        self.assertEqual(execution_verdict(r,b'3\n','exact'),'SE')

    def test_invalid_supervisor_reports(self):
        self.assertIsNotNone(parse_execution_report(json.dumps(report(-6))))
        for raw in ('', '{}', 'null', '[]', json.dumps({**report(),'termination_signal':9}), json.dumps({**report(),'runtime_ms':float('nan')}), json.dumps({**report(),'stdout_b64':'!!!'})):
            self.assertIsNone(parse_execution_report(raw),raw)

    def test_exec_oom_fallback_keeps_measured_host_wall_time(self):
        from minioj.docker_backend import execute
        with patch('minioj.docker_backend.cgroup_metrics',side_effect=[snapshot(),snapshot(oom=1)]),patch('minioj.docker_backend.docker',side_effect=[DockerError('lost supervisor'),b'{"Running":true,"OOMKilled":false}']),patch('minioj.docker_backend.time.monotonic',side_effect=[10,10.5]):
            r=execute('test',{'time_limit_ms':500})
        self.assertEqual(r.reason,'memory_limit')
        self.assertEqual(r.runtime_ms,500)
        self.assertIsNone(r.returncode)
        self.assertIsNone(r.termination_signal)

    def test_exec_transport_failure_with_historical_oom_is_not_mle(self):
        from minioj.docker_backend import execute
        with patch('minioj.docker_backend.cgroup_metrics',return_value=snapshot(oom=2)),patch('minioj.docker_backend.docker',side_effect=[DockerError('transport failed'),b'{"Running":true,"OOMKilled":false}']),patch('minioj.docker_backend.remove_container') as remove:
            with self.assertRaises(DockerError):execute('test',{'time_limit_ms':500})
        remove.assert_called_once_with('test')

    def test_report_validation_survives_optimized_python(self):
        import subprocess,sys
        code="from minioj.docker_backend import parse_execution_report;import sys;sys.exit(0 if parse_execution_report('{\"version\":1,\"returncode\":true,\"termination_signal\":null,\"reason\":null,\"runtime_ms\":0,\"stdout_b64\":\"\",\"stderr_b64\":\"\"}') is None else 1)"
        subprocess.run([sys.executable,'-O','-c',code],check=True)

    def test_local_self_sent_sigxcpu_is_not_timeout(self):
        from runner_support import signaled_run
        r,ready=signaled_run()
        self.assertIsNone(r.reason)
        self.assertEqual(r.termination_signal,signal.SIGXCPU)
        self.assertEqual(r.returncode,-signal.SIGXCPU)
        self.assertLess(ready['ready_cpu_ms'],10000)
        self.assertEqual(execution_verdict(r,b'','exact'),'RE')

    def test_cgroup_reader_has_separate_uid_without_new_capabilities(self):
        with patch('minioj.docker_backend.docker',return_value=b'') as cli:cgroup_metrics('test')
        args=cli.call_args.args[0]
        self.assertEqual(args[:4],['exec','--user','0:0','test'])

    def test_judge_persists_se_instead_of_ce(self):
        db.initialize();pid=db.save_problem(PROBLEM)
        sid=db.create_submission(pid,'int main(){}')
        r=Execution(None,'infrastructure_error',0,None,b'',b'',infrastructure_error='transport_failed')
        with patch('minioj.judge.LocalJudgeSession.compile',return_value=r):judge(sid)
        self.assertEqual(db.submission(sid)['verdict'],'SE')

    def test_judge_persists_se_and_separate_memory_fields(self):
        db.initialize();pid=db.save_problem(PROBLEM);sid=db.create_submission(pid,'int main(){}')
        r=self.result(transport=125)
        with patch('minioj.judge.LocalJudgeSession.compile',return_value=Execution(0,None,0,1,b'',b'')),patch('minioj.judge.LocalJudgeSession.run',return_value=r):judge(sid)
        s=db.submission(sid)
        self.assertEqual(s['verdict'],'SE')
        self.assertEqual(s['results'][0]['container_peak_memory_kb'],4)
        self.assertIsNone(s['results'][0]['process_peak_rss_kb'])
        self.assertEqual(s['results'][0]['transport_exit_code'],125)
