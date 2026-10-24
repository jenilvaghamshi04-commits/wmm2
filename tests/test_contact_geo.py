import asyncio,json,unittest,copy
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
from unittest.mock import patch
from fastapi import HTTPException
from telethon import errors,functions
import phonenumbers
from backend import contact_geo as geo
import test_gateway as gw
from test_gateway import FakeClient

UTC=timezone.utc
def dt(value):return datetime.fromisoformat(value)
class GeographyTests(unittest.TestCase):
    def test_phone_country_is_not_residence_and_single_zone_inference(self):
        loc=geo.profile({'detected_country':'IN','detected_source':'Telegram phone country'})
        self.assertEqual(loc['country_name'],'India');self.assertEqual(loc['timezone'],'Asia/Kolkata');self.assertTrue(loc['timezone_inferred']);self.assertEqual(loc['country_source'],'Telegram phone country')
    def test_multizone_country_waits_for_explicit_zone(self):
        loc=geo.profile({'detected_country':'US'});self.assertFalse(loc['timezone']);self.assertTrue(loc['needs_timezone']);self.assertGreater(len(loc['timezone_choices']),1)
    def test_manual_timezone_can_override_phone_country_for_travel(self):
        loc=geo.profile({'detected_country':'IN','timezone_override':'Asia/Dubai'})
        self.assertEqual(loc['country_code'],'IN');self.assertEqual(loc['timezone'],'Asia/Dubai');self.assertFalse(loc['timezone_inferred'])
    def test_unknown_country_has_no_automatic_timezone_fallback(self):
        self.assertTrue(geo.profile()['needs_timezone']);self.assertFalse(geo.profile()['timezone'])
        self.assertEqual(geo.profile({'timezone_override':'Europe/London'})['country_name'],'Unknown')
    def test_names_codes_aliases_and_invalid_values(self):
        for value,code in [('India','IN'),('in','IN'),('USA','US'),('UK','GB'),('UAE','AE')]:self.assertEqual(geo.country_code(value),code)
        with self.assertRaises(ValueError):geo.country_code('unknownland')
        with self.assertRaises(ValueError):geo.zone_name('IST')
        with self.assertRaises(ValueError):geo.zone_name('../../etc/passwd')
    def test_public_phone_country_uses_valid_numbers_only(self):
        for code in ['IN','US','CA','GB']:
            number=phonenumbers.format_number(phonenumbers.example_number(code),phonenumbers.PhoneNumberFormat.E164)
            self.assertEqual(geo.phone_country(number),code)
        self.assertEqual(geo.phone_country('123'),'');self.assertEqual(geo.phone_country(None),'')
    def test_india_ten_am_half_hour_offset_and_72_hour_floor(self):
        loc=geo.profile({'detected_country':'IN'})
        schedule=geo.timing('2026-10-20T02:00:00+00:00',loc,dt('2026-10-23T04:29:59+00:00'))
        self.assertEqual(schedule['due_at'],'2026-10-23T04:30:00+00:00');self.assertFalse(schedule['in_window'])
        self.assertTrue(geo.timing('2026-10-20T02:00:00+00:00',loc,dt('2026-10-23T04:30:00+00:00'))['in_window'])
    def test_eligibility_after_ten_waits_next_morning(self):
        schedule=geo.timing('2026-10-20T06:00:00+00:00',geo.profile({'detected_country':'IN'}),dt('2026-10-23T06:01:00+00:00'))
        self.assertEqual(schedule['due_at'],'2026-10-24T04:30:00+00:00');self.assertFalse(schedule['in_window'])
    def test_missed_window_never_catches_up_at_night(self):
        loc=geo.profile({'detected_country':'IN'});s=geo.timing('2026-10-20T02:00:00+00:00',loc,dt('2026-10-23T17:00:00+00:00'))
        self.assertEqual(s['next_available_at'],'2026-10-24T04:30:00+00:00');self.assertFalse(s['in_window'])
        self.assertFalse(geo.timing('2026-10-20T02:00:00+00:00',loc,dt('2026-10-23T05:30:00+00:00'))['in_window'])
    def test_daylight_saving_spring_and_fall(self):
        for now,expected in [('2026-03-08T00:00:00+00:00','2026-03-08T14:00:00+00:00'),('2026-11-01T00:00:00+00:00','2026-11-01T15:00:00+00:00')]:self.assertEqual(geo.next_ten(dt(now),'America/New_York').isoformat(),expected)
    def test_quarter_hour_timezone_and_date_line(self):
        self.assertEqual(geo.next_ten(dt('2026-10-23T00:00:00+00:00'),'Asia/Kathmandu').isoformat(),'2026-10-23T04:15:00+00:00')
        self.assertEqual(geo.next_ten(dt('2026-10-23T00:00:00+00:00'),'Pacific/Auckland').isoformat(),'2026-10-23T21:00:00+00:00')
    def test_unknown_timing_is_held(self):
        self.assertIsNone(geo.timing('2026-10-20T00:00:00+00:00',geo.profile(),dt('2026-10-25T00:00:00+00:00'))['due_at'])

class CountryClient(FakeClient):
    def __init__(self,*a,country='IN',**kw):super().__init__(*a,**kw);self.country=country;self.country_calls=[];self.lookup_error=None
    async def __call__(self,request):
        self.country_calls.append(request)
        if self.lookup_error:raise self.lookup_error
        return SimpleNamespace(settings=SimpleNamespace(phone_country=self.country),users=[])
    async def get_messages(self,*a,**kw):return []

class CountryScheduleTests(unittest.TestCase):
    setUp=gw.GatewayTests.setUp;tearDown=gw.GatewayTests.tearDown;load=gw.GatewayTests.load
    run_async=gw.GatewayTests.run_async;contact=gw.GatewayTests.contact
    def setUp(self):
        gw.GatewayTests.setUp(self);self.app.followup_timing=self.real_followup_timing
        class Clock(datetime):
            current=dt('2026-10-23T05:00:00+00:00')
            @classmethod
            def now(cls,tz=None):return cls.current.astimezone(tz) if tz else cls.current.replace(tzinfo=None)
        self.clock=Clock;self.app.datetime=Clock
    def client(self,slot=1,user=101,country='IN'):
        c=CountryClient(user=user,country=country);self.app.clients[slot]=c;return c
    def set_location(self,cid,country='',zone=''):
        return self.run_async(self.app.update_location(self.app.LocationUpdate(contact_id=cid,country=country,timezone=zone)))
    def original(self,country='IN',zone='',now='2026-10-23T05:00:00+00:00'):
        self.clock.current=dt(now);self.c=self.client();self.cid=self.contact(999)
        if country or zone:self.set_location(self.cid,country,zone)
        self.run_async(self.app.deliver(self.cid,message='Hello',token_symbol='LF',exchange='okx'));self.root=self.app.records()[0]['delivery_id']
        self.app.db.execute('update outbox set at=? where id=?',('2026-10-20T02:00:00+00:00',self.root));self.app.db.commit()
    def process(self):return self.run_async(self.app.process_auto_followups())
    def test_country_lookup_is_read_only_cached_and_globally_throttled(self):
        c=self.client();cid=self.contact(1);other=self.contact(2)
        first=self.run_async(self.app.process_country_checks());second=self.run_async(self.app.process_country_checks())
        self.assertEqual((first['checked'],second['checked']),(1,0));self.assertEqual(len(c.country_calls),1);self.assertIsInstance(c.country_calls[0],functions.messages.GetPeerSettingsRequest)
        self.assertEqual(c.sent,[]);self.assertEqual(self.app.contacts()[1]['location']['country_name'],'India');self.assertNotIn('phone',self.app.geo_data('dm:1'));self.assertNotIn('phone_number',self.app.geo_data('dm:1'))
        self.clock.current+=timedelta(seconds=30);self.run_async(self.app.process_country_checks());self.assertEqual(len(c.country_calls),2)
    def test_manual_override_survives_lookup_and_rescan(self):
        self.client(country='US');cid=self.contact(1);self.set_location(cid,'India','Asia/Dubai');self.run_async(self.app.process_country_checks());self.contact(1)
        loc=self.app.location_for('dm:1');self.assertEqual(loc['country_name'],'India');self.assertEqual(loc['phone_country_code'],'US');self.assertEqual(loc['timezone'],'Asia/Dubai');self.assertEqual(loc['country_source'],'Manual entry')
    def test_missing_country_remains_unknown(self):
        self.client(country=None);self.contact(1);self.run_async(self.app.process_country_checks());self.assertTrue(self.app.location_for('dm:1')['needs_timezone'])
    def test_flood_wait_pauses_lookup_and_no_sender_switch(self):
        c=self.client();other=self.client(2,202);c.lookup_error=errors.FloodWaitError(None,capture=3600);self.contact(1)
        result=self.run_async(self.app.process_country_checks());self.assertFalse(result['results'][0]['ok']);self.assertEqual(other.country_calls,[])
        self.assertGreater(self.app.db.execute('select blocked_until from account_info where slot=1').fetchone()[0],self.app.stamp());self.assertEqual(c.sent,[])
    def test_lookup_stays_with_original_identity_after_slot_moves(self):
        self.original();old=self.c;self.app.clients[1]=CountryClient(user=202);self.app.clients[3]=old
        self.run_async(self.app.process_country_checks());self.assertEqual(len(old.country_calls),1);self.assertEqual(self.app.clients[1].country_calls,[])
    def test_auto_followup_sends_once_with_original_sender_at_local_ten(self):
        self.original();other=self.client(2,202);self.process();self.process()
        self.assertEqual(len(self.c.sent),2);self.assertEqual(other.sent,[]);self.assertEqual(self.app.auto_followup_summary('999')['status'],'Complete');self.assertEqual(self.app.usage('101')['dm']['used'],1)
    def test_before_ten_no_lookup_or_send_and_at_ten_sends(self):
        self.original(now='2026-10-23T04:29:59+00:00');self.process();self.assertEqual(len(self.c.sent),1)
        self.clock.current=dt('2026-10-23T04:30:00+00:00');self.process();self.assertEqual(len(self.c.sent),2)
    def test_unknown_or_multizone_wait_until_timezone_selected(self):
        self.original(country='US');self.process();self.assertEqual(len(self.c.sent),1);self.assertEqual(self.app.auto_followup_summary('999')['status'],'Needs timezone')
        self.set_location(self.cid,'US','America/New_York');self.clock.current=dt('2026-10-23T14:10:00+00:00');self.process();self.assertEqual(len(self.c.sent),2)
    def test_restart_at_night_moves_to_next_local_morning(self):
        self.original(now='2026-10-23T17:00:00+00:00');self.process();self.assertEqual(len(self.c.sent),1)
        self.assertEqual(self.app.db.execute('select next_attempt_at from auto_followup_jobs').fetchone()[0],'2026-10-24T04:30:00+00:00')
        self.clock.current=dt('2026-10-24T04:31:00+00:00');self.process();self.assertEqual(len(self.c.sent),2)
    def test_country_change_recalculates_due_time_and_keeps_body(self):
        self.original(now='2026-10-23T04:00:00+00:00');self.app.seed_auto_followups();self.app.db.execute("update auto_followup_jobs set body='Prepared body'");self.app.db.commit()
        self.set_location(self.cid,'GB','Europe/London');job=self.app.db.execute('select due_at,body from auto_followup_jobs').fetchone();self.assertEqual(job,('2026-10-23T09:00:00+00:00','Prepared body'))
    def test_reply_cancels_local_followup(self):
        self.original();self.app.record_reply('101','999',1,SimpleNamespace(id=800,date=self.clock.current,raw_text='No',out=False));self.process();self.assertEqual(len(self.c.sent),1);self.assertEqual(self.app.auto_followup_summary('999')['status'],'Cancelled')
    def test_last_second_window_race_rechecked_under_send_lock(self):
        self.original(now='2026-10-23T05:29:59+00:00');real=self.app.deliver
        async def raced(*a,**kw):self.clock.current=dt('2026-10-23T05:30:00+00:00');return await real(*a,**kw)
        with patch.object(self.app,'deliver',raced):self.process()
        self.assertEqual(len(self.c.sent),1);self.assertEqual(self.app.auto_followup_summary('999')['status'],'Waiting')
    def test_non_affirmative_reply_cancels_remaining_yes_response_part(self):
        self.app.enforce_send_pacing=self.real_pacing
        self.c=self.client();cid=self.contact(777)
        self.run_async(self.app.deliver(cid,message='Hello',token_symbol='LF',exchange='okx',auto_yes=True))
        self.app.record_reply('101','777',1,SimpleNamespace(id=900,date=self.clock.current,raw_text='yeh',out=False))
        self.clock.current+=timedelta(seconds=120);self.run_async(self.app.process_auto_yes());self.assertEqual(len(self.c.sent),2)
        self.app.record_reply('101','777',1,SimpleNamespace(id=901,date=self.clock.current+timedelta(seconds=1),raw_text='not now',out=False))
        self.clock.current+=timedelta(seconds=120);self.run_async(self.app.process_auto_yes())
        self.assertEqual(len(self.c.sent),2);self.assertEqual(self.app.auto_yes_summary('777',{'101'})['status'],'Cancelled')
    def test_rekey_import_preserves_location_and_profiles_show_in_every_record(self):
        self.c=self.client();cid=self.contact(1);self.set_location(cid,'IN');self.app.save({'id':'alias','user_id':'import:alice','name':'Alice','username':'alice_user','kind':'dm','import_unresolved':True})
        self.set_location('alias','GB','Europe/London');self.app.migrate_location('dm:import:alice','dm:99');self.assertEqual(self.app.location_for('dm:99')['timezone'],'Europe/London')
        self.run_async(self.app.deliver(cid,message='Hello'))
        status=self.run_async(self.app.status());self.assertEqual(status['contacts'][0]['location']['country_name'],'Unknown')
        self.assertEqual(status['deliveries'][0]['location']['country_name'],'India');self.assertEqual(next(l for l in status['leads'] if l['target']=='1')['location']['country_name'],'India')
    def test_import_country_timezone_columns_are_preserved(self):
        rows=[['Name','Telegram','Country','Timezone'],['Alice','@alice_user','India','Asia/Kolkata']];mapping,header=self.app.importer.default_mapping(rows)
        preview=self.run_async(self.app.preview_import(self.app.ImportPreview(rows=rows,mapping=mapping,has_header=header)))
        self.run_async(self.app.confirm_import(self.app.ImportConfirm(batch_id=preview['batch_id'])))
        loc=self.app.contacts()[0]['location'];self.assertEqual(loc['country_name'],'India');self.assertEqual(loc['timezone'],'Asia/Kolkata');self.assertEqual(loc['country_source'],'Spreadsheet import')
    def test_manual_overrides_require_auth_and_validate_zone(self):
        import httpx
        self.contact(1)
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app.app),base_url='http://test') as c:
                self.assertEqual((await c.get('/locations/options')).status_code,401)
                self.assertEqual((await c.post('/locations/check',json={})).status_code,401)
                bad=await c.post('/locations/update',headers={'Authorization':'Bearer test-secret'},json={'contact_id':'dm:1','country':'US','timezone':'IST'});self.assertEqual(bad.status_code,400)
        self.run_async(run())

if __name__=='__main__':unittest.main()
