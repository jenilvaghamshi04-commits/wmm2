import copy
import json
import tempfile
import unittest
from unittest.mock import AsyncMock
from datetime import datetime, timezone
import httpx
from fastapi import HTTPException
from dashboard_scheduler import DashboardScheduler
from dashboard_safety import OutreachSafety

class SafetyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.client=AsyncMock()
        self.scheduler=DashboardScheduler(self.tmp.name,'https://backend.example',self.client)
        self.guard=OutreachSafety(self.scheduler)
        self.state={'settings':{'auto_yes_enabled':False,'auto_followup_enabled':False},'accounts':[{'id':i,'authorized':True} for i in (1,2,3)],'contacts':[{'id':f'c{i}','user_id':str(i),'kind':'dm'} for i in range(40)],'deliveries':[],'queued_sends':[]}
        self.scheduler.status=AsyncMock(side_effect=lambda a:copy.deepcopy(self.state))
        self.client.request.return_value=httpx.Response(200,json={'status':'Queued','queue_id':'q'})
    def tearDown(self):
        self.scheduler.db.close();self.tmp.cleanup()
    def plan(self,i=0,account=1,rid=None):
        return {'request_id':rid or 'request-'+str(i),'action':'send','payload':{'id':f'c{i}','account_id':account,'message':'Reviewed message'}}
    async def test_first_send_needs_no_permission_record(self):
        response=await self.guard.submit('/send-queue',self.plan(),'token')
        self.assertEqual(response.status_code,200)
        self.client.request.assert_awaited_once()
    async def test_ten_account_cap_includes_reservations(self):
        for i in range(10):self.assertEqual((await self.guard.submit('/send-queue',self.plan(i),'token')).status_code,200)
        with self.assertRaises(HTTPException) as cm:await self.guard.submit('/send-queue',self.plan(10),'token')
        self.assertEqual(cm.exception.status_code,429)
    async def test_cross_account_and_duplicate_id_blocked(self):
        await self.guard.submit('/send-queue',self.plan(),'token')
        with self.assertRaises(HTTPException):await self.guard.submit('/send-queue',self.plan(account=2,rid='another-request'),'token')
        with self.assertRaises(HTTPException):await self.guard.submit('/send-queue',self.plan(rid='different-id'),'token')
        self.assertEqual(self.client.request.await_count,1)
    async def test_same_request_receipt_never_resends(self):
        p=self.plan()
        await self.guard.submit('/send-queue',p,'token');await self.guard.submit('/send-queue',p,'token')
        self.assertEqual(self.client.request.await_count,1)
    async def test_uncertain_timeout_does_not_retry(self):
        self.client.request.side_effect=httpx.ReadTimeout('timeout');p=self.plan()
        self.assertEqual((await self.guard.submit('/send-queue',p,'token')).status_code,502)
        await self.guard.submit('/send-queue',p,'token');self.assertEqual(self.client.request.await_count,1)
    async def test_restriction_blocks_even_after_cooldown(self):
        self.state['accounts'][0].update(error='Spam restriction',blocked_until='2020-01-01T00:00:00+00:00')
        with self.assertRaises(HTTPException):await self.guard.submit('/send-queue',self.plan(),'token')
        self.client.request.assert_not_awaited()
    async def test_batch_is_atomic_on_unknown_person(self):
        p={'request_id':'batch-request','account_id':1,'messages':[{'id':'c0'},{'id':'missing'}]}
        with self.assertRaises(HTTPException):await self.guard.submit('/groups/admins/send-batch',p,'token')
        self.assertEqual(self.guard.db.execute('select count(*) from outreach_requests').fetchone()[0],0)
    async def test_history_counts_survive_missing_local_ledger(self):
        self.state['deliveries']=[{'account_id':1,'target':str(i),'kind':'dm','at':datetime.now(timezone.utc).isoformat(),'status':'Uncertain'} for i in range(10)]
        with self.assertRaises(HTTPException) as cm:await self.guard.submit('/send-queue',self.plan(20),'token')
        self.assertEqual(cm.exception.status_code,429)
    async def test_default_automation_blocks(self):
        self.state['settings']={}
        with self.assertRaises(HTTPException):await self.guard.submit('/send-queue',self.plan(),'token')
    async def test_old_active_queue_still_reserves_today(self):
        self.state['queued_sends']=[{'account_id':1,'target':str(i),'kind':'dm','created_at':'2020-01-01T00:00:00+00:00','status':'Queued'} for i in range(10)]
        with self.assertRaises(HTTPException) as cm:await self.guard.submit('/send-queue',self.plan(20),'token')
        self.assertEqual(cm.exception.status_code,429)
    async def test_team_cap_with_additional_account(self):
        self.state['accounts'].append({'id':4,'authorized':True})
        self.state['deliveries']=[{'account_id':1+i//10,'target':str(i),'kind':'dm','at':datetime.now(timezone.utc).isoformat(),'status':'Sent'} for i in range(30)]
        with self.assertRaises(HTTPException) as cm:await self.guard.submit('/send-queue',self.plan(35,4),'token')
        self.assertEqual(cm.exception.status_code,429)
    async def test_scheduled_dispatch_rechecks_restrictions(self):
        from datetime import timedelta
        self.scheduler.safety=self.guard
        self.state['accounts'][0]['error']='Spam restriction'
        original={'delivery_id':'original','account_id':1,'kind':'dm','target':'0','status':'Sent'}
        self.state['deliveries']=[original]
        request={'request_id':'scheduled-test','action':'follow-up','payload':{'delivery_id':'original','request_id':'scheduled-test','message':'Reviewed follow-up'}}
        now=datetime.now(timezone.utc)
        self.guard.db.execute('insert into jobs values(?,?,?,?,?,?,?,?,?)',('scheduled-test','f',json.dumps(request),json.dumps({'target':'0','account_id':1,'action':'follow-up'}),(now-timedelta(seconds=1)).isoformat(),(now+timedelta(hours=1)).isoformat(),'Scheduled','',''))
        self.guard.db.commit();self.scheduler.tokens['scheduled-test']=('token',now+timedelta(hours=1))
        await self.scheduler.process()
        self.assertEqual(self.guard.db.execute('select status from jobs').fetchone()[0],'Needs attention')
        self.client.request.assert_not_awaited()
if __name__=='__main__':unittest.main()
