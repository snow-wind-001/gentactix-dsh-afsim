"""Persistent domain tasks reuse existing commands; all physics here are QA estimates."""
import copy
import unittest
from unittest.mock import patch

from gentactix import commands, force_organization as forces, force_tasks, missions
from tools.qa.campaign_plan_fixture import session as fixture
from verify_campaign_plan_backends import proposal

VERSION='force-task-execution-1'


def setup():
    session=fixture()
    session['command_state']=commands.replace_queue(session,[],control_team='red',director=True,no_fire=False,intent='QA')
    ids={u.get('historical_unit_id'):identity for identity,(_,u) in commands.resolve_units(session).items()}
    groups={}
    for label,key in [('north','ww2.cn.division159'),('south','ww2.cn.division51')]:
        session['force_organization']=forces.detach(session,[ids[key]],label+'任务群','显式QA临时配属')
        groups[label]=session['force_organization']['groups'][-1]['id']
    points={n['id']:n['condition'].get('region',{}).get('center') for n in session['war_state']['mission']['definition']['campaign_plan']['nodes']}
    return session,ids,groups,points


def execution(label,*,after=(),finish=None,start=1):
    return dict(version=VERSION,label=label,not_before_turn=start,
        after=dict(mode='all',task_ids=list(after),goal_ids=[]),
        finish=finish or dict(kind='arrived'),assumption='软件任务生命周期QA；不是历史命令')


def register(s,group,point,config,kind='advance'):
    task=dict(kind=kind,destination=point) if kind=='advance' else dict(kind=kind)
    preview=force_tasks.preview(s,group,task,execution=config)
    s['command_state']=force_tasks.commit(s,group,task,preview['preview_hash'],execution=config)
    return list(s['command_state']['task_plans'])[-1]


def step(session):
    """Explicit typed proposal, no model or AFSIM call; no product effect fallback."""
    from backend import dsh_simulation
    saved=copy.deepcopy(session);prepared=commands.prepare(session)
    assert saved==session
    draft=proposal(session['war_state'])
    orders={o['unit']:o for o in draft['orders']}
    changes={o['unit']:o for o in draft['unit_updates']}
    ledger={o['unit']:o for o in draft['resource_ledger']['units']}
    for row in prepared['manual']:
        action=row['order'];orders[action['unit']]=action
        if action['action']=='move':
            changes[action['unit']].update(lat=action['lat'],lng=action['lng'])
            changes[action['unit']]['logistics']['food']-=2;ledger[action['unit']]['food_spent']+=2
    draft['orders']=list(orders.values())
    after=dsh_simulation.apply(session['war_state'],draft,'30分钟')
    cs,_=commands.finish(session,prepared,after,executed=draft['orders'])
    result={**copy.deepcopy(session),'war_state':after,'command_state':cs,'turn_count':session['turn_count']+1}
    commands.validate_saved(result)
    return result,prepared


class ForceTaskExecutionTests(unittest.TestCase):
    def test_assault_at_its_waypoint_waits_without_counting_zero_distance_movement(self):
        s,ids,g,p=setup()
        from gentactix import historical_operations
        from tools.qa.campaign_plan_fixture import inputs
        source,parameters=inputs()
        parameters['actors']['ww2.cn.division159']['position']['lat']+=.03
        s['war_state']=historical_operations.initial(source,parameters)
        unit=commands.resolve_units(s)[ids['ww2.cn.division159']][1]
        task=dict(kind='assault',destination={k:unit[k] for k in ('lat','lng')},target_id=ids['ww2.jp.division106'])
        config=execution('目标尚未进入射程',finish=dict(kind='turn',end_turn=3,minimum_executions=1))
        preview=force_tasks.preview(s,g['north'],task,execution=config)
        self.assertEqual(preview['rows'][0]['order']['action'],'hold')
        self.assertIn('任务地域',preview['rows'][0]['reason'])
        s['command_state']=force_tasks.commit(s,g['north'],task,preview['preview_hash'],execution=config)
        a,prepared=step(s);runtime=list(a['command_state']['task_plans'].values())[-1]['execution']
        self.assertEqual(runtime['status'],'blocked')
        member=runtime['member_states'][ids['ww2.cn.division159']]
        self.assertEqual(member['executions'],0)
        self.assertEqual(member['reason'],preview['rows'][0]['reason'])
        # A valid hold receipt must not erase the actionable planning cause.
        # A specific executor refusal still has precedence over that cause.
        from gentactix import force_task_execution as lifecycle
        receipt=next(r for r in a['command_state']['receipts'] if r['unit_id']==ids['ww2.cn.division159'])
        for actual_reason in ('', '执行时道路已中断'):
            with self.subTest(receipt_reason=actual_reason):
                changed=copy.deepcopy(receipt);changed['reason']=actual_reason
                result=lifecycle.finish(s,copy.deepcopy(prepared['state']),a['war_state'],[changed])
                state=list(result['task_plans'].values())[-1]['execution']['member_states'][changed['unit_id']]
                self.assertEqual(state['reason'],actual_reason or preview['rows'][0]['reason'])
                self.assertEqual(state['executions'],0)

    def test_legal_assault_approach_counts_delivery_without_claiming_a_shot(self):
        s,ids,g,p=setup()
        from gentactix import historical_operations
        from tools.qa.campaign_plan_fixture import inputs
        source,parameters=inputs()
        parameters['actors']['ww2.cn.division159']['position']['lat']+=.03
        s['war_state']=historical_operations.initial(source,parameters)
        enemy=commands.resolve_units(s)[ids['ww2.jp.division106']][1]
        task=dict(kind='assault',destination={k:enemy[k] for k in ('lat','lng')},
            target_id=ids['ww2.jp.division106'])
        config=execution('攻坚接近',finish=dict(kind='turn',end_turn=3,minimum_executions=2))
        preview=force_tasks.preview(s,g['north'],task,execution=config)
        self.assertEqual(preview['rows'][0]['order']['action'],'move')
        self.assertEqual(preview['rows'][0]['status'],'ready')
        s['command_state']=force_tasks.commit(s,g['north'],task,preview['preview_hash'],execution=config)
        identity=list(s['command_state']['task_plans'])[-1]
        before=copy.deepcopy(s)
        a,prepared=step(s)
        receipt=next(r for r in prepared['manual'] if r['command']['unit_id']==ids['ww2.cn.division159'])
        self.assertEqual(receipt['order']['action'],'move')
        self.assertEqual(receipt['command']['task_context']['expected_action'],'move')
        runtime=a['command_state']['task_plans'][identity]['execution']
        self.assertEqual(runtime['status'],'executing')
        self.assertEqual(runtime['member_states'][ids['ww2.cn.division159']]['executions'],1)
        original_enemy=commands.resolve_units(before)[ids['ww2.jp.division106']][1]
        self.assertEqual(commands.resolve_units(a)[ids['ww2.jp.division106']][1]['personnel'],original_enemy['personnel'])
        self.assertEqual(s,before)

    def test_two_axes_wait_release_complete_and_leave_physics_to_the_executor(self):
        s,ids,g,p=setup();saved=copy.deepcopy(s['war_state'])
        first=register(s,g['north'],p['north'],execution('先行方向'))
        second=register(s,g['south'],p['south'],execution('预备队',after=[first]))
        self.assertEqual(s['war_state'],saved)
        a,prepared=step(s);issued={o['command']['unit_id']:o['order']['action'] for o in prepared['manual']}
        self.assertEqual(issued[ids['ww2.cn.division159']],'move');self.assertEqual(issued[ids['ww2.cn.division51']],'hold')
        self.assertEqual(a['command_state']['task_plans'][first]['execution']['status'],'completed')
        self.assertNotEqual(a['command_state']['task_plans'][second]['execution']['status'],'completed')
        b,prepared=step(a)
        self.assertEqual(next(o['order']['action'] for o in prepared['manual'] if o['command']['unit_id']==ids['ww2.cn.division51']),'move')
        self.assertEqual(b['command_state']['task_plans'][second]['execution']['status'],'completed')
        self.assertEqual(b['war_state']['mission']['winner'],'red')

    def test_existing_and_subsequent_manual_orders_are_never_recaptured(self):
        s,ids,g,p=setup();task=register(s,g['north'],p['north'],execution('主攻'))
        unit=ids['ww2.cn.division159']
        s['command_state']=commands.replace_queue(s,[dict(unit_id=unit,action='recon',duration='next')],
            control_team='red',director=True,no_fire=False,intent='人工优先')
        a,_=step(s);b,prepared=step(a)
        self.assertFalse(any(o['command']['unit_id']==unit for o in prepared['manual']))
        self.assertEqual(b['command_state']['task_plans'][task]['execution']['member_states'][unit]['status'],'manual_override')

    def test_restored_record_order_cannot_change_dependency_completion(self):
        s,ids,g,p=setup();unit=commands.resolve_units(s)[ids['ww2.cn.division51']][1]
        first=register(s,g['north'],p['north'],execution('先行'))
        second=register(s,g['south'],dict(lat=unit['lat'],lng=unit['lng']),execution('已在目的地的后续',after=[first]))
        restored=copy.deepcopy(s)
        restored['command_state']['task_plans']=dict(reversed(list(restored['command_state']['task_plans'].items())))
        normal,_=step(s);reordered,prepared=step(restored)
        # The reserve still holds during the predecessor round. At settlement,
        # predicates use dependency order rather than JSON object key order.
        self.assertEqual(next(row['order']['action'] for row in prepared['manual'] if row['command']['unit_id']==ids['ww2.cn.division51']),'hold')
        for identity in (first,second):
            expected=normal['command_state']['task_plans'][identity]['execution']
            actual=reordered['command_state']['task_plans'][identity]['execution']
            self.assertEqual(expected['status'],actual['status'])
            self.assertEqual(expected['events'],actual['events'])
            self.assertEqual([row['executions'] for row in expected['member_states'].values()],
                             [row['executions'] for row in actual['member_states'].values()])
        self.assertEqual(normal['war_state'],reordered['war_state'])
        self.assertEqual(reordered['command_state']['task_plans'][second]['execution']['status'],'completed')

    def test_goal_dependency_and_not_before_wait_instead_of_silently_investing_reserves(self):
        s,ids,g,p=setup();config=execution('延后',start=3)
        config['after']['goal_ids']=['north']
        task=register(s,g['south'],p['south'],config)
        a,prepared=step(s)
        self.assertEqual(prepared['manual'][0]['order']['action'],'hold')
        runtime=a['command_state']['task_plans'][task]['execution']
        self.assertIn(runtime['status'],('waiting_time','waiting_dependency'))
        self.assertEqual(a['war_state']['red_units'][0]['personnel'],s['war_state']['red_units'][0]['personnel'])

    def test_already_at_destination_does_not_complete_before_task_start(self):
        s,ids,g,p=setup();unit=commands.resolve_units(s)[ids['ww2.cn.division159']][1]
        task=register(s,g['north'],dict(lat=unit['lat'],lng=unit['lng']),execution('延后任务',start=3))
        a,_=step(s)
        self.assertEqual(a['command_state']['task_plans'][task]['execution']['status'],'waiting_time')

    def test_undelivered_native_command_does_not_satisfy_execution_count(self):
        from backend import dsh_simulation
        s,ids,g,p=setup();s['execution_backend']='afsim'
        task=register(s,g['north'],p['north'],execution('未交付',finish=dict(kind='turn',end_turn=1,minimum_executions=1)),kind='defend')
        prepared=commands.prepare(s);value=proposal(s['war_state']);after=dsh_simulation.apply(s['war_state'],value,'30分钟')
        # Minimal policy fixture, deliberately not advertised as native telemetry.
        after.pop('dsh_execution');after['afsim']={'effects_source':'afsim-native-fixture'}
        for team in ('red','blue'):
            for unit in after[team+'_units']:unit['formation']['last_execution']={'turn':1,'command_done':0,'blocked':0}
        cs,_=commands.finish(s,prepared,after,executed=value['orders'])
        runtime=cs['task_plans'][task]['execution']
        self.assertEqual(runtime['member_states'][ids['ww2.cn.division159']]['executions'],0)
        self.assertEqual(runtime['status'],'failed')

    def test_transfer_revokes_old_task_and_reassignment_does_not_expand_members(self):
        s,ids,g,p=setup();task=register(s,g['north'],p['north'],execution('原指挥任务'))
        s['force_organization']=forces.detach(s,[ids['ww2.cn.division159']],'新指挥','QA转隶')
        prepared=commands.prepare(s)
        self.assertFalse(any(o['command']['unit_id']==ids['ww2.cn.division159'] for o in prepared['manual']))
        self.assertEqual(prepared['state']['task_plans'][task]['execution']['status'],'blocked')

    def test_overlapping_tasks_and_bad_dependency_versions_reject_without_mutation(self):
        s,ids,g,p=setup();register(s,g['north'],p['north'],execution('已占用'))
        for config in [execution('重叠'),execution('未知前置',after=['missing'])]:
            saved=copy.deepcopy(s)
            with self.assertRaises(ValueError):register(s,g['north'],p['north'],config)
            self.assertEqual(s,saved)

    def test_cancel_removes_only_owned_orders_and_never_rolls_back_consumption(self):
        from gentactix import force_task_execution as lifecycle
        s,ids,g,p=setup();task=register(s,g['north'],p['north'],execution('待取消',start=3))
        a,_=step(s);world=copy.deepcopy(a['war_state'])
        a['command_state']=lifecycle.cancel(a,task)
        self.assertEqual(a['war_state'],world)
        prepared=commands.prepare(a)
        self.assertFalse(any(o['command']['unit_id']==ids['ww2.cn.division159'] for o in prepared['manual']))
        self.assertEqual(a['command_state']['task_plans'][task]['execution']['status'],'cancelled')

    def test_turn_window_counts_valid_defensive_hold_and_stops_at_its_boundary(self):
        s,ids,g,p=setup();config=execution('构筑窗口',finish=dict(kind='turn',end_turn=2,minimum_executions=2))
        task=register(s,g['north'],p['north'],config,kind='defend')
        a,_=step(s);self.assertEqual(a['command_state']['task_plans'][task]['execution']['status'],'executing')
        # A defensive hold is the intended maneuver action, not a fortify fallback.
        self.assertEqual(a['command_state']['task_plans'][task]['execution']['member_states'][ids['ww2.cn.division159']]['executions'],1)
        b,_=step(a);self.assertEqual(b['command_state']['task_plans'][task]['execution']['status'],'completed')

    def test_missing_artillery_capability_fallback_does_not_count_as_fire_support(self):
        s,ids,g,p=setup();task=dict(kind='defend',target_id=ids['ww2.jp.division106'],roles={ids['ww2.cn.division159']:'fire_support'})
        config=execution('支援窗口',finish=dict(kind='turn',end_turn=1,minimum_executions=1))
        preview=force_tasks.preview(s,g['north'],task,execution=config)
        self.assertEqual(preview['rows'][0]['order']['action'],'hold')
        s['command_state']=force_tasks.commit(s,g['north'],task,preview['preview_hash'],execution=config)
        a,_=step(s);runtime=list(a['command_state']['task_plans'].values())[-1]['execution']
        self.assertEqual(runtime['member_states'][ids['ww2.cn.division159']]['executions'],0)
        self.assertEqual(runtime['status'],'failed')

    def test_task_window_with_too_few_real_executions_fails(self):
        s,ids,g,p=setup();task=register(s,g['north'],p['north'],execution('不足次数',finish=dict(kind='turn',end_turn=2,minimum_executions=3)),kind='defend')
        a,_=step(s);b,_=step(a)
        self.assertEqual(b['command_state']['task_plans'][task]['execution']['status'],'failed')

    def test_repeated_readonly_preparation_preserves_movement_intent_ids(self):
        s,ids,g,p=setup();register(s,g['north'],p['north'],execution('分段前进'))
        before=copy.deepcopy(s)
        first=commands.prepare(s);second=commands.prepare(s)
        self.assertEqual(first,second);self.assertEqual(s,before)

    def test_one_readonly_batch_restores_the_frozen_source_only_once(self):
        from gentactix import historical_operations
        s,ids,g,p=setup();register(s,g['north'],p['north'],execution('先行'))
        with patch.object(historical_operations,'from_binding',wraps=historical_operations.from_binding) as restore:
            commands.prepare(s)
        self.assertEqual(restore.call_count,1)

    def test_readonly_validation_scope_does_not_accept_another_invalid_world(self):
        s,_,_,_=setup();invalid=copy.deepcopy(s['war_state']);invalid['mission']['definition_hash']='bad'
        with missions.validation_scope(s['war_state']):
            with self.assertRaises(ValueError):missions.validate(invalid)
        with self.assertRaises(ValueError):missions.validate(invalid)

    def test_readonly_scope_rejects_accidental_state_mutation_before_return(self):
        s,_,_,_=setup();world=s['war_state']
        with self.assertRaisesRegex(ValueError,'只读'):
            with missions.validation_scope(world):world['red_units'][0]['logistics']['food']-=1

    def test_cancel_individual_owned_order_prevents_next_turn_regeneration(self):
        s,ids,g,p=setup();destination=copy.deepcopy(p['north']);destination['lat']+=.02
        register(s,g['north'],destination,execution('分段移动待取消'))
        a,_=step(s)
        owned=next(o for o in a['command_state']['orders'] if o['unit_id']==ids['ww2.cn.division159'])
        a['command_state']=commands.cancel(a,owned['id'])
        self.assertFalse(any(o['command']['unit_id']==ids['ww2.cn.division159'] for o in commands.prepare(a)['manual']))

    def test_import_rejects_cycles_and_forged_definition_without_repairing_them(self):
        s,ids,g,p=setup();task=register(s,g['north'],p['north'],execution('合法'))
        commands.validate_saved(s)
        corrupt=copy.deepcopy(s);runtime=corrupt['command_state']['task_plans'][task]['execution']
        runtime['definition']['after']['task_ids']=[task]
        with self.assertRaises(ValueError):commands.validate_saved(corrupt)
        from gentactix import force_task_execution as lifecycle
        runtime['definition_hash']=lifecycle._definition_hash(corrupt['command_state']['task_plans'][task]);lifecycle._stamp(runtime)
        with self.assertRaisesRegex(ValueError,'成环'):commands.validate_saved(corrupt)

    def test_native_tool_dispatch_is_bounded_and_cannot_write_tasks(self):
        from backend import agent_tools,harness_engine
        s,ids,g,p=setup();register(s,g['north'],p['north'],execution('原生读取'))
        before=copy.deepcopy(s)
        result=agent_tools.execute_tool_call(s,s['war_state'],{'tool':'get_force_tasks','args':{'limit':1}})
        self.assertTrue(result['ok']);self.assertTrue(result['readonly']);self.assertEqual(len(result['rows']),1)
        self.assertEqual(s,before)
        self.assertIn('get_force_tasks',harness_engine.role_policy('engine',tools=True,external=True)['allowed_tools'])

    def test_native_pages_are_readonly_and_pin_the_world_and_command_revision(self):
        from gentactix import force_task_execution as lifecycle
        s,ids,g,p=setup();register(s,g['north'],p['north'],execution('北'))
        register(s,g['south'],p['south'],execution('南'))
        before=copy.deepcopy(s);page=lifecycle.observation(s,{'limit':1});self.assertTrue(page['next_args'])
        final=lifecycle.observation(s,page['next_args']);self.assertEqual(final['offset'],1)
        self.assertEqual(s,before)
        s['command_state']['revision']+=1
        with self.assertRaises(commands.Conflict):lifecycle.observation(s,page['next_args'])


if __name__=='__main__':unittest.main()
