"""Known narrative failures and native preview provenance, not a language oracle."""
import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from gentactix import reporting


def frames():
    before={'current_time':'1938-10-07 03:00','red_units':[dict(name='第159师',personnel=dict(current=300,committed=300,casualties=0,noncombat_losses=0),
        logistics=dict(food=68,ammo=80),supply=68)],'blue_units':[],'engagements':[],
        'mission':{'turn':6,'definition':{'campaign_plan':{'nodes':[dict(id='g',label='保持兵力')]}},'ledger':[]},
        'campaign_plan':{'nodes':{'g':dict(status='waiting_phase',condition=None,reason='等待阶段采样')}},
        'campaign_lifecycle':dict(phase_index=0,last_sample_phase=0,status='active',last_changes=[])}
    before['mission']['definition']['campaign_lifecycle']={'phases':[dict(id='p1',label='阶段一'),dict(id='p2',label='阶段二')]}
    after=copy.deepcopy(before);after['current_time']='1938-10-07 03:30';after['mission']['turn']=7
    after['red_units'][0]['logistics']['food']=66
    after['mission']['ledger']=[dict(unit='第159师',food_spent=2,ammo_spent=0,delivery=0,received={},spent={},source='dsh_model_estimate')]
    after['campaign_plan']['nodes']['g'].update(status='completed',condition=True,reason='目标条件满足')
    after['campaign_lifecycle'].update(phase_index=1,last_sample_phase=0,last_changes=[dict(phase_id='p1',status='completed',at_seconds=12600),dict(phase_id='p2',status='active',at_seconds=12600)])
    return before,after


class SettlementTests(unittest.TestCase):
    def test_actual_food_and_ammo_equal_cost_claim_is_rejected(self):
        old,new=frames();saved=copy.deepcopy(new)
        raw='各单位维持既有阵地与防护，粮弹按待机消耗各扣减2工作量，期末粮余66、弹余80。'
        text,audit=reporting.render(raw,new,old,turn=7)
        self.assertIn('inventory_claim',{i['code'] for i in audit['issues']})
        self.assertNotIn('粮弹按待机',text);self.assertEqual(audit['original_text'],raw);self.assertEqual(new,saved)

    def test_actual_no_material_consumption_cannot_hide_known_food_spend(self):
        old,new=frames();_,audit=reporting.render('各单位扣减粮食2点，本轮无物资消耗。',new,old,turn=7)
        self.assertIn('inventory_claim',{i['code'] for i in audit['issues']})

    def test_original_t9_warehouse_balance_does_not_scope_later_unqualified_zero_cost(self):
        old,new=frames()
        raw='各单位按待命行动扣减粮食工作量2点。本轮无补给到达，补给线路未观察到切断，仓库余额维持零，无物资消耗产生。'
        text,audit=reporting.render(raw,new,old,turn=7)
        self.assertIn('inventory_claim',{i['code'] for i in audit['issues']})
        self.assertNotIn('无物资消耗产生',text)

    def test_actual_no_scoring_change_cannot_override_completed_goal_and_phase(self):
        old,new=frames();_,audit=reporting.render('当前处于阶段一窗口，未激活评分节点，本轮无状态变化可观测。',new,old,turn=7)
        self.assertIn('phase_verdict',{i['code'] for i in audit['issues']})

    def test_host_facts_expose_gross_cost_and_observed_stage(self):
        old,new=frames();text=reporting.facts(new,old)
        self.assertIn('粮食消耗2',text);self.assertIn('弹药消耗0',text)
        self.assertIn('本轮观察阶段：阶段一',text);self.assertIn('轮末阶段：阶段二',text)

    def test_receipts_use_gross_cost_even_when_delivery_hides_net_change(self):
        old,new=frames();row=new['mission']['ledger'][0]
        row.update(delivery=2,food_spent=2,ammo_spent=2)
        new['red_units'][0]['logistics']=copy.deepcopy(old['red_units'][0]['logistics'])
        text,audit=reporting.render('第159师粮弹各消耗2。',new,old,turn=7)
        self.assertEqual(audit['status'],'screened');self.assertIn('粮食消耗2',text)

    def test_unknown_receipt_is_not_zero_and_team_scope_is_not_whole_world(self):
        old,new=frames();new['mission']['ledger']=[]
        _,audit=reporting.render('本轮无物资消耗。',new,old,turn=7)
        self.assertIn('inventory_claim',{i['code'] for i in audit['issues']})
        self.assertIn('粮食消耗未记录',reporting.facts(new,old))
        old,new=frames();new['blue_units']=[dict(name='蓝方巡逻队')]
        new['mission']['ledger'].append(dict(unit='蓝方巡逻队',food_spent=0,ammo_spent=0,spent={}))
        _,audit=reporting.render('蓝方本轮无物资消耗。',new,old,turn=7)
        self.assertEqual(audit['status'],'screened')

    def test_initial_historical_conditional_and_unit_only_changes_are_not_false_flags(self):
        old,new=frames()
        for text in ('轮初处于阶段一，轮末已进入阶段二。','如果本轮无状态变化，应重新检查。',
                     '人员状态无变化，阶段已推进。','上一轮粮弹各消耗2。','仓库无物资消耗，前沿部队仍扣粮。'):
            with self.subTest(text=text):
                _,audit=reporting.render(text,new,old,turn=7)
                self.assertEqual(audit['status'],'screened',audit['issues'])

    def test_actual_explicit_denial_of_full_strength_is_not_a_full_strength_claim(self):
        old,new=frames()
        for raw in ('现有人数300人，累计投入不能据此称满编。','现有人数300人，不据此称满编。','并非满编，现有人数300人。'):
            with self.subTest(raw=raw):
                _,audit=reporting.render(raw,new,old,turn=7)
                self.assertNotIn('strength_claim',{i['code'] for i in audit['issues']})
        _,audit=reporting.render('不据此称满编。另一支部队现已满编。',new,old,turn=7)
        self.assertIn('strength_claim',{i['code'] for i in audit['issues']})

    def test_future_unsampled_goals_are_unknown_in_settlement_not_false(self):
        from gentactix import turn_settlement
        old,new=frames();new['mission']['definition']['campaign_plan']['nodes'].append(dict(id='future',label='后续阶段目标'))
        new['campaign_plan']['nodes']['future']=dict(status='waiting_phase',condition=False,reason='尚未采样')
        saved=copy.deepcopy(new);summary=turn_settlement.build(new,old)
        future=next(r for r in summary['goals'] if r['id']=='future')
        self.assertIsNone(future['condition']);self.assertFalse(future['condition_sampled'])
        current=next(r for r in summary['goals'] if r['id']=='g')
        self.assertTrue(current['condition']);self.assertTrue(current['condition_sampled'])
        self.assertEqual(new,saved)

    def test_settlement_has_known_personnel_changes_and_preserves_unknown_counts(self):
        from gentactix import turn_settlement
        old,new=frames();new['red_units'][0]['personnel'].update(current=295,casualties=5)
        row=turn_settlement.build(new,old)['units'][0]
        self.assertEqual(row['personnel']['current'],295);self.assertEqual(row['personnel']['before_current'],300)
        self.assertEqual(row['personnel']['battle_losses'],5)
        del old['red_units'][0]['personnel']['current']
        self.assertIsNone(turn_settlement.build(new,old)['units'][0]['personnel']['before_current'])

    def test_actual_t5_supply_index_unchanged_claim_is_rejected(self):
        old,new=frames()
        raw='两侧仓库分类存量均为0，未安排运输，DSH派生补给指数未变，但这不代表线路通断已被证实。'
        _,audit=reporting.render(raw,new,old,turn=7)
        self.assertIn('supply_index_claim',{i['code'] for i in audit['issues']})
        new['red_units'][0]['logistics']=copy.deepcopy(old['red_units'][0]['logistics'])
        _,audit=reporting.render('第159师补给指数保持不变。',new,old,turn=7)
        self.assertNotIn('supply_index_claim',{i['code'] for i in audit['issues']})
        # A cause-specific denial does not assert the entire index is unchanged.
        old,new=frames();_,audit=reporting.render('补给指数未因到货变化，耗粮仍使指数降低。',new,old,turn=7)
        self.assertNotIn('supply_index_claim',{i['code'] for i in audit['issues']})

    def test_actual_completed_transition_is_checked_against_both_frames(self):
        old,new=frames()
        raw='目标“保持兵力”本轮已采样且条件成立，状态由未达成转为已完成。'
        _,audit=reporting.render(raw,new,old,turn=7)
        self.assertNotIn('goal_verdict',{i['code'] for i in audit['issues']})
        old['campaign_plan']['nodes']['g'].update(status='completed',condition=True)
        _,audit=reporting.render(raw,new,old,turn=7)
        self.assertIn('goal_verdict',{i['code'] for i in audit['issues']})

    def test_committed_public_report_cannot_still_say_current_effects_await_commit(self):
        old,new=frames();raw='以上仅适用于已预览候选，命令与持续任务仍待原子提交。'
        _,audit=reporting.render(raw,new,old,turn=7)
        self.assertIn('commit_claim',{i['code'] for i in audit['issues']})
        self.assertNotIn('仍待原子提交',reporting.instruction(settlement_preview=True))
        self.assertIn('成功提交后展示',reporting.instruction(settlement_preview=True))

    def test_settlement_supply_indices_derive_from_stock_not_stale_display_fields(self):
        from gentactix import turn_settlement
        old,new=frames();new['red_units'][0]['supply']=99
        row=turn_settlement.build(new,old)['units'][0]
        self.assertEqual(row['supply_index_before'],68);self.assertEqual(row['supply_index_after'],66)
        self.assertIn('补给指数 66（本步-2）',reporting.facts(new,old))

    def test_summary_bounds_unit_rows_but_keeps_complete_team_costs(self):
        from gentactix import turn_settlement
        old,new=frames();prototype=copy.deepcopy(new['red_units'][0]);new['red_units']=[];new['mission']['ledger']=[]
        for index in range(79):
            u=copy.deepcopy(prototype);u['name']='QA'+str(index);new['red_units'].append(u)
            new['mission']['ledger'].append(dict(unit=u['name'],food_spent=2,ammo_spent=0,delivery=0,spent={}))
        value=turn_settlement.projection(turn_settlement.build(new,old))
        self.assertEqual(len(value['units']),16);self.assertEqual(value['unlisted_units'],63)
        self.assertEqual(value['resource_teams'][0]['food_spent'],158)


class PreviewTests(unittest.TestCase):
    def setUp(self):
        from tools.qa.campaign_lifecycle_fixture import session
        from verify_campaign_plan_backends import proposal
        from backend import turn_preview,harness_engine as h
        self.s=session();self.s['agent_mode']='native';self.value=proposal(self.s['war_state'])
        self.observer=h.RunObserver('offline native preview protocol')
        self.ctx=turn_preview.context(self.s,None,operation_id=self.observer.operation_id)

    def call(self,value=None):
        from backend import turn_preview
        return turn_preview.execute(self.ctx,dict(tool=turn_preview.TOOL,args={'candidate':copy.deepcopy(value or self.value)}))

    def record(self,reply,value=None):
        from backend import turn_preview
        self.observer.runs.append(dict(events=[
            dict(type='tool/call',seq=1,session_id='qa-native',callId='p1',name=turn_preview.TOOL,arguments=json.dumps({'candidate':value or self.value})),
            dict(type='tool/result',seq=2,session_id='qa-native',message={'toolCallId':'p1','content':[dict(type='text',text=json.dumps(reply))]})]))
        return dict(preview_hash=reply.get('digest','missing'),report='双方待命，粮食按已知回执扣减；未发生交火。')

    def test_preview_scores_same_world_but_never_executes_or_changes_inputs(self):
        from gentactix import missions
        saved=copy.deepcopy(self.s);candidate=copy.deepcopy(self.value)
        with patch.object(missions,'advance',side_effect=AssertionError('No executor')):
            reply=self.call()
        self.assertTrue(reply['ok'],reply);self.assertTrue(reply['readonly'])
        self.assertEqual(reply['settlement']['phase']['after_label'],'QA阶段2')
        self.assertEqual(self.s,saved);self.assertEqual(self.value,candidate)

    def test_newly_active_phase_is_not_confused_with_its_unsampled_goal(self):
        reply=self.call();self.assertTrue(reply['ok'],reply)
        goals={r['id']:r for r in reply['settlement']['goals']}
        self.assertFalse(goals['milestone2']['condition_sampled'])
        self.assertEqual(goals['milestone2']['phase_at_end']['status'],'active')
        self.assertEqual(goals['milestone1']['phase_at_end']['status'],'completed')
        self.assertEqual(goals['milestone3']['phase_at_end']['status'],'pending')

    def test_missing_failed_and_forged_trajectory_never_resolves(self):
        from backend import turn_preview
        reply=self.call();final=dict(preview_hash=reply['digest'],report='待命。')
        with self.assertRaisesRegex(ValueError,'轨迹'):turn_preview.resolve(final,self.observer,self.ctx)
        reply['ok']=False;self.record(reply)
        with self.assertRaises(ValueError):turn_preview.resolve(final,self.observer,self.ctx)
        self.observer.runs=[];final=self.record(self.call());final['preview_hash']='forged'
        with self.assertRaises(ValueError):turn_preview.resolve(final,self.observer,self.ctx)

    def test_stale_world_and_other_operation_fingerprints_are_rejected(self):
        from backend import turn_preview
        final=self.record(self.call())
        for kind in ('world','operation'):
            ctx=copy.deepcopy(self.ctx)
            if kind=='world':ctx['session']['war_state']['red_units'][0]['logistics']['food']-=1
            else:ctx['turn_preview']['operation_id']='another-operation'
            with self.subTest(kind=kind),self.assertRaisesRegex(ValueError,'指纹'):
                turn_preview.resolve(final,self.observer,ctx)

    def test_illegal_candidate_is_rejected_without_any_balance_repair(self):
        bad=copy.deepcopy(self.value);bad['unit_updates'][0]['logistics']['food']+=2
        saved=copy.deepcopy(bad);reply=self.call(bad)
        self.assertFalse(reply['ok']);self.assertIn('收支',reply['error']);self.assertEqual(bad,saved)

    def test_native_final_uses_tool_trajectory_without_repeating_effect_json(self):
        from backend import dsh_simulation,turn_preview,harness_engine as h
        saved=copy.deepcopy(self.s)
        def model(_message,**kwargs):
            self.ctx=kwargs['native_context'];self.observer=kwargs['observer']
            return self.record(self.call())
        with patch.object(h,'NATIVE_RUNTIME',True),patch.object(h,'get_ai_response',side_effect=model):
            result,_,_=dsh_simulation.advance(self.s,None,self.observer)
        self.assertEqual(result['updated_state']['red_units'][0]['logistics']['food'],78)
        self.assertEqual(result['report_preview']['evidence'],'dsh_public_tool_trajectory');self.assertEqual(self.s,saved)

    def test_json_integer_equivalence_survives_native_javascript_round_trip(self):
        from backend import turn_preview
        raw=copy.deepcopy(self.value);raw['unit_updates'][0]['logistics']['food']=78.0
        reply=self.call(raw);final=self.record(reply,raw)
        candidate,proof=turn_preview.resolve(final,self.observer,self.ctx)
        self.assertEqual(candidate['unit_updates'][0]['logistics']['food'],78)
        self.assertEqual(proof['digest'],reply['digest'])
        raw['unit_updates'][0]['personnel']={'current':299.5,'casualties':.5}
        self.assertFalse(self.call(raw)['ok'])

    def test_only_native_process_engine_has_preview_permission(self):
        from backend import harness_engine as h
        self.assertIn('preview_turn_effects',h.role_policy('engine',tools=True,process=True)['allowed_tools'])
        for role,external,process in [('chat',False,True),('engine',True,True),('engine',False,False)]:
            self.assertNotIn('preview_turn_effects',h.role_policy(role,tools=True,external=external,process=process)['allowed_tools'])

    def test_native_effect_process_uses_preview_instead_of_afsim_order_dry_run(self):
        from backend import harness_engine as h
        self.assertNotIn('evaluate_action',h.role_policy('engine',tools=True,process=True)['allowed_tools'])
        self.assertIn('evaluate_action',h.role_policy('engine',tools=True,external=True)['allowed_tools'])
        self.assertIn('evaluate_action',h.role_policy('chat',tools=True)['allowed_tools'])

    def test_preview_prompt_does_not_keep_the_pre_settlement_goal_prohibition(self):
        from backend import dsh_simulation
        legacy=dsh_simulation.prompt(self.s['war_state'])
        native=dsh_simulation.prompt(self.s['war_state'],settlement_preview=True)
        self.assertIn('省略目标完成',legacy)
        self.assertNotIn('省略目标完成',native)
        self.assertIn('允许引用成功预览的宿主目标与阶段结算',native)
        self.assertIn('未提供的距离',native)

    def test_preview_keeps_manual_priority_and_no_half_commit(self):
        from gentactix import commands
        from backend import turn_preview
        view=commands.view(self.s)
        self.s['command_state']=commands.replace_queue(self.s,[dict(unit_id=u['id'],action='hold',duration='next') for u in view['units']],
            control_team='red',director=True,no_fire=False,intent='QA manual holds')
        prepared=commands.prepare(self.s);saved=copy.deepcopy(self.s)
        self.ctx=turn_preview.context(self.s,prepared,operation_id=self.observer.operation_id)
        value=copy.deepcopy(self.value);value['orders'][0].update(action='fire',target=self.s['war_state']['blue_units'][0]['name'])
        reply=self.call(value);self.assertTrue(reply['ok'],reply)
        self.assertTrue(all(r['action']=='hold' for r in reply['settlement']['units']))
        self.assertEqual(self.s,saved)

    def test_cancel_after_model_reply_does_not_return_or_consume_candidate(self):
        from backend import dsh_simulation,harness_engine as h
        saved=copy.deepcopy(self.s);cancelled=False
        def model(_message,**kwargs):
            nonlocal cancelled
            self.ctx=kwargs['native_context'];self.observer=kwargs['observer'];final=self.record(self.call());cancelled=True;return final
        with patch.object(h,'NATIVE_RUNTIME',True),patch.object(h,'get_ai_response',side_effect=model),self.assertRaisesRegex(RuntimeError,'取消'):
            dsh_simulation.advance(self.s,None,self.observer,cancel_check=lambda:cancelled)
        self.assertEqual(self.s,saved)


if __name__=='__main__':unittest.main()
