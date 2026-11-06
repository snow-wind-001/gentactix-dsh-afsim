"""Formal reorganization preserves deferred NC load without zero-time losses."""
import copy
import json
import math
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from gentactix import formation_conversion as fc, historical_operations as ho, missions, support_dynamics as sd
from tools.qa.converted_phases_live import parameters

POLICY='deferred-support-exposure-1'


class DeferredSupportTests(unittest.TestCase):
    def setUp(self):
        self.source,self.parameters=parameters(personnel_rations=True)
        self.world=ho.initial(self.source,self.parameters)
        self.root=next(u for u in self.world['red_units'] if u['historical_unit_id']=='ww2.cn.division159')
        proposal=fc.split_current(self.root,[dict(id='a',label='left',committed=5000),dict(id='b',label='right',committed=5000)],
            assumption='Explicit T0 software boundary fixture, not observed/historical injury',operation_id='a'*32,product_mode='synthetic')
        self.parts=proposal['after']
        for u in self.parts:u['sustainment']['noncombat_remainder']=.6
        self.cfg=sd.configuration(self.world)

    def merge(self):
        return fc.merge_current(self.parts,assumption='QA existing fractional load',operation_id='b'*32)

    @staticmethod
    def estimated_step(session):
        """Offline response fixture through the real admission chain, not LLM evidence."""
        from backend import dsh_simulation,session_store
        from gentactix import commands,formation_parts,sim_clock
        from verify_campaign_plan_backends import proposal
        world=session['war_state'];value=proposal(world);cfg=sd.configuration(world)
        prepared=commands.prepare(session);seconds=sim_clock.duration_seconds(session['time_step'])
        value['sustainment_ledger']={'version':cfg['version'],'units':[]}
        old={u['name']:u for _,u in missions.units(world)}
        accounts={r['unit']:r for r in value['resource_ledger']['units']}
        for update in value['unit_updates']:
            u=old[update['unit']];q=sd.expected(cfg,u,'hold',seconds)
            update['logistics']['food']=u['logistics']['food']-q['consumed']/formation_parts.scale(u)
            update['formation']['fatigue']=max(u['formation']['fatigue'],math.floor(q['fatigue_floor']))
            update['sustainment']={'version':cfg['version'],**{k:q[k] for k in ('shortage_hours','noncombat_remainder')}}
            update['personnel']={'current':u['personnel']['current']-q['noncombat_delta'],
                'noncombat_losses':u['personnel']['noncombat_losses']+q['noncombat_delta']}
            accounts[u['name']]['food_spent']=q['consumed']
            value['sustainment_ledger']['units'].append({'unit':u['name'],**q})
        with patch.object(missions,'advance',side_effect=AssertionError('No host physical executor')):
            after=dsh_simulation.apply(world,value,session['time_step'])
        cs,_=commands.finish(session,prepared,after,executed=value['orders'])
        session.update(last_war_state=copy.deepcopy(world),war_state=after,command_state=cs,turn_count=session['turn_count']+1)
        session_store.validate(session)

    def test_merge_crosses_integer_without_creating_personnel_loss_or_food(self):
        before=copy.deepcopy(self.parts);p=self.merge();u=p['after'][0]
        self.assertEqual(u['sustainment']['noncombat_remainder'],1.2)
        self.assertEqual(u['runtime_allocation']['support_remainder_policy'],POLICY)
        self.assertEqual(p['totals_before'],p['totals_after'])
        self.assertEqual(u['personnel']['current'],10000)
        self.assertEqual(u['personnel']['noncombat_losses'],0)
        self.assertEqual(self.parts,before)
        self.assertTrue(fc.verify_proposal(p))

    def test_full_food_and_no_new_exposure_preserve_pending_integer(self):
        u=self.merge()['after'][0];before=copy.deepcopy(u)
        r=sd.expected(self.cfg,u,'hold',3600)
        self.assertEqual(r['noncombat_delta'],0)
        self.assertEqual(r['noncombat_remainder'],1.2)
        self.assertEqual(u,before)

    def test_new_effective_exposure_settles_existing_and_new_load_once(self):
        u=self.merge()['after'][0];u['logistics']['food']=0;u['sustainment']['shortage_hours']=49
        cfg={**self.cfg,'incapacity_fraction_per_hour':.00024}
        r=sd.expected(cfg,u,'hold',3600)
        self.assertEqual(r['noncombat_delta'],3)
        self.assertAlmostEqual(r['noncombat_remainder'],.6)
        u['personnel']['current']-=3;u['personnel']['noncombat_losses']+=3
        u['sustainment'].update(shortage_hours=r['shortage_hours'],noncombat_remainder=r['noncombat_remainder'])
        same=sd.expected(cfg,u,'hold',0)
        self.assertEqual(same['noncombat_delta'],0)
        self.assertAlmostEqual(same['noncombat_remainder'],.6)

    def test_zero_time_and_initial_load_probe_do_not_consume_deferred_load(self):
        u=self.merge()['after'][0];u['logistics']['food']=0;u['sustainment']['shortage_hours']=49
        for seconds in (0,.001):
            with self.subTest(seconds=seconds):
                r=sd.expected(self.cfg,u,'hold',seconds)
                self.assertEqual(r['noncombat_delta'],0)
                self.assertEqual(r['noncombat_remainder'],1.2)
                self.assertEqual(r['demand'],0)

    def test_fully_incapacitated_formation_does_not_invent_another_person(self):
        u=self.merge()['after'][0];u['personnel'].update(current=0,noncombat_losses=10000)
        r=sd.expected(self.cfg,u,'hold',3600)
        self.assertEqual(r['noncombat_delta'],0)
        self.assertEqual(r['noncombat_remainder'],1.2)

    def test_resplitting_preserves_marker_and_exact_total_load(self):
        u=self.merge()['after'][0]
        p=fc.split_current(u,[dict(id='c',label='C',committed=6000),dict(id='d',label='D',committed=4000)],
            assumption='QA resplit before physical exposure',operation_id='c'*32,product_mode='synthetic')
        self.assertEqual([v['sustainment']['noncombat_remainder'] for v in p['after']],[.72,.48])
        self.assertTrue(all(v['runtime_allocation']['support_remainder_policy']==POLICY for v in p['after']))
        self.assertEqual(p['totals_before'],p['totals_after'])

    def test_ordinary_unregistered_or_unknown_policy_integer_remains_invalid(self):
        for marker in (None,'invented-policy'):
            u=copy.deepcopy(self.parts[0]);u['sustainment']['noncombat_remainder']=1.2
            if marker:u['runtime_allocation']['support_remainder_policy']=marker
            with self.subTest(marker=marker),self.assertRaises(ValueError):fc._check(u)

    def test_registered_load_cannot_exceed_its_committed_personnel(self):
        u=self.merge()['after'][0];u['sustainment']['noncombat_remainder']=10000
        with self.assertRaises(ValueError):fc._check(u)

    def test_registered_policy_still_rejects_nonfinite_boolean_and_negative_load(self):
        for amount in (-1,float('inf'),float('nan'),True):
            u=self.merge()['after'][0];u['sustainment']['noncombat_remainder']=amount
            with self.subTest(amount=amount),self.assertRaises(ValueError):fc._check(u)

    def test_existing_time_rate_version_uses_same_exposure_trigger(self):
        from verify_support_dynamics import config
        source,p=parameters(personnel_rations=False);cfg=config();p['support_dynamics']=cfg
        world=ho.initial(source,p);root=next(u for u in world['red_units'] if u['historical_unit_id']=='ww2.cn.division159')
        parts=fc.split_current(root,[dict(id='a',label='A',committed=5000),dict(id='b',label='B',committed=5000)],
            assumption='Legacy time-rate QA boundary',operation_id='d'*32,product_mode='synthetic')['after']
        for u in parts:u['sustainment']['noncombat_remainder']=.6
        u=fc.merge_current(parts,assumption='Legacy time support merge',operation_id='e'*32)['after'][0]
        self.assertEqual(u['sustainment']['version'],'time-sustainment-1')
        self.assertEqual(sd.expected(cfg,u,'hold',1800)['noncombat_delta'],0)
        u['logistics']['food']=0;u['sustainment']['shortage_hours']=49
        q=sd.expected({**cfg,'incapacity_fraction_per_hour':.00024},u,'hold',3600)
        self.assertEqual(q['noncombat_delta'],3);self.assertAlmostEqual(q['noncombat_remainder'],.6)

    def test_legacy_small_debt_proposal_keeps_its_existing_policy_and_shape(self):
        self.parts[0]['sustainment']['noncombat_remainder']=.1;self.parts[1]['sustainment']['noncombat_remainder']=.2
        p=self.merge();u=p['after'][0]
        self.assertNotIn('support_remainder_policy',u['runtime_allocation'])
        self.assertEqual(p['policies']['fractions'],'份额分配、合并相加；达到整数的合并债在根账执行契约接入前拒绝')
        self.assertTrue(fc.verify_proposal(p))

    def test_formal_commit_checkpoint_and_idempotent_replay_keep_pending_load(self):
        with tempfile.TemporaryDirectory() as directory:
            values={}
            for key,suffix in [('SESSION_DIR','sessions'),('TRACE_DIR','traces'),('DSH_HOME','home'),('DSH_WORKSPACE','workspace'),('ROLE_INDEX','roles.json'),('LLM_CONFIG','llm.enc'),('VAULT_KEY_FILE','vault.key')]:
                values['GENTACTIX_'+key]=str(Path(directory)/suffix)
            with patch.dict(os.environ,values):
                from backend import session_store,formation_commit
                from gentactix import synthetic_history,commands,campaign_plan
                from verify_formation_commit import fixture
                from verify_converted_phases import conversion
                parameters=copy.deepcopy(self.parameters);parameters['support_dynamics']['incapacity_fraction_per_hour']=.00048
                binding=ho.initial(self.source,parameters)['mission']['definition']['historical_calculation']
                world=missions.from_definition(synthetic_history.definition(binding,synthetic_history.seed(binding)['configuration']))
                from verify_formation_continuity import selected
                selected(world)['sustainment']['shortage_hours']=49
                selected(world)['logistics']['food']=0
                campaign_plan.initialize(world)  # Explicit T0 debt, not a live casualty claim.
                session,root,_=fixture(world)
                _,split=conversion(session,[root]);children=split['command_map'][root]
                self.estimated_step(session)
                self.assertTrue(all(abs(commands.resolve_units(session)[i][1]['sustainment']['noncombat_remainder']-.6)<1e-9 for i in children))
                before_clock=copy.deepcopy(session['war_state']['simulation_clock'])
                request,result=conversion(session,children,'merge')
                merged=next(iter(result['command_map'].values()))[0]
                u=commands.resolve_units(session)[merged][1]
                self.assertEqual(u['sustainment']['noncombat_remainder'],1.2)
                self.assertEqual(session['war_state']['simulation_clock'],before_clock)
                session_store.save(session);before=session_store.serializable(session)
                loaded,errors=session_store.load_all();self.assertFalse(errors)
                self.assertEqual(json.dumps(session_store.serializable(loaded[session['id']]),sort_keys=True),json.dumps(before,sort_keys=True))
                replay=formation_commit.commit(session,request)
                self.assertTrue(replay['replayed'])
                self.assertEqual(session_store.serializable(session),before)
                self.estimated_step(session)
                u=commands.resolve_units(session)[merged][1]
                self.assertEqual(u['personnel']['noncombat_losses'],2)
                self.assertAlmostEqual(u['sustainment']['noncombat_remainder'],.4)


if __name__=='__main__':unittest.main()
