"""Complete Native unit indexes keep exact authority accessible through existing tools."""
import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend import afsim_state, harness_engine as h, unit_planning
from gentactix import commands
from tools.qa.turn_preview_page_fixture import session as full22


class UnitSituationIndexTests(unittest.TestCase):
    def setUp(self):
        self.session=full22()
        self.session['command_state']=commands.replace_queue(self.session,[],control_team='red',director=True,no_fire=False,intent='完整身份索引QA')
        self.view=commands.view(self.session)
        self.uid=self.view['units'][0]['id']
        self.session['command_state']['unit_agents']=[self.uid]

    def packet(self,session=None):
        session=self.session if session is None else session
        prepared=commands.prepare(session);observer=h.RunObserver('unit input index QA');prompts=[]
        def native(binding,prompt,observer,**kwargs):
            prompts.append(prompt)
            run=SimpleNamespace(session_id='qa-index-unit',finish_reason='completed',events=[],
                final_response=json.dumps(dict(order=dict(action='hold',duration='next'),rationale='QA'),ensure_ascii=False))
            observer.record_result(run)
            return run,dict(session_id='qa-index-unit',factory='DSH.AgentRegistry',persistence='session_journal')
        with patch.object(h,'unit_run',side_effect=native):
            unit_planning.plan(session,prepared,observer,briefing='保留本轮检索规则',instruction='保留人工软意图')
        self.assertEqual(len(prompts),1)
        # Prompt ends with one authoritative JSON packet; prose examples precede it.
        return json.loads(prompts[0].split('\n')[-1]),prompts[0]

    def test_all22_exact_ids_positions_and_current_counts_survive_without_roster_details(self):
        saved=copy.deepcopy(self.session);packet,prompt=self.packet()
        index=packet['known_units'];original=self.view['units']
        self.assertEqual(len(index),22)
        self.assertEqual({r['id'] for r in index},{r['id'] for r in original})
        for row,prior in zip(index,original):
            for key in ('id','team','name','type','position','available','attack_range','personnel_strength_pct'):
                self.assertEqual(row.get(key),prior.get(key))
            self.assertEqual(row['personnel_current'],prior['personnel']['current'])
            self.assertEqual(row['detail_query'],dict(ids=[row['id']],limit=1,detail=True))
            self.assertTrue(row['in_world'])
            for key in ('equipment','formation','capabilities','source','last_decision'):
                self.assertNotIn(key,row)
        self.assertEqual(packet['known_units_view']['version'],'unit-situation-index-1')
        self.assertTrue(packet['known_units_view']['complete_registered_index'])
        self.assertEqual(packet['observation_version'],commands.world_version(self.session))
        self.assertEqual(self.session,saved)

    def test_self_constraints_intent_and_briefing_remain_exact(self):
        packet,prompt=self.packet()
        self.assertEqual(packet['unit'],self.view['units'][0])
        self.assertEqual(packet['intent'],'完整身份索引QA')
        self.assertEqual(packet['round_instruction'],'保留人工软意图')
        self.assertEqual(packet['rule_briefing'],'保留本轮检索规则')
        self.assertEqual(packet['mission'],afsim_state.mission_context(self.session['war_state']))
        self.assertTrue('get_afsim_observation' in prompt)
        self.assertTrue('不代表0' in prompt)

    def test_afsim_also_lists_all22_instead_of_only_the_initial_eight(self):
        self.session['execution_backend']='afsim'
        packet,_=self.packet()
        self.assertEqual({r['id'] for r in packet['known_units']},{r['id'] for r in self.view['units']})
        expected=afsim_state.observation(self.session,dict(ids=[self.uid],detail=True))['units'][0]
        for key in expected:self.assertEqual(packet['unit'][key],expected[key])
        self.assertEqual(packet['unit']['capabilities']['actions'],expected['actions'])
        self.assertEqual(packet['unit']['capabilities']['move_km'],expected['move_km'])

    def test_unknown_disabled_and_retired_are_not_conflated_or_filled_with_zero(self):
        rows=[dict(id='unknown',team='red',name='无坐标参考',available=True,position=None,personnel=None),
              dict(id='disabled',team='blue',name='失能实体',available=False,position=dict(lat=1,lng=2),personnel=dict(current=0)),
              dict(id='retired',team='blue',name='退役参考',available=False,position=None)]
        original=copy.deepcopy(rows)
        index=unit_planning.situation_index(rows,{'unknown','disabled'})
        self.assertIsNone(index[0]['personnel_current']);self.assertIsNone(index[0]['position'])
        self.assertEqual(index[1]['personnel_current'],0)
        self.assertTrue(index[1]['in_world']);self.assertIsNotNone(index[1]['detail_query'])
        self.assertFalse(index[2]['in_world']);self.assertIsNone(index[2]['detail_query'])
        index[1]['position']['lat']=9
        self.assertEqual(rows,original)

    def test_no_fixed_roster_limit_and_no_name_based_deduplication(self):
        rows=[dict(id=str(i),team='red' if i%2 else 'blue',name='同名',available=True,position=None) for i in range(79)]
        index=unit_planning.situation_index(rows,{r['id'] for r in rows})
        self.assertEqual([r['id'] for r in index],[r['id'] for r in rows])
        self.assertEqual(len(index),79)

    def test_real79_leaf_wuhan_fixture_keeps_every_current_identity_and_world(self):
        from tools.qa.large_formation_fixture import inputs
        from gentactix import historical_operations
        source,parameters=inputs()
        session=dict(id='native-index79-qa',turn_count=0,role_epoch=0,product_mode='historical',
            simulation_mode='open',agent_mode='native',execution_backend='narrative',time_step='30分钟',
            war_state=historical_operations.initial(source,parameters))
        session['command_state']=commands.replace_queue(session,[],control_team='red',director=True,no_fire=False,intent='79真实身份及QA数值')
        view=commands.view(session)
        session['command_state']['unit_agents']=[view['units'][-1]['id']]
        saved=copy.deepcopy(session)
        packet,_=self.packet(session)
        self.assertEqual(len(packet['known_units']),79)
        self.assertEqual({r['id'] for r in packet['known_units']},{r['id'] for r in view['units']})
        self.assertEqual(packet['unit'],view['units'][-1])
        self.assertEqual(session,saved)

    def test_tail_details_use_the_same_public_native_dispatch_without_state_writes(self):
        from backend.main import _native_tool_dispatch
        from backend.unit_order_submission import context
        from gentactix import missions
        packet,_=self.packet();saved=copy.deepcopy(self.session)
        target=packet['known_units'][-1];prepared=commands.prepare(self.session)
        ctx=context(self.session,prepared,self.uid,operation_id='readonly-tail-index-qa')
        reply=_native_tool_dispatch(ctx,dict(tool='get_afsim_observation',args=target['detail_query']))
        self.assertTrue(reply['ok']);self.assertEqual(len(reply['units']),1)
        actual=reply['units'][0]
        self.assertEqual(actual['id'],target['id'])
        prior=next(u for _,u in missions.units(self.session['war_state']) if u['name']==target['name'])
        self.assertEqual(actual['equipment'],prior['equipment'])
        self.assertEqual(actual['personnel'],prior['personnel'])
        self.assertEqual(self.session,saved)
        for external in (False,True):
            policy=h.role_policy('engine',tools=True,unit=True,external=external)
            self.assertIn('get_afsim_observation',policy['allowed_tools'])
            self.assertNotIn('get_turn_preview',policy['allowed_tools'])

    def test_legacy_staging_remains_explicit_without_a_participation_module(self):
        from datetime import datetime,timedelta
        from tools.qa.large_formation_fixture import inputs
        from gentactix import historical_operations,unit_participation
        source,parameters=inputs();parameters.pop('campaign_plan',None)
        identity=next(iter(parameters['actors']))
        parameters['campaign']['arrivals'][identity]['not_before']=(
            datetime.fromisoformat(parameters['clock']['start'])+timedelta(hours=1)).isoformat()
        session=dict(id='legacy-staging-index-qa',turn_count=0,role_epoch=0,execution_backend='narrative',
            simulation_mode='open',time_step='30分钟',war_state=historical_operations.initial(source,parameters))
        self.assertFalse(unit_participation.supported(session['war_state']))
        unit=next(u for u in commands.view(session)['units'] if u['capabilities'].get('arrival',{}).get('status')=='staging')
        self.assertTrue(unit['available'])  # Alive does not mean released into combat.
        original=copy.deepcopy(unit)
        row=unit_planning.situation_index([unit],{unit['id']})[0]
        self.assertEqual(row['arrival'],unit['capabilities']['arrival'])
        self.assertEqual(row['arrival']['status'],'staging')
        row['arrival']['status']='active'
        self.assertEqual(unit,original)

    def test_full22_serialized_index_materially_reduces_repeated_data(self):
        packet,_=self.packet()
        size=lambda v:len(json.dumps(v,ensure_ascii=False))
        self.assertLess(size(packet['known_units']),size(self.view['units'])*.35)
        self.assertEqual(len(packet['known_units']),len(self.view['units']))


if __name__=='__main__':unittest.main()
