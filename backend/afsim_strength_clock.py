"""Bind Native combat availability to the existing food/labour interval clock."""
from gentactix import strength_clock

REVISION = 1


def functions(damage_expression, captured_expression):
    # Both expressions are closed compiler templates, never model input/code.
    return '''script void GtxCombatStrengthRefresh(WsfPlatform a)
 if (a.AuxDataDouble("cm_initialized")<1) { return; }
 double people=Math.Max(0,a.AuxDataDouble("ca_initial_current")-Math.Floor('''+damage_expression+''')
  -a.AuxDataDouble("gtx_air_damage")-'''+captured_expression+''');
 a.SetAuxData("ca_combat_strength_ratio",people/a.AuxDataDouble("ca_committed"));
 a.SetAuxData("ca_live_strength_ratio",Math.Max(0,people-a.AuxDataDouble("cn_nc"))/a.AuxDataDouble("ca_committed"));
 if (a.AuxDataDouble("workforce_initialized")<1 || people!=a.AuxDataDouble("workforce_people")) {
  writeln("GTXSTRENGTH|",a.Name(),"|",Format.Fixed(TIME_NOW*1000,0),"|",Format.Fixed(people,0));
  a.SetAuxData("workforce_people",people);
  a.SetAuxData("workforce_initialized",1.0);
 }
end_script
'''


def refresh(platform):
    return f' GtxCombatStrengthRefresh({platform});'


def parse(text, model, scene, accounts, segments):
    if type(model.get('strength_clock_revision')) is not int or model['strength_clock_revision'] != REVISION:
        raise ValueError('兵力时钟原生回执版本非法')
    expected = set(scene['entities'])
    if (not isinstance(accounts, dict) or set(accounts) != expected or
            not isinstance(segments, dict) or set(segments) != expected):
        raise ValueError('兵力时钟必须绑定全部时段及期末人员总账')
    rows = {identity: [] for identity in expected}
    for line in text.splitlines():
        if not line.startswith('GTXSTRENGTH|'):
            continue
        fields = line.split('|')
        if len(fields) != 4 or fields[1] not in rows:
            raise ValueError('兵力时钟原生身份或字段非法')
        try:
            event = dict(at_ms=int(fields[2]), combat_current=int(fields[3]))
        except ValueError as exc:
            raise ValueError('兵力时钟必须保持整数人数与毫秒') from exc
        rows[fields[1]].append(event)
    prior = {u['name']: u for _, u in model['units']}
    return {identity: strength_clock.validate(
        prior[scene['entities'][identity]['name']], scene['seconds'],
        segments[identity], rows[identity], final_current=accounts[identity]['current'])
        for identity in expected}
