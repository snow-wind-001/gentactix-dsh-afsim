"""A sourced admission window can explicitly adopt its opening command tree."""
import copy
import unittest
from unittest.mock import patch

from gentactix import campaign_windows as cw, historical_initial as hi
from gentactix import historical_operations as ho, initial_command as ic

BATTLE = '抗日战争-武汉会战-1938.06至1938.10'
NOTE = '仅QA选择：采用来源阶段所列作战关系作为模型开局，不声称零时已发令或完整兵额。'


def source_and_window():
    pin = cw.pin('WH-northern-sep17-18', '1.3.0')
    d = copy.deepcopy(pin['definition'])
    snapshot = hi.initial(BATTLE, d['start_phase_id'],
                          version=d['historical_initial']['version'])['historical_initial']
    phase = next(p for p in snapshot['definition']['phases'] if p['id'] == snapshot['phase_id'])
    d['version'] = '1.4.0'
    d['opening_command'] = dict(version='source-opening-command-1',
                               phase_id=snapshot['phase_id'],
                               relation_ids=[r['id'] for r in ic.relations(snapshot)],
                               scope=NOTE, evidence=copy.deepcopy(phase['evidence']))
    return snapshot, dict(format=cw.FORMAT, id=d['id'], version=d['version'],
                          definition_hash=hi.digest(d), definition=d)


def controls(snapshot, pin):
    return dict(campaign_scope={'version':'campaign-oob-window-1', 'window':pin,
                               'planning_end':pin['definition']['bounds']['end']},
                clock={'start':pin['definition']['bounds']['start']},
                initial_command={'version':ic.VERSION, 'assumption':NOTE})


class WindowCommandTests(unittest.TestCase):
    def test_staged_model_observes_pinned_opening_choice_and_cannot_edit_source(self):
        from backend import scenario_builder, scenario_assembly
        basis = scenario_builder.historical_basis(
            BATTLE, force_scope='campaign', campaign_window_id='WH-northern-sep17-18',
            campaign_window_version='1.4.0', time_step='1小时', termination_mode='objectives')
        assembly = scenario_assembly.create(basis)
        self.addCleanup(scenario_assembly.close, assembly.id)
        original = copy.deepcopy(assembly.export_state())
        for part in ('globals', 'final'):
            view = assembly.tool(part, 'get_scenario_basis', {})
            declaration = view['readonly_campaign_window']['opening_command']
            self.assertEqual(declaration, basis['campaign_window']['definition']['opening_command'])
            self.assertEqual(len(declaration['relation_ids']), 3)
            self.assertIn('initial_command.assumption', view['readonly_campaign_window']['instruction'])
            declaration['relation_ids'].clear()
        self.assertEqual(assembly.export_state(), original)

    def test_registered_window_template_requires_explicit_opening_choice(self):
        snapshot, pin = source_and_window()
        with patch.object(cw, 'load', return_value=pin['definition']):
            template = ho.configuration_template(snapshot, 'campaign', window=pin,
                                                 termination_mode='objectives')
        self.assertEqual(template['initial_command'], {'version':ic.VERSION, 'assumption':None})
        self.assertEqual(len(template['actors']), 8)

    def test_window_command_binds_source_and_window_without_changing_administration(self):
        snapshot, pin = source_and_window()
        original = copy.deepcopy(snapshot)
        with patch.object(cw, 'load', return_value=pin['definition']):
            result = ic.validate(snapshot, controls(snapshot, pin))
        for identity in ('ww2.cn.army71', 'ww2.cn.army30', 'ww2.cn.army42'):
            self.assertEqual(result['parents'][identity], 'ww2.cn.group2')
        self.assertEqual(result['window'], {k:pin[k] for k in ('id','version','definition_hash')})
        self.assertEqual(snapshot, original)
        self.assertEqual(len(result['relation_ids']), 3)

    def test_frozen_window_restores_without_current_registry(self):
        snapshot, pin = source_and_window()
        with patch.object(cw, 'load', side_effect=AssertionError('Frozen recovery must use its pin')):
            result = ic.validate(snapshot, controls(snapshot, pin), frozen=True)
        self.assertEqual(result['parents']['ww2.cn.army71'], 'ww2.cn.group2')

    def test_declared_window_cannot_drop_opening_choice_even_when_frozen(self):
        snapshot, pin = source_and_window()
        p = controls(snapshot, pin)
        p.pop('initial_command')
        with patch.object(cw, 'load', return_value=pin['definition']):
            for frozen in (False, True):
                with self.subTest(frozen=frozen), self.assertRaises(ValueError):
                    ic.validate(snapshot, p, frozen=frozen)

    def test_legacy_window_and_cumulative_oob_keep_their_prior_contract(self):
        old = cw.pin('WH-northern-sep17-18', '1.3.0')
        snapshot = hi.initial(BATTLE, old['definition']['start_phase_id'],
                              version=old['definition']['historical_initial']['version'])['historical_initial']
        p = controls(snapshot, old)
        with self.assertRaises(ValueError):
            ic.validate(snapshot, p)
        p.pop('initial_command')
        self.assertIsNone(ic.validate(snapshot, p, frozen=True))
        p['campaign_scope'] = {'version':'campaign-oob-deployment-2'}
        self.assertIsNone(ic.validate(snapshot, p))
        p['initial_command'] = {'version':ic.VERSION, 'assumption':NOTE}
        with self.assertRaises(ValueError):
            ic.validate(snapshot, p)

    def test_declaration_rejects_other_phase_unknown_omitted_or_duplicate_relations(self):
        snapshot, pin = source_and_window()
        for change in ('phase', 'unknown', 'omitted', 'duplicate'):
            value = copy.deepcopy(pin['definition'])
            d = value['opening_command']
            if change == 'phase': d['phase_id'] = 'campaign_reference'
            if change == 'unknown': d['relation_ids'][0] = 'unverified-command'
            if change == 'omitted': d['relation_ids'].pop()
            if change == 'duplicate': d['relation_ids'].append(d['relation_ids'][0])
            with self.subTest(change=change), self.assertRaises(ValueError):
                cw.validate_definition(value, snapshot)

    def test_invalid_window_hash_and_clock_cannot_bind_a_command_tree(self):
        snapshot, pin = source_and_window()
        for change in ('hash', 'clock'):
            p = controls(snapshot, copy.deepcopy(pin))
            if change == 'hash': p['campaign_scope']['window']['definition_hash'] = '0'*64
            if change == 'clock': p['clock']['start'] = '1938-09-18 00:00'
            with patch.object(cw, 'load', return_value=pin['definition']):
                with self.subTest(change=change), self.assertRaises(ValueError):
                    ic.validate(snapshot, p, frozen=True)


if __name__ == '__main__':
    unittest.main()
