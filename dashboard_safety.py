"""Fail-closed outreach checks for the dashboard gateway; no Telegram credentials stored."""
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from fastapi import HTTPException
from fastapi.responses import JSONResponse
import httpx

ACTIVE = {'Queued', 'Sending', 'Needs attention', 'Uncertain', 'Scheduled', 'Waiting for sign-in'}

class OutreachSafety:
    def __init__(self, scheduler):
        self.scheduler = scheduler
        self.db = scheduler.db
        self.lock = asyncio.Lock()
        self.db.execute('create table if not exists outreach_permissions(target text primary key, account integer, status text, evidence text, updated text)')
        self.db.execute('create table if not exists outreach_requests(id text primary key, fingerprint text, day text, targets text, response text, code integer)')
        self.db.commit()

    def permissions(self):
        return {r[0]:dict(target=r[0], account_id=r[1], status=r[2], evidence=r[3], updated_at=r[4]) for r in self.db.execute('select * from outreach_permissions')}

    def day(self):
        return datetime.now(ZoneInfo('Asia/Kolkata')).date().isoformat()

    def counts(self, state):
        pairs = set()
        for row in state.get('deliveries', []) + state.get('queued_sends', []):
            at = row.get('at') or row.get('created_at') or ''
            try:
                day = datetime.fromisoformat(at.replace('Z', '+00:00')).astimezone(ZoneInfo('Asia/Kolkata')).date().isoformat()
            except (ValueError, TypeError):
                continue
            # Count conservatively, including failed/uncertain attempts and follow-ups.
            if (day == self.day() or row.get('status') in ACTIVE) and row.get('kind', 'dm') == 'dm':
                pairs.add((int(row.get('account_id', 0)), str(row.get('target'))))
        for raw, in self.db.execute('select targets from outreach_requests where day=?', (self.day(),)):
            pairs.update((int(a), str(t)) for a,t in json.loads(raw))
        return pairs

    def summary(self, state):
        pairs = self.counts(state)
        contacts = {}
        for c in state.get('contacts', []):
            if c.get('kind') != 'group' and not c.get('is_bot') and c.get('user_id') is not None:
                t = str(c['user_id'])
                contacts[t] = dict(target=t, name=c.get('name') or t, username=c.get('username', ''))
        return dict(day=self.day(), per_account_limit=10, team_limit=30, team_reserved=len(pairs),
                    account_reserved={str(a['id']):sum(x==a['id'] for x,t in pairs) for a in state.get('accounts', [])},
                    permissions=list(self.permissions().values()), contacts=list(contacts.values()))

    async def update(self, body, authorization):
        state = await self.scheduler.status(authorization)
        target, status, evidence = str(body.get('target', '')), body.get('status'), str(body.get('evidence', '')).strip()
        account = body.get('account_id')
        if not any(str(c.get('user_id')) == target and c.get('kind') != 'group' and not c.get('is_bot') for c in state.get('contacts', [])):
            raise HTTPException(404, 'Choose a saved person.')
        if status not in ('Unknown', 'Agreed', 'Contacted us', 'Opted out') or account not in [a['id'] for a in state.get('accounts', [])]:
            raise HTTPException(422, 'Choose a permission status and an existing account.')
        if status in ('Agreed', 'Contacted us') and (body.get('confirmed') is not True or not 12 <= len(evidence) <= 1000):
            raise HTTPException(422, 'Confirm genuine permission and record its source, date and agreed scope (12–1,000 characters).')
        if len(evidence) > 1000:
            raise HTTPException(422, 'Keep the evidence note under 1,000 characters.')
        async with self.lock:
            old = self.permissions().get(target)
            if old and old['account_id'] != account and any(str(r.get('target')) == target for r in state.get('deliveries', []) + state.get('queued_sends', [])):
                raise HTTPException(409, 'This person already has a sending account. Keep the original assignment.')
            if any(str(r.get('target')) == target and r.get('status') in ('Queued', 'Sending') for r in state.get('queued_sends', [])):
                raise HTTPException(409, 'Review/cancel pending sends before changing permission. Needs-attention rows must be resolved first.')
            self.db.execute('insert or replace into outreach_permissions values(?,?,?,?,?)', (target, account, status, evidence, datetime.now(timezone.utc).isoformat()))
            self.db.commit()
        return {'ok':True}

    def validate(self, path, body, state):
        if state.get('settings', {}).get('auto_followup_enabled', True) or state.get('settings', {}).get('auto_yes_enabled', True):
            raise HTTPException(409, 'Activate reviewed mode in Outreach controls first to disable unattended promotional sequences.')
        permissions = self.permissions()
        action = 'send' if path.endswith('send-batch') else body.get('action')
        payload = body if path.endswith('send-batch') else body.get('payload', {})
        if action not in ('send', 'follow-up', 'reply'):
            raise HTTPException(422, 'Choose a reviewed message action.')
        if payload.get('auto_yes') or payload.get('automatic_followup'):
            raise HTTPException(409, 'Automatic promotional sequences are disabled. Review each message separately.')
        pairs = []
        if action == 'send':
            ids = [m.get('id') for m in body.get('messages', [])] if path.endswith('send-batch') else [payload.get('id')]
            account = payload.get('account_id')
            for cid in ids:
                c = next((c for c in state.get('contacts', []) if c.get('id') == cid), None)
                if not c or c.get('kind') == 'group' or c.get('is_bot') or c.get('user_id') is None:
                    raise HTTPException(409, 'Only saved people with recorded permission can receive dashboard outreach.')
                pairs.append((account, str(c['user_id'])))
        else:
            original = next((d for d in state.get('deliveries', []) if d.get('delivery_id') == payload.get('delivery_id') and d.get('status') == 'Sent' and d.get('kind') == 'dm'), None)
            if not original:
                raise HTTPException(409, 'Choose a confirmed original conversation.')
            pairs = [(original['account_id'], str(original['target']))]
        if not pairs or len(set(pairs)) != len(pairs):
            raise HTTPException(409, 'Choose each person once.')
        for account, target in pairs:
            a = next((a for a in state.get('accounts', []) if a['id'] == account), None)
            if not a or not a.get('authorized'):
                raise HTTPException(409, 'Connect the assigned account first.')
            # An elapsed local cooldown is never treated as spam clearance.
            if a.get('error'):
                raise HTTPException(409, 'Account needs review: '+str(a['error'])[:700])
            if a.get('blocked_until'):
                try:
                    if datetime.fromisoformat(a['blocked_until'].replace('Z','+00:00')) > datetime.now(timezone.utc):
                        raise HTTPException(409, 'Account paused until '+a['blocked_until']+'. This is not proof of spam clearance.')
                except ValueError:
                    raise HTTPException(409, 'Account waiting period needs review.')
            p = permissions.get(target, {})
            if p.get('status') == 'Opted out':
                raise HTTPException(409, 'This person opted out. Sending is blocked.')
            lead = next((l for l in state.get('leads', []) if l.get('key') == 'dm:'+target), {})
            incoming = bool(lead.get('latest_reply') or lead.get('replies'))
            if action != 'reply' or not incoming:
                if p.get('status') not in ('Agreed', 'Contacted us'):
                    raise HTTPException(409, 'Record genuine permission in Outreach controls before sending. Public group membership is not permission.')
            if p and p.get('account_id') != account:
                raise HTTPException(409, 'Use the account assigned in Outreach controls.')
            for raw, receipt, code in self.db.execute('select targets,response,code from outreach_requests'):
                if any(str(t) == target for a,t in json.loads(raw)):
                    unknown = 'Submission is unconfirmed' in json.loads(receipt).get('detail','')
                    if action == 'send' or unknown:
                        raise HTTPException(409, 'An earlier submission exists for this person. Review its history; duplicate or uncertain outreach is blocked.')
            relevant = [d for d in state.get('deliveries', []) + state.get('queued_sends', []) if str(d.get('target')) == target and d.get('kind','dm') == 'dm']
            if any(d.get('account_id') != account and d.get('status') in ACTIVE | {'Sent'} for d in relevant):
                raise HTTPException(409, 'Another account already owns this conversation or needs review. Duplicate outreach blocked.')
            if any(d.get('status') in ACTIVE for d in relevant):
                raise HTTPException(409, 'A pending or uncertain message needs review before another attempt.')
            if action == 'send' and any(d.get('status') == 'Sent' for d in relevant):
                raise HTTPException(409, 'Already contacted. Use the original conversation.')
            if action == 'follow-up' and (incoming or lead.get('stage') in ('Replied','Meeting','Proposal','Client')):
                raise HTTPException(409, 'A reply arrived. Review Replies instead.')
            if action == 'follow-up' and any(d.get('followup_of') and d.get('status') == 'Sent' for d in relevant):
                raise HTTPException(409, 'A follow-up was already sent. Wait for the person to respond.')
        counted = self.counts(state) | set(pairs)
        if len(counted)>30 or any(sum(a==account for a,t in counted)>10 for account,t in pairs):
            raise HTTPException(429, 'Daily outreach cap reached: 10 unique recipients per account, 30 for the team, including reserved and uncertain attempts. Resets at midnight IST; no manual reset.')
        return pairs

    async def submit(self, path, body, authorization):
        if not isinstance(body, dict):
            raise HTTPException(422, 'Invalid message request.')
        rid = body.get('request_id')
        if not isinstance(rid, str) or not 8 <= len(rid) <= 128:
            raise HTTPException(422, 'A stable reviewed request ID is required.')
        fingerprint = hashlib.sha256(json.dumps([path,body],sort_keys=True).encode()).hexdigest()
        async with self.lock:
            # Authenticate every call, including cached receipts.
            state = await self.scheduler.status(authorization)
            old = self.db.execute('select fingerprint,response,code from outreach_requests where id=?',(rid,)).fetchone()
            if old:
                if old[0] != fingerprint:
                    raise HTTPException(409, 'Request ID belongs to a different message.')
                return JSONResponse(json.loads(old[1]),status_code=old[2])
            pairs = self.validate(path,body,state)
            unknown = {'detail':'Submission is unconfirmed. Review Telegram and the sending queue before any new attempt. Automatic retry blocked.'}
            self.db.execute('insert into outreach_requests values(?,?,?,?,?,?)',(rid,fingerprint,self.day(),json.dumps(pairs),json.dumps(unknown),409))
            self.db.commit()
            try:
                r = await self.scheduler.client.request('POST',self.scheduler.origin+path,headers={'Authorization':authorization},json=body)
                data = r.json()
                if not isinstance(data,dict) or not 200<=r.status_code<500:
                    raise ValueError()
                code = r.status_code
            except (httpx.HTTPError,ValueError):
                data,code = unknown,502
            self.db.execute('update outreach_requests set response=?,code=? where id=?',(json.dumps(data),code,rid))
            self.db.commit()
            return JSONResponse(data,status_code=code)
