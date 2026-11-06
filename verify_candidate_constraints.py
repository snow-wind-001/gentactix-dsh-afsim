"""Batch exact read-only calculation facts; model edits and full guards stay mandatory."""
import copy
import json
import unittest
from unittest.mock import patch

from backend import dsh_simulation,turn_preview as p
from gentactix import missions,movement_feedback as mf,resource_accounts as ra
from tools.qa.turn_preview_page_fixture import session,candidate


class CandidateConstraintTests(unittest.TestCase):
    def setUp(self):
        self.s=session();self.ctx=p.context(self.s,None,operation_id='constraints-qa')
        self.good=candidate(self.s['war_state'])

    def rejected(self,value):
        return p.execute(self.ctx,dict(tool=p.TOOL,args=dict(candidate=value)))

    def facts(self,value):
        from backend import effect_constraints
        return effect_constraints.diagnose(self.ctx,value)

    def by_path(self,facts):
        return {x['path']:x for x in facts['mismatches']}

    def test_one_failed_preview_reports_all_units_food_and_fatigue_without_changes(self):
        value=copy.deepcopy(self.good)
        for row in value['unit_updates']:
            row['logistics']['food']+=1;row['formation']['fatigue']=99
        saved=copy.deepcopy((self.ctx,value));reply=self.rejected(value)
        self.assertFalse(reply['ok']);self.assertNotIn('digest',reply)
        facts=reply['calculation_diagnostics'];paths=self.by_path(facts)
        self.assertEqual(facts['candidate_hash'],reply['candidate_hash'])
        self.assertEqual(facts['before_hash'],reply['before_hash'])
        self.assertEqual(facts['operation_id'],'constraints-qa')
        self.assertTrue(facts['readonly']);self.assertFalse(facts['complete_validation'])
        for i,row in enumerate(self.good['unit_updates']):
            self.assertEqual(paths[f'/unit_updates/{i}/logistics/food']['expected'],row['logistics']['food'])
            self.assertEqual(paths[f'/unit_updates/{i}/formation/fatigue']['expected'],row['formation']['fatigue'])
        self.assertEqual((self.ctx,value),saved)

    def test_good_candidate_keeps_success_and_has_no_diagnostic_payload(self):
        with patch.object(dsh_simulation,'apply',wraps=dsh_simulation.apply) as apply:
            reply=self.rejected(self.good)
        self.assertTrue(reply['ok'],reply);self.assertEqual(apply.call_count,1)
        self.assertNotIn('calculation_diagnostics',reply)

    def test_diagnostic_does_not_apply_world_or_author_amendments(self):
        with patch.object(dsh_simulation,'apply',side_effect=AssertionError('No executor')):
            value=self.facts(self.good)
        self.assertEqual(value['mismatches'],[])
        for field in ('edits','candidate','unit_updates','after','digest'):self.assertNotIn(field,value)

    def test_food_spent_and_closing_stock_share_the_same_reference_functions(self):
        from backend import effect_constraints
        world=self.s['war_state'];value=copy.deepcopy(self.good)
        value['resource_ledger']['units'][0]['food_spent']=0
        value['unit_updates'][0]['logistics']['food']+=3
        with patch.object(ra,'required_food',wraps=ra.required_food) as demand,patch.object(ra,'closing_stock',wraps=ra.closing_stock) as balance:
            facts=effect_constraints.diagnose(self.ctx,value)
        paths=self.by_path(facts)
        self.assertEqual(paths['/resource_ledger/units/0/food_spent']['expected'],self.good['resource_ledger']['units'][0]['food_spent'])
        self.assertEqual(paths['/unit_updates/0/logistics/food']['expected'],self.good['unit_updates'][0]['logistics']['food'])
        self.assertEqual(demand.call_count,22);self.assertGreaterEqual(balance.call_count,44)

    def test_reordered_updates_and_ledgers_use_actual_json_paths(self):
        value=copy.deepcopy(self.good);value['unit_updates'].reverse();value['resource_ledger']['units'].reverse()
        value['unit_updates'][0]['logistics']['ammo']-=1
        item=self.by_path(self.facts(value))['/unit_updates/0/logistics/ammo']
        self.assertEqual(item['unit'],value['unit_updates'][0]['unit'])
        self.assertEqual(item['expected'],self.s['war_state']['blue_units'][-1]['logistics']['ammo'])

    def test_malformed_numbers_and_missing_rows_are_unavailable_not_guessed(self):
        value=copy.deepcopy(self.good);value['resource_ledger']['units'][0]['delivery']=True
        facts=self.facts(value)
        self.assertNotIn('/unit_updates/0/logistics/food',self.by_path(facts))
        self.assertTrue(facts['unavailable'])
        value=copy.deepcopy(self.good);value['unit_updates'][1]['unit']=value['unit_updates'][0]['unit']
        facts=self.facts(value);self.assertTrue(facts['unavailable'])
        self.assertFalse(any(x['path'].startswith('/unit_updates/0/') for x in facts['mismatches']))

    def test_formation_integer_contract_reports_all_fractional_fields_without_coercion(self):
        value=copy.deepcopy(self.good)
        value['unit_updates'][0]['formation'].update(fatigue=1.5,suppression=2.5)
        reply=self.rejected(value);self.assertFalse(reply['ok'])
        paths={x['path'] for x in reply['issues']}
        self.assertIn('/unit_updates/0/formation/fatigue',paths)
        self.assertIn('/unit_updates/0/formation/suppression',paths)
        self.assertIs(type(value['unit_updates'][0]['formation']['fatigue']),float)

    def test_expected_fatigue_uses_actual_ground_distance_and_no_rounding_of_candidate(self):
        from verify_movement_feedback import world,moving,session as motion_session
        w=world();s=motion_session(w);s['agent_mode']='native'
        ctx=p.context(s,None,operation_id='move-qa');value=moving(w,.1)
        value['unit_updates'][0]['formation']['fatigue']=99
        from backend import effect_constraints
        paths=self.by_path(effect_constraints.diagnose(ctx,value));u=w['red_units'][0]
        point=value['unit_updates'][0]
        expected=mf.fatigue_value(w,u,'move',mf.travel(w,u,point,value['orders'][0])['ground_km'],following=u)
        self.assertEqual(paths['/unit_updates/0/formation/fatigue']['expected'],expected)
        self.assertEqual(value['unit_updates'][0]['formation']['fatigue'],99)

    def test_locked_move_position_is_reported_before_conditional_fatigue(self):
        from verify_movement_feedback import world,moving,session as motion_session
        w=world();s=motion_session(w);s['agent_mode']='native'
        value=moving(w,.1);value['unit_updates'][0]['lat']=w['red_units'][0]['lat']
        ctx=p.context(s,None,fixed_orders=value['orders'],operation_id='position-qa')
        from backend import effect_constraints
        facts=effect_constraints.diagnose(ctx,value);paths=self.by_path(facts)
        self.assertEqual(paths['/unit_updates/0/lat']['expected'],value['orders'][0]['lat'])
        self.assertNotIn('/unit_updates/0/formation/fatigue',paths)
        self.assertTrue(any(x.get('unit')==w['red_units'][0]['name'] for x in facts['unavailable']))

    def test_scheduled_supply_missing_receipt_never_falls_back_to_legacy_cost(self):
        from verify_supply_schedule import world,model_proposal
        w=world();s={**self.s,'war_state':w,'time_step':'6小时'};ctx=p.context(s,None,operation_id='scheduled-qa')
        value=model_proposal(w);del value['supply_schedule_ledger']
        from backend import effect_constraints
        facts=effect_constraints.diagnose(ctx,value)
        self.assertTrue(facts['unavailable'])
        self.assertFalse(any(x['path'].endswith('/food_spent') for x in facts['mismatches']))

    def test_scheduled_supply_uses_existing_time_receipt_instead_of_legacy_amount(self):
        from verify_supply_schedule import world,model_proposal
        w=world();s={**self.s,'war_state':w,'time_step':'6小时'};ctx=p.context(s,None,operation_id='scheduled-qa')
        value=model_proposal(w);value['resource_ledger']['units'][0]['food_spent']=2
        from backend import effect_constraints
        paths=self.by_path(effect_constraints.diagnose(ctx,value))
        self.assertEqual(paths['/resource_ledger/units/0/food_spent']['expected'],20)

    def test_disabled_operation_and_nonobject_arguments_do_not_expose_facts(self):
        ctx=copy.deepcopy(self.ctx);ctx['session']['execution_backend']='afsim'
        for context,args in [(ctx,dict(candidate=self.good)),(self.ctx,dict(candidate=json.dumps(self.good)))]:
            reply=p.execute(context,dict(tool=p.TOOL,args=args));self.assertFalse(reply['ok'])
            self.assertNotIn('calculation_diagnostics',reply)

    def test_explicit_model_edits_still_need_complete_validation_and_match_full_candidate(self):
        from backend import effect_amendments as a
        bad=copy.deepcopy(self.good)
        for row in bad['unit_updates']:
            row['logistics']['food']+=1;row['formation']['fatigue']=99
        first=self.rejected(bad)
        events=[dict(type='tool/call',seq=1,data=dict(name=p.TOOL,callId='first',arguments=dict(candidate=bad))),
            dict(type='tool/result',seq=2,data=dict(message=dict(toolCallId='first',content=[dict(type='text',text=json.dumps(first))])))]
        edits=[dict(op='replace',path=f'/unit_updates/{i}/{field}/{key}',value=row[field][key])
            for i,row in enumerate(self.good['unit_updates']) for field,key in [('logistics','food'),('formation','fatigue')]]
        reply=p.amend(self.ctx,dict(tool=a.AMEND_TOOL,args=dict(base_ref=first['candidate_ref'],edits=edits),
            session_id='qa-native',candidate_events=events))
        self.assertTrue(reply['ok'],reply)
        self.assertEqual(reply['after_hash'],self.rejected(self.good)['after_hash'])
        self.assertFalse(self.rejected(bad)['ok'])

    def test_failed_amendment_diagnostics_bind_the_new_candidate_not_the_original(self):
        from backend import effect_amendments as a
        bad=copy.deepcopy(self.good);bad['unit_updates'][0]['logistics']['food']+=1
        first=self.rejected(bad)
        events=[dict(type='tool/call',seq=1,data=dict(name=p.TOOL,callId='first',arguments=dict(candidate=bad))),
            dict(type='tool/result',seq=2,data=dict(message=dict(toolCallId='first',content=[dict(type='text',text=json.dumps(first))])))]
        reply=p.amend(self.ctx,dict(tool=a.AMEND_TOOL,args=dict(base_ref=first['candidate_ref'],
            edits=[dict(op='replace',path='/unit_updates/1/formation/fatigue',value=99)]),
            session_id='qa-native',candidate_events=events))
        self.assertFalse(reply['ok']);self.assertNotEqual(reply['candidate_hash'],first['candidate_hash'])
        self.assertEqual(reply['calculation_diagnostics']['candidate_hash'],reply['candidate_hash'])
        self.assertIn('/unit_updates/1/formation/fatigue',self.by_path(reply['calculation_diagnostics']))


if __name__=='__main__':unittest.main()
