"""Process receipts and whole-operation goals across the DSH path."""
import copy
import unittest
from unittest.mock import patch

from backend import dsh_simulation
from gentactix import campaign, historical_operations, missions
from tools.qa.campaign_fixture import inputs
from verify_dsh_resources import model_result


class CampaignModelTests(unittest.TestCase):
    def facet_world(self):
        source,parameters=inputs()
        identity=next(i for i in parameters['actors'] if i.startswith('ww2.cn.'))
        parameters['campaign']['fortifications'][identity]['integrity']=100
        parameters['actors'][identity]['formation'].update(entrenchment=10,materials=2)
        world=historical_operations.initial(source,parameters)
        unit=next(u for u in world['red_units'] if u['historical_unit_id']==identity)
        actor=world['campaign']['actors'][unit['name']]
        actor.update(base_entrenchment=10,fortification_integrity=20,fortification_components=[
            dict(base_entrenchment=10.,fortification_integrity=100.),dict(base_entrenchment=30.,fortification_integrity=20.)])
        unit['formation'].update(entrenchment=10,protection=actor['base_protection']*.4)
        return world,unit

    def facet_proposal(self,world,unit):
        value=self.proposal(world)
        value['campaign']['actors'][unit['name']]['fortification_components']=copy.deepcopy(world['campaign']['actors'][unit['name']]['fortification_components'])
        return value

    def test_facet_hold_payload_is_explicit_preserved_and_never_repaired_by_host(self):
        w,u=self.facet_world();value=self.facet_proposal(w,u);saved=copy.deepcopy(value);before=copy.deepcopy(w)
        after=self.apply(value,w)
        self.assertEqual(after['campaign']['actors'][u['name']]['fortification_components'],value['campaign']['actors'][u['name']]['fortification_components'])
        self.assertEqual(after['campaign']['execution_source'],'dsh_model_estimate')
        self.assertEqual(w,before);self.assertEqual(value,saved)

    def test_facet_payload_cannot_be_omitted_when_prior_world_carries_it(self):
        w,u=self.facet_world();value=self.proposal(w)
        with self.assertRaisesRegex(ValueError,'fortification_components|侧面'):self.apply(value,w)

    def test_latent_facet_changes_need_commands_shells_and_matching_original_indices(self):
        for kind in ('construction','erosion','missing','reorder'):
            w,u=self.facet_world();value=self.facet_proposal(w,u);parts=value['campaign']['actors'][u['name']]['fortification_components']
            if kind=='construction':parts[1]['base_entrenchment']+=10
            elif kind=='erosion':parts[0]['fortification_integrity']-=1
            elif kind=='missing':parts.pop()
            else:parts.reverse()
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.apply(value,w)

    def test_facet_construction_keeps_both_pairs_and_requires_material_cost(self):
        w,u=self.facet_world();value=self.facet_proposal(w,u);name=u['name']
        row=value['campaign']['actors'][name];row['base_entrenchment']=30
        for part in row['fortification_components']:part['base_entrenchment']+=20
        update=next(r for r in value['unit_updates'] if r['unit']==name)
        update['formation'].update(materials=u['formation']['materials']-1,entrenchment=20)
        next(o for o in value['orders'] if o['unit']==name)['action']='fortify'
        next(r for r in value['resource_ledger']['units'] if r['unit']==name)['spent']['materials']=1
        after=self.apply(value,w)
        self.assertEqual(after['campaign']['actors'][name]['fortification_components'],row['fortification_components'])
        self.assertEqual(after['red_units'][0]['formation']['materials'],1)
        free=copy.deepcopy(value);next(r for r in free['unit_updates'] if r['unit']==name)['formation']['materials']=2
        next(r for r in free['resource_ledger']['units'] if r['unit']==name)['spent']={}
        with self.assertRaises(ValueError):self.apply(free,w)

    def test_selective_facet_construction_is_not_a_whole_unit_operation(self):
        w,u=self.facet_world();value=self.facet_proposal(w,u);name=u['name']
        value['campaign']['actors'][name]['fortification_components'][1]['base_entrenchment']+=20
        next(o for o in value['orders'] if o['unit']==name)['action']='fortify'
        next(r for r in value['unit_updates'] if r['unit']==name)['formation']['materials']=1
        next(r for r in value['resource_ledger']['units'] if r['unit']==name)['spent']['materials']=1
        with self.assertRaisesRegex(ValueError,'同一|共同|侧面'):self.apply(value,w)

    def test_facet_output_cannot_report_a_defense_from_the_mixed_scalar_minima(self):
        w,u=self.facet_world();value=self.facet_proposal(w,u)
        next(r for r in value['unit_updates'] if r['unit']==u['name'])['formation']['entrenchment']=4
        with self.assertRaisesRegex(ValueError,'工事|侧面'):self.apply(value,w)

    def test_prompt_explicitly_types_facets_only_for_a_world_that_carries_them(self):
        import json
        w,u=self.facet_world();text=dsh_simulation.prompt(w)
        shape=json.loads(text.split('只输出JSON：',1)[1].split('。',1)[0])
        self.assertIn('fortification_components',shape['campaign']['actors']['精确单位名'])
        self.assertIn('不能相加',text)
        self.assertNotIn('fortification_components',dsh_simulation.prompt(self.world))

    def test_primary_output_example_includes_all_required_campaign_fields(self):
        import json
        text=dsh_simulation.prompt(self.world)
        shape=json.loads(text.split('只输出JSON：',1)[1].split('。',1)[0])
        self.assertEqual(set(shape['campaign']),{'actors'})
        self.assertEqual(set(shape['campaign']['actors']['精确单位名']),{'active','fortification_integrity','base_entrenchment','captured_this_turn'})
        self.assertIn('响应最外层',text)

    def test_actual_nested_combined_arms_failure_names_its_json_path_without_repair(self):
        value=self.proposal();value['campaign']['combined_arms']={}
        before=copy.deepcopy(self.world);candidate=copy.deepcopy(value)
        with self.assertRaisesRegex(ValueError,r'\$\.campaign'):
            self.apply(value)
        self.assertEqual(self.world,before);self.assertEqual(value,candidate)

    def setUp(self):
        self.world = historical_operations.initial(*inputs())

    def test_objective_instruction_does_not_order_deadline_settlement(self):
        from backend import campaign_model
        snapshot, params = inputs()
        params['goal'].update(termination_mode='objectives', deadline_turn=20, required_turns=2)
        world = historical_operations.initial(snapshot, params)
        text = campaign_model.instruction(world)
        self.assertNotIn('在截止回合结算', text)
        self.assertIn('不按规划参考回合自动结束', text)
        self.assertIn('连续达标', text)

    def test_legacy_instruction_still_describes_frozen_deadline(self):
        from backend import campaign_model
        self.assertNotIn('termination_mode', self.world['mission']['definition'])
        self.assertIn('在截止回合结算', campaign_model.instruction(self.world))

    def proposal(self, world=None):
        world = world or self.world
        value = model_result(world)
        value['campaign'] = {'actors': {name: {k: copy.deepcopy(row[k]) for k in
            ('active', 'fortification_integrity', 'base_entrenchment', 'captured_this_turn')}
            for name, row in world['campaign']['actors'].items()}}
        for row in value['campaign']['actors'].values(): row['captured_this_turn'] = 0
        return value

    def apply(self, value, world=None):
        with patch.object(missions, 'advance', side_effect=AssertionError('No Python process executor')):
            return dsh_simulation.apply(world or self.world, value, '30分钟')

    def test_waiting_then_exact_boundary_arrival_is_model_supplied_and_validated(self):
        before=copy.deepcopy(self.world);value=self.proposal();saved=copy.deepcopy(value)
        after=self.apply(value);name=self.world['blue_units'][-1]['name']
        self.assertFalse(after['campaign']['actors'][name]['active'])
        self.assertEqual(after['campaign']['turn'],1)
        self.assertEqual(after['campaign']['execution_source'],'dsh_model_estimate')
        value2=self.proposal(after)
        with self.assertRaisesRegex(ValueError,'入场'):self.apply(value2,after)
        value2['campaign']['actors'][name]['active']=True
        self.assertTrue(self.apply(value2,after)['campaign']['actors'][name]['active'])
        self.assertEqual(self.world,before);self.assertEqual(value,saved)

    def test_missing_extra_fabricated_or_unsupported_process_is_rejected(self):
        for kind in ('missing','unit','objective','integrity','capture','entrenchment'):
            value=self.proposal();name=self.world['blue_units'][0]['name']
            if kind=='missing':value.pop('campaign')
            elif kind=='unit':value['campaign']['actors'].pop(name)
            elif kind=='objective':value['campaign']['objective']={'town_control':True}
            elif kind=='integrity':value['campaign']['actors'][name]['fortification_integrity']-=1
            elif kind=='capture':value['campaign']['actors'][name]['captured_this_turn']=1
            else:value['campaign']['actors'][name]['base_entrenchment']+=1
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.apply(value)

    def test_capture_has_matching_personnel_account_and_needs_no_fictitious_shot(self):
        target=self.world['blue_units'][0];target['logistics']['ammo']=0
        value=self.proposal();actor=self.world['red_units'][0]
        value['orders'][0].update(action='capture',target=target['name'])
        row=next(r for r in value['unit_updates'] if r['unit']==target['name'])
        row['personnel']={'current':target['personnel']['current']-10,'casualties':10,'captured':10}
        value['campaign']['actors'][target['name']]['captured_this_turn']=10
        after=self.apply(value)
        self.assertEqual(after['blue_units'][0]['personnel']['captured'],10)
        self.assertEqual(after['engagements'],[])
        self.assertEqual(after['red_units'][0]['personnel'],actor['personnel'])
        bad=copy.deepcopy(value);bad['orders'][0]={'unit':actor['name'],'action':'hold'}
        with self.assertRaisesRegex(ValueError,'受降'):self.apply(bad)

    def test_all_three_goal_conditions_are_required_and_cannot_finish_early(self):
        w=self.world;spec=w['mission']['definition'];town=spec['objective'];red=w['red_units'][0]
        red.update(town)
        for u in w['blue_units']:u['lat']+=.1
        spec['campaign_definition']['objective']['relief_regions'][0]['center']={'lat':town['lat']+.1,'lng':town['lng']}
        w['mission']['turn']=1;missions.evaluate(w)
        self.assertTrue(w['campaign']['objective']['town_control'])
        self.assertFalse(w['campaign']['objective']['relief_denied'])
        self.assertFalse(w['mission']['metrics']['condition'])
        spec['campaign_definition']['objective']['relief_regions'][0]['center']=copy.deepcopy(town)
        missions.evaluate(w)
        self.assertTrue(w['mission']['metrics']['condition'])
        self.assertEqual(w['mission']['status'],'active')
        w['mission']['turn']=spec['deadline_turn'];missions.evaluate(w)
        self.assertEqual(w['mission']['winner'],'red')

    def test_prompt_includes_process_contract_and_never_requests_goal_flags(self):
        message=dsh_simulation.prompt(self.world)
        self.assertIn('captured_this_turn',message)
        self.assertIn('阻援',message)
        self.assertIn('目标标志由程序判定',message)

    def test_native_observation_exposes_waiting_and_fortification_without_full_world(self):
        from backend import afsim_state
        s={'id':'campaign-observation','war_state':self.world,'turn_count':0,'time_step':'30分钟','execution_backend':'afsim'}
        value=afsim_state.observation(s,{'limit':16});name=self.world['blue_units'][-1]['name']
        row=next(u for u in value['units'] if u['name']==name)
        self.assertEqual(row['arrival']['status'],'staging')
        self.assertFalse(row['operational_state']['active'])
        self.assertNotIn('fire',row['actions'])
        self.assertNotIn('definition',value['mission'])
        self.assertIn('relief_regions',value['mission']['operational_process']['objective'])

    def test_goal_description_matches_all_three_conditions(self):
        text=self.world['mission']['definition']['goal']
        self.assertIn('阻援',text);self.assertIn('人数',text)
        self.assertNotIn('连续保持',text)


if __name__=='__main__':unittest.main()
