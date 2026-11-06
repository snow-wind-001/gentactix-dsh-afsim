"""Source-bound Xiangjiang local phases; missing facts never become deployments."""
import copy
import unittest
from unittest.mock import patch
from gentactix import historical_initial as hi,historical_operations as ho,combat_effects

BATTLE='红军长征-湘江战役-1934.11.25至1934.12.01'
PROFILE='LM01-xiangjiang'
XINXU='xinxu_nov28'
GUANGHUA='guanghuapu_nov30_morning'

class XiangjiangInitialTests(unittest.TestCase):
    def snapshot(self,phase=XINXU):return hi.initial(BATTLE,phase)['historical_initial']

    def test_catalog_exposes_partial_factual_profile_without_certifying_history(self):
        d=hi.definition(BATTLE);self.assertEqual(d['id'],PROFILE);hi.validate_definition(d)
        self.assertFalse(any(d['coverage'][k] for k in ('order_of_battle_complete','opening_deployment_complete','strength_complete')))
        self.assertFalse(hi.readiness(hi.initial(BATTLE))['ready_for_process_simulation'])

    def test_reference_roster_is_not_simultaneous_opening_deployment(self):
        s=hi.initial(BATTLE)['historical_initial'];self.assertEqual(s['phase_id'],'campaign_reference')
        with self.assertRaises(ValueError):ho.partition(s)

    def test_xinxu_first_day_binds_two_actual_regiments_and_attached_artillery(self):
        self.assertEqual(set(ho.partition(self.snapshot())),{'lm.red.regiment14','lm.red.regiment15',
            'lm.red.cmc_artillery_battalion','lm.gx.division44'})

    def test_later_reinforcements_and_detached_regiment_are_not_deployed_early(self):
        s=self.snapshot();units={u['id']:u for u in s['definition']['units']}
        for identity in ('lm.gx.division24','lm.gx.division45','lm.red.regiment18'):
            row=next(r for r in units[identity]['presence'] if r['phase_id']==XINXU)
            self.assertEqual(row['status'],'later_participant')
        self.assertEqual(next(r['status'] for r in units['lm.red.regiment13']['presence'] if r['phase_id']==XINXU),'outside_scope')

    def test_guanghuapu_does_not_mix_xinxu_or_afternoon_relief(self):
        self.assertEqual(set(ho.partition(self.snapshot(GUANGHUA))),{'lm.red.regiment10','lm.gx.division43'})
        self.assertNotIn('lm.red.division4',ho.partition(self.snapshot(GUANGHUA)))
        self.assertNotIn('lm.red.regiment14',ho.partition(self.snapshot(GUANGHUA)))

    def test_unknown_numerics_and_positions_stay_unknown_in_shared_facts(self):
        for p in (XINXU,GUANGHUA):
            s=self.snapshot(p);t=ho.configuration_template(s)
            self.assertEqual(t['rules']['era'],'long_march');self.assertFalse(t['rules']['motorized']);self.assertFalse(t['rules']['air_support'])
            for identity,a in t['actors'].items():
                self.assertIsNone(a['personnel']);self.assertEqual(a['position'],{'lat':None,'lng':None})
                self.assertTrue(all(v is None for v in a['equipment'].values()))
            for u in s['definition']['units']:
                for fact in u['facts'].values():self.assertIsNone(fact['value'])

    def test_three_purposes_and_both_engines_freeze_the_same_source_definition(self):
        baseline=hi.initial(BATTLE,XINXU)
        for purpose in ('analysis','historical','synthetic'):
            for engine in ('afsim','narrative'):self.assertEqual(hi.initial(BATTLE,XINXU,purpose=purpose,engine=engine),baseline)
        with patch.object(hi,'definition',side_effect=AssertionError('Frozen facts cannot consult latest index')):
            self.assertEqual(hi.restore(copy.deepcopy(baseline['historical_initial'])),baseline)

    def test_default_configuration_discloses_selected_local_phase(self):
        from backend.scenario_builder import historical_basis
        v=historical_basis(BATTLE);self.assertTrue(v['ready']);self.assertEqual(v['initial']['phase_id'],XINXU)
        self.assertIn('默认选择',v['scope']);self.assertEqual(set(v['configuration_template']['actors']),set(ho.partition(self.snapshot())))

    def test_guidance_preserves_defensive_task_and_explicit_missing_mechanisms(self):
        for p in (XINXU,GUANGHUA):
            g=ho.objective_guidance(self.snapshot(p));self.assertIsNotNone(g)
            self.assertEqual((g['team'],g['profile']),('red','delay'));self.assertTrue(g['not_covered'])

    def test_explicit_inputs_bind_without_teaching_fallback_and_reject_wrong_stage(self):
        from tools.qa.xiangjiang_fixture import inputs
        for phase in (XINXU,GUANGHUA):
            s,p=inputs(phase)
            with patch('gentactix.combined_arms.definition',side_effect=AssertionError('No CA fallback')):
                w=ho.initial(s,p);self.assertEqual(w['historical_initial'],s)
                self.assertEqual(len(w['red_units'])+len(w['blue_units']),len(ho.partition(s)))
                for when in ('1934-11-27 06:00','1934-11-29 06:00' if phase==XINXU else '1934-11-30 18:00'):
                    bad=copy.deepcopy(p);bad['clock']['start']=when
                    with self.assertRaises(ValueError):ho.initial(s,bad)

    def test_historical_loss_references_keep_subunit_scope_and_no_hourly_quota(self):
        b=combat_effects.benchmark(BATTLE)
        rows=[r for r in b['figures'] if r.get('unit_id')=='lm.red.regiment10']
        self.assertTrue(rows);self.assertEqual(rows[0]['value'],400)
        self.assertIn('伤亡',rows[0]['metric']);self.assertIn('不是阵亡',rows[0]['note'])
        self.assertFalse(b['force_historical_outcome'])
        all_casualties=next(r for r in b['figures'] if r['metric']=='战斗伤亡合计' and r['side']=='红军')
        self.assertIsNone(all_casualties['value'])

    def test_same_id_observation_reference_does_not_assign_parent_losses_to_regiments(self):
        from tools.qa.xiangjiang_fixture import inputs
        s,p=inputs(GUANGHUA);w=ho.initial(s,p);refs=combat_effects.observation(w)['unit_references']
        self.assertEqual(combat_effects.observation(w)['fire_stop_reasons']['6'],combat_effects.FIRE_STOPS[6])
        r=next(r for r in refs if r['historical_unit_id']=='lm.red.regiment10')
        self.assertIsNone(r['committed_approx']);self.assertFalse(r['hourly_rate_available'])
        self.assertIsNone(r['duration_hours']);self.assertIn('400',r['metric_summary'])
        s,p=inputs(XINXU);w=ho.initial(s,p);ref_ids={r['historical_unit_id'] for r in combat_effects.observation(w)['unit_references']}
        self.assertNotIn('lm.red.regiment14',ref_ids);self.assertNotIn('lm.red.regiment15',ref_ids)

if __name__=='__main__':unittest.main()
