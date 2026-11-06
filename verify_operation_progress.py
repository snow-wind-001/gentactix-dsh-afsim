"""Operation wall time and terminal facts survive reconnect and failed checkpoints."""
import copy
import json
import os
from pathlib import Path
import tempfile
import subprocess
import unittest
from unittest.mock import patch

from backend import harness_engine as h, main, extensions, session_store


class OperationProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.env=patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':self.temp.name+'/sessions',
            'GENTACTIX_TRACE_DIR':self.temp.name+'/traces'})
        self.env.start();self.addCleanup(self.env.stop)
        self.addCleanup(h.ENGINE_NOTICES.clear)
        self.s=main._new_session('operation-clock QA','1小时',False,None,False,False)
        main._SESSIONS[self.s['id']]=self.s
        self.addCleanup(main._SESSIONS.pop,self.s['id'],None)

    def observer(self):
        with patch.object(h.time,'time',return_value=1700000000),patch.object(h.time,'monotonic',return_value=100):
            return h.RunObserver('推演 T+1')

    def test_server_clock_includes_waiting_without_runtime_events(self):
        o=self.observer();saved=copy.deepcopy(self.s)
        with patch.object(h.time,'monotonic',return_value=851.5):clock=o.clock_snapshot()
        self.assertEqual(clock['wall_elapsed_ms'],751500)
        self.assertEqual(clock['started_at_ms'],1700000000000)
        self.assertEqual(clock['operation_id'],o.operation_id);self.assertEqual(self.s,saved)

    def test_wall_clock_jump_does_not_change_elapsed_or_existing_sdk_elapsed(self):
        o=self.observer();o.elapsed_ms=1234.5
        with patch.object(h.time,'time',return_value=1),patch.object(h.time,'monotonic',return_value=160):meta=o.meta()
        self.assertEqual(meta['elapsed_ms'],1234);self.assertEqual(meta['wall_elapsed_ms'],60000)
        self.assertEqual(meta['clock_sampled_at_ms'],meta['started_at_ms']+60000)

    def test_progress_get_is_fresh_readonly_and_matches_current_operation(self):
        o=self.observer();self.s.update(active_observer=o,progress=o.progress)
        before=copy.deepcopy(self.s['progress'])
        with patch.object(h.time,'monotonic',return_value=861):a=main.get_progress(self.s['id'])
        with patch.object(h.time,'monotonic',return_value=862):b=main.get_progress(self.s['id'])
        self.assertTrue(a['active']);self.assertEqual(a['progress']['wall_elapsed_ms'],761000)
        self.assertEqual(b['progress']['wall_elapsed_ms']-a['progress']['wall_elapsed_ms'],1000)
        self.assertEqual(a['operation_id'],a['progress']['operation_id'])
        self.assertEqual(self.s['progress'],before)

    def test_failure_time_and_label_are_saved_before_clean_shutdown(self):
        o=self.observer();before=copy.deepcopy(self.s)
        with patch.object(h.time,'monotonic',return_value=853):extensions.record_failure(self.s,o,'next',ValueError('候选未提交'))
        stored=json.loads((Path(self.temp.name)/'sessions'/f"{self.s['id']}.json").read_text())['session']
        failed=stored['failed_operations'][-1]
        self.assertEqual(failed['wall_elapsed_ms'],753000);self.assertEqual(failed['label'],'推演 T+1')
        self.assertEqual(failed['operation_id'],o.operation_id)
        for key in ('war_state','turn_count','history','decision_log'):self.assertEqual(stored[key],before[key])
        self.s.update(stored)
        value=main.get_progress(self.s['id']);self.assertFalse(value['active'])
        self.assertEqual(value['last_operation']['outcome'],'failed')
        self.assertEqual(value['last_operation']['wall_elapsed_ms'],753000)

    def test_failed_checkpoint_does_not_mask_original_error_or_drop_memory_record(self):
        o=self.observer()
        with patch.object(session_store,'save',side_effect=OSError('disk full')):
            extensions.record_failure(self.s,o,'next',ValueError('原始模型错误'))
        self.assertEqual(self.s['failed_operations'][-1]['error'],'原始模型错误')

    def test_fresh_recovery_selects_newer_success_instead_of_stale_failure(self):
        self.s['failed_operations']=[dict(operation_id='old',error='旧失败',clock_sampled_at_ms=1000)]
        self.s['engine_last_meta']=dict(operation_id='new',label='推演 T+2',finish_reason='completed',
            started_at_ms=2000,wall_elapsed_ms=5000,clock_sampled_at_ms=7000)
        value=main.get_progress(self.s['id'])
        self.assertEqual(value['last_operation']['operation_id'],'new')
        self.assertEqual(value['last_operation']['outcome'],'success')

    def test_cancellation_is_a_terminal_fact_and_is_never_a_success(self):
        self.s['engine_last_meta']=dict(operation_id='old',clock_sampled_at_ms=1000)
        self.s['failed_operations']=[dict(operation_id='cancelled',error='用户已取消',cancelled=True,
            started_at_ms=2000,wall_elapsed_ms=730000,clock_sampled_at_ms=732000)]
        value=main.get_progress(self.s['id'])
        self.assertEqual(value['last_operation']['outcome'],'cancelled')
        self.assertEqual(value['last_operation']['wall_elapsed_ms'],730000)

    def test_cancelled_failure_does_not_rearm_cancel_after_restore(self):
        o=self.observer();self.s['cancel_requested']=True
        extensions.record_failure(self.s,o,'next',ValueError('用户已取消'))
        stored=json.loads((Path(self.temp.name)/'sessions'/f"{self.s['id']}.json").read_text())['session']
        self.assertTrue(stored['failed_operations'][-1]['cancelled'])
        self.assertFalse(stored['cancel_requested'])
        self.assertTrue(self.s['cancel_requested'])  # Caller still emits its original cancellation response.

    def test_legacy_ordering_or_duration_is_not_invented(self):
        self.s['engine_last_meta']=dict(operation_id='legacy-success',elapsed_ms=12000)
        self.s['failed_operations']=[dict(operation_id='legacy-failure',error='旧失败')]
        value=main.get_progress(self.s['id'])
        self.assertIsNone(value['last_operation'])
        self.assertNotIn('wall_elapsed_ms',value['completed_operation'])

    def test_frontend_monotonic_recovery_and_terminal_clock_contract(self):
        result=subprocess.run(['node','tools/qa/operation_clock_contract.mjs'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_auxiliary_causal_operation_registers_success_without_advancing_world(self):
        from fastapi.testclient import TestClient
        from verify_causal import fixture
        record=fixture();self.s.update(war_state=copy.deepcopy(record['after']),trajectory=[record])
        before=copy.deepcopy(self.s['war_state'])
        response=TestClient(main.app).post(f"/api/sessions/{self.s['id']}/analysis",json={'explain':False})
        self.assertEqual(response.status_code,200,response.text)
        last=main.get_progress(self.s['id'])['last_operation']
        self.assertEqual(last['outcome'],'success');self.assertEqual(last['label'],'因果解读')
        self.assertIn('wall_elapsed_ms',last);self.assertEqual(self.s['war_state'],before)

    def test_auxiliary_failure_and_cancel_are_durable_terminal_facts(self):
        from fastapi.testclient import TestClient
        from verify_causal import fixture
        self.s['trajectory']=[fixture()]
        for cancelled in (False,True):
            self.s['cancel_requested']=cancelled
            with patch.object(extensions,'analyze',side_effect=ValueError('测试解读失败')):
                response=TestClient(main.app).post(f"/api/sessions/{self.s['id']}/analysis",json={'explain':False})
            self.assertEqual(response.status_code,409 if cancelled else 502)
            last=main.get_progress(self.s['id'])['last_operation']
            self.assertEqual(last['outcome'],'cancelled' if cancelled else 'failed')
            stored=json.loads((Path(self.temp.name)/'sessions'/f"{self.s['id']}.json").read_text())['session']
            self.assertEqual(stored['failed_operations'][-1]['operation_id'],last['operation_id'])
            self.assertEqual(stored,session_store.serializable(self.s))

    def test_model_operation_stays_active_until_failure_record_is_published(self):
        from fastapi.testclient import TestClient
        from verify_causal import fixture
        self.s['war_state']=fixture()['after'];observed=[]
        record=main._record_failed_operation
        def publishing(session,observer,phase,error):
            observed.append(main.get_progress(session['id'])['active'])
            return record(session,observer,phase,error)
        with patch.object(h,'ask_xuanji',side_effect=RuntimeError('测试失败保存中')),patch.object(main,'_record_failed_operation',side_effect=publishing):
            response=TestClient(main.app).post(f"/api/sessions/{self.s['id']}/chat",json={'message':'只读测试'})
        self.assertEqual(response.status_code,502)
        self.assertEqual(observed,[True])
        current=main.get_progress(self.s['id'])
        self.assertFalse(current['active']);self.assertEqual(current['last_operation']['outcome'],'failed')

    def test_chat_cancellation_remains_cancelled_in_restored_outcome(self):
        from fastapi.testclient import TestClient
        from verify_causal import fixture
        self.s['war_state']=fixture()['after']
        def finished(*args,**kwargs):
            self.s['cancel_requested']=True
            return '', '这份回答不应提交'
        with patch.object(h,'ask_xuanji',side_effect=finished):
            response=TestClient(main.app).post(f"/api/sessions/{self.s['id']}/chat",json={'message':'取消测试'})
        self.assertEqual(response.status_code,409)
        self.assertEqual(main.get_progress(self.s['id'])['last_operation']['outcome'],'cancelled')
        self.assertEqual(self.s['chat_messages'],[])
        stored=json.loads((Path(self.temp.name)/'sessions'/f"{self.s['id']}.json").read_text())['session']
        self.assertEqual(stored,session_store.serializable(self.s))


if __name__=='__main__':unittest.main()
