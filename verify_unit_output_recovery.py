"""Native unit JSON recovery preserves bindings, operation budgets and state.

Offline transport fixtures reproduce a real completed-but-malformed reply.
They do not replace live SDK evidence or calculate process effects.
"""
import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend import unit_planning as planning,harness_engine as h
from gentactix import commands
from tools.qa.campaign_plan_fixture import session

BAD='{"order":{"action":"hold","duration":"next"},"rationale":"公开依据","expected_effect"}'
GOOD=json.dumps(dict(order=dict(action='hold',duration='next'),rationale='本单位待命',expected_effect='由后续过程结算'))


class UnitOutputRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.session=session();self.session['agent_mode']='native';self.session['execution_backend']='narrative'
        view=commands.view(self.session);self.uid=next(u['id'] for u in view['units'] if u['team']=='red')
        cs=commands.replace_queue(self.session,[dict(unit_id=u['id'],action='hold',duration='next') for u in view['units'] if u['available'] and u['id']!=self.uid],
            control_team='red',director=True,no_fire=False,intent='离线原生单位JSON恢复回归')
        cs['unit_agents']=[self.uid];self.session['command_state']=cs
        self.prepared=commands.prepare(self.session);self.observer=h.RunObserver('offline unit recovery')
        self.binding=dict(session_id='qa-unit-existing',factory='DSH.AgentRegistry',persistence='session_journal')
        self.calls=[];h.ENGINE_NOTICES.clear()

    def tearDown(self):h.ENGINE_NOTICES.clear()

    def transport(self,replies,*,cancel_after_first=False):
        def run(binding,prompt,observer,**kwargs):
            self.calls.append(dict(binding=copy.deepcopy(binding),prompt=prompt,context=kwargs['context'],namespace=kwargs['namespace']))
            value=SimpleNamespace(session_id=self.binding['session_id'],finish_reason='completed',events=[],final_response=replies[len(self.calls)-1])
            observer.record_result(value)
            if cancel_after_first:observer.cancel_requested=True
            return value,copy.deepcopy(self.binding)
        return run

    def test_real_missing_value_retries_once_on_same_native_binding_without_state_repair(self):
        prior=copy.deepcopy(self.session)
        with patch.object(h,'unit_run',side_effect=self.transport([BAD,GOOD])):
            orders,decisions=planning.plan(self.session,self.prepared,self.observer)
        self.assertEqual(len(self.calls),2)
        self.assertIsNone(self.calls[0]['binding']);self.assertEqual(self.calls[1]['binding'],self.binding)
        self.assertEqual(self.calls[0]['namespace'],self.calls[1]['namespace'])
        self.assertEqual(self.calls[0]['context'],self.calls[1]['context'])
        self.assertIn('不是新的战局回合',self.calls[1]['prompt'])
        self.assertEqual(self.observer.json_recoveries,1)
        self.assertEqual(self.observer.runs[0]['rejection'],'invalid_unit_json')
        self.assertFalse(self.observer.runs[0]['accepted'])
        self.assertEqual(len(decisions[0]['run_ids']),2)
        self.assertEqual(self.prepared['state']['agent_sessions'][self.uid],self.binding)
        self.assertEqual(orders[0]['action'],'hold');self.assertEqual(self.session,prior)

    def test_second_malformed_reply_rejects_without_binding_adoption_or_silent_hold(self):
        before=copy.deepcopy(self.session)
        with patch.object(h,'unit_run',side_effect=self.transport([BAD,BAD])),self.assertRaisesRegex(ValueError,'恢复后仍'):
            planning.plan(self.session,self.prepared,self.observer)
        self.assertEqual(len(self.calls),2);self.assertEqual(self.observer.json_recoveries,1)
        self.assertNotIn(self.uid,self.prepared['state']['agent_sessions']);self.assertEqual(self.session,before)

    def test_cancel_after_bad_reply_never_retries_or_consumes_recovery_budget(self):
        with patch.object(h,'unit_run',side_effect=self.transport([BAD,GOOD],cancel_after_first=True)),self.assertRaisesRegex(RuntimeError,'取消'):
            planning.plan(self.session,self.prepared,self.observer)
        self.assertEqual(len(self.calls),1);self.assertEqual(self.observer.json_recoveries,0)

    def test_unit_recovery_shares_the_existing_whole_operation_quota(self):
        self.observer.json_recoveries=1
        with patch.object(h,'unit_run',side_effect=self.transport([BAD,GOOD])),self.assertRaisesRegex(ValueError,'恢复额度已用完'):
            planning.plan(self.session,self.prepared,self.observer)
        self.assertEqual(len(self.calls),1);self.assertEqual(self.observer.json_recoveries,1)

    def test_runtime_error_and_max_tokens_are_not_completed_json_recovery(self):
        for reason in ('runtime error','harness unfinished: max-tokens'):
            with self.subTest(reason=reason),patch.object(h,'unit_run',side_effect=RuntimeError(reason)) as run,self.assertRaises(RuntimeError):
                planning.plan(self.session,self.prepared,self.observer)
            self.assertEqual(run.call_count,1);self.assertEqual(self.observer.json_recoveries,0)
            self.assertEqual(self.observer.empty_recoveries,0)

    def empty_transport(self,*,always_empty=False,cancel=False):
        def run(binding,prompt,observer,**kwargs):
            self.calls.append(dict(binding=copy.deepcopy(binding),prompt=prompt,context=kwargs['context'],namespace=kwargs['namespace']))
            kwargs.get('on_session',lambda value:None)(copy.deepcopy(self.binding))
            empty=always_empty or len(self.calls)==1
            result=SimpleNamespace(session_id=self.binding['session_id'],finish_reason='completed',events=[],final_response='' if empty else GOOD)
            observer.record_result(result)
            if empty:
                if cancel:observer.cancel_requested=True
                raise h.EmptyFinalResponseError(result)
            return result,copy.deepcopy(self.binding)
        return run

    def test_completed_empty_unit_recovers_once_on_the_created_native_binding(self):
        before=copy.deepcopy(self.session)
        with patch.object(h,'unit_run',side_effect=self.empty_transport()):
            orders,decisions=planning.plan(self.session,self.prepared,self.observer)
        self.assertEqual(len(self.calls),2)
        self.assertIsNone(self.calls[0]['binding']);self.assertEqual(self.calls[1]['binding'],self.binding)
        self.assertEqual(self.calls[0]['context'],self.calls[1]['context'])
        self.assertEqual(self.calls[0]['namespace'],self.calls[1]['namespace'])
        self.assertIn('不是新的战局回合',self.calls[1]['prompt'])
        self.assertEqual(self.observer.empty_recoveries,1)
        self.assertEqual(self.observer.json_recoveries,0)
        self.assertFalse(self.observer.runs[0]['accepted'])
        self.assertEqual(self.observer.runs[0]['rejection'],'empty_unit_response')
        self.assertEqual(len(decisions[0]['run_ids']),2);self.assertEqual(orders[0]['action'],'hold')
        self.assertEqual(self.prepared['state']['agent_sessions'][self.uid],self.binding)
        self.assertEqual(self.session,before)

    def test_second_empty_unit_does_not_adopt_a_binding_or_invent_hold(self):
        before=copy.deepcopy(self.session)
        with patch.object(h,'unit_run',side_effect=self.empty_transport(always_empty=True)),self.assertRaisesRegex(h.HarnessRunError,'恢复.*已用完|恢复后仍'):
            planning.plan(self.session,self.prepared,self.observer)
        self.assertEqual(len(self.calls),2);self.assertEqual(self.observer.empty_recoveries,1)
        self.assertNotIn(self.uid,self.prepared['state']['agent_sessions']);self.assertEqual(self.session,before)

    def test_cancelled_empty_unit_never_uses_the_recovery_quota(self):
        with patch.object(h,'unit_run',side_effect=self.empty_transport(cancel=True)),self.assertRaisesRegex(RuntimeError,'取消'):
            planning.plan(self.session,self.prepared,self.observer)
        self.assertEqual(len(self.calls),1);self.assertEqual(self.observer.empty_recoveries,0)
        self.assertNotIn(self.uid,self.prepared['state']['agent_sessions'])

    def test_empty_unit_recovery_shares_the_existing_whole_operation_quota(self):
        self.observer.empty_recoveries=1
        with patch.object(h,'unit_run',side_effect=self.empty_transport()),self.assertRaisesRegex(h.HarnessRunError,'恢复.*已用完|额度'):
            planning.plan(self.session,self.prepared,self.observer)
        self.assertEqual(len(self.calls),1);self.assertEqual(self.observer.empty_recoveries,1)
        self.assertNotIn(self.uid,self.prepared['state']['agent_sessions'])

    def test_valid_json_cannot_rebind_another_unit_or_acquire_a_format_retry(self):
        value=json.dumps(dict(order=dict(unit_id='other-unit',action='hold'),rationale='不合法身份'))
        with patch.object(h,'unit_run',side_effect=self.transport([value,GOOD])),self.assertRaisesRegex(ValueError,'不能改写单位身份'):
            planning.plan(self.session,self.prepared,self.observer)
        self.assertEqual(len(self.calls),1);self.assertEqual(self.observer.json_recoveries,0)


if __name__=='__main__':unittest.main()
