"""Small explicit QA loads on sourced identities, not historical strengths."""
import copy
from gentactix import historical_initial as hi,historical_operations as ho
from tools.qa.historical_crossing_fixture import inputs as crossing_inputs

CASES={
 'LM04-jinsha1935':('红军长征-中央红军巧渡金沙江-1935.05.03至1935.05.09','column_may3_night'),
 'LM13-jinsha1936':('红军长征-红二六军团抢渡金沙江-1936.04.25至1936.04.28','regiment12_apr25_night'),
}
NOTE='QA仅10人计算载荷与估计舟艇几何，非军委纵队或红12团史实全编制；不代表完成全军分批渡江。'

def inputs(identity='LM13-jinsha1936'):
    battle,phase_id=CASES[identity];snapshot=hi.initial(battle,phase_id)['historical_initial']
    template=ho.configuration_template(snapshot);_,base=crossing_inputs();params=copy.deepcopy(base)
    phase=next(p for p in snapshot['definition']['phases'] if p['id']==phase_id)
    center=copy.deepcopy(phase['geographic_scope']['center']);lat,lng=center['lat'],center['lng']
    params['phase_id']=phase_id;params['actors']={}
    for key in template['actors']:
        actor=copy.deepcopy(next(iter(base['actors'].values())))
        actor.update(personnel=10,position={'lat':lat-.0003,'lng':lng},assumption=NOTE)
        actor['equipment']={k:0 for k in actor['equipment']}
        actor['formation'].update(fuel_liters=0,materials=0,shells=0,motorized=False)
        params['actors'][key]=actor
    params['clock'].update(start=phase['execution_window']['start'].replace('T',' '),time_step='1分钟',assumption=NOTE)
    params['area'].update(center=center,radius_km=8,terrain_factor=1,assumption=NOTE)
    for value in params['support'].values():value.update(position=center,stock=0,assumption=NOTE)
    params['facility'].update(**center,name='局部渡运计算设施（非历史桥梁）',progress=0,integrity=100)
    c=params['facility']['crossing_model']
    c.update(barrier={'a':{'lat':lat,'lng':lng-.005},'b':{'lat':lat,'lng':lng+.005}},
        banks={'a':{'lat':lat-.0003,'lng':lng},'b':{'lat':lat+.0003,'lng':lng}},assumption=NOTE)
    c['ferry']={'version':'formation-ferry-1','assumption':NOTE,'boats':[{
        'id':'qa_boat','name':'QA估计渡船','team':'red','seats':10,'equipment_work_capacity':0,
        'speed_mps':.5,'load_seconds':10,'unload_seconds':10,'initial_bank':'a','assumption':NOTE}]}
    params['rules']['required_survivors']=1
    target=copy.deepcopy(c['banks']['b'])
    params['goal'].update(objective=target,exit=target,radius_km=.02,deadline_turn=12,
        required_turns=1,required_survivors=1,description='QA载荷完成渡运后抵岸，不是全军历史目标。',assumption=NOTE)
    params['assumptions']=NOTE
    return snapshot,params
