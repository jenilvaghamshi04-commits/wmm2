import unittest,json,copy
from unittest.mock import patch
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
from fastapi import HTTPException
import test_gateway as gw
import test_auto_followups as af

class TemplateVariantTests(unittest.TestCase):
    setUp=gw.GatewayTests.setUp;tearDown=gw.GatewayTests.tearDown;load=gw.GatewayTests.load
    run_async=gw.GatewayTests.run_async;sender=gw.GatewayTests.sender;contact=gw.GatewayTests.contact
    original=af.AutomaticFollowupTests.original
    def pools(self):return {key:[f'{key} option {i+1} @username $TOKEN {{'+'{exchange}}' for i in range(5)] for key in self.app.TEMPLATE_KEYS}
    def store(self,pools=None):
        pools=pools or self.pools();self.run_async(self.app.save_templates(self.app.Templates(template='Initial',followup_template='Follow',template_variants=pools)));return pools
    def test_legacy_settings_migrate_to_option_one_without_changing_messages(self):
        self.run_async(self.app.save_templates(self.app.Templates(template='Existing introduction',followup_template='Existing follow-up')))
        cfg=self.app.settings();self.assertEqual(cfg['template_variants']['template'],['Existing introduction','','','','']);self.assertEqual(cfg['template_variants']['followup_template'][0],'Existing follow-up');self.assertEqual(cfg['yes_demo_template'],self.app.DEFAULT_YES_DEMO)
    def test_all_twenty_options_persist_after_reload(self):
        pools=self.store();self.app.db.close();self.load();self.assertEqual(self.app.settings()['template_variants'],pools)
        self.assertTrue(self.run_async(self.app.status())['features']['template_variants'])
    def test_empty_slots_allowed_but_blank_type_bad_count_unknown_type_oversize_rejected(self):
        pools=self.pools();pools['template']=['','Only active @username','','',''];self.store(pools);self.assertEqual(self.app.settings()['template'],'Only active @username')
        for mutation in [lambda p:p.update(template=['']*5),lambda p:p.update(template=['a']*6),lambda p:p.update(unknown=['a']*5),lambda p:p.update(template=['a'*4097,'','','',''])]:
            bad=self.pools();mutation(bad)
            with self.assertRaises(HTTPException):self.store(bad)
        self.assertEqual(self.app.settings()['template'],'Only active @username')
    def test_legacy_template_and_compose_updates_keep_four_alternates(self):
        pools=self.store();self.run_async(self.app.save_templates(self.app.Templates(template='Legacy edit',followup_template='Follow edit')))
        self.assertEqual(self.app.settings()['template_variants']['template'],['Legacy edit']+pools['template'][1:])
        self.run_async(self.app.config(self.app.Config(template='Compose edit',token_symbol='LF')))
        self.assertEqual(self.app.settings()['template_variants']['template'],['Compose edit']+pools['template'][1:]);self.assertEqual(self.app.settings()['template_variants']['yes_demo_template'],pools['yes_demo_template'])
    def test_sheet_settings_preserve_blank_first_option_and_all_five_pools(self):
        pools=self.pools();pools['template']=['','Second initial','','','Fifth initial'];self.store(pools)
        self.run_async(self.app.config(self.app.Config(sheet_url='https://docs.google.com/spreadsheets/d/test',sender_account=2)))
        self.assertEqual(self.app.settings()['template_variants'],pools);self.assertEqual(self.app.settings()['template'],'Second initial')
    def test_chooser_uses_only_nonempty_choices_of_requested_type(self):
        pools=self.pools();pools['template']=['','Initial two','','','Initial five'];self.store(pools)
        with patch.object(self.app.secrets,'choice',side_effect=lambda choices:choices[-1]) as pick:
            self.assertEqual(self.app.choose_template('template'),'Initial five');self.assertEqual(pick.call_args.args[0],['Initial two','Initial five'])
            self.assertEqual(self.app.choose_template('yes_demo_template'),pools['yes_demo_template'][4])
    def test_sheet_and_implicit_send_choose_per_recipient_and_personalize(self):
        pools=self.store();sender=self.sender()
        with patch.object(self.app.secrets,'choice',side_effect=lambda options:options[-1]):
            self.run_async(self.app.deliver(self.contact(1),token_symbol='LF',exchange='okx'))
            # Sheet sender reads the saved token. Keep this test's intro exchange-free.
            self.run_async(self.app.config(self.app.Config(template='Sheet one @username',token_symbol='LF')))
            cfg=self.app.settings();cfg['template_variants']['template']=['Sheet one @username','Sheet two @username','','',''];self.app.db.execute('insert or replace into settings values(1,?)',(json.dumps(cfg),));self.app.db.commit()
            self.run_async(self.app.sheet_send(self.app.SheetSend(id=self.contact(2))))
        self.assertEqual(sender.sent[0][1],'template option 5 Person 1 $LF OKX');self.assertEqual(sender.sent[1][1],'Sheet two Person 2');self.assertEqual(self.app.usage('101')['dm']['used'],2)
    def test_reviewed_manual_text_is_exact_and_never_rerolled(self):
        self.store();sender=self.sender()
        with patch.object(self.app.secrets,'choice',side_effect=AssertionError('A reviewed message must not reroll')):
            self.run_async(self.app.send(self.app.Send(id=self.contact(1),message='Reviewed option @username',token_symbol='LF')))
        self.assertEqual(sender.sent[0][1],'Reviewed option Person 1')
    def test_automatic_previews_are_validated_then_snapshotted_for_yes_once(self):
        pools=self.store();sender=self.sender();cid=self.contact(999)
        chosen={key:pools[key][3] for key in ('yes_pitch_template','yes_demo_template')}
        self.run_async(self.app.send(self.app.Send(id=cid,message='Reviewed initial',auto_yes=True,token_symbol='LF',exchange='okx',auto_reply_templates=chosen)))
        self.store({key:['Changed '+key,'','','',''] for key in pools})
        self.app.record_reply('101','999',1,SimpleNamespace(id=700,date=datetime.now(timezone.utc)+timedelta(seconds=1),raw_text='yes',out=False))
        with patch.object(self.app.secrets,'choice',side_effect=AssertionError('Already selected')):self.run_async(self.app.process_auto_yes());self.run_async(self.app.process_auto_yes())
        self.assertEqual([text for _,text in sender.sent[1:]],['yes_pitch_template option 4 Person 999 $LF OKX','yes_demo_template option 4 Person 999 $LF OKX'])
        self.assertEqual(self.app.usage('101')['dm']['used'],1)
    def test_automatic_no_does_not_choose_or_send_a_response(self):
        self.store();sender=self.sender();cid=self.contact(999)
        self.run_async(self.app.deliver(cid,message='Hi',auto_yes=True,token_symbol='LF',exchange='mexc'))
        self.app.record_reply('101','999',1,SimpleNamespace(id=700,date=datetime.now(timezone.utc)+timedelta(seconds=1),raw_text='no',out=False));self.run_async(self.app.process_auto_yes())
        self.assertEqual(len(sender.sent),1);self.assertNotIn('no_reply_template',self.app.settings()['template_variants'])
    def test_stale_or_unlisted_automatic_preview_cannot_send(self):
        self.store();sender=self.sender();cid=self.contact(1)
        bad={key:'Unexpected text' for key in ('yes_pitch_template','yes_demo_template')}
        with self.assertRaises(HTTPException) as caught:self.run_async(self.app.send(self.app.Send(id=cid,message='Hi',auto_yes=True,token_symbol='LF',exchange='okx',auto_reply_templates=bad)))
        self.assertEqual(caught.exception.status_code,409);self.assertEqual(sender.sent,[]);self.assertEqual(self.app.records(),[])
    def test_auto_followup_selection_is_saved_before_cooldown_and_kept_for_retry(self):
        self.store();self.original();real=self.app.deliver
        with patch.object(self.app.secrets,'choice',side_effect=lambda options:options[2]),patch.object(self.app,'deliver',side_effect=HTTPException(429,{'code':'send_cooldown','message':'Wait','next_available_at':(datetime.now(timezone.utc)+timedelta(seconds=120)).isoformat()})):
            self.run_async(self.app.process_auto_followups())
        chosen=self.app.db.execute('select body from auto_followup_jobs').fetchone()[0];self.assertEqual(chosen,'followup_template option 3 Person 999 $ABC MEXC');self.assertEqual(len(self.c.sent),1)
        self.store({key:['Later '+key,'','','',''] for key in self.app.TEMPLATE_KEYS});self.app.db.execute("update auto_followup_jobs set next_attempt_at=''");self.app.db.commit()
        with patch.object(self.app.secrets,'choice',side_effect=AssertionError('Prepared follow-up must not reroll')):self.run_async(self.app.process_auto_followups())
        self.assertEqual(self.c.sent[-1][1],chosen);self.assertEqual(len(self.c.sent),2)

if __name__=='__main__':unittest.main()
