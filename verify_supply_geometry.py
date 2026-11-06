"""Timed supply cannot bypass known control or deliver to a dead recipient."""
import copy
from datetime import datetime, timedelta
import unittest

from gentactix import historical_operations as ho, missions, supply_schedule as ss
from verify_personnel_rations import parameters, config as ration_config
from verify_supply_schedule import config as schedule_config
from verify_split_supply import config as split_config


def sample(*, blocked=True, staged=False,parameters_only=False):
    if staged:
        from tools.qa.campaign_fixture import inputs
        source, p = inputs()
        p.update(support_dynamics=ration_config(), supply_distribution=split_config())
        p['rules']['ton_per_supply_unit'] = .25
        for a in p['actors'].values():a['logistics']['food'] = 0
    else:
        source, p = parameters(food=0)
    p['supply_schedule'] = schedule_config()
    p['clock']['time_step'] = '1小时'
    p['rules']['bridge_enabled'] = False
    for a in p['actors'].values():
        a['ground_control_radius_km'] = 0
        a['equipment']['transport'] = 20
    red, depot = p['actors']['ww2.cn.division31']['position'], p['support']['red']['position']
    enemy = p['actors']['ww2.jp.seya_detachment']
    enemy['position'] = {k: (red[k] + depot[k]) / 2 for k in ('lat', 'lng')}
    enemy['ground_control_radius_km'] = .2 if blocked else 0
    if staged:
        p['campaign']['arrivals']['ww2.jp.seya_detachment']['not_before'] = (datetime.fromisoformat(p['clock']['start']) + timedelta(hours=2)).isoformat()
    return (source,p) if parameters_only else ho.initial(source, p)


def ledger(world, *, received=.1):
    return dict(version=ss.VERSION, units=[dict(unit=u['name'], events=[
        dict(seconds=t, kind=kind, supply_status='未切断', position={k:u[k] for k in ('lat','lng')},
             food_received=received if kind=='delivery' and u['personnel']['current'] else 0,
             ammo_received=0, ammo_spent=0, received={}, spent={})
        for t,kind in ss.event_times(world,3600)]) for _,u in missions.units(world)])


def holds(world):return [dict(unit=u['name'],action='hold') for _,u in missions.units(world)]


class SupplyGeometryTests(unittest.TestCase):
    def test_static_known_enemy_blocks_claimed_delivery_without_mutating_input(self):
        w=sample();data=ledger(w);before=copy.deepcopy((w,data))
        with self.assertRaisesRegex(ValueError,'控制区|切断'):
            ss.validate_ledger(w,data,holds(w),3600)
        self.assertEqual((w,data),before)

    def test_blocked_status_and_zero_cargo_is_a_valid_shortage_receipt(self):
        w=sample();data=ledger(w,received=0)
        for event in data['units'][0]['events']:event['supply_status']='已切断'
        result=ss.validate_ledger(w,data,holds(w),3600)
        self.assertEqual(result[w['red_units'][0]['name']]['food_received'],0)

    def test_valid_declared_blocker_move_clears_the_link_at_delivery(self):
        w=sample();data=ledger(w);orders=holds(w)
        enemy=next(u for u in w['blue_units'] if u['historical_unit_id']=='ww2.jp.seya_detachment')
        next(o for o in orders if o['unit']==enemy['name'])['action']='move'
        from gentactix import supply
        red=w['red_units'][0];node=supply.bound_node(w,'red',red)
        axis='lng' if abs(red['lat']-node['lat'])>abs(red['lng']-node['lng']) else 'lat'
        for event in next(r for r in data['units'] if r['unit']==enemy['name'])['events']:
            event['position'][axis]+=.006 if axis=='lng' else .004
        result=ss.validate_ledger(w,data,orders,3600)
        self.assertEqual(result[w['red_units'][0]['name']]['food_received'],.1)

    def test_not_yet_arrived_blocker_does_not_control_the_link(self):
        w=sample(staged=True)
        result=ss.validate_ledger(w,ledger(w),holds(w),3600)
        self.assertEqual(result[w['red_units'][0]['name']]['food_received'],.1)

    def test_surviving_target_is_still_a_proven_blocker_even_during_combat(self):
        w=sample();orders=holds(w)
        enemy=next(u for u in w['blue_units'] if u['historical_unit_id']=='ww2.jp.seya_detachment')
        orders[0].update(action='fire',target=enemy['name'])
        with self.assertRaisesRegex(ValueError,'控制区|切断'):
            ss.validate_ledger(w,ledger(w),orders,3600,after=copy.deepcopy(w))

    def test_unknown_timed_combat_death_is_not_guessed_as_a_live_blocker(self):
        w=sample();orders=holds(w)
        enemy=next(u for u in w['blue_units'] if u['historical_unit_id']=='ww2.jp.seya_detachment')
        orders[0].update(action='fire',target=enemy['name'])
        result=ss.validate_ledger(w,ledger(w),orders,3600)
        self.assertEqual(result[w['red_units'][0]['name']]['food_received'],.1)

    def test_receipt_cannot_use_the_whole_round_movement_budget_at_first_quarter(self):
        w=sample(blocked=False);w['mission']['definition']['supply_schedule']['period_seconds']=900
        data=ledger(w,received=0);orders=holds(w);unit=w['red_units'][0]
        next(o for o in orders if o['unit']==unit['name'])['action']='move'
        distance=missions.move_budget(w,unit)*.8
        for event in data['units'][0]['events']:event['position']['lat']+=distance/111.2
        with self.assertRaisesRegex(ValueError,'机动|时点'):
            ss.validate_ledger(w,data,orders,3600)

    def test_intra_step_noncombat_death_prevents_later_food_receipt(self):
        w=sample(blocked=False);unit=w['red_units'][0]
        unit['personnel'].update(committed=1,current=1)
        unit['sustainment'].update(shortage_hours=2,noncombat_remainder=.95)
        w['mission']['definition']['support_dynamics'].update(incapacity_after_hours=1,incapacity_fraction_per_hour=.1)
        with self.assertRaisesRegex(ValueError,'无可用|失能'):
            ss.validate_ledger(w,ledger(w,received=.001),holds(w),3600)


if __name__=='__main__':unittest.main()
