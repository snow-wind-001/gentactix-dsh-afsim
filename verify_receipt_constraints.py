"""Exact sustainment/reload feedback, using the strict guards' reference functions."""
import copy
import unittest
from unittest.mock import patch

from backend import effect_constraints as facts,turn_preview
from gentactix import support_dynamics as sd,fire_process as fp,missions
from tools.qa.turn_preview_page_fixture import session,candidate


class ReceiptConstraintTests(unittest.TestCase):
    def setUp(self):
        self.session=session();self.world=self.session['war_state']
        self.ctx=turn_preview.context(self.session,None,operation_id='receipt-qa')
        self.good=candidate(self.world)

    def paths(self,value,ctx=None):
        return {r['path']:r for r in facts.diagnose(ctx or self.ctx,value)['mismatches']}

    def test_failed_preview_batches_demand_for_every_unit_without_changing_inputs(self):
        value=copy.deepcopy(self.good)
        for row in value['sustainment_ledger']['units']:row['demand']=-1
        original=copy.deepcopy((self.ctx,value))
        reply=turn_preview.execute(self.ctx,dict(tool=turn_preview.TOOL,args=dict(candidate=value)))
        self.assertFalse(reply['ok']);paths={r['path']:r for r in reply['calculation_diagnostics']['mismatches']}
        for i,row in enumerate(self.good['sustainment_ledger']['units']):
            self.assertEqual(paths[f'/sustainment_ledger/units/{i}/demand']['expected'],row['demand'])
        self.assertEqual((self.ctx,value),original)

    def test_all_reference_receipt_fields_and_state_use_the_existing_expected_function(self):
        value=copy.deepcopy(self.good)
        row=value['sustainment_ledger']['units'][0]
        for key in sd.RECEIPT_FIELDS:row[key]=-1
        value['unit_updates'][0]['sustainment'].update(shortage_hours=99,noncombat_remainder=.7)
        value['unit_updates'][0]['personnel']={'noncombat_losses':99}
        with patch.object(sd,'expected',wraps=sd.expected) as expected:
            paths=self.paths(value)
        self.assertGreaterEqual(expected.call_count,22)
        for key in sd.RECEIPT_FIELDS:
            self.assertEqual(paths['/sustainment_ledger/units/0/'+key]['expected'],self.good['sustainment_ledger']['units'][0][key])
        self.assertEqual(paths['/unit_updates/0/sustainment/shortage_hours']['expected'],0)
        self.assertEqual(paths['/unit_updates/0/personnel/noncombat_losses']['expected'],self.world['red_units'][0]['personnel']['noncombat_losses'])
        self.assertNotIn('/unit_updates/0/formation/fatigue',paths)

    def test_receipt_row_reordering_does_not_change_identity_or_guess_indices(self):
        value=copy.deepcopy(self.good);value['sustainment_ledger']['units'].reverse()
        value['sustainment_ledger']['units'][0]['consumed']=-1
        row=self.paths(value)['/sustainment_ledger/units/0/consumed']
        self.assertEqual(row['unit'],value['sustainment_ledger']['units'][0]['unit'])
        self.assertEqual(row['expected'],self.good['sustainment_ledger']['units'][-1]['consumed'])

    def test_missing_and_duplicate_receipts_are_unavailable_without_inventing_rows(self):
        for kind in ('missing','duplicate'):
            value=copy.deepcopy(self.good)
            if kind=='missing':value.pop('sustainment_ledger')
            else:value['sustainment_ledger']['units'][1]['unit']=value['sustainment_ledger']['units'][0]['unit']
            result=facts.diagnose(self.ctx,value)
            self.assertTrue(result['unavailable'])
            if kind=='missing':self.assertFalse(any(r['path'].startswith('/sustainment_ledger/') for r in result['mismatches']))
            else:self.assertFalse(any(r['path'].startswith('/sustainment_ledger/units/0/') for r in result['mismatches']))

    def test_scheduled_reference_is_used_and_invalid_schedule_never_falls_back(self):
        from verify_supply_schedule import world,model_proposal
        w=world();s={**self.session,'war_state':w,'time_step':'6小时'}
        ctx=turn_preview.context(s,None,operation_id='scheduled-receipt-qa');value=model_proposal(w)
        value['sustainment_ledger']['units'][0]['consumed']=2
        self.assertEqual(self.paths(value,ctx)['/sustainment_ledger/units/0/consumed']['expected'],20)
        value.pop('supply_schedule_ledger');result=facts.diagnose(ctx,value)
        self.assertTrue(result['unavailable'])
        self.assertFalse(any(r['path'].startswith('/sustainment_ledger/') for r in result['mismatches']))

    def fire_fixture(self):
        from verify_fire_process import FireProcessTests
        test=FireProcessTests();test.setUp();value=test.shot()
        s={**self.session,'war_state':test.world,'time_step':'30分钟'}
        return test,turn_preview.context(s,None,operation_id='reload-qa'),value

    def test_fired_reload_and_unit_state_share_strict_reference_clock(self):
        test,ctx,value=self.fire_fixture();value['fire_ledger']['units'][0]['reload_remaining_s']=886
        value['unit_updates'][0]['formation']['reload_remaining_s']=886
        original=copy.deepcopy((ctx,value))
        with patch.object(fp,'reload_after',wraps=fp.reload_after) as reference:
            paths=self.paths(value,ctx)
        self.assertTrue(reference.called)
        for path in ['/fire_ledger/units/0/reload_remaining_s','/unit_updates/0/formation/reload_remaining_s']:
            self.assertEqual(paths[path]['expected'],30)
        self.assertEqual((ctx,value),original)
        with self.assertRaisesRegex(ValueError,'期末装填'):test.apply(value,require_fire_ledger=True)

    def test_passive_cooldown_reports_seconds_without_faking_ground_fire(self):
        w=copy.deepcopy(self.world);w['red_units'][0]['formation'].update(reload_remaining_s=60,reload_remaining=60)
        s={**self.session,'war_state':w};ctx=turn_preview.context(s,None,operation_id='passive-qa')
        value=candidate(w);value['unit_updates'][0]['formation'].pop('reload_remaining_s',None)
        paths=self.paths(value,ctx)
        self.assertEqual(paths['/unit_updates/0/formation/reload_remaining_s']['expected'],0)
        self.assertFalse(any(path.startswith('/fire_ledger/') for path in paths))
        self.assertNotIn('fire_ledger',value)

    def test_shared_clock_keeps_passive_precision_but_truncates_ground_fire_remainder(self):
        from gentactix import combat_effects
        _,ctx,value=self.fire_fixture();w=ctx['session']['war_state'];unit=w['red_units'][0];ref=combat_effects.reference(w)
        row=value['fire_ledger']['units'][0];row['last_fire_s']=1710.75
        self.assertEqual(fp.reload_after(w,unit,1800,row=row,reference=ref),30)
        unit['formation']['reload_remaining_s']=1800.75
        self.assertEqual(fp.reload_after(w,unit,1800,reference=ref),.75)

    def test_zero_shot_and_legacy_count_follow_existing_reload_clock(self):
        from gentactix import combat_effects
        _,ctx,value=self.fire_fixture();w=ctx['session']['war_state'];u=w['red_units'][0];ref=combat_effects.reference(w)
        u['formation'].pop('reload_remaining_s',None);u['formation']['reload_remaining']=10
        expected=max(0,10*ref['artillery_cycle_s']-900)
        self.assertEqual(fp.reload_after(w,u,900,reference=ref),expected)
        row=value['fire_ledger']['units'][0];row.update(fire_cycles=0,first_fire_s=None,last_fire_s=None,active_fire_s=0,stop_reason='reload_pending')
        self.assertEqual(fp.reload_after(w,u,900,row=row,reference=ref),int(expected))

    def test_missing_or_invalid_fire_dependencies_are_unavailable_not_guessed(self):
        for kind in ('missing','target','last','boolean'):
            _,ctx,value=self.fire_fixture()
            if kind=='missing':value.pop('fire_ledger')
            else:
                row=value['fire_ledger']['units'][0]
                if kind=='target':row['target']='unknown'
                if kind=='last':row['last_fire_s']=1800
                if kind=='boolean':row['fire_cycles']=True
            result=facts.diagnose(ctx,value)
            self.assertTrue(result['unavailable'],kind)
            self.assertFalse(any(r['path'].startswith('/fire_ledger/units/0/reload_remaining_s') for r in result['mismatches']),kind)

    def test_legacy_sustainment_does_not_gain_time_receipts_and_good_candidate_is_unchanged(self):
        _,ctx,value=self.fire_fixture();result=facts.diagnose(ctx,value)
        self.assertFalse(any(r['path'].startswith('/sustainment_ledger/') for r in result['mismatches']))
        saved=copy.deepcopy((ctx,value));facts.diagnose(ctx,value);self.assertEqual((ctx,value),saved)

    def test_diagnostics_never_call_the_effect_executor(self):
        from backend import dsh_simulation
        with patch.object(dsh_simulation,'apply',side_effect=AssertionError('No executor')):
            result=facts.diagnose(self.ctx,self.good)
        self.assertEqual(result['mismatches'],[])

    def test_positive_noncombat_reference_is_cumulative_and_does_not_apply_losses(self):
        from verify_support_dynamics import world
        from verify_dsh_resources import model_result
        w=world(0,'1小时');u=w['red_units'][0]
        u['sustainment'].update(shortage_hours=49,noncombat_remainder=.99)
        receipt=sd.expected(sd.configuration(w),u,'hold',3600)
        self.assertGreater(receipt['noncombat_delta'],0)
        s={**self.session,'war_state':w};ctx=turn_preview.context(s,None,operation_id='shortage-qa')
        value=model_result(w);value['sustainment_ledger']={'version':sd.VERSION,'units':[]}
        for _,unit in missions.units(w):
            wanted=sd.expected(sd.configuration(w),unit,'hold',3600)
            value['sustainment_ledger']['units'].append(dict(unit=unit['name'],**wanted))
        prior=copy.deepcopy((ctx,value));paths=self.paths(value,ctx)
        self.assertEqual(paths['/unit_updates/0/personnel/noncombat_losses']['expected'],u['personnel']['noncombat_losses']+receipt['noncombat_delta'])
        self.assertEqual((ctx,value),prior)

    def test_zero_shot_explicit_seconds_are_required_even_if_legacy_value_matches(self):
        _,ctx,value=self.fire_fixture();row=value['fire_ledger']['units'][0]
        row.update(fire_cycles=0,first_fire_s=None,last_fire_s=None,active_fire_s=0,reload_remaining_s=0,stop_reason='uncertain')
        value['unit_updates'][0]['formation'].pop('reload_remaining_s')
        actual=self.paths(value,ctx)['/unit_updates/0/formation/reload_remaining_s']
        self.assertEqual(actual['expected'],0);self.assertFalse(actual['present'])


if __name__=='__main__':unittest.main()
