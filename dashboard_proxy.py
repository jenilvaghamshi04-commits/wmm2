"""Serve the updated UI while leaving the existing WMM backend/data untouched.

Run this entrypoint on a NEW service. Do not replace the original backend service.
No Telegram sessions, dashboard keys or original database records are copied here.
Only new schedule metadata is stored locally; issued session tokens stay in memory.
"""
import os
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from dashboard_scheduler import DashboardScheduler

BACKEND_ORIGIN = os.getenv('WMM_BACKEND_ORIGIN', 'https://wmm2.onrender.com').rstrip('/')
origin = urlsplit(BACKEND_ORIGIN)
if origin.scheme != 'https' or not origin.hostname or origin.username or origin.password or origin.path or origin.query or origin.fragment:
    raise RuntimeError('WMM_BACKEND_ORIGIN must be the existing backend HTTPS origin only.')

GET_PATHS = {'/status', '/templates', '/health', '/api/health', '/groups/admins', '/locations/options'}
POST_PATHS = {
    '/auth/login', '/auth/logout', '/auth/session', '/accounts/add', '/telegram-api',
    '/login', '/login/resend', '/login/qr', '/login/qr/status', '/login/qr/cancel',
    '/verify', '/logout', '/groups/new', '/groups/new/admins', '/groups/admins/send-batch',
    '/sending-pace', '/templates', '/replies/sync', '/leads/update', '/send-queue', '/send-queue/cancel',
}

@asynccontextmanager
async def lifespan(app):
    # Never retry writes: the backend owns idempotency, quotas and delivery state.
    async with httpx.AsyncClient(timeout=httpx.Timeout(75, connect=10), follow_redirects=False) as client:
        app.state.backend_client = client
        scheduler = DashboardScheduler(os.getenv('DASHBOARD_SCHEDULE_DIR', '/tmp/wmm-dashboard-schedules'), BACKEND_ORIGIN, client)
        app.state.scheduler = scheduler
        task = asyncio.create_task(scheduler.loop())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            scheduler.db.close()

app = FastAPI(title='WMM Team Dashboard', docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

@app.get('/dashboard-health')
async def dashboard_health():
    return {'ok': True, 'service': 'wmm-dashboard'}

@app.middleware('http')
async def forward_api(request: Request, call_next):
    path = request.url.path
    if path not in GET_PATHS | POST_PATHS:
        return await call_next(request)
    permitted = GET_PATHS if request.method == 'GET' else POST_PATHS if request.method == 'POST' else set()
    if path not in permitted:
        return JSONResponse({'detail': 'Method not allowed'}, status_code=405)
    body = await request.body()
    if len(body) > 256 * 1024:
        return JSONResponse({'detail': 'Request is too large'}, status_code=413)
    headers = {name: request.headers[name] for name in ('authorization', 'content-type', 'accept') if name in request.headers}
    try:
        result = await request.app.state.backend_client.request(
            request.method, BACKEND_ORIGIN + path,
            params=request.query_params, content=body, headers=headers,
        )
    except httpx.HTTPError:
        return JSONResponse({'detail': 'Your existing WMM server is waking up or temporarily unavailable. Retry the same request; do not create another message.'}, status_code=502, headers={'Cache-Control': 'no-store'})
    if 300 <= result.status_code < 400:
        return JSONResponse({'detail': 'The existing backend returned an unexpected redirect.'}, status_code=502)
    if 'application/json' not in result.headers.get('content-type', '').lower():
        # Render can return an HTML wake-up page before a free backend is ready.
        # Preserve the browser's session and request ID instead of a JSON parse error.
        return JSONResponse({'detail': 'Your existing WMM server is waking up or temporarily unavailable. Retry the same request once it is ready.'}, status_code=503, headers={'Cache-Control': 'no-store'})
    if path == '/status' and result.status_code == 200:
        data = result.json()
        scheduler = request.app.state.scheduler
        scheduler.remember(request.headers.get('authorization', ''), request.headers.get('x-workspace-expires-at'))
        data['scheduled_sends'] = scheduler.records(data.get('queued_sends', []), data.get('leads', []))
        return JSONResponse(data, headers={'Cache-Control': 'no-store'})
    return Response(result.content, status_code=result.status_code, headers={
        'Content-Type': result.headers.get('content-type', 'application/json'),
        'Cache-Control': 'no-store',
    })

@app.post('/scheduled-sends')
async def schedule_message(request: Request, body: dict):
    return await request.app.state.scheduler.create(body, request.headers.get('authorization', ''))

@app.post('/scheduled-sends/cancel')
async def cancel_scheduled_message(request: Request, body: dict):
    return await request.app.state.scheduler.cancel(body.get('schedule_id', ''), request.headers.get('authorization', ''))

@app.get('/tg-groups')
@app.get('/sent-messages')
@app.get('/replies')
@app.get('/message-templates')
@app.get('/settings')
async def dashboard_page():
    return FileResponse(Path(__file__).resolve().parent / 'dist' / 'index.html', headers={'Cache-Control': 'no-cache'})

app.mount('/', StaticFiles(directory=str(Path(__file__).resolve().parent / 'dist'), html=True), name='dashboard')
