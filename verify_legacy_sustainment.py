"""Legacy hunger limits and explicit fractional receipts, never casualty repair."""
import copy
import unittest
from unittest.mock import patch

from backend import dsh_simulation
from gentactix import historical_operations as ho,missions,formation_parts
from tools.qa.historical_operational_fixture import inputs
from verify_dsh_resources import model_result


def partitioned(parts=4,deadline=4,synthetic=False):
    if parts not in (1,4):raise ValueError('QA fixture supports whole or four disjoint parts')
    source,p=inputs();parent='ww2.cn.division31';u=p['actors'][parent]
    p['goal']['deadline_turn']=deadline;u['logistics']['food']=0
    for node in p['support'].values():
        node['stock']=0
        for key in node['inventory']:node['inventory'][key]=0
    if parts>1:
        p['partitions']=dict(version='formation-partitions-1',groups={parent:dict(assumption='QA互斥份额，非史实兵力',parts=[
            dict(id='p'+str(i),label='保障'+str(i),personnel=u['personnel']//parts,position=copy.deepcopy(u['position']),
                equipment={k:n//parts for k,n in u['equipment'].items()},resources={k:u['formation'][k]//parts for k in formation_parts.RESOURCES},
                dispersion_km2=u['formation']['dispersion_km2'],assumption='QA') for i in range(parts)])})
    w=ho.initial(source,p)
    if synthetic:
        from gentactix import synthetic_history
        binding=w['mission']['definition']['historical_calculation']
        w=missions.from_definition(synthetic_history.definition(binding,synthetic_history.seed(binding)['configuration']))
    return w


def proposal(world,*,remainder=None,loss=0):
    value=model_result(world);units={u['name']:u for _,u in missions.units(world)}
    for row in value['resource_ledger']['units']:row['food_spent']*=formation_parts.scale(units[row['unit']])
    if remainder is not None:
        value['sustainment_ledger']=dict(version='legacy-noncombat-1',units=[
            dict(unit=u['name'],noncombat_remainder=remainder) for _,u in missions.units(world) if formation_parts.is_fragment(u)])
    if loss:
        for row in value['unit_updates']:
            u=units[row['unit']]
            if not formation_parts.is_fragment(u):continue
            row['personnel']=dict(current=u['personnel']['current']-loss,
                casualties=u['personnel']['casualties'],noncombat_losses=u['personnel']['noncombat_losses']+loss)
    return value


class LegacySustainmentTests(unittest.TestCase):
    def apply(self,w,v):
        with patch.object(missions,'advance',side_effect=AssertionError('No Python battle executor')):
            return dsh_simulation.apply(w,v,'30分钟',require_fire_ledger=True)

    def test_ample_food_cannot_hide_239_losses_as_noncombat(self):
        w=ho.initial(*inputs());v=model_result(w);u=w['blue_units'][0]
        v['unit_updates'][1]['personnel']=dict(current=u['personnel']['current']-239,casualties=0,noncombat_losses=239)
        saved=copy.deepcopy((w,v))
        with self.assertRaisesRegex(ValueError,'非战斗'):self.apply(w,v)
        self.assertEqual((w,v),saved)

    def test_legacy_singleton_budget_is_two_per_turn_only_when_food_ends_at_zero(self):
        for loss in (0,2,3):
            w=ho.initial(*inputs());u=w['red_units'][0];u['logistics']['food']=0;v=model_result(w)
            v['unit_updates'][0]['personnel']=dict(current=u['personnel']['current']-loss,casualties=0,noncombat_losses=loss)
            if loss>2:
                with self.assertRaisesRegex(ValueError,'非战斗'):self.apply(w,v)
            else:self.assertEqual(self.apply(w,v)['red_units'][0]['personnel']['noncombat_losses'],loss)

    def test_quarter_parts_require_explicit_changed_remainder_and_keep_it_across_turns(self):
        w=partitioned();saved=copy.deepcopy(w)
        with self.assertRaisesRegex(ValueError,'余量|sustainment_ledger'):self.apply(w,proposal(w))
        self.assertEqual(w,saved)
        first=self.apply(w,proposal(w,remainder=.5))
        self.assertTrue(all(u['formation']['partition_noncombat_remainder']==.5 for u in first['red_units']))
        self.assertEqual(sum(u['personnel']['noncombat_losses'] for u in first['red_units']),0)
        second=self.apply(first,proposal(first,remainder=0,loss=1))
        self.assertEqual(sum(u['personnel']['noncombat_losses'] for u in second['red_units']),4)
        self.assertTrue(all(u['formation']['partition_noncombat_remainder']==0 for u in second['red_units']))
        self.assertNotIn('sustainment',second['red_units'][0])

    def test_wrong_duplicate_or_out_of_range_remainders_reject_without_mutation(self):
        for kind in ('wrong','duplicate','boolean','raw'):
            w=partitioned();v=proposal(w,remainder=.5);saved=copy.deepcopy(w)
            if kind=='wrong':v['sustainment_ledger']['units'][0]['noncombat_remainder']=.4
            if kind=='duplicate':v['sustainment_ledger']['units'].append(copy.deepcopy(v['sustainment_ledger']['units'][0]))
            if kind=='boolean':v['sustainment_ledger']['units'][0]['noncombat_remainder']=True
            if kind=='raw':v['unit_updates'][0].setdefault('formation',{})['partition_noncombat_remainder']=.5
            with self.subTest(kind=kind),self.assertRaises(ValueError):self.apply(w,v)
            self.assertEqual(w,saved)

    def test_fed_parts_keep_existing_remainder_without_spontaneous_losses_or_receipts(self):
        w=partitioned()
        for u in w['red_units']:u['logistics']['food']=10;u['formation']['partition_noncombat_remainder']=.5
        after=self.apply(w,proposal(w))
        self.assertTrue(all(u['formation']['partition_noncombat_remainder']==.5 for u in after['red_units']))
        self.assertTrue(all(u['personnel']['noncombat_losses']==0 for u in after['red_units']))

    def test_legacy_receipts_cannot_disguise_as_the_time_sustainment_model(self):
        w=partitioned();v=proposal(w,remainder=.5);v['sustainment_ledger']['version']='time-sustainment-1'
        with self.assertRaisesRegex(ValueError,'版本|旧模型'):self.apply(w,v)

    def test_wrong_legacy_field_feedback_names_actual_expected_and_fraction(self):
        w=partitioned();v=proposal(w,remainder=.5);row=v['sustainment_ledger']['units'][0]
        name=row['unit'];row['noncombat_losses']=row.pop('noncombat_remainder');saved=copy.deepcopy((w,v))
        with self.assertRaises(ValueError) as error:self.apply(w,v)
        message=str(error.exception)
        for required in (name,'noncombat_losses','noncombat_remainder','0.5'):
            self.assertIn(required,message)
        self.assertEqual((w,v),saved)

    def test_legacy_identity_feedback_distinguishes_missing_extra_and_duplicate(self):
        w=partitioned();v=proposal(w,remainder=.5);rows=v['sustainment_ledger']['units']
        missing=rows[0]['unit'];duplicate=rows[1]['unit'];rows[0]=copy.deepcopy(rows[1])
        rows.append(dict(unit='旧父级不存在',noncombat_remainder=.5));saved=copy.deepcopy((w,v))
        with self.assertRaises(ValueError) as error:self.apply(w,v)
        message=str(error.exception)
        for required in ('缺少',missing,'多余','旧父级不存在','重复',duplicate):
            self.assertIn(required,message)
        self.assertEqual((w,v),saved)

    def test_actual_engine_prompt_includes_legacy_receipt_schema_and_current_fraction(self):
        w=partitioned();message=dsh_simulation.prompt(w)
        self.assertIn('sustainment_ledger={"version":"legacy-noncombat-1"',message)
        self.assertIn('每行仅有unit和noncombat_remainder',message)
        self.assertIn('"per_turn_allowance": 0.5',message)
        self.assertIn('"prior_remainder": 0',message)
        self.assertNotIn('启用时间保障模型 time-sustainment-1',message)

    def test_thirds_cross_the_integer_boundary_without_losing_the_fraction(self):
        from gentactix import support_dynamics as sd
        unit=dict(personnel={'current':10},formation={'partition_noncombat_remainder':.333333333333},
            formation_part={'numerator':1,'denominator':3})
        self.assertEqual(sd.legacy_quote(unit,0),dict(maximum=1,remainder=0,starved=True))

    def test_readonly_receipt_keeps_actual_loss_remainder_and_upper_bound_distinct(self):
        from backend import afsim_state
        w=partitioned();after=self.apply(w,proposal(w,remainder=.5))
        s=dict(id='a'*12,role_epoch=0,war_state=after,turn_count=1,time_step='30分钟',execution_backend='narrative')
        row=afsim_state.observation(s)['units'][0]['legacy_support_constraint']
        self.assertEqual((row['noncombat_delta'],row['noncombat_maximum'],row['remainder']),(0,0,.5))
        self.assertFalse(row['calibration_proven']);self.assertNotIn('accepted_remainders',row)
        after['dsh_execution']['legacy_noncombat_constraint']['turn']=0
        self.assertTrue(all('legacy_support_constraint' not in r for r in afsim_state.observation(s)['units']))

    def test_native_frame_replaces_only_current_dsh_receipt_and_preserves_source_history(self):
        from verify_afsim_world import world
        from backend import afsim_turns,afsim_world
        from types import SimpleNamespace
        w=world();w['dsh_execution']={'source':'dsh_native_runtime','old_turn_marker':'keep-in-history'}
        s=dict(id='a'*12,war_state=w,turn_count=0,time_step='15分钟',history=[copy.deepcopy(w)])
        before=copy.deepcopy(s);observed=copy.deepcopy(w)
        with patch.object(afsim_world,'compile_scene',return_value={'seconds':900}),patch.object(afsim_world,'run_scene',return_value=({},{})),patch.object(afsim_world,'apply_observations',return_value=observed):
            result,_,_=afsim_turns.execute_scene(s,[],SimpleNamespace(progress={}))
        self.assertFalse('dsh_execution' in result['updated_state'],'A completed Native frame must not expose a stale DSH current receipt')
        self.assertEqual(s,before);self.assertEqual(result['updated_state']['red_units'],w['red_units'])


if __name__=='__main__':unittest.main(verbosity=2)
