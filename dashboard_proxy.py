"""Serve the updated UI while leaving the existing WMM backend/data untouched.

Run this entrypoint on a NEW service. Do not replace the original backend service.
No Telegram sessions, dashboard keys or database records are stored here.
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

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
        yield

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
    return Response(result.content, status_code=result.status_code, headers={
        'Content-Type': result.headers.get('content-type', 'application/json'),
        'Cache-Control': 'no-store',
    })

app.mount('/', StaticFiles(directory=str(Path(__file__).resolve().parent / 'dist'), html=True), name='dashboard')
