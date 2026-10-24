> **Data-preserving dashboard deployment:** To use the new Sent Messages and Replies pages without redeploying your existing backend, deploy `dashboard_proxy.py` as a **separate** service using `dashboard-requirements.txt` and `render-dashboard.yaml`. See [DASHBOARD_DEPLOYMENT.md](DASHBOARD_DEPLOYMENT.md). Keep the current `wmm2` service running with its existing accounts and data.

# WMM Team — standalone TG Groups admins

An independent project with five workspace pages:

1. **TG Groups admins** — new-group monitoring, visible admin roles/titles, group dropdowns, account progress, editable delay, admin checkboxes, token/exchange fields, saved-template selection, individual message previews and reviewed batch sending.
2. **Message templates** — four message types, five editable options for each, nonrepeating shuffled cycles, token/exchange previews and automation preferences.
3. **Sent Messages** — confirmed recipients awaiting reply, original sender, sent/follow-up status, IST timestamps, history and reviewed follow-ups.
4. **Replies** — replied contacts are removed from Sent Messages and shown here for reviewed replies from the original Telegram account.
5. **Settings** — add accounts (one initially, up to three), enter Telegram API credentials, phone/QR login, code recovery, two-step verification, disconnect an account, and review/cancel queued messages.

The established WMM Telegram engine is included. It retains its authenticated API and supporting reply/follow-up workers; the separate frontend exposes the five pages above. No old WMM account, database, Site identity, API secret, live lead, or Telegram session is included. The current WMM site is not modified by this package.

## Run locally

Use Python 3.12 or later. From the extracted project folder:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copy the generated random value into `DASHBOARD_KEY` in `.env`. Set a separate `DASHBOARD_PASSWORD` if desired. Do not upload `.env`, `data/`, database files or Telegram session files to GitHub.

Start the full application:

```bash
python -m uvicorn backend.app:app --env-file .env --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. Sign in with `DASHBOARD_USERNAME` (default `admin`) and `DASHBOARD_PASSWORD`, or your `DASHBOARD_KEY` when no separate password is set. The Python server serves the frontend and API from one origin; no separate frontend build or gateway URL entry is needed. This is not a static-only app.

On Windows, activate the environment with `.venv\Scripts\activate` instead of `source ...`.

## Create your new GitHub and Render project

1. Create a **new** repository. Upload the contents of this folder, including `backend/`, `dist/`, `render.yaml` and `README.md`. Do not upload `.env` or runtime data.
2. Create a new Render **Web Service** connected to that repository. The included `render.yaml` can also be used as a Blueprint.
3. Build command: `pip install -r backend/requirements.txt`.
4. Start command: `python -m uvicorn backend.app:app --host 0.0.0.0 --port $PORT`.
5. Set a new `DASHBOARD_KEY` (Blueprint generates one), `DASHBOARD_USERNAME=admin`, and optionally a separate `DASHBOARD_PASSWORD`.
6. Open the new service URL. Everything runs from that URL; `SITE_ORIGIN` is only needed for a separately hosted frontend.

### Persistence matters

The included free Render example uses `/tmp/wmm-tg-admins-data`, which is temporary. It can lose records and Telegram sessions when the container is replaced or redeployed. For durable operation, use a host with persistent private storage and set `DATA_DIR` to its mounted directory. A persistent disk may require a paid hosting plan; this package does not create or purchase one. Run one server worker/instance against each DATA_DIR. Do not point two deployments at the same SQLite/Telegram session directory.

A refresh reloads saved server records; it does not clear the database. Issued browser sessions expire after 12 hours and can renew on restoration. Sign-out clears the browser session. Passwords, login codes and API hashes are not saved in browser storage.

## Connect Telegram and collect admins

1. Open **Settings**. Select Account 1.
2. Save a matching API ID and API Hash from the same app at https://my.telegram.org/apps.
3. Connect with QR from an already signed-in Telegram phone, or request a phone code and complete two-step verification when asked. Telegram determines delivery; alternate delivery is offered only when Telegram allows it.
4. Wait for **Watching for new groups** on TG Groups admins. Existing joined groups form a private exclusion baseline; their admins are not imported.
5. Join a new group in Telegram. The running backend checks about every five minutes. Or click **Add new group data**, choose a newly joined group, then **Get admins & archive**.
6. Only visible non-bot admins and actual custom titles are saved. Missing CEO/CTO/title data is not invented. After successful collection the same Telegram account archives the group; it remains a member.

## Templates and sending

Save at least one option for each of the four message types. Each type supports five options. Initial admin batches can choose a saved option first or use a shuffled cycle. Each distinct option is used before repeating.

Select 1–15 admins, choose the original sending account and delay (2, 5 or 10 minutes), enter token and exchange, then preview the exact messages. Only the explicit confirmation button queues them. A checkbox selection alone never sends. The first eligible message can send immediately; later messages honor the account's minimum gap. The queue is stored on the server and continues when the browser is closed **while the backend remains running**. Review or cancel pending messages in **Settings → Sending queue**.

`@username` uses the actual handle or display name, `$TOKEN`/`@TOKEN` use the chosen ticker, and `{{exchange}}` uses the chosen exchange. Already contacted/pending/uncertain recipients remain protected. Batch request IDs are retained on ambiguous failures; do not blindly create a new batch after a timeout.

The server retains the existing limits of **15 new DM recipients** and **30 group-message attempts** per Telegram identity per IST day. Repeat DMs do not use another new-contact slot. The exposed admin composer sends DMs, not group posts. Telegram waits, original sender, nonrepeating templates and uncertain-delivery protections stay in effect. Delays/limits never guarantee that Telegram will allow messages or prevent restrictions.

The template library retains affirmative-reply and follow-up types for the included automation engine. Saving a template alone does not enroll an admin batch into an automatic conversation sequence. This frontend exposes reviewed initial admin messaging; it does not add an inbox, Saved data, Sent messages, pipeline, Sheets import or account-health page.

## Project files

- `backend/app.py`: FastAPI service, Telegram accounts, persistence, quotas and workers.
- `backend/contact_geo.py`, `backend/contact_import.py`: supporting engine modules.
- `dist/index.html`: the five-page app and sign-in screen.
- `dist/standalone.js`: independent authentication, settings, templates and queue UI.
- `dist/group-admins.js`, `dist/admin-batch.js`: collection and reviewed batch workflow.
- `dist/workspace-polish.css`: the WMM design; `dist/standalone.css`: three-page layout adjustments.
- `.env.example`: local setup placeholders; `render.yaml`: separate service deployment example.

## Verification

The package includes backend regression tests using fake Telegram clients, plus frontend helper tests. Install `httpx` to run the backend tests:

```bash
pip install httpx
python -m unittest discover -s tests -p 'test_*.py' -q
node --test tests/test_*.cjs
```

No real Telegram login, admin extraction or message is performed by tests. Live code delivery and account restrictions can only be checked after deploying and connecting your own account.

Package validation: 306 backend tests passed. Both included frontend helper suites passed. Browser QA verified the three-page navigation, Settings controls, initial-message option selection and exact username/token/exchange preview with isolated fake records. Temporary QA pages are excluded from this archive.
