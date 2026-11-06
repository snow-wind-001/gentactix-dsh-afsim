"""A unit command must checkpoint its own session, not every loaded campaign."""
import copy
import unittest
from unittest.mock import patch

from backend import main


class CheckpointScopeTests(unittest.TestCase):
    def test_view_refresh_preserves_a_saved_legacy_adjudication(self):
        session = main._new_session('只读旧局面板夹具', '1小时', True,
            '抗日战争-万家岭战役-1938.09下旬至1938.10', False, False)
        session['war_state'] = {'current_time': '1938-10-06 00:00', 'red_units': [], 'blue_units': []}
        session['adj_last'] = {'version': 'geo-legacy', 'fingerprint': 'saved-legacy-audit'}
        before = main.session_store.serializable(session)
        fresh = {'version': main.adjudicator.ADJUDICATOR_VERSION, 'fingerprint': 'display-only'}
        with patch.object(main, '_safe_adjudicate', return_value=fresh), \
                patch.object(main.battlefield, 'build_battlefield_view', return_value={}) as battlefield:
            view = main._snapshot(session)
        self.assertEqual(main.session_store.serializable(session), before)
        self.assertEqual(view['adjudication']['last'], fresh)
        self.assertEqual(battlefield.call_args.args[1], fresh)

    def test_view_refresh_does_not_persist_an_initially_missing_audit(self):
        session = main._new_session('面板缺审计夹具', '1小时', True,
            '抗日战争-万家岭战役-1938.09下旬至1938.10', False, False)
        session['war_state'] = {'current_time': '1938-10-06 00:00', 'red_units': [], 'blue_units': []}
        fresh = {'version': main.adjudicator.ADJUDICATOR_VERSION}
        with patch.object(main, '_safe_adjudicate', return_value=fresh):
            view = main._snapshot(session)
        self.assertIsNone(session['adj_last'])
        self.assertEqual(view['adjudication']['last'], fresh)

    def test_only_accessed_session_is_saved(self):
        sessions = {'a': {'id': 'a'}, 'b': {'id': 'b'}}
        @main._serialized
        def operation():
            main._get('a')['changed'] = True
        with patch.dict(main._SESSIONS, sessions, clear=True), patch.object(main.session_store, 'save') as save:
            operation()
            self.assertEqual(save.call_args_list, [unittest.mock.call(sessions['a'])])

    def test_reading_catalog_does_not_rewrite_sessions(self):
        @main._serialized
        def operation():
            return 'configuration only'
        with patch.dict(main._SESSIONS, {'b': {'id': 'b'}}, clear=True), patch.object(main.session_store, 'save') as save:
            self.assertEqual(operation(), 'configuration only')
            save.assert_not_called()

    def test_failed_operation_does_not_leak_touched_ids_into_next_operation(self):
        @main._serialized
        def failure():
            main._get('a')
            raise ValueError('failed candidate')
        @main._serialized
        def success():
            main._get('b')
        sessions = {'a': {'id': 'a'}, 'b': {'id': 'b'}}
        with patch.dict(main._SESSIONS, sessions, clear=True), patch.object(main.session_store, 'save') as save:
            with self.assertRaises(ValueError):
                failure()
            success()
            self.assertEqual(save.call_args_list, [unittest.mock.call(sessions['b'])])


if __name__ == '__main__':
    unittest.main()
