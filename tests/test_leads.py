import asyncio,importlib.util,json,os,tempfile,unittest
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import HTTPException
from telethon import errors
from pydantic import ValidationError
from test_gateway import FakeClient

class LeadTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'DATA_DIR':self.tmp.name,'DASHBOARD_KEY':'test-secret','TELEGRAM_API_ID':'','TELEGRAM_API_HASH':''});self.env.start()
        spec=importlib.util.spec_from_file_location('lead_gateway','backend/app.py');self.app=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.app);self.real_followup_timing=self.app.followup_timing;__import__('legacy_timing').isolate_scheduler(self.app);self.app.enforce_send_pacing=lambda *args:None
        self.client=FakeClient(user=101);self.app.clients[1]=self.client
        self.app.save({'id':'scanA:7','user_id':'7','name':'Lead Seven','username':'','kind':'dm','group':'Test group','group_id':'-1001','scanned_at':datetime.now(timezone.utc).isoformat()})
    def tearDown(self):self.app.db.close();self.env.stop();self.tmp.cleanup()
    def run_async(self,coro):return asyncio.run(coro)
    def send(self):
        self.run_async(self.app.deliver('scanA:7',1,message='Hi there'))
        return self.app.records()[0]['delivery_id']
    def lead(self):return next(l for l in self.app.lead_records() if l['key']=='dm:7')
    def old_send(self,days=4):
        did=self.send();self.app.db.execute('update outbox set at=? where id=?',((datetime.now(timezone.utc)-timedelta(days=days)).isoformat(),did));self.app.db.commit();return did
    def message(self,mid=1,**kwargs):return SimpleNamespace(id=mid,date=datetime.now(timezone.utc),out=False,raw_text='Yes, tell me more',**kwargs)
    def test_new_contact_and_sent_lead_transition(self):
        self.assertEqual(self.lead()['stage'],'New');self.assertEqual(self.lead()['reply_status'],'Not contacted');self.assertFalse(self.lead()['followup_due'])
        self.send();lead=self.lead();self.assertEqual(lead['stage'],'Contacted');self.assertEqual(lead['reply_status'],'Awaiting reply');self.assertTrue(lead['reminder_active']);self.assertFalse(lead['followup_due'])
    def test_reminders_3_5_7_days_and_pause(self):
        self.old_send();self.assertTrue(self.lead()['followup_due'])
        for days in (5,7):
            self.run_async(self.app.update_lead(self.app.LeadUpdate(key='dm:7',reminder_days=days)));self.assertFalse(self.lead()['followup_due']);self.assertEqual(self.lead()['reminder_days'],days)
        self.run_async(self.app.update_lead(self.app.LeadUpdate(key='dm:7',reminder_days=3,reminders_enabled=False)));self.assertFalse(self.lead()['reminder_active']);self.assertIsNone(self.lead()['due_at'])
        with self.assertRaises(ValidationError):self.app.LeadUpdate(key='dm:7',reminder_days=4)
    def test_received_reply_stops_reminders_and_marks_attention(self):
        self.old_send();usage=self.app.usage('101')['dm']['used'];self.assertTrue(self.app.record_reply('101','7',1,self.message()))
        lead=self.lead();self.assertEqual(lead['stage'],'Replied');self.assertEqual(lead['reply_status'],'Replied');self.assertTrue(lead['needs_attention']);self.assertFalse(lead['followup_due']);self.assertFalse(lead['reminder_active']);self.assertEqual(self.app.usage('101')['dm']['used'],usage)
    def test_outgoing_old_unknown_sender_and_uncontacted_messages_ignored(self):
        self.assertFalse(self.app.record_reply('101','7',1,self.message()))
        self.send();message=self.message();message.out=True;self.assertFalse(self.app.record_reply('101','7',1,message))
        message=self.message();message.date-=timedelta(days=1);self.assertFalse(self.app.record_reply('101','7',1,message))
        self.assertFalse(self.app.record_reply('999','7',1,self.message()));self.assertFalse(self.app.record_reply('101','8',1,self.message()));self.assertEqual(self.lead()['reply_status'],'Awaiting reply')
    def test_reply_dedup_review_and_new_reply_flag(self):
        self.send();m=self.message();self.app.record_reply('101','7',1,m);self.assertFalse(self.app.record_reply('101','7',1,m));self.assertEqual(len(self.lead()['replies']),1)
        self.run_async(self.app.update_lead(self.app.LeadUpdate(key='dm:7',acknowledge=True)));self.assertFalse(self.lead()['needs_attention'])
        m=self.message(mid=2);m.date+=timedelta(seconds=1);self.app.record_reply('101','7',1,m);self.assertTrue(self.lead()['needs_attention'])
    def test_manual_later_stage_preserved_on_reply_and_followup(self):
        did=self.send();self.run_async(self.app.update_lead(self.app.LeadUpdate(key='dm:7',stage='Proposal')));self.app.record_reply('101','7',1,self.message())
        self.assertEqual(self.lead()['stage'],'Proposal');self.run_async(self.app.follow_up(self.app.Followup(delivery_id=did,message='Answer to your question',request_id='lead-followup-001')));self.assertEqual(self.lead()['stage'],'Proposal');self.assertFalse(self.lead()['reminder_active'])
    def test_client_stops_reminder_and_preserves_stage(self):
        self.old_send();self.run_async(self.app.update_lead(self.app.LeadUpdate(key='dm:7',stage='Client')));self.assertFalse(self.lead()['reminder_active']);self.app.record_reply('101','7',1,self.message());self.assertEqual(self.lead()['stage'],'Client');self.assertFalse(self.lead()['needs_attention'])
    def test_followup_restarts_delay_from_last_confirmed_send(self):
        did=self.old_send();self.assertTrue(self.lead()['followup_due']);self.run_async(self.app.follow_up(self.app.Followup(delivery_id=did,message='Checking in',request_id='delay-followup-001')));self.assertFalse(self.lead()['followup_due']);self.assertGreater(datetime.fromisoformat(self.lead()['due_at']),datetime.now(timezone.utc)+timedelta(days=2))
    def test_identity_survives_alias_scan_and_reload(self):
        self.send();self.run_async(self.app.update_lead(self.app.LeadUpdate(key='dm:7',stage='Meeting',reminder_days=7)));self.app.record_reply('101','7',1,self.message())
        self.app.save({'id':'scanB:7','user_id':'7','name':'Same lead','kind':'dm'});self.assertEqual(len(self.app.lead_records()),1)
        self.assertEqual(self.lead()['stage'],'Meeting');self.assertEqual(self.lead()['reminder_days'],7)
        self.app.db.close();spec=importlib.util.spec_from_file_location('reloaded_leads','backend/app.py');self.app=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.app);self.real_followup_timing=self.app.followup_timing;__import__('legacy_timing').isolate_scheduler(self.app);self.app.enforce_send_pacing=lambda *args:None;self.assertEqual(self.lead()['stage'],'Meeting');self.assertEqual(self.lead()['reply_status'],'Replied')
    def test_groups_do_not_become_replies_or_reminders(self):
        self.app.save({'id':'group:-1001','group_id':'-1001','name':'Test group','kind':'group'});self.run_async(self.app.deliver('group:-1001',1,kind='group',message='Hello group'));lead=next(l for l in self.app.lead_records() if l['kind']=='group');self.assertEqual(lead['reply_status'],'Not tracked');self.assertFalse(lead['reminder_active'])
    def test_history_sync_collects_only_incoming_and_tracks_cursor(self):
        self.old_send();calls=[]
        async def get_messages(peer,**options):
            calls.append(options);a=self.message(mid=12);b=self.message(mid=13);b.out=True;return [a,b]
        self.client.get_messages=get_messages;result=self.run_async(self.app.sync_replies('dm:7',limit=3));self.assertTrue(result['results'][0]['ok']);self.assertEqual(self.lead()['reply_status'],'Replied');self.assertTrue(self.lead()['sync_complete']);self.assertEqual(len(self.lead()['replies']),1);self.assertTrue(calls[0]['reverse']);self.assertIn('offset_date',calls[0]);self.assertEqual(self.app.db.execute('select cursor from reply_sync').fetchone()[0],13)
        self.assertEqual(self.run_async(self.app.sync_replies('dm:7'))['checked'],0)
    def test_partial_history_remains_incomplete_and_resumes_by_id(self):
        self.old_send();calls=[]
        async def get_messages(peer,**options):
            calls.append(options);result=[self.message(mid=n+1) for n in range(100)] if len(calls)==1 else []
            for m in result:m.out=True
            return result
        self.client.get_messages=get_messages;self.run_async(self.app.sync_replies('dm:7'));self.assertFalse(self.lead()['sync_complete']);self.assertEqual(self.lead()['reply_status'],'Awaiting reply')
        past=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat();self.app.db.execute('update reply_sync set checked_at=?,next_check_at=?',(past,past));self.app.db.commit();self.run_async(self.app.sync_replies('dm:7'));self.assertEqual(calls[1]['min_id'],100);self.assertNotIn('offset_date',calls[1]);self.assertTrue(self.lead()['sync_complete'])
    def test_sync_failure_and_wrong_account_never_claim_checked(self):
        self.old_send();self.client.user=999;result=self.run_async(self.app.sync_replies('dm:7'));self.assertFalse(result['results'][0]['ok']);self.assertFalse(self.lead()['sync_complete']);self.assertIn('original sender',self.lead()['sync_error']);self.assertEqual(self.lead()['reply_status'],'Awaiting reply')
    def test_history_flood_wait_respects_backoff(self):
        self.old_send();calls=[]
        async def get_messages(*args,**kwargs):calls.append(1);raise errors.FloodWaitError(request=None,capture=1200)
        self.client.get_messages=get_messages;self.run_async(self.app.sync_replies('dm:7'));self.assertIn('1200s',self.lead()['sync_error']);self.run_async(self.app.sync_replies('dm:7'));self.assertEqual(len(calls),1)
    def test_unknown_lead_and_group_sync_rejected(self):
        with self.assertRaises(HTTPException):self.run_async(self.app.update_lead(self.app.LeadUpdate(key='dm:888',stage='Client')))
        with self.assertRaises(HTTPException):self.run_async(self.app.check_replies(self.app.ReplySync(key='group:-1001')))
    def test_live_listener_records_only_contacted_private_replies(self):
        self.send();handlers=[];self.client.add_event_handler=lambda handler,builder:handlers.append(handler);self.app.attach_reply_listener(self.client,1)
        event=SimpleNamespace(is_private=True,sender_id=7,message=self.message());self.run_async(handlers[0](event));self.assertEqual(self.lead()['reply_status'],'Replied')
        event.is_private=False;event.message=self.message(mid=2);self.run_async(handlers[0](event));self.assertEqual(len(self.lead()['replies']),1)

    def test_reply_detection_follows_sender_identity_when_slot_changes(self):
        self.old_send();self.app.clients.pop(1);self.app.clients[2]=self.client
        async def get_messages(peer,**kwargs):return [self.message(mid=33)]
        self.client.get_messages=get_messages;result=self.run_async(self.app.sync_replies('dm:7'));self.assertTrue(result['results'][0]['ok']);self.assertEqual(self.lead()['latest_reply']['account_id'],2)
        handlers=[];self.client.add_event_handler=lambda handler,builder:handlers.append(handler);self.app.attach_reply_listener(self.client,2)
        self.run_async(handlers[0](SimpleNamespace(is_private=True,sender_id=7,message=self.message(mid=34))));self.assertEqual(len(self.lead()['replies']),2)
