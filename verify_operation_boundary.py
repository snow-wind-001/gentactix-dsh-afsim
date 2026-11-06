"""An explicit operation boundary is distinct from the physical world extent."""
import copy
import json
import unittest
from gentactix import commands, historical_operations as ho, missions
from tools.qa.operation_boundary_fixture import inputs
from verify_unit_participation import physical, order


class OperationBoundaryTests(unittest.TestCase):
    def world(self):
        return ho.initial(*inputs())

    def unit(self, world):
        return next(u for u in world['red_units'] if u['historical_unit_id']=='ww2.cn.division159')

    def route(self, world):
        return world['mission']['definition']['operation_boundary']['routes'][0]

    def advance(self, before, point, kind='withdraw', request_id='a'*32):
        from gentactix import unit_participation as up
        unit=self.unit(before);after=physical(before,unit['name'],point)
        raw=order(unit['name'],self.route(before)['outside' if kind=='withdraw' else 'inside'],kind,request_id)
        raw.update(point)
        up.advance(before,after,[raw],1800,source='dsh_model_estimate')
        return after

    def test_config_is_frozen_and_old_definition_does_not_gain_fields(self):
        source,p=inputs();original=copy.deepcopy(p);new=ho.definition(source,p)
        self.assertEqual(new['operation_boundary'],p['operation_boundary']);self.assertEqual(p,original)
        p.pop('operation_boundary');legacy=ho.definition(source,p)
        self.assertNotIn('operation_boundary',legacy);self.assertNotEqual(missions.digest(new),missions.digest(legacy))
        self.assertEqual(ho.from_binding(legacy['historical_calculation']),legacy)

    def test_invalid_boundary_routes_or_unsupported_rules_are_rejected(self):
        for case in ('outside_world','no_routes','wrong_side','invalid_point','no_plan','outside_initial'):
            s,p=inputs();cfg=p['operation_boundary']
            if case=='outside_world':cfg['radius_km']=5
            elif case=='no_routes':cfg['routes']=[]
            elif case=='wrong_side':cfg['routes'][0]['outside']=copy.deepcopy(cfg['routes'][0]['inside'])
            elif case=='invalid_point':cfg['routes'][0]['outside']['lat']=float('nan')
            elif case=='no_plan':p.pop('campaign_plan')
            else:cfg['radius_km']=.1
            with self.subTest(case=case),self.assertRaises(ValueError):ho.initial(s,p)

    def test_crossing_requires_explicit_directive_and_registered_corridor(self):
        w=self.world();u=self.unit(w);route=self.route(w);before=copy.deepcopy(w)
        with self.assertRaises(ValueError):missions.validate_orders(w,[dict(unit=u['name'],action='move',**route['outside'])],'30分钟')
        raw=order(u['name'],dict(lat=u['lat']-.012,lng=u['lng']))
        with self.assertRaises(ValueError):missions.validate_orders(w,[raw],'30分钟')
        raw=order(u['name'],route['outside']);raw.update(lat=u['lat']+.003,lng=u['lng'])
        missions.validate_orders(w,[raw],'30分钟')
        self.assertEqual(w,before)

    def test_actual_arrival_is_offmap_not_legacy_reserve_and_keeps_all_accounts(self):
        from gentactix import unit_participation as up
        w=self.world();u=self.unit(w);u['personnel'].update(current=280,casualties=20)
        a=self.advance(w,self.route(w)['outside']);row=up.unit_view(a,self.unit(a),'red')
        self.assertEqual(row['status'],'offmap');self.assertEqual(row['operation_zone'],'outside')
        self.assertTrue(row['targetable']);self.assertFalse(row['controls_objectives'])
        for k in ('personnel','equipment','logistics','formation'):
            self.assertEqual(self.unit(a)[k],u[k])
        self.assertEqual(set(a['unit_participation']['actors']),set(w['unit_participation']['actors']))
        self.assertEqual(a['unit_participation']['version'],'unit-participation-2')

    def test_partial_exit_has_position_based_zone_without_premature_arrival(self):
        from gentactix import unit_participation as up
        w=self.world();u=self.unit(w);point=dict(lat=u['lat']+.010,lng=u['lng'])
        a=self.advance(w,point);row=up.unit_view(a,self.unit(a))
        self.assertEqual(row['status'],'withdrawing');self.assertEqual(row['operation_zone'],'outside')
        self.assertFalse(up.in_operation(a,self.unit(a)));self.assertIsNotNone(row['pending'])

    def test_cancel_after_crossing_keeps_offmap_instead_of_fake_deployed(self):
        from gentactix import unit_participation as up
        w=self.world();u=self.unit(w);a=self.advance(w,dict(lat=u['lat']+.010,lng=u['lng']))
        b=physical(a);up.advance(a,b,[dict(unit=u['name'],action='hold')],1800,source='dsh_model_estimate')
        self.assertEqual(up.unit_view(b,self.unit(b))['status'],'offmap')
        self.assertEqual(self.unit(b),self.unit(a));self.assertIsNone(up.unit_view(b,self.unit(b))['pending'])

    def test_reentry_uses_actual_route_and_preserves_entity(self):
        from gentactix import unit_participation as up
        w=self.world();a=self.advance(w,self.route(w)['outside']);identity=up.unit_view(a,self.unit(a))['entity_id']
        b=self.advance(a,self.route(a)['inside'],'reenter','b'*32)
        self.assertEqual(up.unit_view(b,self.unit(b))['status'],'deployed')
        self.assertEqual(up.unit_view(b,self.unit(b))['entity_id'],identity)
        self.assertEqual(self.unit(b)['personnel'],self.unit(w)['personnel'])

    def test_backend_cannot_invent_off_corridor_or_unordered_movement(self):
        from gentactix import unit_participation as up
        w=self.world();u=self.unit(w);outside=self.route(w)['outside']
        for case in ('deviation','no_order'):
            point={**outside,'lng':outside['lng']+.004} if case=='deviation' else outside
            a=physical(w,u['name'],point);saved=copy.deepcopy(a)
            orders=[order(u['name'],outside)] if case=='deviation' else [dict(unit=u['name'],action='hold')]
            with self.subTest(case=case),self.assertRaises(ValueError):up.advance(w,a,orders,1800,source='dsh_model_estimate')
            self.assertEqual(a,saved)

    def test_offmap_state_cannot_be_forged_at_inside_position(self):
        from gentactix import unit_participation as up
        w=self.world();a=self.advance(w,self.route(w)['outside']);self.unit(a).update(self.route(w)['inside'])
        with self.assertRaises(ValueError):up.validate_state(a)

    def test_normal_command_queue_preserves_boundary_route_intent(self):
        w=self.world();s=dict(id='boundary-qa',war_state=w,time_step='30分钟',turn_count=0,role_epoch=0,
            product_mode='historical',simulation_mode='open',execution_backend='afsim')
        cs=commands.state(s);unit=self.unit(w);uid=next(r['id'] for r in cs['registry'] if r['name']==unit['name'])
        s['command_state']=commands.replace_queue(s,[dict(unit_id=uid,action='move',duration='until_arrived',
            destination=self.route(w)['outside'],participation='withdraw')],control_team='red',director=True,no_fire=False,intent='QA')
        prepared=commands.prepare(s);raw=prepared['manual'][0]['order']
        self.assertEqual(raw['participation']['destination'],self.route(w)['outside'])
        commands.validate_saved(s)

    def test_boundary_registry_cannot_be_omitted_and_legacy_rejects_offmap(self):
        from gentactix import unit_participation as up
        w=self.world();w.pop('unit_participation')
        with self.assertRaises(ValueError):up.validate_state(w)
        s,p=inputs();p.pop('operation_boundary');legacy=ho.initial(s,p)
        u=self.unit(legacy);a=physical(legacy,u['name'],dict(lat=u['lat']+.001,lng=u['lng']))
        up.advance(legacy,a,[order(u['name'],dict(lat=u['lat']+.001,lng=u['lng']))],1800,source='dsh_model_estimate')
        next(iter(a['unit_participation']['actors'].values()))['status']='offmap';up._seal(a['unit_participation'])
        with self.assertRaises(ValueError):up.validate_state(a)

    def test_outside_to_outside_cannot_cut_through_operation_zone(self):
        from gentactix import operation_boundary as ob
        w=self.world();a=self.advance(w,self.route(w)['outside']);u=self.unit(a)
        point=dict(lat=w['mission']['definition']['map_center']['lat']-.012,lng=u['lng'])
        with self.assertRaises(ValueError):ob.check_order(a,u,'red',dict(unit=u['name'],action='move',**point))

    def test_inside_reserve_and_reentry_keep_legacy_semantics(self):
        from gentactix import unit_participation as up
        w=self.world();u=self.unit(w);rear=dict(lat=u['lat']+.001,lng=u['lng'])
        a=physical(w,u['name'],rear);up.advance(w,a,[order(u['name'],rear)],1800,source='dsh_model_estimate')
        self.assertEqual(up.unit_view(a,self.unit(a))['status'],'reserve')
        b=physical(a,u['name'],self.route(w)['inside'])
        up.advance(a,b,[order(u['name'],self.route(w)['inside'],'reenter','b'*32)],1800,source='dsh_model_estimate')
        self.assertEqual(up.unit_view(b,self.unit(b))['status'],'deployed')

    def test_native_observation_separates_compact_zone_and_full_geometry(self):
        from backend import afsim_state
        w=self.world();s=dict(id='boundary-observe',war_state=w,turn_count=0,time_step='30分钟',execution_backend='afsim')
        view=afsim_state.observation(s,{'limit':16})
        self.assertEqual(view['operation_boundary']['route_count'],1)
        self.assertNotIn('routes',view['operation_boundary'])
        self.assertTrue(all('operation_routes' not in u for u in view['units']))
        detailed=afsim_state.observation(s,{'ids':[view['units'][1]['id']],'limit':1,'detail':True})
        self.assertEqual(detailed['operation_boundary']['routes'],w['mission']['definition']['operation_boundary']['routes'])

    def test_frozen_save_roundtrip_and_original_legacy_checks(self):
        from gentactix import unit_participation as up
        w=self.world();a=self.advance(w,self.route(w)['outside']);restored=json.loads(json.dumps(a))
        up.validate_state(restored);missions.validate(self.world())
        # physical() is a participation-only fixture, not a complete combat turn.
        # Full committed-world cold recovery belongs to backend acceptance.
        self.assertEqual(restored,a)


if __name__=='__main__':unittest.main()
