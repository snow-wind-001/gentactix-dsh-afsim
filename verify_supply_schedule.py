"""Time-scheduled supply must survive different turn lengths and old saves."""
import copy
import unittest

from gentactix import historical_operations as ho, missions
from tools.qa.historical_operational_fixture import inputs
from verify_support_dynamics import config as nutrition_config
from verify_split_supply import config as split_config


def config():
    return {'version': 'scheduled-supply-1', 'period_seconds': 3600,
            'passive_work_per_hour': 4, 'resupply_work_per_hour': 16,
            'convoy_speed_kph': 15, 'loading_hours': .25,
            'warehouse_tons_per_hour': {'red-historical-supply': 100, 'blue-historical-supply': 100},
            'assumption': 'QA aggregate scheduled service; capacity and operating pipeline assumed, no historical calibration or individual convoy transit.'}


def world(*, food=0, step='6小时'):
    s, p = inputs()
    p.update(support_dynamics=nutrition_config(), supply_distribution=split_config(), supply_schedule=config())
    p['clock']['time_step'] = step
    p['goal'].update(termination_mode='objectives', deadline_turn=30,profile='assault',
                     objective={'lat':p['area']['center']['lat']+.1,'lng':p['area']['center']['lng']})
    p['rules']['goal_profile']='assault'
    for a in p['actors'].values():
        a['logistics'] = {'food': food, 'ammo': 100}
        a['ground_control_radius_km'] = 0
    return ho.initial(s, p)


def schedule_ledger(before, seconds):
    """Explicit test receipts: four food work per fixed hour, no ammunition use."""
    from gentactix import supply_schedule as ss
    return {'version': ss.VERSION, 'units': [
        {'unit': u['name'], 'events': [dict(seconds=t, kind=kind,
            supply_status='未切断', position={'lat': u['lat'], 'lng': u['lng']},
            food_received=4 if kind=='delivery' else 0, ammo_received=0,
            ammo_spent=0, received={}, spent={}) for t,kind in ss.event_times(before, seconds)]}
        for _, u in missions.units(before)]}


def model_proposal(before):
    from verify_dsh_resources import model_result
    p=model_result(before);p['supply_schedule_ledger']=schedule_ledger(before,21600)
    p['sustainment_ledger']={'version':'time-sustainment-1','units':[]}
    for row,update,(_,u) in zip(p['resource_ledger']['units'],p['unit_updates'],missions.units(before)):
        row.update(food_spent=20,delivery=12,food_received=24,ammo_received=0,supply_status='未切断')
        update['logistics']={'food':4,'ammo':100}
        update['sustainment']={'version':'time-sustainment-1','shortage_hours':0,'noncombat_remainder':0}
        p['sustainment_ledger']['units'].append({'unit':u['name'],'demand':24,'consumed':20,'unmet':4,
            'shortage_hours':0,'noncombat_remainder':0,'fatigue_floor':0,'noncombat_delta':0})
        depot=next(n for n in p['supply_nodes'] if n['id']==u['supply_node_id'])
        depot['commodities']['food']-=24;depot['stock']-=12
    return p


class CampaignSupplyContextTests(unittest.TestCase):
    def campaign_world(self, *, future=True):
        from tools.qa.campaign_plan_fixture import inputs as campaign_inputs
        source, parameters = campaign_inputs()
        red = parameters['actors']['ww2.cn.division159']['position']
        depot = parameters['support']['red']['position']
        parameters['actors']['ww2.jp.division106']['position'] = {
            key: (red[key] + depot[key]) / 2 for key in ('lat', 'lng')}
        parameters['actors']['ww2.jp.division106']['ground_control_radius_km'] = .2
        if future:
            parameters['campaign']['arrivals']['ww2.jp.division106']['not_before'] = '1938-10-07T02:00'
        return ho.initial(source, parameters)

    def test_native_reference_preserves_campaign_release_time_without_live_aliases(self):
        from gentactix import campaign, supply_schedule as ss
        before = self.campaign_world()
        saved = copy.deepcopy(before)
        reference = ss.reference_inputs(before)
        unit = reference['blue_units'][0]
        self.assertEqual(campaign.release_seconds(reference, unit), 7200)
        self.assertEqual(reference['current_time'], before['current_time'])
        unit['personnel']['current'] = 0
        self.assertEqual(before, saved)

    def test_known_control_guard_distinguishes_future_and_arrived_campaign_blockers(self):
        from gentactix import supply_schedule as ss
        for future in (True, False):
            world = self.campaign_world(future=future)
            target = next(u for u in world['red_units'] if u['historical_unit_id'] == 'ww2.cn.division159')
            # Minimal inputs to the control-bound guard, not a simulated delivery.
            rows = [{'unit': u['name'], 'events': [dict(kind='delivery', seconds=1800,
                supply_status='未切断', position={k: u[k] for k in ('lat', 'lng')})]
                if u['name'] == target['name'] else []} for _, u in missions.units(world)]
            reference = ss.reference_inputs(world)
            saved = copy.deepcopy(reference)
            if future:
                ss._validate_known_control(reference, rows, [], after=world)
            else:
                with self.assertRaisesRegex(ValueError, '切断'):
                    ss._validate_known_control(reference, rows, [], after=world)
            self.assertEqual(reference, saved)

    def test_native_reference_resolves_formally_converted_campaign_arrivals(self):
        from gentactix import campaign, formation_continuity, supply_schedule as ss
        from verify_formation_continuity import world, proposal
        before = world()
        prepared = formation_continuity.prepare(before, proposal(before), team='red')['world']
        reference = ss.reference_inputs(prepared)
        converted = [u for u in reference['red_units'] if u.get('runtime_allocation')]
        self.assertEqual(len(converted), 2)
        for unit in converted:
            self.assertEqual(campaign.release_seconds(reference, unit),
                             campaign.release_seconds(prepared, unit))
            self.assertEqual(campaign.scheduled_time(campaign.definition(reference), unit, world=reference),
                campaign.scheduled_time(campaign.definition(prepared), unit, world=prepared))


class ScheduledSupplyTests(unittest.TestCase):
    def test_adjacent_phase_reset_preserves_the_next_delivery_instead_of_restarting_period(self):
        from gentactix import supply_schedule as ss,phase_continuity,sim_clock
        source=world(food=80,step='5分钟')
        source['current_time'],source['simulation_clock']=sim_clock.target(source,'55分钟')
        source['mission'].update(turn=11,status='completed')
        binding=source['mission']['definition']['historical_calculation'];p=copy.deepcopy(binding['parameters'])
        p['clock']['start']=source['current_time']
        target={'format':ho.FORMAT,'initial':binding['initial'],'parameters':p}
        child=missions.from_definition(phase_continuity.definition(phase_continuity.bind(source,target)))
        self.assertEqual(ss.event_times(child,300),ss.event_times(source,300))
        self.assertEqual(ss.event_times(child,300),[(300,'delivery'),(300,'settlement')])
        p.pop('supply_schedule')
        with self.assertRaisesRegex(ValueError,'supply_schedule'):
            phase_continuity.definition(phase_continuity.bind(source,target))

    def test_shared_warehouse_capacity_is_not_multiplied_by_unit_count(self):
        from gentactix import supply_schedule as ss
        w=world();cfg=w['mission']['definition']['supply_schedule']
        one=4*.5*w['mission']['definition']['combined_rules']['ton_per_supply_unit']
        cfg['warehouse_tons_per_hour']['blue-historical-supply']=one*1.5
        with self.assertRaisesRegex(ValueError,'多单位争用'):
            ss.validate_ledger(w,schedule_ledger(w,21600),[],21600)

    def test_required_model_template_and_native_globals_expose_real_configuration(self):
        from backend import scenario_builder,scenario_assembly
        from tools.qa.historical_operational_fixture import BATTLE
        basis=scenario_builder.historical_basis(BATTLE,'taierzhuang',termination_mode='objectives')
        scenario_assembly.prepare_required_models(basis,['time-sustainment-1','scheduled-supply-1'])
        self.assertIsNone(basis['configuration_template']['supply_schedule']['passive_work_per_hour'])
        assembly=scenario_assembly.create(basis);self.addCleanup(scenario_assembly.close,assembly.id)
        p=world()['mission']['definition']['historical_calculation']['parameters']
        p=copy.deepcopy(p);p['goal']['team']=basis['configuration_template']['goal']['team']
        for actor in p['actors'].values():actor['formation'].setdefault('motorized',p['rules']['motorized'])
        patch={k:v for k,v in p.items() if k not in ('format','phase_id','actors')}
        result=assembly.tool('globals','update_scenario_configuration',{'revision':0,'patch':patch})
        self.assertTrue(result['updated'],result.get('error'))
        self.assertEqual(assembly.tool('globals','get_scenario_basis',{})['configuration']['supply_schedule'],config())
        updated=assembly.tool('actors:0','update_scenario_configuration',{'revision':1,'patch':{'actors':p['actors']}})
        self.assertTrue(updated['updated'],updated.get('error'))
        final=assembly.tool('final','validate_scenario_configuration',{})
        self.assertTrue(final['valid'],final.get('error'))
        with self.assertRaisesRegex(ValueError,'定时补给'):
            scenario_assembly.validate_required_models({},['scheduled-supply-1'])

    def test_one_millisecond_initial_load_is_not_a_delivery_or_turn(self):
        from backend import afsim_world
        from gentactix import supply_schedule as ss
        w=world();before=copy.deepcopy(w)
        self.assertEqual(ss.event_times(w,.001),[(.001,'settlement')])
        scene=afsim_world.compile_scene(w,[],.001,native_rules=True)
        self.assertEqual(scene['native_model']['script'].count('GTXSCHEDULE|'),3)
        self.assertEqual(w,before)

    def test_compact_observation_reports_totals_and_detail_preserves_event_times(self):
        from backend import dsh_simulation,afsim_state
        w=dsh_simulation.apply(world(),model_proposal(world()),'6小时')
        session={'id':'a123456789ab','war_state':w,'turn_count':1,'execution_backend':'narrative','time_step':'6小时'}
        before=copy.deepcopy(session);page=afsim_state.observation(session)
        receipt=page['units'][0]['supply_schedule']
        self.assertEqual(receipt['event_count'],7)
        self.assertEqual(receipt['delivery_times_s'],list(range(3600,21601,3600)))
        self.assertEqual(receipt['food_received'],24)
        self.assertNotIn('events',receipt)
        row=afsim_state.observation(session,page['units'][0]['detail_query'])['units'][0]
        self.assertEqual(len(row['supply_schedule']['events']),7)
        self.assertEqual(session,before)

    def test_invalid_rates_and_unsupported_crossing_do_not_silently_downgrade(self):
        from gentactix import supply_schedule as ss
        for key,value in [('period_seconds',True),('period_seconds',13),('passive_work_per_hour',float('nan')),('loading_hours',0),('assumption','')]:
            cfg={**config(),key:value}
            with self.subTest(key=key),self.assertRaises(ValueError):ss.validate_config(cfg)
        s,p=inputs();p.update(supply_schedule=config(),support_dynamics=nutrition_config(),supply_distribution=split_config())
        p['rules']['bridge_enabled']=True
        with self.assertRaisesRegex(ValueError,'定时补给'):ho.initial(s,p)

    def test_dsh_requires_matching_chronology_without_executing_the_effects(self):
        from backend import dsh_simulation
        from unittest.mock import patch
        before=world();proposal=model_proposal(before);frozen=copy.deepcopy(proposal);old=copy.deepcopy(before)
        with patch.object(missions,'advance',side_effect=AssertionError('No physical fallback')):
            after=dsh_simulation.apply(before,proposal,'6小时')
        self.assertEqual(before,old);self.assertEqual(proposal,frozen)
        self.assertEqual(after['red_units'][0]['logistics']['food'],4)
        self.assertEqual(after['mission']['ledger'][0]['food_spent'],20)
        self.assertEqual(after['supply_schedule']['source'],'dsh_model_estimate')
        for field in ('supply_schedule_ledger','sustainment_ledger'):
            bad=copy.deepcopy(proposal);bad.pop(field)
            with self.subTest(field=field),self.assertRaises(ValueError):dsh_simulation.apply(before,bad,'6小时')
        bad=copy.deepcopy(proposal);bad['resource_ledger']['units'][0]['food_received']=23
        with self.assertRaises(ValueError):dsh_simulation.apply(before,bad,'6小时')

    def test_dsh_instruction_does_not_combine_old_end_only_delivery_caps(self):
        from backend import dsh_simulation
        text=dsh_simulation.prompt(world())
        self.assertIn('supply_schedule_ledger',text)
        self.assertIn('段小时',text)
        self.assertNotIn('待命2*scale',text)
        self.assertNotIn('轮末弹药不能支付本轮射击',text)

    def test_native_compilation_contains_actual_timed_events_and_zero_end_bonus(self):
        from backend import afsim_world
        w=world();before=copy.deepcopy(w)
        scene=afsim_world.compile_scene(w,[],21600,native_rules=True)
        self.assertEqual(scene['native_model']['supply_schedule'],config())
        self.assertEqual(scene['native_model']['script'].count('GTXSCHEDULE|'),21)
        self.assertEqual(w,before)

    def test_optional_configuration_freezes_and_old_inputs_are_untouched(self):
        w = world()
        self.assertEqual(w['mission']['definition']['supply_schedule'], config())
        self.assertTrue(missions.validate(w))
        s,p=inputs();old=ho.initial(s,p)
        self.assertNotIn('supply_schedule', old['mission']['definition'])

    def test_fixed_delivery_times_do_not_restart_at_each_turn(self):
        from gentactix import supply_schedule as ss
        w = world(step='15分钟')
        self.assertEqual(ss.event_times(w,900),[(900,'settlement')])
        w['simulation_clock']['elapsed_seconds']=2700
        self.assertEqual(ss.event_times(w,900),[(900,'delivery'),(900,'settlement')])
        self.assertEqual(ss.event_times(world(),21600),[(t,'delivery') for t in range(3600,21601,3600)]+[(21600,'settlement')])

    def test_mid_turn_food_does_not_retroactively_feed_the_first_hour(self):
        from gentactix import supply_schedule as ss
        w=world();prior=copy.deepcopy(w)
        rows=ss.validate_ledger(w,schedule_ledger(w,21600),[],21600)
        unit=w['red_units'][0];row=rows[unit['name']]
        self.assertEqual(row['nutrition']['demand'],24)
        self.assertEqual(row['nutrition']['consumed'],20)
        self.assertEqual(row['nutrition']['unmet'],4)
        self.assertEqual(row['food_after'],4)
        self.assertEqual(row['food_received'],24)
        self.assertEqual(w,prior)

    def test_missing_duplicate_early_and_wrong_depot_capacity_receipts_reject(self):
        from gentactix import supply_schedule as ss
        w=world();good=schedule_ledger(w,21600)
        for mode in ('missing','duplicate','early','capacity'):
            bad=copy.deepcopy(good);source=copy.deepcopy(w)
            if mode=='missing':bad['units'][0]['events'].pop(0)
            elif mode=='duplicate':bad['units'][0]['events'].append(copy.deepcopy(bad['units'][0]['events'][0]))
            elif mode=='early':bad['units'][0]['events'][0]['seconds']=1
            else:source['mission']['definition']['supply_schedule']['warehouse_tons_per_hour']['blue-historical-supply']=0
            with self.subTest(mode=mode),self.assertRaisesRegex(ValueError,'定时补给'):
                ss.validate_ledger(source,bad,[],21600)


if __name__=='__main__':unittest.main()
