"""Bounded final-JSON recovery over real validators, with offline model fixtures.

No live model or engine is called. A successful native preview is still only a
candidate; retries must not commit, repair JSON, or weaken its fingerprint.
"""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

from backend import dsh_simulation as d, harness_engine as h, turn_preview
from gentactix import commands, missions
from tools.qa.campaign_lifecycle_fixture import session
from verify_campaign_plan_backends import proposal
from verify_harness_engine import FakeHarness


class FinalJSONRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.s=session();self.s['agent_mode']='native'
        self.value=proposal(self.s['war_state'])
        self.observer=h.RunObserver('offline final JSON recovery')
        self.ctx=None;self.final=None;self.prompts=[]
        h.ENGINE_NOTICES.clear()

    def tearDown(self):
        h.ENGINE_NOTICES.clear()

    def preview(self,context):
        self.ctx=context
        reply=turn_preview.execute(context,{'tool':turn_preview.TOOL,'args':{'candidate':copy.deepcopy(self.value)}})
        self.assertTrue(reply['ok'],reply)
        self.observer.runs.append({'id':self.observer.operation_id+':fixture-preview',
            'session_id':'qa-native','finish_reason':'completed','event_count':2,
            'first_seq':1,'last_seq':2,'evidence':'offline_fixture','events':[
            dict(type='tool/call',seq=1,session_id='qa-native',callId='p1',name=turn_preview.TOOL,
                 arguments=json.dumps({'candidate':self.value})),
            dict(type='tool/result',seq=2,session_id='qa-native',message={'toolCallId':'p1',
                 'content':[dict(type='text',text=json.dumps(reply))]})]})
        self.final=dict(preview_hash=reply['digest'],report='双方待命，粮食依规则消耗。')
        return self.final

    def malformed(self):
        # Same failure shape as the actual completed call: unterminated report.
        return h.parse_json_object('{"preview_hash":"'+self.final['preview_hash']+'","report":"未闭合')

    def test_parser_has_typed_diagnostics_and_never_repairs_a_completed_reply(self):
        for raw in ('{"report":"未闭合','{"report":]}','no JSON'):
            with self.subTest(raw=raw),self.assertRaises(h.JSONOutputError) as raised:
                h.parse_json_object(raw)
            self.assertEqual(raised.exception.diagnostics['characters'],len(raw))
            self.assertNotIn('raw_text',raised.exception.diagnostics)

    def test_rejected_completed_run_is_preserved_without_generic_json_retry(self):
        fake=FakeHarness(['{"report":"未闭合','{"ok":true}'])
        with patch.object(h,'get_harness',return_value=fake),self.assertRaises(h.JSONOutputError):
            h.get_ai_response('继续',observer=self.observer)
        self.assertEqual(len(fake.prompts),1)
        self.assertEqual(self.observer.runs[0]['finish_reason'],'completed')
        self.assertFalse(self.observer.runs[0]['accepted'])
        self.assertEqual(self.observer.runs[0]['rejection'],'invalid_final_json')
        self.assertEqual(self.observer.json_recoveries,0)

    def test_native_recovery_reuses_only_verified_current_operation_preview(self):
        saved=copy.deepcopy(self.s);contexts=[]
        def model(message,**kwargs):
            self.prompts.append(message);contexts.append(kwargs['native_context'])
            if len(self.prompts)==1:
                self.preview(contexts[-1]);return self.malformed()
            self.assertIn(self.final['preview_hash'],message)
            self.assertIn('不是新的战局回合',message)
            self.assertIn('未提交',message)
            self.assertNotIn('未闭合',message)
            self.assertEqual(kwargs['role_id'],'gentactix-qa-engine')
            return self.final
        with patch.object(h,'NATIVE_RUNTIME',True),patch.object(h,'get_ai_response',side_effect=model):
            result,_,_=d.advance(self.s,None,self.observer,role_id='gentactix-qa-engine')
        self.assertEqual(len(self.prompts),2);self.assertEqual(contexts[0],contexts[1])
        self.assertEqual(self.observer.json_recoveries,1)
        self.assertEqual(result['updated_state']['mission']['turn'],1)
        self.assertEqual(result['updated_state']['red_units'][0]['logistics']['food'],78)
        self.assertEqual(self.s,saved)

    def test_json_retry_without_any_successful_preview_requires_a_new_preview(self):
        saved=copy.deepcopy(self.s)
        def model(message,**kwargs):
            self.prompts.append(message)
            if len(self.prompts)==1:return h.parse_json_object('{"report":"unfinished')
            self.assertIn('没有可复用的成功预览',message)
            return self.preview(kwargs['native_context'])
        with patch.object(h,'NATIVE_RUNTIME',True),patch.object(h,'get_ai_response',side_effect=model):
            result,_,_=d.advance(self.s,None,self.observer)
        self.assertEqual(result['updated_state']['mission']['turn'],1);self.assertEqual(self.s,saved)

    def test_repeated_malformed_final_stops_after_two_calls_without_any_commit(self):
        saved=copy.deepcopy(self.s)
        def model(message,**kwargs):
            self.prompts.append(message)
            if self.final is None:self.preview(kwargs['native_context'])
            return self.malformed()
        with patch.object(h,'NATIVE_RUNTIME',True),patch.object(h,'get_ai_response',side_effect=model),self.assertRaisesRegex(ValueError,'最终JSON.*仍失败'):
            d.advance(self.s,None,self.observer)
        self.assertEqual(len(self.prompts),2);self.assertEqual(self.s,saved)

    def test_cancellation_after_parse_error_prevents_a_second_call(self):
        saved=copy.deepcopy(self.s);cancelled=False
        def model(message,**kwargs):
            nonlocal cancelled
            self.prompts.append(message);self.preview(kwargs['native_context']);cancelled=True
            return self.malformed()
        with patch.object(h,'NATIVE_RUNTIME',True),patch.object(h,'get_ai_response',side_effect=model),self.assertRaisesRegex(RuntimeError,'取消'):
            d.advance(self.s,None,self.observer,cancel_check=lambda:cancelled)
        self.assertEqual(len(self.prompts),1);self.assertEqual(self.s,saved)
        self.assertEqual(self.observer.json_recoveries,0)

    def test_runtime_and_transport_errors_are_not_json_recovered(self):
        for error in (h.HarnessRunError('finish_reason=max-tokens'),RuntimeError('transport disconnected'),ValueError('unrelated runtime value')):
            with self.subTest(error=type(error).__name__),patch.object(h,'NATIVE_RUNTIME',True),patch.object(h,'get_ai_response',side_effect=error) as model,self.assertRaises(type(error)):
                d.advance(self.s,None,self.observer)
            self.assertEqual(model.call_count,1)

    def test_forged_final_after_recovery_does_not_get_an_extra_attempt(self):
        saved=copy.deepcopy(self.s)
        def model(message,**kwargs):
            self.prompts.append(message)
            if len(self.prompts)==1:
                self.preview(kwargs['native_context']);return self.malformed()
            return {**self.final,'preview_hash':'forged'}
        with patch.object(h,'NATIVE_RUNTIME',True),patch.object(h,'get_ai_response',side_effect=model),self.assertRaisesRegex(ValueError,'轨迹'):
            d.advance(self.s,None,self.observer)
        self.assertEqual(len(self.prompts),2);self.assertEqual(self.s,saved)

    def test_recovery_hint_excludes_stale_world_operation_and_forged_evidence(self):
        self.preview(turn_preview.context(self.s,None,operation_id=self.observer.operation_id))
        self.assertEqual(turn_preview.recovery_hint(self.observer,self.ctx)['preview_hash'],self.final['preview_hash'])
        for kind in ('world','operation','no_calls'):
            context=copy.deepcopy(self.ctx);observer=copy.copy(self.observer)
            if kind=='world':context['session']['war_state']['red_units'][0]['logistics']['food']-=1
            elif kind=='operation':context['turn_preview']['operation_id']='another-operation'
            else:observer.runs=[{'events':[observer.runs[0]['events'][1]]}]
            self.assertIsNone(turn_preview.recovery_hint(observer,context))

    def test_json_recovery_budget_is_shared_across_calls_of_the_same_operation(self):
        def model(message,**kwargs):
            self.prompts.append(message)
            if len(self.prompts)==1:
                self.preview(kwargs['native_context']);return self.malformed()
            if len(self.prompts)==2:return self.final
            return self.malformed()
        with patch.object(h,'NATIVE_RUNTIME',True),patch.object(h,'get_ai_response',side_effect=model):
            d.advance(self.s,None,self.observer)
            with self.assertRaisesRegex(ValueError,'恢复额度'):
                d.advance(self.s,None,self.observer)
        self.assertEqual(len(self.prompts),3);self.assertEqual(self.observer.json_recoveries,1)

    def test_legacy_process_also_recovers_from_its_original_uncommitted_state(self):
        good=copy.deepcopy(self.value);saved=copy.deepcopy(self.s)
        fake=FakeHarness(['{"unit_updates":',json.dumps(good)])
        with patch.object(h,'NATIVE_RUNTIME',False),patch.object(h,'get_harness',return_value=fake):
            result,_,_=d.advance(self.s,None,self.observer,role_id='gentactix-qa-engine')
        self.assertEqual(fake.session_ids,['gentactix-qa-engine']*2)
        self.assertEqual(result['updated_state']['mission']['turn'],1);self.assertEqual(self.s,saved)


class FinalJSONRouteTests(unittest.TestCase):
    def setUp(self):
        from backend import main,session_store
        from fastapi.testclient import TestClient
        self.main=main;self.store=session_store
        self.folder=tempfile.TemporaryDirectory();base=Path(self.folder.name)
        self.env=patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':str(base/'sessions'),
            'GENTACTIX_TRACE_DIR':str(base/'traces')});self.env.start()
        world=session()['war_state']
        self.s=main._new_session('最终JSON恢复路由QA','30分钟',False,
            world['mission']['definition']['battle'],False,False,agent_mode='native',persist_roles=False)
        self.s.update(war_state=world,mission_id=world['mission']['id'],product_mode='historical',
            simulation_mode='open',execution_backend='narrative',historical_definition=copy.deepcopy(world['mission']['definition']))
        view=commands.view(self.s)
        self.s['command_state']=commands.replace_queue(self.s,[dict(unit_id=u['id'],action='hold',duration='next') for u in view['units']],
            control_team='red',director=True,no_fire=False,intent='所有单位明确待命，QA估计参数')
        self.sid=self.s['id'];main._SESSIONS[self.sid]=self.s;self.base='/api/sessions/'+self.sid
        self.store.validate(self.s);self.store.save(self.s)
        view=commands.view(self.s)
        self.body=dict(expected_turn=view['turn'],revision=view['revision'],world_version=view['world_version'],batch_id=uuid.uuid4().hex)
        self.client=TestClient(main.app,raise_server_exceptions=False)
        self.value=proposal(world);self.calls=0;self.final=None

    def tearDown(self):
        self.main._SESSIONS.pop(self.sid,None);self.env.stop();self.folder.cleanup();h.ENGINE_NOTICES.clear()

    def model(self,_message,**kwargs):
        self.calls+=1
        if self.final is None:
            helper=FinalJSONRecoveryTests();helper.s=self.s;helper.value=self.value;helper.observer=kwargs['observer']
            self.final=helper.preview(kwargs['native_context'])
        if self.calls==1:return h.parse_json_object('{"report":"unfinished')
        return self.final

    def unchanged(self,before):
        cold,errors=self.store.load_all();self.assertFalse(errors)
        for field in ('war_state','last_war_state','turn_count','history','trajectory','command_state','decision_log'):
            self.assertEqual(self.s[field],before[field],field)
            self.assertEqual(cold[self.sid][field],before[field],field)

    def test_recovered_output_commits_once_and_same_batch_replay_never_reexecutes(self):
        before=copy.deepcopy(self.s)
        with patch.object(h,'NATIVE_RUNTIME',True),patch.object(h,'get_ai_response',side_effect=self.model):
            response=self.client.post(self.base+'/next',json=self.body)
            self.assertEqual(response.status_code,200,response.text)
            repeated=self.client.post(self.base+'/next',json=self.body)
        self.assertEqual(repeated.status_code,200,repeated.text);self.assertTrue(repeated.json()['command_result']['replayed'])
        self.assertEqual(self.calls,2);self.assertEqual(self.s['turn_count'],1)
        self.assertEqual(len(self.s['history']),len(before['history'])+1)
        self.assertEqual(len(self.s['trajectory']),len(before['trajectory'])+1)
        self.assertEqual(self.s['engine_last_meta']['json_recoveries'],1)
        self.assertEqual(self.s['war_state']['red_units'][0]['logistics']['food'],78)
        cold,errors=self.store.load_all();self.assertFalse(errors);self.assertEqual(cold[self.sid]['war_state'],self.s['war_state'])

    def test_two_parse_failures_keep_world_and_pending_orders_in_memory_and_on_disk(self):
        before=copy.deepcopy(self.s)
        with patch.object(h,'NATIVE_RUNTIME',True),patch.object(h,'get_ai_response',side_effect=lambda *_a,**_k:h.parse_json_object('{"report":"unfinished')) as model:
            response=self.client.post(self.base+'/next',json=self.body)
        self.assertEqual(response.status_code,502,response.text);self.assertEqual(model.call_count,2)
        self.unchanged(before)

    def test_cancelled_recovery_keeps_world_and_pending_orders(self):
        before=copy.deepcopy(self.s)
        def cancel(*_a,**_k):
            self.calls+=1;self.s['cancel_requested']=True
            return h.parse_json_object('{"report":"unfinished')
        with patch.object(h,'NATIVE_RUNTIME',True),patch.object(h,'get_ai_response',side_effect=cancel):
            response=self.client.post(self.base+'/next',json=self.body)
        self.assertEqual(response.status_code,409,response.text);self.assertEqual(self.calls,1);self.unchanged(before)

    def test_disk_failure_after_recovery_never_consumes_the_queue_or_candidate(self):
        before=copy.deepcopy(self.s)
        with patch.object(h,'NATIVE_RUNTIME',True),patch.object(h,'get_ai_response',side_effect=self.model),patch.object(self.store,'save',side_effect=OSError('QA full disk')):
            response=self.client.post(self.base+'/next',json=self.body)
        self.assertEqual(response.status_code,502,response.text);self.assertEqual(self.calls,2);self.unchanged(before)


if __name__=='__main__':unittest.main()
