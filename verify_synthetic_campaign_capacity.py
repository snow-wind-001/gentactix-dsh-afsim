"""Campaign-derived exercises preserve large source rosters and bounded edits."""
import copy
import tempfile
import os
import unittest
from unittest.mock import patch

from gentactix import combined_arms,historical_operations as ho,missions,synthetic_history as sh
from tools.qa.campaign_capacity_fixture import inputs,configuration


class CampaignCapacityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot,cls.parameters=inputs();cls.base=ho.definition(cls.snapshot,cls.parameters)
        cls.binding=cls.base['historical_calculation']

    def test_unchanged_wuhan_seed_preserves_every_source_unit(self):
        seed=sh.seed(self.binding);old=copy.deepcopy((self.base,self.binding,seed))
        spec=sh.definition(self.binding,seed['configuration']);w=missions.from_definition(spec)
        self.assertEqual([len(w[t+'_units'])for t in ('red','blue')],[70,9])
        for team in ('red','blue'):
            self.assertEqual([u['historical_unit_id']for u in w[team+'_units']],
                [u['historical_unit_id']for u in self.base['initial_state'][team+'_units']])
            self.assertEqual([u['personnel']['committed']for u in w[team+'_units']],
                [u['personnel']['committed']for u in self.base['initial_state'][team+'_units']])
        self.assertEqual((self.base,self.binding,seed),old);self.assertTrue(missions.validate(w))

    def test_exact64_and128_exercise_rosters_keep_explicit_provenance(self):
        for red,blue in [(56,8),(112,16)]:
            config=configuration(self.binding,red,blue);saved=copy.deepcopy(config)
            spec=sh.definition(self.binding,config);w=missions.from_definition(spec)
            self.assertEqual([len(w[t+'_units'])for t in ('red','blue')],[red,blue])
            self.assertEqual(config,saved);self.assertEqual(w['historical_initial'],self.snapshot)
            for _,u in missions.units(w):
                if '新增演习'in u['name']:
                    self.assertNotIn('historical_unit_id',u)
                    self.assertTrue(u.get('source_historical_unit_id'))
                    self.assertEqual(u.get('historical_evidence'),[])
            self.assertEqual(sh.from_binding(spec['historical_synthetic']),spec)
            self.assertTrue(missions.validate(w))

    def test_capacity_metadata_uses_the_existing_campaign_leaf_bound(self):
        from gentactix import formation_parts,scenario_basis
        self.assertEqual(sh.seed(self.binding)['configuration_limits']['max_units_per_team'],
            formation_parts.LIMITS[formation_parts.CAMPAIGN_VERSION][1])
        self.assertEqual(scenario_basis.exercise_seed('CA-AJ18-v1')['configuration_limits']['max_units_per_team'],12)

    def test_native_plugin_reads_the_same_readonly_limit_without_injecting_it_into_configuration(self):
        from backend import scenario_builder
        seed=sh.seed(self.binding);frozen=copy.deepcopy(seed)
        context={'scenario_composer':dict(mission_id=self.base['id'],historical_base=self.binding,seed=seed)}
        value=scenario_builder.execute_tool(context,dict(tool='get_scenario_basis'))
        self.assertEqual(value['configuration_limits']['max_units_per_team'],256)
        self.assertNotIn('configuration_limits',value['configuration'])
        self.assertEqual(seed,frozen)

    def test_large_capacity_never_bypasses_source_identity_or_upper_bound(self):
        config=configuration(self.binding,257,1)
        with self.assertRaisesRegex(ValueError,'256'):sh.definition(self.binding,config)
        config=configuration(self.binding,70,9)
        config['teams']['red'][0]['basis_id']=config['teams']['blue'][0]['basis_id']
        with self.assertRaisesRegex(ValueError,'同阵营|来源|绑定'):sh.definition(self.binding,config)

    def test_generic_legacy_configuration_retains_its_existing_bound(self):
        from verify_synthetic_configuration import configuration as legacy
        with self.assertRaisesRegex(ValueError,'12'):combined_arms.configure('CA-AJ18-v1',legacy(13,1))

    def test_ordinary_derivation_endpoint_returns_all79_units_and_shared_limits(self):
        from fastapi.testclient import TestClient
        from backend import main,scenario_builder as builder
        parent=dict(id='a'*32,mission_id=self.base['id'],construction={'source':'explicit_offline_fixture'})
        with tempfile.TemporaryDirectory()as directory,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':directory+'/sessions'}),\
                patch.object(builder,'historical_draft_base',return_value=(parent,copy.deepcopy(self.binding))):
            response=TestClient(main.app).post('/api/scenarios/from-historical',
                json=dict(base_draft_id=parent['id'],operation_id='b'*32,execution_backend='narrative'))
        self.assertEqual(response.status_code,200,response.text)
        value=response.json();self.assertEqual(value['configuration_limits']['max_units_per_team'],256)
        self.assertEqual([len(value['preview_world'][t+'_units'])for t in ('red','blue')],[70,9])
        self.assertIsNone(value['draft']['afsim'])


if __name__=='__main__':unittest.main(verbosity=2)
