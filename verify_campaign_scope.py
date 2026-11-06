"""Cumulative OOB opt-in is distinct from strict same-day historical presence."""
import copy
import unittest
from gentactix import historical_initial,historical_operations as op


class CampaignScopeTests(unittest.TestCase):
    def test_wuhan_legacy_reference_does_not_invent_blue_combat_units(self):
        from gentactix import campaign_scope
        s=historical_initial.initial('抗日战争-武汉会战-1938.06至1938.10',version='1.0.0')['historical_initial']
        with self.assertRaisesRegex(ValueError,'双方'):campaign_scope.select(s)

    def test_explicit_campaign_selects_all_nonoverlapping_leaves_with_sources(self):
        from gentactix import campaign_scope
        s=historical_initial.initial('抗日战争-武汉会战-1938.06至1938.10',version='1.1.0')['historical_initial']
        saved=copy.deepcopy(s);ids=campaign_scope.select(s);index={u['id']:u for u in s['definition']['units']}
        self.assertGreaterEqual(len(ids),64)
        self.assertEqual({index[i]['team'] for i in ids},{'red','blue'})
        self.assertTrue(all(index[i]['evidence'] for i in ids))
        for i in ids:
            parent=index[i]['parent_id']
            while parent:self.assertNotIn(parent,ids);parent=index[parent]['parent_id']
        self.assertEqual(s,saved)
        with self.assertRaises(ValueError):op.partition(s)

    def test_builder_exposes_qualified_campaign_deployment_without_changing_source(self):
        from backend import scenario_builder
        b=scenario_builder.historical_basis('抗日战争-武汉会战-1938.06至1938.10',version='1.1.0',force_scope='campaign')
        self.assertTrue(b['ready'],b['error']);p=b['configuration_template']
        self.assertIn('campaign_scope',p);self.assertIn('campaign',p)
        self.assertEqual(len(p['actors']),len(b['actors']))
        self.assertGreaterEqual(len(p['actors']),64)
        self.assertIn('估计',b['scope'])

    def test_79_leaf_world_freezes_all_source_identities_and_restore_is_exact(self):
        from tools.qa.large_formation_fixture import inputs
        from gentactix import missions,force_organization as f
        s,p=inputs();world=op.initial(s,p)
        self.assertEqual(len(world['red_units']),70);self.assertEqual(len(world['blue_units']),9)
        missions.validate(world)
        binding=world['mission']['definition']['historical_calculation']
        self.assertEqual(op.from_binding(binding),world['mission']['definition'])
        v=f.view(dict(id='b'*12,war_state=world,turn_count=0))
        self.assertEqual(v['totals']['red']['current'],210000)
        self.assertEqual(v['totals']['blue']['current'],72000)
        from backend import afsim_state
        session=dict(id='b'*12,war_state=world,turn_count=0,time_step='30分钟',execution_backend='afsim')
        initial=afsim_state.initial_observation(session)
        self.assertLessEqual(len(initial['units']),8)
        self.assertEqual(initial['force_organization']['totals'],v['totals'])
        self.assertNotIn('nodes',initial['force_organization'])

    def test_campaign_cannot_silently_revert_to_local_roster(self):
        from backend.scenario_assembly import validate_build_constraints
        from tools.qa.large_formation_fixture import inputs
        s,p=inputs()
        with self.assertRaisesRegex(ValueError,'范围'):validate_build_constraints(p,{'force_scope':'phase'})
        with self.assertRaises(ValueError):op.initial(s,{k:v for k,v in p.items() if k!='campaign'})
        p['actors'].pop(next(iter(p['actors'])))
        with self.assertRaises(ValueError):op.initial(s,p)

    def test_legacy_unit_order_is_independent_of_actor_json_key_order(self):
        from tools.qa.historical_operational_fixture import inputs
        s,p=inputs();original=op.definition(s,p)
        p['actors']=dict(reversed(list(p['actors'].items())))
        self.assertEqual(op.definition(s,p),original)


if __name__=='__main__':unittest.main()
