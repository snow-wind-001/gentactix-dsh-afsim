"""Native report tools replace brittle final text only with verified evidence."""
import copy
import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend import harness_engine as h,turn_preview as p
import verify_dsh_output_recovery as recovery_fixture
from verify_harness_engine import FakeHarness


class NativeReportSubmissionTests(unittest.TestCase):
    def setUp(self):
        self.fixture=recovery_fixture.FinalJSONRecoveryTests();self.fixture.setUp()
        self.s=self.fixture.s;self.o=self.fixture.observer
        self.ctx=p.context(self.s,None,operation_id=self.o.operation_id)
        self.final=self.fixture.preview(self.ctx)

    def tearDown(self):self.fixture.tearDown()

    def raw_preview(self):
        events=self.o.runs[0]['events']
        return [dict(seq=e['seq'],type=e['type'],data={k:v for k,v in e.items() if k not in ('seq','type','session_id')}) for e in events]

    def submit(self,final=None,events=None):
        return p.submit_report(self.ctx,dict(tool='submit_turn_report',session_id='qa-native',args=copy.deepcopy(final or self.final),
            preview_events=copy.deepcopy(self.raw_preview() if events is None else events)))

    def record(self,reply,final=None):
        self.o.runs[0]['events'] += [
            dict(type='tool/call',seq=3,session_id='qa-native',callId='report1',name='submit_turn_report',arguments=json.dumps(final or self.final)),
            dict(type='tool/result',seq=4,session_id='qa-native',message={'toolCallId':'report1','content':[dict(type='text',text=json.dumps(reply))]})]

    def test_report_submission_is_readonly_and_bound_to_current_preview(self):
        before=copy.deepcopy(self.s);reply=self.submit()
        self.assertTrue(reply['ok'],reply);self.assertTrue(reply['readonly']);self.assertEqual(self.s,before)
        self.record(reply);value,receipt=p.submitted_report(self.o,self.ctx)
        self.assertEqual(value,self.final);self.assertEqual(receipt['source'],'dsh_native_report_tool')
        self.assertEqual(receipt['report_digest'],reply['report_digest'])

    def test_missing_stale_or_other_operation_preview_is_not_a_report(self):
        for kind in ('missing','stale','other_operation'):
            ctx=copy.deepcopy(self.ctx)
            if kind=='stale':ctx['session']['war_state']['red_units'][0]['logistics']['food']-=1
            elif kind=='other_operation':ctx['turn_preview']['operation_id']='other'
            value=p.submit_report(ctx,dict(tool='submit_turn_report',session_id='qa-native',args=self.final,
                preview_events=[] if kind=='missing' else self.raw_preview()))
            self.assertFalse(value['ok'],value)

    def test_report_fields_are_not_guessed_or_repaired(self):
        for final in ({**self.final,'preview_hash':'forged'},{**self.final,'report':''},{**self.final,'report':5},{**self.final,'unit_updates':[]}):
            original=copy.deepcopy(final);reply=self.submit(final)
            self.assertFalse(reply['ok']);self.assertEqual(final,original)

    def test_known_false_claim_returns_feedback_without_changing_effects(self):
        final={**self.final,'report':'全军弹药耗尽。'};saved=copy.deepcopy((self.s,final,self.o.runs))
        reply=self.submit(final)
        self.assertFalse(reply['ok'],reply)
        self.assertIn('inventory_claim',{r['code'] for r in reply['issues']})
        self.assertEqual((self.s,final,self.o.runs),saved)
        corrected={**final,'report':'双方待命，粮食依规则消耗。'}
        accepted=self.submit(corrected)
        self.assertTrue(accepted['ok'],accepted)
        self.assertEqual(accepted['preview_hash'],self.final['preview_hash'])
        self.record(accepted,corrected)
        self.assertEqual(p.submitted_report(self.o,self.ctx)[0],corrected)

    def test_final_reader_rechecks_claims_even_when_a_reply_is_forged_ok(self):
        final={**self.final,'report':'全军弹药耗尽。'}
        reply=self.submit()
        reply['report_digest']=p._report_digest(self.ctx,final)
        self.record(reply,final)
        with self.assertRaisesRegex(ValueError,'断言'):
            p.submitted_report(self.o,self.ctx)

    def test_report_header_uses_the_same_final_render_guard(self):
        reply=self.submit({**self.final,'report':'【T+999 | 1938-10-07 00:00】双方待命。'})
        self.assertFalse(reply['ok'],reply)
        self.assertIn('report_header',{r['code'] for r in reply['issues']})

    def test_false_tool_result_or_changed_report_cannot_pass_the_final_reader(self):
        reply=self.submit();self.record(reply)
        for kind in ('digest','text','failed'):
            observer=copy.deepcopy(self.o);events=observer.runs[0]['events']
            if kind=='text':
                args=json.loads(events[-2]['arguments']);args['report']+='篡改';events[-2]['arguments']=json.dumps(args)
            else:
                result=json.loads(events[-1]['message']['content'][0]['text'])
                result['report_digest']='forged' if kind=='digest' else result['report_digest']
                if kind=='failed':result['ok']=False
                events[-1]['message']['content'][0]['text']=json.dumps(result)
            with self.subTest(kind=kind):
                if kind=='failed':self.assertIsNone(p.submitted_report(observer,self.ctx))
                else:
                    with self.assertRaises(ValueError):p.submitted_report(observer,self.ctx)

    def test_native_final_text_can_be_plain_or_malformed_when_report_tool_is_valid(self):
        self.record(self.submit())
        for text in ('候选已提交。','{"report":"unclosed'):
            result=SimpleNamespace(final_response=text,finish_reason='completed')
            with patch.object(h,'_run_brain',return_value=result):
                value=h.get_ai_response('test',observer=self.o,native_context=self.ctx)
            self.assertEqual(value,self.final)
        _,receipt=p.resolve(self.final,self.o,self.ctx)
        self.assertEqual(receipt['report_source'],'dsh_native_report_tool')

    def test_completed_empty_text_needs_no_recovery_when_native_report_is_complete(self):
        self.record(self.submit());fake=FakeHarness(['','must not run'])
        with patch.object(h,'get_harness',return_value=fake):
            value=h.get_ai_response('test',observer=self.o,native_context=self.ctx)
        self.assertEqual(value,self.final);self.assertEqual(len(fake.prompts),1)
        self.assertEqual(self.o.empty_recoveries,0);self.assertEqual(self.o.last_finish,'completed')

    def test_new_preview_after_submitted_report_requires_a_new_report(self):
        self.record(self.submit());candidate=copy.deepcopy(self.fixture.value)
        candidate['unit_updates'][0].setdefault('formation',{})['fatigue']=1
        reply=p.execute(self.ctx,dict(tool=p.TOOL,args={'candidate':candidate}));self.assertTrue(reply['ok'],reply)
        self.o.runs[0]['events'] += [dict(type='tool/call',seq=5,session_id='qa-native',callId='p2',name=p.TOOL,arguments=json.dumps({'candidate':candidate})),
            dict(type='tool/result',seq=6,session_id='qa-native',message={'toolCallId':'p2','content':[dict(type='text',text=json.dumps(reply))]})]
        with self.assertRaisesRegex(ValueError,'新预览'):p.submitted_report(self.o,self.ctx)

    def test_only_current_native_process_engine_gets_report_tool(self):
        self.assertIn('submit_turn_report',h.role_policy('engine',tools=True,process=True)['allowed_tools'])
        for role,external,process in [('chat',False,True),('engine',True,True),('engine',False,False)]:
            self.assertNotIn('submit_turn_report',h.role_policy(role,tools=True,external=external,process=process)['allowed_tools'])

    def test_unknown_source_cannot_bypass_runtime_completion_gate(self):
        # A valid proposal is not sufficient if the actual runtime aborted.
        self.record(self.submit())
        for reason in ('aborted','error','max-tokens'):
            fake=FakeHarness([SimpleNamespace(text='done',finish_reason=reason)])
            with patch.object(h,'get_harness',return_value=fake),self.assertRaises(h.HarnessRunError):
                h.get_ai_response('test',observer=self.o,native_context=self.ctx)

    def test_python_observer_does_not_trust_an_unpaired_report_result(self):
        reply=self.submit();self.record(reply)
        del self.o.runs[0]['events'][-2]
        self.assertIsNone(p.submitted_report(self.o,self.ctx))

    def test_report_cannot_claim_another_world_in_a_valid_tool_result(self):
        self.record(self.submit());ctx=copy.deepcopy(self.ctx);ctx['turn_preview']['operation_id']='other'
        with self.assertRaises(ValueError):p.submitted_report(self.o,ctx)

    def test_runtime_journal_selection_uses_only_the_linked_public_tool_pair(self):
        result=subprocess.run(['node','tools/qa/native_report_evidence.mjs'],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


class NativeReportRouteTests(unittest.TestCase):
    def setUp(self):
        self.api=recovery_fixture.FinalJSONRouteTests();self.api.setUp();self.calls=0;self.submitted=False

    def tearDown(self):self.api.tearDown()

    def completed(self,_message,_role_id=None,**kwargs):
        self.calls+=1
        fixture=recovery_fixture.FinalJSONRecoveryTests();fixture.s=self.api.s;fixture.value=self.api.value
        fixture.observer=kwargs['observer'];final=fixture.preview(kwargs['native_context'])
        events=fixture.observer.runs[-1]['events'];raw=[dict(type=e['type'],seq=e['seq'],data={k:v for k,v in e.items() if k not in ('type','seq','session_id')}) for e in events]
        from backend import main
        reply=main._native_tool_dispatch(kwargs['native_context'],dict(tool=p.REPORT_TOOL,session_id='qa-native',args=final,preview_events=raw))
        self.assertTrue(reply['ok'],reply)
        self.submitted=True
        fixture.observer.runs[-1]['events'] += [dict(type='tool/call',seq=3,session_id='qa-native',callId='report1',name=p.REPORT_TOOL,arguments=json.dumps(final)),
            dict(type='tool/result',seq=4,session_id='qa-native',message={'toolCallId':'report1','content':[dict(type='text',text=json.dumps(reply))]})]
        return SimpleNamespace(final_response='完整候选已通过工具提交。',finish_reason='completed')

    def test_plain_final_with_native_report_commits_exactly_once(self):
        with patch.object(h,'NATIVE_RUNTIME',True),patch.object(h,'_run_brain',side_effect=self.completed):
            response=self.api.client.post(self.api.base+'/next',json=self.api.body)
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(self.calls,1);self.assertTrue(self.submitted)
        self.assertEqual(self.api.s['turn_count'],1);self.assertEqual(self.api.s['war_state']['red_units'][0]['logistics']['food'],78)
        trace=self.api.s['trajectory'][-1]
        self.assertEqual(trace['guards']['report']['preview']['report_source'],'dsh_native_report_tool')
        cold,errors=self.api.store.load_all();self.assertFalse(errors);self.assertEqual(cold[self.api.sid]['war_state'],self.api.s['war_state'])

    def test_cancellation_after_report_tool_still_does_not_commit(self):
        before=copy.deepcopy(self.api.s)
        def model(*args,**kwargs):
            result=self.completed(*args,**kwargs);self.api.s['cancel_requested']=True;return result
        with patch.object(h,'NATIVE_RUNTIME',True),patch.object(h,'_run_brain',side_effect=model):
            response=self.api.client.post(self.api.base+'/next',json=self.api.body)
        self.assertEqual(response.status_code,409,response.text);self.assertTrue(self.submitted);self.api.unchanged(before)

    def test_disk_failure_after_report_tool_still_does_not_consume_orders(self):
        before=copy.deepcopy(self.api.s)
        with patch.object(h,'NATIVE_RUNTIME',True),patch.object(h,'_run_brain',side_effect=self.completed),patch.object(self.api.store,'save',side_effect=OSError('QA full disk')):
            response=self.api.client.post(self.api.base+'/next',json=self.api.body)
        self.assertEqual(response.status_code,502,response.text);self.assertTrue(self.submitted);self.api.unchanged(before)

    def test_aborted_runtime_after_report_tool_is_not_accepted(self):
        before=copy.deepcopy(self.api.s)
        def model(*args,**kwargs):
            self.completed(*args,**kwargs);raise h.HarnessRunError('finish_reason=aborted')
        with patch.object(h,'NATIVE_RUNTIME',True),patch.object(h,'_run_brain',side_effect=model):
            response=self.api.client.post(self.api.base+'/next',json=self.api.body)
        self.assertEqual(response.status_code,502,response.text);self.assertTrue(self.submitted);self.api.unchanged(before)


if __name__=='__main__':unittest.main()
