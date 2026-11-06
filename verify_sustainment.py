"""Read-only supply feasibility must not create stocks or promise deliveries."""
import copy
import unittest
from unittest.mock import patch

from gentactix import sustainment,missions,historical_operations as ho


class SustainmentTests(unittest.TestCase):
    def test_insufficient_food_is_visible_without_changing_the_world(self):
        world=missions.initial('CA-AJ18-v1');world['mission']['definition']['deadline_turn']=100
        for _,u in missions.units(world):u['logistics']['food']=10
        for node in world['supply_nodes']:node['stock']=0
        before=copy.deepcopy(world);v=sustainment.assess(world);row=v['teams']['red']
        self.assertGreater(row['optimistic_food_shortfall'],0)
        self.assertEqual(row['minimum_hold_food'],row['food_per_hold_round']*100)
        self.assertEqual(world,before)

    def test_partitioned_parent_is_counted_once_not_once_per_leaf(self):
        from tools.qa.historical_crossing_fixture import inputs
        from verify_formation_parts import partition_input
        s,p=inputs();whole=sustainment.assess(ho.initial(s,p))
        p['partitions']=partition_input(p);split=sustainment.assess(ho.initial(s,p))
        for key in ('food_per_hold_round','on_hand_food','warehouse_packages','optimistic_food_shortfall'):
            self.assertAlmostEqual(whole['teams']['red'][key],split['teams']['red'][key])

    def test_full_ammo_can_block_the_legacy_combined_package(self):
        world=missions.initial('CA-AJ18-v1')
        unit=world['red_units'][0];unit['logistics'].update(food=0,ammo=100)
        row=sustainment.assess(world)['teams']['red']
        self.assertGreater(row['full_ammo_blocks_food_count'],0)
        self.assertIn('粮弹绑定',sustainment.assess(world)['scope'])

    def test_complete_or_unknown_world_does_not_invent_future_requirements(self):
        self.assertIsNone(sustainment.assess(None));self.assertIsNone(sustainment.assess({}))
        world=missions.initial('CA-AJ18-v1');world['mission']['turn']=world['mission']['definition']['deadline_turn']
        value=sustainment.assess(world)
        self.assertEqual(value['remaining_turns'],0)
        self.assertTrue(all(r['minimum_hold_food']==0 for r in value['teams'].values()))

    def test_staging_cost_and_native_observation_are_explicit(self):
        from tools.qa.campaign_fixture import inputs
        from backend import afsim_state
        world=ho.initial(*inputs());value=sustainment.assess(world)
        self.assertGreater(value['teams']['blue']['waiting_count'],0)
        self.assertIn('等待',value['scope'])
        self.assertEqual(afsim_state.mission_context(world)['sustainment'],value)
        self.assertNotIn('red_units',str(value))

    def test_frontend_snapshot_and_draft_use_the_same_bound_as_dsh(self):
        from backend import main,scenario_builder,afsim_state
        from tools.qa.campaign_fixture import inputs
        basis,params=inputs()
        session=main._new_session('保障预算检查','30分钟',False,None,False,False)
        session['war_state']=ho.initial(basis,params)
        frozen=copy.deepcopy(session['war_state'])
        self.assertEqual(main._snapshot(session)['sustainment'],afsim_state.mission_context(frozen)['sustainment'])
        self.assertEqual(session['war_state'],frozen)
        with patch.object(scenario_builder,'_save_draft',side_effect=lambda value,world:{**value,'preview_world':copy.deepcopy(world)}),patch.object(scenario_builder,'_load_world',return_value=None):
            draft=scenario_builder.stage_historical(basis,params,construction={},execution_backend='narrative')
        self.assertEqual(draft['sustainment'],sustainment.assess(draft['preview_world']))


if __name__=='__main__':unittest.main()
