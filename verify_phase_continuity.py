"""Phase handoff preserves losses and stocks, including after frozen restore."""
import copy
import unittest

from gentactix import historical_operations, missions, phase_continuity
from tools.qa.historical_operational_fixture import inputs


def checkpoint(**overrides):
    snapshot, params = inputs()
    params.update(copy.deepcopy(overrides))
    world = historical_operations.initial(snapshot, params)
    world['mission'].update(turn=2, status='completed')
    world['current_time'] = '1938-03-31 01:00'
    unit = world['red_units'][0]
    unit['personnel'].update(current=5993, casualties=7)
    unit['equipment'][1].update(operational=6, damaged=1, destroyed=1)
    unit['logistics'].update(food=12, ammo=3)
    unit['formation'].update(shells=9, fatigue=73)
    world['supply_nodes'][0]['stock'] = 2
    world['combined_arms']['depots']['red']['shells'] = 11
    params['clock']['start'] = world['current_time']
    return world, {'format': historical_operations.FORMAT, 'initial': snapshot, 'parameters': params}


class PhaseContinuityTests(unittest.TestCase):
    def test_motion_contract_and_existing_fatigue_survive_handoff_and_cannot_be_dropped(self):
        from verify_movement_feedback import CONFIG
        source,target=checkpoint(movement_feedback=CONFIG)
        child=missions.from_definition(phase_continuity.definition(phase_continuity.bind(source,target)))
        self.assertEqual(child['mission']['definition']['movement_feedback'],CONFIG)
        self.assertEqual(child['red_units'][0]['formation']['fatigue'],73)
        target['parameters'].pop('movement_feedback')
        with self.assertRaisesRegex(ValueError,'movement_feedback'):
            phase_continuity.definition(phase_continuity.bind(source,target))

    def test_unit_returning_from_archive_cannot_receive_a_fresh_full_roster(self):
        from gentactix import historical_initial, sim_clock
        snapshot,p=inputs();base=next(x for x in snapshot['definition']['phases'] if x['id']==snapshot['phase_id'])
        for identity in ('qa_exit','qa_return'):
            phase=copy.deepcopy(base);phase.update(id=identity,label='QA离场/归队测试，非史实阶段')
            snapshot['definition']['phases'].append(phase)
            for u in snapshot['definition']['units']:
                existing=next((r for r in u['presence'] if r['phase_id']==snapshot['phase_id']),None)
                if existing:
                    entry=copy.deepcopy(existing);entry['phase_id']=identity
                    if identity=='qa_exit' and u['id'] in ('ww2.jp.sakamoto_detachment','ww2.jp.division5'):entry['status']='outside_scope'
                    u['presence'].append(entry)
        snapshot['definition_hash']=historical_initial.digest(snapshot['definition'])
        source=historical_operations.initial(snapshot,p)
        source['mission'].update(turn=2,status='completed');source['current_time']='1938-03-31 01:00'
        source['blue_units'][1]['personnel'].update(current=1700,casualties=100)
        exit_snapshot=copy.deepcopy(snapshot);exit_snapshot['phase_id']='qa_exit'
        exit_p=copy.deepcopy(p);exit_p['phase_id']='qa_exit';exit_p['clock']['start']=source['current_time']
        exit_p['actors'].pop('ww2.jp.sakamoto_detachment')
        target={'format':historical_operations.FORMAT,'initial':exit_snapshot,'parameters':exit_p}
        child=missions.from_definition(phase_continuity.definition(phase_continuity.bind(source,target)))
        self.assertEqual(child['phase_handoff']['exited'][0]['personnel']['casualties'],100)
        child['current_time'],child['simulation_clock']=sim_clock.target(child,'1小时')
        child['mission'].update(turn=2,status='completed')
        return_snapshot=copy.deepcopy(snapshot);return_snapshot['phase_id']='qa_return'
        p['phase_id']='qa_return';p['clock']['start']=child['current_time']
        target={'format':historical_operations.FORMAT,'initial':return_snapshot,'parameters':p}
        with self.assertRaisesRegex(ValueError,'归档'):
            phase_continuity.definition(phase_continuity.bind(child,target))

    def test_damaged_fortification_and_arrival_status_are_not_reset(self):
        from tools.qa.campaign_fixture import inputs as campaign_inputs
        snapshot,p=campaign_inputs();source=historical_operations.initial(snapshot,p)
        source['mission'].update(turn=2,status='completed');source['current_time']='1938-03-31 01:00'
        source['campaign']['turn']=2
        for row in source['campaign']['actors'].values():row['active']=True
        enemy=source['blue_units'][0]['name'];source['campaign']['actors'][enemy]['fortification_integrity']=20
        p['clock']['start']=source['current_time']
        for row in p['campaign']['arrivals'].values():row['not_before']='1938-03-31T01:00'
        target={'format':historical_operations.FORMAT,'initial':snapshot,'parameters':p}
        child=missions.from_definition(phase_continuity.definition(phase_continuity.bind(source,target)))
        self.assertEqual(child['campaign']['actors'][enemy]['fortification_integrity'],20)
        self.assertTrue(child['campaign']['actors'][enemy]['active'])
        p['campaign']['arrivals']['ww2.jp.seya_detachment']['not_before']='1938-03-31T02:00'
        with self.assertRaisesRegex(ValueError,'入场'):
            phase_continuity.definition(phase_continuity.bind(source,target))

    def test_frozen_handoff_preserves_casualties_equipment_stock_and_fatigue(self):
        source, target = checkpoint()
        original = copy.deepcopy(source)
        spec = phase_continuity.definition(phase_continuity.bind(source, target))
        world = missions.from_definition(spec)
        self.assertEqual(world['red_units'][0]['personnel'], source['red_units'][0]['personnel'])
        self.assertEqual(world['red_units'][0]['equipment'], source['red_units'][0]['equipment'])
        self.assertEqual(world['red_units'][0]['logistics'], {'food': 12, 'ammo': 3})
        self.assertEqual(world['red_units'][0]['formation']['fatigue'], 73)
        self.assertEqual(world['supply_nodes'], source['supply_nodes'])
        self.assertEqual(world['combined_arms']['depots'], source['combined_arms']['depots'])
        self.assertEqual(world['mission']['turn'], 0)
        self.assertEqual(world['red_units'][0]['parameter_sources']['personnel']['kind'],'carried_computed')
        self.assertEqual(source, original)
        self.assertTrue(missions.validate(copy.deepcopy(world)))

    def test_reject_time_gap_changed_units_and_unfinished_stage(self):
        for kind in ('gap', 'active', 'tamper', 'version', 'depot'):
            source, target = checkpoint()
            binding = phase_continuity.bind(source, target)
            if kind == 'gap': binding['target']['parameters']['clock']['start'] = '1938-03-31 02:00'
            if kind == 'active':
                binding['source']['mission']['status'] = 'active'
                binding['source_hash'] = missions.digest(binding['source'])
            if kind == 'tamper': binding['source']['red_units'][0]['personnel']['current'] += 1
            if kind == 'version': binding['target']['initial']['version'] = '99.0.0'
            if kind == 'depot': binding['target']['parameters']['support']['red']['position']['lat'] += .001
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                phase_continuity.definition(binding)

    def test_destroyed_unit_is_not_resurrected_from_new_phase_inputs(self):
        source, target = checkpoint()
        source['red_units'][0]['personnel'].update(current=0, casualties=6000)
        spec = phase_continuity.definition(phase_continuity.bind(source, target))
        world = missions.from_definition(spec)
        self.assertEqual(world['red_units'][0]['personnel']['current'], 0)


if __name__ == '__main__': unittest.main()
