"""Current-state platform codecs and isolated execution, no runtime commit."""
import copy
import unittest
from unittest.mock import patch

from backend import afsim_formation_parts, afsim_state, dsh_simulation, formation_execution as execution
from gentactix import formation_session as handoff, formation_parts, missions
from verify_formation_session import setup, prepare
from verify_campaign_plan_backends import proposal as model_proposal


def payload(world):
    value=model_proposal(world);index={u['name']:u for _,u in missions.units(world)}
    for row in value['resource_ledger']['units']:row['food_spent']*=formation_parts.scale(index[row['unit']])
    return value


def candidate():
    s,_,_=setup();return prepare(s)['session']


class FormationExecutionTests(unittest.TestCase):
    def test_artillery_salvo_budget_is_shared_by_the_original_root_not_each_fragment(self):
        from gentactix import fire_process
        from tools.qa.campaign_plan_fixture import inputs
        from gentactix import historical_operations as ho, synthetic_history
        source,p=inputs()
        for actor in p['actors'].values():actor['personnel']=10000
        p['actors']['ww2.cn.division159']['equipment']['artillery']=24
        binding=ho.initial(source,p)['mission']['definition']['historical_calculation']
        initial=missions.from_definition(synthetic_history.definition(binding,synthetic_history.seed(binding)['configuration']))
        s=dict(id='a'*12,war_state=initial,turn_count=0,time_step=initial['mission']['definition']['time_step'],
            product_mode='synthetic',simulation_mode='open',execution_backend='afsim')
        w=prepare(s)['session']['war_state'];parts=[u for _,u in missions.units(w) if u.get('runtime_allocation')]
        cap=int(w['mission']['definition']['combined_rules']['max_salvo'])
        orders=[dict(unit=u['name'],action='bombard') for u in parts]
        limits=fire_process.salvo_limits(w,orders)
        self.assertEqual(sum(limits[u['name']] for u in parts),cap)
        self.assertTrue(all(type(limits[u['name']]) is int for u in parts))
        one=fire_process.salvo_limits(w,orders[:1])
        self.assertEqual(one[parts[0]['name']],cap)
        self.assertEqual(one[parts[1]['name']],0)
        artillery=next(e for e in parts[0]['equipment'] if e['category']=='artillery')
        artillery['operational']=0
        artillery['damaged']=artillery['committed']-artillery['destroyed']
        limits=fire_process.salvo_limits(w,orders)
        self.assertEqual(limits[parts[0]['name']],0)
        self.assertEqual(limits[parts[1]['name']],cap)

    def test_native_compiler_loads_all_current_identities_without_calling_python_effects(self):
        s=candidate();saved=copy.deepcopy(s)
        with patch.object(missions,'advance',side_effect=AssertionError('No Python physics')):
            scene=execution.scene(s,[dict(unit=u['name'],action='hold') for _,u in missions.units(s['war_state'])])
        self.assertEqual(s,saved);self.assertEqual(len(scene['entities']),7)
        self.assertEqual({u['name'] for _,u in scene['native_model']['units']},{u['name'] for _,u in missions.units(s['war_state'])})
        self.assertEqual(len([line for line in scene['script'].splitlines() if 'GTXPARTSTATE|' in line]),2)
        self.assertIn('gtx_parent_goal',scene['script'])

    def test_runtime_noncombat_remainder_receipts_are_required_and_not_discarded(self):
        s=candidate();scene=execution.scene(s,[]);model=scene['native_model']
        ids=[i for i,e in scene['entities'].items() if next(u for _,u in missions.units(s['war_state']) if u['name']==e['name']).get('runtime_allocation')]
        text='\n'.join('GTXPARTSTATE|'+i+'|0.125' for i in ids)
        rows=afsim_formation_parts.parse(text,model,scene);self.assertEqual(set(rows),set(ids))
        after=copy.deepcopy(s['war_state']);afsim_formation_parts.apply(after,rows,scene)
        self.assertEqual([u['formation']['partition_noncombat_remainder'] for _,u in missions.units(after) if u.get('runtime_allocation')],[.125,.125])
        with self.assertRaises(ValueError):afsim_formation_parts.parse('',model,scene)

    def test_historical_children_read_the_original_root_fortification_configuration(self):
        from tools.qa.formation_ownership_fixture import historical_parent_world
        from gentactix import formation_conversion as fc
        w=historical_parent_world();s=dict(id='b'*12,war_state=w,turn_count=0,role_epoch=0,product_mode='historical',
            simulation_mode='open',execution_backend='afsim',time_step=w['mission']['definition']['time_step'])
        parent=next(u for u in w['red_units'] if u['historical_unit_id']=='ww2.cn.army74')
        p=fc.split_current(parent,[dict(id='a',historical_unit_id='ww2.cn.division51',committed=4000),
            dict(id='b',historical_unit_id='ww2.cn.division58',committed=4000),dict(id='rest',historical_unit_id=None,committed=2000)],
            assumption='QA原根配置继承，非真实兵额',operation_id='e'*32,product_mode='historical',historical_snapshot=w['historical_initial'])
        after=handoff.prepare(s,p,team='red')['session'];scene=execution.scene(after,[])
        self.assertEqual(len(scene['entities']),len(missions.units(w))+2)
        self.assertIn('ca_campaign_integrity',scene['script'])

    def test_external_observation_exposes_runtime_identity_scale_and_bounded_roots(self):
        s=candidate();ids=[i for i,(_,u) in __import__('gentactix.commands',fromlist=['resolve_units']).resolve_units(s).items() if u.get('runtime_allocation')]
        view=afsim_state.observation(s,dict(ids=ids,detail=True))
        self.assertEqual(len(view['units']),2)
        for row in view['units']:
            self.assertIn('calculation_unit_id',row);self.assertEqual(row['normalized_resource_scale'],.5)
            self.assertIn('runtime_allocation',row);self.assertNotIn('transactions',row['runtime_allocation'])

    def test_previous_native_receipt_does_not_certify_the_new_roster(self):
        original,_,_=setup();s=prepare(original)['session']
        s['war_state']['afsim']=dict(source='dsh_native_mcp_controller',status='completed',returncode=0,
            entity_count=6,roster_digest=formation_parts.roster_digest(original['war_state']))
        view=afsim_state.observation(s)
        self.assertTrue(view['execution']['verified'])
        self.assertEqual(view['execution']['receipt_scope'],'last_completed_frame')
        self.assertFalse(view['execution']['current_roster_match'])
        self.assertEqual(view['execution']['current_unit_count'],7)
        self.assertEqual(view['effects']['motion'],'not_yet_verified_for_current_roster')

    def test_area_fire_density_uses_the_shared_footprint_only_while_parts_are_colocated(self):
        from gentactix import fire_process
        w=candidate()['war_state'];parts=[u for _,u in missions.units(w) if u.get('runtime_allocation')]
        factors=fire_process.area_factors(w)
        self.assertAlmostEqual(factors[parts[0]['name']]['size_factor'],10000/3000)
        self.assertEqual(factors[parts[0]['name']],factors[parts[1]['name']])
        parts[0]['lat']+=.001
        isolated=fire_process.area_factors(w)
        self.assertAlmostEqual(isolated[parts[0]['name']]['size_factor'],5000/3000)
        self.assertAlmostEqual(isolated[parts[1]['name']]['size_factor'],5000/3000)

    def test_effective_root_groups_are_visible_without_an_initial_partition_table(self):
        s=candidate();self.assertNotIn('formation_groups',s['war_state'])
        groups=formation_parts.observation(s['war_state'])['groups']
        self.assertEqual(len(groups),1);self.assertEqual(len(groups[0]['parts']),2)
        self.assertEqual(groups[0]['personnel']['committed'],10000)

    def test_typed_dsh_apply_uses_current_registry_without_accepting_a_normal_runtime_world(self):
        s=candidate();w=s['war_state'];saved=copy.deepcopy(w);v=execution.validator(s)
        after=dsh_simulation.apply(w,payload(w),s['time_step'],validator=v)
        self.assertEqual(w,saved);self.assertEqual(len(missions.units(after)),7);self.assertEqual(after['mission']['turn'],1)
        self.assertTrue(v(after));self.assertTrue(all('normalized_resource_scale' in r for r in after['mission']['ledger'] if r['unit'] in {u['name'] for _,u in missions.units(w) if u.get('runtime_allocation')}))
        with self.assertRaises(ValueError):missions.validate(after)

    def test_execution_validator_rejects_another_definition_registry_or_time_window(self):
        s=candidate();v=execution.validator(s);self.assertTrue(v(s['war_state']))
        for field in ('definition','registry','clock'):
            w=copy.deepcopy(s['war_state'])
            if field=='definition':w['mission']['definition_hash']='0'*64
            elif field=='registry':w.pop('formation_registry')
            else:w['simulation_clock']['elapsed_seconds']+=3600
            with self.subTest(field=field),self.assertRaises(ValueError):v(w)

    def test_native_dsh_preview_keeps_the_host_validator_private_and_revalidates_effects(self):
        from backend import turn_preview
        s=candidate();value=payload(s['war_state']);check=execution.validator(s)
        ctx=turn_preview.context(s,None,operation_id='qa-isolated',fixed_orders=value['orders'],world_validator=check)
        copied=copy.deepcopy(ctx);result=turn_preview.execute(copied,dict(tool=turn_preview.TOOL,args=dict(candidate=value)))
        self.assertTrue(result['ok'],result);self.assertTrue(result['readonly'])
        self.assertTrue(callable(copied['_world_validator']));self.assertNotIn('_world_validator',result)
        bad=copy.deepcopy(value);bad['_world_validator']='from-model'
        rejected=turn_preview.execute(copied,dict(tool=turn_preview.TOOL,args=dict(candidate=bad)))
        self.assertFalse(rejected['ok']);self.assertIn('顶层字段',rejected['error'])

    def test_default_dsh_path_still_refuses_unadmitted_registered_worlds(self):
        s=candidate()
        with self.assertRaises(ValueError):dsh_simulation.apply(s['war_state'],payload(s['war_state']),s['time_step'])

    def test_engine_prompt_does_not_repeat_conversion_history_or_previous_world_metadata(self):
        from gentactix import formation_conversion as fc
        from verify_formation_continuity import selected
        s,_,_=setup();u=selected(s['war_state']);marker='HOST-ONLY-OPERATION-481516'
        p=fc.split_current(u,[dict(id='a',label='甲',committed=5000),dict(id='b',label='乙',committed=5000)],
            assumption='QA当前数值仍是估计，保留来源说明',operation_id=marker,product_mode='synthetic',historical_snapshot=s['war_state']['historical_initial'])
        after=handoff.prepare(s,p,team='red')['session'];text=dsh_simulation.prompt(after['war_state'])
        self.assertFalse(marker in text,'Host-only proposal provenance leaked into the model prompt')
        self.assertFalse('before_metadata' in text,'Previous process state leaked into the model prompt')
        self.assertFalse('source_world_digest' in text,'Private handoff digest repeated in the prompt')
        self.assertTrue('normalized_resource_scale' in text,'Current fragment resource scales must remain visible')
        self.assertTrue('parameter_sources' in text,'Current source/estimate labels must remain visible')


if __name__=='__main__':unittest.main(verbosity=2)
