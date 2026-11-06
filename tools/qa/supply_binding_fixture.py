"""Frozen multi-depot QA input. No historical deployment or stock claim."""
import copy

from gentactix import combined_arms, missions


def definition(*, combined=False, split=False):
    spec = combined_arms.demo_definition() if combined else missions.definition('AJ15-local-v1')
    spec['id'] = 'QA-bound-depots-' + ('combined' if combined else 'legacy') + ('-split' if split else '')
    spec.pop('air_definition', None)
    state = spec['initial_state']
    if combined:
        cfg = spec['combined_rules']
        cfg.update(bridge_enabled=False, air_support=False)
        state['combined_arms']['rules_hash'] = missions.digest(cfg)
    nodes = state['supply_nodes']
    red = next(n for n in nodes if n['team'] == 'red')
    red['stock'] = 0
    branch = {**copy.deepcopy(red), 'id': 'qa-red-branch', 'name': 'QA独立分仓',
              'stock': 9, 'lat': red['lat'] + .012}
    spare = {**copy.deepcopy(red), 'id': 'qa-red-unused', 'name': 'QA未绑定仓库',
             'stock': 99, 'lat': red['lat'] - .012}
    nodes.extend([branch, spare])
    for index, unit in enumerate(state['red_units']):
        if index:
            unit['supply_node_id'] = branch['id']
    for _, unit in missions.units(state):
        unit['logistics'] = {'food': 80, 'ammo': 80}
        if combined:
            unit['ground_control_radius_km'] = 0
            unit['formation']['fuel_liters'] = 2000
    if split:
        spec['supply_distribution'] = {
            'version': 'split-stocks-1', 'food_mass_share': .5, 'priority': 'food',
            'assumption': 'QA独立分仓的分类库存假设，不是历史物资记录。'}
        for node in nodes:
            node['commodities'] = {'food': node['stock'], 'ammo': node['stock']}
    return spec
