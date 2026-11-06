"""Waiting-stage action contracts and command-version attribution boundaries."""
import copy
import unittest
from unittest.mock import patch

from gentactix import campaign,combined_arms,combat_effects,historical_operations as ho
from backend import afsim_comparison,afsim_world
from tools.qa.campaign_fixture import inputs


class StagingSupportTests(unittest.TestCase):
    def setUp(self):
        self.world=ho.initial(*inputs())
        self.unit=next(u for u in self.world['blue_units'] if campaign.release_seconds(self.world,u)>0)

    def test_waiting_support_is_allowed_but_movement_and_fire_are_rejected(self):
        before=copy.deepcopy(self.world)
        self.assertEqual(set(combined_arms.actions(self.world,self.unit,'blue')),{'hold','recon','resupply','restore_comms'})
        for action in ('hold','recon','resupply','restore_comms'):
            campaign.check_order(self.world,{'unit':self.unit['name'],'action':action})
        for action in ('move','fire','bombard','capture'):
            with self.subTest(action=action),self.assertRaisesRegex(ValueError,'等待'):
                campaign.check_order(self.world,{'unit':self.unit['name'],'action':action})
        self.assertEqual(self.world,before)

    def test_old_command_semantics_cannot_be_attributed_to_different_decisions(self):
        after=copy.deepcopy(self.world)
        after['afsim']={'motion_revision':afsim_world.motion_revision(self.world),
            'combat_revision':combat_effects.COMBAT_REVISION,'combat_profile':combat_effects.reference(self.world),
            'supply_control_revision':1}
        record={'before':self.world,'after':after,'time_step':'30分钟'}
        frozen=copy.deepcopy(record)
        with patch.object(afsim_world,'run_scene',side_effect=AssertionError('Mixed rules must not execute')):
            with self.assertRaisesRegex(ValueError,'指挥.*版本'):
                afsim_comparison.compare({'war_state':self.world},record,[])
        self.assertEqual(record,frozen)


if __name__=='__main__':unittest.main()
