"""Combat time, historical reference scope and casualty ledger regressions."""
import copy
import unittest
from unittest.mock import patch

from gentactix import historical_operations, missions
from tools.qa.historical_operational_fixture import inputs


class CombatEffectsTests(unittest.TestCase):
    def world(self):
        return historical_operations.initial(*inputs())

    def test_local_completion_never_claims_campaign_completion(self):
        from backend import afsim_state
        world=self.world();world['mission'].update(status='completed',winner='red')
        original=copy.deepcopy(world)
        result=afsim_state.mission_context(world)['historical_process_coverage']
        self.assertTrue(result['local_goal_settled'])
        self.assertFalse(result['full_campaign_verified'])
        self.assertTrue(result['phase_transition_available'])
        self.assertEqual(result['phase_id'],world['historical_initial']['phase_id'])
        session={'war_state':world,'turn_count':0,'time_step':'30分钟'}
        self.assertIn('不等于整场战役完成',afsim_state.analysis_facts(session))
        self.assertEqual(world,original)

    def test_observation_separates_session_clock_from_one_turn(self):
        from backend import afsim_state
        world=self.world();world['simulation_clock']={'elapsed_seconds':14400}
        world['combat_assessment']={'turn':8,'elapsed_seconds':1800,'units':[]}
        session={'id':'a123456789ab','war_state':world,'turn_count':8,'time_step':'30分钟','simulation_mode':'open','execution_backend':'afsim'}
        before=copy.deepcopy(session);o=afsim_state.observation(session)
        self.assertEqual(o['elapsed_seconds'],14400)  # legacy cumulative alias
        self.assertEqual(o['session_elapsed_seconds'],14400)
        self.assertEqual(o['last_turn_duration_seconds'],1800)
        self.assertEqual(o['configured_step_seconds'],1800)
        self.assertEqual(o['event_time_semantics']['elapsed_seconds'],'session_cumulative_duration_seconds')
        facts=afsim_state.analysis_facts(session)
        self.assertIn('本局累计240分钟',facts);self.assertIn('最近已完成一轮30分钟',facts)
        self.assertEqual(session,before)

    def test_absent_or_stale_turn_receipt_does_not_invent_a_duration(self):
        from backend import afsim_state
        world=self.world();world.pop('simulation_clock',None)
        world['combat_assessment']={'turn':7,'elapsed_seconds':1800,'units':[]}
        session={'id':'a123456789ab','war_state':world,'turn_count':8,'time_step':'30分钟','simulation_mode':'open','execution_backend':'afsim'}
        o=afsim_state.observation(session)
        self.assertIsNone(o['session_elapsed_seconds']);self.assertIsNone(o['last_turn_duration_seconds'])
        self.assertEqual(o['configured_step_seconds'],1800)

    def test_historical_reference_preserves_side_metric_and_scope(self):
        from gentactix import combat_effects as c
        value = c.benchmark('抗日战争-台儿庄战役-1938.03.23至1938.04.07')
        self.assertTrue(value['figures'])
        self.assertTrue(any('伤亡失踪' in r['metric'] for r in value['figures']))
        self.assertTrue(all(r['sources'] and r['scope'] for r in value['figures']))
        self.assertFalse(value['force_historical_outcome'])
        self.assertIn('第31师', str(c.reference(self.world())))

    def test_captured_and_missing_references_are_not_dropped_or_recast_as_deaths(self):
        from gentactix import combat_effects as c
        value = c.benchmark('红军长征-直罗镇战役-1935.11.20至1935.11.24')
        prisoners = [r for r in value['figures'] if r['metric'] == '被俘']
        self.assertEqual(len(prisoners), 1)
        self.assertEqual(prisoners[0]['value'], 5300)
        self.assertIn('全战役', prisoners[0]['scope'])
        self.assertTrue(prisoners[0]['sources'])
        self.assertFalse(value['force_historical_outcome'])
        self.assertTrue(all(r['value'] is None for r in value['figures'] if r['metric'] == '阵亡'))
        # A missing-person count is an independent loss category as well.
        data = {'scenarios': [{'name': 'missing-test', 'scope': '独立统计', 'figures': [
            {'side': '红军', 'metric': metric, 'value': 7, 'sources': ['S']}
            for metric in ('失踪', '中方所报歼敌（含俘168）', '俘敌')]}]}
        with patch.object(c.json, 'loads', side_effect=[data, {'sources': {'S': {'title': 'test'}}}]):
            self.assertEqual([r['metric'] for r in c.benchmark('missing-test')['figures']],
                             ['失踪', '中方所报歼敌（含俘168）', '俘敌'])

    def test_reported_aggregate_enemy_losses_remain_claims_with_their_scope(self):
        from gentactix import combat_effects as c
        value = c.benchmark('抗日战争-万家岭战役-1938.09下旬至1938.10')
        claims = [r for r in value['figures'] if r['metric']=='中方所报歼敌']
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]['value'], 10000)
        self.assertIn('未细分毙伤俘', claims[0]['note'])
        self.assertTrue(claims[0]['sources'])
        self.assertFalse(value['force_historical_outcome'])
        self.assertFalse(any(r['metric']=='阵亡' and r['value']==10000 for r in value['figures']))

    def test_reference_keeps_conflicting_death_claims_and_local_unit_scope(self):
        from gentactix import combat_effects as c
        value=c.benchmark('抗日战争-台儿庄战役-1938.03.23至1938.04.07')
        self.assertTrue(any(r['metric']=='报道所称捐躯' and r['evidence_status']=='source_conflict' for r in value['figures']))
        row=c.reference(self.world())['benchmark']['unit_references'][0]
        self.assertEqual(row['historical_unit_id'],'ww2.cn.division31')
        self.assertEqual(row['metric'],'killed_and_wounded')
        self.assertEqual(row['casualties_approx'],3000)
        self.assertIsNone(row['duration_hours'])
        self.assertFalse(row['hourly_rate_available'])

    def test_first_campaign_reference_keeps_prisoners_separate_and_unknown_strength(self):
        from gentactix import combat_effects as c
        world = {'mission': {'definition': {'battle': '抗美援朝-第一次战役-1950.10.25至1950.11.05'}}}
        reference = c.reference(world)
        row = reference['benchmark']['unit_references'][0]
        self.assertEqual(row['historical_unit_id'], 'kw.rok.regiment2.battalion3')
        self.assertIsNone(row['committed_approx'])
        self.assertIsNone(row['casualties_approx'])
        self.assertEqual(row['reported_killed'], 325)
        self.assertEqual(row['reported_captured'], 161)
        self.assertIn('异文', row['metric_summary'])
        self.assertFalse(row['hourly_rate_available'])
        self.assertFalse(reference['benchmark']['force_historical_outcome'])
        self.assertNotIn('死伤486', row['metric_summary'])

    def test_maryang_reference_keeps_wounded_returning_to_duty_separate(self):
        from gentactix import combat_effects as c
        world={'mission':{'definition':{'battle':'抗美援朝-夏秋季防御战役-1951.08.18至1951.10.22'}}}
        row=c.reference(world)['benchmark']['unit_references'][0]
        self.assertEqual(row['historical_unit_id'],'kw.au.rar3')
        self.assertEqual(row['reported_killed'],20)
        self.assertEqual(row['reported_wounded'],104)
        self.assertEqual(row['reported_wounded_remained_on_duty'],15)
        self.assertEqual(row['alternate_reported_wounded'],89)
        self.assertIsNone(row['casualties_approx'])
        self.assertIsNone(row['duration_hours'])
        self.assertFalse(row['hourly_rate_available'])
        self.assertIn('1951-10-03',row['scope'])

    def test_gloster_aggregate_is_not_622_killed_or_a_four_hour_quota(self):
        from gentactix import combat_effects as c
        world={'mission':{'definition':{'battle':'抗美援朝-第五次战役-1951.04.22至1951.06.10'}}}
        row=c.reference(world)['benchmark']['unit_references'][0]
        self.assertEqual(row['historical_unit_id'],'kw.uk.gloucestershire.battalion1')
        self.assertEqual(row['reported_aggregate_losses'],622)
        self.assertIsNone(row['reported_killed'])
        self.assertIsNone(row['casualties_approx'])
        self.assertFalse(row['hourly_rate_available'])
        self.assertIn('被俘',row['metric_summary'])

    def test_koyangdae_cumulative_claim_does_not_invent_opening_strength_or_kills(self):
        from gentactix import combat_effects as c
        world={'mission':{'definition':{'battle':'抗美援朝-秋季战术反击作战-1952.09.18至1952.10.31'}}}
        row=c.reference(world)['benchmark']['unit_references'][0]
        self.assertEqual(row['historical_unit_id'],'kw.us.division3.koyangdae_garrison')
        self.assertEqual(row['reported_initial_guard'],135)
        self.assertEqual(row['reported_enemy_losses'],600)
        self.assertIsNone(row['committed_approx'])
        self.assertIsNone(row['casualties_approx'])
        self.assertIn('1952-09-24',row['scope'])
        self.assertFalse(row['hourly_rate_available'])

    def review_world(self, *, losses=2, seconds=10800, cycles=80, active=9000, stop=0):
        before=self.world();after=copy.deepcopy(before)
        after['mission']['turn']=1
        red,blue=after['red_units'][0],after['blue_units'][0]
        red['personnel'].update(current=red['personnel']['current']-losses,casualties=losses)
        blue['formation']['last_execution']={'turn':1,'action':'fire','fire_cycles':cycles,
            'active_fire_s':active,'fire_stop_reason':stop,'small_arms_rounds_estimate':100000}
        orders=[{'unit':blue['name'],'action':'fire','target':red['name']}]
        return before,after,seconds,orders

    def test_large_formation_long_fire_tiny_losses_requires_review(self):
        from gentactix import combat_effects as c
        before,after,seconds,orders=self.review_world()
        review=c.assess_turn(before,after,seconds,orders,source='afsim_native')
        row=next(r for r in review['units'] if r['team']=='red')
        self.assertEqual(review['status'],'review_required')
        self.assertIn('sustained_fire_low_attrition',row['issues'])
        self.assertEqual(row['incoming_max_fire_s'],9000)
        self.assertEqual(row['turn_casualties'],2)
        self.assertEqual(after['red_units'][0]['personnel']['casualties'],2)
        self.assertFalse(review['historical_fit_verified'])

    def test_review_does_not_conflate_elapsed_time_or_many_attackers_with_exposure(self):
        from gentactix import combat_effects as c
        before,after,seconds,orders=self.review_world(active=120,cycles=1,stop=8)
        review=c.assess_turn(before,after,seconds,orders,source='afsim_native')
        row=next(r for r in review['units'] if r['team']=='red')
        self.assertNotIn('sustained_fire_low_attrition',row['issues'])
        self.assertEqual(row['incoming_max_fire_s'],120)
        self.assertEqual(review['status'],'calibration_pending')
        self.assertEqual(next(r for r in review['units'] if r['name']==orders[0]['unit'])['stop_reason'],'弹药工作量不足')

    def test_stale_or_dsh_receipts_are_not_native_fire_evidence(self):
        from gentactix import combat_effects as c
        before,after,seconds,orders=self.review_world()
        after['blue_units'][0]['formation']['last_execution']['turn']=0
        review=c.assess_turn(before,after,seconds,orders,source='afsim_native')
        row=next(r for r in review['units'] if r['team']=='red')
        self.assertIsNone(row['incoming_max_fire_s'])
        self.assertIn('fire_receipt_missing',next(r for r in review['units'] if r['name']==orders[0]['unit'])['issues'])
        after['blue_units'][0]['formation']['last_execution']['turn']=1
        review=c.assess_turn(before,after,seconds,orders,source='dsh_model_estimate')
        self.assertTrue(all(r['incoming_max_fire_s'] is None for r in review['units']))
        self.assertEqual(review['source'],'dsh_model_estimate')

    def test_review_reports_high_attrition_without_death_or_quota_inference(self):
        from gentactix import combat_effects as c
        before,after,seconds,orders=self.review_world(losses=200)
        review=c.assess_turn(before,after,seconds,orders,source='afsim_native')
        row=next(r for r in review['units'] if r['team']=='red')
        self.assertNotIn('sustained_fire_low_attrition',row['issues'])
        self.assertIsNone(row['turn_killed'])
        self.assertEqual(row['historical_reference']['historical_unit_id'],'ww2.cn.division31')
        self.assertEqual(row['historical_comparison'],'context_only_window_or_strength_differs')

    def test_review_accumulates_short_turns_and_resets_on_backend_change(self):
        from gentactix import combat_effects as c
        before,after,_,orders=self.review_world(losses=0,seconds=1800,active=1750,cycles=15)
        for turn in range(1,7):
            after=copy.deepcopy(before);after['mission']['turn']=turn
            after['blue_units'][0]['formation']['last_execution']={'turn':turn,'action':'fire','fire_cycles':15,'active_fire_s':1750,'fire_stop_reason':0}
            after['combat_assessment']=c.assess_turn(before,after,1800,orders,source='afsim_native')
            before=after
        review=after['combat_assessment'];self.assertEqual(review['status'],'review_required')
        self.assertEqual(review['tracked_from_turn'],1)
        self.assertEqual(review['units'][0]['tracked_incoming_max_fire_s'],10500)
        after=copy.deepcopy(before);after['mission']['turn']=7
        review=c.assess_turn(before,after,1800,orders,source='dsh_model_estimate')
        self.assertEqual(review['tracked_from_turn'],7)
        self.assertEqual(review['units'][0]['tracked_incoming_max_fire_s'],0)

    def test_multiple_attackers_do_not_multiply_target_exposure_time(self):
        from gentactix import combat_effects as c
        before,after,seconds,orders=self.review_world(seconds=1800,active=1750,cycles=15)
        other=after['blue_units'][1];other['formation']['last_execution']=copy.deepcopy(after['blue_units'][0]['formation']['last_execution'])
        orders.append({'unit':other['name'],'action':'fire','target':after['red_units'][0]['name']})
        row=c.assess_turn(before,after,seconds,orders,source='afsim_native')['units'][0]
        self.assertEqual(row['incoming_max_fire_s'],1750)
        self.assertNotIn('sustained_fire_low_attrition',row['issues'])

    def test_frozen_combat_reference_does_not_read_the_latest_library(self):
        from gentactix import combat_effects as c
        world = self.world(); frozen = c.reference(world)
        world['afsim'] = {'combat_profile': frozen}
        with patch.object(c, 'benchmark', side_effect=AssertionError('No latest source dependency')):
            self.assertEqual(c.reference(world), frozen)

    def test_casualty_breakdown_does_not_invent_deaths_from_unknown_prior_losses(self):
        from gentactix import combat_effects as c
        p = {'committed':100,'current':93,'casualties':5,'noncombat_losses':2,
             'killed':1,'wounded':1,'missing':0,'captured':0,'unclassified_casualties':3}
        self.assertTrue(c.validate_personnel(p))
        bad=copy.deepcopy(p);bad['killed']=5
        with self.assertRaises(ValueError):c.validate_personnel(bad)
        self.assertTrue(c.validate_personnel({'casualties':5}))

    def test_known_casualties_cannot_disappear_into_unknown(self):
        from gentactix import combat_effects as c
        prior={'casualties':5,'killed':1,'wounded':4}
        for value in ({'casualties':5}, {'casualties':5,'killed':None,'wounded':4}):
            with self.assertRaises(ValueError):c.validate_personnel(value,prior)
        prior={'casualties':7}
        with self.assertRaises(ValueError):c.validate_personnel({'casualties':7,'killed':2,'wounded':5},prior)
        self.assertTrue(c.validate_personnel({'casualties':10,'killed':1,'wounded':2,
            'missing':0,'captured':0,'unclassified_casualties':7},prior))

    def test_dsh_upgrade_freezes_reference_and_retains_unclassified_prior_losses(self):
        from backend import dsh_simulation
        from gentactix import combat_effects as c
        before=self.world();p=before['red_units'][0]['personnel']
        p.update(current=p['current']-7,casualties=7)
        from verify_dsh_resources import model_result
        result=model_result(before)
        after=dsh_simulation.apply(before,result,'30分钟')
        self.assertEqual(after['combat_reference'],c.reference(before))
        self.assertEqual(after['red_units'][0]['personnel']['casualties'],7)
        self.assertNotIn('killed',after['red_units'][0]['personnel'])

    def test_native_fire_repeats_on_time_and_carries_fractional_damage(self):
        from backend import afsim_world
        world=self.world();red,blue=world['red_units'][0],world['blue_units'][0]
        scene=afsim_world.compile_scene(world,[{'unit':red['name'],'action':'bombard','target':blue['name']}],1800,native_rules=True)
        self.assertIn('ca_next_fire_s',scene['script'])
        self.assertIn('GTXFIRE|',scene['script'])
        self.assertIn('GTXCASUALTY|',scene['script'])
        self.assertNotIn('double damage=GtxRound(power*efficiency',scene['script'])
        self.assertEqual(scene['native_model']['combat_revision'],2)

    def test_comparison_cannot_mix_combat_revisions(self):
        from backend import afsim_comparison,afsim_world
        before=self.world();after=copy.deepcopy(before)
        after['afsim']={'motion_revision':afsim_world.NATIVE_MOTION_REVISION,'combat_revision':1}
        with patch.object(afsim_world,'run_scene',side_effect=AssertionError('No mixed-model run')):
            with self.assertRaisesRegex(ValueError,'火力模型.*版本'):
                afsim_comparison.compare({'war_state':before},{'before':before,'after':after,'time_step':'30分钟'},[])

    def test_observation_and_dsh_independent_prompt_disclose_rate_reference(self):
        from backend import afsim_state,dsh_simulation
        session={'id':'abcdef123456','war_state':self.world(),'time_step':'30分钟','turn_count':0}
        session['war_state']['red_units'][0]['personnel']['killed']=0
        observation=afsim_state.observation(session,{'limit':1})
        self.assertEqual(observation['units'][0]['personnel'].get('killed'),0)
        self.assertEqual(observation['combat_reference']['combat_revision'],2)
        self.assertLess(len(str(observation['combat_reference'])),5000)
        self.assertIn('8000',observation['combat_reference'].get('local_reference',''))
        prompt=dsh_simulation.prompt(session['war_state'],'','')
        self.assertIn('历史战损参照',prompt)

    def test_dsh_bad_shooting_geometry_gets_retry_before_commit(self):
        from backend import dsh_simulation as d
        before=self.world();red,blue=before['red_units'][0],before['blue_units'][0]
        from verify_dsh_resources import model_result
        bad=model_result(before)
        bad['engagements']=[{'attacker':red['name'],'target':blue['name']}]
        bad['resource_ledger']['units'][0]['ammo_spent']=1
        bad['resource_ledger']['units'][0]['spent']={'shells':1}
        bad['unit_updates'][0]['logistics']['ammo']-=1
        bad['unit_updates'][0]['formation'].update(shells=red['formation']['shells']-1)
        bad['orders'][0].update(action='bombard',target=blue['name'])
        good=copy.deepcopy(bad)
        good['engagements']=[{'attacker':red['name'],'attacker_team':'red','attacker_pos':[red['lat'],red['lng']],
            'lat':blue['lat'],'lng':blue['lng'],'weapon_action':'bombard'}]
        from gentactix import fire_process
        good['unit_updates'][0]['formation'].update(suppression=red['formation']['suppression'],
            intel_age_min=red['formation']['intel_age_min']+30,intel_confidence=70,reload_remaining_s=0)
        good['unit_updates'][1]['formation'].update(suppression=30)
        good['fire_ledger']={'version':fire_process.VERSION,'units':[{'unit':red['name'],'action':'bombard','target':blue['name'],
            'delay_s':fire_process.delay_seconds(before,red),'first_fire_s':150,'last_fire_s':150,'fire_cycles':1,
            'active_fire_s':120,'reload_remaining_s':0,'stop_reason':'uncertain','assumptions':'测试单次炮击及后续中断估计，不是原生遥测。'}]}
        frozen=copy.deepcopy(before)
        with patch.object(d.h,'get_ai_response',side_effect=[bad,good]) as model:
            result,_,_=d.advance({'war_state':before,'time_step':'30分钟'},None,None)
        self.assertEqual(model.call_count,2)
        self.assertIn('缺少有效射击起点',model.call_args.args[0])
        self.assertEqual(result['updated_state']['engagements'],good['engagements'])
        self.assertEqual(before,frozen)

    def test_missing_attack_target_feedback_identifies_field_and_exact_opponents(self):
        world=self.world();red=world['red_units'][0]
        with self.assertRaisesRegex(ValueError,'target') as caught:
            missions.validate_orders(world,[{'unit':red['name'],'action':'fire'}],'30分钟')
        self.assertIn(world['blue_units'][0]['name'],str(caught.exception))

    def test_dsh_only_prompt_declares_attack_target_contract(self):
        from backend import dsh_simulation as d
        text=d.prompt(self.world(),'','')
        self.assertIn('"target":"敌方精确单位名"',text)
        self.assertIn('不能只提供交战动画',text)

    def test_report_distinguishes_casualties_from_deaths_and_old_unknowns(self):
        from gentactix import combat_effects as c
        before=self.world();after=copy.deepcopy(before)
        p=after['red_units'][0]['personnel'];p.update(current=p['current']-20,casualties=20,
            killed=5,wounded=15,missing=0,captured=0,unclassified_casualties=0)
        text=c.loss_summary(before,after)
        self.assertIn('本轮战斗减员20人',text)
        self.assertIn('累计阵亡估计5人',text)
        self.assertIn('累计负伤估计15人',text)
        self.assertNotIn('战死20人',text)

    def test_report_lists_capture_separately_without_reclassifying_old_losses(self):
        from gentactix import combat_effects as c
        before=self.world();after=copy.deepcopy(before)
        p=after['blue_units'][0]['personnel']
        p.update(current=p['current']-492,casualties=492,killed=0,wounded=0,
                 missing=0,captured=492,unclassified_casualties=0)
        text=c.loss_summary(before,after)
        self.assertIn('本轮被俘492人',text)
        self.assertIn('累计被俘492人',text)
        self.assertIn('本轮阵亡估计0人',text)
        before['blue_units'][0]['personnel']['casualties']=20
        before['blue_units'][0]['personnel'].pop('captured',None)
        self.assertIn('本轮被俘未分类',c.loss_summary(before,after))

    def test_capture_before_order_execution_is_not_missing_fire_telemetry(self):
        from gentactix import combat_effects as c
        before,after,seconds,orders=self.review_world(active=0,cycles=0)
        victim=after['blue_units'][0];p=victim['personnel'];captured=p['current']
        p.update(current=0,casualties=captured,killed=0,wounded=0,missing=0,
                 captured=captured,unclassified_casualties=0)
        victim['formation']['last_execution'].update(action='未交付',command_done=0)
        after['campaign']={'actors':{victim['name']:{'captured_this_turn':captured}}}
        row=next(r for r in c.assess_turn(before,after,seconds,orders,source='afsim_native')['units']
                 if r['name']==victim['name'])
        self.assertEqual(row['turn_captured'],captured)
        self.assertEqual(row['order_interruption'],'captured_before_execution')
        self.assertEqual(row['outgoing_fire_s'],0)
        self.assertNotIn('fire_receipt_missing',row['issues'])
        for invalidate in ('stale','mismatch','nonzero_fire','model_only'):
            bad=copy.deepcopy(after);receipt=bad['blue_units'][0]['formation']['last_execution']
            if invalidate=='stale':receipt['turn']=0
            elif invalidate=='mismatch':bad['campaign']['actors'][victim['name']]['captured_this_turn']=1
            elif invalidate=='nonzero_fire':receipt['active_fire_s']=10
            source='dsh_model_estimate' if invalidate=='model_only' else 'afsim_native'
            row=next(r for r in c.assess_turn(before,bad,seconds,orders,source=source)['units'] if r['name']==victim['name'])
            self.assertNotEqual(row.get('order_interruption'),'captured_before_execution')
            if source=='afsim_native':self.assertIn('fire_receipt_missing',row['issues'])

    def test_direct_fire_exposes_bounded_shooter_and_range_assumptions(self):
        from gentactix import combat_effects as c
        from backend import afsim_world
        world=self.world();profile=c.reference(world)
        self.assertIn('direct_fire',profile)
        for value in (-1,2,float('nan')):
            bad=copy.deepcopy(profile);bad['direct_fire']['engaged_fraction']=value
            with self.assertRaises(ValueError):c.validate_profile(bad)
        red,blue=world['red_units'][0],world['blue_units'][0]
        scene=afsim_world.compile_scene(world,[{'unit':red['name'],'action':'fire','target':blue['name']}],1800,native_rules=True)
        self.assertIn('GTXSMALL|',scene['script'])
        self.assertIn('GtxCADirectCover',scene['script'])

    def test_frozen_legacy_fire_profile_does_not_gain_new_small_arms_assumptions(self):
        from gentactix import combat_effects as c
        from backend import afsim_world
        world=self.world();legacy=c.reference(world);legacy.pop('direct_fire',None)
        legacy['version']='aggregate-fire-cycles-2.2';legacy['definition_hash']=c.digest({k:v for k,v in legacy.items() if k!='definition_hash'})
        world['combat_reference']=legacy
        self.assertTrue(c.validate_profile(legacy))
        scene=afsim_world.compile_scene(world,[],1800,native_rules=True)
        self.assertNotIn('GTXSMALL|',scene['script'])


if __name__=='__main__':unittest.main()
