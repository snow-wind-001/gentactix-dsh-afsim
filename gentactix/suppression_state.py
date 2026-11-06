"""Frozen suppression precision and read-only state checks; no turn executor."""
import math

VERSION = 'fixed-time-suppression-1'
SCALE = 1_800_000_000_000
FIELD = 'suppression_carry_ticks'
CONFIG = {'version': VERSION, 'units_per_point': SCALE,
          'gain_quantum': .000001, 'clock_resolution_ms': 1}


def validate_config(value):
    if (not isinstance(value, dict) or value != CONFIG
            or any(type(value[k]) is not type(v) for k, v in CONFIG.items())):
        raise ValueError('连续压制的冻结版本、精度或时钟单位非法')


def validate_unit(unit):
    f = unit['formation']; points = f['suppression']; carry = f.get(FIELD, 0)
    if (type(points) is not int or not 0 <= points <= 100
            or type(carry) is not int or not 0 <= carry < SCALE
            or points == 100 and carry):
        raise ValueError('压制整数与余量须为有界整数，合计不得超过100')


def load(unit):
    validate_unit(unit)
    f = unit['formation']
    return f['suppression'] * SCALE + f.get(FIELD, 0)


def value(unit):
    f = unit.get('formation', {})
    return load(unit)/SCALE if FIELD in f else f.get('suppression', 0)


def quiet_load(unit, decay, seconds):
    """Necessary unopposed-decay bound; callers do not apply it to a world."""
    return max(0, load(unit)-math.floor(decay*1e6+.5)*math.floor(seconds*1000+.5))


def validate_model_transition(before, after, orders, seconds):
    """Check exact unopposed decay; incoming effects remain model estimates."""
    incoming = {o['target'] for o in orders if o['action'] in ('fire', 'bombard', 'suppress', 'air_support') and 'target' in o}
    old = {u['name']: u for team in ('red', 'blue') for u in before[team+'_units']}
    decay = before['mission']['definition']['combined_rules']['suppression_decay']
    for team in ('red', 'blue'):
        for u in after[team+'_units']:
            validate_unit(u)
            if u['name'] not in incoming:
                expected = quiet_load(old[u['name']], decay, seconds)
                if load(u) != expected:
                    raise ValueError(u['name']+'：无来袭时压制整数及余量不符合冻结时间衰减')


def instruction():
    return ('【fixed-time-suppression-1】启用时，每个unit_updates[].formation必须同时明确提交'
            'suppression整数及suppression_carry_ticks整数。此余量是两种执行路径共用的数值状态，不是AFSIM回执，须由模型声明，不属于禁止写入的原生毁伤余量。总压制载荷=' 
            'suppression*1800000000000+suppression_carry_ticks；余量范围[0,1800000000000)，100点时余量为0。'
            '无来袭时，载荷=max(0,旧载荷-floor(suppression_decay*1000000+0.5)*floor(本轮秒数*1000+0.5))；'
            '整数与余量用整除和取模拆分。来袭增量由模型估计、保持0—100范围；不得伪称AFSIM回执。'
            '这不是伤亡或历史效能标定。未启用该版本时禁止添加此余量字段。')
