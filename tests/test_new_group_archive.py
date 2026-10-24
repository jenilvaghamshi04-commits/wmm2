import unittest
from unittest.mock import patch
from fastapi import HTTPException
from fastapi.testclient import TestClient
from telethon import errors,utils
import test_new_group_watch as nw

class NewGroupArchiveTests(unittest.TestCase):
    setUp=nw.NewGroupWatchTests.setUp;tearDown=nw.NewGroupWatchTests.tearDown;load=nw.NewGroupWatchTests.load
    run_async=nw.NewGroupWatchTests.run_async;scan_client=nw.NewGroupWatchTests.scan_client
    channel=nw.NewGroupWatchTests.channel;setup_watch=nw.NewGroupWatchTests.setup_watch;due=nw.NewGroupWatchTests.due
    def prepare(self):
        c,p=self.setup_watch();c.groups.append(self.channel(78));self.due(p);c.archived=[]
        async def archive(entity,folder):
            self.assertTrue(self.app.db.execute('select data from tg_group_admins where key=?',(str(utils.get_peer_id(entity))+':'+p,)).fetchone())
            c.archived.append((str(utils.get_peer_id(entity)),folder))
        c.edit_folder=archive
        return c,p,str(utils.get_peer_id(self.channel(78)))
    def body(self,p,gid):return self.app.NewGroupRead(group_id=gid,watch_principal=p)
    def test_picker_lists_only_new_unsaved_joined_groups_and_never_reads_admins(self):
        c,p,gid=self.prepare();r=self.run_async(self.app.available_new_groups(self.app.Account()))
        self.assertEqual([g['group_id'] for g in r['groups']],[gid]);self.assertEqual(r['groups'][0]['name'],'Group 78');self.assertEqual(r['watch_principal'],p);self.assertEqual(self.app.group_admin_records(),[]);self.assertEqual(c.archived,[])
        self.run_async(self.app.collect_selected_new_group(self.body(p,gid)));self.assertEqual(self.run_async(self.app.available_new_groups(self.app.Account()))['groups'],[])
    def test_selected_group_is_committed_before_archiving_and_repeat_does_not_rescan(self):
        c,p,gid=self.prepare();self.run_async(self.app.available_new_groups(self.app.Account()));r=self.run_async(self.app.collect_selected_new_group(self.body(p,gid)))
        self.assertEqual(r['count'],1);self.assertEqual(r['archive']['status'],'Archived');self.assertEqual(c.archived,[(gid,1)]);self.assertEqual(c.sent,[])
        again=self.run_async(self.app.collect_selected_new_group(self.body(p,gid)));self.assertTrue(again['already_saved']);self.assertEqual(c.archived,[(gid,1)]);self.assertEqual(self.app.group_admin_records()[0]['archive']['status'],'Archived')
    def test_old_group_and_wrong_identity_cannot_be_collected_or_archived(self):
        c,p,gid=self.prepare();self.run_async(self.app.available_new_groups(self.app.Account()))
        for body in [self.body(p,str(utils.get_peer_id(self.channel(77)))),self.body('999',gid)]:
            with self.assertRaises(HTTPException):self.run_async(self.app.collect_selected_new_group(body))
        self.assertEqual(c.archived,[]);self.assertEqual(self.app.group_admin_records(),[])
    def test_failed_or_empty_admin_read_never_archives(self):
        c,p,gid=self.prepare();self.run_async(self.app.available_new_groups(self.app.Account()))
        async def hidden(*a,**k):raise errors.ChatAdminRequiredError(request=None)
        c.get_participants=hidden
        with self.assertRaises(HTTPException):self.run_async(self.app.collect_selected_new_group(self.body(p,gid)))
        self.assertEqual(c.archived,[]);self.assertEqual(self.app.db.execute('select count(*) from tg_group_archives').fetchone()[0],0)
        async def empty(*a,**k):return []
        c.get_participants=empty;self.due(p,True);r=self.run_async(self.app.collect_selected_new_group(self.body(p,gid)));self.assertEqual(r['archive']['status'],'Skipped');self.assertEqual(c.archived,[])
    def test_archive_failure_keeps_saved_data_and_retries_after_restart(self):
        c,p,gid=self.prepare();self.run_async(self.app.available_new_groups(self.app.Account()));real=c.edit_folder
        async def fail(*a):raise ConnectionError()
        c.edit_folder=fail;r=self.run_async(self.app.collect_selected_new_group(self.body(p,gid)));self.assertEqual(r['archive']['status'],'Pending');self.assertEqual(len(self.app.group_admin_records()),1)
        self.app.db.close();self.load();self.app.clients[1]=c;c.edit_folder=real
        with self.app.db:self.app.db.execute("update tg_group_archives set next_attempt_at='' where principal=?",(p,))
        self.run_async(self.app.process_new_group_archive(1,p));self.assertEqual(c.archived,[(gid,1)]);self.assertEqual(self.app.group_admin_records()[0]['archive']['status'],'Archived')
    def test_archiving_respects_telegram_pause_and_never_switches_identity(self):
        c,p,gid=self.prepare();self.run_async(self.app.available_new_groups(self.app.Account()));self.run_async(self.app.process_new_group_admins(1,p))
        with self.app.db:self.app.db.execute("update account_info set blocked_until='2099-01-01T00:00:00+00:00'")
        with self.assertRaises(HTTPException):self.run_async(self.app.process_new_group_archive(1,p))
        with self.app.db:self.app.db.execute("update account_info set blocked_until=''")
        c.user=999;self.run_async(self.app.process_new_group_archive(1,p));self.assertEqual(c.archived,[])
    def test_new_endpoints_require_auth(self):
        client=TestClient(self.app.app)
        for path in ['/groups/new','/groups/new/admins']:self.assertEqual(client.post(path).status_code,401)
    def test_next_manual_collection_keeps_shared_read_gap(self):
        c,p,gid=self.prepare();c.groups.append(self.channel(79));self.run_async(self.app.available_new_groups(self.app.Account()));self.run_async(self.app.collect_selected_new_group(self.body(p,gid)))
        with self.assertRaises(HTTPException) as caught:self.run_async(self.app.collect_selected_new_group(self.body(p,str(utils.get_peer_id(self.channel(79))))))
        self.assertEqual(caught.exception.status_code,429);self.assertEqual(len(c.archived),1);self.assertEqual(len(self.app.group_admin_records()),1)
    def test_archive_flood_wait_saves_pause_without_losing_admins(self):
        c,p,gid=self.prepare();self.run_async(self.app.available_new_groups(self.app.Account()))
        async def flood(*args):raise errors.FloodWaitError(request=None,capture=120)
        c.edit_folder=flood;r=self.run_async(self.app.collect_selected_new_group(self.body(p,gid)))
        self.assertEqual(r['archive']['status'],'Pending');self.assertEqual(len(self.app.group_admin_records()),1);self.assertTrue(self.app.db.execute('select blocked_until from account_info where principal=?',(p,)).fetchone()[0]);self.assertEqual(c.sent,[])
