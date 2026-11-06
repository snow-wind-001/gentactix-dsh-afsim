"""Zero-time identity/process continuity; no runtime command or physics admission."""
import copy
import json
import unittest

from gentactix import campaign, campaign_plan, formation_continuity as continuity, formation_conversion as fc
from gentactix import formation_registry as registry, historical_operations as ho, missions, synthetic_history, unit_participation as part
from tools.qa.campaign_plan_fixture import inputs
from verify_campaign_plan import step


def world(*,boundary=False,future=False,initial_parts=False,fortification_integrity=None):
    if boundary:
        from tools.qa.boundary_lifecycle_fixture import inputs as source_inputs
        source,p=source_inputs()
    else:source,p=inputs()
    for actor in p['actors'].values():actor['personnel']=10000;actor['equipment']['transport']=20
    if fortification_integrity is not None:
        for row in p['campaign']['fortifications'].values():row['integrity']=fortification_integrity
    if future:p['campaign']['arrivals']['ww2.cn.division159']['not_before']='1938-10-07T00:30:00'
    if initial_parts:
        u=p['actors']['ww2.cn.division159'];resources=('fuel_liters','spares','materials','shells','aa_rounds')
        p['partitions']=dict(version='formation-partitions-1',groups={'ww2.cn.division159':dict(assumption='QA互斥初始分队',parts=[
            dict(id=label,label=label,personnel=5000,position=copy.deepcopy(u['position']),
                 equipment={k:n//2 for k,n in u['equipment'].items()},resources={k:u['formation'][k]//2 for k in resources},
                 dispersion_km2=.25,assumption='QA同地互斥份额') for label in ('a','b')])})
        for node in p['campaign_plan']['nodes']:
            node['unit_ids']=[item for identity in node['unit_ids'] for item in
                (['ww2.cn.division159::a','ww2.cn.division159::b'] if identity=='ww2.cn.division159' else [identity])]
    binding=ho.initial(source,p)['mission']['definition']['historical_calculation']
    return missions.from_definition(synthetic_history.definition(binding,synthetic_history.seed(binding)['configuration']))


def selected(w):
    return next(u for u in w['red_units'] if u.get('source_historical_unit_id',u.get('historical_unit_id'))=='ww2.cn.division159')


def proposal(w,*,op='a',sizes=None):
    u=selected(w);n=u['personnel']['committed'];sizes=sizes or (n//2,n-n//2)
    return fc.split_current(u,[dict(id='p'+str(i),label='QA细分'+str(i),committed=x) for i,x in enumerate(sizes)],
        assumption='仅转换回归，非历史兵额或部署',operation_id=op*32,product_mode='synthetic',historical_snapshot=w['historical_initial'])


class ContinuityTests(unittest.TestCase):
    def make(self,**kw):return world(**kw)

    def prepare(self,w,p=None):return continuity.prepare(w,p or proposal(w),team='red')

    def mixed_fortifications(self):
        # Declared post-turn state fixture; only Native executes construction or
        # shell impact in runtime. The oracle below does not change any state.
        w=step(self.prepare(self.make(fortification_integrity=100))['world'])
        children=[u for u in w['red_units'] if u.get('runtime_allocation')]
        for unit,(base,integrity) in zip(children,((30,0),(10,100))):
            actor=w['campaign']['actors'][unit['name']]
            actor.update(base_entrenchment=base,fortification_integrity=integrity)
            factor=.25+.75*integrity/100
            unit['formation'].update(entrenchment=round(base*factor),protection=actor['base_protection']*factor)
        w['campaign_plan']['input_hash']=campaign_plan._input_hash(w)
        campaign_plan._seal(w['campaign_plan'])
        self.assertTrue(missions.validate(w,allow_prepared=True))
        return w,children

    @staticmethod
    def defense_oracle(row,*,shell_erosion=0,construction_gain=0):
        components=row.get('fortification_components') or [row]
        return min(min(100,p['base_entrenchment']+construction_gain)*
            (.25+.75*max(0,p['fortification_integrity']-shell_erosion)/100) for p in components)

    def test_mixed_built_and_damaged_fortifications_do_not_create_a_weaker_pair_on_merge(self):
        w,children=self.mixed_fortifications();saved=copy.deepcopy(w)
        actors=[w['campaign']['actors'][u['name']] for u in children]
        expected=min(self.defense_oracle(row) for row in actors)
        result=self.prepare(w,fc.merge_current(children,assumption='QA不同施工及毁伤状态同地合编',operation_id='c'*32))['world']
        merged=next(u for u in result['red_units'] if u.get('runtime_allocation'))
        actor=result['campaign']['actors'][merged['name']]
        self.assertEqual(self.defense_oracle(actor),expected)
        protection=actor['base_protection']*(.25+.75*actor['fortification_integrity']/100)
        self.assertEqual(protection,min(u['formation']['protection'] for u in children))
        self.assertEqual(w,saved)

    def test_mixed_fortification_handoff_retains_the_envelope_for_future_damage_and_construction(self):
        w,children=self.mixed_fortifications();actors=[w['campaign']['actors'][u['name']] for u in children]
        result=self.prepare(w,fc.merge_current(children,assumption='QA工事状态不能仅匹配显示值',operation_id='d'*32))['world']
        merged=next(u for u in result['red_units'] if u.get('runtime_allocation'))
        actor=result['campaign']['actors'][merged['name']]
        for erosion,gain in ((0,20),(25,0),(50,20),(100,80)):
            expected=min(self.defense_oracle(row,shell_erosion=erosion,construction_gain=gain) for row in actors)
            self.assertEqual(self.defense_oracle(actor,shell_erosion=erosion,construction_gain=gain),expected)

    def test_previous_v2_handoff_keeps_its_frozen_interpretation_after_json_restore(self):
        from unittest.mock import patch
        original=continuity._campaign
        def previous(before,after,event,**kwargs):
            return original(before,after,event,legacy=kwargs.get('legacy',False),envelope=False)
        with patch.object(continuity,'VERSION',continuity.PREVIOUS_VERSION),patch.object(continuity,'_campaign',side_effect=previous):
            w,children=self.mixed_fortifications()
            old=self.prepare(w,fc.merge_current(children,assumption='QA冻结v2旧解释',operation_id='e'*32))['world']
        frozen=json.dumps(old,ensure_ascii=False)
        self.assertTrue(missions.validate(json.loads(frozen),allow_prepared=True))
        merged=next(u for u in old['red_units'] if u.get('runtime_allocation'))
        actor=old['campaign']['actors'][merged['name']]
        self.assertNotIn('fortification_components',actor)
        self.assertEqual(self.defense_oracle(actor),2.5)
        self.assertEqual(json.dumps(old,ensure_ascii=False),frozen)

    def test_resealed_zero_time_receipt_cannot_upgrade_a_defensive_facet(self):
        w,children=self.mixed_fortifications()
        after=self.prepare(w,fc.merge_current(children,assumption='QA工事侧面防篡改',operation_id='f'*32))['world']
        merged=next(u for u in after['red_units'] if u.get('runtime_allocation'))
        actor=after['campaign']['actors'][merged['name']]
        actor['fortification_components'][1]['base_entrenchment']+=10
        campaign.validate_state(after)
        receipt=after['formation_registry']['transactions'][-1]['process_handoff']
        receipt['after_metadata_hashes']['campaign']=missions.digest(after['campaign'])
        receipt['after_world_digest']=continuity.physical_digest(continuity._without_latest_receipt(after))
        continuity._seal(after['formation_registry'])
        with self.assertRaisesRegex(ValueError,'接续|推导|物理'):
            missions.validate(after,allow_prepared=True)

    def test_constructed_fortification_base_is_carried_through_split_and_merge(self):
        w=self.make();unit=selected(w);actor=w['campaign']['actors'][unit['name']]
        # Explicit post-construction state fixture; not a Python fortify executor.
        actor['base_entrenchment']+=8;unit['formation']['entrenchment']+=8
        unit['formation']['materials']=5
        campaign_plan.initialize(w)
        base=actor['base_entrenchment'];before=copy.deepcopy(w)
        after=self.prepare(w)['world']
        self.assertTrue(missions.validate(after,allow_prepared=True))
        children=[u for u in after['red_units'] if u.get('runtime_allocation')]
        for child in children:self.assertEqual(after['campaign']['actors'][child['name']]['base_entrenchment'],base)
        merged=self.prepare(after,fc.merge_current(children,assumption='QA保留已构筑防御',operation_id='f'*32))['world']
        member=next(u for u in merged['red_units'] if u.get('runtime_allocation'))
        self.assertEqual(merged['campaign']['actors'][member['name']]['base_entrenchment'],base)
        self.assertEqual(member['formation']['materials'],selected(before)['formation']['materials'])
        self.assertEqual(w,before)

    def test_ordinary_construction_state_does_not_allow_zero_time_fortification_upgrade(self):
        from gentactix import campaign
        after=self.prepare(self.make())['world'];unit=next(u for u in after['red_units'] if u.get('runtime_allocation'))
        after['campaign']['actors'][unit['name']]['base_entrenchment']+=8
        # The ordinary validator permits construction; conversion receipt still
        # rejects changing its registered zero-time outcome without a turn.
        campaign.validate_state(after)
        with self.assertRaises(ValueError):missions.validate(after,allow_prepared=True)

    def test_legacy_handoff_keeps_frozen_baseline_interpretation_without_migration(self):
        from unittest.mock import patch
        w=self.make();unit=selected(w);w['campaign']['actors'][unit['name']]['base_entrenchment']+=8
        unit['formation']['entrenchment']+=8;campaign_plan.initialize(w)
        original=continuity._campaign
        def old_campaign(before,after,event,**kwargs):return original(before,after,event,legacy=True)
        with patch.object(continuity,'VERSION',continuity.LEGACY_VERSION),patch.object(continuity,'_campaign',side_effect=old_campaign):
            legacy=self.prepare(w)['world']
        frozen=json.dumps(legacy,ensure_ascii=False)
        self.assertTrue(missions.validate(json.loads(frozen),allow_prepared=True))
        self.assertEqual(json.dumps(legacy,ensure_ascii=False),frozen)
        child=next(u for u in legacy['red_units'] if u.get('runtime_allocation'))
        self.assertEqual(legacy['campaign']['actors'][child['name']]['base_entrenchment'],10)
        current=self.prepare(w)['world'];child=next(u for u in current['red_units'] if u.get('runtime_allocation'))
        self.assertEqual(current['campaign']['actors'][child['name']]['base_entrenchment'],18)
        self.assertEqual(current['formation_registry']['transactions'][-1]['process_handoff']['version'],continuity.VERSION)

    def test_split_has_shared_fixed_identity_validation_and_leaves_live_input_unchanged(self):
        w=self.make();saved=copy.deepcopy(w);value=self.prepare(w);after=value['world']
        self.assertTrue(missions.validate(after,allow_prepared=True));self.assertFalse(value['runtime_admitted'])
        self.assertEqual(w,saved);self.assertEqual(after['mission'],w['mission'])
        self.assertEqual(after['historical_initial'],w['historical_initial'])
        self.assertEqual(after['simulation_clock'],w['simulation_clock'])
        self.assertEqual(len(after['red_units']),len(w['red_units'])+1)

    def test_public_validator_still_blocks_execution_until_session_and_platform_migration(self):
        after=self.prepare(self.make())['world']
        with self.assertRaisesRegex(ValueError,'执行|接纳|事务'):missions.validate(after)
        with missions.validation_scope(after):
            self.assertTrue(missions.validate(after,allow_prepared=True))
            with self.assertRaises(ValueError):missions.validate(after)

    def test_goal_milestones_progress_and_sample_clock_are_not_reset_or_rewarded_twice(self):
        w=self.make();point=w['mission']['definition']['campaign_plan']['nodes'][0]['condition']['region']['center']
        w=step(w,{'ww2.cn.division159':point});self.assertEqual(w['campaign_plan']['nodes']['north']['status'],'completed')
        after=self.prepare(w)['world']
        before_state={k:v for k,v in w['campaign_plan'].items() if k not in ('input_hash','state_hash')}
        self.assertEqual({k:v for k,v in after['campaign_plan'].items() if k not in ('input_hash','state_hash')},before_state)
        saved=copy.deepcopy(after['campaign_plan']);campaign_plan.evaluate(after)
        self.assertEqual(after['campaign_plan'],saved)

    def test_goal_selector_expands_to_disjoint_current_children_and_members_page(self):
        w=self.make();after=self.prepare(w)['world'];config=after['mission']['definition']['campaign_plan']
        self.assertEqual(config,w['mission']['definition']['campaign_plan'])
        first=campaign_plan.observation(after,kind='members',node_id='north',limit=1)
        second=campaign_plan.observation(after,**first['next_args'])
        self.assertEqual(first['total'],2);self.assertIsNone(second['next_args'])
        self.assertEqual(len({u['unit_id'] for u in first['members']+second['members']}),2)
        self.assertTrue(all(u['selection_unit_id']==config['nodes'][0]['unit_ids'][0] for u in first['members']+second['members']))

    def test_goal_node_distinguishes_frozen_selectors_from_current_execution_entities(self):
        after=self.prepare(self.make())['world']
        node=campaign_plan.observation(after,node_id='north')['nodes'][0]
        self.assertEqual(node['unit_count'],1);self.assertEqual(node['active_entity_count'],2)

    def test_campaign_fixed_bases_arrival_and_turn_are_inherited(self):
        w=self.make();u=selected(w);before=copy.deepcopy(w['campaign']['actors'][u['name']]);after=self.prepare(w)['world']
        self.assertEqual(after['campaign']['turn'],w['campaign']['turn'])
        self.assertEqual(after['campaign']['objective'],w['campaign']['objective'])
        for row in after['red_units']:
            if not row.get('runtime_allocation'):continue
            self.assertEqual(campaign.release_seconds(after,row),campaign.release_seconds(w,u))
            self.assertEqual(after['campaign']['actors'][row['name']],before)

    def test_classified_capture_of_current_round_is_distributed_once(self):
        w=self.make();u=selected(w);u['personnel'].update(current=9990,casualties=10,captured=10)
        w['campaign']['actors'][u['name']]['captured_this_turn']=3
        w['campaign_plan']['input_hash']=campaign_plan._input_hash(w);campaign_plan._seal(w['campaign_plan'])
        after=self.prepare(w)['world'];self.assertTrue(missions.validate(after,allow_prepared=True))
        self.assertEqual(sum(row['captured_this_turn'] for row in after['campaign']['actors'].values()),3)

    def test_boundary_participation_history_remains_auditable_without_a_fake_physical_transition(self):
        w=self.make(boundary=True);u=selected(w);key=part._key(w,u);row=w['unit_participation']['actors'][key]
        row['transition_count']=2;part._seal(w['unit_participation']);saved=copy.deepcopy(row)
        after=self.prepare(w)['world'];self.assertTrue(missions.validate(after,allow_prepared=True))
        self.assertEqual(after['campaign_lifecycle'],w['campaign_lifecycle'])
        for unit in after['red_units']:
            if not unit.get('runtime_allocation'):continue
            current=part.unit_view(after,unit)
            self.assertEqual(current['status'],saved['status']);self.assertEqual(current['transition_count'],0)
            self.assertIsNone(current['last_transition'])
            self.assertEqual(current['conversion_origin']['inherited_counts'],{key:2})
        before_record=after['formation_registry']['transactions'][-1]['process_handoff']['before_metadata']['unit_participation']
        self.assertEqual(before_record['actors'][key],saved)

    def test_rear_reserve_is_not_promoted_by_splitting(self):
        w=self.make(boundary=True);row=w['unit_participation']['actors'][part._key(w,selected(w))];row['status']='reserve'
        part._seal(w['unit_participation']);w['campaign_plan']['input_hash']=campaign_plan._input_hash(w);campaign_plan._seal(w['campaign_plan'])
        after=self.prepare(w)['world'];self.assertTrue(missions.validate(after,allow_prepared=True))
        self.assertTrue(all(not part.in_operation(after,u) for u in after['red_units'] if u.get('runtime_allocation')))

    def test_staging_unit_cannot_become_deployed_through_a_new_name(self):
        w=self.make(boundary=True,future=True)
        self.assertEqual(part.unit_view(w,selected(w))['status'],'staging')
        with self.assertRaisesRegex(ValueError,'到场|在途|参与'):self.prepare(w)

    def test_split_then_merge_keeps_one_goal_root_and_preserves_losses_and_resources(self):
        w=self.make();one=self.prepare(w)['world'];units=[u for u in one['red_units'] if u.get('runtime_allocation')]
        q=fc.merge_current(units,assumption='QA同源同地还原',operation_id='b'*32)
        after=self.prepare(one,q)['world'];self.assertTrue(missions.validate(after,allow_prepared=True))
        self.assertEqual(fc._totals([selected(w)]),fc._totals([u for u in after['red_units'] if u.get('runtime_allocation')]))
        self.assertEqual(len(campaign_plan.observation(after,kind='members',node_id='north')['members']),1)

    def test_initial_partition_parent_groups_remain_complete_without_duplicate_survivors(self):
        from gentactix import formation_parts
        w=self.make(initial_parts=True);one=self.prepare(w)['world']
        self.assertTrue(missions.validate(one,allow_prepared=True))
        self.assertEqual(formation_parts.count(one,'red',lambda u:True),formation_parts.count(w,'red',lambda u:True))
        groups=formation_parts.observation(one)['groups'];self.assertEqual(len(groups),1)
        self.assertEqual(len(groups[0]['parts']),3);self.assertEqual(groups[0]['personnel']['committed'],10000)

    def test_zero_time_conversion_that_changes_goal_observation_is_rejected_unchanged(self):
        one=self.prepare(self.make())['world'];units=[u for u in one['red_units'] if u.get('runtime_allocation')]
        units[0]['logistics']['ammo']=1;units[1]['logistics']['ammo']=9
        # The original immutable plan has no resource node. Add no new rules:
        # suppression changes the control predicate at the selected north goal.
        point=one['mission']['definition']['campaign_plan']['nodes'][0]['condition']['region']['center']
        for u in units:u.update(point)
        units[0]['formation']['suppression']=0;units[1]['formation']['suppression']=100
        one=step(one)
        units=[u for u in one['red_units'] if u.get('runtime_allocation')]
        snapshot=copy.deepcopy(one);q=fc.merge_current(units,assumption='QA不可借重绑定改变目标',operation_id='c'*32)
        with self.assertRaisesRegex(ValueError,'改变了目标物理观察'):self.prepare(one,q)
        self.assertEqual(one,snapshot)

    def test_resealed_receipt_cannot_hide_reset_goal_progress_or_promote_participation(self):
        after=self.prepare(self.make(boundary=True))['world'];before=copy.deepcopy(after)
        child=next(u for u in after['red_units'] if u.get('runtime_allocation'))
        row=after['unit_participation']['actors'][part._key(after,child)];row['transition_count']=99
        part._seal(after['unit_participation'])
        with self.assertRaises(ValueError):missions.validate(after,allow_prepared=True)
        self.assertEqual(before['mission'],after['mission'])

    def test_json_restore_rechecks_the_handoff_instead_of_trusting_extra_unit_metadata(self):
        after=self.prepare(self.make(boundary=True))['world'];cold=json.loads(json.dumps(after,ensure_ascii=False))
        self.assertTrue(missions.validate(cold,allow_prepared=True));self.assertEqual(cold,after)
        event=cold['formation_registry']['transactions'][-1];event['process_handoff']['source_world_digest']='0'*64
        state=cold['formation_registry'];state['state_hash']=missions.digest({k:v for k,v in state.items() if k!='state_hash'})
        with self.assertRaises(ValueError):missions.validate(cold,allow_prepared=True)

    def test_initial_part_already_across_keeps_its_declared_route_after_further_split(self):
        from tools.qa.historical_crossing_fixture import inputs as crossing_inputs
        from verify_formation_parts import partition_input
        from gentactix import formation_parts
        source,p=crossing_inputs();p['partitions']=partition_input(p)
        binding=ho.initial(source,p)['mission']['definition']['historical_calculation']
        w=missions.from_definition(synthetic_history.definition(binding,synthetic_history.seed(binding)['configuration']))
        unit=next(u for u in w['red_units'] if u.get('formation_part',{}).get('part_id')=='advance')
        p=fc.split_current(unit,[dict(id='a',label='甲',committed=2),dict(id='b',label='乙',committed=3)],
            assumption='QA预置渡口份额',operation_id='d'*32,product_mode='synthetic')
        expected=formation_parts.prepositioned_route(w,unit);self.assertIsNotNone(expected)
        after=continuity.prepare(w,p,team='red')['world']
        children=[u for u in after['red_units'] if u.get('runtime_allocation')]
        self.assertTrue(all(formation_parts.prepositioned_route(after,u)==expected for u in children))

    def test_pending_withdrawal_is_rejected_without_dropping_the_request(self):
        from gentactix import sim_clock
        w=self.make(boundary=True);w['current_time'],w['simulation_clock']=sim_clock.target(w,w['mission']['definition']['time_step'])
        w['mission']['turn']=1;w['campaign']['turn']=1
        state=w['unit_participation'];state.update(turn=1,elapsed_seconds=w['simulation_clock']['elapsed_seconds'])
        u=selected(w);row=state['actors'][part._key(w,u)]
        route=w['mission']['definition']['operation_boundary']['routes'][0]
        row.update(status='withdrawing',pending=dict(id='a'*32,kind='withdraw',destination=copy.deepcopy(route['outside']),
            origin_status='deployed',origin_position={k:u[k] for k in ('lat','lng')},issued_turn=0))
        part._seal(state);campaign_plan.evaluate(w);missions.validate(w)
        saved=copy.deepcopy(w)
        with self.assertRaisesRegex(ValueError,'在途|请求'):self.prepare(w)
        self.assertEqual(w,saved)

    def test_malformed_receipt_metadata_is_a_clean_domain_rejection(self):
        after=self.prepare(self.make())['world'];event=after['formation_registry']['transactions'][-1]
        event['process_handoff']['before_metadata']['campaign']=[]
        with self.assertRaises(ValueError):continuity.check_receipt(event)

    def test_historical_parent_and_legacy_goal_prepare_without_committing_a_probe_score(self):
        from tools.qa.formation_ownership_fixture import historical_parent_world
        from unittest.mock import patch
        w=historical_parent_world();u=next(u for u in w['red_units'] if u['historical_unit_id']=='ww2.cn.army74')
        p=fc.split_current(u,[dict(id='a',historical_unit_id='ww2.cn.division51',committed=4000),
            dict(id='b',historical_unit_id='ww2.cn.division58',committed=4000),
            dict(id='rest',historical_unit_id=None,committed=2000)],assumption='QA历史来源父级分配',
            operation_id='e'*32,product_mode='historical',historical_snapshot=w['historical_initial'])
        before=copy.deepcopy(w)
        with patch.object(missions,'advance',side_effect=AssertionError('No Python physics')):
            after=continuity.prepare(w,p,team='red')['world']
        self.assertTrue(missions.validate(after,allow_prepared=True));self.assertEqual(after['mission'],w['mission'])
        self.assertEqual(after['campaign']['objective'],w['campaign']['objective']);self.assertEqual(w,before)


if __name__=='__main__':unittest.main(verbosity=2)
