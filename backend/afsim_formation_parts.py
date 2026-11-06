"""Native goal aggregation and fractional noncombat receipts for disjoint parts."""
import math

from gentactix import formation_parts, missions


def goal_flags(platform, current, goal_test, exit_test, crossed_test):
    flags = {'live': f'{current}>0', 'zone': f'{current}>0 && ({goal_test})',
             'exit': f'{current}>0 && ({exit_test})', 'crossed': f'{current}>0 && ({crossed_test})'}
    return [f' {platform}.SetAuxData("gtx_parent_{key}",(double)((int)({value})));' for key, value in flags.items()]


def goal_counts(world, identities):
    """Compile aggregation, not perform a mission-state transition in Python."""
    if not formation_parts.has_groups(world):
        return []
    lines = [' // gtx_parent_goal: count original formations once, never per fragment']
    for team in ('red', 'blue'):
        for metric in ('Alive', 'InGoal', 'AtExit', 'Crossed'):
            lines.append(f' {team}{metric}=0;')
        for members in formation_parts.buckets(world, team):
            def flag(unit, field):
                return f'WsfSimulation.FindPlatform("{identities[unit["name"]]}").AuxDataDouble("gtx_parent_{field}")'
            live = '(' + '+'.join(flag(u, 'live') for u in members) + ')>0'
            for field, metric in (('live', 'Alive'), ('zone', 'InGoal'), ('exit', 'AtExit'), ('crossed', 'Crossed')):
                if field in ('exit', 'crossed'):
                    condition = live + ' && ' + ' && '.join(f'({flag(u,"live")}==0 || {flag(u,field)}>0)' for u in members)
                else:
                    condition = '(' + '+'.join(flag(u, field) for u in members) + ')>0'
                lines.append(f' if ({condition}) {{ {team}{metric}={team}{metric}+1; }}')
    return lines


def parse(text, model, scene):
    expected = {i for i, e in scene['entities'].items() if formation_parts.is_fragment(next(u for _, u in model['units'] if u['name'] == e['name']))}
    rows = {}
    for line in text.splitlines():
        if not line.startswith('GTXPARTSTATE|'):
            continue
        pieces = line.split('|')
        if len(pieces) != 3 or pieces[1] not in expected or pieces[1] in rows:
            raise ValueError('计算分队余量回执未知、缺项或重复')
        value = float(pieces[2])
        if not math.isfinite(value) or not 0 <= value < 1:
            raise ValueError('计算分队非战斗减员余量非法')
        rows[pieces[1]] = value
    if set(rows) != expected:
        raise ValueError('计算分队缺少原生非战斗减员余量回执')
    return rows


def apply(after, rows, scene):
    index = {u['name']: u for _, u in missions.units(after)}
    for identity, value in rows.items():
        index[scene['entities'][identity]['name']]['formation']['partition_noncombat_remainder'] = value
