import asyncio,base64,importlib.util,os,tempfile,unittest
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import patch
from telethon import errors
from fastapi.testclient import TestClient
from test_telegram_login import LoginClient

class FakeQR:
    def __init__(self,client,password=False,expired=False):
        self.client=client;self.password=password;self.expired=expired;self.scanned=asyncio.Event();self.listening=False;self.url='tg://login?token=SYNTHETIC_QA_ONLY';self.expires=datetime.now(timezone.utc)+timedelta(seconds=30)
    async def wait(self):
        self.listening=True
        if self.expired:raise asyncio.TimeoutError()
        await self.scanned.wait()
        self.client.code_accepted=True
        if self.password:raise errors.SessionPasswordNeededError(request=None)
        self.client.authorized=True;return SimpleNamespace(id=self.client.user)

class QRClient(LoginClient):
    def __init__(self,user=101,password=False,expired=False):super().__init__(user=user,two_step=password);self.qr=FakeQR(self,password,expired);self.qr_requests=0
    async def qr_login(self):self.qr_requests+=1;return self.qr

class QRLoginTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'DATA_DIR':self.tmp.name,'DASHBOARD_KEY':'test-secret','TELEGRAM_API_ID':'','TELEGRAM_API_HASH':''});self.env.start()
        spec=importlib.util.spec_from_file_location('qr_flow_test','backend/app.py');self.app=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.app);self.client=QRClient();self.app.clients[1]=self.client
    def tearDown(self):self.app.db.close();self.env.stop();self.tmp.cleanup()
    async def tick(self):
        for _ in range(4):await asyncio.sleep(0)
    def run_async(self,coro):return asyncio.run(coro)
    def test_qr_registers_listener_and_reuses_token_without_code_request(self):
        async def run():
            r=await self.app.start_qr_login(self.app.Account());self.assertTrue(self.client.qr.listening);self.assertEqual(r['status'],'waiting');self.assertEqual(self.client.codes_requested,0)
            svg=base64.b64decode(r['image'].split(',')[1]).decode();self.assertIn('<svg',svg);self.assertNotIn('http://api.qrserver',svg)
            again=await self.app.start_qr_login(self.app.Account());self.assertEqual(r['image'],again['image']);self.assertEqual(self.client.qr_requests,1)
            status=await self.app.check_qr_login(self.app.Account());self.assertNotIn('image',status);self.assertNotIn('url',status);self.app.cancel_qr_login(1);await self.tick()
        self.run_async(run())
    def test_scan_authorizes_and_identifies_correct_slot(self):
        async def run():
            other=QRClient(user=102);self.app.clients[2]=other
            await self.app.start_qr_login(self.app.Account());self.client.qr.scanned.set();await self.tick()
            self.assertEqual((await self.app.check_qr_login(self.app.Account()))['status'],'authorized');self.assertEqual(self.app.db.execute('select principal from account_info where slot=1').fetchone()[0],'101');self.assertFalse(other.authorized);self.assertEqual(other.qr_requests,0)
        self.run_async(run())
    def test_scan_requires_password_and_accepts_it_without_phone_code(self):
        async def run():
            self.client=QRClient(password=True);self.app.clients[1]=self.client
            await self.app.start_qr_login(self.app.Account());self.client.qr.scanned.set();await self.tick()
            self.assertEqual((await self.app.check_qr_login(self.app.Account()))['status'],'password');self.assertEqual(self.app.login_progress(1)['login_step'],'password')
            with self.assertRaises(Exception):await self.app.verify(self.app.Verify(password='wrong'))
            self.assertEqual(self.app.login_progress(1)['login_step'],'password')
            r=await self.app.verify(self.app.Verify(phone='+441234567890',password='correct-password'));self.assertTrue(r['authorized']);self.assertEqual(self.client.steps,['password','password']);self.assertNotIn(1,self.app.qr_logins)
        self.run_async(run())
    def test_expiry_requires_manual_new_qr(self):
        async def run():
            self.app.clients[1]=QRClient(expired=True);await self.app.start_qr_login(self.app.Account());await self.tick()
            r=await self.app.check_qr_login(self.app.Account());self.assertEqual(r['status'],'expired');self.assertNotIn('image',self.app.qr_logins[1]);self.assertEqual(self.app.clients[1].qr_requests,1)
        self.run_async(run())
    def test_cancel_stops_listener_and_scanning_cannot_finish(self):
        async def run():
            await self.app.start_qr_login(self.app.Account());task=self.app.qr_logins[1]['task'];await self.app.stop_qr_login(self.app.Account());self.client.qr.scanned.set();await self.tick()
            self.assertTrue(task.cancelled());self.assertFalse(self.client.authorized);self.assertNotIn(1,self.app.qr_logins)
        self.run_async(run())
    def test_code_request_cannot_interrupt_qr(self):
        async def run():
            await self.app.start_qr_login(self.app.Account())
            with self.assertRaises(Exception) as e:await self.app.login(self.app.Login(phone='+919876543210'))
            self.assertIn('cancel QR',e.exception.detail);self.assertEqual(self.client.codes_requested,0);self.app.cancel_qr_login(1);await self.tick()
        self.run_async(run())
    def test_duplicate_identity_is_logged_out(self):
        async def run():
            other=LoginClient(user=101);other.authorized=True;self.app.clients[2]=other
            await self.app.start_qr_login(self.app.Account());self.client.qr.scanned.set();await self.tick()
            r=await self.app.check_qr_login(self.app.Account());self.assertEqual(r['status'],'error');self.assertIn('Account 2',r['error']);self.assertFalse(self.client.authorized);self.assertTrue(other.authorized)
        self.run_async(run())
    def test_all_qr_endpoints_require_auth(self):
        client=TestClient(self.app.app)
        for path in ['/login/qr','/login/qr/status','/login/qr/cancel']:
            self.assertEqual(client.post(path,json={'account_id':1}).status_code,401)
    def test_password_session_expires_without_accepting_password(self):
        async def run():
            self.client=QRClient(password=True);self.app.clients[1]=self.client;await self.app.start_qr_login(self.app.Account());self.client.qr.scanned.set();await self.tick()
            self.app.login_pending[1]['expires_at']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat();self.assertEqual((await self.app.check_qr_login(self.app.Account()))['status'],'expired')
        self.run_async(run())
