"""Continuous stages never clone worlds or reset their physical/command ledgers."""
import copy
import json
import unittest
from gentactix import commands, missions, historical_operations
from tools.qa.campaign_lifecycle_fixture import inputs,session
from verify_campaign_plan_backends import proposal


def step(s):
    from backend import dsh_simulation
    saved=copy.deepcopy(s);prepared=commands.prepare(s);candidate=proposal(s['war_state'])
    after=dsh_simulation.apply(s['war_state'],candidate,s['time_step'])
    cs,_=commands.finish(s,prepared,after,executed=candidate['orders'])
    result={**copy.deepcopy(s),'war_state':after,'command_state':cs,'turn_count':s['turn_count']+1}
    assert s==saved
    commands.validate_saved(result)
    return result


class CampaignLifecycleTests(unittest.TestCase):
    def test_ten_stages_gap_and_continuous_resources_never_clone_the_world(self):
        s=session();definition=copy.deepcopy(s['war_state']['mission']['definition'])
        original={u['name']:copy.deepcopy(u) for _,u in missions.units(s['war_state'])}
        for turn in range(1,13):
            s=step(s);w=s['war_state'];life=w['campaign_lifecycle']
            self.assertEqual(w['mission']['definition'],definition)
            self.assertNotIn('phase_continuation',json.dumps(definition))
            self.assertEqual(w['simulation_clock']['elapsed_seconds'],turn*1800)
            for _,u in missions.units(w):
                self.assertEqual(u['personnel'],original[u['name']]['personnel'])
                self.assertEqual(u['logistics']['food'],80-turn*2)
                self.assertEqual(u['logistics']['ammo'],80)
            if turn<12:self.assertEqual(w['mission']['status'],'active')
        self.assertEqual(life['status'],'completed')
        self.assertEqual(len([r for r in life['phases'].values() if r['status']=='completed']),10)
        self.assertEqual(w['mission']['winner'],'red')

    def test_future_goal_cannot_complete_before_its_stage_and_no_early_global_win(self):
        source,p=inputs();p['campaign_plan']['outcomes']['red']['node_ids']=['milestone1']
        w=historical_operations.initial(source,p);s={**session(),'war_state':w}
        s=step(s)
        self.assertEqual(s['war_state']['campaign_plan']['nodes']['milestone10']['status'],'waiting_phase')
        self.assertEqual(s['war_state']['mission']['status'],'active')

    def test_repeated_scoring_and_cold_json_recovery_do_not_advance_again(self):
        s=step(session());saved=copy.deepcopy(s['war_state'])
        missions.evaluate(s['war_state']);self.assertEqual(s['war_state'],saved)
        recovered=json.loads(json.dumps(s));self.assertTrue(missions.validate(recovered['war_state']))
        self.assertEqual(step(recovered)['war_state'],step(s)['war_state'])

    def test_reject_invalid_goal_bindings_empty_zero_duration_and_unsupported_phase_facts(self):
        source,p=inputs()
        for mutate in [lambda v:v['phases'][0]['goal_ids'].append('unknown'),
                       lambda v:v['phases'][1].update(goal_ids=['milestone1']),
                       lambda v:v['phases'][3].update(minimum_duration_seconds=0),
                       lambda v:v['phases'][0].update(unit_ids=['invented'])]:
            bad=copy.deepcopy(p);mutate(bad['campaign_lifecycle'])
            with self.subTest(value=bad['campaign_lifecycle']):
                with self.assertRaises(ValueError):historical_operations.initial(source,bad)

    def test_stage_dependencies_cannot_wait_for_a_later_phase(self):
        source,p=inputs();p['campaign_plan']['nodes'][0]['after']['node_ids']=['milestone10']
        with self.assertRaisesRegex(ValueError,'后阶段'):historical_operations.initial(source,p)

    def test_actual_command_task_identity_and_counts_continue_across_all_stages(self):
        from gentactix import force_organization as forces
        from verify_force_task_execution import register,execution
        s=session();pairs=commands.resolve_units(s);unit=next(i for i,(e,u) in pairs.items() if u['historical_unit_id']=='ww2.cn.division159')
        s['command_state']=commands.replace_queue(s,[dict(unit_id=i,action='hold',duration='until_turn',end_turn=30) for i in pairs if i!=unit],
            control_team='red',director=True,no_fire=False,intent='QA跨阶段')
        s['force_organization']=forces.detach(s,[unit],'跨阶段任务群','软件QA，不是历史改隶')
        group=s['force_organization']['groups'][-1]['id'];organization=copy.deepcopy(s['force_organization'])
        identity=register(s,group,None,execution('跨十阶段任务',finish=dict(kind='turn',end_turn=12,minimum_executions=12)),kind='defend')
        registry=copy.deepcopy(s['command_state']['registry'])
        for _ in range(12):
            s=step(s)
            self.assertEqual(s['command_state']['registry'],registry)
            self.assertEqual(s['force_organization'],organization)
        task=s['command_state']['task_plans'][identity]['execution']
        self.assertEqual(task['status'],'completed');self.assertEqual(task['member_states'][unit]['executions'],12)

    def test_invalid_model_effect_or_injected_stage_state_never_advances_source(self):
        from backend import dsh_simulation
        s=session();before=copy.deepcopy(s)
        for mode in ('injected','bad_balance'):
            value=proposal(s['war_state'])
            if mode=='injected':value['campaign_lifecycle']=copy.deepcopy(s['war_state']['campaign_lifecycle'])
            else:value['resource_ledger']['units'][0]['food_spent']=99
            with self.subTest(mode=mode):
                with self.assertRaises(ValueError):dsh_simulation.apply(s['war_state'],value,'30分钟')
                self.assertEqual(s,before)

    def test_native_paging_is_readonly_bounded_and_rejects_old_version(self):
        from gentactix import campaign_lifecycle as life
        from backend import agent_tools,harness_engine
        s=session();saved=copy.deepcopy(s);args={'limit':3};ids=[];first=life.observation(s['war_state'],**args)
        while args:
            page=life.observation(s['war_state'],**args);ids.extend(r['id'] for r in page['rows']);args=page['next_args']
        self.assertEqual(len(ids),10);self.assertEqual(len(set(ids)),10);self.assertEqual(s,saved)
        reply=agent_tools.execute_tool_call(s,s['war_state'],{'tool':'get_campaign_lifecycle','args':{'limit':2}})
        self.assertTrue(reply['ok']);self.assertTrue(reply['readonly']);self.assertEqual(len(reply['rows']),2)
        self.assertIn('get_campaign_lifecycle',harness_engine.role_policy('engine',tools=True,external=True)['allowed_tools'])
        with self.assertRaises(ValueError):life.observation(s['war_state'],offset=2)
        with self.assertRaises(ValueError):life.observation(s['war_state'],limit=17)
        after=step(s)
        with self.assertRaises(ValueError):life.observation(after['war_state'],**first['next_args'])

    def test_same_frame_cannot_accept_tampered_lifecycle_state(self):
        s=step(session());s['war_state']['campaign_lifecycle']['phase_index']=8
        with self.assertRaises(ValueError):missions.evaluate(s['war_state'])
        with self.assertRaises(ValueError):missions.validate(s['war_state'])

    def test_restore_cannot_complete_a_stage_before_any_physical_round(self):
        from gentactix import campaign_lifecycle as life
        s=session();w=s['war_state'];state=w['campaign_lifecycle']
        state.update(phase_index=1,last_sample_phase=0)
        state['phases']['phase1'].update(status='completed',completed_at=0,goal_evidence={'milestone1':'completed'})
        state['phases']['phase2'].update(status='active',entered_at=0)
        life._seal(state)
        with self.assertRaises(ValueError):missions.validate(w)

    def test_saved_phase_changes_must_reference_registered_stages_and_sample_time(self):
        from gentactix import campaign_lifecycle as life
        original=step(session())['war_state']
        for change in [dict(phase_id='unknown',status='active',at_seconds=1800),
                       dict(phase_id='phase2',status='active',at_seconds=0)]:
            w=copy.deepcopy(original);w['campaign_lifecycle']['last_changes']=[change];life._seal(w['campaign_lifecycle'])
            with self.subTest(change=change):
                with self.assertRaises(ValueError):missions.validate(w)

    def test_synthetic_derivation_keeps_explicit_stage_contract_and_old_source(self):
        from gentactix import synthetic_history
        s=session();saved=copy.deepcopy(s);binding=s['war_state']['mission']['definition']['historical_calculation']
        config=synthetic_history.seed(binding)['configuration']
        spec=synthetic_history.definition(binding,config);w=missions.from_definition(spec)
        self.assertEqual(w['mission']['definition']['campaign_lifecycle'],s['war_state']['mission']['definition']['campaign_lifecycle'])
        self.assertEqual(w['campaign_lifecycle']['phase_index'],0);self.assertEqual(s,saved)

    def test_prompt_does_not_repeat_full_stage_state_and_reports_unknown_future_predicate(self):
        from backend import dsh_simulation
        from gentactix import reporting
        s=step(session());w=s['war_state'];text=dsh_simulation.prompt(w,turn=2)
        physical=json.loads(text.split('\n当前态势：',1)[1].split('\n史料：',1)[0])
        self.assertNotIn('campaign_lifecycle',physical);self.assertIn('当前第2/10阶段',text)
        self.assertIn('QA阶段9兵力保持：当前条件尚未采样',reporting.facts(w))
        _,audit=reporting.render('QA阶段9兵力保持的当前条件不成立。',w,turn=1)
        self.assertIn('goal_verdict',{r['code'] for r in audit['issues']})

    def test_explicit_goal_outcome_policy_allows_early_opponent_success(self):
        source,p=inputs();p['campaign_lifecycle']['finish_policy']='goal_outcomes'
        p['campaign_plan']['nodes'][-1]['condition']={'kind':'preserve','minimum_fraction':.5}
        s={**session(),'war_state':historical_operations.initial(source,p)};after=step(s)['war_state']
        self.assertEqual(after['mission']['winner'],'blue')
        self.assertEqual(after['campaign_lifecycle']['status'],'interrupted')
        self.assertEqual(after['campaign_lifecycle']['phases']['phase10']['status'],'pending')


if __name__=='__main__':unittest.main()
