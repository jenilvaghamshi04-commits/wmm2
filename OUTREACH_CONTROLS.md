# Sending protections

The Outreach controls page, permission form and server permission checks have been removed at the workspace owner's request. The old page URL redirects to Settings. Historical permission records are not deleted; they are no longer read or used as sending gates.

The dashboard gateway retains 10 unique recipients per account and 30 across the team per IST day, conservative attempt reservations, stable request receipts, duplicate and uncertain-delivery checks, original sender locking, and account restriction stops. Reviewed sending can be applied in Settings; unattended promotional sequences stay disabled on template saves. Scheduled messages recheck these protections when due.

These checks cover dashboard submissions, not the original backend's direct API or other Telegram clients. They do not remove Telegram restrictions or guarantee against bans. Keep durable storage and backups for both services; temporary storage can lose sessions, receipts and history. The original backend is not redeployed by this update.

Verify with `python -m unittest discover -s tests -p 'test_dashboard*.py'` and `node tests/test_outreach_controls.cjs` (jsdom required). Tests do not send Telegram messages.
