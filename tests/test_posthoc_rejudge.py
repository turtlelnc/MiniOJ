import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from test_judge import PROBLEM
from benchmark.posthoc import recover, rejudge, code_sha
from minioj.runner import Execution


class PosthocTests(unittest.TestCase):
    def unit(self):return {'id':'u','run_id':'r','problem_id':1,'status':'Failed','record':{'verdict':None,'failure_category':'agent_failure'}}
    def experiment(self):return {'manifest':{'git_commit':'original','judge_backend':'docker','environment_information':{'image_id':'sha256:pinned'},'problem_snapshots':[{**PROBLEM,'id':1,'_judge_fingerprint':'old'}]}}
    def test_last_write_without_mutation_review_is_unknown(self):
        u=self.unit();code='int main(){}'
        u['record']['messages']=[{'role':'assistant','tool_calls':[{'id':'w','function':{'name':'write_file','arguments':json.dumps({'path':'main.cpp','content':code})}}]},
                                 {'role':'tool','tool_call_id':'w','content':'{"size":12}'}]
        self.assertEqual(recover(u)['status'],'unknown')
        self.assertEqual(recover(u,code_sha(code))['status'],'available')
        self.assertEqual(recover(u,'wrong')['status'],'unknown')

    def test_termination_snapshot_integrity(self):
        u=self.unit();u['record']['termination_code']={'content':'source','sha256':code_sha('source'),'provenance':'paused_container_copy_before_cleanup'}
        self.assertEqual(recover(u)['status'],'available')
        u['record']['termination_code']['content']='later modified';self.assertEqual(recover(u)['status'],'unknown')

    def test_standalone_rejudge_pins_image_and_preserves_original(self):
        u=self.unit();e=self.experiment();before=copy.deepcopy((e,u));seen=[]
        class Session:
            def __init__(self,image):seen.append(image)
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def compile(self,code):seen.append(code);return Execution(0,None,1,None,b'',b'')
            def run(self,inp,*args):return Execution(0,None,1,None,b'3\n',b'')
        source={'status':'available','content':'code','sha256':code_sha('code'),'provenance':'snapshot'}
        with patch('benchmark.posthoc.judge_compatibility',return_value={'compatible':True}):
            a=rejudge(e,u,source,Path('.'),Session);b=rejudge(e,u,source,Path('.'),Session)
        self.assertEqual(a['verdict'],'AC');self.assertEqual(a['status'],'verified');self.assertNotEqual(a['id'],b['id'])
        self.assertTrue(a['created_at']);self.assertEqual(seen[0],'sha256:pinned');self.assertEqual((e,u),before)

    def test_missing_snapshot_and_infrastructure_are_unknown(self):
        u=self.unit();e=self.experiment();source={'status':'available','content':'code','sha256':code_sha('code')}
        self.assertEqual(rejudge(e,u,{'status':'unknown'},Path('.'))['status'],'unknown')
        e['manifest']['problem_snapshots'][0].pop('testcases')
        self.assertEqual(rejudge(e,u,source,Path('.'))['reason'],'frozen_tests_unavailable')
        e=self.experiment()
        class Broken:
            def __init__(self,**kw):raise RuntimeError('socket unavailable')
        with patch('benchmark.posthoc.judge_compatibility',return_value={'compatible':True}):
            result=rejudge(e,u,source,Path('.'),Broken)
        self.assertEqual(result['status'],'unknown');self.assertIsNone(result['verdict'])
        with patch('benchmark.posthoc.judge_compatibility',return_value={'compatible':False,'reason':'judge_source_changed'}):
            self.assertEqual(rejudge(e,u,source,Path('.'))['reason'],'judge_source_changed')


class SnapshotTests(unittest.TestCase):
    def test_pause_precedes_trusted_inspector_and_errors_are_unknown(self):
        from benchmark.snapshots import capture
        from minioj import config
        from minioj.docker_backend import DockerError
        calls=[]
        def docker(args,**kwargs):
            calls.append(args[0])
            if args[0]=='inspect':
                if 'Paused' in args[2]:return b'false'
                if '.Image' in args[2]:return b'sha256:original'
                return str(config.DB_PATH).encode()
            if args[0]=='run':
                self.assertIn('--read-only',args);self.assertIn('no-new-privileges',args)
                self.assertNotIn('--privileged',args);self.assertIn('container:owned',args)
                return b'{"content_b64":"Y29kZQ=="}'
            return b''
        with patch('minioj.db.run',return_value={'status':'Active','container':'owned'}),patch('minioj.docker_backend.docker',side_effect=docker):
            result=capture('r')
        self.assertLess(calls.index('pause'),calls.index('run'));self.assertEqual(result['content'],'code')
        self.assertLessEqual(result['frozen_at'],result['captured_at'])
        def broken(args,**kwargs):
            if args[0]=='run':raise DockerError('source not regular or unavailable')
            return docker(args,**kwargs)
        with patch('minioj.db.run',return_value={'status':'Active','container':'owned'}),patch('minioj.docker_backend.docker',side_effect=broken):
            self.assertIsNone(capture('r'))

    def test_missing_owner_db_is_unknown(self):
        from benchmark.snapshots import capture
        with patch('minioj.db.run',return_value=None),patch('minioj.docker_backend.docker') as docker:
            self.assertIsNone(capture('remote'));docker.assert_not_called()
