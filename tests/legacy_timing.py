"""Keep pre-timezone regression tests focused on their original features.
The real country/time-window scheduler has independent clock-based integration tests.
"""
from datetime import datetime,timezone,timedelta

def isolate_scheduler(app):
    def timing(first,location,now=None,days=3):
        now=now or app.datetime.now(timezone.utc);first=datetime.fromisoformat(first) if isinstance(first,str) else first
        due=first+timedelta(days=days)
        return {'due_at':due.isoformat(),'eligible_at':due.isoformat(),'timezone':'UTC','needs_timezone':False,'in_window':now>=due,'next_available_at':due.isoformat()}
    app.followup_timing=timing
