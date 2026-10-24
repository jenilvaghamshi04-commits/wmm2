import importlib.util,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient

class StandaloneTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'DATA_DIR':self.tmp.name,'DASHBOARD_KEY':'standalone-test-secret','DASHBOARD_USERNAME':'admin','DASHBOARD_PASSWORD':'standalone-test-secret','TELEGRAM_API_ID':'','TELEGRAM_API_HASH':''});self.env.start()
        spec=importlib.util.spec_from_file_location('standalone_test_app','backend/app.py');self.module=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.module);self.client=TestClient(self.module.app)
    def tearDown(self):self.client.close();self.module.db.close();self.env.stop();self.tmp.cleanup()
    def test_conversation_pages_and_same_origin_login(self):
        page=self.client.get('/');self.assertEqual(page.status_code,200)
        import re
        self.assertEqual(re.findall(r'data-view="([^"]+)"',page.text),['groups','sent','replies','templates','connections'])
        self.assertNotIn('id="loginGateway"',page.text);self.assertNotIn('qa-only',page.text);self.assertNotIn('id="saved"',page.text)
    def test_auth_templates_and_pacing_persist(self):
        self.assertEqual(self.client.get('/status').status_code,401)
        result=self.client.post('/auth/login',json={'username':'admin','password':'standalone-test-secret'});self.assertEqual(result.status_code,200)
        token=result.json()['access_token'];headers={'Authorization':'Bearer '+token}
        pools={name:[name+' option '+str(i) for i in range(5)] for name in ['template','followup_template','yes_pitch_template','yes_demo_template']}
        body={'template_variants':pools,**{k:v[0] for k,v in pools.items()},'auto_yes_enabled':False,'auto_followup_enabled':False}
        self.assertEqual(self.client.post('/templates',json=body,headers=headers).status_code,200)
        self.assertEqual(self.client.post('/sending-pace',json={'delay_seconds':300},headers=headers).status_code,200)
        data=self.client.get('/status',headers=headers).json();self.assertEqual(data['settings']['send_delay_seconds'],300);self.assertEqual(data['settings']['template_variants'],pools);self.assertEqual(data['account_slots'],1);self.assertEqual(data['contacts'],[])
        renewed=self.client.post('/auth/session',json={},headers=headers);self.assertEqual(renewed.status_code,200)
        self.assertEqual(self.client.post('/auth/logout',json={},headers=headers).status_code,200);self.assertEqual(self.client.get('/status',headers=headers).status_code,401)
    def test_empty_or_placeholder_key_fails_closed(self):
        with patch.dict(os.environ,{'DASHBOARD_KEY':'REPLACE_WITH_A_RANDOM_SECRET'}):
            spec=importlib.util.spec_from_file_location('bad_standalone_config','backend/app.py');module=importlib.util.module_from_spec(spec)
            with self.assertRaises(RuntimeError):spec.loader.exec_module(module)
