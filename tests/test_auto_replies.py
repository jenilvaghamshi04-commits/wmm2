import unittest,json
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
from fastapi import HTTPException
import test_gateway as gateway_tests

class AutomaticReplyTests(unittest.TestCase):
    setUp=gateway_tests.GatewayTests.setUp;tearDown=gateway_tests.GatewayTests.tearDown;load=gateway_tests.GatewayTests.load
    run_async=gateway_tests.GatewayTests.run_async;sender=gateway_tests.GatewayTests.sender;contact=gateway_tests.GatewayTests.contact
    def arm(self,slot=1):
        self.client=self.sender(slot);cid=self.contact(999)
        result=self.run_async(self.app.deliver(cid,slot,message='Hey @username about $TOKEN',token_symbol='ABC',exchange='bitget',auto_yes=True))
        return cid
    def reply(self,text='yeh',mid=500,**kwargs):
        msg=SimpleNamespace(id=mid,date=datetime.now(timezone.utc)+timedelta(seconds=1),raw_text=text,out=False,**kwargs)
        return self.app.record_reply('101','999',1,msg)
    def process(self):return self.run_async(self.app.process_auto_yes())
    def test_yes_two_messages_in_order_once_and_quota(self):
        self.arm();self.reply();self.process();self.reply('yes',501);self.process()
        self.assertEqual(len(self.client.sent),3)
        self.assertIn('Nice to meet you Person 999,',self.client.sent[1][1]);self.assertIn('$ABC chart on Bitget',self.client.sent[1][1]);self.assertEqual(self.client.sent[2][1],self.app.DEFAULT_YES_DEMO)
        self.assertEqual(self.app.usage('101')['dm']['used'],1)
        a=self.app.auto_yes_summary('999',{'101'});self.assertEqual((a['status'],a['sent_parts'],a['total_parts']),('Complete',2,2))
        self.assertEqual(sum(d['automation_step']>0 for d in self.app.records()),2)
    def test_legacy_negative_job_is_cancelled_on_upgrade(self):
        self.arm();self.reply('yes');self.app.db.execute("update auto_yes_jobs set branch='no',pitch='Legacy negative offer'");self.app.db.commit()
        self.app.db.close();self.load();self.app.clients[1]=self.client;self.process()
        self.assertEqual(len(self.client.sent),1);self.assertEqual(self.app.db.execute('select status from auto_yes_jobs').fetchone()[0],'Cancelled')
    def test_non_affirmative_reply_cancels_queued_yes_before_any_response(self):
        self.arm();self.reply('yes');self.reply('Let me check with our team',501);self.process()
        self.assertEqual(len(self.client.sent),1);self.assertEqual(self.app.auto_yes_summary('999',{'101'})['status'],'Cancelled')
    def test_no_receives_no_automatic_response(self):
        self.arm();self.reply('no');self.process();self.reply('nope',501);self.process()
        self.assertEqual(len(self.client.sent),1);self.assertEqual(self.app.auto_yes_summary('999',{'101'})['total_parts'],0)
    def test_ambiguous_and_forwarded_wait(self):
        self.arm()
        for i,text in enumerate(['maybe','yes?','yesterday','no problem','yes but no','no?','sure?']):self.reply(text,500+i)
        self.reply('yes',600,fwd_from=True);self.process();self.assertEqual(len(self.client.sent),1)
    def test_optout_cancels_queued_and_later_yes(self):
        self.arm();self.reply();self.reply('stop messaging me',501);self.process();self.reply('yes',502);self.process()
        self.assertEqual(len(self.client.sent),1);self.assertEqual(self.app.auto_yes_summary('999',{'101'})['status'],'Cancelled')
    def test_old_messages_cannot_arm(self):
        self.arm();self.app.db.execute('update message_details set telegram_message_id=1000');self.app.db.commit();self.reply('yes',500);self.process();self.assertEqual(len(self.client.sent),1)
    def test_no_old_conversations_autoenrolled(self):
        c=self.sender();cid=self.contact(999);self.run_async(self.app.deliver(cid,message='Hello'));self.reply();self.process();self.assertEqual(len(c.sent),1)
    def test_affirmative_templates_snapshotted_and_legacy_negative_template_ignored(self):
        self.run_async(self.app.save_templates(self.app.Templates(template='Hello',followup_template='Follow',yes_pitch_template='Original pitch @username {{exchange}} @TOKEN')))
        self.arm();self.run_async(self.app.save_templates(self.app.Templates(template='New initial',followup_template='New follow',yes_pitch_template='Changed pitch',no_reply_template='Ignored legacy offer')))
        self.reply('yes');self.process();self.assertEqual(self.client.sent[1][1],'Original pitch Person 999 Bitget $ABC')
        self.assertNotIn('no_reply_template',self.app.settings())
    def test_global_and_per_contact_pause(self):
        self.arm();self.reply();self.run_async(self.app.save_templates(self.app.Templates(template='Hello',followup_template='Follow',auto_yes_enabled=False)));self.process();self.assertEqual(len(self.client.sent),1)
        self.run_async(self.app.save_templates(self.app.Templates(template='Hello',followup_template='Follow',auto_yes_enabled=True)))
        self.run_async(self.app.update_auto_yes(self.app.AutoYesControl(key='dm:999',enabled=False)));self.process();self.assertEqual(len(self.client.sent),1)
        self.run_async(self.app.update_auto_yes(self.app.AutoYesControl(key='dm:999',enabled=True)));self.process();self.assertEqual(len(self.client.sent),3)
    def test_failure_uncertain_stops_no_duplicate(self):
        self.arm();self.reply();self.client.fail=RuntimeError('Network timeout');self.process();self.client.fail=None;self.process()
        self.assertEqual(len(self.client.sent),1);self.assertEqual(self.app.auto_yes_summary('999',{'101'})['status'],'Needs attention');self.assertEqual(self.app.records()[0]['status'],'Uncertain')
    def test_second_message_failure_preserves_first(self):
        self.arm();self.reply();original=self.client.send_message
        async def fail_second(peer,text):
            if text==self.app.DEFAULT_YES_DEMO:raise RuntimeError('timeout')
            return await original(peer,text)
        self.client.send_message=fail_second;self.process();self.process();self.assertEqual(len(self.client.sent),2);self.assertEqual(self.app.auto_yes_summary('999',{'101'})['sent_parts'],1)
    def test_original_sender_moves_slots(self):
        self.arm();self.reply();self.app.clients.pop(1);self.app.clients[2]=self.client;self.process();self.assertEqual(len(self.client.sent),3)
        self.assertTrue(all(d['account_id']==2 for d in self.app.records() if d['automation_step']))
    def test_missing_original_sender_waits(self):
        self.arm();self.reply();self.app.clients[1]=self.sender(user=202);self.process();self.assertEqual(len(self.client.sent),1);self.assertEqual(self.app.auto_yes_summary('999',{'101'})['status'],'Pending')
    def test_crash_after_confirmed_part_reuses_outbox(self):
        self.arm();self.reply();self.process();self.app.db.execute("update auto_yes_jobs set step=0,status='Pending'");self.app.db.execute("update auto_yes_enrollments set enabled=1");self.app.db.commit();self.process();self.assertEqual(len(self.client.sent),3);self.assertEqual(self.app.auto_yes_summary('999',{'101'})['status'],'Complete')
    def test_restart_keeps_pending_job_and_no_replay(self):
        self.arm();self.reply('no');self.app.db.close();self.load();self.app.clients[1]=self.client;self.process();self.reply('no');self.process();self.assertEqual(len(self.client.sent),1)
    def test_exchange_and_token_required_before_initial(self):
        c=self.sender();cid=self.contact(999)
        for exchange,token in [('', 'ABC'),('invalid','ABC'),('bitget','')]:
            with self.assertRaises(HTTPException):self.run_async(self.app.deliver(cid,message='Hello',exchange=exchange,token_symbol=token,auto_yes=True))
        self.assertEqual(c.sent,[])
    def test_group_does_not_arm(self):
        c=self.sender();cid=self.contact(999,'group')
        with self.assertRaises(HTTPException):self.run_async(self.app.deliver(cid,kind='group',message='Hello',exchange='okx',token_symbol='ABC',auto_yes=True))
        self.assertEqual(c.sent,[])
    def test_all_exchanges_and_placeholders(self):
        self.assertEqual(len(self.app.EXCHANGES),14)
        for key,name in self.app.EXCHANGES.items():self.assertEqual(self.app.normalize_exchange(name),key)
        self.assertEqual(self.app.personalize_message('Hi @username @TOKEN {{exchange}}',{'username':'alice'},'ABC','lbank'),'Hi @alice $ABC LBank')
    def test_completed_response_disables_enrollment_and_cannot_resume(self):
        self.arm();self.reply();self.process();summary=self.app.auto_yes_summary('999',{'101'});self.assertFalse(summary['enabled']);self.assertTrue(summary['completed_once'])
        with self.assertRaises(HTTPException) as e:self.run_async(self.app.update_auto_yes(self.app.AutoYesControl(key='dm:999',enabled=True)))
        self.assertEqual(e.exception.status_code,409);self.reply('yes',501);self.reply('no',502);self.process();self.assertEqual(len(self.client.sent),3)
    def test_completed_sequence_stays_stopped_after_restart_and_template_edit(self):
        self.arm();self.reply();self.process();self.app.db.close();self.load();self.app.clients[1]=self.client
        self.run_async(self.app.save_templates(self.app.Templates(template='New initial',followup_template='New follow',yes_pitch_template='Different pitch',yes_demo_template='Different invitation')))
        self.reply('yeh',501);self.process();self.assertEqual(len(self.client.sent),3);self.assertFalse(self.app.auto_yes_summary('999',{'101'})['enabled'])
    def test_upgrade_disables_previously_completed_enrollment_without_resending(self):
        self.arm();self.reply();self.process();self.app.db.execute('update auto_yes_enrollments set enabled=1');self.app.db.commit();self.app.db.close();self.load();self.app.clients[1]=self.client;self.process();self.assertFalse(self.app.auto_yes_summary('999',{'101'})['enabled']);self.assertEqual(len(self.client.sent),3)
