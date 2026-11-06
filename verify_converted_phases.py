"""Formal conversions across one-world phases; all fixture numbers are estimates."""
import copy
import json
import os
import tempfile
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from backend import dsh_simulation, formation_commit, session_store
from gentactix import commands, campaign_lifecycle, campaign_plan, formation_conversion, force_organization, force_tasks, missions
from verify_formation_commit import fixture
from verify_formation_continuity import world, selected
from verify_formation_session import register
from verify_force_task_execution import execution
from verify_campaign_plan_backends import proposal


def source():
    w=world(boundary=True);u=selected(w)
    # Explicit software accounting fixture, not actual combat or a historical total.
    u['personnel'].update(current=9866,casualties=134)
    e=next(e for e in u['equipment'] if e['category']=='transport');e.update(operational=19,damaged=1)
    campaign_plan.initialize(w)
    return fixture(w)


def conversion(s,ids,kind='split'):
    args=dict(kind=kind,unit_ids=ids,assumption='连续阶段软件估计，非历史编组或兵额')
    if kind=='split':
        unit=commands.resolve_units(s)[ids[0]][1];n=unit['personnel']['committed']
        args['allocations']=[dict(id='a',label='连续左',committed=n//2),dict(id='b',label='连续右',committed=n-n//2)]
    v=commands.view(s);p=formation_conversion.observation(s,args)
    req=dict(**args,expected_turn=v['turn'],revision=v['revision'],world_version=v['world_version'],
        organization_revision=force_organization.state(s)['revision'],view_version=p['view_version'],commit_id=uuid.uuid4().hex)
    return req,formation_commit.commit(s,req)


def hold_others(s,excluded):
    v=commands.view(s)
    s['command_state']=commands.replace_queue(s,[dict(unit_id=u['id'],action='hold',duration='next') for u in v['units'] if u['id'] not in excluded and u['available']],
        control_team='red',director=True,no_fire=True,intent='离线阶段协议检查，非模型响应或真实战果')


def step(s):
    """Typed estimate fixture only; normal host checks own all phase/goal scoring."""
    old=copy.deepcopy(s);prepared=commands.prepare(s);value=proposal(s['war_state'])
    rows={r['unit']:r for r in value['unit_updates']};ledger={r['unit']:r for r in value['resource_ledger']['units']}
    orders={r['unit']:r for r in value['orders']}
    for item in prepared['manual']:
        order=item['order'];orders[order['unit']]=order
        if order['action']=='move':
            row=rows[order['unit']];row.update({k:order[k] for k in ('lat','lng')})
            row['logistics']['food']-=2;ledger[order['unit']]['food_spent']+=2
    value['orders']=list(orders.values())
    units={u['name']:u for _,u in missions.units(s['war_state'])}
    for row in value['resource_ledger']['units']:
        row['food_spent']*=formation_conversion.resource_scale(units[row['unit']])
    after=dsh_simulation.apply(s['war_state'],value,s['time_step'])
    cs,_=commands.finish(s,prepared,after,executed=value['orders'])
    candidate={**session_store.serializable(s),'war_state':after,'last_war_state':copy.deepcopy(s['war_state']),
        'command_state':cs,'turn_count':s['turn_count']+1}
    session_store.validate(candidate);assert s==old
    return candidate


class ConvertedPhaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source,cls.root,cls.group=source()
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':directory}):
            s=copy.deepcopy(cls.source);tid=register(s,cls.group,execution('四轮连续防御',finish=dict(kind='turn',end_turn=4,minimum_executions=4)))
            hold_others(s,{cls.root});s=step(s)
            req,result=conversion(s,[cls.root]);children=result['command_map'][cls.root]
            hold_others(s,set(children));s=step(s)
            _,result=conversion(s,children,'merge');merged=next(iter(result['command_map'].values()))[0]
            hold_others(s,{merged});s=step(s)
            _,result=conversion(s,[merged]);current=result['command_map'][merged]
            cls.phase3=(s,tid,current,req)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'GENTACTIX_SESSION_DIR':self.temp.name});self.env.start()
        self.s=copy.deepcopy(self.source)

    def tearDown(self):self.env.stop();self.temp.cleanup()

    def before_phase3(self):
        return copy.deepcopy(self.phase3)

    def test_three_phase_identity_changes_preserve_fixed_definition_clock_and_existing_damage(self):
        s,tid,ids,_=self.before_phase3();w=s['war_state']
        self.assertEqual(w['campaign_lifecycle']['phase_index'],2)
        self.assertEqual(w['mission']['definition'],self.source['war_state']['mission']['definition'])
        self.assertEqual(w['simulation_clock']['elapsed_seconds'],2700)
        units=[commands.resolve_units(s)[i][1] for i in ids]
        self.assertEqual(sum(u['personnel']['current'] for u in units),9866)
        self.assertEqual(sum(u['personnel']['casualties'] for u in units),134)
        self.assertEqual(len(s['formation_commits']),3)
        self.assertEqual(w['campaign_plan']['nodes']['north']['status'],'waiting_phase')
        session_store.save(s);loaded,errors=session_store.load_all();self.assertFalse(errors)
        self.assertEqual(session_store.serializable(loaded[s['id']]),session_store.serializable(s))

    def test_phase_change_does_not_reset_or_sum_inherited_task_counts(self):
        s,tid,ids,_=self.before_phase3();runtime=s['command_state']['task_plans'][tid]['execution']
        self.assertEqual([r['executions'] for r in runtime['member_states'].values()],[3,3])
        hold_others(s,set(ids));s=step(s);runtime=s['command_state']['task_plans'][tid]['execution']
        self.assertEqual(runtime['status'],'completed')
        self.assertEqual([r['executions'] for r in runtime['member_states'].values()],[4,4])
        self.assertEqual(s['war_state']['mission']['status'],'active')
        self.assertEqual(s['war_state']['campaign_lifecycle']['phase_index'],2)

    def test_conversion_retry_maps_original_and_current_actors_without_reexecuting(self):
        s,_,ids,request=self.before_phase3();old=copy.deepcopy(s)
        with patch.object(session_store,'save',side_effect=AssertionError('No replay write')):
            replay=formation_commit.commit(s,request)
        self.assertTrue(replay['replayed'])
        first=s['command_state']['formation_handoffs'][0]['command_map']
        self.assertEqual(replay['command_map'],first)
        self.assertEqual(replay['current_command_map'],{self.root:ids})
        self.assertEqual(s,old)

    def test_zero_time_conversion_does_not_resample_phase_or_complete_goals(self):
        s=self.s;phase=copy.deepcopy(s['war_state']['campaign_lifecycle']);clock=copy.deepcopy(s['war_state']['simulation_clock'])
        _,result=conversion(s,[self.root]);self.assertEqual(s['war_state']['campaign_lifecycle'],phase)
        self.assertEqual(s['war_state']['simulation_clock'],clock)
        self.assertFalse(s['war_state']['campaign_plan']['outcomes']['red'])
        _,result=conversion(s,result['command_map'][self.root],'merge')
        self.assertEqual(s['war_state']['campaign_lifecycle'],phase);self.assertEqual(s['turn_count'],0)

    def test_model_cannot_choose_phase_or_supply_host_progress(self):
        s=self.s;conversion(s,[self.root]);old=copy.deepcopy(s)
        for field in ('campaign_lifecycle','campaign_plan'):
            value=proposal(s['war_state']);value[field]=copy.deepcopy(s['war_state'][field])
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'顶层字段'):
                dsh_simulation.apply(s['war_state'],value,'15分钟')
        self.assertEqual(s,old)

    def test_all_three_phases_and_two_axes_finish_by_program_goals_without_reinitialization(self):
        s,tid,ids,_=self.before_phase3();hold_others(s,set(ids));s=step(s)
        points={n['id']:n['condition'].get('region',{}).get('center') for n in s['war_state']['mission']['definition']['campaign_plan']['nodes']}
        south=next(i for i,(_,u) in commands.resolve_units(s).items() if u.get('source_historical_unit_id')=='ww2.cn.division51')
        s['force_organization']=force_organization.detach(s,[south],'南侧连续目标','软件双方向验收，非历史改隶')
        south_group=s['force_organization']['groups'][-1]['id']
        for group,key in [(self.group,'north'),(south_group,'south')]:
            config=execution(key+'阶段三到达',start=s['turn_count']+1)
            v=force_tasks.preview(s,group,dict(kind='advance',destination=points[key]),execution=config)
            s['command_state']=force_tasks.commit(s,group,dict(kind='advance',destination=points[key]),v['preview_hash'],execution=config)
        for _ in range(8):
            hold_others(s,set(ids)|{south});s=step(s)
            if s['war_state']['mission']['status']=='completed':break
        self.assertEqual(s['war_state']['mission']['winner'],'red')
        self.assertEqual(s['war_state']['campaign_lifecycle']['status'],'completed')
        self.assertTrue(all(p['status']=='completed' for p in s['war_state']['campaign_lifecycle']['phases'].values()))
        self.assertEqual(s['command_state']['task_plans'][tid]['execution']['status'],'completed')
        self.assertEqual(s['war_state']['mission']['definition_hash'],self.source['war_state']['mission']['definition_hash'])
        self.assertEqual(sum(u['personnel']['casualties'] for _,u in missions.units(s['war_state'])),134)

    def test_native_unit_observes_current_phase_without_repeating_frozen_definition(self):
        from backend import unit_planning,harness_engine
        for engine in ('narrative','afsim'):
            with self.subTest(engine=engine):
                s,_,_,_=self.before_phase3();s['execution_backend']=engine
                blue=next(i for i,(row,_) in commands.resolve_units(s).items() if row['team']=='blue')
                s['command_state']['unit_agents']=[blue];before=copy.deepcopy(s);seen=[]
                def native(binding,prompt,observer,*,context,namespace,on_session=None):
                    seen.append((json.loads(prompt.split('\n',1)[1]),context))
                    created=dict(session_id='gentactix-unit-'+namespace+'-qa')
                    if on_session:on_session(created)
                    return SimpleNamespace(final_response=json.dumps(dict(order=dict(action='hold',duration='next'),rationale='离线观察协议检查'))),created
                with patch.object(harness_engine,'unit_run',side_effect=native):
                    unit_planning.plan(s,commands.prepare(s),harness_engine.RunObserver('阶段转换单位作用域回归'))
                self.assertEqual(len(seen),1);body,context=seen[0]
                self.assertFalse('definition' in body['mission'],'Native单位提示不得重复冻结初态定义')
                self.assertEqual(body['mission']['campaign_lifecycle']['phase_index'],2)
                self.assertEqual(body['mission']['campaign_lifecycle']['current_label'],s['war_state']['mission']['definition']['campaign_lifecycle']['phases'][2]['label'])
                self.assertEqual(body['mission']['campaign_lifecycle']['read_tool'],'get_campaign_lifecycle')
                self.assertIn('get_campaign_objectives',harness_engine.role_policy('engine',tools=True,external=engine=='afsim')['allowed_tools'])
                self.assertEqual(context['session']['war_state']['mission']['definition'],s['war_state']['mission']['definition'])
                self.assertLess(len(json.dumps(body['mission'])),len(json.dumps(s['war_state']['mission']))/2)
                self.assertEqual(s,before)


if __name__=='__main__':unittest.main(verbosity=2)
