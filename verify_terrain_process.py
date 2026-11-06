"""Finite terrain barriers constrain LOS/movement without fabricating DEM data."""
import copy
import unittest
from gentactix import historical_operations, missions
from tools.qa.historical_operational_fixture import inputs


def terrain_inputs():
    snap, params = inputs()
    params['terrain_model'] = {'version': 'local-terrain-1', 'assumption': 'QA有限障碍线，不是测绘地形',
        'barriers': [{'id': 'qa-ridge', 'a': {'lat': 34.558, 'lng': 117.73},
                      'b': {'lat': 34.558, 'lng': 117.75}, 'blocks': ['direct_fire', 'movement'],
                      'source': 'QA测试地形'}], 'roads': []}
    return snap, params


class TerrainProcessTests(unittest.TestCase):
    def test_registered_road_changes_budget_only_inside_its_corridor(self):
        snap, params = terrain_inputs()
        params['terrain_model']['roads']=[{'id':'qa-road','a':{'lat':34.55,'lng':117.73817},
            'b':{'lat':34.557,'lng':117.73817},'width_m':20,'speed_factor':1.5,'source':'QA道路估计'}]
        world=historical_operations.initial(snap,params)
        unit=world['red_units'][0]
        base=missions.move_budget(world,unit)
        self.assertEqual(missions.move_budget(world,unit,{'lat':34.556,'lng':117.73817}),base*1.5)
        self.assertEqual(missions.move_budget(world,unit,{'lat':34.556,'lng':117.742}),base)

    def test_direct_fire_and_movement_cannot_cross_registered_barrier(self):
        from gentactix import terrain_process
        snap, params = terrain_inputs()
        world = historical_operations.initial(snap, params)
        before = copy.deepcopy(world)
        red, blue = world['red_units'][0], world['blue_units'][0]
        self.assertTrue(terrain_process.blocked(world, red, blue, 'direct_fire'))
        for order in ({'unit': red['name'], 'action': 'fire', 'target': blue['name']},
                      {'unit': red['name'], 'action': 'move', 'lat': blue['lat'], 'lng': blue['lng']}):
            with self.assertRaisesRegex(ValueError, '地形'):
                missions.validate_orders(world, [order], '30分钟')
        # Indirect fire is not automatically blocked by a ridge.
        terrain_process.check_order(world, {'unit':red['name'],'action':'bombard','target':blue['name']})
        self.assertEqual(world, before)

    def test_finite_line_does_not_block_path_beyond_its_end(self):
        from gentactix import terrain_process
        snap, params = terrain_inputs()
        world = historical_operations.initial(snap, params)
        self.assertFalse(terrain_process.blocked(world, {'lat':34.55,'lng':117.76}, {'lat':34.56,'lng':117.76}, 'movement'))

    def test_legacy_world_has_no_invented_terrain_and_invalid_geometry_rejected(self):
        from gentactix import terrain_process
        snap, params = inputs()
        world = historical_operations.initial(snap, params)
        self.assertIsNone(terrain_process.configuration(world))
        snap, params = terrain_inputs()
        params['terrain_model']['barriers'][0]['b'] = params['terrain_model']['barriers'][0]['a']
        with self.assertRaises(ValueError): historical_operations.initial(snap, params)


if __name__ == '__main__': unittest.main()
