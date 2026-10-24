import asyncio,importlib.util,os,tempfile,unittest,sqlite3,json
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import HTTPException
from telethon import errors

class FakeClient:
    def __init__(self,*args,user=101,authorized=True,**kwargs):self.user=user;self.authorized=authorized;self.sent=[];self.fail=None
    async def connect(self):pass
    async def disconnect(self):pass
    def is_connected(self):return True
    async def is_user_authorized(self):return self.authorized
    async def get_me(self):return SimpleNamespace(id=self.user,first_name='Sender',last_name=str(self.user),phone='919999999999')
    async def get_input_entity(self,uid):return uid
    async def get_entity(self,target):return SimpleNamespace(id=target,megagroup=True)
    async def send_message(self,peer,text):
        if self.fail:raise self.fail
        self.sent.append((peer,text))
    async def send_code_request(self,phone):return SimpleNamespace(phone_code_hash='hash-'+phone)
    async def sign_in(self,*args,**kwargs):self.authorized=True
    async def log_out(self):self.authorized=False

class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'DATA_DIR':self.tmp.name,'DASHBOARD_KEY':'test-secret','TELEGRAM_API_ID':'','TELEGRAM_API_HASH':''});self.env.start();self.load()
    def load(self):
        spec=importlib.util.spec_from_file_location('gateway_under_test','backend/app.py');self.app=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.app);self.real_followup_timing=self.app.followup_timing;__import__('legacy_timing').isolate_scheduler(self.app)
        # These regression tests isolate quotas, routing and templates. Pacing has dedicated clock-based tests.
        self.real_pacing=self.app.enforce_send_pacing;self.app.enforce_send_pacing=lambda *args:None
    def tearDown(self):self.app.db.close();self.env.stop();self.tmp.cleanup()
    def run_async(self,coro):return asyncio.run(coro)
    def sender(self,slot=1,user=None):
        c=FakeClient(user=user or slot+100);self.app.clients[slot]=c;return c
    def contact(self,n,kind='dm'):
        c={'id':f'{kind}:{n}','user_id':str(n),'name':f'Person {n}','role':'CTO','group':'Group','kind':kind,'username':'','group_id':str(-1000000-n)};self.app.save(c);return c['id']
    def setup_template(self):self.run_async(self.app.config(self.app.Config(template='Hello {{name}} in {{group}}')))
    def test_three_empty_slots_no_secrets(self):
        d=self.run_async(self.app.status());self.assertEqual(len(d['accounts']),3);self.assertFalse(d['authorized']);self.assertNotIn('api_hash',json.dumps(d));self.assertEqual(d['quota_timezone'],'Asia/Kolkata')
    def test_templates_preserve_config_and_survive_reload(self):
        self.run_async(self.app.config(self.app.Config(template='Old initial',sheet_url='https://docs.google.com/spreadsheets/d/test',sender_account=2,token_symbol='LF')))
        self.run_async(self.app.save_templates(self.app.Templates(template=' New @username $TOKEN ',followup_template=' Follow-up {{name}} ')))
        cfg=self.app.settings();self.assertEqual(cfg['template'],'New @username $TOKEN');self.assertEqual(cfg['followup_template'],'Follow-up {{name}}');self.assertEqual(cfg['sender_account'],2);self.assertEqual(cfg['token_symbol'],'LF');self.assertIn('spreadsheets',cfg['sheet_url'])
        self.app.db.close();self.load();self.assertEqual(self.app.settings()['followup_template'],'Follow-up {{name}}')
        self.run_async(self.app.config(self.app.Config(template='Compose edit')))
        self.assertEqual(self.app.settings()['followup_template'],'Follow-up {{name}}')
    def test_default_followup_and_blank_template_rejected(self):
        self.assertTrue(self.app.settings()['followup_template'].startswith('Hey, just following up on my previous message.'))
        with self.assertRaises(HTTPException):self.run_async(self.app.save_templates(self.app.Templates(template='   ',followup_template='Hello')))
        self.assertEqual(self.app.settings()['template'],'')
    def test_edited_template_sends_personalized_text_and_history_is_preserved(self):
        sender=self.sender();cid=self.contact(999)
        self.run_async(self.app.save_templates(self.app.Templates(template='Hi @username about $TOKEN',followup_template='Checking in {{name}}')))
        self.run_async(self.app.deliver(cid,1,token_symbol='LF'))
        self.run_async(self.app.save_templates(self.app.Templates(template='Changed',followup_template='Changed too')))
        self.assertEqual(sender.sent[0][1],'Hi Person 999 about $LF');self.assertEqual(self.app.records()[0]['message'],'Hi Person 999 about $LF')
    def test_auth_and_missing_account(self):
        with self.assertRaises(HTTPException):self.app.auth('Bearer wrong')
        self.app.auth('Bearer test-secret')
        with self.assertRaises(HTTPException):self.app.require_client(2)
    def test_separate_api_credentials(self):
        async def run():
            with patch.object(self.app,'TelegramClient',lambda *a,**k:FakeClient(authorized=False)):
                for slot in (1,2,3):await self.app.configure_telegram_api(self.app.TelegramAPI(account_id=slot,api_id=slot,api_hash=str(slot)*32))
            self.assertEqual(len(self.app.clients),3);self.assertEqual(self.app.db.execute('select count(*) from telegram_api').fetchone()[0],3)
            self.assertNotIn('api_hash',json.dumps(await self.app.status()))
        self.run_async(run())
    def test_invalid_hash_and_document(self):
        with self.assertRaises(HTTPException):self.run_async(self.app.configure_telegram_api(self.app.TelegramAPI(api_id=1,api_hash='bad')))
        with self.assertRaises(HTTPException):self.run_async(self.app.config(self.app.Config(sheet_url='https://docs.google.com/document/d/test')))
    def test_selected_sender_and_direct_compose_message(self):
        a=self.sender(1);b=self.sender(2);cid=self.contact(1)
        result=self.run_async(self.app.send(self.app.Send(id=cid,account_id=2,message='Hi {{name}}')))
        self.assertEqual(result['account_id'],2);self.assertEqual(a.sent,[]);self.assertEqual(b.sent[0][1],'Hi Person 1');self.assertEqual(self.app.records()[0]['account_id'],2)
    def test_dm_limit_and_independent_account_quota(self):
        self.sender(1);self.sender(2);self.setup_template()
        async def run():
            for n in range(15):await self.app.deliver(self.contact(n),1)
            with self.assertRaises(HTTPException) as e:await self.app.deliver(self.contact(100),1)
            self.assertEqual(e.exception.status_code,429)
            await self.app.deliver(self.contact(101),2)
            self.assertEqual(self.app.usage('101')['dm']['used'],15);self.assertEqual(self.app.usage('102')['dm']['used'],1)
        self.run_async(run())
    def test_group_limit_is_separate_from_dms(self):
        self.sender();self.setup_template()
        async def run():
            for n in range(30):await self.app.deliver(self.contact(n,'group'),1,'group')
            with self.assertRaises(HTTPException) as e:await self.app.deliver(self.contact(99,'group'),1,'group')
            self.assertEqual(e.exception.status_code,429)
            await self.app.deliver(self.contact(100),1)
            self.assertEqual(self.app.usage('101')['group']['used'],30)
        self.run_async(run())
    def test_duplicate_blocked_across_accounts_and_groups(self):
        self.sender(1);self.sender(2);self.setup_template();cid=self.contact(1)
        async def run():
            await self.app.deliver(cid,1)
            self.app.save({'id':'differentgroup:1','user_id':'1','name':'Same person','role':'Admin','group':'Another group'})
            with self.assertRaises(HTTPException) as e:await self.app.deliver('differentgroup:1',2)
            self.assertEqual(e.exception.status_code,409)
        self.run_async(run())
    def test_telegram_identity_cannot_occupy_two_slots(self):
        self.sender(1,user=123);c=self.sender(2,user=123)
        with self.assertRaises(HTTPException) as e:self.run_async(self.app.identify(2,c))
        self.assertEqual(e.exception.status_code,409)
    def test_concurrent_requests_respect_cap(self):
        c=self.sender();self.setup_template();ids=[self.contact(n) for n in range(20)]
        async def run():
            results=await asyncio.gather(*(self.app.deliver(cid,1) for cid in ids),return_exceptions=True)
            self.assertEqual(sum(isinstance(r,dict) for r in results),15);self.assertEqual(len(c.sent),15)
        self.run_async(run())
    def test_restart_retains_usage_and_relogin_cannot_reset(self):
        self.sender(user=555);self.setup_template();self.run_async(self.app.deliver(self.contact(1)));self.app.db.close();self.load();self.sender(3,user=555)
        self.run_async(self.app.identify(3,self.app.clients[3]));self.assertEqual(self.app.usage('555')['dm']['used'],1)
    def test_day_reset(self):
        self.sender();self.setup_template()
        with patch.object(self.app,'today',return_value='2026-10-22'):self.run_async(self.app.deliver(self.contact(1)))
        with patch.object(self.app,'today',return_value='2026-10-23'):self.assertEqual(self.app.usage('101')['dm']['used'],0)
    def test_uncertain_delivery_consumes_quota_and_blocks_retry(self):
        c=self.sender();c.fail=RuntimeError('network timeout');self.setup_template();cid=self.contact(1)
        with self.assertRaises(HTTPException) as e:self.run_async(self.app.deliver(cid))
        self.assertEqual(e.exception.status_code,502);self.assertEqual(self.app.usage('101')['dm']['used'],1)
        with self.assertRaises(HTTPException) as e:self.run_async(self.app.deliver(cid))
        self.assertEqual(e.exception.status_code,409)
    def test_flood_wait_pauses_account_without_sender_switch(self):
        c=self.sender();other=self.sender(2);c.fail=errors.FloodWaitError(request=None,capture=120);self.setup_template()
        with self.assertRaises(errors.FloodWaitError):self.run_async(self.app.deliver(self.contact(1)))
        with self.assertRaises(HTTPException) as e:self.run_async(self.app.deliver(self.contact(2)))
        self.assertEqual(e.exception.status_code,429);self.assertEqual(other.sent,[])
    def test_sheet_sender_uses_saved_account(self):
        a=self.sender(1);b=self.sender(3);cid=self.contact(1)
        self.run_async(self.app.config(self.app.Config(template='Hi {{name}}',sender_account=3)))
        self.run_async(self.app.sheet_send(self.app.SheetSend(id=cid)))
        self.assertEqual(len(a.sent),0);self.assertEqual(len(b.sent),1)
    def test_legacy_delivery_migrates_without_resend(self):
        self.app.db.execute('delete from meta');self.app.db.execute('insert into deliveries values(?,?,?,?)',('old:1','Sent',self.app.stamp(),''));self.app.save({'id':'old:1','user_id':'1','name':'Old','role':'Admin','group':'Old'});self.app.db.commit();self.app.db.close();self.load();self.sender();self.setup_template()
        with self.assertRaises(HTTPException) as e:self.run_async(self.app.deliver('old:1'))
        self.assertEqual(e.exception.status_code,409)

    def scan_client(self,slot=1,empty=False,scan_error=None,leave_error=None,basic=False):
        from telethon import types,functions
        app=self.app
        entity=types.Chat(77,'Test group',types.ChatPhotoEmpty(),1,None,1) if basic else types.Channel(77,'Test group',types.ChatPhotoEmpty(),None,megagroup=True)
        class Scanner(FakeClient):
            def __init__(self):super().__init__(user=100+slot);self.requests=[]
            async def get_entity(self,target):return entity
            async def get_participants(self,*args,**kwargs):
                if scan_error:raise scan_error
                return [] if empty else [SimpleNamespace(id=10,first_name='Admin',last_name='',username='admin_test',bot=False,deleted=False,participant=SimpleNamespace(rank='CTO'))]
            async def __call__(self,req):
                self.requests.append(req)
                if isinstance(req,functions.messages.GetFullChatRequest):
                    return SimpleNamespace(users=[SimpleNamespace(id=10,first_name='Admin',last_name='',username='admin_test',bot=False,deleted=False)],full_chat=SimpleNamespace(participants=SimpleNamespace(participants=[types.ChatParticipantAdmin(10,1,None)])))
                if isinstance(req,(functions.channels.LeaveChannelRequest,functions.messages.DeleteChatUserRequest)):
                    assert app.db.execute("select 1 from contacts where id='77:10'").fetchone(),'leave happened before admin data was saved'
                    if leave_error:raise leave_error
                return SimpleNamespace()
        client=Scanner();self.app.clients[slot]=client;return client
    def test_leave_only_selected_account_after_committed_scan(self):
        from telethon import functions
        other=self.sender(1);c=self.scan_client(2)
        r=self.run_async(self.app.scan(self.app.Scan(account_id=2,link='@test_group',leave_after_scan=True)))
        self.assertEqual(r['leave']['status'],'left');self.assertEqual(r['count'],1)
        self.assertTrue(any(isinstance(x,functions.channels.LeaveChannelRequest) for x in c.requests));self.assertEqual(other.sent,[])
        group=next(p for p in self.app.contacts() if p.get('kind')=='group');self.assertEqual(group['membership']['2'],'left')
        self.assertTrue(any(p['id']=='77:10' for p in self.app.contacts()))
    def test_scan_failure_does_not_leave(self):
        c=self.scan_client(scan_error=errors.ChatAdminRequiredError(request=None))
        with self.assertRaises(HTTPException):self.run_async(self.app.scan(self.app.Scan(link='@test_group',leave_after_scan=True)))
        self.assertEqual(c.requests,[])
    def test_empty_scan_does_not_leave(self):
        c=self.scan_client(empty=True);r=self.run_async(self.app.scan(self.app.Scan(link='@test_group',leave_after_scan=True)))
        self.assertEqual(r['leave']['status'],'skipped');self.assertEqual(c.requests,[])
    def test_default_scan_stays_in_group(self):
        c=self.scan_client();r=self.run_async(self.app.scan(self.app.Scan(link='@test_group')))
        self.assertEqual(r['leave']['status'],'not_requested');self.assertEqual(c.requests,[])
    def test_leave_error_preserves_scan_results(self):
        self.scan_client(leave_error=errors.ChatAdminRequiredError(request=None))
        r=self.run_async(self.app.scan(self.app.Scan(link='@test_group',leave_after_scan=True)))
        self.assertEqual(r['leave']['status'],'failed');self.assertEqual(r['count'],1)
        self.assertTrue(any(p['id']=='77:10' for p in self.app.contacts()))
    def test_basic_group_leaves_with_delete_chat_user(self):
        from telethon import functions
        c=self.scan_client(basic=True);r=self.run_async(self.app.scan(self.app.Scan(link='@test_group',leave_after_scan=True)))
        self.assertEqual(r['leave']['status'],'left');self.assertTrue(any(isinstance(x,functions.messages.DeleteChatUserRequest) for x in c.requests))
    def test_group_send_requires_rejoin_after_leaving(self):
        self.scan_client();self.run_async(self.app.scan(self.app.Scan(link='@test_group',leave_after_scan=True)))
        group=next(p for p in self.app.contacts() if p.get('kind')=='group');self.setup_template()
        with self.assertRaises(HTTPException) as e:self.run_async(self.app.deliver(group['id'],1,'group'))
        self.assertEqual(e.exception.status_code,409);self.assertIn('Rejoin',e.exception.detail)

    def test_reset_both_restores_allowance_preserves_history(self):
        self.sender();self.setup_template()
        async def run():
            await self.app.deliver(self.contact(1));await self.app.deliver(self.contact(2,'group'),1,'group')
            response=await self.app.reset_daily_limits(self.app.ResetQuota(account_id=1,scope='both',request_id='reset-both-001'))
            self.assertEqual(response['usage']['dm']['used'],0);self.assertEqual(response['usage']['group']['used'],0)
            self.assertEqual(len(self.app.records()),2);self.assertEqual(len(self.app.reset_records()),2)
            self.assertEqual(self.app.sent_in_current_quota('101'),0)
            await self.app.deliver(self.contact(3));self.assertEqual(self.app.usage('101')['dm']['used'],1)
        self.run_async(run())
    def test_reset_only_dms_preserves_group_counter_and_other_account(self):
        self.sender(1);self.sender(2);self.setup_template()
        async def run():
            await self.app.deliver(self.contact(1),1);await self.app.deliver(self.contact(2,'group'),1,'group');await self.app.deliver(self.contact(3),2)
            await self.app.reset_daily_limits(self.app.ResetQuota(account_id=1,scope='dm',request_id='reset-dm-001'))
            self.assertEqual(self.app.usage('101')['dm']['used'],0);self.assertEqual(self.app.usage('101')['group']['used'],1);self.assertEqual(self.app.usage('102')['dm']['used'],1)
        self.run_async(run())
    def test_reset_does_not_bypass_duplicate_or_telegram_pause(self):
        self.sender();self.setup_template();cid=self.contact(1)
        async def run():
            await self.app.deliver(cid)
            blocked='2099-01-01T00:00:00+00:00'
            self.app.db.execute('update account_info set blocked_until=? where slot=1',(blocked,));self.app.db.commit()
            await self.app.reset_daily_limits(self.app.ResetQuota(request_id='reset-pause-001'))
            self.assertEqual(self.app.db.execute('select blocked_until from account_info where slot=1').fetchone()[0],blocked)
            with self.assertRaises(HTTPException) as e:await self.app.deliver(cid)
            self.assertEqual(e.exception.status_code,409)
            with self.assertRaises(HTTPException) as e:await self.app.deliver(self.contact(2))
            self.assertEqual(e.exception.status_code,429)
        self.run_async(run())
    def test_reset_request_is_idempotent_after_new_sends(self):
        self.sender();self.setup_template()
        async def run():
            request=self.app.ResetQuota(scope='dm',request_id='retry-request-001')
            await self.app.deliver(self.contact(1));await self.app.reset_daily_limits(request)
            await self.app.deliver(self.contact(2));r=await self.app.reset_daily_limits(request)
            self.assertTrue(r['already_applied']);self.assertEqual(r['usage']['dm']['used'],1)
            self.assertEqual(len(self.app.reset_records()),1)
        self.run_async(run())
    def test_reset_persists_after_restart(self):
        self.sender(user=555);self.setup_template()
        self.run_async(self.app.deliver(self.contact(1)))
        self.run_async(self.app.reset_daily_limits(self.app.ResetQuota(scope='dm',request_id='persistent-reset-001')))
        self.run_async(self.app.deliver(self.contact(2)))
        self.app.db.close();self.load();self.sender(3,user=555)
        self.run_async(self.app.identify(3,self.app.clients[3]))
        self.assertEqual(self.app.usage('555')['dm']['used'],1);self.assertEqual(len(self.app.records()),2)
    def test_reset_requires_connected_account(self):
        with self.assertRaises(HTTPException) as e:self.run_async(self.app.reset_daily_limits(self.app.ResetQuota(account_id=3,request_id='offline-reset-001')))
        self.assertEqual(e.exception.status_code,409);self.assertEqual(self.app.reset_records(),[])
    def test_reset_baseline_expires_at_midnight(self):
        self.sender();self.setup_template()
        async def run():
            with patch.object(self.app,'today',return_value='2026-10-22'):
                await self.app.deliver(self.contact(1));await self.app.reset_daily_limits(self.app.ResetQuota(request_id='reset-midnight-001'));await self.app.deliver(self.contact(2))
            with patch.object(self.app,'today',return_value='2026-10-23'):
                self.assertEqual(self.app.usage('101')['dm']['used'],0);await self.app.deliver(self.contact(3));self.assertEqual(self.app.usage('101')['dm']['used'],1)
        self.run_async(run())

    def dashboard_request(self):
        from fastapi import Request
        return Request({'type':'http','client':('test-client',1234),'headers':[]})
    def test_dashboard_login_token_hash_and_logout(self):
        async def run():
            with patch.object(self.app,'DASHBOARD_USERNAME','admin'),patch.object(self.app,'DASHBOARD_PASSWORD','test-secret'):
                response=await self.app.dashboard_login(self.app.DashboardLogin(username='admin',password='test-secret'),self.dashboard_request())
            token=response['access_token'];self.assertEqual(self.app.auth('Bearer '+token),'admin')
            stored=self.app.db.execute('select token_hash from dashboard_sessions').fetchone()[0];self.assertNotEqual(stored,token)
            await self.app.dashboard_logout('Bearer '+token)
            with self.assertRaises(HTTPException):self.app.auth('Bearer '+token)
        self.run_async(run())
    def test_dashboard_bad_login_rate_limit(self):
        async def run():
            for _ in range(5):
                with self.assertRaises(HTTPException) as e:await self.app.dashboard_login(self.app.DashboardLogin(username='wrong',password='wrong'),self.dashboard_request())
                self.assertEqual(e.exception.status_code,401)
            with self.assertRaises(HTTPException) as e:await self.app.dashboard_login(self.app.DashboardLogin(username='wrong',password='wrong'),self.dashboard_request())
            self.assertEqual(e.exception.status_code,429)
        self.run_async(run())
    def test_expired_dashboard_session_rejected(self):
        self.app.db.execute('insert into dashboard_sessions values(?,?,?)',('e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855','admin','2000-01-01T00:00:00+00:00'));self.app.db.commit()
        with self.assertRaises(HTTPException):self.app.auth('Bearer ')
    def test_bot_admin_is_not_collected(self):
        c=self.scan_client()
        async def bots(*args,**kwargs):return [SimpleNamespace(id=99,first_name='Bot Admin',last_name='',username='bot_admin',bot=True,deleted=False,participant=SimpleNamespace(rank='Admin'))]
        c.get_participants=bots
        result=self.run_async(self.app.scan(self.app.Scan(link='@test_group')))
        self.assertEqual(result['count'],0);self.assertFalse(any(p.get('user_id')=='99' for p in self.app.contacts()))
    def test_known_bot_is_not_messaged_or_listed(self):
        c=self.sender();self.setup_template();cid=self.contact(1)
        saved=json.loads(self.app.db.execute('select data from contacts where id=?',(cid,)).fetchone()[0]);saved['is_bot']=True;self.app.save(saved)
        self.assertFalse(any(p['id']==cid for p in self.app.contacts()))
        with self.assertRaises(HTTPException) as e:self.run_async(self.app.deliver(cid))
        self.assertEqual(e.exception.status_code,400);self.assertEqual(c.sent,[])
    def test_sent_records_include_message_and_recipient(self):
        self.sender();self.setup_template();cid=self.contact(1);self.run_async(self.app.deliver(cid))
        record=self.app.records()[0]
        self.assertEqual(record['recipient_name'],'Person 1');self.assertEqual(record['message'],'Hello Person 1 in Group');self.assertEqual(record['sender_label'],'Sender 101')
    def test_followup_uses_original_account_and_keeps_both_records(self):
        other=self.sender(1);sender=self.sender(2);self.setup_template();cid=self.contact(1)
        async def run():
            await self.app.deliver(cid,2)
            original=self.app.records()[0]['delivery_id']
            r=await self.app.follow_up(self.app.Followup(delivery_id=original,message='Following up, {{name}}',request_id='follow-up-001'))
            self.assertEqual(r['account_id'],2);self.assertEqual(len(sender.sent),2);self.assertEqual(other.sent,[])
            records=self.app.records();self.assertEqual(len(records),2);self.assertEqual(records[0]['followup_of'],original);self.assertEqual(records[0]['message'],'Following up, Person 1')
        self.run_async(run())
    def test_followup_retry_does_not_send_twice(self):
        c=self.sender();self.setup_template()
        async def run():
            await self.app.deliver(self.contact(1));original=self.app.records()[0]['delivery_id']
            body=self.app.Followup(delivery_id=original,message='Checking in with you.',request_id='repeat-followup-001')
            await self.app.follow_up(body);r=await self.app.follow_up(body)
            self.assertTrue(r['already_sent']);self.assertEqual(len(c.sent),2);self.assertEqual(self.app.usage('101')['dm']['used'],1)
        self.run_async(run())
    def test_followup_requires_original_telegram_identity(self):
        self.sender(user=555);self.setup_template()
        async def run():
            await self.app.deliver(self.contact(1));original=self.app.records()[0]['delivery_id'];new=self.sender(user=777)
            with self.assertRaises(HTTPException) as e:await self.app.follow_up(self.app.Followup(delivery_id=original,message='Hello again.',request_id='wrong-sender-001'))
            self.assertEqual(e.exception.status_code,409);self.assertEqual(new.sent,[])
        self.run_async(run())
    def test_followup_to_existing_person_allowed_at_new_recipient_cap(self):
        self.sender();self.setup_template()
        async def run():
            for n in range(15):await self.app.deliver(self.contact(n))
            original=self.app.records()[-1]['delivery_id']
            await self.app.follow_up(self.app.Followup(delivery_id=original,message='Following up.',request_id='cap-followup-001'))
            self.assertEqual(self.app.usage('101')['dm']['used'],15)
            with self.assertRaises(HTTPException) as e:await self.app.deliver(self.contact(99))
            self.assertEqual(e.exception.status_code,429)
        self.run_async(run())
    def test_followup_rejects_unconfirmed_delivery(self):
        c=self.sender();c.fail=RuntimeError('timeout');self.setup_template()
        async def run():
            with self.assertRaises(HTTPException):await self.app.deliver(self.contact(1))
            original=self.app.records()[0]['delivery_id']
            with self.assertRaises(HTTPException) as e:await self.app.follow_up(self.app.Followup(delivery_id=original,message='Hello again.',request_id='uncertain-followup-001'))
            self.assertEqual(e.exception.status_code,409)
        self.run_async(run())

    def test_account_health_not_configured_and_disconnected(self):
        h=self.app.account_health('101',None,False,'');self.assertEqual(h['state'],'Not configured')
        c=FakeClient();c.is_connected=lambda:False
        self.assertEqual(self.app.account_health('101',c,False,'')['state'],'Disconnected')
    def test_account_health_reports_known_pause(self):
        c=self.sender();h=self.app.account_health('101',c,True,'2099-01-01T00:00:00+00:00')
        self.assertEqual(h['state'],'Paused');self.assertIsNotNone(h['blocked_until'])
    def test_account_health_counts_failures_and_latest_error(self):
        c=self.sender();c.fail=errors.ChatWriteForbiddenError(request=None);self.setup_template()
        with self.assertRaises(errors.ChatWriteForbiddenError):self.run_async(self.app.deliver(self.contact(1)))
        h=self.app.account_health('101',c,True,'')
        self.assertEqual(h['state'],'Needs review');self.assertEqual(h['failed_today'],1);self.assertTrue(h['last_error'])
    def test_health_actual_sent_count_is_not_erased_by_quota_reset(self):
        c=self.sender();self.setup_template();self.run_async(self.app.deliver(self.contact(1)))
        self.run_async(self.app.reset_daily_limits(self.app.ResetQuota(request_id='health-reset-001')))
        h=self.app.account_health('101',c,True,'')
        self.assertEqual(h['state'],'Ready');self.assertEqual(h['sent_today_total'],1);self.assertEqual(self.app.usage('101')['dm']['used'],0)
    def test_status_includes_health_for_all_accounts(self):
        self.sender();d=self.run_async(self.app.status());self.assertEqual(len(d['accounts']),3)
        self.assertTrue(all('health' in a for a in d['accounts']));self.assertTrue(d['accounts'][0]['health']['connected'])

    def test_username_and_token_personalization(self):
        contact={'name':'Jenil','username':'jenil_test','role':'Admin','group':'WMM'}
        self.assertEqual(self.app.personalize_message('Hey @username! I saw $TOKEN.',contact,'$LF'),'Hey @jenil_test! I saw $LF.')
        self.assertEqual(self.app.personalize_message('{{username}} / {{token}}',contact,'LF'),'@jenil_test / $LF')
        self.assertEqual(self.app.personalize_message('Hey @username!',{'name':'Jenil'},''),'Hey Jenil!')
        with self.assertRaises(HTTPException):self.app.personalize_message('I saw $TOKEN',contact,'')
        with self.assertRaises(HTTPException):self.app.normalize_token('invalid token with spaces')
    def test_token_is_stored_with_actual_sent_text(self):
        c=self.sender();cid=self.contact(1)
        self.run_async(self.app.send(self.app.Send(id=cid,message='Hey @username! I saw $TOKEN.',token_symbol='LF')))
        self.assertEqual(c.sent[0][1],'Hey Person 1! I saw $LF.')
        record=self.app.records()[0];self.assertEqual(record['token_symbol'],'LF');self.assertEqual(record['message'],c.sent[0][1])
    def test_followup_inherits_token_and_does_not_consume_another_dm_slot(self):
        self.sender();cid=self.contact(1)
        async def run():
            await self.app.send(self.app.Send(id=cid,message='Hello @username, $TOKEN.',token_symbol='LF'))
            first=self.app.records()[0]['delivery_id']
            await self.app.follow_up(self.app.Followup(delivery_id=first,message='Following up about $TOKEN.',request_id='token-followup-001'))
            record=self.app.records()[0];self.assertEqual(record['message'],'Following up about $LF.');self.assertEqual(record['token_symbol'],'LF');self.assertEqual(self.app.usage('101')['dm']['used'],1)
        self.run_async(run())
    def test_existing_recipient_followup_next_day_does_not_count_as_new(self):
        self.sender();self.setup_template()
        async def run():
            with patch.object(self.app,'today',return_value='2026-10-22'):
                await self.app.deliver(self.contact(1));first=self.app.records()[0]['delivery_id']
            with patch.object(self.app,'today',return_value='2026-10-23'):
                await self.app.follow_up(self.app.Followup(delivery_id=first,message='Hello again.',request_id='next-day-followup-001'))
                self.assertEqual(self.app.usage('101')['dm']['used'],0);self.assertEqual(self.app.sent_in_current_quota('101'),0)
                await self.app.deliver(self.contact(2));self.assertEqual(self.app.usage('101')['dm']['used'],1)
        self.run_async(run())
    def test_failed_retry_same_new_recipient_counts_once(self):
        c=self.sender();self.setup_template();cid=self.contact(1);c.fail=errors.ChatWriteForbiddenError(request=None)
        with self.assertRaises(errors.ChatWriteForbiddenError):self.run_async(self.app.deliver(cid))
        self.assertEqual(self.app.usage('101')['dm']['used'],1)
        c.fail=None;self.run_async(self.app.deliver(cid));self.assertEqual(self.app.usage('101')['dm']['used'],1)
    def test_settings_store_token_for_checkbox_sends(self):
        c=self.sender();cid=self.contact(1)
        self.run_async(self.app.config(self.app.Config(template='Hi @username, $TOKEN.',token_symbol='$LF')))
        self.run_async(self.app.sheet_send(self.app.SheetSend(id=cid)))
        self.assertEqual(c.sent[0][1],'Hi Person 1, $LF.')

if __name__=='__main__':unittest.main()





