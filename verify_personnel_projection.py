"""Known personnel accounts, not legacy HP, determine the displayed strength."""
import copy
import json
from pathlib import Path
import subprocess
import unittest


class PersonnelProjectionTests(unittest.TestCase):
    def test_v3_preview_and_report_proof_survive_actual_javascript_json_transport(self):
        from verify_dsh_output_recovery import FinalJSONRecoveryTests
        from backend import turn_preview
        f=FinalJSONRecoveryTests();f.setUp()
        try:
            before=copy.deepcopy(f.s)
            ctx=turn_preview.context(f.s,None,operation_id=f.observer.operation_id)
            final=f.preview(ctx)
            event=f.observer.runs[-1]['events'][1]
            block=event['message']['content'][0]
            node=subprocess.run(['node','-e',
                "let raw='';process.stdin.setEncoding('utf8');process.stdin.on('data',x=>raw+=x);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(raw))));"],
                input=block['text'],text=True,capture_output=True)
            self.assertEqual(node.returncode,0,node.stderr)
            block['text']=node.stdout
            value,proof=turn_preview.resolve(final,f.observer,ctx)
            self.assertEqual(proof['settlement_version'],'turn-settlement-3')
            self.assertEqual(value['unit_updates'],f.value['unit_updates'])
            self.assertEqual(f.s,before)
        finally:f.tearDown()

    def test_old_noncanonical_v3_digest_is_rejected_rather_than_repaired(self):
        from verify_dsh_output_recovery import FinalJSONRecoveryTests
        from backend import turn_preview
        from gentactix import missions
        f=FinalJSONRecoveryTests();f.setUp()
        try:
            ctx=turn_preview.context(f.s,None,operation_id=f.observer.operation_id)
            final=f.preview(ctx);block=f.observer.runs[-1]['events'][1]['message']['content'][0]
            reply=json.loads(block['text'])
            for row in reply['settlement']['units']:
                if row['personnel_strength_pct'] is not None:row['personnel_strength_pct']=float(row['personnel_strength_pct'])
            reply['settlement_hash']=missions.digest(reply['settlement'])
            value=turn_preview.normalize(ctx,f.value)
            reply['digest']=turn_preview._digest(ctx,value,reply['after_hash'],reply['settlement_hash'])
            final['preview_hash']=reply['digest']
            for row in reply['settlement']['units']:
                v=row['personnel_strength_pct']
                if isinstance(v,float) and v.is_integer():row['personnel_strength_pct']=int(v)
            block['text']=json.dumps(reply)
            with self.assertRaisesRegex(ValueError,'指纹'):
                turn_preview.resolve(final,f.observer,ctx)
        finally:f.tearDown()

    def test_existing_v2_native_preview_proof_stays_resumable_with_exact_old_digest(self):
        from verify_dsh_output_recovery import FinalJSONRecoveryTests
        from backend import turn_preview,dsh_simulation
        from gentactix import reporting,turn_settlement,missions
        from unittest.mock import patch
        f=FinalJSONRecoveryTests();f.setUp()
        try:
            ctx=turn_preview.context(f.s,None,operation_id=f.observer.operation_id)
            with patch.object(turn_settlement,'VERSION',turn_settlement.LEGACY_VERSION):final=f.preview(ctx)
            _,proof,summary=turn_preview._resolve_preview(final['preview_hash'],f.observer,ctx)
            self.assertEqual(summary['version'],'turn-settlement-2');self.assertNotIn('settlement_version',proof)
            self.assertNotIn('fatigue',summary['units'][0])
            after=dsh_simulation.apply(f.s['war_state'],f.value,f.s['time_step'],require_fire_ledger=True)
            self.assertEqual(missions.digest(reporting.turn_settlement_summary(after,f.s['war_state'],version='turn-settlement-2')),proof['settlement_hash'])
            with patch.object(dsh_simulation.h,'get_ai_response',return_value=final):
                result,_,_=dsh_simulation.advance(f.s,None,f.observer)
            self.assertEqual(result['updated_state'],after)
        finally:f.tearDown()

    def test_native_preview_returns_validated_strength_and_fatigue_without_new_tools(self):
        from verify_dsh_output_recovery import FinalJSONRecoveryTests
        from backend import turn_preview
        from gentactix import personnel_projection as p
        f=FinalJSONRecoveryTests();f.setUp()
        try:
            ctx=turn_preview.context(f.s,None,operation_id=f.observer.operation_id)
            before=copy.deepcopy(f.s)
            reply=turn_preview.execute(ctx,dict(tool=turn_preview.TOOL,args=dict(candidate=f.value)))
            self.assertTrue(reply['ok'],reply)
            row=reply['settlement']['units'][0];u=f.s['war_state']['red_units'][0]
            self.assertEqual(row['personnel_strength_pct'],p.strength_pct(u))
            self.assertEqual(row['fatigue'],u['formation']['fatigue']);self.assertEqual(f.s,before)
        finally:f.tearDown()

    def test_actual_grouped_fatigue_error_is_rejected_and_original_text_preserved(self):
        from gentactix import reporting
        w=dict(red_units=[dict(name=name,formation=dict(fatigue=value)) for name,value in [('第90师',36),('第160师',35),('第159师',35)]],blue_units=[])
        text='连续机动使推进部队疲劳明显上升（第90师、第160师升至36，第159师35）。'
        before=copy.deepcopy(w);display,audit=reporting.render(text,w,turn=1)
        self.assertEqual(audit['status'],'fallback');self.assertEqual(audit['original_text'],text)
        self.assertTrue(any(i['code']=='fatigue_value' for i in audit['issues']))
        self.assertNotIn(text,display);self.assertIn('疲劳35',display);self.assertEqual(w,before)

    def test_exact_fatigue_current_claims_do_not_swallow_other_times_or_unknown_aliases(self):
        from gentactix import reporting
        w=dict(red_units=[dict(name='第160师',formation=dict(fatigue=35))],blue_units=[])
        for text in ('第160师疲劳为35。','下一轮第160师疲劳为36。',
                     '轮初疲劳列表（第160师36）。','疲劳记录（第160师补给指数36）。'):
            with self.subTest(text=text):
                self.assertFalse(any(i['code']=='fatigue_value' for i in reporting.inspect(text,w)))
        self.assertTrue(any(i['code']=='fatigue_value' for i in reporting.inspect('第160师疲劳为36。',w)))

    def test_actual_7935_of_8000_is_not_full_strength_and_never_changes_raw_hp(self):
        from gentactix import personnel_projection as p
        unit=dict(hp=100,personnel=dict(current=7935,committed=8000));before=copy.deepcopy(unit)
        self.assertEqual(p.strength_pct(unit),99.19)
        self.assertEqual(unit,before)

    def test_native_even_ties_and_invalid_unknown_accounts(self):
        from gentactix import personnel_projection as p
        self.assertEqual(p.strength_pct(dict(personnel=dict(current=1,committed=32))),3.12)
        self.assertEqual(p.strength_pct(dict(personnel=dict(current=107,committed=4000))),2.68)
        for counts in ({},{'current':None,'committed':8000},{'current':True,'committed':10},
                       {'current':11,'committed':10},{'current':1,'committed':0},
                       {'current':float('nan'),'committed':10},{'current':1.5,'committed':10}):
            with self.subTest(counts=counts):self.assertIsNone(p.strength_pct(dict(hp=100,personnel=counts)))
        self.assertEqual(p.strength_pct(dict(personnel=dict(current=1.0,committed=10.0))),10)

    def test_personnel_controls_inactive_marker_with_legacy_hp_fallback(self):
        from gentactix import personnel_projection as p
        for unit,expected in [(dict(hp=100,personnel=dict(current=0,committed=10)),True),
                              (dict(hp=0,personnel=dict(current=5,committed=10)),False),
                              (dict(hp=0),True),(dict(hp=100),False)]:
            with self.subTest(unit=unit):self.assertEqual(p.inactive(unit),expected)

    def test_program_facts_use_named_personnel_projection_without_rewriting_legacy_world(self):
        from gentactix import reporting
        w=dict(red_units=[dict(name='测试投入部',hp=100,personnel=dict(current=7935,committed=8000,casualties=65,noncombat_losses=0))],blue_units=[])
        before=copy.deepcopy(w);text=reporting.facts(w)
        self.assertIn('人员保有率99.19%',text)
        self.assertIn('非编制满员率',text);self.assertNotIn('HP 100',text);self.assertEqual(w,before)
        self.assertIn('HP 42',reporting.facts(dict(red_units=[dict(name='旧单位',hp=42)],blue_units=[])))
        w['red_units'][0]['formation']='旧记录未载'
        self.assertIn('人员保有率99.19%',reporting.facts(w))

    def test_normal_command_and_native_and_main_observation_share_readonly_value(self):
        from backend import afsim_state,dsh_simulation
        from gentactix import commands,historical_operations as ho
        from tools.qa.historical_operational_fixture import inputs
        world=ho.initial(*inputs());u=world['red_units'][0];u['personnel'].update(current=5993,casualties=7)
        session=dict(id='personnel-projection-qa',war_state=world,turn_count=0,time_step='30分钟',
            execution_backend='narrative',product_mode='historical',simulation_mode='open')
        before=copy.deepcopy(session)
        native=afsim_state.observation(session,dict(limit=16))
        row=next(r for r in native['units'] if r['name']==u['name'])
        self.assertEqual(row['personnel_strength_pct'],99.88)
        command=next(r for r in commands.view(session)['units'] if r['name']==u['name'])
        self.assertEqual(command['personnel_strength_pct'],99.88)
        view=dsh_simulation.observation_view(world)
        self.assertEqual(view['red_units'][0]['personnel_strength_pct'],99.88)
        self.assertEqual(session,before);self.assertEqual(world['red_units'][0]['hp'],100)

    def test_military_symbols_do_not_show_dead_personnel_as_active(self):
        from gentactix import military_symbols as m
        dead=dict(name='损失耗尽',type='步兵',hp=100,personnel=dict(current=0,committed=10))
        self.assertIn('unit-inactive',m.unit_html(dead,'red'))
        alive={**dead,'hp':0,'personnel':dict(current=5,committed=10)}
        self.assertIn('unit-active',m.unit_html(alive,'red'))

    def test_optional_geometry_uses_personnel_sot_without_changing_legacy_hp(self):
        from gentactix import adjudicator as adj
        dead=dict(name='损失耗尽',type='步兵',lat=29,lng=115,hp=100,personnel=dict(current=0,committed=10))
        alive={**dead,'name':'仍有人员','hp':0,'personnel':dict(current=5,committed=10)}
        world=dict(red_units=[dead,alive],blue_units=[]);before=copy.deepcopy(world)
        units,skipped=adj._collect_units(world)
        self.assertEqual([u['name'] for u in units],['仍有人员']);self.assertEqual(units[0]['hp'],50)
        self.assertEqual(adj.unit_control_radius_km(dead),0);self.assertGreater(adj.unit_control_radius_km(alive),0)
        self.assertEqual(world,before)

    def test_frontend_uses_same_rounding_popup_and_inactive_semantics(self):
        from gentactix import personnel_projection as p
        values=[dict(name='账本部队',type='步兵',hp=100,personnel=dict(current=7935,committed=8000)),
            dict(hp=100,personnel=dict(current=0,committed=10)),dict(hp=0,personnel=dict(current=5,committed=10)),
            dict(hp=100,personnel=dict(current=1,committed=32)),dict(hp=100,personnel=dict(current=107,committed=4000)),dict(name='旧部队',hp=42),dict(hp='0'),dict(hp='NaN')]
        run=subprocess.run(['node','tools/qa/personnel_projection_contract.mjs'],input=json.dumps(values),text=True,capture_output=True)
        self.assertEqual(run.returncode,0,run.stderr);rows=json.loads(run.stdout)
        self.assertEqual([r['percent'] for r in rows],[p.strength_pct(u) for u in values])
        self.assertEqual([r['inactive'] for r in rows],[p.inactive(u) for u in values])
        self.assertIn('人员保有率',rows[0]['popup']);self.assertIn('99.19%',rows[0]['popup'])
        self.assertNotIn('HP:',rows[0]['popup']);self.assertIn('unit-inactive',rows[1]['symbol'])
        self.assertIn('HP:',rows[5]['popup'])


if __name__=='__main__':unittest.main()
