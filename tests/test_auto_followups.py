import unittest,json
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import HTTPException
import test_gateway as gw

class AutomaticFollowupTests(unittest.TestCase):
    setUp=gw.GatewayTests.setUp;tearDown=gw.GatewayTests.tearDown;load=gw.GatewayTests.load
    run_async=gw.GatewayTests.run_async;sender=gw.GatewayTests.sender;contact=gw.GatewayTests.contact
    def original(self,age=timedelta(days=3,seconds=1),slot=1):
        self.c=self.sender(slot);self.cid=self.contact(999)
        async def messages(peer,**kwargs):return []
        self.c.get_messages=messages
        self.run_async(self.app.deliver(self.cid,slot,message='Hi @username about $TOKEN',token_symbol='ABC',exchange='mexc'))
        self.root=self.app.records()[0]['delivery_id'];at=(datetime.now(timezone.utc)-age).isoformat()
        self.app.db.execute('update outbox set at=? where id=?',(at,self.root));self.app.db.commit()
    def process(self):return self.run_async(self.app.process_auto_followups())
    def state(self):return self.app.auto_followup_summary('999')['status']
    def reply(self,text='Hello'):
        msg=SimpleNamespace(id=600,date=datetime.now(timezone.utc),raw_text=text,out=False)
        self.app.record_reply('101','999',1,msg)
    def test_waits_72_hours_then_sends_once(self):
        self.original(timedelta(days=2,hours=23));self.process();self.assertEqual(len(self.c.sent),1);self.assertEqual(self.state(),'Scheduled')
        self.app.db.execute('update outbox set at=? where id=?',((datetime.now(timezone.utc)-timedelta(days=3,seconds=1)).isoformat(),self.root));self.app.db.commit();self.process();self.process()
        self.assertEqual(len(self.c.sent),2);self.assertEqual(self.c.sent[-1][1],self.app.DEFAULT_FOLLOWUP);self.assertEqual(self.state(),'Complete');self.assertEqual(self.app.usage('101')['dm']['used'],1)
    def test_existing_unreplied_messages_are_scheduled(self):
        self.original();self.process();self.assertEqual(len(self.c.sent),2)
    def test_detected_reply_cancels(self):
        self.original();self.reply();self.process();self.assertEqual(len(self.c.sent),1);self.assertEqual(self.state(),'Cancelled')
    def test_sync_discovers_reply_before_send(self):
        self.original()
        async def messages(peer,**kwargs):return [SimpleNamespace(id=600,date=datetime.now(timezone.utc),raw_text='Yes',out=False)]
        self.c.get_messages=messages;self.process();self.assertEqual(len(self.c.sent),1);self.assertEqual(self.state(),'Cancelled')
    def test_incomplete_history_waits(self):
        self.original()
        async def messages(peer,**kwargs):return [SimpleNamespace(id=i+10,date=datetime.now(timezone.utc),raw_text='Old outgoing',out=True) for i in range(100)]
        self.c.get_messages=messages;self.process();self.assertEqual(len(self.c.sent),1);self.assertEqual(self.state(),'Waiting')
    def test_history_error_waits(self):
        self.original()
        async def messages(peer,**kwargs):raise OSError('offline')
        self.c.get_messages=messages;self.process();self.assertEqual(len(self.c.sent),1);self.assertEqual(self.state(),'Waiting')
    def test_missing_sender_never_uses_other_account(self):
        self.original();other=self.sender(user=202);self.process();self.assertEqual(len(self.c.sent),1);self.assertEqual(other.sent,[]);self.assertEqual(self.state(),'Waiting')
    def test_original_identity_moves_slots(self):
        self.original();other=self.sender(user=202);self.app.clients[3]=self.c;self.process();self.assertEqual(len(self.c.sent),2);self.assertEqual(other.sent,[]);self.assertEqual(self.app.records()[0]['account_id'],3)
    def test_manual_followup_resolves_original_identity(self):
        self.original();other=self.sender(user=202);self.app.clients[2]=self.c
        self.run_async(self.app.follow_up(self.app.Followup(delivery_id=self.root,message='Manual follow-up',request_id='manual-root-001')))
        self.assertEqual(len(self.c.sent),2);self.assertEqual(other.sent,[])
    def test_internal_followup_cannot_use_wrong_sender(self):
        self.original();other=self.sender(2,user=202)
        with self.assertRaises(HTTPException):self.run_async(self.app.deliver(self.cid,2,message='Incorrect sender',followup_of=self.root,request_id='wrong-root-001'))
        self.assertEqual(other.sent,[])
    def test_global_pause_and_lead_pause(self):
        self.original();self.run_async(self.app.save_templates(self.app.Templates(template='Hi',followup_template='Follow',auto_followup_enabled=False)));self.process();self.assertEqual(len(self.c.sent),1);self.assertEqual(self.state(),'Paused')
        self.run_async(self.app.save_templates(self.app.Templates(template='Hi',followup_template='Follow',auto_followup_enabled=True)))
        self.run_async(self.app.update_lead(self.app.LeadUpdate(key='dm:999',reminders_enabled=False)))
        self.process();self.assertEqual(len(self.c.sent),1);self.assertEqual(self.state(),'Paused')
    def test_manual_followup_already_sent_cancels_automatic(self):
        self.original();self.run_async(self.app.follow_up(self.app.Followup(delivery_id=self.root,message='Manual follow-up',request_id='manual-root-001')));self.process();self.assertEqual(len(self.c.sent),2);self.assertEqual(self.state(),'Cancelled')
    def test_progressed_lead_stops(self):
        self.original();self.app.db.execute("update lead_settings set stage='Meeting' where key='dm:999'");self.app.db.commit();self.process();self.assertEqual(len(self.c.sent),1);self.assertEqual(self.state(),'Cancelled')
    def test_uncertain_attempt_is_not_retried(self):
        self.original();self.c.fail=RuntimeError('timeout');self.process();self.c.fail=None;self.process();self.assertEqual(len(self.c.sent),1);self.assertEqual(self.state(),'Needs attention');self.assertEqual(self.app.records()[0]['status'],'Uncertain')
    def test_restart_after_confirmed_send_does_not_resend(self):
        self.original();self.process();self.app.db.execute("update auto_followup_jobs set status='Sending'");self.app.db.commit();self.app.db.close();self.load();self.app.clients[1]=self.c;self.process();self.assertEqual(len(self.c.sent),2);self.assertEqual(self.state(),'Complete')
    def test_current_followup_template_personalized(self):
        self.original();self.run_async(self.app.save_templates(self.app.Templates(template='Hi',followup_template='Hi @username, $TOKEN on {{exchange}}')));self.process();self.assertEqual(self.c.sent[-1][1],'Hi Person 999, $ABC on MEXC')
    def test_pending_job_survives_restart(self):
        self.original();self.app.seed_auto_followups();self.app.db.close();self.load();self.app.clients[1]=self.c;self.process();self.assertEqual(len(self.c.sent),2);self.assertEqual(self.state(),'Complete')
    def test_reply_race_rechecked_under_delivery_lock(self):
        self.original();real=self.app.deliver
        async def raced(*args,**kwargs):self.reply();return await real(*args,**kwargs)
        with patch.object(self.app,'deliver',raced):self.process()
        self.assertEqual(len(self.c.sent),1);self.assertEqual(self.state(),'Cancelled')
    def test_two_scans_of_same_recipient_one_job(self):
        self.original();data=json.loads(self.app.db.execute('select data from contacts where id=?',(self.cid,)).fetchone()[0]);data['id']='another:999';self.app.save(data);self.process();self.assertEqual(self.app.db.execute('select count(*) from auto_followup_jobs').fetchone()[0],1)
    def test_group_never_gets_automatic_followup(self):
        c=self.sender();cid=self.contact(4,'group');self.run_async(self.app.deliver(cid,kind='group',message='Group post'));self.process();self.assertEqual(len(c.sent),1);self.assertEqual(self.app.db.execute('select count(*) from auto_followup_jobs').fetchone()[0],0)
