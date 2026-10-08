import time,unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from minioj import db
from minioj.judge import JudgeQueue,judge
from test_judge import PROBLEM,GOOD
class QueueTests(unittest.TestCase):
 def setUp(self):
  db.initialize();self.pid=db.save_problem(PROBLEM)
  with db.connect() as c:c.execute("UPDATE submissions SET status='Finished',verdict='SE' WHERE status!='Finished'")
 def test_capacity_is_transactional(self):
  q=JudgeQueue();q.CAPACITY=5
  def submit(_):
   try:return q.submit(self.pid,GOOD)
   except OverflowError:return None
  with ThreadPoolExecutor(max_workers=12) as pool:results=list(pool.map(submit,range(20)))
  self.assertEqual(sum(x is not None for x in results),5)
  self.assertEqual(len(db.pending()),5)
 def test_claim_unique_and_duplicate_hint(self):
  sid=db.create_submission(self.pid,GOOD)
  with ThreadPoolExecutor(max_workers=10) as pool:claimed=list(pool.map(lambda i:db.claim_submission(str(i),sid),range(10)))
  self.assertEqual(claimed.count(sid),1)
  owner=db.submission(sid,True)['lease_owner'];judge(sid,owner);judge(sid)
  self.assertEqual(db.submission(sid)['attempt_count'],1)
  self.assertEqual(db.submission(sid)['verdict'],'AC')
 def test_expired_compiling_and_running_fenced(self):
  for state in ('Compiling','Running'):
   rid=db.create_run(self.pid,'agent',{'feedback_policy':'final_only'},db.problem(self.pid,True))
   sid=db.create_submission(self.pid,GOOD,'agent',rid,final=True)
   db.claim_submission('dead-worker',sid)
   db.update_submission(sid,owner='dead-worker',status=state,lease_expires_at=time.time()-1)
   db.initialize() # fresh startup must not overwrite a live lease
   db.claim_submission('new-worker')
   self.assertEqual(db.submission(sid)['verdict'],'SE');self.assertEqual(db.run(rid)['status'],'Finished')
   with self.assertRaises(ValueError):db.update_submission(sid,owner='dead-worker',status='Finished',verdict='AC')
 def test_live_claim_survives_initialize(self):
  sid=db.create_submission(self.pid,GOOD);db.claim_submission('alive',sid);db.initialize()
  self.assertEqual(db.submission(sid)['status'],'Compiling')
 def test_final_run_atomic_with_fast_worker(self):
  q=JudgeQueue();q.start()
  try:
   for _ in range(5):
    rid=db.create_run(self.pid,'agent',{'feedback_policy':'final_only'},db.problem(self.pid,True))
    sid=q.submit(self.pid,GOOD,'agent',rid,final=True)
    deadline=time.monotonic()+10
    while db.submission(sid)['status']!='Finished' and time.monotonic()<deadline:time.sleep(.02)
    self.assertEqual(db.run(rid)['status'],'Finished')
  finally:q.close()
 def test_full_hint_queue_does_not_hide_durable_work(self):
  q=JudgeQueue()
  for _ in range(100):q.queue.put_nowait(-1)
  sid=q.submit(self.pid,GOOD);q.start()
  try:
   deadline=time.monotonic()+5
   while db.submission(sid)['status']!='Finished' and time.monotonic()<deadline:time.sleep(.02)
   self.assertEqual(db.submission(sid)['verdict'],'AC')
  finally:q.close()
