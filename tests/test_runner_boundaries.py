import signal
import time
import psutil
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from minioj.runner import LocalRunner
from minioj.judge import execution_verdict
from runner_support import executable,signaled_run


class RunnerBoundaryTests(unittest.TestCase):
    def run_mode(self,mode,**kw):
        return LocalRunner().run([executable(),mode],'.',time_limit_ms=kw.pop('time_limit_ms',5000),**kw)

    def test_normal_nonzero_and_exit_137(self):
        for mode,verdict in [('0','AC'),('1','RE'),('137','RE')]:
            r=self.run_mode(mode)
            self.assertEqual(r.returncode,int(mode))
            self.assertIsNone(r.termination_signal)
            self.assertIsNone(r.reason)
            self.assertEqual(execution_verdict(r,b'','exact'),verdict)

    def test_self_sigkill_has_actual_signal(self):
        r,_=signaled_run('sigkill')
        self.assertEqual(r.returncode,-signal.SIGKILL)
        self.assertEqual(r.termination_signal,signal.SIGKILL)
        self.assertIsNone(r.reason)
        self.assertEqual(execution_verdict(r,b'','exact'),'RE')

    def test_self_sigxfsz_without_output_is_not_output_limit(self):
        r=self.run_mode('sigxfsz')
        self.assertEqual(r.termination_signal,signal.SIGXFSZ)
        self.assertIsNone(r.reason)
        self.assertEqual(execution_verdict(r,b'','exact'),'RE')

    def test_crash(self):
        r=self.run_mode('crash')
        self.assertEqual(r.termination_signal,signal.SIGABRT)
        self.assertIsNone(r.reason)
        self.assertEqual(execution_verdict(r,b'','exact'),'RE')

    def test_real_wall_timeout(self):
        r=self.run_mode('wall',time_limit_ms=100,wall_limit_ms=100)
        self.assertEqual(r.reason,'timeout')
        self.assertGreaterEqual(r.runtime_ms,100)
        self.assertEqual(execution_verdict(r,b'','exact'),'TLE')

    def test_real_cpu_timeout_with_independent_wall_budget(self):
        r=self.run_mode('cpu',time_limit_ms=1000,wall_limit_ms=10000)
        self.assertGreaterEqual(r.cpu_time_ms,1000)
        self.assertLess(r.runtime_ms,10000)
        self.assertEqual(execution_verdict(r,b'','exact'),'TLE')

    def test_output_overflow_and_exact_boundary(self):
        overflow=self.run_mode('output')
        self.assertEqual(overflow.reason,'output_limit')
        self.assertEqual(execution_verdict(overflow,b'','exact'),'RE')
        exact=self.run_mode('exact_output')
        self.assertEqual(exact.returncode,0)
        self.assertEqual(len(exact.stdout),1048576)
        self.assertIsNone(exact.reason)

    def test_stderr_is_not_resource_evidence(self):
        r=self.run_mode('bad_alloc')
        self.assertEqual(r.returncode,1)
        self.assertIsNone(r.reason)
        self.assertEqual(execution_verdict(r,b'','exact'),'RE')

    def test_shared_cgroup_is_never_attributed_to_local_child(self):
        original=Path.read_text
        def read(path,*args,**kw):
            if str(path).startswith('/sys/fs/cgroup'):
                raise AssertionError('shared caller cgroup is not contestant evidence')
            return original(path,*args,**kw)
        with patch('pathlib.Path.read_text',read):r=self.run_mode('0')
        self.assertEqual(r.returncode,0)
        self.assertIsNone(r.reason)
        self.assertEqual(r.memory_method,'sampled_process_tree_rss')

    def test_completed_signal_survives_delayed_monitor_observation(self):
        with tempfile.TemporaryDirectory() as td:
            ready=Path(td)/'ready';ack=Path(td)/'ack'
            def delayed_children(proc,*args,**kwargs):
                end=time.monotonic()+3
                while not ready.exists():
                    if time.monotonic()>end:raise AssertionError('target did not become ready')
                    time.sleep(.001)
                ack.write_text('ack')
                while proc.status()!=psutil.STATUS_ZOMBIE:
                    if time.monotonic()>end:raise AssertionError('target did not exit')
                    time.sleep(.001)
                time.sleep(.1)
                return []
            with patch.object(psutil.Process,'children',delayed_children):
                r=LocalRunner().run([executable(),'sigxcpu',str(ready),str(ack)],td,time_limit_ms=50)
        self.assertEqual(r.returncode,-signal.SIGXCPU)
        self.assertEqual(r.termination_signal,signal.SIGXCPU)
        self.assertIsNone(r.reason)
        self.assertGreaterEqual(r.runtime_ms,100)

    def test_launcher_overhead_is_part_of_wall_budget(self):
        # Controlled reproduction of slow launcher startup. The target has not
        # reached exec; this must remain a real wall timeout, not a fake SIGXCPU.
        with tempfile.TemporaryDirectory() as td:
            launcher=Path(td)/'delayed.py'
            launcher.write_text('import time\ntime.sleep(.2)\n'+Path('minioj/launcher.py').read_text())
            with patch('minioj.runner.Path.with_name',return_value=launcher):
                r=LocalRunner().run([executable(),'0'],'.',time_limit_ms=50)
        self.assertEqual(r.reason,'timeout')
        self.assertEqual(r.termination_signal,signal.SIGKILL)
