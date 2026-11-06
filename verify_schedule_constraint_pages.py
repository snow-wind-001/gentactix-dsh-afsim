"""Large timed ledgers page failed-candidate facts through existing Native evidence."""
import copy
import json
import unittest
from unittest.mock import patch

from backend import dsh_simulation, effect_amendments, effect_constraints, turn_preview
from verify_supply_schedule import world, model_proposal
from verify_schedule_constraints import context


class ScheduledConstraintPageTests(unittest.TestCase):
    def setUp(self):
        self.world=world();self.ctx=context(self.world)
        self.value=model_proposal(self.world)
        self.value['supply_schedule_ledger']['units'][0]['events'][0]['food_received']=5000
        self.reply=turn_preview.execute(self.ctx,dict(tool=turn_preview.TOOL,args={'candidate':self.value}))
        self.assertFalse(self.reply['ok'])
        self.events=self.pair(1,'first',turn_preview.TOOL,{'candidate':self.value},self.reply)

    def pair(self,seq,identity,tool,args,reply):
        return [dict(type='tool/call',seq=seq,data=dict(name=tool,callId=identity,arguments=args)),
                dict(type='tool/result',seq=seq+1,data=dict(message=dict(toolCallId=identity,
                    content=[dict(type='text',text=json.dumps(reply))])))]

    def query(self,args=None,*,ctx=None,events=None):
        return turn_preview.get_preview(ctx or self.ctx,dict(tool=turn_preview.READ_TOOL,
            session_id='qa-current-native',args=args or dict(kind='constraints',candidate_ref=self.reply['candidate_ref']),
            candidate_events=self.events if events is None else events))

    def test_failed_reply_is_bounded_and_links_the_same_candidate_reference(self):
        facts=self.reply['calculation_diagnostics']
        self.assertGreater(facts['constraint_count'],16)
        self.assertEqual(len(facts['constraints']),16)
        self.assertEqual(facts['constraints_next_args']['candidate_ref'],self.reply['candidate_ref'])
        self.assertEqual(facts['constraints_next_args']['kind'],'constraints')

    def test_all_pages_are_reconstructed_without_executor_or_state_cache(self):
        saved=copy.deepcopy((self.ctx,self.value,self.events));rows=[];args=None
        with patch.object(dsh_simulation,'apply',side_effect=AssertionError('No executor')):
            while True:
                result=self.query(args);self.assertTrue(result['ok'],result)
                self.assertTrue(result['readonly']);self.assertLessEqual(len(result['items']),16)
                rows.extend(result['items']);args=result['next_args']
                if args is None:break
        expected=effect_constraints.diagnose(self.ctx,self.value)['constraints']
        self.assertEqual(rows,expected)
        self.assertEqual((self.ctx,self.value,self.events),saved)

    def test_stale_operation_and_invalid_page_never_resolve_public_candidate(self):
        other=copy.deepcopy(self.ctx);other['turn_preview']['operation_id']='other-operation'
        self.assertFalse(self.query(ctx=other)['ok'])
        self.assertFalse(self.query(dict(kind='constraints',candidate_ref=self.reply['candidate_ref'],limit=17))['ok'])
        self.assertFalse(self.query(dict(kind='constraints',candidate_ref='0'*64))['ok'])

    def test_failed_and_successful_references_cannot_be_mixed_or_substituted(self):
        saved=copy.deepcopy(self.ctx)
        ref=self.reply['candidate_ref']
        invalid=[dict(kind='constraints',preview_hash=ref),
            dict(kind='constraints',candidate_ref=ref,preview_hash=ref),
            dict(kind='units',candidate_ref=ref),
            dict(kind='goals',candidate_ref=ref),dict(candidate_ref=ref),
            dict(kind='constraints',candidate_ref=ref,offset=True),
            dict(kind='constraints',candidate_ref=ref,limit=True)]
        for args in invalid:
            with self.subTest(args=args):
                self.assertFalse(self.query(args)['ok'])
        self.assertEqual(self.ctx,saved)
        self.assertTrue(self.query()['ok'],'rejections must not consume or invalidate the original public candidate')

    def test_full22_multi_period_window_keeps_all_constraints_accessible(self):
        from backend.scenario_builder import historical_basis
        from gentactix import historical_operations
        from tools.qa.turn_preview_page_fixture import candidate
        from verify_supply_schedule import config,schedule_ledger
        from verify_split_supply import config as split_config
        basis=historical_basis('抗日战争-万家岭战役-1938.09下旬至1938.10',force_scope='campaign',
            campaign_window_id='WJL-oct6-10',campaign_window_version='1.5.0',termination_mode='objectives',time_step='6小时')
        parameters=basis['configuration_template']
        parameters.update(supply_schedule=config(),supply_distribution=split_config())
        parameters['rules']['bridge_enabled']=False
        self.world=historical_operations.initial(basis['initial'],parameters)
        self.ctx=context(self.world);self.value=candidate(self.world)
        self.value['supply_schedule_ledger']=schedule_ledger(self.world,21600)
        self.value['supply_schedule_ledger']['units'][0]['events'][0]['food_received']=5000
        self.reply=turn_preview.execute(self.ctx,dict(tool=turn_preview.TOOL,args={'candidate':self.value}))
        self.assertFalse(self.reply['ok'])
        self.events=self.pair(1,'large',turn_preview.TOOL,{'candidate':self.value},self.reply)
        count=self.reply['calculation_diagnostics']['constraint_count']
        self.assertGreaterEqual(count,22*6)
        self.assertLessEqual(len(self.reply['calculation_diagnostics']['constraints']),16)
        rows=[];args=None
        while True:
            page=self.query(args);self.assertTrue(page['ok'],page)
            rows.extend(page['items']);args=page['next_args']
            if args is None:break
        self.assertEqual(len(rows),count)
        self.assertEqual(len({r['unit']for r in rows if r['kind']=='delivery_capacity'}),22)

    def test_failed_amendment_pages_bind_its_new_hash_and_quantity(self):
        args={'base_ref':self.reply['candidate_ref'],'edits':[dict(op='replace',
              path='/supply_schedule_ledger/units/0/events/0/food_received',value=4000)]}
        reply=turn_preview.amend(self.ctx,dict(tool=effect_amendments.AMEND_TOOL,args=args,
            session_id='qa-current-native',candidate_events=self.events))
        self.assertFalse(reply['ok']);self.assertNotEqual(reply['candidate_hash'],self.reply['candidate_hash'])
        events=self.events+self.pair(3,'amend',effect_amendments.AMEND_TOOL,args,reply)
        page=self.query(dict(kind='constraints',candidate_ref=reply['candidate_ref']),events=events)
        self.assertTrue(page['ok'],page);self.assertEqual(page['candidate_hash'],reply['candidate_hash'])
        capacity=next(row for row in page['items']if row['kind']=='delivery_capacity'and row['event_path'].endswith('/0/events/0'))
        self.assertEqual(capacity['actual_mass_tons'],500)


if __name__ == '__main__':unittest.main()
