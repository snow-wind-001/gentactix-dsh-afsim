"""A private coarse window over frozen, sourced Wanjialing identities.

It exercises the existing selected-ancestor contract without editing published
windows or historical facts. Every deployment and force amount is a QA estimate.
"""
import copy
from unittest.mock import patch

from gentactix import campaign_scope, campaign_windows, historical_initial as hi, historical_operations as ho
from tools.qa.campaign_window_fixture import inputs as window_inputs,NOTE
from tools.upgrade_wanjialing import BATTLE


def historical_parent_world():
    _,p=window_inputs();snapshot=hi.initial(BATTLE,'oct7_attack',version='1.3.0')['historical_initial']
    definition=copy.deepcopy(p['campaign_scope']['window']['definition'])
    definition.pop('parameter_estimates',None)
    definition.update(id='WJL-QA-coarse-ownership',version='1.0.0',label='仅软件QA父级归属窗口',
        start_phase_id='oct7_attack',phase_ids=[i for i in definition['phase_ids'] if i!='oct6_orders'])
    definition['bounds']['start']='1938-10-07T00:00:00';definition['bounds']['note']=NOTE
    parent='ww2.cn.army74';children={'ww2.cn.division51','ww2.cn.division58'}
    definition['units'][parent].update(representation='actor',represented_by=None,extent=NOTE)
    for identity in children:definition['units'][identity].update(representation='covered_reference',represented_by=parent,extent=NOTE)
    for sector in definition['sectors']:
        sector['unit_ids']=list(dict.fromkeys(parent if i in children else i for i in sector['unit_ids']))
    definition['milestones']=[r for r in definition['milestones'] if r['phase_id']!='oct6_orders']
    definition['limitations']=NOTE+' 此测试选择父级而未重复投入其下级；不是默认历史初态。'
    pin=dict(format=campaign_windows.FORMAT,id=definition['id'],version=definition['version'],
             definition_hash=hi.digest(definition),definition=definition)
    selected=campaign_windows.validate(snapshot,pin,frozen=True)
    actor=copy.deepcopy(p['actors']['ww2.cn.division51']);actor['personnel']=10000;actor['equipment']['transport']=20
    for identity in children:p['actors'].pop(identity)
    p['actors'][parent]=actor
    p['phase_id']=snapshot['phase_id'];p['clock']['start']=definition['bounds']['start'];p['campaign_scope'].update(window=pin,
        remainders={row['parent_id']:dict(policy='excluded_unquantified',assumption=NOTE)
                    for row in campaign_scope.coverage(snapshot,selected)})
    for field in ('arrivals','fortifications'):
        row=copy.deepcopy(p['campaign'][field]['ww2.cn.division51'])
        for identity in children:p['campaign'][field].pop(identity)
        p['campaign'][field][parent]=row
    for arrival in p['campaign']['arrivals'].values():arrival['not_before']=p['clock']['start']
    phase=next(row for row in snapshot['definition']['phases'] if row['id']==snapshot['phase_id'])
    center=copy.deepcopy(phase['geographic_scope']['center'])
    p['area'].update(center=center,radius_km=min(8,phase['geographic_scope']['radius_km']),assumption=NOTE)
    for i,row in enumerate(p['actors'].values()):row['position']={**center,'lat':center['lat']+i*.0001}
    for row in p['support'].values():row['position']=copy.deepcopy(center)
    p['facility'].update(center);p['goal'].update(objective=copy.deepcopy(center),exit=copy.deepcopy(center))
    p['campaign']['objective']['relief_regions']=[dict(center=copy.deepcopy(center),radius_km=.4)]
    with patch.object(campaign_windows,'load',return_value=definition):
        return ho.initial(snapshot,p)
