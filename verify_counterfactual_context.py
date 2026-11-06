"""Decision-before tool visibility; fixtures never certify real model effects."""
import copy
import unittest
from unittest.mock import patch

from backend import agent_tools, dsh_simulation, turn_preview
from gentactix import commands, force_organization, missions


def fixture():
    world = missions.initial('AJ15-local-v1')
    session = dict(id='c0ffee000001', role_epoch=0, turn_count=4, war_state=copy.deepcopy(world),
        time_step='30分钟', agent_mode='native', execution_backend='narrative',
        product_mode='historical', simulation_mode='open', use_rag=False,
        mission_id=world['mission']['id'], scenario_input='测试反事实资料边界')
    records = [dict(id=f'c0ffee000001:e0:t{turn}', epoch=0, turn=turn,
        before=copy.deepcopy(world), after=copy.deepcopy(world), time_step='30分钟',
        report='PAST_ALLOWED' if turn < 2 else 'FUTURE_FORBIDDEN', changes=[], decisions=[],
        runs=[], tool_executions=[], geometry_enabled=False, clock={'status':'verified'})
        for turn in range(5)]
    session.update(trajectory=records, history=[r['report'] for r in records])
    cs = commands.state(session)
    cs.update(intent='FUTURE_INTENT', unit_agents=['future-agent'], task_plans={'future-task':{'label':'FUTURE_TASK'}})
    session['command_state'] = cs
    session['force_organization'] = dict(version=force_organization.VERSION, revision=9, groups=[],
        events=[{'message':'FUTURE_ORGANIZATION_EVENT'}])
    record = records[2]
    record['force_organization'] = dict(version=force_organization.VERSION, revision=1, groups=[])
    record['force_task_plans'] = {'past-task':{'label':'PAST_TASK'}}
    record['command_context'] = {'policies':{'revision':1,'control_team':'red','director':True,
        'no_fire':False,'intent':'PAST_INTENT'}}
    return session, record


class CounterfactualContextTests(unittest.TestCase):
    def exercise(self, inspect, *, first=False, old_epoch=False, missing_organization=False):
        session, record = fixture()
        if first:
            record = session['trajectory'][1]
        if missing_organization:
            record.pop('force_organization',None)
        if old_epoch:
            other = copy.deepcopy(session['trajectory'][1]);other.update(epoch=-1,report='OTHER_EPOCH')
            session['trajectory'].insert(0,other)
        original = copy.deepcopy(session)
        observed = {}
        def advance(branch, prepared, observer, **kwargs):
            observed.update(branch=branch, kwargs=kwargs)
            context = turn_preview.context(branch,None,fixed_orders=kwargs['fixed_orders'],operation_id='cf-qa')
            inspect(context['session'], observed)
            return {'updated_state':copy.deepcopy(record['before'])}, [], ''
        observer = type('Observer',(),{'runs':[]})()
        with patch.object(dsh_simulation,'advance',side_effect=advance):
            result = dsh_simulation.compare(session,record,[],observer)
        self.assertEqual(session,original,'A read-only intervention must not modify the live session')
        return result, observed

    def test_selected_and_future_reports_are_not_retrievable(self):
        def inspect(session, observed):
            response = agent_tools.exec_retrieve_history(session,{'query':'FUTURE_FORBIDDEN'})
            self.assertEqual(response['history_hits'],[])
        self.exercise(inspect)

    def test_selected_and_future_trajectory_are_not_tool_visible(self):
        def inspect(session, observed):
            for turn in (2,3,4):
                response = agent_tools.execute_tool_call(session,session['war_state'],
                    {'tool':'inspect_trajectory','args':{'turn':turn}})
                self.assertFalse(response['ok'],f'T{turn} is not known before T2')
        self.exercise(inspect)

    def test_prior_reports_and_trace_remain_readable(self):
        def inspect(session, observed):
            self.assertTrue(agent_tools.exec_retrieve_history(session,{'query':'PAST_ALLOWED'})['history_hits'])
            response=agent_tools.execute_tool_call(session,session['war_state'],
                {'tool':'inspect_trajectory','args':{'turn':1}})
            self.assertTrue(response['ok'])
            self.assertEqual([r['turn']for r in session['trajectory']],[0,1])
        self.exercise(inspect)

    def test_current_queue_agents_and_intent_do_not_leak_into_past(self):
        def inspect(session, observed):
            cs=commands.state(session)
            self.assertEqual(cs['intent'],'PAST_INTENT')
            self.assertEqual(cs['orders'],[])
            self.assertEqual(cs['unit_agents'],[])
            self.assertNotIn('future-task',cs.get('task_plans',{}))
        self.exercise(inspect)

    def test_organization_and_task_plans_come_from_selected_trace(self):
        def inspect(session, observed):
            self.assertEqual(force_organization.state(session)['revision'],1)
            self.assertNotIn('FUTURE_ORGANIZATION_EVENT',str(force_organization.state(session)))
            self.assertEqual(commands.state(session).get('task_plans'),{'past-task':{'label':'PAST_TASK'}})
        self.exercise(inspect)

    def test_missing_historical_organization_never_falls_back_to_current(self):
        def inspect(session, observed):
            self.assertNotEqual(force_organization.state(session)['revision'],9)
        self.exercise(inspect,missing_organization=True)

    def test_first_turn_keeps_only_initial_record(self):
        def inspect(session, observed):
            self.assertEqual(session['turn_count'],0)
            self.assertEqual([r['turn']for r in session['trajectory']],[0])
        self.exercise(inspect,first=True)

    def test_other_epoch_records_are_not_a_decision_prefix(self):
        def inspect(session, observed):
            self.assertTrue(all(r.get('epoch',0)==0 for r in session['trajectory']))
            self.assertNotIn('OTHER_EPOCH',str(session['history']))
        self.exercise(inspect,old_epoch=True)

    def test_tool_context_mutation_cannot_modify_source_history_or_organization(self):
        def inspect(session, observed):
            session['trajectory'][0]['report']='MUTATED'
            session['history'].append('MUTATED')
            session['force_organization']['groups'].append({'id':'MUTATED'})
            session['command_state']['intent']='MUTATED'
        self.exercise(inspect)


if __name__=='__main__':
    unittest.main(verbosity=2)
