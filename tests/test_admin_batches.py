import json,unittest
from datetime import timedelta
from fastapi import HTTPException
from fastapi.testclient import TestClient
import test_gateway as gw
from test_background_sends import Clock

class AdminBatchTests(unittest.TestCase):
    load=gw.GatewayTests.load;tearDown=gw.GatewayTests.tearDown;run_async=gw.GatewayTests.run_async;sender=gw.GatewayTests.sender
    def setUp(self):
        gw.GatewayTests.setUp(self);self.app.datetime=Clock;Clock.current=Clock(2026,10,23,6,0,tzinfo=__import__('datetime').timezone.utc);self.app.enforce_send_pacing=self.real_pacing;self.c=self.sender()
    def contact(self,n):
        cid='77:'+str(n);self.app.save({'id':cid,'user_id':str(n),'name':'Admin '+str(n),'username':'','group':'Community','group_id':'-10077','role':'Admin','scan_account':1});return cid
    def body(self,n=3,request='batch-request-1',delay=300,messages=None):
        return self.app.AdminBatchSend(request_id=request,account_id=1,delay_seconds=delay,token_symbol='ABC',messages=messages or [self.app.AdminBatchMessage(id=self.contact(i),message='Hi @username about $TOKEN') for i in range(1,n+1)])
    def queue(self,**kw):return self.run_async(self.app.queue_admin_batch(self.body(**kw)))
    def process(self):return self.run_async(self.app.process_manual_queue(limit=15))
    def advance(self,n):Clock.current+=timedelta(seconds=n)
    def count(self):return self.app.db.execute('select count(*) from manual_send_queue').fetchone()[0]
    def test_batch_is_reviewed_personalized_and_queued_without_sending(self):
        r=self.queue(n=10);self.assertEqual(r['count'],10);self.assertEqual(self.c.sent,[]);self.assertEqual(self.count(),10)
        first=json.loads(self.app.db.execute('select payload from manual_send_queue order by rowid limit 1').fetchone()[0]);self.assertEqual(first['message'],'Hi Admin 1 about $ABC');self.assertEqual(first['minimum_delay_seconds'],300)
        self.assertEqual(self.app.db.execute('select count(distinct principal) from manual_send_queue').fetchone()[0],1)
    def test_five_minute_delay_persists_after_reload_and_global_shortening(self):
        self.queue();self.process();self.assertEqual(len(self.c.sent),1);self.advance(120);self.process();self.assertEqual(len(self.c.sent),1)
        self.app.db.close();self.load();self.app.datetime=Clock;self.app.enforce_send_pacing=self.real_pacing;self.app.clients[1]=self.c;self.app.recover_manual_queue();self.advance(180);self.process();self.assertEqual(len(self.c.sent),2);self.advance(299);self.process();self.assertEqual(len(self.c.sent),2);self.advance(1);self.process();self.assertEqual(len(self.c.sent),3)
    def test_actual_delivery_time_controls_delay_after_server_wakes_late(self):
        self.queue(n=3);self.advance(3600);self.process();self.assertEqual(len(self.c.sent),1);self.advance(120);self.process();self.assertEqual(len(self.c.sent),1);self.advance(180);self.process();self.assertEqual(len(self.c.sent),2)
    def test_batch_cannot_shorten_global_delay(self):
        self.run_async(self.app.update_sending_pace(self.app.SendingPace(delay_seconds=600)));self.assertEqual(self.queue(delay=120)['delay_seconds'],600)
    def test_idempotent_retry_returns_original_receipt_and_detects_changed_preview(self):
        body=self.body();a=self.run_async(self.app.queue_admin_batch(body));self.process();b=self.run_async(self.app.queue_admin_batch(body));self.assertTrue(b['already_queued']);self.assertEqual(a['batch_id'],b['batch_id']);self.assertEqual(self.count(),3)
        body.messages[0].message='Changed'
        with self.assertRaises(HTTPException):self.run_async(self.app.queue_admin_batch(body))
    def test_paused_account_cannot_queue(self):
        self.run_async(self.app.identify(1,self.c));self.app.db.execute('update account_info set blocked_until=?',((Clock.current+timedelta(hours=1)).isoformat(),));self.app.db.commit()
        with self.assertRaises(HTTPException) as e:self.queue()
        self.assertEqual(e.exception.status_code,429);self.assertEqual(self.count(),0);self.assertEqual(self.c.sent,[])
    def test_new_recipient_limit_includes_existing_pending_messages(self):
        self.queue(n=10)
        msgs=[self.app.AdminBatchMessage(id=self.contact(i),message='Hello') for i in range(11,17)]
        with self.assertRaises(HTTPException) as e:self.queue(request='batch-request-2',messages=msgs)
        self.assertEqual(e.exception.status_code,429);self.assertEqual(self.count(),10)
    def test_demo_bots_groups_and_duplicate_identity_are_rejected_atomically(self):
        for data in [{'id':'demo','user_id':'900001','name':'Demo'}, {'id':'bot','user_id':'900002','name':'Bot','scan_account':1,'group_id':'-77','is_bot':True},{'id':'chat','user_id':'900003','name':'Group','scan_account':1,'group_id':'-77','kind':'group'}]:
            self.app.save(data)
            with self.assertRaises(HTTPException):self.queue(messages=[self.app.AdminBatchMessage(id=data['id'],message='Hello')])
        self.assertEqual(self.count(),0)
        cid=self.contact(1);self.app.save({'id':'alias','user_id':'1','name':'Alias','scan_account':2,'group_id':'-88'})
        with self.assertRaises(HTTPException):self.queue(messages=[self.app.AdminBatchMessage(id=cid,message='Hi'),self.app.AdminBatchMessage(id='alias',message='Hi')])
        self.assertEqual(self.count(),0)
    def test_stale_template_rolls_back_entire_batch_and_rotation(self):
        pools={key:['One','Two','','',''] for key in self.app.TEMPLATE_KEYS};self.run_async(self.app.save_templates(self.app.Templates(template='One',followup_template='One',template_variants=pools)))
        msgs=[self.app.AdminBatchMessage(id=self.contact(1),message='One',template_choices={'template':'One'}),self.app.AdminBatchMessage(id=self.contact(2),message='Stale',template_choices={'template':'Stale'})]
        with self.assertRaises(HTTPException):self.queue(messages=msgs)
        self.assertEqual(self.count(),0);self.assertEqual(self.app.db.execute('select count(*) from template_rotation').fetchone()[0],0)
    def test_queue_keeps_original_identity_and_cancellation_works(self):
        r=self.queue(n=1);self.app.clients[1]=gw.FakeClient(user=202);self.process();self.assertEqual(self.c.sent,[]);self.assertEqual(self.app.clients[1].sent,[])
        self.run_async(self.app.cancel_queued_send(self.app.QueueCancel(id=r['messages'][0]['queue_id'])));self.app.clients[1]=self.c;self.advance(600);self.process();self.assertEqual(self.c.sent,[])
    def test_batch_endpoint_requires_authentication(self):self.assertEqual(TestClient(self.app.app).post('/groups/admins/send-batch',json={}).status_code,401)
