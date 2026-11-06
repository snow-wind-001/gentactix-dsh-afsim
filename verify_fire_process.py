"""Model-reported fire timing/resource evidence; never a casualty executor."""
import copy
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gentactix import historical_operations as operations, missions
from tools.qa.historical_operational_fixture import inputs
from verify_dsh_resources import model_result


class FireProcessTests(unittest.TestCase):
    def setUp(self):
        self.world=operations.initial(*inputs())

    def shot(self):
        from gentactix import fire_process
        value=model_result(self.world);actor=self.world['red_units'][0];target=self.world['blue_units'][0]
        value['orders'][0].update(action='fire',target=target['name'])
        value['engagements']=[{'attacker':actor['name'],'attacker_team':'red',
            'attacker_pos':[actor['lat'],actor['lng']],'target':target['name'],
            'lat':target['lat'],'lng':target['lng'],'weapon_action':'fire'}]
        value['resource_ledger']['units'][0]['ammo_spent']=14
        value['unit_updates'][0]['logistics']['ammo']-=14
        value['unit_updates'][0]['formation']={'suppression':0,'intel_age_min':40,'intel_confidence':70,'reload_remaining_s':30}
        value['unit_updates'][1]['formation'].update(suppression=30)
        delay=next(u['delay_s'] for u in fire_process.observation(self.world)['units'] if u['unit']==actor['name'])
        self.assertLessEqual(delay,150)
        value['fire_ledger']={'version':'dsh-fire-estimate-1','units':[{'unit':actor['name'],'action':'fire','target':target['name'],
            'delay_s':delay,'first_fire_s':150,'last_fire_s':1710,'fire_cycles':14,'active_fire_s':1650,
            'reload_remaining_s':30,'stop_reason':'none','assumptions':'测试的模型估计，无历史或原生遥测声明。'}]}
        return value

    def apply(self,value,**kwargs):
        from backend import dsh_simulation
        with patch.object(missions,'advance',side_effect=AssertionError('No Python combat executor')):
            return dsh_simulation.apply(self.world,value,'30分钟',**kwargs)

    def test_prompt_supplies_registered_feedback_parameters_without_mutating_world(self):
        from backend import dsh_simulation
        prior=copy.deepcopy(self.world)
        text=dsh_simulation.prompt(self.world)
        self.assertIn('command_signal_s',text)
        self.assertIn('intel_age_decay',text)
        self.assertIn('dsh-fire-estimate-1',text)
        self.assertIn('每个周期',text)
        self.assertEqual(self.world,prior)

    def test_real_protocol_rejects_missing_fire_ledger_instead_of_inventing_it(self):
        value=self.shot();value.pop('fire_ledger');prior=copy.deepcopy(self.world)
        with self.assertRaisesRegex(ValueError,'fire_ledger'):self.apply(value,require_fire_ledger=True)
        self.assertEqual(self.world,prior)

    def test_valid_zero_hit_fire_keeps_zero_casualties_and_explicit_estimate_source(self):
        value=self.shot();prior=copy.deepcopy(value);after=self.apply(value,require_fire_ledger=True)
        self.assertEqual(after['blue_units'][0]['personnel']['casualties'],0)
        ledger=after['dsh_execution']['fire_ledger']
        self.assertEqual(ledger['source'],'dsh_model_estimate')
        self.assertEqual(ledger['units'][0]['fire_cycles'],14)
        self.assertEqual(value,prior)
        self.assertNotIn('last_execution',value['unit_updates'][0]['formation'])

    def test_communication_and_firing_window_reject_the_observed_eighth_cycle(self):
        from gentactix import fire_process
        value=self.shot();r=value['fire_ledger']['units'][0]
        r.update(fire_cycles=8,first_fire_s=150,last_fire_s=990,active_fire_s=750)
        with self.assertRaisesRegex(ValueError,'时间|窗口|周期'):
            fire_process.validate(self.world,self.world,value,900,required=True)
        r.update(fire_cycles=7,last_fire_s=870,delay_s=0)
        with self.assertRaisesRegex(ValueError,'联络|延迟'):
            fire_process.validate(self.world,self.world,value,900,required=True)

    def test_cycle_cost_must_match_parent_scaled_resource_ledger(self):
        value=self.shot();value['fire_ledger']['units'][0]['fire_cycles']=13
        with self.assertRaisesRegex(ValueError,'弹药|周期'):self.apply(value,require_fire_ledger=True)

    def test_fire_ledger_cannot_describe_a_hold_or_a_different_target(self):
        for kind in ('hold','target','duplicate'):
            value=self.shot()
            if kind=='hold':value['fire_ledger']['units'][0]['action']='hold'
            if kind=='target':value['fire_ledger']['units'][0]['target']=self.world['blue_units'][1]['name']
            if kind=='duplicate':value['fire_ledger']['units']*=2
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.apply(value,require_fire_ledger=True)

    def test_firing_feedback_states_must_be_explicit_without_forcing_a_loss_floor(self):
        value=self.shot();value['unit_updates'][0].pop('formation')
        with self.assertRaisesRegex(ValueError,'状态|压制|情报'):self.apply(value,require_fire_ledger=True)

    def test_native_feedback_identifies_the_repeated_missing_action_field(self):
        value=self.shot();value['fire_ledger']['units'][0].pop('action')
        prior=copy.deepcopy((self.world,value))
        with self.assertRaisesRegex(ValueError,'fire_ledger.*缺少字段.*action'):
            self.apply(value,require_fire_ledger=True)
        self.assertEqual((self.world,value),prior)

    def test_hold_and_legacy_estimates_do_not_acquire_fake_fire_timing(self):
        after=self.apply(model_result(self.world),require_fire_ledger=True)
        self.assertNotIn('fire_ledger',after['dsh_execution'])
        legacy=self.shot();legacy.pop('fire_ledger')
        after=self.apply(legacy)
        self.assertNotIn('fire_ledger',after['dsh_execution'])
        self.assertIsNone(after['combat_assessment']['units'][0]['incoming_max_fire_s'])

    def test_passive_cooldown_rejects_the_real_stale_sixty_seconds_without_repair(self):
        from tools.qa.boundary_lifecycle_fixture import inputs as boundary_inputs
        from verify_campaign_plan_backends import proposal
        self.world=operations.initial(*boundary_inputs())
        name=self.world['blue_units'][0]['name']
        self.world['blue_units'][0]['formation'].update(reload_remaining_s=60,reload_remaining=60)
        prior=copy.deepcopy(self.world)
        for submitted in (None,60):
            value=proposal(self.world)
            if submitted is not None:next(r for r in value['unit_updates'] if r['unit']==name)['formation']['reload_remaining_s']=submitted
            untouched=copy.deepcopy(value)
            with self.subTest(submitted=submitted),self.assertRaisesRegex(ValueError,'轮初=60.*本轮=900.*期末须=0'):
                from backend import dsh_simulation
                dsh_simulation.apply(self.world,value,'15分钟',require_fire_ledger=True)
            self.assertEqual(self.world,prior)
            self.assertEqual(value,untouched)
        value=proposal(self.world)
        next(r for r in value['unit_updates'] if r['unit']==name)['formation']['reload_remaining_s']=0
        from backend import dsh_simulation
        after=dsh_simulation.apply(self.world,value,'15分钟',require_fire_ledger=True)
        self.assertEqual(after['blue_units'][0]['formation']['reload_remaining_s'],0)
        self.assertEqual(self.world,prior)
        self.assertNotIn('fire_ledger',after['dsh_execution'])

    def test_passive_cooldown_partial_wait_legacy_units_and_canonical_precedence(self):
        from gentactix import fire_process
        for initial,legacy,expected in ((1800,60,900),(0,60,0),(None,10,300)):
            old=copy.deepcopy(self.world);unit=old['blue_units'][0]
            unit['formation']['reload_remaining']=legacy
            if initial is None:unit['formation'].pop('reload_remaining_s',None)
            else:unit['formation']['reload_remaining_s']=initial
            value=model_result(old,seconds=900);new=copy.deepcopy(old)
            value['unit_updates'][1]['formation']['reload_remaining_s']=expected
            new['blue_units'][0]['formation']['reload_remaining_s']=expected
            with self.subTest(initial=initial,legacy=legacy):
                self.assertIsNone(fire_process.validate(old,new,value,900,required=True))
                new['blue_units'][0]['formation']['reload_remaining_s']=expected+1
                with self.assertRaisesRegex(ValueError,'装填倒计时'):
                    fire_process.validate(old,new,value,900,required=True)

    def test_passive_clock_runs_for_nonfiring_actions_even_when_not_available(self):
        from gentactix import fire_process
        old=copy.deepcopy(self.world);old['blue_units'][0]['formation']['reload_remaining_s']=1800
        for action in ('hold','move','resupply','conceal','air_support'):
            value=model_result(old,seconds=900);new=copy.deepcopy(old)
            value['orders'][1]['action']=action
            value['unit_updates'][1]['formation']['reload_remaining_s']=900
            new['blue_units'][0]['formation']['reload_remaining_s']=900
            with self.subTest(action=action):
                self.assertIsNone(fire_process.validate(old,new,value,900))
        # The native end-of-frame timer has no alive/release guard. A disabled
        # formation still advances its clock, without inventing an action.
        old['blue_units'][0]['personnel']['current']=0
        value=model_result(old,seconds=900);new=copy.deepcopy(old)
        value['unit_updates'][1]['formation']['reload_remaining_s']=900
        new['blue_units'][0]['formation']['reload_remaining_s']=900
        self.assertIsNone(fire_process.validate(old,new,value,900))
        new['blue_units'][0]['formation']['reload_remaining_s']=1800
        with self.assertRaisesRegex(ValueError,'装填倒计时'):fire_process.validate(old,new,value,900)

    def test_shooter_cooldown_must_follow_last_shot_or_a_zero_shot_wait(self):
        from gentactix import fire_process
        value=self.shot()
        for residual in (0,31):
            value['fire_ledger']['units'][0]['reload_remaining_s']=residual
            value['unit_updates'][0]['formation']['reload_remaining_s']=residual
            with self.subTest(residual=residual),self.assertRaisesRegex(ValueError,'末发|期末装填'):
                self.apply(value,require_fire_ledger=True)
        value=self.shot();row=value['fire_ledger']['units'][0]
        row.update(last_fire_s=1710.75,reload_remaining_s=30)
        self.assertIsNotNone(fire_process.validate(self.world,self.world,value,1800,required=True))
        # A fire command waiting the whole window has no new reload cycle.
        self.world['red_units'][0]['formation']['reload_remaining_s']=2400
        value=model_result(self.world);target=self.world['blue_units'][0]['name']
        value['orders'][0].update(action='fire',target=target)
        value['unit_updates'][0]['formation'].update(suppression=0,intel_confidence=70,reload_remaining_s=600)
        value['fire_ledger']={'version':fire_process.VERSION,'units':[dict(unit=self.world['red_units'][0]['name'],action='fire',target=target,
            delay_s=fire_process.delay_seconds(self.world,self.world['red_units'][0]),first_fire_s=None,last_fire_s=None,
            fire_cycles=0,active_fire_s=0,reload_remaining_s=600,stop_reason='reload_pending',assumptions='本轮未装填完成，不射击。')]}
        self.assertIsNotNone(fire_process.validate(self.world,self.world,value,1800,required=True))
        value['fire_ledger']['units'][0]['reload_remaining_s']=2400
        value['unit_updates'][0]['formation']['reload_remaining_s']=2400
        with self.assertRaisesRegex(ValueError,'期末装填'):fire_process.validate(self.world,self.world,value,1800,required=True)

    def test_runtime_corrects_rejected_passive_timer_through_existing_feedback(self):
        from backend import dsh_simulation
        self.world['blue_units'][0]['formation']['reload_remaining_s']=60
        bad=model_result(self.world);good=copy.deepcopy(bad)
        good['unit_updates'][1]['formation']['reload_remaining_s']=0
        before=copy.deepcopy(self.world)
        with patch.object(dsh_simulation.h,'get_ai_response',side_effect=[bad,good]) as model:
            result,_,_=dsh_simulation.advance({'war_state':self.world,'time_step':'30分钟'},None,None)
        self.assertEqual(model.call_count,2)
        self.assertIn('期末须=0',model.call_args.args[0])
        self.assertEqual(result['updated_state']['blue_units'][0]['formation']['reload_remaining_s'],0)
        self.assertEqual(self.world,before)

    def test_readonly_basis_uses_current_parameters_not_fixed_qa_delays(self):
        from gentactix import fire_process
        a=fire_process.observation(self.world);world=copy.deepcopy(self.world)
        world['mission']['definition']['combined_rules']['command_base_s']+=30
        b=fire_process.observation(world)
        self.assertEqual(b['units'][0]['delay_s']-a['units'][0]['delay_s'],30)
        self.assertEqual(a['parameters']['command_base_s'],60)
        self.assertIn('sqrt',a['formulas']['direct_cover'])

    def test_malformed_or_unbounded_model_receipts_fail_without_mutation(self):
        for field,bad in [('delay_s',float('nan')),('active_fire_s',True),('fire_cycles',10**1000),('stop_reason',[])]:
            value=self.shot();value['fire_ledger']['units'][0][field]=bad
            prior=copy.deepcopy(self.world)
            with self.subTest(field=field),self.assertRaises(ValueError):self.apply(value,require_fire_ledger=True)
            self.assertEqual(self.world,prior)

    def test_incoming_fire_needs_explicit_target_pressure_estimate_even_without_hits(self):
        value=self.shot();value['unit_updates'][1].pop('formation')
        with self.assertRaisesRegex(ValueError,'压制'):self.apply(value,require_fire_ledger=True)

    def test_runtime_retry_requests_the_missing_receipt_and_keeps_the_main_world(self):
        from backend import dsh_simulation
        good=self.shot();bad=copy.deepcopy(good);bad.pop('fire_ledger');prior=copy.deepcopy(self.world)
        with patch.object(dsh_simulation.h,'get_ai_response',side_effect=[bad,good]) as model:
            result,_,_=dsh_simulation.advance({'war_state':self.world,'time_step':'30分钟'},None,None)
        self.assertEqual(model.call_count,2)
        self.assertIn('fire_ledger',model.call_args.args[0])
        self.assertEqual(self.world,prior)
        self.assertEqual(result['updated_state']['dsh_execution']['fire_ledger']['units'][0]['fire_cycles'],14)

    def test_short_round_can_wait_for_communication_with_no_fire_no_losses(self):
        from gentactix import fire_process
        value=model_result(self.world);u=self.world['red_units'][0];target=self.world['blue_units'][0]
        value['orders'][0].update(action='fire',target=target['name'])
        value['unit_updates'][0]['formation']={'suppression':0,'intel_age_min':11,'intel_confidence':80,'reload_remaining_s':0}
        value['fire_ledger']={'version':fire_process.VERSION,'units':[{'unit':u['name'],'action':'fire','target':target['name'],
            'delay_s':fire_process.delay_seconds(self.world,u),'first_fire_s':None,'last_fire_s':None,'fire_cycles':0,
            'active_fire_s':0,'reload_remaining_s':0,'stop_reason':'command_pending','assumptions':'一分钟不足以收到命令，未宣称实际射击。'}]}
        checked=fire_process.validate(self.world,self.world,value,60,required=True)
        self.assertEqual(checked['units'][0]['fire_cycles'],0)
        with self.assertRaisesRegex(ValueError,'等待原因'):
            fire_process.validate(self.world,self.world,value,1800,required=True)

    def test_readonly_tool_exposes_only_current_unit_estimate_with_explicit_source(self):
        from backend import afsim_state
        world=self.apply(self.shot(),require_fire_ledger=True)
        world['dsh_execution']['fire_ledger']['units'][0]['assumptions']='x'*5000
        session={'id':'a123456789ab','war_state':world,'turn_count':1,'time_step':'30分钟','role_epoch':0}
        before=copy.deepcopy(session)
        view=afsim_state.observation(session,{'limit':1})
        row=view['units'][0];receipt=row['model_fire_estimate']
        self.assertEqual(receipt['source'],'dsh_model_estimate')
        self.assertEqual(receipt['fire_cycles'],14)
        self.assertLessEqual(len(receipt['assumptions']),400)
        self.assertEqual(receipt['last_fire_s'],1710)
        self.assertNotIn('model_fire_estimate',afsim_state.observation(session,{'offset':1,'limit':1})['units'][0])
        self.assertIn('turn_offset',view['event_time_semantics']['model_fire_estimate.first_fire_s'])
        self.assertFalse(view['execution']['verified'])
        self.assertEqual(session,before)

    def test_readonly_tool_never_backfills_legacy_stale_or_wrong_source_estimates(self):
        from backend import afsim_state
        world=self.apply(self.shot(),require_fire_ledger=True)
        for kind in ('legacy','stale','source'):
            candidate=copy.deepcopy(world)
            if kind=='legacy':candidate['dsh_execution'].pop('fire_ledger')
            elif kind=='stale':candidate['dsh_execution']['fire_ledger']['turn']=0
            else:candidate['dsh_execution']['fire_ledger']['source']='afsim_native'
            session={'id':'a123456789ab','war_state':candidate,'turn_count':1,'time_step':'30分钟','role_epoch':0}
            with self.subTest(kind=kind):
                self.assertTrue(all('model_fire_estimate' not in row for row in afsim_state.observation(session)['units']))

    def test_dsh_analysis_routes_bind_fresh_committed_world_to_existing_native_tools(self):
        from fastapi.testclient import TestClient
        from backend import main,harness_engine as h
        initial,parameters=inputs()
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{
                'GENTACTIX_SESSION_DIR':directory+'/sessions','GENTACTIX_TRACE_DIR':directory+'/traces'}), \
                patch.object(h,'_run_brain',return_value=SimpleNamespace(events=[],final_response='只读估计核对')) as run, \
                patch('backend.afsim_world.run_scene',side_effect=AssertionError('No AFSIM for DSH observation')):
            client=TestClient(main.app)
            response=client.post('/api/sessions',json={'scenario':'射击估计只读核对',
                'battle':initial['definition']['battle'],'historical_parameters':parameters,
                'product_mode':'historical','simulation_mode':'open','execution_backend':'narrative',
                'time_step':'30分钟','persist_roles':False})
            self.assertEqual(response.status_code,200,response.text)
            sid=response.json()['session_id'];path='/api/sessions/'+sid
            try:
                response=client.post(path+'/init');self.assertEqual(response.status_code,200,response.text)
                session=main._SESSIONS[sid];session['war_state']=self.apply(self.shot(),require_fire_ledger=True)
                session['turn_count']=1;before=copy.deepcopy(session['war_state'])
                for suffix in ('/chat','/review'):
                    with self.subTest(route=suffix):
                        response=client.post(path+suffix,json={'message':'只读核对本轮射击过程'} if suffix=='/chat' else {})
                        self.assertEqual(response.status_code,200,response.text)
                        context=run.call_args.kwargs.get('native_context')
                        self.assertIsNotNone(context,'DSH estimates must use existing current-state tools, not stale chat memory')
                        self.assertEqual(context['session']['war_state'],before)
                        self.assertIn('model_fire_estimate',run.call_args.args[0])
                        self.assertEqual(session['war_state'],before)
            finally:main._SESSIONS.pop(sid,None)

    def test_analysis_facts_label_model_estimates_without_claiming_native_execution(self):
        from backend import afsim_state
        world=self.apply(self.shot(),require_fire_ledger=True)
        session={'id':'a123456789ab','war_state':world,'turn_count':1,'time_step':'30分钟','role_epoch':0}
        text=afsim_state.analysis_facts(session)
        self.assertIn('DSH模型估计',text)
        self.assertIn('14周期',text)
        self.assertNotIn('团级原生模型',text)
        self.assertNotIn('外部回传实体',text)


if __name__=='__main__':unittest.main()
