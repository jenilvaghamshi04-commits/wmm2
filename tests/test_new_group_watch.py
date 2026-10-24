import json,unittest
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import HTTPException
from fastapi.testclient import TestClient
from telethon import types,errors,utils
import test_gateway as gw

class NewGroupWatchTests(unittest.TestCase):
    setUp=gw.GatewayTests.setUp;tearDown=gw.GatewayTests.tearDown;load=gw.GatewayTests.load
    run_async=gw.GatewayTests.run_async;scan_client=gw.GatewayTests.scan_client
    def setup_watch(self,slot=1):
        c=self.scan_client(slot);c.groups=[self.channel(77)];c.list_calls=[]
        async def dialogs(**kwargs):
            c.list_calls.append(kwargs)
            for entity in c.groups:yield SimpleNamespace(entity=entity)
        async def entity(target):return next(g for g in c.groups if str(utils.get_peer_id(g))==str(target))
        c.iter_dialogs=dialogs;c.get_entity=entity
        principal=self.run_async(self.app.identify(slot,c));return c,principal
    def channel(self,n):return types.Channel(n,'Group '+str(n),types.ChatPhotoEmpty(),None,megagroup=True,username='group_'+str(n))
    def due(self,principal,scan=False):
        state=self.app.watch_state(principal);state['next_poll_at']=''
        if scan:state['next_scan_at']=''
        with self.app.db:self.app.save_watch(principal,state)
    def test_initial_inventory_excludes_all_previous_groups_without_admin_reads(self):
        c,p=self.setup_watch();self.assertTrue(self.app.watch_state(p)['ready']);self.assertEqual(self.app.group_admin_records(),[])
        self.assertEqual(c.list_calls,[{'limit':None}]);self.assertEqual(c.sent,[])
        self.due(p);self.run_async(self.app.poll_new_groups(1));self.assertEqual(self.app.db.execute('select count(*) from tg_group_watch_jobs').fetchone()[0],0)
    def test_new_group_collects_visible_admins_titles_once_without_messages_or_join(self):
        c,p=self.setup_watch();c.groups.append(self.channel(78));self.due(p)
        self.run_async(self.app.poll_new_groups(1));self.run_async(self.app.process_new_group_admins(1,p))
        records=self.app.group_admin_records();self.assertEqual(len(records),1);self.assertEqual(records[0]['name'],'Group 78');self.assertEqual(records[0]['collection_source'],'automatic_join');self.assertEqual(records[0]['admins'][0]['title'],'CTO')
        self.assertEqual(c.sent,[]);self.assertFalse(any(type(req).__name__ in ('JoinChannelRequest','LeaveChannelRequest') for req in c.requests))
        self.due(p,True);self.run_async(self.app.poll_new_groups(1));self.run_async(self.app.process_new_group_admins(1,p));self.assertEqual(len(self.app.group_admin_records()),1)
    def test_restart_keeps_baseline_and_pending_new_groups(self):
        c,p=self.setup_watch();c.groups.append(self.channel(78));self.due(p);self.run_async(self.app.poll_new_groups(1))
        self.app.db.close();self.load();self.app.clients[1]=c;self.run_async(self.app.process_new_group_admins(1,p));self.assertEqual(len(self.app.group_admin_records()),1);self.assertEqual(len(c.list_calls),2)
    def test_partial_inventory_failure_does_not_add_or_forget_groups(self):
        c,p=self.setup_watch();original=self.app.watch_state(p)['seen']
        async def broken(**kwargs):
            yield SimpleNamespace(entity=self.channel(78))
            raise ConnectionError('interrupted page')
        c.iter_dialogs=broken;self.due(p);self.run_async(self.app.poll_new_groups(1));self.assertEqual(self.app.watch_state(p)['seen'],original);self.assertEqual(self.app.group_watch_status(p,True)['pending'],0)
    def test_baseline_failure_is_closed_and_only_later_joins_are_collected(self):
        c=self.scan_client()
        async def broken(**kwargs):
            yield SimpleNamespace(entity=self.channel(77))
            raise ConnectionError()
        c.iter_dialogs=broken;p=self.run_async(self.app.identify(1,c));self.assertFalse(self.app.watch_state(p)['ready'])
        async def complete(**kwargs):
            for n in (77,78):yield SimpleNamespace(entity=self.channel(n))
        c.iter_dialogs=complete;self.due(p);self.run_async(self.app.poll_new_groups(1));self.assertTrue(self.app.watch_state(p)['ready']);self.assertEqual(self.app.group_watch_status(p,True)['pending'],0)
    def test_scans_are_spaced_and_pause_is_respected(self):
        c,p=self.setup_watch();c.groups.extend([self.channel(78),self.channel(79)]);self.due(p);self.run_async(self.app.poll_new_groups(1))
        self.run_async(self.app.process_new_group_admins(1,p));self.run_async(self.app.process_new_group_admins(1,p));self.assertEqual(len(self.app.group_admin_records()),1)
        self.due(p,True);self.app.db.execute("update account_info set blocked_until='2099-01-01T00:00:00+00:00'");self.app.db.commit()
        with self.assertRaises(HTTPException):self.run_async(self.app.process_new_group_admins(1,p))
        self.assertEqual(len(self.app.group_admin_records()),1)
    def test_hidden_admins_are_not_retried_and_other_saved_data_is_retained(self):
        c,p=self.setup_watch();c.groups.append(self.channel(78));self.due(p);self.run_async(self.app.poll_new_groups(1))
        self.app.save({'id':'keep','name':'Existing lead','user_id':'999'})
        async def hidden(*a,**k):raise errors.ChatAdminRequiredError(request=None)
        c.get_participants=hidden;self.run_async(self.app.process_new_group_admins(1,p));self.assertEqual(self.app.group_watch_status(p,True)['unavailable'],1);self.assertTrue(any(x['id']=='keep' for x in self.app.contacts()))
    def test_baseline_is_per_identity_not_slot_and_rejoining_old_group_is_ignored(self):
        c,p=self.setup_watch();c.groups=[];self.due(p);self.run_async(self.app.poll_new_groups(1));c.groups=[self.channel(77)];self.due(p);self.run_async(self.app.poll_new_groups(1));self.assertEqual(self.app.group_watch_status(p,True)['pending'],0)
        c.user=999;p2=self.run_async(self.app.identify(1,c));self.assertNotEqual(p,p2);self.assertEqual(self.app.watch_state(p2)['seen'],self.app.watch_state(p)['seen']);self.assertEqual(self.app.group_watch_status(p2,True)['pending'],0)
    def test_changed_sender_cannot_collect_original_accounts_job(self):
        c,p=self.setup_watch();c.groups.append(self.channel(78));self.due(p);self.run_async(self.app.poll_new_groups(1));c.user=999
        self.run_async(self.app.process_new_group_admins(1,p));self.assertEqual(self.app.group_admin_records(),[])
    def test_template_catalog_requires_auth_and_returns_actual_saved_options_and_rotation(self):
        client=TestClient(self.app.app);self.assertEqual(client.get('/templates').status_code,401)
        self.run_async(self.app.save_templates(self.app.Templates(template='Saved first',followup_template='Saved follow-up')))
        self.app.choose_template('template');data=client.get('/templates',headers={'Authorization':'Bearer test-secret'}).json()
        self.assertEqual(data['template_variants']['template'],['Saved first','','','','']);self.assertEqual(data['template_rotation']['template']['last'],'Saved first');self.assertNotIn('api_hash',json.dumps(data))
