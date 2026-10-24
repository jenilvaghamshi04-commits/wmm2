import asyncio,json,unittest
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import HTTPException
from fastapi.testclient import TestClient
from telethon import types,functions,errors
import test_gateway as gw

class GroupAdminsTests(unittest.TestCase):
    setUp=gw.GatewayTests.setUp;tearDown=gw.GatewayTests.tearDown;load=gw.GatewayTests.load;run_async=gw.GatewayTests.run_async;scan_client=gw.GatewayTests.scan_client
    def test_snapshot_has_requested_fields_and_separate_role_and_title(self):
        c=self.scan_client();r=self.run_async(self.app.scan(self.app.Scan(link='@test_group')))
        group=r['group_record'];self.assertEqual(group['name'],'Test group');self.assertEqual(group['group_id'],'-1000000000077')
        self.assertEqual(group['admins'][0]['role'],'Admin');self.assertEqual(group['admins'][0]['title'],'CTO');self.assertEqual(group['admins'][0]['user_id'],'10');self.assertEqual(group['admins'][0]['username'],'admin_test');self.assertEqual(group['admins'][0]['scraped_at'],group['scraped_at'])
        self.assertEqual(self.app.contacts()[0].get('kind'),'group');self.assertEqual(c.sent,[])
        self.app.db.close();self.load();self.assertEqual(self.app.group_admin_records(),[group])
    def test_owner_missing_username_bots_deleted_and_full_admin_list(self):
        c=self.scan_client();entity=types.Channel(77,'Public channel',types.ChatPhotoEmpty(),None,broadcast=True,username='project_news')
        async def get_entity(_):return entity
        async def admins(*args,**kwargs):
            self.assertEqual(kwargs['filter'],types.ChannelParticipantsAdmins)
            return [SimpleNamespace(id=i,first_name='First',last_name='Last',username=None,bot=i==2,deleted=i==3,participant=types.ChannelParticipantCreator(i,types.ChatAdminRights(),rank='CEO') if i==1 else SimpleNamespace(rank='')) for i in range(1,154)]
        c.get_entity=get_entity;c.get_participants=admins
        result=self.run_async(self.app.scan(self.app.Scan(link='@project_news')));g=result['group_record']
        self.assertEqual(len(g['admins']),151);self.assertEqual(g['username'],'project_news');self.assertEqual(g['kind'],'channel');self.assertEqual(g['admins'][0]['role'],'Owner');self.assertEqual(g['admins'][0]['title'],'CEO');self.assertEqual(g['admins'][0]['name'],'First Last');self.assertEqual(g['admins'][0]['username'],'')
        self.assertNotIn('group',[(p.get('kind')) for p in self.app.contacts()])
    def test_joined_reader_checks_membership_and_never_joins_leaves_or_sends(self):
        c=self.scan_client();r=self.run_async(self.app.read_group_admins(self.app.GroupAdminRead(group_id='-1000000000077')))
        self.assertEqual(r['count'],1);self.assertTrue(any(isinstance(req,functions.channels.GetParticipantRequest) for req in c.requests))
        self.assertFalse(any(isinstance(req,(functions.channels.JoinChannelRequest,functions.channels.LeaveChannelRequest,functions.messages.ImportChatInviteRequest)) for req in c.requests));self.assertEqual(c.sent,[])
        self.assertEqual(next(p for p in self.app.contacts() if p.get('kind')=='group')['membership']['1'],'member')
    def test_hidden_admins_and_nonmembers_preserve_saved_snapshot(self):
        c=self.scan_client();self.run_async(self.app.scan(self.app.Scan(link='@test_group')));before=self.app.group_admin_records()
        async def denied(*a,**k):raise errors.ChatAdminRequiredError(request=None)
        c.get_participants=denied
        with self.assertRaises(HTTPException) as caught:self.run_async(self.app.read_group_admins(self.app.GroupAdminRead(group_id='-1000000000077')))
        self.assertEqual(caught.exception.status_code,403);self.assertEqual(self.app.group_admin_records(),before)
        async def no_member(self,req):raise errors.UserNotParticipantError(request=None)
        c.__class__.__call__=no_member
        with self.assertRaises(HTTPException) as caught:self.run_async(self.app.read_group_admins(self.app.GroupAdminRead(group_id='-1000000000077')))
        self.assertEqual(caught.exception.status_code,409);self.assertEqual(self.app.group_admin_records(),before)
    def test_scan_updates_snapshot_without_erasing_other_saved_contacts(self):
        c=self.scan_client();self.app.save({'id':'keep','name':'Saved lead','user_id':'700','role':'Admin'})
        for _ in range(2):self.run_async(self.app.scan(self.app.Scan(link='@test_group')))
        self.assertEqual(len(self.app.group_admin_records()),1);self.assertTrue(any(p['id']=='keep' for p in self.app.contacts()))
    def test_basic_group_and_empty_list_are_saved(self):
        self.scan_client(basic=True);self.run_async(self.app.read_group_admins(self.app.GroupAdminRead(group_id='-77')));self.assertEqual(self.app.group_admin_records()[0]['kind'],'group')
        c=self.scan_client(empty=True);self.run_async(self.app.scan(self.app.Scan(link='@test_group')));self.assertEqual(self.app.group_admin_records()[0]['admins'],[])
    def test_legacy_scans_are_visible_without_telegram_calls(self):
        self.app.save({'id':'77:10','user_id':'10','name':'Admin','group':'Legacy group','group_id':'-77','scan_account':2,'role':'CTO','title':'CTO','scanned_at':'2026-10-22T10:00:00+00:00'})
        g=self.app.group_admin_records()[0];self.assertTrue(g['legacy']);self.assertEqual(g['admins'][0]['role'],'Admin');self.assertEqual(g['admins'][0]['title'],'CTO')
    def test_joined_list_is_scoped_cached_and_excludes_users_and_left_chats(self):
        c=self.scan_client();calls=[]
        async def dialogs(**kwargs):
            calls.append(kwargs)
            for entity in [types.User(10),types.Channel(77,'Joined',types.ChatPhotoEmpty(),None,megagroup=True,username='joined'),types.Channel(78,'Left',types.ChatPhotoEmpty(),None,left=True),types.Chat(79,'Basic',types.ChatPhotoEmpty(),1,None,1)]:yield SimpleNamespace(entity=entity)
        c.iter_dialogs=dialogs
        result=self.run_async(self.app.joined_groups(self.app.Account(account_id=1)));self.assertEqual(len(result['groups']),2);self.assertFalse(result['cached'])
        self.assertEqual(self.run_async(self.app.joined_groups(self.app.Account(account_id=1)))['groups'],result['groups']);self.assertEqual(len(calls),2);self.assertEqual(calls[0],{'limit':None});self.assertEqual(calls[1],{'limit':1001})
        self.assertNotIn('access_hash',json.dumps(result));self.assertEqual(c.sent,[])
    def test_pause_stops_scans_and_listing_and_floodwait_is_persisted(self):
        c=self.scan_client(scan_error=errors.FloodWaitError(request=None,capture=120))
        with self.assertRaises(HTTPException) as caught:self.run_async(self.app.scan(self.app.Scan(link='@test_group')))
        self.assertEqual(caught.exception.status_code,429);self.assertTrue(self.app.db.execute('select blocked_until from account_info').fetchone()[0])
        with self.assertRaises(HTTPException) as caught:self.run_async(self.app.joined_groups(self.app.Account()))
        self.assertEqual(caught.exception.status_code,429)
        with self.assertRaises(HTTPException):self.run_async(self.app.read_group_admins(self.app.GroupAdminRead(group_id='-1000000000077')))
        self.assertEqual(self.app.group_admin_records(),[])
    def test_account_setup_starts_one_and_grows_without_clearing_existing_connections(self):
        self.assertEqual(self.app.account_slot_count(),1)
        self.assertEqual(self.run_async(self.app.add_account_slot())['account_id'],2);self.app.db.close();self.load();self.assertEqual(self.app.account_slot_count(),2)
        self.assertEqual(self.run_async(self.app.add_account_slot())['account_id'],3)
        with self.assertRaises(HTTPException):self.run_async(self.app.add_account_slot())
        self.app.db.execute("delete from meta where key='account_slots'");self.app.db.execute("insert into telegram_api values(3,123,'private-hash')");self.app.db.commit();self.assertEqual(self.app.account_slot_count(),3)
    def test_new_endpoints_require_authentication(self):
        client=TestClient(self.app.app)
        for method,path in [('get','/groups/admins'),('post','/groups/admins'),('post','/groups/joined'),('post','/accounts/add')]:self.assertEqual(getattr(client,method)(path).status_code,401)
    def test_invalid_group_ids_rejected(self):
        with self.assertRaises(HTTPException):self.run_async(self.app.read_group_admins(self.app.GroupAdminRead(group_id='https://t.me/other')))
