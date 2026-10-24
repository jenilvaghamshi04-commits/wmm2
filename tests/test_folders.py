import asyncio,copy,importlib.util,os,tempfile,unittest
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import patch
from telethon import types,functions,errors
from test_gateway import FakeClient

class FolderClient(FakeClient):
    def __init__(self,*args,**kwargs):super().__init__(*args,**kwargs);self.filters=[];self.updates=[];self.calls=0;self.folder_error=None;self.reject_empty=False;self.next_message=100
    async def get_input_entity(self,uid):return types.InputPeerUser(uid,uid*100)
    async def send_message(self,peer,text):
        await super().send_message(peer,text);self.next_message+=1;return SimpleNamespace(id=self.next_message)
    async def __call__(self,request):
        self.calls+=1
        if self.folder_error:raise self.folder_error
        if isinstance(request,functions.messages.GetDialogFiltersRequest):return SimpleNamespace(filters=copy.deepcopy(self.filters))
        if isinstance(request,functions.messages.UpdateDialogFilterRequest):
            f=request.filter
            if self.reject_empty and f and not (f.include_peers or f.pinned_peers or any(getattr(f,n,False) for n in ('contacts','non_contacts','groups','broadcasts','bots'))):raise errors.FilterIncludeEmptyError(request=None)
            self.updates.append(copy.deepcopy(request));self.filters=[old for old in self.filters if getattr(old,'id',None)!=request.id]
            if f:self.filters.append(copy.deepcopy(f))
            return True
        raise AssertionError(type(request).__name__)

class FolderTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'DATA_DIR':self.tmp.name,'DASHBOARD_KEY':'test-secret','TELEGRAM_API_ID':'','TELEGRAM_API_HASH':''});self.env.start();self.load()
        self.client=FolderClient(user=101);self.app.clients[1]=self.client;self.app.save({'id':'dm:7','user_id':'7','name':'Lead Seven','kind':'dm','username':'','group':'Test group'})
    def load(self):
        spec=importlib.util.spec_from_file_location('folder_test_gateway','backend/app.py');self.app=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.app);self.real_followup_timing=self.app.followup_timing;__import__('legacy_timing').isolate_scheduler(self.app);self.app.enforce_send_pacing=lambda *args:None
    def tearDown(self):self.app.db.close();self.env.stop();self.tmp.cleanup()
    def run_async(self,coro):return asyncio.run(coro)
    def send(self):
        self.run_async(self.app.deliver('dm:7',1,message='Hello there'));return self.app.records()[0]['delivery_id']
    def reply(self,mid=102):return self.app.record_reply('101','7',1,SimpleNamespace(id=mid,date=datetime.now(timezone.utc)+timedelta(seconds=1),out=False,raw_text='Yes, hello'))
    def route(self):return self.app.folder_route_records('7',{'101'})[0]
    def folder(self,title):return next(f for f in self.client.filters if self.app.folder_title(f)==title)
    def make_folder(self,title,fid,include=(),pins=(),exclude=(),**kwargs):return types.DialogFilter(id=fid,title=types.TextWithEntities(title,[]),include_peers=[types.InputPeerUser(i,i*100) for i in include],pinned_peers=[types.InputPeerUser(i,i*100) for i in pins],exclude_peers=[types.InputPeerUser(i,i*100) for i in exclude],**kwargs)
    def sync(self):return self.run_async(self.app.sync_folder_routes('dm:7',limit=3))
    def test_confirmed_send_queues_blue_and_creates_only_needed_folder(self):
        self.send();self.assertEqual(self.route()['desired'],'🔵');self.assertEqual(self.route()['status'],'Pending');self.assertEqual(self.client.calls,0)
        result=self.sync();self.assertTrue(result['results'][0]['ok']);self.assertEqual(self.route()['applied'],'🔵');self.assertEqual(self.folder('🔵').include_peers[0].user_id,7);self.assertEqual(self.app.records()[0]['status'],'Sent')
    def test_reply_moves_yellow_and_preserves_other_chats_and_folder_metadata(self):
        self.client.filters=[self.make_folder('🔵',4,include=[7,8],pins=[7,9],exclude=[10],color=3,emoticon='📁'),self.make_folder('🟡',6,include=[11],exclude=[7],non_contacts=True),self.make_folder('Work',9,include=[12],contacts=True)]
        unrelated=copy.deepcopy(self.client.filters[2].to_dict());self.send();self.reply();self.sync()
        blue=self.folder('🔵');yellow=self.folder('🟡');self.assertEqual([p.user_id for p in blue.include_peers],[8]);self.assertEqual([p.user_id for p in blue.pinned_peers],[9]);self.assertEqual(blue.color,3);self.assertEqual(blue.emoticon,'📁');self.assertEqual([p.user_id for p in blue.exclude_peers],[10]);self.assertEqual([p.user_id for p in yellow.include_peers],[11,7]);self.assertEqual(yellow.exclude_peers,[]);self.assertEqual(self.folder('Work').to_dict(),unrelated);self.assertEqual(self.route()['applied'],'🟡')
    def test_automatic_source_folder_adds_only_target_exclusion(self):
        self.client.filters=[self.make_folder('🔵',4,contacts=True),self.make_folder('🟡',5,include=[8])];self.send();self.reply();self.sync();self.assertTrue(self.folder('🔵').contacts);self.assertEqual([p.user_id for p in self.folder('🔵').exclude_peers],[7])
    def test_new_send_returns_blue_and_old_reply_history_does_not_move_yellow(self):
        did=self.send();self.reply(mid=102);self.sync();self.client.next_message=200
        self.run_async(self.app.follow_up(self.app.Followup(delivery_id=did,message='Thanks for replying',request_id='folder-next-send-001')))
        self.assertEqual(self.route()['desired'],'🔵');self.reply(mid=150);self.assertEqual(self.route()['desired'],'🔵');self.reply(mid=202);self.assertEqual(self.route()['desired'],'🟡')
    def test_empty_source_is_retained_as_template_and_restored_with_metadata(self):
        self.client.reject_empty=True;self.client.filters=[self.make_folder('🔵',4,include=[7],color=3,emoticon='📁')];did=self.send();self.reply();self.sync();self.assertEqual(self.route()['status'],'Synced');self.assertEqual(self.route()['applied'],'🟡');self.assertFalse(any(self.app.folder_title(f)=='🔵' for f in self.client.filters));self.assertIsNotNone(self.app.db.execute('select body from empty_folder_templates').fetchone())
        self.client.next_message=200;self.run_async(self.app.follow_up(self.app.Followup(delivery_id=did,message='Thanks, here are details',request_id='restore-folder-001')));self.sync();blue=self.folder('🔵');self.assertEqual(blue.id,4);self.assertEqual(blue.color,3);self.assertEqual(blue.emoticon,'📁');self.assertEqual([p.user_id for p in blue.include_peers],[7]);self.assertEqual(self.route()['status'],'Synced')
    def test_folder_error_never_changes_delivery_or_resends_message(self):
        self.send();self.client.folder_error=errors.RPCError(request=None,message='FOLDER_LIMIT');result=self.sync();self.assertFalse(result['results'][0]['ok']);self.assertEqual(self.route()['status'],'Needs attention');self.assertEqual(self.app.records()[0]['status'],'Sent');self.assertEqual(len(self.client.sent),1);self.assertEqual(self.app.usage('101')['dm']['used'],1)
        self.client.folder_error=None;self.run_async(self.app.check_chat_folders(self.app.ReplySync(key='dm:7')));self.assertEqual(self.route()['status'],'Synced');self.assertEqual(len(self.client.sent),1)
    def test_telegram_wait_blocks_all_routes_even_manual_retry(self):
        self.send();self.client.folder_error=errors.FloodWaitError(request=None,capture=1000);self.sync();calls=self.client.calls;self.run_async(self.app.check_chat_folders(self.app.ReplySync(key='dm:7')));self.assertEqual(self.client.calls,calls);self.assertIn('1000s',self.route()['error'])
    def test_duplicate_folder_names_never_overwrite_either(self):
        self.client.filters=[self.make_folder('🔵',3,include=[8]),self.make_folder('🔵',4,include=[9])];self.send();self.sync();self.assertEqual(len(self.client.updates),0);self.assertIn('Multiple',self.route()['error'])
    def test_existing_shared_folder_is_not_modified(self):
        self.client.filters=[types.DialogFilterChatlist(id=5,title=types.TextWithEntities('🔵',[]),pinned_peers=[],include_peers=[])];self.send();self.sync();self.assertEqual(len(self.client.updates),0);self.assertIn('personal',self.route()['error'])
    def test_only_original_sender_account_can_modify_folders(self):
        self.send();self.client.user=999;self.sync();self.assertEqual(self.client.calls,0);self.assertEqual(self.route()['status'],'Needs attention');self.assertEqual(self.route()['applied'],'')
    def test_sender_identity_can_move_to_another_account_slot(self):
        self.send();self.app.clients.pop(1);self.app.clients[2]=self.client;self.sync();self.assertEqual(self.route()['account_id'],2);self.assertEqual(self.route()['status'],'Synced')
    def test_failed_and_uncertain_messages_and_group_sends_do_not_queue(self):
        self.client.fail=RuntimeError('Connection lost')
        with self.assertRaises(Exception):self.send()
        self.assertEqual(self.app.db.execute('select count(*) from folder_routes').fetchone()[0],0)
        self.client.fail=None;self.app.save({'id':'group:1','group_id':'-1001','kind':'group','name':'Test group'})
        self.run_async(self.app.deliver('group:1',1,kind='group',message='Group hello'));self.assertEqual(self.app.db.execute('select count(*) from folder_routes').fetchone()[0],0)
    def test_queue_survives_restart_without_resending(self):
        self.send();self.app.db.close();self.load();self.app.clients[1]=self.client;self.sync();self.assertEqual(len(self.client.sent),1);self.assertEqual(self.route()['applied'],'🔵')
    def test_existing_sent_contacts_seed_once_and_synced_work_is_idempotent(self):
        self.send();self.reply();self.app.db.execute('delete from folder_routes');self.app.db.commit();self.app.seed_folder_routes();self.assertEqual(self.route()['desired'],'🟡');self.sync();calls=self.client.calls;self.app.seed_folder_routes();self.sync();self.assertEqual(self.client.calls,calls)
    def test_duplicate_reply_events_do_not_requeue_synced_folder(self):
        self.send();self.reply();self.sync();calls=self.client.calls;self.assertFalse(self.reply());self.sync();self.assertEqual(self.client.calls,calls)
    def test_yes_stays_yellow_after_both_automatic_messages(self):
        self.run_async(self.app.deliver('dm:7',message='Hi about $TOKEN',token_symbol='ABC',exchange='mexc',auto_yes=True))
        self.app.record_reply('101','7',1,SimpleNamespace(id=102,date=datetime.now(timezone.utc)+timedelta(seconds=1),out=False,raw_text='yeh'))
        self.assertEqual(self.route()['desired'],'🟡');self.run_async(self.app.process_auto_yes());self.assertEqual(len(self.client.sent),3);self.assertEqual(self.route()['desired'],'🟡');self.sync();self.assertEqual(self.route()['applied'],'🟡');self.assertEqual(self.folder('🟡').include_peers[0].user_id,7)
        self.assertEqual(self.app.usage('101')['dm']['used'],1)
    def test_yes_stays_yellow_after_later_manual_message(self):
        did=self.send();self.app.record_reply('101','7',1,SimpleNamespace(id=102,date=datetime.now(timezone.utc)+timedelta(seconds=1),out=False,raw_text='Yes!'));self.client.next_message=200
        self.run_async(self.app.follow_up(self.app.Followup(delivery_id=did,message='Thanks, sharing details',request_id='positive-manual-001')));self.assertEqual(self.route()['desired'],'🟡')
    def test_existing_positive_route_repaired_once_without_message_send(self):
        self.send();self.app.record_reply('101','7',1,SimpleNamespace(id=102,date=datetime.now(timezone.utc)+timedelta(seconds=1),out=False,raw_text='yes'))
        self.app.db.execute("update folder_routes set desired='🔵',applied='🔵',applied_revision=revision");self.app.db.commit();self.app.seed_folder_routes();self.assertEqual(self.route()['desired'],'🟡');self.sync();calls=self.client.calls;self.app.seed_folder_routes();self.sync();self.assertEqual(self.client.calls,calls);self.assertEqual(len(self.client.sent),1)
    def test_backfilled_yes_older_than_latest_outgoing_still_routes_yellow(self):
        did=self.send();self.client.next_message=200;self.run_async(self.app.follow_up(self.app.Followup(delivery_id=did,message='More information',request_id='positive-backfill-001')));self.assertEqual(self.route()['desired'],'🔵')
        self.app.record_reply('101','7',1,SimpleNamespace(id=150,date=datetime.now(timezone.utc),out=False,raw_text='yes'));self.assertEqual(self.route()['desired'],'🟡')
    def test_positive_folder_uses_original_identity_after_slot_move(self):
        self.send();self.app.record_reply('101','7',1,SimpleNamespace(id=102,date=datetime.now(timezone.utc)+timedelta(seconds=1),out=False,raw_text='yeah'));self.app.clients.pop(1);other=FolderClient(user=999);self.app.clients[1]=other;self.app.clients[3]=self.client;self.sync();self.assertEqual(other.calls,0);self.assertEqual(self.route()['account_id'],3);self.assertEqual(self.route()['applied'],'🟡')
    def test_yes_from_another_sender_does_not_move_this_account_yellow(self):
        self.send();self.app.db.execute('insert into replies values(?,?,?,?,?,?)',('999','7',102,2,datetime.now(timezone.utc).isoformat(),'yes'));self.app.db.commit();self.app.queue_folder_route('101','7',1,'🔵');self.assertEqual(self.route()['desired'],'🔵')
