# Dashboard outreach controls

This feature reduces outreach risk; it does not guarantee Telegram account availability or remove restrictions.

- `/outreach-controls` records genuine permission, its source/date/scope, and the sending account. No existing contacts are automatically marked eligible.
- Gateway submission checks enforce 10 unique recipients per account and 30 across the team per IST day. Attempts, uncertain submissions, follow-ups and active older queue rows reserve capacity conservatively. There is no manual cap reset.
- New outreach requires permission; an incoming reply may be answered in its original confirmed conversation unless opted out. Restrictions, account errors, pending/uncertain deliveries and cross-account duplicate outreach block submission.
- Batch validation is atomic. Stable request receipts prevent repeated submission, including after an unknown network result.
- Scheduled follow-ups/replies are revalidated when created and when due. An elapsed local pause does not establish spam clearance.
- Reviewed mode disables global automatic promotional reply/follow-up sequences through the existing templates API. Existing template contents and variants are preserved. An empty initial template must be configured before activating this mode. The gateway forces these automation flags off on subsequent template saves.
- These checks cover this dashboard's queue and schedule entry points. Direct use of the original backend, Telegram clients, or previously queued backend work is outside this gateway. Review/cancel pending work before changing permission; do not use other clients to bypass restrictions.

## Storage and deployment

The existing backend is not redeployed or migrated by this update. Its sessions and records are not copied into the dashboard. Permission notes and conservative submission receipts share `DASHBOARD_SCHEDULE_DIR/schedules.db`, without credentials. Tokens remain in RAM. Both the original backend DATA_DIR and this directory require durable storage and backups for production; default `/tmp` storage can disappear on host replacement/redeploy. Missing permission records block new outreach by default. Do not represent a free ephemeral deployment as durable or a record of Telegram clearance.

## Verification

Run `python -m unittest discover -s tests -p 'test_dashboard*.py'` with dashboard dependencies installed. `node tests/test_outreach_controls.cjs` requires jsdom on NODE_PATH. Tests use mocked backend calls and never send Telegram messages.
