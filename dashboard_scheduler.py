"""Reviewed, session-bounded schedules for the separate dashboard service.

Credentials stay in process memory, never in the schedules database. The original
backend still owns actual sends, sender locking, pacing and final reply checks.
"""
import asyncio
import hashlib
import json
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
from fastapi import HTTPException


def utcnow():
    return datetime.now(timezone.utc)


def timestamp(value):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError()
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError):
        raise HTTPException(422, 'Choose a valid date and time with a timezone.')


class DashboardScheduler:
    def __init__(self, directory, origin, client):
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        os.chmod(root, 0o700)
        self.db = sqlite3.connect(root / 'schedules.db', check_same_thread=False)
        os.chmod(root / 'schedules.db', 0o600)
        self.db.execute('create table if not exists jobs(id text primary key,fingerprint text,payload text,metadata text,due_at text,expires_at text,status text,error text,backend_id text)')
        self.db.execute("update jobs set status='Needs attention',error='Dashboard restarted during queue submission. Review the existing sending queue before another attempt.' where status='Sending'")
        self.db.commit()
        self.origin, self.client = origin, client
        self.tokens = {}
        self.lock = asyncio.Lock()

    async def status(self, authorization):
        response = await self.client.request('GET', self.origin + '/status', headers={'Authorization': authorization})
        if response.status_code == 401:
            raise HTTPException(401, 'Sign in to your workspace again.')
        if response.status_code != 200 or 'application/json' not in response.headers.get('content-type', ''):
            raise HTTPException(503, 'Your existing WMM server is waking up or unavailable. Retry once it is ready.')
        return response.json()

    def remember(self, authorization, expires_at):
        if not authorization or not expires_at:
            return
        try:
            expiry = timestamp(expires_at)
        except HTTPException:
            return
        if not utcnow() < expiry <= utcnow() + timedelta(hours=12, minutes=1):
            return
        for jid, in self.db.execute("select id from jobs where status in ('Scheduled','Waiting for sign-in')"):
            self.tokens[jid] = (authorization, expiry)

    async def create(self, body, authorization):
        now = utcnow()
        due, expiry = timestamp(body.get('scheduled_at')), timestamp(body.get('session_expires_at'))
        jid, action, payload = body.get('request_id'), body.get('action'), body.get('payload')
        if not isinstance(jid, str) or not 8 <= len(jid) <= 128 or action not in ('follow-up', 'reply') or not isinstance(payload, dict):
            raise HTTPException(422, 'Choose a reviewed follow-up or reply to schedule.')
        if payload.get('request_id') != jid or not isinstance(payload.get('message'), str) or not 1 <= len(payload['message'].strip()) <= 4096:
            raise HTTPException(422, 'Preview a message of up to 4,096 characters first.')
        request = {'request_id': jid, 'action': action, 'payload': payload}
        fingerprint = hashlib.sha256(json.dumps([request, due.isoformat()], sort_keys=True).encode()).hexdigest()
        state = await self.status(authorization)
        if hasattr(self, 'safety'):
            self.safety.validate('/send-queue', request, state)
        async with self.lock:
            existing = self.db.execute('select fingerprint,status from jobs where id=?', (jid,)).fetchone()
            if existing:
                if existing[0] != fingerprint:
                    raise HTTPException(409, 'This request ID already belongs to a different scheduled message.')
                return {'status': existing[1], 'schedule_id': jid, 'scheduled_at': due.isoformat()}
            if due <= now + timedelta(seconds=20) or due >= expiry - timedelta(seconds=20) or due > now + timedelta(hours=12):
                raise HTTPException(422, 'Schedule at least one minute ahead and before your current workspace session expires (up to 12 hours).')
            original = next((d for d in state.get('deliveries', []) if d['delivery_id'] == payload.get('delivery_id') and d['status'] == 'Sent' and d['kind'] == 'dm'), None)
            if not original:
                raise HTTPException(409, 'Choose a confirmed direct-message conversation.')
            target = str(original['target'])
            lead = next((r for r in state.get('leads', []) if r['key'] == 'dm:' + target), {})
            if action == 'follow-up' and (lead.get('latest_reply') or lead.get('replies') or lead.get('reply_status') == 'Replied' or lead.get('stage') in ('Replied','Meeting','Proposal','Client')):
                raise HTTPException(409, 'This person has replied. Use the Replies page instead.')
            for metadata, in self.db.execute("select metadata from jobs where status in ('Scheduled','Waiting for sign-in','Sending','Needs attention')"):
                if str(json.loads(metadata)['target']) == target:
                    raise HTTPException(409, 'This person already has a scheduled message. Review or cancel it first.')
            if any(str(q.get('target')) == target and q.get('status') in ('Queued','Sending','Needs attention') for q in state.get('queued_sends', [])):
                raise HTTPException(409, 'This person already has a pending message in Sending queue.')
            metadata = {'target': target, 'name': original.get('recipient_name', target), 'account_id': original['account_id'], 'action': action}
            self.db.execute('insert into jobs values(?,?,?,?,?,?,?,?,?)', (jid, fingerprint, json.dumps(request), json.dumps(metadata), due.isoformat(), expiry.isoformat(), 'Scheduled', '', ''))
            self.db.commit()
            self.tokens[jid] = (authorization, expiry)
        return {'status': 'Scheduled', 'schedule_id': jid, 'scheduled_at': due.isoformat()}

    def records(self, backend_queue=(), leads=()):
        backend = {r['queue_id']: r for r in backend_queue}
        replied = {r['key'] for r in leads if r.get('latest_reply') or r.get('replies') or r.get('reply_status') == 'Replied' or r.get('stage') in ('Replied','Meeting','Proposal','Client')}
        result = []
        for jid, raw, metadata, due, status, error, backend_id in self.db.execute('select id,payload,metadata,due_at,status,error,backend_id from jobs order by due_at desc limit 1000').fetchall():
            meta = json.loads(metadata)
            if status in ('Scheduled', 'Waiting for sign-in') and meta['action'] == 'follow-up' and 'dm:' + str(meta['target']) in replied:
                status, error = 'Cancelled', 'Reply received. Open Replies to respond.'
                self.finish(jid, status, error)
            if backend_id in backend and status == 'Queued':
                status = backend[backend_id]['status']
            result.append({'schedule_id': jid, **meta, 'message': json.loads(raw)['payload']['message'], 'scheduled_at': due, 'status': status, 'error': error, 'backend_queue_id': backend_id})
        return result

    async def cancel(self, jid, authorization):
        await self.status(authorization)
        async with self.lock:
            row = self.db.execute('select status from jobs where id=?', (jid,)).fetchone()
            if not row:
                raise HTTPException(404, 'Scheduled message not found.')
            if row[0] not in ('Scheduled', 'Waiting for sign-in', 'Needs attention', 'Missed'):
                raise HTTPException(409, 'This message has reached the sending queue. Review it in Settings → Sending queue.')
            self.finish(jid, 'Cancelled', 'Cancelled by you.')
        return {'status': 'Cancelled'}

    def finish(self, jid, status, error='', backend_id=''):
        self.db.execute('update jobs set status=?,error=?,backend_id=? where id=?', (status, error, backend_id, jid))
        self.db.commit()
        if status not in ('Scheduled', 'Waiting for sign-in'):
            self.tokens.pop(jid, None)

    async def process(self):
        async with self.lock:
            for jid, raw, metadata, due in self.db.execute("select id,payload,metadata,due_at from jobs where status in ('Scheduled','Waiting for sign-in') and due_at<=? order by due_at limit 3", (utcnow().isoformat(),)).fetchall():
                if utcnow() - timestamp(due) > timedelta(minutes=15):
                    self.finish(jid, 'Missed', 'The server was not ready during this schedule. Review and schedule again; nothing was sent.')
                    continue
                authorization, expiry = self.tokens.get(jid, ('', utcnow()))
                if not authorization or expiry <= utcnow():
                    self.finish(jid, 'Waiting for sign-in', 'Sign in again before this message can be queued.')
                    self.tokens.pop(jid, None)
                    continue
                request, meta = json.loads(raw), json.loads(metadata)
                try:
                    state = await self.status(authorization)
                except (HTTPException, httpx.HTTPError):
                    continue  # Read-only checks may be retried; sends never are.
                lead = next((r for r in state.get('leads', []) if r['key'] == 'dm:' + str(meta['target'])), {})
                if request['action'] == 'follow-up' and (lead.get('latest_reply') or lead.get('replies') or lead.get('reply_status') == 'Replied' or lead.get('stage') in ('Replied','Meeting','Proposal','Client')):
                    self.finish(jid, 'Cancelled', 'A reply arrived before the scheduled follow-up. Open Replies to respond.')
                    continue
                claim = self.db.execute("update jobs set status='Sending' where id=? and status in ('Scheduled','Waiting for sign-in')", (jid,))
                self.db.commit()
                if not claim.rowcount:
                    continue
                try:
                    if hasattr(self, 'safety'):
                        response = await self.safety.submit('/send-queue', request, authorization)
                        data = json.loads(response.body)
                    else:
                        response = await self.client.request('POST', self.origin + '/send-queue', headers={'Authorization': authorization}, json=request)
                        data = response.json()
                    if not isinstance(data, dict):
                        raise ValueError('Invalid queue response')
                    if response.status_code == 200 and data.get('status') in ('Queued','Sending','Sent'):
                        self.finish(jid, 'Queued' if data['status'] != 'Sent' else 'Sent', backend_id=data.get('queue_id',''))
                    elif response.status_code == 401:
                        self.finish(jid, 'Waiting for sign-in', 'Sign in again to continue this schedule.')
                        self.tokens.pop(jid, None)
                    else:
                        detail = data.get('detail', 'Review the original sending queue before trying again.')
                        self.finish(jid, 'Needs attention', detail if isinstance(detail, str) else 'Review the original sending queue before trying again.')
                except HTTPException as exc:
                    self.finish(jid, 'Needs attention', str(exc.detail))
                except (httpx.HTTPError, ValueError):
                    self.finish(jid, 'Needs attention', 'Queue submission could not be confirmed. Check Settings → Sending queue before another attempt.')

    async def loop(self):
        while True:
            await asyncio.sleep(5)
            try:
                await self.process()
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
