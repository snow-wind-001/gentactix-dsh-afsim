"""Native construction-work component; not yet a public whole-world executor.

These hooks are for isolated integration verification. They do not replace the
live combined model's stock or fortification fields. Production must bind the
same physical balances, account for combat and register both effect backends
before a configuration can enable the new version.
"""
import copy
import hashlib
import json

from gentactix import fortification_work as work

FIELDS = ('elapsed_ms','waited_ms','available_ms','work_added','packets_reserved',
          'discarded_numerator','cap_excess_micro_work','base_ticks','point_remainder',
          'work_remainder','materials','material_credit_work','wait_remaining_ms')


def _get(platform, field):
    return platform+'.AuxDataDouble("gtx_ft_'+field+'")'


def _put(platform, field, value):
    # WSF overload selection fixes the AuxData type at first assignment.
    # Later arithmetic writes doubles, so seed numeric literals as doubles too.
    literal=str(value)+'.0' if type(value) is int else str(value)
    return platform+'.SetAuxData("gtx_ft_'+field+'",'+literal+');'


def functions():
    """WSF owns work production, material reservation and entrenchment effects."""
    g=lambda key:_get('p',key)
    lines=['script void GtxFortificationWork(WsfPlatform p, double elapsed)',
           f' double waited=Math.Min(elapsed,{g("waiting")});',
           ' double available=0;',
           f' if ({g("enabled")}>0) {{ available=elapsed-waited; }}',
           f' double raw={g("rate")}*{g("current")}*available+{g("work_remainder")};',
           f' if ({g("enabled")}<1 || {g("base_ticks")}>={work.CAP}) {{ raw={g("work_remainder")}; }}',
           f' double packet={g("packet_points")}*{g("root_committed")};',
           f' double stock={g("materials")}*packet+{g("material_credit_work")};',
           f' double capacity=Math.Ceil((({work.CAP}-{g("base_ticks")})*{g("committed")}-{g("point_remainder")})/{work.SCALE});',
           f' double desired=Math.Floor(raw/{work.HOUR_MS});',
           ' double added=Math.Min(desired,Math.Min(stock,capacity));',
           f' double numerator={g("base_ticks")}*{g("committed")}+{g("point_remainder")}+added*{work.SCALE};',
           f' double capped=Math.Min(numerator,{work.CAP}*{g("committed")});',
           f' double base=Math.Floor(capped/{g("committed")});',
           f' double pointRemainder=capped-base*{g("committed")};',
           ' double remainder=0;',
           f' if (added==desired && base<{work.CAP}) {{ remainder=raw-desired*{work.HOUR_MS}; }}',
           f' double reserved=Math.Max(0,Math.Ceil((added-{g("material_credit_work")})/packet));',
           f' double credit={g("material_credit_work")}+reserved*packet-added;',
           _put('p','elapsed_ms','elapsed'),_put('p','waited_ms','waited'),
           _put('p','available_ms','available'),_put('p','work_added','added'),
           _put('p','packets_reserved','reserved'),
           _put('p','discarded_numerator',f'raw-added*{work.HOUR_MS}-remainder'),
           _put('p','cap_excess_micro_work','numerator-capped'),
           _put('p','base_ticks','base'),_put('p','point_remainder','pointRemainder'),
           _put('p','work_remainder','remainder'),
           _put('p','materials',g('materials')+'-reserved'),
           _put('p','material_credit_work','credit'),
           _put('p','wait_remaining_ms',g('waiting')+'-waited'),'end_script']
    return '\n'.join(lines)


def compile_component(controls, elapsed_ms):
    """Bind explicit component inputs; no world/config migration or live writes."""
    work._integer(elapsed_ms,0,work.MAX_ELAPSED_MS,'施工跨度毫秒')
    if not isinstance(controls,list) or not controls or len(controls)>512:
        raise ValueError('施工组件需要1至512项明确实体输入')
    identities=[]
    for control in controls:
        work.validate_control(control);identities.append(control['entity_id'])
        if (control['configuration']['gain_points_per_hour']*control['current']*elapsed_ms
                +control['state']['work_remainder']>work.MAX_EXACT_INTEGER):
            raise ValueError('施工时间乘积超过Native整数精度；须明确分段执行')
    if len(identities)!=len(set(identities)):
        raise ValueError('施工组件身份重复')
    model=dict(version=work.VERSION,controls=copy.deepcopy(controls),elapsed_ms=elapsed_ms)
    model['binding_digest']=hashlib.sha256(json.dumps(model,ensure_ascii=False,sort_keys=True,
                                                    separators=(',',':')).encode()).hexdigest()
    setup=[];finish=[]
    for index,control in enumerate(controls):
        platform='ftUnit'+str(index);state=control['state'];cfg=control['configuration']
        waiting=(state['wait_remaining_ms'] if state['intent_id']==control['intent_id']
                 else control['command_delay_ms']) if control['fortify'] else 0
        setup.append(f' WsfPlatform {platform}=WsfSimulation.FindPlatform("{control["entity_id"]}");')
        values={**{k:v for k,v in state.items() if k not in ('version','root_id','intent_id','wait_remaining_ms')},
                'enabled':int(control['fortify']),'current':control['current'],
                'waiting':waiting,'rate':cfg['gain_points_per_hour'],
                'packet_points':cfg['material_points_per_packet']}
        setup.extend(_put(platform,key,value) for key,value in values.items())
        finish.append(f' WsfPlatform {platform}=WsfSimulation.FindPlatform("{control["entity_id"]}");')
        finish.append(f' GtxFortificationWork({platform},{elapsed_ms});')
        fields=',"|",'.join('Format.Fixed('+_get(platform,key)+',0)' for key in FIELDS)
        finish.append(f' writeln("GTXFT|{control["entity_id"]}|",{fields});')
    finish.append(f' writeln("GTXFTMETA|{model["binding_digest"]}|{elapsed_ms}|{len(controls)}");')
    return dict(functions=functions(),setup_lines=setup,receipt_lines=finish,model=model)


def parse(text, model):
    if '***** ERROR:' in text or 'GTXERROR|' in text:
        raise ValueError('Native施工脚本报告错误，不能接纳看似有效的数值回执')
    # Recreate the binding rather than trusting a copied digest on mutable input.
    expected=compile_component(model['controls'],model['elapsed_ms'])['model']
    if model!=expected:
        raise ValueError('施工组件输入与冻结摘要不一致')
    controls={r['entity_id']:r for r in model['controls']};rows={};meta=[]
    for line in text.splitlines():
        if line.startswith('GTXFTMETA|'):
            meta.append(line)
        elif line.startswith('GTXFT|'):
            parts=line.split('|')
            if len(parts)!=2+len(FIELDS) or parts[1] not in controls or parts[1] in rows:
                raise ValueError('施工原生回执身份、数量或字段非法')
            try:
                values=dict(zip(FIELDS,(int(value) for value in parts[2:])))
            except ValueError as exc:
                raise ValueError('施工原生回执须保持整数工作量') from exc
            control=controls[parts[1]]
            if values['elapsed_ms']!=model['elapsed_ms']:
                raise ValueError('施工组件跨度不一致')
            after=copy.deepcopy(control['state'])
            after.update({k:values[k] for k in ('base_ticks','point_remainder','work_remainder',
                'materials','material_credit_work','wait_remaining_ms')},intent_id=control['intent_id'])
            row=dict(version=work.RECEIPT_VERSION,entity_id=parts[1],
                **{k:values[k] for k in FIELDS[:7]},after=after)
            work.check_transition(control,row);rows[parts[1]]=row
    marker=f'GTXFTMETA|{model["binding_digest"]}|{model["elapsed_ms"]}|{len(controls)}'
    if meta!=[marker] or set(rows)!=set(controls):
        raise ValueError('施工组件缺少完整或正确绑定的原生回执')
    return rows
