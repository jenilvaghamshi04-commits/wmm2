import asyncio,base64,io,json,sys,unittest
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
from unittest.mock import patch,MagicMock
from fastapi import HTTPException
from pydantic import ValidationError
from telethon import types,errors
from backend import contact_import as parser
import test_gateway as gw

class FeatureCase(unittest.TestCase):
    setUp=gw.GatewayTests.setUp;tearDown=gw.GatewayTests.tearDown;load=gw.GatewayTests.load
    run_async=gw.GatewayTests.run_async;sender=gw.GatewayTests.sender;contact=gw.GatewayTests.contact
    def restore_pacing(self):self.app.enforce_send_pacing=self.real_pacing
    def clock(self):
        class Clock(datetime):
            current=datetime.now(timezone.utc)
            @classmethod
            def now(cls,tz=None):return cls.current.astimezone(tz) if tz else cls.current.replace(tzinfo=None)
        self.timer=Clock;self.app.datetime=Clock
    def advance(self,seconds):self.timer.current+=timedelta(seconds=seconds)
    def preview(self,rows,**kw):
        mapping,header=parser.default_mapping(rows)
        return self.run_async(self.app.preview_import(self.app.ImportPreview(rows=rows,mapping=mapping,has_header=header,**kw)))
    def confirm(self,batch):return self.run_async(self.app.confirm_import(self.app.ImportConfirm(batch_id=batch['batch_id'])))

class PacingTests(FeatureCase):
    def setUp(self):super().setUp();self.restore_pacing();self.clock()
    def test_second_send_waits_without_quota_or_attempt_and_other_account_stays_independent(self):
        a=self.sender();b=self.sender(2);self.run_async(self.app.deliver(self.contact(1),message='Hello'))
        with self.assertRaises(HTTPException) as caught:self.run_async(self.app.deliver(self.contact(2),message='Hello'))
        self.assertEqual(caught.exception.status_code,429);self.assertEqual(caught.exception.detail['code'],'send_cooldown');self.assertEqual(caught.exception.detail['retry_after'],120)
        self.assertEqual(len(a.sent),1);self.assertEqual(self.app.usage('101')['dm']['used'],1)
        self.run_async(self.app.deliver(self.contact(3),2,message='Hello'));self.assertEqual(len(b.sent),1)
        self.advance(120);self.run_async(self.app.deliver('dm:2',message='Hello'));self.assertEqual(len(a.sent),2)
    def test_concurrent_sends_cannot_burst(self):
        a=self.sender();ids=[self.contact(n) for n in range(5)]
        async def run():return await asyncio.gather(*(self.app.deliver(i,message='Hello') for i in ids),return_exceptions=True)
        results=self.run_async(run());self.assertEqual(sum(isinstance(r,dict) for r in results),1);self.assertEqual(len(a.sent),1)
    def test_restart_slot_move_and_daily_reset_cannot_clear_cooldown(self):
        self.sender(user=555);self.run_async(self.app.deliver(self.contact(1),message='Hello'))
        self.run_async(self.app.reset_daily_limits(self.app.ResetQuota(account_id=1,scope='both',request_id='pacing-reset-001')))
        self.app.db.close();self.load();self.restore_pacing();self.clock();self.app.clients.clear();self.sender(3,user=555)
        with self.assertRaises(HTTPException) as caught:self.run_async(self.app.deliver(self.contact(2),3,message='Hello'))
        self.assertEqual(caught.exception.detail['code'],'send_cooldown')
    def test_workspace_reset_preserves_pacing(self):
        self.sender();self.run_async(self.app.deliver(self.contact(1),message='Hello'))
        self.run_async(self.app.reset_workspace(self.app.WorkspaceReset(confirmation='RESET DATA',request_id='workspace-pace-1')))
        self.assertEqual(self.app.pacing_status('101')['retry_after'],120)
    def test_group_and_followup_share_same_account_delay(self):
        a=self.sender();cid=self.contact(1);self.run_async(self.app.deliver(cid,message='Hello'));root=self.app.records()[0]['delivery_id']
        with self.assertRaises(HTTPException):self.run_async(self.app.deliver(self.contact(2,'group'),kind='group',message='Group hello'))
        self.advance(120);self.run_async(self.app.follow_up(self.app.Followup(delivery_id=root,message='Follow-up',request_id='followup-paced-1')))
        self.assertEqual(len(a.sent),2);self.assertEqual(self.app.usage('101')['dm']['used'],1)
    def test_longer_delay_persists_and_invalid_short_delay_rejected(self):
        self.sender();self.run_async(self.app.deliver(self.contact(1),message='Hello'))
        self.run_async(self.app.update_sending_pace(self.app.SendingPace(delay_seconds=600)));self.assertEqual(self.app.pacing_status('101')['retry_after'],600)
        self.advance(120);self.assertEqual(self.app.pacing_status('101')['retry_after'],480)
        with self.assertRaises(ValidationError):self.app.SendingPace(delay_seconds=1)
    def test_telegram_pause_takes_priority_and_failed_attempt_also_spaced(self):
        a=self.sender();a.fail=errors.FloodWaitError(None,capture=900)
        with self.assertRaises(errors.FloodWaitError):self.run_async(self.app.deliver(self.contact(1),message='Hello'))
        self.advance(120)
        with self.assertRaises(HTTPException) as caught:self.run_async(self.app.deliver(self.contact(2),message='Hello'))
        self.assertIsInstance(caught.exception.detail,str);self.assertIn('paused by Telegram',caught.exception.detail)
    def test_auto_reply_sequence_waits_between_two_messages_and_sends_once(self):
        a=self.sender();cid=self.contact(1)
        self.run_async(self.app.deliver(cid,message='Hello',token_symbol='LF',exchange='okx',auto_yes=True))
        self.app.record_reply('101','1',1,SimpleNamespace(id=500,date=self.timer.current+timedelta(seconds=1),raw_text='yes',out=False))
        self.run_async(self.app.process_auto_yes());self.assertEqual(len(a.sent),1)
        self.advance(120);self.run_async(self.app.process_auto_yes());self.assertEqual(len(a.sent),2)
        self.assertEqual(self.app.auto_yes_summary('1',{'101'})['sent_parts'],1)
        self.advance(120);self.run_async(self.app.process_auto_yes());self.run_async(self.app.process_auto_yes());self.assertEqual(len(a.sent),3)
        self.assertTrue(self.app.auto_yes_summary('1',{'101'})['completed_once'])
    def test_status_exposes_pacing_without_credentials(self):
        self.sender();self.run_async(self.app.deliver(self.contact(1),message='Hello'))
        status=self.run_async(self.app.status());self.assertTrue(status['features']['send_pacing']);self.assertEqual(status['accounts'][0]['pacing']['retry_after'],120)

class ImportTests(FeatureCase):
    def test_preview_then_confirm_dedupes_and_never_connects_or_sends(self):
        self.app.save({'id':'existing','user_id':'1','username':'existing_user','name':'Existing','role':'CTO','group':'Test'})
        batch=self.preview([['Name','Telegram','Role','Group'],['Alice','https://t.me/alice_user','BD','Project A'],['Again','@ALICE_USER','',''],['Exists','@existing_user','',''],['Bot','@spam_bot','',''],['Private','https://t.me/+invite','',''],['Invalid','https://example.com','','']])
        self.assertEqual((batch['ready'],batch['duplicates'],batch['skipped']),(1,2,3));self.assertEqual(len(self.app.contacts()),1)
        result=self.confirm(batch);self.assertEqual(result['added'],1)
        contact=next(c for c in self.app.contacts() if c.get('username')=='alice_user');self.assertTrue(contact['import_unresolved']);self.assertEqual(contact['role'],'BD');self.assertEqual(contact['group'],'Project A')
        self.assertEqual(self.app.records(),[]);self.assertEqual(self.app.clients,{})
        self.assertTrue(self.run_async(self.app.status())['features']['contact_import'])
        with self.assertRaises(HTTPException):self.confirm(batch)
    def test_headerless_single_column_and_custom_mapping(self):
        batch=self.preview([['@alice_user'],['t.me/bravo_user']]);self.assertEqual(batch['ready'],2)
        custom=self.run_async(self.app.preview_import(self.app.ImportPreview(rows=[['Project','Contact'],['A','@charlie_user']],mapping={'telegram':1,'group':0},has_header=True)))
        self.confirm(custom);self.assertEqual(self.app.contacts()[0]['group'],'A')
    def test_concurrent_preview_import_rechecks_duplicates(self):
        one=self.preview([['Username'],['@alice_user']]);two=self.preview([['Username'],['@alice_user']]);self.confirm(one)
        result=self.confirm(two);self.assertEqual((result['added'],result['duplicates']),(0,1));self.assertEqual(len(self.app.contacts()),1)
    def test_expired_preview_cannot_import(self):
        batch=self.preview([['@alice_user']]);self.app.db.execute("update import_batches set expires_at='2000-01-01'");self.app.db.commit()
        with self.assertRaises(HTTPException):self.confirm(batch)
    def test_group_rows_and_imported_user_type_are_explicit(self):
        batch=self.preview([['Telegram','Type'],['@project_group','group'],['@alice_user','dm'],['@wrong_type','channel']]);self.assertEqual(batch['ready'],2);self.assertEqual(batch['skipped'],1);self.confirm(batch)
        group=next(c for c in self.app.contacts() if c['kind']=='group');self.assertTrue(group['group_id'].startswith('import:group:'))
    def imported(self,handle='alice_user',kind='dm'):
        self.confirm(self.preview([['@'+handle]],default_kind=kind));return next(c['id'] for c in self.app.contacts() if c['username']==handle)
    def test_import_resolves_to_real_telegram_id_then_dedupes_against_scan_history(self):
        a=self.sender();self.run_async(self.app.deliver(self.contact(88),message='Already contacted'))
        cid=self.imported();a.get_entity=MagicMock(side_effect=lambda username:asyncio.sleep(0,result=types.User(id=88,first_name='Alice',username='alice_user')))
        with self.assertRaises(HTTPException) as caught:self.run_async(self.app.deliver(cid,message='Hello'))
        self.assertEqual(caught.exception.status_code,409);self.assertEqual(len(a.sent),1);self.assertEqual(len(self.app.records()),1)
    def test_valid_imported_person_sends_to_resolved_id_on_review_only(self):
        cid=self.imported();a=self.sender();a.get_entity=lambda username:asyncio.sleep(0,result=types.User(id=88,first_name='Alice',username='alice_user'))
        self.run_async(self.app.deliver(cid,message='Hi @username'))
        self.assertEqual(self.app.records()[0]['target'],'88');self.assertFalse(self.app.contacts()[0]['import_unresolved']);self.assertEqual(a.sent[0][1],'Hi @alice_user')
    def test_channel_bot_and_changed_username_rejected_before_send(self):
        for peer in [types.User(id=88,bot=True),types.Channel(id=88,title='Channel',photo=types.ChatPhotoEmpty(),date=None)]:
            cid=self.imported('test_user_'+str(peer.id)+('_botcase' if getattr(peer,'bot',False) else '_channel'))
            a=self.sender();a.get_entity=lambda username:asyncio.sleep(0,result=peer)
            with self.assertRaises(HTTPException):self.run_async(self.app.deliver(cid,message='Hello'))
            self.assertEqual(a.sent,[])
    def test_resolution_flood_wait_is_saved_before_any_send(self):
        cid=self.imported();a=self.sender()
        async def resolve(name):raise errors.FloodWaitError(None,capture=500)
        a.get_entity=resolve
        with self.assertRaises(errors.FloodWaitError):self.run_async(self.app.deliver(cid,message='Hello'))
        self.assertGreater(self.app.db.execute('select blocked_until from account_info where slot=1').fetchone()[0],self.app.stamp());self.assertEqual(a.sent,[]);self.assertEqual(self.app.records(),[])
    def test_google_read_uses_read_only_bounded_range_and_key(self):
        book=MagicMock();ws=book.get_worksheet.return_value;ws.get.return_value=[['Telegram'],['@alice_user']]
        client=MagicMock();client.open_by_key.return_value=book
        with patch.dict('os.environ',{'GOOGLE_SERVICE_ACCOUNT_JSON':'{}'}),patch('gspread.service_account_from_dict',return_value=client):
            result=self.run_async(self.app.read_import(self.app.ImportRead(sheet_url='https://docs.google.com/spreadsheets/d/test_id/edit#gid=0')))
        client.open_by_key.assert_called_once_with('test_id');ws.get.assert_called_once_with('A1:AE1003');self.assertEqual(result['mapping']['telegram'],0);ws.update.assert_not_called()
    def test_api_auth_required_preview_confirm_and_pace(self):
        import httpx
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app.app),base_url='http://test') as c:
                for path in ['/contacts/import/read','/contacts/import/preview','/contacts/import/confirm','/sending-pace']:
                    r=await c.post(path,json={});self.assertEqual(r.status_code,401)
                r=await c.post('/contacts/import/read',headers={'Authorization':'Bearer test-secret'},json={'filename':'leads.csv','content_base64':base64.b64encode(b'Username\n@alice_user\n').decode()});self.assertEqual(r.status_code,200)
                d=r.json();p=await c.post('/contacts/import/preview',headers={'Authorization':'Bearer test-secret'},json={'rows':d['rows'],'mapping':d['mapping'],'has_header':d['has_header']});self.assertEqual(p.status_code,200)
                final=await c.post('/contacts/import/confirm',headers={'Authorization':'Bearer test-secret'},json={'batch_id':p.json()['batch_id']});self.assertEqual(final.json()['added'],1)
        self.run_async(run())

class ParserTests(unittest.TestCase):
    def test_csv_utf8_bom_semicolon_quotes_and_tsv(self):
        content='\ufeffName;Telegram\r\n"Alice, B";@alice_user\r\n'
        rows=parser.read_file('test.csv',base64.b64encode(content.encode()).decode());self.assertEqual(rows[1],['Alice, B','@alice_user'])
        self.assertEqual(parser.read_file('test.tsv',base64.b64encode(b'Name\tTelegram\nAlice\t@alice_user').decode())[0],['Name','Telegram'])
    def test_xlsx_reads_active_tab_and_ignores_formula_cells(self):
        from openpyxl import Workbook
        b=Workbook();s=b.active;s.append(['Name','Telegram']);s.append(['Alice','@alice_user']);s.append(['Formula','=HYPERLINK("https://t.me/unsafe","Click")']);data=io.BytesIO();b.save(data);b.close()
        rows=parser.read_file('file.xlsx',base64.b64encode(data.getvalue()).decode());self.assertEqual(rows[1],['Alice','@alice_user']);self.assertEqual(rows[2][1],'')
    def test_empty_wrong_format_bad_encoding_and_oversized_rejected(self):
        for name,data in [('test.xls',b'fake'),('empty.csv',b''),('bad.csv',b'\xff'),('test.xlsx',b'not-zip'),('huge.csv',b'a'*(parser.MAX_BYTES+1))]:
            with self.assertRaises(ValueError):parser.read_file(name,base64.b64encode(data).decode())
        with self.assertRaises(ValueError):parser.read_file('bad.csv','!bad!')
        with self.assertRaises(ValueError):parser.bounded_matrix([['@alice_user']]*1002)
        with self.assertRaises(ValueError):parser.bounded_matrix([['x']*31])
    def test_sheet_urls_reject_non_google_and_private_destinations(self):
        for url in ['http://docs.google.com/spreadsheets/d/abc','https://evil.test/spreadsheets/d/abc','https://docs.google.com.evil.test/spreadsheets/d/abc','https://localhost','https://docs.google.com/document/d/abc','https://user:secret@docs.google.com/spreadsheets/d/abc']:
            with self.assertRaises(ValueError):parser.sheet_identifier(url)
    def test_telegram_links_are_strict_and_case_insensitive(self):
        for value in ['@Alice_User','https://t.me/Alice_User/','t.me/alice_user',"'@alice_user"]:self.assertEqual(parser.telegram_handle(value),'alice_user')
        for value in ['https://t.me/+invite','https://t.me/alice_user/123','tg://resolve?domain=alice_user','https://t.me/alice_user?start=1','https://evil.test/@alice_user','@helper_bot']:
            with self.assertRaises(ValueError):parser.telegram_handle(value)

if __name__=='__main__':unittest.main()
