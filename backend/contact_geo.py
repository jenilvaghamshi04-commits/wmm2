"""Country evidence and IANA-zone scheduling, without guessing a residence."""
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo
import pytz,phonenumbers

COUNTRIES=dict(pytz.country_names)
ALIASES={'UK':'GB','USA':'US','UAE':'AE','UNITED STATES OF AMERICA':'US','SOUTH KOREA':'KR','RUSSIA':'RU'}

def country_code(value):
    value=str(value or '').strip()
    if not value:return ''
    upper=value.upper();upper=ALIASES.get(upper,upper)
    if upper in COUNTRIES:return upper
    for code,name in COUNTRIES.items():
        if name.casefold()==value.casefold():return code
    raise ValueError('Choose a recognized country or leave it unknown.')

def phone_country(phone):
    if not phone:return ''
    try:
        number=phonenumbers.parse('+'+str(phone).lstrip('+'),None)
        if not phonenumbers.is_valid_number(number):return ''
        region=phonenumbers.region_code_for_number(number)
        return region if region in COUNTRIES else ''
    except phonenumbers.NumberParseException:return ''

def zone_name(value):
    value=str(value or '').strip()
    if not value:return ''
    if value not in pytz.all_timezones_set:raise ValueError('Choose an IANA timezone, such as Asia/Kolkata.')
    try:ZoneInfo(value)
    except Exception:raise ValueError('This timezone is unavailable on the server.')
    return value

def profile(data=None):
    data=data or {};country=data.get('country_override') or data.get('detected_country') or ''
    zones=list(pytz.country_timezones.get(country,[]));override=data.get('timezone_override') or ''
    zone=override or (zones[0] if len(zones)==1 else '')
    source=(data.get('override_source') or 'Manual entry') if data.get('country_override') else data.get('detected_source') or 'Unknown'
    return {'country_code':country,'country_name':COUNTRIES.get(country,'Unknown'),'country_source':source,'phone_country_code':data.get('detected_country',''),'phone_country_name':COUNTRIES.get(data.get('detected_country'),'Unknown'),'country_override':data.get('country_override',''),'timezone_override':override,'timezone':zone,'timezone_source':('Manual entry' if override else 'Inferred from country' if zone else 'Unknown'),'timezone_inferred':bool(zone and not override),'timezone_choices':zones,'needs_timezone':not bool(zone),'checked_at':data.get('checked_at',''),'observed_at':data.get('observed_at',''),'lookup_error':data.get('lookup_error','')}

def next_ten(not_before,zone):
    zone=ZoneInfo(zone);local=not_before.astimezone(zone)
    candidate=local.replace(hour=10,minute=0,second=0,microsecond=0)
    if candidate.astimezone(timezone.utc)<not_before.astimezone(timezone.utc):candidate=(local+timedelta(days=1)).replace(hour=10,minute=0,second=0,microsecond=0)
    return candidate.astimezone(timezone.utc)

def timing(first_at,location,now=None,days=3):
    now=now or datetime.now(timezone.utc)
    first=datetime.fromisoformat(first_at) if isinstance(first_at,str) else first_at
    eligible=first.astimezone(timezone.utc)+timedelta(days=days);zone=location.get('timezone')
    if not zone:return {'due_at':None,'eligible_at':eligible.isoformat(),'timezone':'','needs_timezone':True,'in_window':False,'next_available_at':None}
    due=next_ten(eligible,zone);local=now.astimezone(ZoneInfo(zone))
    ready=now>=due and local.hour==10
    # An interrupted service must wait for the next local morning instead of catching up at night.
    next_at=due if now<due else now if ready else next_ten(now,zone)
    return {'due_at':due.isoformat(),'eligible_at':eligible.isoformat(),'timezone':zone,'needs_timezone':False,'in_window':ready,'next_available_at':next_at.isoformat(),'send_time':'10:00','window_end':'11:00'}

def options():
    return {'countries':[{'code':code,'name':name,'timezones':list(pytz.country_timezones.get(code,[]))} for code,name in sorted(COUNTRIES.items(),key=lambda pair:pair[1])],'timezones':list(pytz.all_timezones)}
