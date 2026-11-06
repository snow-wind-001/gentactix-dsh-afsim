"""Regressions for versioned objectives and persistent campaign command identity."""
import copy
import unittest

from gentactix import commands, force_organization as forces, historical_initial as hi
from gentactix import historical_operations as ho


class ObjectiveBindingTests(unittest.TestCase):
    def test_corrected_changsha_source_is_not_borrowed_by_old_version(self):
        battle = next(r['battle'] for r in hi.catalog() if r['profile_id'] == 'AJ09-changsha2')
        old = hi.initial(battle, 'dayun_sep7', version='1.0.0')['historical_initial']
        with self.assertRaisesRegex(ValueError, '1.1.0'):
            ho.configuration_template(old)
        current = hi.initial(battle, 'dayun_sep7', version='1.1.0')['historical_initial']
        guidance = ho.objective_guidance(current)
        self.assertEqual(guidance['binding']['initial_version'], '1.1.0')
        self.assertIn('DAYUN_PUBLISHER', {s['id'] for s in guidance['sources']})

    def test_same_source_id_with_changed_content_cannot_rebind_objective(self):
        battle = next(r['battle'] for r in hi.catalog() if r['profile_id'] == 'AJ09-changsha2')
        s = hi.initial(battle, 'dayun_sep7', version='1.1.0')['historical_initial']
        s['definition']['sources']['DAYUN_PUBLISHER']['title'] += ' QA altered'
        s['definition_hash'] = hi.digest(s['definition'])
        with self.assertRaisesRegex(ValueError, '来源'):
            ho.objective_guidance(s)


class ForceMemberTests(unittest.TestCase):
    def partitioned_session(self):
        from verify_campaign_partitions import CampaignPartitionTests
        case = CampaignPartitionTests(); case.setUp()
        return dict(id='campaign-members', time_step='30分钟', turn_count=0,
                    execution_backend='afsim', war_state=ho.initial(case.s, case.p))

    def test_members_pages_distinguish_equal_calculation_parts_and_cover_all(self):
        s = self.partitioned_session()
        ids = [i for i, (e, _) in commands.resolve_units(s).items() if e['team'] == 'red']
        s['force_organization'] = forces.detach(s, ids, '编组QA', '同一父级互斥计算叶子')
        group = s['force_organization']['groups'][0]['id']
        before = copy.deepcopy(s); args = {'kind':'members', 'node_id':group, 'limit':7}
        rows = []
        while args:
            value = forces.observation(s, args)
            self.assertLessEqual(len(value['items']), 7)
            rows.extend(value['items']); args = value['next_args']
        self.assertEqual({r['command_id'] for r in rows}, set(ids))
        self.assertEqual(len({r['leaf_key'] for r in rows}), 32)
        self.assertEqual(len({r['calculation_unit_id'] for r in rows}), 32)
        self.assertTrue(all(r['task_group_id'] == group for r in rows))
        self.assertEqual(s, before)

    def test_stale_member_page_revision_is_rejected(self):
        s = self.partitioned_session(); ids = list(commands.resolve_units(s))[:2]
        s['force_organization'] = forces.detach(s, ids, '编组QA', 'QA')
        revision = forces.state(s)['revision']
        s['force_organization'] = forces.detach(s, ids[:1], '分遣QA', 'QA')
        with self.assertRaisesRegex(ValueError, '修订'):
            forces.observation(s, {'kind':'members', 'revision':revision})

    def test_decision_trace_freezes_task_members_without_mutating_session(self):
        from unittest.mock import patch
        from backend import extensions
        from gentactix import missions
        s=self.partitioned_session();s['use_adjudicator']=False
        ids=list(commands.resolve_units(s))[:2]
        s['force_organization']=forces.detach(s,ids,'轨迹任务群','QA组织快照')
        original=copy.deepcopy(s)
        with patch.object(extensions.registry,'emit',return_value={}):
            record=extensions.prepare_record(s,before=s['war_state'],after=s['war_state'],turn=1)
        self.assertEqual(record['force_organization']['groups'],s['force_organization']['groups'])
        self.assertEqual(record['force_organization_hash'],missions.digest(record['force_organization']))
        s['force_organization']['groups'].clear()
        self.assertEqual(record['force_organization']['groups'],original['force_organization']['groups'])


class CoverageContractTests(unittest.TestCase):
    def test_unknown_children_cannot_claim_whole_parent_or_hide_remainder(self):
        from tools.qa.large_formation_fixture import inputs
        from gentactix import campaign_scope
        snapshot,p=inputs()
        rows=campaign_scope.coverage(snapshot)
        self.assertTrue(rows)
        self.assertTrue(all(r['children_coverage']=='unknown' for r in rows))
        key=next(iter(p['campaign_scope']['remainders']))
        p['campaign_scope']['remainders'][key]['policy']='covered_by_children'
        with self.assertRaisesRegex(ValueError,'完整'):
            ho.initial(snapshot,p)
        p['campaign_scope']['remainders'].pop(key)
        with self.assertRaisesRegex(ValueError,'余部'):
            ho.initial(snapshot,p)

    def test_legacy_frozen_scope_restores_but_new_generation_requires_coverage(self):
        from tools.qa.large_formation_fixture import inputs
        snapshot,p=inputs();p['campaign_scope'].pop('remainders',None)
        p['campaign_scope']['version']='campaign-oob-deployment-1'
        with self.assertRaisesRegex(ValueError,'覆盖'):
            ho.definition(snapshot,p)
        binding={'format':ho.FORMAT,'initial':snapshot,'parameters':p}
        restored=ho.from_binding(binding)
        self.assertEqual(restored,ho.from_binding(copy.deepcopy(binding)))


if __name__ == '__main__':
    unittest.main()
