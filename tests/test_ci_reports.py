"""Artifacts must retain useful evidence without arbitrary fixture contents."""
import json
import unittest
from scripts.ci_docker import safe_resource,safe_benchmark,number,diagnostics,ROOT
from scripts.ci_unit import counts

class CIReportsTests(unittest.TestCase):
    def test_resource_allowlist(self):
        secret='private_api_key_hidden_input'
        row={'case':secret,'stdout':secret,'stderr':secret,'infrastructure_error':secret,
             'reason':secret,'returncode':137,'termination_signal':None,
             'container_state':{'OOMKilled':False,'Error':secret},
             'cgroup':{'memory':{'oom_kill_delta':0,'max_delta':3,'private':secret},'pids':{'max_delta':2}}}
        result=safe_resource(row)
        self.assertNotIn(secret,json.dumps(result))
        self.assertEqual(result['returncode'],137)
        self.assertIsNone(result['termination_signal'])
        self.assertEqual(result['event_deltas']['memory']['max_delta'],3)
        self.assertEqual(result['event_deltas']['pids']['max_delta'],2)
        self.assertIsNone(result['event_deltas']['cpu']['usage_usec_delta'])
        self.assertEqual(safe_resource({'reason':{}})['reason'],'unknown')

    def test_benchmark_allowlist(self):
        secret='private_api_key_hidden_input'
        result=safe_benchmark({'manifest':secret,'summary':{'protocol':'iterative',
            'overall':{'planned_units':18,'completed_units':18,'end_to_end_success_rate':.5,
                       'error':secret,'verdict_counts':{'AC':9,'WA':9,secret:1}}}})
        self.assertNotIn(secret,json.dumps(result))
        self.assertEqual(result['planned_units'],18)
        self.assertEqual(result['verdict_counts']['AC'],9)
        self.assertIsNone(result['mean_total_tokens'])

    def test_missing_metrics_are_not_fabricated(self):
        for value in (None,True,'1',float('nan'),float('inf')):self.assertIsNone(number(value))
        self.assertEqual(number(0),0)
        self.assertIsNone(safe_resource({})['cpu_time_ms'])

    def test_failure_diagnostics_do_not_copy_assertion_contents(self):
        secret='private_api_key_hidden_input'
        log=f'  File "{ROOT}/scripts/acceptance.py", line 50, in main\n    {secret}\nAssertionError: {secret}\n'
        result=diagnostics(log)
        self.assertEqual(result['frames'],[{'file':'scripts/acceptance.py','line':50}])
        self.assertEqual(result['exception_type'],'AssertionError')
        self.assertNotIn(secret,json.dumps(result))

    def test_counts_include_skips_and_errors(self):
        class Result:
            testsRun=10;failures=[(unittest.FunctionTestCase(lambda:None),'private')]
            errors=[];skipped=[(None,'private')]
        result=counts(Result())
        self.assertEqual((result['passed'],result['failed'],result['skipped']),(8,1,1))
        self.assertNotIn('private',json.dumps(result))
