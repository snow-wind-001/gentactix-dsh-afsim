"""Native fixed-point suppression generation and strict receipt admission."""
import math
from gentactix import suppression_state as state


def functions(decay):
    rate = math.floor(decay*1e6+.5)
    return f'''script void GtxSuppressionDecay(WsfPlatform actor,double at)
 double ms=Math.Floor(at*1000+0.5);
 double dt=Math.Max(0,ms-actor.AuxDataDouble("ca_suppression_sample_ms"));
 double ticks=Math.Max(0,actor.AuxDataDouble("ca_suppression_ticks")-{rate}.0*dt);
 actor.SetAuxData("ca_suppression_ticks",ticks);
 actor.SetAuxData("ca_suppression",ticks/{state.SCALE}.0);
 actor.SetAuxData("ca_suppression_sample_ms",ms);
end_script
script void GtxSuppressionCommit(WsfPlatform actor)
 double ticks=Math.Min({100*state.SCALE}.0,actor.AuxDataDouble("ca_suppression_ticks")+actor.AuxDataDouble("ca_pending_suppression_ticks"));
 actor.SetAuxData("ca_suppression_ticks",ticks);
 actor.SetAuxData("ca_suppression",ticks/{state.SCALE}.0);
 actor.SetAuxData("ca_pending_suppression_ticks",0.0);
end_script
'''


def gain(expression):
    return ('target.SetAuxData("ca_pending_suppression_ticks",target.AuxDataDouble("ca_pending_suppression_ticks")+'
            f'Math.Floor(({expression})*1000000+0.5)*{state.SCALE//1000000});')


def receipt(actor, identity):
    total = actor+'.AuxDataDouble("ca_suppression_ticks")'
    points = f'Math.Floor({total}/{state.SCALE}.0)'
    return (f' writeln("GTXSUPPRESSION|{identity}|",Format.Fixed({points},0),"|",'
            f'Format.Fixed({total}-{points}*{state.SCALE}.0,0),"|",'
            f'Format.Fixed({actor}.AuxDataDouble("ca_suppression_sample_ms"),0));')


def read_row(parts, rows, scene):
    if len(parts) != 5 or parts[1] not in scene['entities'] or parts[1] in rows:
        raise ValueError('连续压制回执缺项、重复或身份不符')
    rows[parts[1]] = dict(zip(('points', 'carry_ticks', 'at_ms'), map(int, parts[2:])))


def validate_receipts(rows, model, scene, units):
    cfg = model.get('combat_profile', {}).get('suppression_state')
    if cfg is None:
        if rows: raise ValueError('旧规则不得接收连续压制余量回执')
        return
    state.validate_config(cfg)
    if set(rows) != set(scene['entities']): raise ValueError('连续压制回执必须覆盖全部单位')
    endpoint = math.floor(scene['seconds']*1000+.5)
    for identity, row in rows.items():
        if (set(row) != {'points', 'carry_ticks', 'at_ms'}
                or any(type(v) is not int for v in row.values())
                or row['at_ms'] != endpoint or identity not in units
                or row['points'] != units[identity]['suppression']):
            raise ValueError('连续压制回执时刻、整数或余量不一致')
        state.validate_unit({'formation': {'suppression': row['points'], state.FIELD: row['carry_ticks']}})
