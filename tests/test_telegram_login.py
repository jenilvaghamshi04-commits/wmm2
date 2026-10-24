import asyncio,importlib.util,os,tempfile,unittest
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import HTTPException
from telethon import errors
from test_gateway import FakeClient

class LoginClient(FakeClient):
    def __init__(self,user=101,two_step=True):super().__init__(user=user,authorized=False);self.two_step=two_step;self.code_accepted=False;self.steps=[];self.password_error=None;self.code_error=None;self.request_error=None;self.codes_requested=0;self._phone_code_hash={}
    async def send_code_request(self,phone):
        self.codes_requested+=1
        if self.request_error:raise self.request_error
        self.code_accepted=False;return SimpleNamespace(phone_code_hash='hash-for-'+phone)
    async def sign_in(self,phone=None,code=None,password=None,phone_code_hash=None):
        self.steps.append('password' if password is not None else 'code')
        if password is not None:
            if not self.code_accepted:raise errors.AuthKeyUnregisteredError(request=None)
            if self.password_error:raise self.password_error
            if password!='correct-password':raise errors.PasswordHashInvalidError(request=None)
            self.authorized=True;return
        if self.code_error:raise self.code_error
        if code!='12345':raise errors.PhoneCodeInvalidError(request=None)
        self.code_accepted=True
        if self.two_step:raise errors.SessionPasswordNeededError(request=None)
        self.authorized=True

class TelegramLoginTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'DATA_DIR':self.tmp.name,'DASHBOARD_KEY':'test-secret','TELEGRAM_API_ID':'','TELEGRAM_API_HASH':''});self.env.start();self.load();self.client=LoginClient();self.app.clients[1]=self.client
    def load(self):
        spec=importlib.util.spec_from_file_location('login_flow_test','backend/app.py');self.app=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.app)
    def tearDown(self):self.app.db.close();self.env.stop();self.tmp.cleanup()
    def run_async(self,coro):return asyncio.run(coro)
    def request(self,slot=1,phone='+919876543210'):return self.run_async(self.app.login(self.app.Login(account_id=slot,phone=phone)))
    def verify(self,**kwargs):return self.run_async(self.app.verify(self.app.Verify(**kwargs)))
    def test_code_then_requested_password_connects(self):
        self.request();self.assertEqual(self.app.login_progress(1)['login_step'],'code');r=self.verify(code='12345');self.assertTrue(r['password_required']);self.assertEqual(self.client.steps,['code']);self.assertEqual(self.app.login_progress(1)['login_step'],'password')
        r=self.verify(password='correct-password');self.assertTrue(r['authorized']);self.assertEqual(self.client.steps,['code','password']);self.assertEqual(self.app.login_progress(1)['login_step'],'phone')
    def test_prefilled_password_never_skips_code(self):
        self.request();self.assertTrue(self.verify(code='12345',password='correct-password')['authorized']);self.assertEqual(self.client.steps,['code','password'])
    def test_password_before_code_is_rejected_without_get_password(self):
        self.request()
        with self.assertRaises(HTTPException) as e:self.verify(password='correct-password')
        self.assertIn('login code first',e.exception.detail);self.assertEqual(self.client.steps,[])
    def test_code_only_account_ignores_unneeded_password(self):
        self.client.two_step=False;self.request();self.verify(code='12345',password='unneeded');self.assertEqual(self.client.steps,['code']);self.assertTrue(self.client.authorized)
    def test_invalid_code_cannot_open_password_step(self):
        self.request()
        with self.assertRaises(HTTPException):self.verify(code='99999',password='correct-password')
        self.assertEqual(self.client.steps,['code']);self.assertEqual(self.app.login_progress(1)['login_step'],'code')
    def test_wrong_password_preserves_validated_code_for_retry(self):
        self.request();self.verify(code='12345')
        with self.assertRaises(HTTPException) as e:self.verify(password='wrong')
        self.assertIn('two-step password is incorrect',e.exception.detail);self.assertEqual(self.app.login_progress(1)['login_step'],'password');self.assertTrue(self.verify(password='correct-password')['authorized'])
    def test_expired_code_and_session_require_fresh_code(self):
        self.request();self.client.code_error=errors.PhoneCodeExpiredError(request=None)
        with self.assertRaises(HTTPException) as e:self.verify(code='12345')
        self.assertEqual(e.exception.status_code,409);self.assertNotIn(1,self.app.login_pending)
        self.client.code_error=None;self.request();self.verify(code='12345');self.client.password_error=errors.AuthKeyUnregisteredError(request=None)
        with self.assertRaises(HTTPException) as e:self.verify(password='correct-password')
        self.assertEqual(e.exception.status_code,409);self.assertIn('new login code',e.exception.detail);self.assertNotIn(1,self.app.login_pending)
    def test_restart_and_timeout_cannot_reuse_password_only(self):
        self.request();self.verify(code='12345');self.app.login_pending.clear()
        with self.assertRaises(HTTPException):self.verify(password='correct-password')
        self.request();self.app.login_pending[1]['expires_at']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        with self.assertRaises(HTTPException):self.verify(code='12345')
        self.assertNotIn(1,self.app.login_pending)
    def test_pending_logins_are_scoped_to_account_and_phone(self):
        self.app.clients[2]=LoginClient(user=102);self.request()
        with self.assertRaises(HTTPException):self.verify(account_id=2,password='correct-password')
        with self.assertRaises(HTTPException):self.verify(phone='+441234567890',code='12345')
        self.assertEqual(self.client.steps,[]);self.assertEqual(self.app.clients[2].steps,[])
    def test_repeated_request_preserves_password_step_and_normalizes_phone(self):
        self.request();self.verify(code='12345');r=self.request(phone='+91 98765-43210');self.assertTrue(r['existing_code']);self.assertEqual(self.client.codes_requested,1);self.assertEqual(self.app.login_progress(1)['login_step'],'password');self.assertEqual(self.app.login_pending[1]['phone'],'+919876543210');self.assertEqual(self.app.login_progress(1)['login_phone_hint'],'••••3210')
    def test_valid_connected_account_does_not_request_new_code(self):
        self.client.authorized=True;self.assertTrue(self.request()['authorized']);self.assertEqual(self.client.codes_requested,0)
    def test_rejected_transport_key_is_renewed_only_in_selected_slot(self):
        self.client.request_error=errors.AuthKeyUnregisteredError(request=None);session=SimpleNamespace(auth_key='rejected',save=lambda:None,close=lambda:None);self.client.session=session;replacement=LoginClient();other=LoginClient(user=102);self.app.clients[2]=other
        with patch.object(self.app,'make_client',return_value=replacement):self.request()
        self.assertIsNone(session.auth_key);self.assertIs(self.app.clients[1],replacement);self.assertIs(self.app.clients[2],other);self.assertEqual(replacement.codes_requested,1);self.assertEqual(other.codes_requested,0)

    def test_repeated_request_preserves_code_without_resending(self):
        self.request();state=dict(self.app.login_pending[1]);r=self.request()
        self.assertTrue(r['existing_code']);self.assertEqual(self.client.codes_requested,1);self.assertEqual(self.app.login_pending[1],state)
    def test_stale_telethon_hash_is_cleared_for_fresh_login(self):
        self.client._phone_code_hash={'919876543210':'stale','441234567890':'other'}
        self.request();self.assertNotIn('919876543210',self.client._phone_code_hash);self.assertEqual(self.client._phone_code_hash['441234567890'],'other')
    def test_unavailable_delivery_is_friendly_and_pauses_requests_across_slots(self):
        self.client.request_error=errors.SendCodeUnavailableError(request=None)
        with self.assertRaises(HTTPException) as e:self.request()
        self.assertEqual(e.exception.status_code,429);self.assertEqual(e.exception.headers['Retry-After'],'900');self.assertIn('Telegram cannot deliver',e.exception.detail);self.assertNotIn(1,self.app.login_pending)
        self.app.clients[2]=LoginClient(user=102)
        with self.assertRaises(HTTPException):self.request(slot=2)
        self.assertEqual(self.app.clients[2].codes_requested,0)
        self.app.db.close();self.load();self.app.clients[1]=self.client
        with self.assertRaises(HTTPException):self.request()
        self.assertEqual(self.client.codes_requested,1)
    def test_telegram_flood_wait_is_preserved(self):
        self.client.request_error=errors.FloodWaitError(request=None,capture=120)
        with self.assertRaises(HTTPException) as e:self.request()
        self.assertEqual(e.exception.headers['Retry-After'],'120')
        self.client.request_error=None
        with self.assertRaises(HTTPException):self.request()
        self.assertEqual(self.client.codes_requested,1)
    def test_other_phone_cannot_replace_active_login(self):
        self.request()
        with self.assertRaises(HTTPException):self.request(phone='+441234567890')
        self.assertEqual(self.client.codes_requested,1);self.assertEqual(self.app.login_pending[1]['phone'],'+919876543210')

    def prepare_resend(self):
        from telethon import types
        result=SimpleNamespace(phone_code_hash='old-hash',type=types.auth.SentCodeTypeApp(length=5),next_type=types.auth.CodeTypeSms(),timeout=120)
        self.app.store_login_code(1,'+919876543210',result)
        return self.app.login_pending[1]
    def test_delivery_metadata_and_explicit_resend_use_new_hash(self):
        from telethon import types
        from unittest.mock import AsyncMock
        state=self.prepare_resend();self.assertEqual(self.app.login_progress(1)['code_delivery'],'Telegram app')
        state['code_resend_at']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        rpc=AsyncMock(return_value=SimpleNamespace(phone_code_hash='new-hash',type=types.auth.SentCodeTypeSms(length=5),next_type=None,timeout=60))
        with patch.object(LoginClient,'__call__',rpc,create=True):
            result=self.run_async(self.app.resend_login_code(self.app.ResendLogin(account_id=1)))
        self.assertEqual(result['code_delivery'],'SMS');self.assertFalse(result['code_resend_available']);self.assertEqual(self.app.login_pending[1]['hash'],'new-hash');self.assertEqual(rpc.call_args.args[0].phone_code_hash,'old-hash');self.assertEqual(self.client.codes_requested,0)
    def test_resend_cannot_skip_timer_phone_or_password_step(self):
        state=self.prepare_resend()
        for body in [self.app.ResendLogin(account_id=1),self.app.ResendLogin(account_id=1,phone='+441234567890')]:
            with self.assertRaises(HTTPException):self.run_async(self.app.resend_login_code(body))
        state['password_required']=True
        with self.assertRaises(HTTPException) as e:self.run_async(self.app.resend_login_code(self.app.ResendLogin()))
        self.assertIn('accepted',e.exception.detail);self.assertEqual(self.client.codes_requested,0)
    def test_no_next_delivery_never_implicitly_resends(self):
        self.request()
        with self.assertRaises(HTTPException) as e:self.run_async(self.app.resend_login_code(self.app.ResendLogin()))
        self.assertIn('QR',e.exception.detail);self.assertEqual(self.client.codes_requested,1)
    def test_resend_flood_pause_survives_reload_and_other_slot(self):
        from unittest.mock import AsyncMock
        state=self.prepare_resend();state['code_resend_at']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        rpc=AsyncMock(side_effect=errors.FloodWaitError(request=None,capture=120))
        with patch.object(LoginClient,'__call__',rpc,create=True):
            with self.assertRaises(HTTPException) as e:self.run_async(self.app.resend_login_code(self.app.ResendLogin()))
        self.assertEqual(e.exception.headers['Retry-After'],'120')
        self.app.db.close();self.load();self.app.clients[2]=LoginClient(user=102)
        with self.assertRaises(HTTPException):self.request(slot=2)
        self.assertEqual(self.app.clients[2].codes_requested,0)
    def test_workspace_key_exchange_and_session_survive_server_reload(self):
        result=self.run_async(self.app.resume_dashboard_session('Bearer test-secret'));token=result['access_token']
        self.assertNotEqual(token,'test-secret');self.assertEqual(self.app.auth('Bearer '+token),'admin')
        self.app.db.close();self.load();self.assertEqual(self.app.auth('Bearer '+token),'admin')
        renewed=self.run_async(self.app.resume_dashboard_session('Bearer '+token));self.assertEqual(renewed['access_token'],token)
        self.run_async(self.app.dashboard_logout('Bearer '+token))
        with self.assertRaises(HTTPException):self.app.auth('Bearer '+token)
    def test_session_endpoint_rejects_missing_expired_or_revoked_tokens(self):
        from fastapi.testclient import TestClient
        client=TestClient(self.app.app)
        self.assertEqual(client.post('/auth/session').status_code,401)
        self.assertEqual(client.post('/auth/session',headers={'Authorization':'Bearer invalid'}).status_code,401)
        result=self.run_async(self.app.resume_dashboard_session('Bearer test-secret'));token=result['access_token']
        self.app.db.execute("update dashboard_sessions set expires_at='2000-01-01T00:00:00+00:00'");self.app.db.commit()
        self.assertEqual(client.post('/auth/session',headers={'Authorization':'Bearer '+token}).status_code,401)
