"""Edited campaign exercises keep per-unit processes and frozen history distinct."""
import copy
import os
import tempfile
import unittest
from unittest.mock import patch

from gentactix import campaign, historical_operations as ho, missions, synthetic_history as sh
from tools.qa.campaign_fixture import inputs


class SyntheticCampaignTests(unittest.TestCase):
    def setUp(self):
        self.snapshot, self.params = inputs()
        self.base = ho.definition(self.snapshot, self.params)
        self.binding = self.base['historical_calculation']
        self.config = sh.seed(self.binding)['configuration']

    def edited(self, config=None):
        return sh.definition(self.binding, config if config is not None else self.config)

    def test_added_exercise_unit_has_its_own_frozen_process_and_unchanged_history(self):
        before = copy.deepcopy(self.binding)
        row = copy.deepcopy(self.config['teams']['blue'][1])
        row.update(name='蓝方增援演习单位', personnel=700)
        self.config['teams']['blue'].append(row)
        spec = self.edited(); world = missions.from_definition(spec)
        unit = world['blue_units'][-1]; origin = self.base['initial_state']['blue_units'][1]
        key = campaign.actor_key(unit)
        self.assertNotEqual(key, campaign.actor_key(origin))
        self.assertTrue(key.startswith('exercise.'))
        self.assertNotIn('historical_unit_id', unit)
        self.assertEqual(campaign.scheduled_time(spec['campaign_definition'], unit),
                         campaign.scheduled_time(self.base['campaign_definition'], origin))
        self.assertEqual(set(world['campaign']['actors']), {u['name'] for _, u in missions.units(world)})
        self.assertEqual(world['campaign']['actors'][unit['name']]['base_protection'], unit['formation']['protection'])
        self.assertEqual(campaign.release_seconds(world, unit), 3600)
        with self.assertRaisesRegex(ValueError, '尚处集结'):
            campaign.check_order(world, {'unit': unit['name'], 'action': 'move'})
        self.assertEqual(world['historical_initial'], self.snapshot)
        self.assertEqual(self.binding, before)
        self.assertEqual(sh.from_binding(spec['historical_synthetic']), spec)
        unit['exercise_unit_id'] = 'exercise.tampered'
        with self.assertRaises(ValueError): missions.validate(world)

    def test_removed_and_renamed_units_leave_no_stale_process_rows(self):
        removed = self.config['teams']['blue'].pop()
        old = self.config['teams']['red'][0]['name']
        self.config['teams']['red'][0]['name'] = '重命名演习单位'
        world = missions.from_definition(self.edited())
        self.assertNotIn(old, world['campaign']['actors'])
        self.assertNotIn(removed['name'], world['campaign']['actors'])
        keys = {campaign.actor_key(u) for _, u in missions.units(world)}
        spec = world['mission']['definition']['campaign_definition']
        self.assertEqual(set(spec['arrivals']), keys)
        self.assertEqual(set(spec['fortifications']), keys)
        self.assertEqual(len(campaign.observation(world)['actors']), 2)

    def test_no_edit_preserves_arrival_timing_and_model_parameters(self):
        world = missions.from_definition(self.edited())
        self.assertEqual(world['mission']['definition']['campaign_definition'], self.base['campaign_definition'])
        self.assertEqual(world['campaign'], self.base['initial_state']['campaign'])
        self.assertEqual(self.edited(), self.edited())

    def test_legacy_frozen_exercise_is_restored_without_new_revision(self):
        legacy = {'format': sh.FORMAT, 'base': self.binding, 'configuration': self.config}
        old = sh.from_binding(legacy)
        self.assertNotIn('campaign_revision', old['historical_synthetic'])
        missions.validate(missions.from_definition(old))
        bad = copy.deepcopy(legacy); bad['campaign_revision'] = 'unknown'
        with self.assertRaises(ValueError): sh.from_binding(bad)

    def test_renamed_calculation_parts_keep_distinct_scheduled_arrivals(self):
        from gentactix import formation_parts as fp
        identity = next(iter(self.params['actors']))
        parent = self.params['actors'][identity]
        count = parent['personnel']; equipment = parent['equipment']
        parts = []
        for i in range(2):
            parts.append({'id': 'part'+str(i), 'label': '梯队'+str(i),
                'personnel': count//2 + (count % 2 if i == 0 else 0),
                'equipment': {k: v if i == 0 else 0 for k,v in equipment.items()},
                'resources': {k: parent['formation'][k] if i == 0 else 0 for k in fp.RESOURCES},
                'position': copy.deepcopy(parent['position']), 'dispersion_km2': .2,
                'assumption': '仅软件测试的互斥计算划分'})
        self.params['partitions'] = {'version': fp.VERSION, 'groups': {identity: {
            'parts': parts, 'assumption': '软件QA分梯队，不是实际历史下级'}}}
        self.params['campaign']['arrivals'][identity]['parts'] = {
            'part0': {'not_before': '1938-03-31T00:00', 'assumption': 'QA先头'},
            'part1': {'not_before': '1938-03-31T00:30', 'assumption': 'QA后续'}}
        base = ho.definition(self.snapshot, self.params); binding = base['historical_calculation']
        config = sh.seed(binding)['configuration']; config['teams']['red'][1]['name'] = '更名后续梯队'
        original = copy.deepcopy(config['teams']['red'][0]); original['name'] = '新增先头梯队'
        config['teams']['red'].append(original)
        world = missions.from_definition(sh.definition(binding, config))
        red = world['red_units']
        self.assertEqual([campaign.release_seconds(world,u) for u in red], [0, 1800, 0])
        config['teams']['red'].pop(0)
        world = missions.from_definition(sh.definition(binding, config))
        self.assertEqual([campaign.release_seconds(world,u) for u in world['red_units']], [1800, 0])

    def test_normal_api_validates_then_initializes_the_edited_campaign(self):
        from backend import main, scenario_builder as builder, session_store
        from fastapi.testclient import TestClient
        client = TestClient(main.app)
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'GENTACTIX_SESSION_DIR': folder+'/sessions'}):
            base = builder.stage_historical(self.snapshot, self.params,
                construction={'source':'dsh_native_skill'}, execution_backend='narrative')
            response = client.post('/api/scenarios/from-historical', json={
                'base_draft_id':base['id'], 'execution_backend':'narrative'})
            self.assertEqual(response.status_code, 200, response.text)
            draft = response.json()['draft']; config = copy.deepcopy(draft['configuration'])
            added = copy.deepcopy(config['teams']['red'][0]); added['name'] = 'API新增演习单位'
            config['teams']['red'].append(added)
            result = client.post('/api/scenarios/validate', json={'mission_id':'',
                'parent_draft_id':draft['id'], 'configuration':config, 'execution_backend':'narrative'})
            self.assertEqual(result.status_code, 200, result.text)
            verified = result.json(); self.assertIn('API新增演习单位', verified['preview_world']['campaign']['actors'])
            created = client.post('/api/sessions', json={'battle':self.base['battle'],
                'scenario':self.base['title'],
                'time_step':'30分钟',
                'product_mode':'synthetic', 'execution_backend':'narrative',
                'scenario_draft_id':verified['id'], 'mission_id':verified['mission_id']})
            self.assertEqual(created.status_code, 200, created.text)
            sid = created.json()['session_id']
            try:
                initialized = client.post(f'/api/sessions/{sid}/init')
                self.assertEqual(initialized.status_code, 200, initialized.text)
                session_store.validate(session_store.serializable(main._SESSIONS[sid]))
                self.assertEqual(main._SESSIONS[sid]['war_state']['historical_initial'], self.snapshot)
            finally: main._SESSIONS.pop(sid, None)


if __name__ == '__main__': unittest.main(verbosity=2)
