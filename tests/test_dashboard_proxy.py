import unittest
import tempfile
import os
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient
from dashboard_proxy import app, BACKEND_ORIGIN


class DashboardProxyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env_patch = patch.dict(os.environ, {'DASHBOARD_SCHEDULE_DIR': self.tmp.name})
        self.env_patch.start()
        self.backend = AsyncMock()
        self.factory_patch = patch('dashboard_proxy.httpx.AsyncClient')
        self.factory_patch.start().return_value.__aenter__.return_value = self.backend
        self.client = TestClient(app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.factory_patch.stop()
        self.env_patch.stop()
        self.tmp.cleanup()

    def test_separate_page_urls_serve_the_workspace_without_reading_backend(self):
        for path in ['/pending-messages', '/sent-messages', '/replies', '/tg-groups', '/message-templates', '/settings']:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn('/page-routes.js', response.text)
        self.backend.request.assert_not_awaited()

    def test_dashboard_health_and_assets_do_not_touch_existing_backend(self):
        self.assertEqual(self.client.get('/dashboard-health').json()['ok'], True)
        page = self.client.get('/')
        self.assertEqual(page.status_code, 200)
        self.assertIn('data-view="sent"', page.text)
        self.assertIn('data-view="replies"', page.text)
        self.assertEqual(self.client.get('/conversations.js').status_code, 200)
        self.backend.request.assert_not_awaited()

    def test_existing_authentication_and_records_are_forwarded_without_storage(self):
        self.backend.request.return_value = httpx.Response(200, json={'accounts': [{'id': 1, 'authorized': True}], 'deliveries': [{'delivery_id': 'existing'}]})
        result = self.client.get('/status', headers={'Authorization': 'Bearer test-issued-token'})
        self.assertEqual(result.json()['deliveries'][0]['delivery_id'], 'existing')
        call = self.backend.request.call_args
        self.assertEqual(call.args, ('GET', BACKEND_ORIGIN + '/status'))
        self.assertEqual(call.kwargs['headers']['authorization'], 'Bearer test-issued-token')
        self.assertEqual(result.headers['cache-control'], 'no-store')

    def test_reviewed_send_is_forwarded_exactly_once_with_original_ids(self):
        self.backend.request.return_value = httpx.Response(200, json={'status': 'Queued'})
        payload = {'request_id': 'stable-request-id', 'action': 'reply', 'payload': {'delivery_id': 'original-delivery', 'request_id': 'stable-request-id', 'message': 'Reviewed answer'}}
        self.assertEqual(self.client.post('/send-queue', json=payload).status_code, 200)
        import json
        self.assertEqual(json.loads(self.backend.request.call_args.kwargs['content']), payload)
        self.backend.request.assert_awaited_once()

    def test_auth_failures_are_preserved_and_not_retried(self):
        self.backend.request.return_value = httpx.Response(401, json={'detail': 'Please log in'})
        self.assertEqual(self.client.get('/status').status_code, 401)
        self.backend.request.assert_awaited_once()

    def test_timeouts_do_not_retry_writes_or_claim_success(self):
        self.backend.request.side_effect = httpx.ReadTimeout('timeout')
        result = self.client.post('/send-queue', json={})
        self.assertEqual(result.status_code, 502)
        self.backend.request.assert_awaited_once()

    def test_redirects_and_unlisted_targets_do_not_forward_credentials(self):
        self.backend.request.return_value = httpx.Response(302, headers={'Location': 'https://other.example'})
        self.assertEqual(self.client.get('/status', headers={'Authorization': 'Bearer test'}).status_code, 502)
        self.backend.request.reset_mock()
        self.assertEqual(self.client.post('/workspace/reset', json={}).status_code, 405)
        self.backend.request.assert_not_awaited()

    def test_methods_and_large_requests_are_rejected_before_forwarding(self):
        self.assertEqual(self.client.post('/status', json={}).status_code, 405)
        self.assertEqual(self.client.post('/send-queue', content=b'x' * (256 * 1024 + 1)).status_code, 413)
        self.backend.request.assert_not_awaited()

    def test_backend_wakeup_html_is_a_retryable_json_error_without_resending(self):
        self.backend.request.return_value = httpx.Response(200, text='<html>Service waking up</html>', headers={'Content-Type': 'text/html'})
        response = self.client.post('/send-queue', json={'request_id': 'keep-this-request'})
        self.assertEqual(response.status_code, 503)
        self.assertIn('waking up', response.json()['detail'])
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.backend.request.assert_awaited_once()
