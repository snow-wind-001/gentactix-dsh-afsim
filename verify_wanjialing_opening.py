"""A15h source command opening must be usable without rewriting older games."""
import copy
from datetime import datetime
import unittest
from unittest.mock import patch

from gentactix import campaign_windows as cw, historical_initial as hi
from gentactix import historical_operations as ho, initial_command as ic

BATTLE = '抗日战争-万家岭战役-1938.09下旬至1938.10'
WINDOW = 'WJL-oct6pm-10'


class WanjialingOpeningTests(unittest.TestCase):
    def basis(self):
        from backend.scenario_builder import historical_basis
        return historical_basis(BATTLE, force_scope='campaign',
            campaign_window_id=WINDOW, campaign_window_version='1.0.0',
            termination_mode='objectives', time_step='1小时')

    def test_normal_basis_admits22identities_with_explicit15h_source_command(self):
        b = self.basis()
        self.assertTrue(b['ready'])
        self.assertEqual(len(b['actors']), 22)
        self.assertEqual(b['initial']['version'], '1.7.0')
        self.assertEqual(b['configuration_template']['clock']['start'], '1938-10-06T15:00:00')
        self.assertEqual(b['configuration_template']['initial_command']['version'], ic.VERSION)
        self.assertIsNone(b['configuration_template']['initial_command']['assumption'])

    def test_registered_window_is_bound_to_source_and_matching_objective_guidance(self):
        pin = cw.pin(WINDOW, '1.0.0')
        s = hi.initial(BATTLE, 'oct6_orders', version='1.7.0')['historical_initial']
        self.assertEqual(cw.validate(s, pin), cw.select(s, pin, frozen=True))
        self.assertEqual(pin['definition']['historical_initial']['definition_hash'], s['definition_hash'])
        guide = ho.objective_guidance(s)
        self.assertEqual(guide['binding']['initial_version'], s['version'])
        self.assertEqual(guide['binding']['initial_definition_hash'], s['definition_hash'])

    def test_source_relations_cover_only_three_ordered_armies_and_keep_administration(self):
        old = hi.definition(BATTLE, '1.6.0')
        new = hi.definition(BATTLE, '1.7.0')
        self.assertEqual(old['units'], new['units'])
        self.assertEqual(old['sources'], new['sources'])
        s = hi._materialize(new, 'oct6_orders')['historical_initial']
        rows = ic.relations(s)
        self.assertEqual({r['child_id'] for r in rows},
                         {'ww2.cn.army4', 'ww2.cn.army66', 'ww2.cn.army74'})
        self.assertTrue(all(r['parent_id'] == 'ww2.cn.corps1' for r in rows))
        self.assertTrue(all(r['kind'] == 'operational_command' for r in rows))
        self.assertTrue(all('119' in r['evidence'][0]['locator'] and '15' in r['evidence'][0]['locator'] for r in rows))
        self.assertFalse(new['sources']['WJL_GUO']['original_archive_examined'])
        self.assertEqual(ic.parents(s)['ww2.cn.division161.wjl_part'], 'ww2.cn.division161')
        # The source event is an instruction, not proof of actual arrival/action.
        phase = next(p for p in new['phases'] if p['id'] == 'oct6_orders')
        order = next(o for o in phase['operations'] if o['id'] == 'WJL-Oct6-orders')
        self.assertEqual(order['kind'], 'command')
        self.assertEqual(order['date']['precision'], 'hour')

    def test_runtime_binding_requires_explicit_choice_and_rejects_pre_order_clock(self):
        b = self.basis(); s = b['initial']; p = copy.deepcopy(b['configuration_template'])
        with self.assertRaises(ValueError):
            ic.validate(s, p)
        p['initial_command']['assumption'] = '按论文记载采用15时关系为计算开局；到场、人员和部署仍为显式估计。'
        binding = ic.validate(s, p)
        self.assertEqual(binding['parents']['ww2.cn.army66'], 'ww2.cn.corps1')
        p['clock']['start'] = '1938-10-06T14:00:00'
        with self.assertRaises(ValueError):
            ic.validate(s, p)

    def test_old_window_and_default_keep_prior_source_without_implicit_migration(self):
        old = cw.pin('WJL-oct6-10', '1.7.0')
        self.assertEqual(old['definition']['historical_initial']['version'], '1.6.0')
        self.assertNotIn('opening_command', old['definition'])
        self.assertEqual(old['definition']['bounds']['start'], '1938-10-06T00:00:00')
        self.assertEqual(hi.definition(BATTLE)['version'], '1.0.0')
        self.assertIn(WINDOW, {r['id'] for r in cw.catalog(BATTLE)})

    def test_global_prior_clock_and_planning_budget_match_new_window(self):
        pin = cw.pin(WINDOW, '1.0.0'); d = pin['definition']
        prior = d['parameter_estimates']['global_priors']
        self.assertEqual(prior['clock']['start'], d['bounds']['start'])
        self.assertEqual(prior['campaign_scope']['planning_end'], d['bounds']['end'])
        self.assertGreater(datetime.fromisoformat(d['bounds']['end']), datetime.fromisoformat(prior['clock']['start']))
        self.assertIsNone(prior.get('initial_command'))
        # Existing strengths/equipment remain model estimates, not historical facts.
        old = cw.load('WJL-oct6-10', '1.7.0')
        self.assertEqual(d['parameter_estimates']['actors'], old['parameter_estimates']['actors'])

    def test_declared_estimates_produce_a_real22unit_world_and_five_command_members(self):
        from gentactix import commands, force_organization as forces
        b = self.basis(); p = copy.deepcopy(b['configuration_template'])
        p['initial_command']['assumption'] = 'QA采用15时来源指挥；数值、部署及开局在场为显式估计。'
        world = ho.initial(b['initial'], p)
        session = dict(id='wjl-opening-test', turn_count=0, role_epoch=0,
                       product_mode='historical', simulation_mode='open',
                       execution_backend='afsim', time_step='1小时', war_state=world)
        saved = copy.deepcopy(world)
        selected = set(forces.effective_member_ids(session, 'ww2.cn.corps1'))
        units = commands.resolve_units(session)
        self.assertEqual({row[0]['name'] for identity,row in units.items() if identity in selected},
                         {'第90师','第159师','第160师','第51师','第58师'})
        self.assertEqual(len(world['red_units']) + len(world['blue_units']), 22)
        queue = forces.queue(session, 'ww2.cn.corps1', {'action':'hold','duration':'next'})
        self.assertEqual({o['unit_id'] for o in queue['orders']}, selected)
        self.assertEqual(world, saved)
        self.assertEqual(world['current_time'], '1938-10-06 15:00')

    def test_rebased_arrival_priors_are_explicit_estimates_not_preopening_times(self):
        window = cw.load(WINDOW, '1.0.0')
        start = datetime.fromisoformat(window['bounds']['start'])
        old = cw.load('WJL-oct6-10', '1.7.0')['parameter_estimates']['global_priors']['campaign']['arrivals']
        rows = window['parameter_estimates']['global_priors']['campaign']['arrivals']
        for identity,row in rows.items():
            self.assertGreaterEqual(datetime.fromisoformat(row['not_before']), start)
            if datetime.fromisoformat(old[identity]['not_before']) < start:
                self.assertEqual(row['not_before'], window['bounds']['start'])
                self.assertIn('不代表史实到场', row['assumption'])
            else:
                self.assertEqual(row, old[identity])

    def test_frozen_recovery_and_temporary_attachment_keep_mutually_exclusive_command(self):
        from gentactix import commands, force_organization as forces
        b = self.basis(); p = copy.deepcopy(b['configuration_template'])
        p['initial_command']['assumption'] = 'QA15时来源指挥基线，临时配属优先；不补全未知余部。'
        session = dict(id='wjl-opening-frozen-test', turn_count=0, role_epoch=0,
            product_mode='historical', simulation_mode='open', execution_backend='afsim',
            time_step='1小时', war_state=ho.initial(b['initial'], p))
        physical = copy.deepcopy(session['war_state'])
        member = next(i for i,(e,u) in commands.resolve_units(session).items() if e['name']=='第159师')
        session['force_organization'] = forces.detach(session, [member], '独立警戒分遣群', 'QA明确临时配属，保留原人员装备库存账。')
        restored = copy.deepcopy(session)
        with patch.object(cw, 'load', side_effect=AssertionError('Frozen command uses inline source/window')):
            view = forces.view(restored)
            self.assertEqual(len(forces.effective_member_ids(restored,'ww2.cn.corps1')), 4)
            self.assertNotIn(member, forces.effective_member_ids(restored,'ww2.cn.army66'))
        self.assertEqual(view['groups'][0]['member_ids'], [member])
        self.assertEqual(session['war_state'], physical)
        self.assertEqual(restored['war_state'], physical)

    def test_native_source_observation_retains_command_and_task_guidance_without_rag(self):
        from backend import scenario_assembly
        basis = self.basis(); assembly = scenario_assembly.create(basis)
        self.addCleanup(scenario_assembly.close, assembly.id)
        saved = copy.deepcopy(assembly.export_state())
        for part in ('globals','final'):
            view = assembly.tool(part, 'get_scenario_basis', {})
            self.assertEqual(len(view['readonly_campaign_window']['opening_command']['relation_ids']),3)
            self.assertIn('initial_command.assumption',view['readonly_campaign_window']['instruction'])
        self.assertEqual(assembly.export_state(), saved)
        self.assertIn('第66军',basis['objective_guidance']['objective_label'])
        self.assertEqual(basis['objective_guidance']['binding']['initial_version'],'1.7.0')

    def test_objective_pin_rejects_changed_definition_even_if_source_metadata_is_unchanged(self):
        for rehash in (False, True):
            snapshot = hi.initial(BATTLE, 'oct6_orders', version='1.7.0')['historical_initial']
            snapshot['definition']['coverage']['notes'].append('QA changed source contents under same version')
            if rehash:
                snapshot['definition_hash'] = hi.digest(snapshot['definition'])
            with self.subTest(rehash=rehash), self.assertRaisesRegex(ValueError, '初态|目标'):
                ho.objective_guidance(snapshot)


if __name__ == '__main__':
    unittest.main()
