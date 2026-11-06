"""Proof-bound candidate paging over all22 source-bound actors; no API/model."""
import copy
import json
import subprocess
import unittest
from unittest.mock import patch

from backend import harness_engine as h, turn_preview as p
from tools.qa.turn_preview_page_fixture import session, candidate
from gentactix import missions, turn_settlement


class TurnPreviewPageTests(unittest.TestCase):
    def setUp(self):
        self.s = session()
        self.o = h.RunObserver('offline full22 preview paging')
        self.ctx = p.context(self.s, None, operation_id=self.o.operation_id)
        self.value = candidate(self.s['war_state'])
        self.reply = p.execute(self.ctx, dict(tool=p.TOOL, args=dict(candidate=self.value)))
        self.assertTrue(self.reply['ok'], self.reply)
        self.events = [
            dict(type='tool/call', seq=1, data=dict(name=p.TOOL, callId='preview', arguments=dict(candidate=self.value))),
            dict(type='tool/result', seq=2, data=dict(message=dict(toolCallId='preview',
                 content=[dict(type='text', text=json.dumps(self.reply))])))]

    def query(self, args=None, *, ctx=None, events=None):
        payload = dict(tool='get_turn_preview', session_id='qa-current-native',
                       args={'preview_hash':self.reply['digest'], **(args or {})},
                       preview_events=copy.deepcopy(self.events if events is None else events))
        return p.get_preview(self.ctx if ctx is None else ctx, payload)

    def test_registered22_tail_is_read_from_candidate_not_initial_observation(self):
        before = copy.deepcopy((self.s, self.ctx, self.value, self.events))
        with patch('gentactix.missions.advance', side_effect=AssertionError('No effect executor')):
            reply = self.query(dict(offset=16, limit=16))
        self.assertTrue(reply['ok'], reply)
        self.assertTrue(reply['readonly'])
        self.assertEqual(reply['total'], 22)
        self.assertEqual(len(reply['items']), 6)
        self.assertEqual({row['team'] for row in reply['items']}, {'red', 'blue'})
        self.assertEqual(reply['settlement_version'], 'turn-settlement-3')
        self.assertEqual(reply['next_args'], None)
        unit = next(u for u in self.s['war_state']['blue_units'] if u['name'] == '日军第106师团')
        row = next(u for u in reply['items'] if u['name'] == unit['name'])
        self.assertLess(row['food_after'], unit['logistics']['food'])
        self.assertEqual((self.s, self.ctx, self.value, self.events), before)

    def test_preview_offers_tail_query_without_changing_its_v3_summary(self):
        self.assertEqual(len(self.reply['settlement']['units']), 16)
        args = self.reply['next_units_args']
        self.assertEqual(args, dict(preview_hash=self.reply['digest'], kind='units', offset=16, limit=16))
        self.assertTrue(self.query(args)['ok'])

    def test_all22_pages_include_both_sides_and_preserve_classified_stocks(self):
        args = dict(kind='units', offset=0, limit=5)
        rows = []
        while args:
            reply = self.query(args)
            self.assertTrue(reply['ok'], reply)
            rows += reply['items']; args = reply['next_args']
            if args:
                self.assertEqual(args['preview_hash'], self.reply['digest'])
                self.assertEqual(args['kind'], 'units')
        self.assertEqual(len({(r['team'],r['name']) for r in rows}), 22)
        original = {(t,u['name']):u for t,u in missions.units(self.s['war_state'])}
        for row in rows:
            for key, stock in row['classified_inventory'].items():
                self.assertEqual(stock['before'], original[row['team'],row['name']]['formation'][key])
                self.assertEqual(stock['after'], stock['before'])
        rows[0]['food_after'] = -100
        self.assertGreater(self.query()['items'][0]['food_after'], 0)

    def test_goals_page_independently_and_keep_its_query_kind(self):
        args = dict(kind='goals', limit=1)
        rows = []
        while args:
            reply = self.query(args); self.assertTrue(reply['ok'], reply)
            rows += reply['items']; args = reply['next_args']
            if args:self.assertEqual(args['kind'], 'goals')
        self.assertGreater(len(rows), 1)
        self.assertEqual(len(rows), len({r['id'] for r in rows}))

    def test_missing_cross_operation_and_changed_world_proofs_are_rejected(self):
        self.assertFalse(self.query(events=[])['ok'])
        other = copy.deepcopy(self.ctx); other['turn_preview']['operation_id'] = 'different'
        self.assertFalse(self.query(ctx=other)['ok'])
        changed = copy.deepcopy(self.ctx); changed['session']['war_state']['red_units'][0]['logistics']['food'] -= 1
        self.assertFalse(self.query(ctx=changed)['ok'])
        self.assertFalse(self.query(dict(preview_hash='a'*64))['ok'])

    def test_tampered_summary_or_self_consistent_fake_after_hash_cannot_page(self):
        for forged_hash in (False, True):
            events = copy.deepcopy(self.events)
            reply = json.loads(events[1]['data']['message']['content'][0]['text'])
            if forged_hash:
                reply['after_hash'] = 'f'*64
                value = p.normalize(self.ctx,self.value)
                reply['digest'] = p._digest(self.ctx,value,reply['after_hash'],reply['settlement_hash'])
            else:reply['settlement']['units'][0]['food_after'] += 1
            events[1]['data']['message']['content'][0]['text'] = json.dumps(reply)
            self.assertFalse(self.query(dict(preview_hash=reply['digest']), events=events)['ok'])

    def test_strict_paging_and_operation_gates(self):
        for args in (dict(offset=-1),dict(offset=True),dict(limit=True),dict(limit=17),dict(offset=23),
                     dict(kind='world'),dict(candidate={}),dict(preview_hash='wrong')):
            with self.subTest(args=args):self.assertFalse(self.query(args)['ok'])
        for key,value in (('agent_mode','json'),('execution_backend','afsim')):
            other = copy.deepcopy(self.ctx);other['session'][key]=value
            self.assertFalse(self.query(ctx=other)['ok'])
        other = copy.deepcopy(self.ctx);other.pop('turn_preview')
        self.assertFalse(self.query(ctx=other)['ok'])
        self.assertEqual(self.query(dict(offset=22))['items'], [])

    def test_legacy_v2_preview_keeps_its_version_and_original_fields(self):
        with patch.object(turn_settlement,'VERSION',turn_settlement.LEGACY_VERSION):
            reply = p.execute(self.ctx,dict(tool=p.TOOL,args=dict(candidate=self.value)))
        events = copy.deepcopy(self.events)
        events[1]['data']['message']['content'][0]['text'] = json.dumps(reply)
        page = self.query(dict(preview_hash=reply['digest'],offset=16),events=events)
        self.assertTrue(page['ok'],page)
        self.assertEqual(page['settlement_version'],'turn-settlement-2')
        self.assertNotIn('fatigue',page['items'][0])
        self.assertNotIn('personnel_strength_pct',page['items'][0])

    def test_normal_dispatch_and_role_policy_share_the_new_readonly_tool(self):
        from backend.main import _native_tool_dispatch
        payload = dict(tool=p.READ_TOOL,session_id='qa-current-native',
                       args=dict(preview_hash=self.reply['digest'],offset=16),preview_events=self.events)
        reply = _native_tool_dispatch(self.ctx,payload)
        self.assertTrue(reply['ok'],reply)
        self.assertEqual(len(reply['items']),6)
        self.assertIn(p.READ_TOOL,h.role_policy('engine',tools=True,process=True)['allowed_tools'])
        self.assertNotIn(p.READ_TOOL,h.role_policy('engine',tools=True,process=True,unit=True)['allowed_tools'])
        self.assertNotIn(p.READ_TOOL,h.role_policy('engine',tools=True,process=True,external=True)['allowed_tools'])
        self.assertNotIn(p.READ_TOOL,h.role_policy('chat',tools=True)['allowed_tools'])

    def test_full22_public_evidence_survives_actual_javascript_json_transport(self):
        node = subprocess.run(['node','-e',
            "let raw='';process.stdin.setEncoding('utf8');process.stdin.on('data',x=>raw+=x);process.stdin.on('end',()=>process.stdout.write(JSON.stringify(JSON.parse(raw))));"],
            input=json.dumps(self.events),text=True,capture_output=True)
        self.assertEqual(node.returncode,0,node.stderr)
        page = self.query(dict(offset=16),events=json.loads(node.stdout))
        self.assertTrue(page['ok'],page)
        self.assertEqual(page['after_hash'],self.reply['after_hash'])
        self.assertEqual(len(page['items']),6)


if __name__ == '__main__':
    unittest.main()
