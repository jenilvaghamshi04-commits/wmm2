import asyncio,json,unittest
from datetime import datetime,timezone,timedelta
from unittest.mock import patch,AsyncMock
from types import SimpleNamespace
from fastapi import HTTPException
from fastapi.testclient import TestClient
import test_gateway as gw

class Clock(datetime):
    current=datetime(2026,10,23,6,0,tzinfo=timezone.utc)
    @classmethod
    def now(cls,tz=None):return cls.current.astimezone(tz) if tz else cls.current.replace(tzinfo=None)

class BackgroundSendTests(unittest.TestCase):
    load=gw.GatewayTests.load;tearDown=gw.GatewayTests.tearDown;run_async=gw.GatewayTests.run_async;sender=gw.GatewayTests.sender;contact=gw.GatewayTests.contact
    def setUp(self):
        gw.GatewayTests.setUp(self);self.app.enforce_send_pacing=self.real_pacing;self.app.datetime=Clock;Clock.current=datetime(2026,10,23,6,0,tzinfo=timezone.utc);self.c=self.sender()
    def queue(self,n=1,text='Reviewed text',request='queue-request-1',action='send',payload=None):
        cid=self.contact(n)
        return self.run_async(self.app.enqueue_send(self.app.QueueSend(action=action,request_id=request,payload=payload or {'id':cid,'account_id':1,'message':text})))
    def process(self):return self.run_async(self.app.process_manual_queue())
    def advance(self,n=121):Clock.current+=timedelta(seconds=n)
    def state(self,q):return self.app.db.execute('select status from manual_send_queue where id=?',(q['queue_id'],)).fetchone()[0]
    def original(self):
        cid=self.contact(99);self.run_async(self.app.deliver(cid,message='First'));root=self.app.records()[0]['delivery_id'];return cid,root
    def test_send_waits_on_server_and_survives_restart_without_browser(self):
        self.original();q=self.queue();self.process();self.assertEqual(len(self.c.sent),1);self.assertEqual(self.state(q),'Queued')
        self.app.db.close();self.load();self.app.datetime=Clock;self.app.enforce_send_pacing=self.real_pacing;self.app.clients[1]=self.c;self.app.recover_manual_queue();self.advance();self.process();self.assertEqual(self.state(q),'Sent');self.assertEqual(self.c.sent[-1][1],'Reviewed text');self.process();self.assertEqual(len(self.c.sent),2)
    def test_cancelled_message_never_sends(self):
        q=self.queue();self.run_async(self.app.cancel_queued_send(self.app.QueueCancel(id=q['queue_id'])));self.process();self.assertEqual(self.state(q),'Cancelled');self.assertEqual(self.c.sent,[])
    def test_original_sender_can_move_slots_but_never_changes_identity(self):
        q=self.queue();self.app.clients[1]=gw.FakeClient(user=202);self.process();self.assertEqual(self.state(q),'Queued');self.assertEqual(self.app.clients[1].sent,[])
        self.app.clients[2]=self.c;self.advance(31);self.process();self.assertEqual(self.state(q),'Sent');self.assertEqual(len(self.c.sent),1);self.assertEqual(self.app.records()[0]['account_id'],2)
    def test_stable_request_id_and_duplicate_contact_are_protected(self):
        q=self.queue();same=self.queue();self.assertEqual(q['queue_id'],same['queue_id'])
        with self.assertRaises(HTTPException):self.queue(text='Different text')
        with self.assertRaises(HTTPException):self.queue(request='different-request')
        with self.assertRaises(HTTPException):self.run_async(self.app.deliver('dm:1',message='Direct competing send'))
        self.assertEqual(self.c.sent,[])
    def test_network_uncertainty_is_not_retried(self):
        q=self.queue();self.c.fail=TimeoutError();self.process();self.assertEqual(self.state(q),'Needs attention');self.assertEqual(self.app.records()[0]['status'],'Uncertain');self.c.fail=None;self.process();self.assertEqual(self.c.sent,[])
    def test_restart_recovers_confirmed_delivery_without_resending(self):
        q=self.queue();self.process();self.app.db.execute("update manual_send_queue set status='Sending'");self.app.db.commit();self.app.recover_manual_queue();self.process();self.assertEqual(self.state(q),'Sent');self.assertEqual(len(self.c.sent),1)
    def test_restart_before_outbox_attempt_requeues_safely(self):
        q=self.queue();self.app.db.execute("update manual_send_queue set status='Sending'");self.app.db.commit();self.app.recover_manual_queue();self.process();self.assertEqual(self.state(q),'Sent');self.assertEqual(len(self.c.sent),1)
    def test_queued_text_is_fixed_after_template_edits(self):
        pools={key:['First '+key,'Second '+key,'','',''] for key in self.app.TEMPLATE_KEYS};self.run_async(self.app.save_templates(self.app.Templates(template='a',followup_template='b',template_variants=pools)))
        q=self.queue(payload={'id':self.contact(1),'message':'First template','template_choices':{'template':'First template'}})
        self.run_async(self.app.save_templates(self.app.Templates(template='Changed',followup_template='Changed followup')));self.process();self.assertEqual(self.state(q),'Sent');self.assertEqual(self.c.sent[0][1],'First template')
    def test_reply_arrival_cancels_queued_followup(self):
        cid,root=self.original();q=self.queue(99,action='follow-up',payload={'delivery_id':root,'message':'Following up','request_id':'follow-request'})
        self.app.record_reply('101','99',1,SimpleNamespace(id=700,date=Clock.current+timedelta(seconds=1),raw_text='no',out=False));self.advance()
        with patch.object(self.app,'sync_reply_pair',new=AsyncMock(return_value={'ok':True,'complete':True})):self.process()
        self.assertEqual(self.state(q),'Needs attention');self.assertEqual(len(self.c.sent),1)
    def test_inbox_reply_sends_after_reply_and_keeps_sender_and_delivery_type(self):
        cid,root=self.original();self.app.record_reply('101','99',1,SimpleNamespace(id=700,date=Clock.current+timedelta(seconds=1),raw_text='Tell me more',out=False))
        q=self.queue(99,action='reply',payload={'delivery_id':root,'message':'Happy to discuss','request_id':'reply-request'})
        self.advance();self.process();self.assertEqual(self.state(q),'Sent');latest=self.app.records()[0];self.assertTrue(latest['conversation_reply']);self.assertEqual(latest['principal'],'101');self.assertEqual(self.c.sent[-1][1],'Happy to discuss')
    def test_direct_inbox_reply_is_idempotent(self):
        cid,root=self.original();self.advance();body=self.app.Followup(delivery_id=root,message='Manual response',request_id='manual-reply-1');self.run_async(self.app.reply_to_conversation(body));self.run_async(self.app.reply_to_conversation(body));self.assertEqual(len(self.c.sent),2);self.assertTrue(self.app.records()[0]['conversation_reply'])
    def test_queue_and_reply_endpoints_require_auth(self):
        client=TestClient(self.app.app)
        for path in ['/send-queue','/send-queue/cancel','/conversation/reply']:self.assertEqual(client.post(path,json={}).status_code,401)

class RotationTests(unittest.TestCase):
    setUp=gw.GatewayTests.setUp;tearDown=gw.GatewayTests.tearDown;load=gw.GatewayTests.load;run_async=gw.GatewayTests.run_async
    def pools(self):
        pools={key:[key+' '+str(i) for i in range(5)] for key in self.app.TEMPLATE_KEYS};self.run_async(self.app.save_templates(self.app.Templates(template='a',followup_template='b',template_variants=pools)));return pools
    def test_every_option_once_before_repeat_and_no_boundary_repeat(self):
        self.pools();chosen=[self.app.choose_template('template') for _ in range(15)]
        for start in [0,5,10]:self.assertEqual(len(set(chosen[start:start+5])),5)
        self.assertNotEqual(chosen[4],chosen[5]);self.assertNotEqual(chosen[9],chosen[10])
    def test_rotation_survives_reload_and_is_independent_per_type(self):
        self.pools();first=self.app.choose_template('template');self.app.db.close();self.load();self.assertNotEqual(self.app.choose_template('template'),first);self.assertEqual(len(self.app.rotation_status(self.app.settings())['followup_template']['available']),5)
    def test_identical_and_empty_options_are_not_separate_choices(self):
        pools=self.pools();pools['template']=['Same','Same','','Other',''];self.run_async(self.app.save_templates(self.app.Templates(template='a',followup_template='b',template_variants=pools)));a=self.app.choose_template('template');b=self.app.choose_template('template');self.assertNotEqual(a,b)
    def test_reservation_transaction_rolls_back_if_any_option_is_stale(self):
        pools=self.pools()
        with self.assertRaises(HTTPException):
            with self.app.db:self.app.reserve_template_choices({'template':pools['template'][0],'yes_demo_template':'Stale'})
        self.assertEqual(len(self.app.rotation_status(self.app.settings())['template']['available']),5)
    def test_used_choice_rejected_until_other_choices_consumed(self):
        pools=self.pools()
        with self.app.db:self.app.reserve_template_choices({'template':pools['template'][0]})
        with self.assertRaises(HTTPException):
            with self.app.db:self.app.reserve_template_choices({'template':pools['template'][0]})
        self.assertEqual(len(self.app.rotation_status(self.app.settings())['template']['available']),4)
