import os, tempfile, unittest
from pathlib import Path
# Isolate test database from the runnable application.
TEST_DATA=tempfile.TemporaryDirectory(prefix='minioj-tests-')
os.environ['MINIOJ_DATA']=TEST_DATA.name
os.environ['MINIOJ_JUDGE_BACKEND']='local'
from minioj import db
from minioj.checker import compare
from minioj.judge import judge
from minioj.runner import LocalRunner
from minioj.config import COMPILER

GOOD='#include <iostream>\nint main(){long long a,b;std::cin>>a>>b;std::cout<<a+b<<"\\n";}'
PROBLEM={'title':'A+B','description':'sum','input_description':'two integers','output_description':'sum','time_limit_ms':300,'memory_limit_mb':64,'checker':'trimmed','samples':[{'input':'1 2\n','expected_output':'3\n'}],'testcases':[{'input':'1 2\n','expected_output':'3\n','weight':1},{'input':'-5 8\n','expected_output':'3\n','weight':1}]}
class CheckerTests(unittest.TestCase):
    def test_exact(self):
        self.assertTrue(compare(b'3\n',b'3\n','exact'));self.assertFalse(compare(b'3',b'3\n','exact'))
    def test_trimmed(self):
        self.assertTrue(compare(b'3 \t\n\n',b'3','trimmed'))
        self.assertFalse(compare(b'1  2',b'1 2','trimmed'))
        self.assertFalse(compare(b'\n3',b'3','trimmed'))
        self.assertFalse(compare(b'a\n\nb',b'a\nb','trimmed'))
class JudgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): db.initialize(); cls.pid=db.save_problem(PROBLEM)
    def verdict(self,code,expected):
        sid=db.create_submission(self.pid,code);judge(sid);s=db.submission(sid)
        self.assertEqual(s['verdict'],expected,s)
        self.assertEqual(s['status'],'Finished');return s
    def test_ac(self): self.assertEqual(self.verdict(GOOD,'AC')['passed_tests'],2)
    def test_wa(self): self.verdict('int main(){}','WA')
    def test_tle(self): self.verdict('int main(){while(true){}}','TLE')
    def test_re(self): self.verdict('#include <cstdlib>\nint main(){std::abort();}','RE')
    def test_ce(self): self.assertTrue(self.verdict('broken c++','CE')['compile_output'])
    def test_output_limit(self):
        s=self.verdict('#include <cstdio>\nint main(){while(true) puts("xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx");}','RE')
        self.assertEqual(s['reason'],'output_limit')
    def test_mle(self):
        self.verdict('#include <cstdlib>\n#include <cstring>\n#include <unistd.h>\nint main(){for(;;){char* p=(char*)malloc(1024*1024);if(!p)abort();memset(p,1,1024*1024);usleep(1000);}}','MLE')
    def test_snapshot_and_soft_delete(self):
        pid=db.save_problem(PROBLEM);sid=db.create_submission(pid,GOOD)
        changed={**PROBLEM,'testcases':[{'input':'1 2','expected_output':'999'}]}
        db.save_problem(changed,pid);db.delete_problem(pid);judge(sid)
        self.assertEqual(db.submission(sid)['verdict'],'AC');self.assertIsNone(db.problem(pid))
    def test_compile_timeout(self):
        r=LocalRunner().run(['/bin/sleep','5'],TEST_DATA.name,time_limit_ms=100,memory_limit_mb=64)
        self.assertEqual(r.reason,'timeout')
    def test_fork_cleanup(self):
        import subprocess,time,psutil
        with tempfile.TemporaryDirectory() as td:
            src=Path(td)/'main.cpp';src.write_text('#include <unistd.h>\n#include <cstdio>\nint main(){pid_t p=fork();if(p==0){while(1){}}printf("%d",(int)p);fflush(stdout);while(1){}}')
            exe=Path(td)/'main';subprocess.run([COMPILER,str(src),'-o',str(exe)],check=True)
            r=LocalRunner().run([str(exe)],td,time_limit_ms=100,memory_limit_mb=64)
            self.assertEqual(r.reason,'timeout');pid=int(r.stdout)
            time.sleep(.1)
            if psutil.pid_exists(pid): self.assertEqual(psutil.Process(pid).status(),psutil.STATUS_ZOMBIE)
        root=Path(tempfile.gettempdir())/'minioj'
        self.assertEqual(list(root.glob('submission-*')),[])
    def test_pending_run_restart_recovery(self):
        from unittest.mock import patch
        from minioj.workspace import WorkspaceManager
        rid=db.create_run(self.pid,'agent',{'feedback_policy':'final_only'},db.problem(self.pid,True))
        sid=db.create_submission(self.pid,GOOD,'agent',rid)
        db.update_run(rid,status='Judging',final_submission_id=sid)
        manager=WorkspaceManager()
        with patch('minioj.workspace.docker',return_value=b''):
            manager.start()
            self.assertEqual(db.run(rid)['status'],'Judging')
            manager.close()
            db.update_submission(sid,status='Running');db.initialize()
            manager=WorkspaceManager();manager.start()
            self.assertEqual(db.run(rid)['status'],'Finished')
            self.assertEqual(db.submission(sid)['verdict'],'SE')
            manager.close()
    def test_system_error(self):
        from unittest.mock import patch
        sid=db.create_submission(self.pid,GOOD)
        with patch('minioj.judge.LocalJudgeSession.compile',side_effect=RuntimeError('compiler unavailable')):
            judge(sid)
        self.assertEqual(db.submission(sid)['verdict'],'SE')
    def test_restart_recovery(self):
        sid=db.create_submission(self.pid,GOOD);db.update_submission(sid,status='Running');db.initialize()
        self.assertEqual(db.submission(sid)['verdict'],'SE')
if __name__=='__main__': unittest.main(verbosity=2)
