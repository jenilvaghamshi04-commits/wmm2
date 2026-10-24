import unittest,json
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
from pydantic import ValidationError
import test_gateway as gw

class WorkspaceResetTests(unittest.TestCase):
    setUp=gw.GatewayTests.setUp;tearDown=gw.GatewayTests.tearDown;load=gw.GatewayTests.load
    run_async=gw.GatewayTests.run_async;sender=gw.GatewayTests.sender;contact=gw.GatewayTests.contact
    def seed(self):
        self.c=self.sender();cid=self.contact(999)
        self.run_async(self.app.save_templates(self.app.Templates(template='Initial text',followup_template='Saved follow-up',yes_pitch_template='Saved pitch',yes_demo_template='Saved invitation',no_reply_template='Saved no offer')))
        self.run_async(self.app.deliver(cid,message='Hello',token_symbol='ABC',exchange='okx',auto_yes=True))
        self.app.record_reply('101','999',1,SimpleNamespace(id=500,date=datetime.now(timezone.utc)+timedelta(seconds=1),raw_text='yes',out=False))
        self.app.seed_auto_followups()
        self.app.db.execute("insert into telegram_api values(1,123,'test-hash')")
        self.app.db.execute("insert into dashboard_sessions values('test-session','admin','2099-01-01T00:00:00+00:00')")
        self.app.db.execute("insert into folder_pauses values('101','2099-01-01T00:00:00+00:00','Telegram wait')")
        self.app.db.execute("insert into deliveries values('old','Sent','2026-10-01T00:00:00+00:00','')")
        self.app.db.commit();return self.app.settings()
    def reset(self,request='reset-qa-0001'):return self.run_async(self.app.reset_workspace(self.app.WorkspaceReset(confirmation='RESET DATA',request_id=request)))
    def test_clears_records_and_preserves_sessions_credentials_templates_and_waits(self):
        cfg=self.seed();result=self.reset();self.assertTrue(result['ok']);self.assertEqual(result['counts']['messages'],1);self.assertEqual(result['counts']['replies'],1)
        for table in self.app.WORKSPACE_DATA_TABLES:self.assertEqual(self.app.db.execute('select count(*) from '+table).fetchone()[0],0,table)
        self.assertEqual(self.app.settings(),cfg);self.assertIs(self.app.clients[1],self.c)
        for table in ['telegram_api','dashboard_sessions','account_info','folder_pauses']:self.assertEqual(self.app.db.execute('select count(*) from '+table).fetchone()[0],1,table)
        self.assertEqual(self.app.usage('101')['dm']['used'],0)
    def test_repeat_request_does_not_clear_new_records(self):
        self.seed();first=self.reset();self.contact(42);again=self.reset();self.assertTrue(again['already_reset']);self.assertEqual(again['counts'],first['counts']);self.assertEqual(len(self.app.contacts()),1)
    def test_preview_does_not_delete_anything(self):
        self.seed();preview=self.run_async(self.app.preview_workspace_reset());self.assertEqual(preview['counts']['contacts'],1);self.assertEqual(len(self.app.records()),1);self.assertEqual(len(self.app.contacts()),1)
    def test_explicit_confirmation_and_request_id_required(self):
        for value in ['','RESET','reset data']:
            with self.assertRaises(ValidationError):self.app.WorkspaceReset(confirmation=value,request_id='reset-qa-0001')
        with self.assertRaises(ValidationError):self.app.WorkspaceReset(confirmation='RESET DATA',request_id='x')
    def test_stale_reply_check_does_not_recreate_deleted_history(self):
        self.seed();self.reset();result=self.run_async(self.app.sync_reply_pair('101','999',1,'2026-10-01T00:00:00+00:00'));self.assertTrue(result['skipped']);self.assertEqual(self.app.db.execute('select count(*) from reply_sync').fetchone()[0],0)
    def test_automation_queues_stay_empty_after_reset_and_restart(self):
        self.seed();self.reset();self.run_async(self.app.process_auto_yes());self.run_async(self.app.process_auto_followups());self.assertEqual(len(self.c.sent),1)
        self.app.db.close();self.load();self.app.clients[1]=self.c;self.app.seed_folder_routes();self.app.seed_auto_followups();self.assertEqual(self.app.records(),[]);self.assertEqual(self.app.contacts(),[]);self.assertEqual(self.app.lead_records(),[])
    def test_reset_can_run_again_with_new_explicit_request(self):
        self.seed();self.reset();self.contact(44);self.reset('reset-qa-0002');self.assertEqual(self.app.contacts(),[])
    def test_reset_waits_for_active_send_and_then_clears_its_record(self):
        import asyncio
        async def run():
            client=self.sender();cid=self.contact(99);started=asyncio.Event();release=asyncio.Event()
            async def send_message(peer,text):started.set();await release.wait();client.sent.append((peer,text))
            client.send_message=send_message
            send=asyncio.create_task(self.app.deliver(cid,message='An active send'))
            await started.wait();reset=asyncio.create_task(self.app.reset_workspace(self.app.WorkspaceReset(confirmation='RESET DATA',request_id='reset-concurrent-001')))
            await asyncio.sleep(0);self.assertFalse(reset.done());release.set();await send;result=await reset
            self.assertEqual(result['counts']['messages'],1);self.assertEqual(self.app.records(),[]);self.assertIs(self.app.clients[1],client)
        self.run_async(run())
