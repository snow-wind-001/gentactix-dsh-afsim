"""Current-state conversion proposals: conservation before runtime admission."""
import copy
import unittest
from unittest.mock import patch

from gentactix import formation_conversion as fc, historical_initial as hi, historical_operations as ho, missions
from tools.qa.campaign_plan_fixture import inputs
from tools.upgrade_wanjialing import BATTLE


def damaged():
    unit=copy.deepcopy(ho.initial(*inputs())['red_units'][0])
    unit['personnel'].update(committed=10000,current=9800,casualties=180,noncombat_losses=20,
                             killed=40,wounded=140,missing=0,captured=0,unclassified_casualties=0)
    item=next(e for e in unit['equipment'] if e['category']=='transport')
    item.update(committed=20,operational=14,damaged=3,destroyed=3)
    unit['logistics'].update(food=17.125,ammo=3.75)
    unit['formation'].update(fatigue=77,suppression=66,signal=33,intel_age_min=91,intel_confidence=22,
        reload_remaining=3,reload_remaining_s=75,shells=101,fuel_liters=301,materials=11,
        combat_damage_remainder=.6,fatality_remainder=.4,partition_noncombat_remainder=.3,
        last_execution={'turn':9,'action':'fire','shots':8})
    unit['sustainment']={'version':'time-sustainment-1','shortage_hours':12.25,'noncombat_remainder':.8,
                       'last_receipt':{'turn':9,'demand':2,'consumed':1}}
    return unit


def parts():
    return [dict(id='left',label='左翼计算分队',committed=4000),dict(id='right',label='右翼计算分队',committed=6000)]


class ConversionTests(unittest.TestCase):
    def split(self, unit=None, allocations=None, **options):
        return fc.split_current(unit or damaged(),allocations or parts(),assumption='仅软件QA当前实态分配；不是历史兵额',
                                operation_id='a'*32,product_mode='synthetic',**options)

    def test_damaged_split_conserves_every_exclusive_category_and_source(self):
        u=damaged();old=copy.deepcopy(u);p=self.split(u)
        self.assertEqual(u,old);self.assertTrue(p['preview_only']);self.assertFalse(p['runtime_admitted'])
        self.assertEqual(p['totals_before'],p['totals_after'])
        for name in ('committed','current','casualties','noncombat_losses','killed','wounded','captured','missing','unclassified_casualties'):
            self.assertEqual(sum(x['personnel'][name] for x in p['after']),u['personnel'][name])
        self.assertEqual([x['personnel']['committed'] for x in p['after']],[4000,6000])
        for category in ('operational','damaged','destroyed'):
            self.assertEqual(sum(next(e for e in x['equipment'] if e['category']=='transport')[category] for x in p['after']),
                             next(e for e in u['equipment'] if e['category']=='transport')[category])

    def test_stock_work_is_not_duplicated_and_scale_is_not_current_strength(self):
        p=self.split();a,b=p['after']
        self.assertAlmostEqual(fc.resource_scale(a),.4);self.assertAlmostEqual(fc.resource_scale(b),.6)
        self.assertEqual(a['logistics'],damaged()['logistics']);self.assertEqual(b['logistics'],a['logistics'])
        self.assertEqual(p['totals_after']['normalized_stock']['ammo'],3.75)
        for k in fc.ABSOLUTE_STOCK:
            self.assertEqual(sum(x['formation'][k] for x in p['after']),damaged()['formation'][k])

    def test_split_keeps_state_and_does_not_clone_last_turn_receipts(self):
        u=damaged();p=self.split(u)
        for x in p['after']:
            for k in ('fatigue','suppression','signal','intel_age_min','intel_confidence','reload_remaining','reload_remaining_s','dispersion_km2'):
                self.assertEqual(x['formation'][k],u['formation'][k])
            self.assertNotIn('last_execution',x['formation']);self.assertNotIn('last_receipt',x['sustainment'])
            self.assertEqual((x['lat'],x['lng']),(u['lat'],u['lng']))
        self.assertEqual(p['before'][0]['formation']['last_execution'],u['formation']['last_execution'])
        self.assertAlmostEqual(sum(x['sustainment']['noncombat_remainder'] for x in p['after']),.8)

    def test_merge_current_damage_and_weighted_stock_without_healing(self):
        p=self.split();a,b=copy.deepcopy(p['after']);a['logistics']['ammo']=1;b['logistics']['ammo']=7
        a['formation']['fatigue']=90;b['formation']['fatigue']=20
        a['formation']['intel_confidence']=10;b['formation']['intel_confidence']=80
        q=fc.merge_current([a,b],assumption='QA同地合并',operation_id='b'*32)
        x=q['after'][0]
        self.assertEqual(q['totals_before'],q['totals_after'])
        self.assertEqual(x['personnel']['current'],9800);self.assertEqual(x['personnel']['casualties'],180)
        self.assertAlmostEqual(x['logistics']['ammo'],4.6)
        self.assertEqual(x['formation']['fatigue'],90);self.assertEqual(x['formation']['intel_confidence'],10)
        self.assertEqual(x['formation']['reload_remaining_s'],75)

    def test_absent_loss_classifications_are_not_invented_as_known_zero(self):
        u=damaged()
        for k in ('killed','wounded','captured','missing','unclassified_casualties'):u['personnel'].pop(k)
        p=self.split(u)
        for x in p['after']:
            self.assertNotIn('killed',x['personnel']);self.assertNotIn('wounded',x['personnel'])
        self.assertEqual(sum(x['personnel']['unclassified_casualties'] for x in p['after']),180)

    def test_dead_personnel_are_not_restored_by_division(self):
        u=damaged();u['personnel'].update(current=0,casualties=9980,killed=9840)
        p=self.split(u)
        self.assertTrue(all(x['personnel']['current']==0 for x in p['after']))

    def test_new_leaf_ids_are_deterministic_unique_and_keep_lineage(self):
        a=self.split();b=self.split();self.assertEqual(a,b)
        ids=[x['calculation_unit_id'] for x in a['after']];self.assertEqual(len(set(ids)),2)
        self.assertTrue(all(x['runtime_allocation']['version']==fc.VERSION for x in a['after']))
        self.assertTrue(fc.verify_proposal(a))
        for field in ('current','casualties'):
            bad=copy.deepcopy(a);bad['after'][0]['personnel'][field]+=1
            with self.subTest(field=field),self.assertRaises(ValueError):fc.verify_proposal(bad)

    def test_invalid_allocation_never_mutates_current_force(self):
        u=damaged();old=copy.deepcopy(u)
        for allocations in ([parts()[0]], [*parts(),parts()[0]],
                            [dict(id='left',label='重复',committed=10000),dict(id='right',label='负数',committed=-1)],
                            [dict(id='left',label='左',committed=1),dict(id='right',label='右',committed=9998)]):
            with self.subTest(allocations=allocations),self.assertRaises(ValueError):self.split(u,allocations)
        self.assertEqual(u,old)

    def test_duplicate_labels_cannot_produce_ambiguous_execution_names(self):
        allocations=parts();allocations[1]['label']=allocations[0]['label']
        with self.assertRaisesRegex(ValueError,'名称|重复'):self.split(allocations=allocations)

    def test_remote_or_in_transit_merge_cannot_teleport_or_drop_tasks(self):
        p=self.split();a,b=copy.deepcopy(p['after']);b['lng']+=.05;old=copy.deepcopy([a,b])
        with self.assertRaisesRegex(ValueError,'同地|集结'):fc.merge_current([a,b],assumption='QA',operation_id='b'*32)
        self.assertEqual([a,b],old)
        for status in ('queued','transit'):
            u=damaged();u['crossing']={'status':status}
            with self.subTest(status=status),self.assertRaisesRegex(ValueError,'渡运|在途'):self.split(u)

    def test_fractional_debt_cannot_be_laundered_by_merge(self):
        a,b=self.split()['after'];a['formation']['combat_damage_remainder']=.7;b['formation']['combat_damage_remainder']=.7
        old=copy.deepcopy([a,b])
        with self.assertRaisesRegex(ValueError,'余量|根账'):fc.merge_current([a,b],assumption='QA',operation_id='b'*32)
        self.assertEqual([a,b],old)

    def test_unknown_dynamic_state_is_rejected_instead_of_silently_reset(self):
        u=damaged();u['formation']['unknown_carry']=.8
        with self.assertRaisesRegex(ValueError,'字段|状态'):self.split(u)

    def test_native_combat_receipt_is_kept_in_history_without_becoming_new_leaf_results(self):
        u=damaged();u['last_combat_effects']={'turn':9,'source':'afsim-native-teaching-1',
            'ground_casualties':180,'air_casualties':0,'air_equipment_destroyed':0}
        p=self.split(u)
        self.assertEqual(p['before'][0]['last_combat_effects'],u['last_combat_effects'])
        self.assertTrue(all('last_combat_effects' not in leaf for leaf in p['after']))
        a,b=p['after'];a['last_combat_effects']=copy.deepcopy(u['last_combat_effects'])
        merged=fc.merge_current([a,b],assumption='QA旧回执不能变为合编后战果',operation_id='e'*32)
        self.assertNotIn('last_combat_effects',merged['after'][0])

    def test_equipment_carry_provenance_is_preserved_without_changing_gear_counts(self):
        u=damaged()
        for e in u['equipment']:e['carried_forward']=True
        p=self.split(u)
        self.assertTrue(all(e['carried_forward'] for leaf in p['after'] for e in leaf['equipment']))
        self.assertEqual(p['totals_before'],p['totals_after'])

    def test_large_absolute_stocks_are_not_capped_by_personnel_capacity(self):
        u=damaged();u['formation'].update(shells=200001,fuel_liters=300003)
        p=self.split(u)
        self.assertEqual(sum(x['formation']['shells'] for x in p['after']),200001)
        self.assertEqual(sum(x['formation']['fuel_liters'] for x in p['after']),300003)

    def test_equipment_damage_debt_is_shared_once_and_retained_on_merge(self):
        u=damaged();next(e for e in u['equipment'] if e['category']=='transport')['damage_load']=.75
        p=self.split(u)
        self.assertAlmostEqual(sum(next(e for e in x['equipment'] if e['category']=='transport')['damage_load'] for x in p['after']),.75)
        q=fc.merge_current(p['after'],assumption='QA装备余量',operation_id='b'*32)
        self.assertAlmostEqual(next(e for e in q['after'][0]['equipment'] if e['category']=='transport')['damage_load'],.75)

    def test_unknown_stock_or_cargo_cannot_be_duplicated_by_copying(self):
        for field,value in [('logistics',{'food':17.125,'ammo':3.75,'water_liters':100}),('cargo',{'personnel':12})]:
            u=damaged();u[field]=value
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'字段|载荷|库存'):self.split(u)

    def test_nested_split_and_partial_merge_do_not_impersonate_complete_parent(self):
        u=damaged();p=self.split(u,[dict(id='a',label='甲',committed=4000),dict(id='b',label='乙',committed=3000),dict(id='c',label='丙',committed=3000)])
        q=fc.merge_current(p['after'][:2],assumption='QA部分合并',operation_id='b'*32)
        self.assertIn('合并部',q['after'][0]['name'])
        r=fc.merge_current([q['after'][0],p['after'][2]],assumption='QA全部合并',operation_id='c'*32)
        self.assertEqual(r['after'][0]['name'],u['name'])
        left=self.split()['after'][0]
        sub=self.split(left,[dict(id='a',label='甲',committed=2000),dict(id='b',label='乙',committed=2000)])
        restored=fc.merge_current(sub['after'],assumption='QA嵌套还原',operation_id='c'*32)
        self.assertEqual(restored['after'][0]['name'],left['name'])

    def test_merge_does_not_pick_health_or_morale_of_the_better_member(self):
        a,b=self.split()['after'];a.update(hp=90,morale=85);b.update(hp=30,morale=40)
        x=fc.merge_current([a,b],assumption='QA状态保留',operation_id='b'*32)['after'][0]
        self.assertEqual(x['hp'],30);self.assertEqual(x['morale'],40)
        self.assertEqual(x['supply'],min(x['logistics'].values()))

    def test_partial_classifications_survive_merge_without_converting_unknowns_to_zero(self):
        a,b=self.split()['after'];p=b['personnel']
        for k in ('killed','wounded','captured','missing'):p.pop(k)
        p['unclassified_casualties']=p['casualties']
        q=fc.merge_current([a,b],assumption='QA未分类保留',operation_id='b'*32)
        x=q['after'][0]['personnel']
        self.assertEqual(x['killed'],a['personnel']['killed']);self.assertEqual(x['wounded'],a['personnel']['wounded'])
        self.assertNotIn('missing',x);self.assertNotIn('captured',x)
        self.assertEqual(x['unclassified_casualties'],b['personnel']['casualties'])

    def test_historical_split_requires_real_present_descendants_and_residual(self):
        snapshot=hi.initial(BATTLE,'oct7_attack',version='1.3.0')['historical_initial']
        u=damaged();u.update(historical_unit_id='ww2.cn.army74',name='第74军')
        allocations=[dict(id='d51',historical_unit_id='ww2.cn.division51',committed=4000),
                     dict(id='d58',historical_unit_id='ww2.cn.division58',committed=4000),
                     dict(id='residual',historical_unit_id=None,committed=2000)]
        p=fc.split_current(u,allocations,assumption='有来源番号，数值仅QA估计',operation_id='c'*32,
                           product_mode='historical',historical_snapshot=snapshot)
        self.assertEqual(p['after'][0]['name'],'第51师');self.assertEqual(p['after'][1]['name'],'第58师')
        self.assertIn('余部',p['after'][2]['name'])
        self.assertEqual(snapshot,hi.initial(BATTLE,'oct7_attack',version='1.3.0')['historical_initial'])
        bad=copy.deepcopy(allocations[:2]);bad[1]['committed']=6000
        with self.assertRaisesRegex(ValueError,'余部|覆盖'):
            fc.split_current(u,bad,assumption='QA',operation_id='c'*32,product_mode='historical',historical_snapshot=snapshot)

    def test_outside_scope_regiment_is_not_spawned_by_its_real_name(self):
        s=hi.initial(BATTLE,'oct7_attack',version='1.3.0')['historical_initial'];u=damaged()
        u.update(historical_unit_id='ww2.jp.division106',name='日军第106师团')
        parts=[dict(id='r123',historical_unit_id='ww2.jp.regiment123',committed=3000),
               dict(id='residual',historical_unit_id=None,committed=7000)]
        with self.assertRaisesRegex(ValueError,'在场|阶段'):
            fc.split_current(u,parts,assumption='QA',operation_id='d'*32,product_mode='historical',historical_snapshot=s)

    def test_estimated_parts_keep_source_parent_and_conserve_resources(self):
        snapshot=hi.initial(BATTLE,'oct7_attack',version='1.3.0')['historical_initial']
        unit=damaged();unit.update(historical_unit_id='ww2.cn.army74',name='第74军')
        proposal=fc.split_current(unit,parts(),assumption='教学计算分队，番号和分配均为估计',
            operation_id='e'*32,product_mode='historical',historical_snapshot=snapshot)
        self.assertEqual(proposal['totals_before'],proposal['totals_after'])
        for child in proposal['after']:
            self.assertEqual(child['historical_unit_id'],unit['historical_unit_id'])
            self.assertIn('计算分队',child['name'])
            self.assertEqual(child['runtime_allocation']['parent_identity']['historical_unit_id'],unit['historical_unit_id'])
        merged=fc.merge_current(proposal['after'],assumption='合并教学计算分队',operation_id='f'*32)
        self.assertEqual(merged['totals_before'],merged['totals_after'])


class ConversionIntegrationTests(unittest.TestCase):
    def setUp(self):
        from gentactix import commands,synthetic_history
        world=ho.initial(*inputs());binding=world['mission']['definition']['historical_calculation']
        cfg=synthetic_history.seed(binding)['configuration']
        self.world=missions.from_definition(synthetic_history.definition(binding,cfg))
        self.session=dict(id='conversion-qa',war_state=self.world,turn_count=0,time_step='30分钟',
                          product_mode='synthetic',simulation_mode='open',execution_backend='narrative',role_epoch=0)
        self.ids=list(commands.resolve_units(self.session));self.unit=commands.resolve_units(self.session)[self.ids[0]][1]
        committed=self.unit['personnel']['committed']
        self.args=dict(kind='split',unit_ids=[self.ids[0]],allocations=[dict(id='left',label='左翼',committed=committed//2),
                       dict(id='right',label='右翼',committed=committed-committed//2)],assumption='QA只读当前账预览',limit=1)

    def test_domain_preview_is_paged_and_all_session_state_is_unchanged(self):
        saved=copy.deepcopy(self.session);first=fc.observation(self.session,self.args)
        self.assertTrue(first['readonly']);self.assertFalse(first['runtime_admitted'])
        self.assertEqual(first['total_rows'],2);self.assertEqual(len(first['rows']),1)
        second=fc.observation(self.session,first['next_args']);self.assertIsNone(second['next_args'])
        self.assertEqual(first['view_version'],second['view_version'])
        self.assertNotEqual(first['rows'][0]['proposed_calculation_id'],second['rows'][0]['proposed_calculation_id'])
        self.assertEqual(first['totals_before'],first['totals_after']);self.assertEqual(self.session,saved)

    def test_preview_contains_bounded_ownership_proof_without_admitting_or_exporting_a_world(self):
        saved=copy.deepcopy(self.session);result=fc.observation(self.session,self.args)
        proof=result['ownership']
        self.assertTrue(proof['verified']);self.assertEqual(proof['current_revision'],0)
        self.assertEqual(proof['candidate_revision'],1);self.assertEqual(proof['selected_roots'],1)
        self.assertEqual(proof['current_entities'],6);self.assertEqual(proof['candidate_entities'],7)
        self.assertFalse(result['runtime_admitted']);self.assertNotIn('world',result)
        self.assertNotIn('transactions',proof);self.assertEqual(self.session,saved)

    def test_stale_pages_or_an_attempt_to_supply_current_state_are_rejected(self):
        from gentactix import commands
        page=fc.observation(self.session,self.args)
        self.session['command_state']=commands.replace_queue(self.session,[],control_team='red',director=True,no_fire=False,intent='新修订')
        with self.assertRaisesRegex(ValueError,'变化'):fc.observation(self.session,page['next_args'])
        for extra in ('world','product_mode','commit'):
            with self.subTest(extra=extra),self.assertRaises(ValueError):fc.observation(self.session,{**self.args,extra:{}})

    def test_preview_checks_process_continuity_without_exporting_receipts_or_running_physics(self):
        saved=copy.deepcopy(self.session);first=fc.observation(self.session,self.args)
        second=fc.observation(self.session,first['next_args'])
        self.assertEqual(first['continuity'],second['continuity'])
        proof=first['continuity'];self.assertTrue(proof['world_prepared'])
        self.assertTrue(proof['participation_history_preserved'])
        for key in ('clock_advanced','goals_evaluated','physics_executed','command_task_platform_admitted'):
            self.assertIs(proof[key],False)
        self.assertNotIn('before_metadata',proof);self.assertNotIn('world',first)
        self.assertFalse(first['runtime_admitted']);self.assertEqual(self.session,saved)

    def test_preview_includes_bounded_session_migration_proof_but_never_command_history(self):
        saved=copy.deepcopy(self.session);v=fc.observation(self.session,self.args)
        p=v['session_continuity'];self.assertTrue(p['commands_prepared']);self.assertTrue(p['organization_prepared'])
        self.assertFalse(p['agent_sessions_cloned']);self.assertFalse(p['runtime_admitted'])
        self.assertNotIn('before_command_state',p);self.assertNotIn('command_map',v);self.assertNotIn('session',v)
        self.assertEqual(self.session,saved)

    def test_existing_native_domain_dispatch_uses_the_same_readonly_preview(self):
        from backend import agent_tools,harness_engine
        saved=copy.deepcopy(self.session)
        result=agent_tools.execute_tool_call(self.session,self.world,dict(tool='preview_force_conversion',args=self.args))
        self.assertTrue(result['ok'],result);self.assertFalse(result['runtime_admitted']);self.assertEqual(self.session,saved)
        for external in (True,False):
            self.assertIn('preview_force_conversion',harness_engine.role_policy('chat',tools=True,external=external)['allowed_tools'])
        self.assertNotIn('preview_force_conversion',harness_engine.role_policy('scenario-builder',tools=True)['allowed_tools'])

    def test_production_native_context_preserves_synthetic_policy_for_domain_preview(self):
        from backend import afsim_state,main
        saved=copy.deepcopy(self.session)
        context=afsim_state.operation_context(self.session)
        self.assertEqual(context['session'].get('product_mode'),'synthetic')
        result=main._native_tool_dispatch(context,dict(tool='preview_force_conversion',args=self.args))
        self.assertTrue(result['ok'],result);self.assertFalse(result['runtime_admitted'])
        self.assertEqual(result['total_rows'],2);self.assertEqual(self.session,saved)

    def test_native_context_retains_epoch_bound_unit_ids_after_restart_or_reset(self):
        from backend import afsim_state,main
        from gentactix import commands
        self.session['role_epoch']=3
        args={**self.args,'unit_ids':[next(iter(commands.resolve_units(self.session)))]}
        saved=copy.deepcopy(self.session);context=afsim_state.operation_context(self.session)
        result=main._native_tool_dispatch(context,dict(tool='preview_force_conversion',args=args))
        self.assertTrue(result['ok'],result)
        self.assertEqual(result['world_version'],commands.world_version(self.session))
        self.assertEqual(self.session,saved)

    def test_http_preview_binds_revision_and_never_persists_or_adds_entities(self):
        from backend import main,session_store
        from fastapi.testclient import TestClient
        from gentactix import commands,force_organization
        v=commands.view(self.session);body={**self.args,'expected_turn':0,'revision':v['revision'],
            'world_version':v['world_version'],'organization_revision':force_organization.state(self.session)['revision']}
        saved=copy.deepcopy(self.session)
        with patch.dict(main._SESSIONS,{self.session['id']:self.session},clear=True),patch.object(session_store,'save',side_effect=AssertionError('Read-only preview cannot write')):
            client=TestClient(main.app);url='/api/sessions/conversion-qa/force-organization/conversion-preview'
            response=client.post(url,json=body);self.assertEqual(response.status_code,200,response.text)
            self.assertFalse(response.json()['runtime_admitted'])
            self.assertEqual(client.post(url,json={**body,'world_version':'stale'}).status_code,409)
            self.assertEqual(client.post(url,json={**body,'product_mode':'historical'}).status_code,422)
            self.assertEqual(len(main._SESSIONS),1);self.assertEqual(self.session,saved)


if __name__=='__main__':unittest.main(verbosity=2)
