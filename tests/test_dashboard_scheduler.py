import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from fastapi import HTTPException
from dashboard_scheduler import DashboardScheduler


class DashboardSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.now = datetime(2026, 10, 24, 8, tzinfo=timezone.utc)
        self.clock = patch('dashboard_scheduler.utcnow', side_effect=lambda: self.now)
        self.clock.start()
        self.client = AsyncMock()
        self.state = {'deliveries': [{'delivery_id': 'first', 'status': 'Sent', 'kind': 'dm', 'target': '7', 'recipient_name': 'Test person', 'account_id': 2}], 'leads': [{'key': 'dm:7', 'reply_status': 'Awaiting reply'}], 'queued_sends': []}
        async def request(method, url, **kwargs):
            return httpx.Response(200, json=self.state if method == 'GET' else {'status': 'Queued', 'queue_id': 'original-backend-queue'})
        self.client.request.side_effect = request
        self.scheduler = DashboardScheduler(self.tmp.name, 'https://backend.example', self.client)
        self.body = {'request_id': 'schedule-request-001', 'action': 'follow-up', 'payload': {'delivery_id': 'first', 'request_id': 'schedule-request-001', 'message': 'Reviewed message'}, 'scheduled_at': (self.now + timedelta(minutes=10)).isoformat(), 'session_expires_at': (self.now + timedelta(hours=5)).isoformat()}

    def tearDown(self):
        self.scheduler.db.close()
        self.clock.stop()
        self.tmp.cleanup()

    def run_async(self, value):
        return asyncio.run(value)

    def create(self):
        return self.run_async(self.scheduler.create(self.body, 'Bearer test-credential-secret'))

    def posts(self):
        return [c for c in self.client.request.call_args_list if c.args[0] == 'POST']

    def test_schedule_never_submits_before_due_time(self):
        self.assertEqual(self.create()['status'], 'Scheduled')
        self.run_async(self.scheduler.process())
        self.assertEqual(len(self.posts()), 0)
        self.now += timedelta(minutes=10, seconds=1)
        self.run_async(self.scheduler.process())
        self.assertEqual(len(self.posts()), 1)
        self.assertEqual(self.posts()[0].kwargs['json']['payload']['delivery_id'], 'first')
        self.assertEqual(self.posts()[0].kwargs['json']['request_id'], self.body['request_id'])
        self.assertEqual(self.scheduler.records()[0]['status'], 'Queued')
        self.run_async(self.scheduler.process())
        self.assertEqual(len(self.posts()), 1)

    def test_reply_before_due_cancels_schedule_without_posting(self):
        self.create()
        self.state['leads'][0]['reply_status'] = 'Replied'
        self.now += timedelta(minutes=10, seconds=1)
        self.run_async(self.scheduler.process())
        self.assertEqual(self.scheduler.records()[0]['status'], 'Cancelled')
        self.assertEqual(len(self.posts()), 0)

    def test_status_poll_cancels_future_followup_on_reply(self):
        self.create()
        rows = self.scheduler.records(leads=[{'key': 'dm:7', 'latest_reply': {'body': 'Yes'}}])
        self.assertEqual(rows[0]['status'], 'Cancelled')
        self.assertNotIn(self.body['request_id'], self.scheduler.tokens)

    def test_expired_signin_waits_and_can_resume_with_fresh_authenticated_session(self):
        self.create()
        self.now += timedelta(minutes=10, seconds=1)
        self.scheduler.tokens[self.body['request_id']] = ('Bearer old', self.now - timedelta(seconds=1))
        self.run_async(self.scheduler.process())
        self.assertEqual(self.scheduler.records()[0]['status'], 'Waiting for sign-in')
        self.assertEqual(len(self.posts()), 0)
        self.scheduler.remember('Bearer new', (self.now + timedelta(hours=1)).isoformat())
        self.run_async(self.scheduler.process())
        self.assertEqual(len(self.posts()), 1)

    def test_ambiguous_submit_is_quarantined_and_never_automatically_retried(self):
        self.create()
        real = self.client.request.side_effect
        async def timeout(method, *args, **kwargs):
            if method == 'POST':
                raise httpx.ReadTimeout('timeout')
            return await real(method, *args, **kwargs)
        self.client.request.side_effect = timeout
        self.now += timedelta(minutes=10, seconds=1)
        self.run_async(self.scheduler.process())
        self.assertEqual(self.scheduler.records()[0]['status'], 'Needs attention')
        self.run_async(self.scheduler.process())
        self.assertEqual(len(self.posts()), 1)

    def test_duplicate_request_returns_same_schedule_even_after_due_and_blocks_changed_payload(self):
        self.create()
        self.now += timedelta(minutes=10, seconds=1)
        self.assertEqual(self.create()['schedule_id'], self.body['request_id'])
        self.body['payload']['message'] = 'Changed'
        with self.assertRaises(HTTPException) as caught:
            self.create()
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(len(self.scheduler.records()), 1)

    def test_cancel_and_missed_window_do_not_send(self):
        self.create()
        self.run_async(self.scheduler.cancel(self.body['request_id'], 'Bearer test'))
        self.assertEqual(self.scheduler.records()[0]['status'], 'Cancelled')
        self.now += timedelta(hours=1)
        self.run_async(self.scheduler.process())
        self.assertEqual(len(self.posts()), 0)

    def test_missed_window_requires_review_instead_of_sending_a_day_late(self):
        self.create()
        self.now += timedelta(hours=1)
        self.run_async(self.scheduler.process())
        self.assertEqual(self.scheduler.records()[0]['status'], 'Missed')
        self.assertEqual(len(self.posts()), 0)

    def test_no_credentials_are_written_to_database(self):
        self.create()
        self.assertNotIn(b'test-credential-secret', (Path(self.tmp.name) / 'schedules.db').read_bytes())
        self.assertNotIn('authorization', json.dumps(self.scheduler.records()).lower())

    def test_late_or_outside_session_schedule_is_rejected(self):
        for delta in [-1, 13 * 60]:
            self.body['scheduled_at'] = (self.now + timedelta(minutes=delta)).isoformat()
            with self.assertRaises(HTTPException):
                self.create()
        self.assertEqual(len(self.posts()), 0)

    def test_replied_contacts_cannot_be_scheduled_as_followups(self):
        self.state['leads'][0]['latest_reply'] = {'body': 'Hello'}
        with self.assertRaises(HTTPException):
            self.create()
        self.body['action'] = 'reply'
        self.assertEqual(self.create()['status'], 'Scheduled')

    def test_deduplicates_recipients_and_reports_backend_delivery_status(self):
        self.create()
        self.body['request_id'] = self.body['payload']['request_id'] = 'another-request-001'
        with self.assertRaises(HTTPException):
            self.create()
        self.now += timedelta(minutes=10, seconds=1)
        self.run_async(self.scheduler.process())
        self.assertEqual(self.scheduler.records([{'queue_id': 'original-backend-queue', 'status': 'Sent'}])[0]['status'], 'Sent')
