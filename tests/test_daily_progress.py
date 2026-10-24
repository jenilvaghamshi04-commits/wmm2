import unittest,json
import test_gateway as gw

class DailyProgressTests(unittest.TestCase):
    setUp=gw.GatewayTests.setUp;tearDown=gw.GatewayTests.tearDown;load=gw.GatewayTests.load;run_async=gw.GatewayTests.run_async
    def attempt(self,id,target,status='Sent',kind='dm',principal='101',day=None):
        self.app.db.execute('insert into outbox values(?,?,?,?,?,?,?,?,?,?,?)',(id,principal,1,kind,target,id,status,day or self.app.today(),self.app.stamp(),'','hash'));self.app.db.commit()
    def queue(self,id,target,kind='dm',status='Queued',principal='101'):
        self.app.db.execute('insert into manual_send_queue values(?,?,?,?,?,?,?,?,?,?,?,?)',(id,id,principal,1,id,kind,target,json.dumps({'message':'Test'}),status,self.app.stamp(),self.app.stamp(),''));self.app.db.commit()
    def test_unique_new_dms_exclude_repeat_targets_and_cancelled_queues(self):
        self.attempt('prior','repeat',day='2020-01-01');self.attempt('repeat-now','repeat');self.attempt('new','new');self.attempt('failed','failed','Failed');self.attempt('other','other',principal='102')
        self.queue('followup','repeat');self.queue('one','pending');self.queue('duplicate','pending');self.queue('cancel','cancelled',status='Cancelled')
        p=self.app.daily_progress('101')['dm'];self.assertEqual((p['sent'],p['used'],p['queued'],p['remaining']),(1,2,1,12));self.assertEqual(p['queued_messages'],3);self.assertEqual(p['other_used'],1)
    def test_group_attempts_and_pending_jobs_have_separate_allowance(self):
        self.attempt('group-sent','-1',kind='group');self.attempt('group-failed','-2','Failed','group');self.queue('group-wait','-3','group');self.queue('ignore','-4','group','Cancelled')
        p=self.app.daily_progress('101');self.assertEqual((p['group']['sent'],p['group']['used'],p['group']['queued'],p['group']['remaining']),(1,2,1,27));self.assertEqual(p['dm']['remaining'],15);self.assertEqual(p['timezone'],'Asia/Kolkata')
    def test_quota_reset_floor_is_reflected_without_losing_pending_reservations(self):
        self.attempt('sent','one');floor=self.app.db.execute('select max(rowid) from outbox').fetchone()[0]
        self.app.db.execute('insert into quota_resets values(?,?,?,?,?,?,?,?,?)',('r','101',1,'dm',self.app.today(),floor,self.app.stamp(),1,'reset'));self.app.db.commit();self.queue('pending','two')
        p=self.app.daily_progress('101')['dm'];self.assertEqual((p['sent'],p['used'],p['queued'],p['remaining']),(0,0,1,14))
    def test_status_exposes_progress_for_all_accounts(self):
        status=self.run_async(self.app.status());self.assertTrue(all('daily_progress' in a for a in status['accounts']));self.assertEqual(status['accounts'][0]['daily_progress']['dm']['remaining'],15)
