"""Exclusive immutable commitments before runtime entity admission."""
import copy
import json
import unittest

from gentactix import formation_conversion as fc, formation_registry as registry, historical_operations as ho, missions, synthetic_history
from tools.qa.campaign_plan_fixture import inputs


def world():
    source,p=inputs()
    for actor in p['actors'].values():
        actor['personnel']=10000;actor['equipment']['transport']=20
    baseline=ho.initial(source,p);binding=baseline['mission']['definition']['historical_calculation']
    return missions.from_definition(synthetic_history.definition(binding,synthetic_history.seed(binding)['configuration']))


def split(unit,op='a',sizes=(4000,6000)):
    return fc.split_current(unit,[dict(id='p'+str(i),label='QA分队'+str(i),committed=n) for i,n in enumerate(sizes)],
        assumption='软件唯一归属测试，非历史兵额',operation_id=op*32,product_mode='synthetic')


def reseal(value):
    value['state_hash']=missions.digest({k:v for k,v in value.items() if k!='state_hash'})


class FormationRegistryTests(unittest.TestCase):
    def setUp(self):self.world=world();self.unit=self.world['red_units'][0]

    def continuous_world(self):
        from verify_scheduled_physical import world as physical_world
        base=physical_world()['mission']['definition']['historical_calculation']
        return missions.from_definition(synthetic_history.definition(base,synthetic_history.seed(base)['configuration']))

    def continuous_proposal(self,world):
        from gentactix import combat_effects
        unit=world['red_units'][0];n=unit['personnel']['committed']
        return fc.split_current(unit,[dict(id='left',label='左分队',committed=n//2),dict(id='right',label='右分队',committed=n-n//2)],
            assumption='连续机动唯一归属QA',operation_id='a'*32,product_mode='synthetic',
            damage_quantum=combat_effects.reference(world).get('damage_quantum'))

    def test_registered_children_can_receive_later_motion_without_becoming_reorganizable(self):
        from backend import afsim_continuous_motion as motion
        original=self.continuous_world();root=original['red_units'][0]
        n=root['personnel']['committed'];candidate=registry.stage(original,self.continuous_proposal(original),team='red')['world']
        before=copy.deepcopy(candidate)
        for status in ('waiting','moving','blocked'):
            with self.subTest(status=status):
                current=copy.deepcopy(before);unit=current['red_units'][0]
                unit['formation']['motion_task']=motion.intent(unit,dict(action='move',lat=unit['lat']+.001,lng=unit['lng']),1000 if status=='waiting' else 0)
                unit['formation']['motion_task']['status']=status
                self.assertEqual(registry.validate(current)['revision'],1)
                with self.assertRaisesRegex(ValueError,'在途意图'):
                    split(unit,op='b',sizes=(n//4,n//2-n//4))
        self.assertEqual(candidate['mission'],before['mission'])

    def test_other_ongoing_units_do_not_block_stationary_unit_reorganization(self):
        from backend import afsim_continuous_motion as motion
        original=self.continuous_world();unit=original['blue_units'][0]
        unit['formation']['motion_task']=motion.intent(unit,dict(action='move',lat=unit['lat']+.001,lng=unit['lng']),1000)
        before=copy.deepcopy(original);root=original['red_units'][0];n=root['personnel']['committed']
        candidate=registry.stage(original,self.continuous_proposal(original),team='red')['world']
        self.assertEqual(registry.validate(candidate)['revision'],1)
        self.assertEqual(candidate['blue_units'][0]['formation']['motion_task'],unit['formation']['motion_task'])
        self.assertEqual(original,before)

    def test_ordinary_registry_validation_still_rejects_malformed_motion_state(self):
        from backend import afsim_continuous_motion as motion
        original=self.continuous_world();root=original['red_units'][0];n=root['personnel']['committed']
        candidate=registry.stage(original,self.continuous_proposal(original),team='red')['world']
        unit=candidate['red_units'][0]
        unit['formation']['motion_task']=motion.intent(unit,dict(action='move',lat=unit['lat']+.001,lng=unit['lng']),1000)
        unit['formation']['motion_task']['speed_mps']=float('nan')
        with self.assertRaises(ValueError):registry.validate(candidate)

    def stage(self,w=None,proposal=None,team='red'):
        w=w or self.world
        return registry.stage(w,proposal or split(w['red_units'][0]),team=team)

    def test_prepare_allocates_every_person_and_equipment_commitment_once_without_writing(self):
        before=copy.deepcopy(self.world);proposal=split(self.unit);value=self.stage(proposal=proposal)
        self.assertEqual(self.world,before);self.assertFalse(value['runtime_admitted'])
        candidate=value['world'];view=registry.validate(candidate)
        self.assertEqual(len(candidate['red_units']),6);self.assertEqual(len(view['active']),7)
        self.assertEqual(view['revision'],1);self.assertEqual(view['root_count'],6)
        self.assertEqual(candidate['mission'],before['mission'])
        self.assertEqual(candidate['historical_initial'],before['historical_initial'])
        self.assertEqual(fc._totals(proposal['before']),fc._totals(proposal['after']))

    def test_effective_reference_is_derived_from_verified_events_not_a_copied_active_cache(self):
        value=self.stage();candidate=value['world'];reference=registry.reference(candidate)
        self.assertEqual([(t,u['name']) for t,u in reference],[(t,u['name']) for t,u in missions.units(candidate)])
        reference[0][1]['name']='不能改候选'
        self.assertNotEqual(reference[0][1]['name'],candidate['red_units'][0]['name'])

    def test_nested_split_partial_merge_full_merge_keep_one_root(self):
        p=split(self.unit,sizes=(4000,3000,3000));one=self.stage(proposal=p)['world']
        q=fc.merge_current(p['after'][:2],assumption='QA部分合并',operation_id='b'*32)
        two=self.stage(one,q)['world']
        merged=q['after'][0];third=next(u for u in two['red_units'] if u['calculation_unit_id']==p['after'][2]['calculation_unit_id'])
        z=fc.merge_current([merged,third],assumption='QA完整还原',operation_id='c'*32)
        three=self.stage(two,z)['world'];v=registry.validate(three)
        self.assertEqual(v['revision'],3);self.assertEqual(len(three['red_units']),5)
        self.assertEqual(three['red_units'][0]['personnel']['committed'],10000)
        self.assertEqual(registry.commitment_scale(three,three['red_units'][0],'red'),1)

    def test_nested_subdivision_does_not_reset_resource_scale_to_one(self):
        p=split(self.unit);one=self.stage(proposal=p)['world'];part=one['red_units'][0]
        q=split(part,'b',(2000,2000));two=self.stage(one,q)['world']
        self.assertAlmostEqual(registry.commitment_scale(two,two['red_units'][0],'red'),.2)
        self.assertAlmostEqual(registry.commitment_scale(two,two['red_units'][1],'red'),.2)
        self.assertAlmostEqual(sum(registry.commitment_scale(two,u,'red') for u in two['red_units'][:3]),1)

    def test_damage_and_supplies_can_change_without_changing_ownership(self):
        one=self.stage()['world'];part=one['red_units'][0]
        part['personnel']['current']-=7;part['personnel']['casualties']+=7
        part['personnel']['unclassified_casualties']=7
        e=next(e for e in part['equipment'] if e['category']=='transport');e['operational']-=1;e['destroyed']+=1
        part['logistics']['food']-=3
        self.assertTrue(registry.validate(one))
        two=self.stage(one,split(part,'b',(2000,2000)))['world']
        self.assertEqual(sum(u['personnel']['casualties'] for u in two['red_units']),7)
        self.assertEqual(sum(e['destroyed'] for u in two['red_units'] for e in u['equipment']),1)

    def test_copying_a_child_and_only_changing_its_id_is_rejected(self):
        one=self.stage()['world'];clone=copy.deepcopy(one['red_units'][0]);clone['calculation_unit_id']+='copy';clone['name']+='复制'
        one['red_units'].append(clone)
        with self.assertRaisesRegex(ValueError,'集合|身份|归属'):registry.validate(one)

    def test_forged_runtime_metadata_without_registry_is_rejected_by_host_validator(self):
        self.unit['runtime_allocation']=split(self.unit)['after'][0]['runtime_allocation']
        with self.assertRaisesRegex(ValueError,'登记|归属'):missions.validate(self.world)

    def test_changed_current_commitment_or_equipment_base_is_rejected(self):
        for field in ('personnel','equipment'):
            candidate=self.stage()['world'];u=candidate['red_units'][0]
            if field=='personnel':u[field]['committed']+=1;u[field]['current']+=1
            else:u[field][-1]['committed']+=1;u[field][-1]['operational']+=1
            with self.subTest(field=field),self.assertRaises(ValueError):registry.validate(candidate)

    def test_unknown_or_retired_source_cannot_be_consumed_again(self):
        p=split(self.unit);one=self.stage(proposal=p)['world'];saved=copy.deepcopy(one)
        with self.assertRaisesRegex(ValueError,'前态|退役|身份'):self.stage(one,p)
        self.assertEqual(one,saved)

    def test_wrong_team_cannot_acquire_other_side_personnel_or_gear(self):
        with self.assertRaises(ValueError):self.stage(team='blue')

    def test_proposal_must_match_exact_current_state_not_only_its_digest(self):
        p=split(self.unit);self.unit['logistics']['ammo']-=1
        before=copy.deepcopy(self.world)
        with self.assertRaisesRegex(ValueError,'前态|当前'):self.stage(proposal=p)
        self.assertEqual(self.world,before)

    def test_repeated_event_is_rejected_even_after_resealing_registry(self):
        candidate=self.stage()['world'];state=candidate['formation_registry'];state['transactions'].append(copy.deepcopy(state['transactions'][0]));reseal(state)
        with self.assertRaisesRegex(ValueError,'重复|前态|退役|序号'):registry.validate(candidate)

    def test_recomputed_hash_does_not_authorize_overlapping_or_missing_ownership(self):
        candidate=self.stage()['world'];original=candidate['formation_registry']
        for bad in ('overlap','missing'):
            damaged=copy.deepcopy(candidate);state=damaged['formation_registry'];event=state['transactions'][0]
            ids=list(event['ownership_after']);first=event['ownership_after'][ids[0]];second=event['ownership_after'][ids[1]]
            root=next(iter(first));second[root]['personnel']=copy.deepcopy(first[root]['personnel']) if bad=='overlap' else []
            reseal(state)
            with self.subTest(bad=bad),self.assertRaisesRegex(ValueError,'归属|区间|分配'):registry.validate(damaged)
        self.assertEqual(candidate['formation_registry'],original)

    def test_gear_ownership_is_verified_separately_from_personnel_counts(self):
        candidate=self.stage()['world'];state=candidate['formation_registry'];event=state['transactions'][0]
        first,second=event['ownership_after'].values();root=next(iter(first))
        second[root]['equipment']['transport']=copy.deepcopy(first[root]['equipment']['transport']);reseal(state)
        with self.assertRaisesRegex(ValueError,'归属|区间|分配'):registry.validate(candidate)

    def test_cold_json_roundtrip_preserves_reference_scale_and_all_ownership(self):
        candidate=self.stage()['world'];cold=json.loads(json.dumps(candidate,ensure_ascii=False))
        self.assertEqual(registry.validate(cold),registry.validate(candidate))
        self.assertEqual(registry.reference(cold),registry.reference(candidate))

    def test_prepared_roster_is_not_admitted_without_remaining_process_migrations(self):
        candidate=self.stage()['world']
        with self.assertRaises(ValueError):missions.validate(candidate)

    def test_existing_initial_parts_keep_their_original_fraction_after_runtime_split(self):
        from tools.qa.historical_crossing_fixture import inputs as crossing_inputs
        from verify_formation_parts import partition_input
        source,p=crossing_inputs();p['partitions']=partition_input(p)
        binding=ho.initial(source,p)['mission']['definition']['historical_calculation']
        current=missions.from_definition(synthetic_history.definition(binding,synthetic_history.seed(binding)['configuration']))
        unit=next(u for u in current['red_units'] if u.get('formation_part',{}).get('part_id')=='main')
        candidate=self.stage(current,split(unit,sizes=(795,800)))['world']
        rows=[u for u in candidate['red_units'] if u.get('runtime_allocation')]
        self.assertAlmostEqual(registry.commitment_scale(candidate,rows[0],'red'),795/1600)
        self.assertAlmostEqual(registry.commitment_scale(candidate,rows[1],'red'),800/1600)
        advance=next(u for u in candidate['red_units'] if u.get('formation_part',{}).get('part_id')=='advance')
        self.assertAlmostEqual(sum(registry.commitment_scale(candidate,u,'red') for u in [*rows,advance]),1)

    def test_unselected_units_keep_current_losses_stock_and_cooldown_not_old_templates(self):
        one=self.stage()['world'];blue=one['blue_units'][0]
        blue['personnel']['current']-=11;blue['personnel']['casualties']+=11;blue['personnel']['unclassified_casualties']=11
        blue['logistics']['ammo']=12;blue['formation']['reload_remaining_s']=99
        before=copy.deepcopy(blue);two=self.stage(one,split(one['red_units'][0],'b',(2000,2000)))['world']
        self.assertEqual(two['blue_units'][0],before)

    def test_historical_world_cannot_claim_synthetic_policy_to_bypass_sourced_names(self):
        historical=ho.initial(*inputs());u=historical['red_units'][0];n=u['personnel']['committed']
        with self.assertRaisesRegex(ValueError,'用途|历史'):self.stage(historical,split(u,sizes=(n//2,n-n//2)))

    def test_registry_cannot_be_transplanted_to_another_definition(self):
        candidate=self.stage()['world'];candidate['mission']['definition_hash']='f'*64
        with self.assertRaisesRegex(ValueError,'来源|摘要'):registry.validate(candidate)

    def test_event_clock_cannot_move_backward_when_turn_increases(self):
        self.world['mission']['turn']=1;self.world['simulation_clock']['elapsed_seconds']=1800
        one=self.stage()['world'];one['mission']['turn']=2;one['simulation_clock']['elapsed_seconds']=3600
        two=self.stage(one,split(one['red_units'][0],'b',(2000,2000)))['world']
        state=two['formation_registry'];state['transactions'][1]['elapsed_seconds']=900;reseal(state)
        with self.assertRaisesRegex(ValueError,'时钟'):registry.validate(two)

    def test_boolean_revision_is_not_an_integer_transaction_identity(self):
        candidate=self.stage()['world'];state=candidate['formation_registry'];state['transactions'][0]['revision']=True;reseal(state)
        with self.assertRaisesRegex(ValueError,'序号'):registry.validate(candidate)

    def test_malformed_current_lineage_is_a_domain_rejection(self):
        candidate=self.stage()['world'];candidate['red_units'][0]['runtime_allocation']=['invalid']
        with self.assertRaises(ValueError):registry.validate(candidate)

    def test_a_new_name_cannot_collide_with_another_active_formation(self):
        allocations=[dict(id='a',label='甲',committed=4000),dict(id='b',label='乙',committed=6000)]
        p=fc.split_current(self.unit,allocations,assumption='QA',operation_id='a'*32,product_mode='synthetic')
        frozen=self.world['mission']['definition']['historical_synthetic']
        config=copy.deepcopy(frozen['configuration']);config['teams']['red'][1]['name']=p['after'][0]['name']
        self.world=missions.from_definition(synthetic_history.definition(frozen['base'],config))
        with self.assertRaisesRegex(ValueError,'名称|同名'):self.stage(proposal=p)

    def test_sourced_historical_children_and_unknown_residual_keep_exclusive_parent_ownership(self):
        from tools.qa.formation_ownership_fixture import historical_parent_world
        current=historical_parent_world();snapshot=copy.deepcopy(current['historical_initial'])
        parent=next(u for u in current['red_units'] if u['historical_unit_id']=='ww2.cn.army74')
        parent['personnel'].update(current=9800,casualties=180,noncombat_losses=20,killed=40,wounded=140)
        gear=next(e for e in parent['equipment'] if e['category']=='transport');gear.update(operational=14,damaged=3,destroyed=3)
        allocations=[dict(id='d51',historical_unit_id='ww2.cn.division51',committed=4000),
                     dict(id='d58',historical_unit_id='ww2.cn.division58',committed=4000),
                     dict(id='residual',historical_unit_id=None,committed=2000)]
        p=fc.split_current(parent,allocations,assumption='仅软件QA分配，非史实兵额',operation_id='f'*32,
            product_mode='historical',historical_snapshot=snapshot)
        candidate=self.stage(current,p)['world'];self.assertTrue(registry.validate(candidate))
        rows=[u for u in candidate['red_units'] if u.get('runtime_allocation')]
        self.assertEqual([u['historical_unit_id'] for u in rows],['ww2.cn.division51','ww2.cn.division58','ww2.cn.army74'])
        self.assertEqual(sum(u['personnel']['current'] for u in rows),9800)
        self.assertEqual(sum(e['destroyed'] for u in rows for e in u['equipment']),3)
        self.assertIn('未分配余部',rows[-1]['name']);self.assertEqual(candidate['historical_initial'],snapshot)


if __name__=='__main__':unittest.main(verbosity=2)
