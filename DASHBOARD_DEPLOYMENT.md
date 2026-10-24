# Updated dashboard with existing accounts and records

The `wmm2` backend currently uses temporary storage. Redeploying it can lose
Telegram session files and records. This update therefore runs a **separate
dashboard service**, leaving the existing backend service and its configuration
unchanged.

## New dashboard service

- Repository: `jenilvaghamshi04-commits/wmm2`
- Branch: `feature/sent-messages-replies`
- Root directory: leave blank
- Python: `3.12.8`
- Build: `pip install -r dashboard-requirements.txt`
- Start: `python -m uvicorn dashboard_proxy:app --host 0.0.0.0 --port $PORT`
- Health check: `/dashboard-health`
- `WMM_BACKEND_ORIGIN=https://wmm2.onrender.com`
- Free compute plan; no disk or new Telegram credentials are needed here.

`render-dashboard.yaml` contains the same configuration. The original
`render.yaml` is for the original backend; do not use it for this dashboard.

The dashboard serves the updated static files and passes only its allowlisted
API requests to the existing backend. Authentication, sender ownership, reply
detection, nonrepeating templates, queue persistence and delivery checks stay
with that backend. The dashboard does not copy or initialize its database,
store Telegram sessions, change credentials, or retry message sends.

Sign in at the new dashboard URL with the **same existing workspace username
and password**. A new dashboard domain needs its own browser login, but does
not require reconnecting Telegram accounts. No message is sent until its exact
preview is confirmed with Queue follow-up or Queue reply.

## New pages

- **Sent Messages** lists confirmed DM recipients who have not replied. It
  shows original account, token/exchange, message/follow-up statuses, IST times,
  and saved message history. Follow-ups are reviewed individually and use the
  original sender. Existing account pacing is honored by the backend queue.
- **Replies** lists replied contacts and their recent incoming messages. They
  are excluded from Sent Messages. The composer supports custom responses and
  saved affirmative-reply templates, with an exact personalized preview.
- Both pages refresh with the existing ten-second status poll. Telegram event
  listeners and background checks remain on the original backend. An explicit
  Check replies action respects Telegram's existing cooldowns. Queued
  follow-ups recheck reply history and stop if a reply arrives before dispatch.

No database migration, account disconnect, reset, data import, or real message
send is performed by installing the dashboard.

The backend's original free-plan storage limitations still apply to future
backend restarts or redeployments. This dashboard does not make its temporary
storage durable. Back up and migrate the original backend to persistent storage
before any future deployment that restarts it. Never merge this branch into the
original backend's auto-deploy branch until that preservation step is complete.

## Separate pages and reviewed scheduling

- `/sent-messages` keeps recipients awaiting reply; `/replies` shows replied contacts.
- Page links survive refresh, sign-in and browser Back/Forward.
- The composer offers Queue now or Schedule for later, with explicit IST input.
- Schedules are limited to the current workspace sign-in (up to 12 hours), and recheck replies before submitting to the original sending queue.
- Schedules can be cancelled from Sent Messages. A reply cancels a pending scheduled follow-up.
- The dashboard must remain running. A schedule missed by more than 15 minutes waits for review rather than sending unexpectedly late.
- New schedule metadata uses temporary dashboard storage; free-host restarts or redeployments can clear it. No original backend records or Telegram sessions are moved.
- Session tokens used for a reviewed schedule stay only in process memory, never in the schedule database. Authentication expiry/restarts require signing in again; no authentication lifetime is extended by the scheduler.

## Pending Messages and black/lime branding

The `/pending-messages` page reads the original queue and dashboard schedules.
After a reviewed admin batch is queued, navigation opens this page. Each batch
shows its recipients, planned earliest IST send times, countdowns, status and
individual cancellation. Account pauses, disconnected senders, delivery errors
and recent failed UI requests appear in Queue issues. Timings are estimates,
not confirmation of sending; Sent is shown only after backend confirmation.
The UI now uses black surfaces and lime accents throughout. No original backend
files, Telegram account sessions, original queue entries or credentials change.
