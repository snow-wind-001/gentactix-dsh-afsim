"""Explicit exploratory inputs within window priors; not historical strengths."""
import copy
from gentactix import historical_operations as ho,campaign_windows as cw
from tools.qa.campaign_window_fixture import inputs as previous_inputs

NOTE=('万家岭6—10日计算示例；人数、装备、初始位置、到场、工事及保障均为显式先验，'
      '未经历史标定。单仓／平面通路、缺航空和真正场外仍限制历史解释。')


def inputs():
    s,base=previous_inputs();window=cw.pin('WJL-oct6-10','1.1.0')
    p=ho.configuration_template(s,'campaign',window=window,termination_mode='objectives')
    estimates=window['definition']['parameter_estimates'];center=estimates['area']['center']
    for key in ('rules','support','facility','goal'):p[key]=copy.deepcopy(base[key])
    p['area'].update(center=copy.deepcopy(center),radius_km=40,terrain_factor=1.5,assumption=NOTE)
    p['rules'].update(motorized=False,convoy_km_per_turn=8)
    p['clock'].update(time_step='1小时',assumption=NOTE)
    p['campaign_scope']['assumption']=NOTE
    for row in p['campaign_scope']['remainders'].values():row.update(policy='excluded_unquantified',assumption=NOTE+' 未核余部不投入。')
    prototype=next(iter(base['actors'].values()))
    for n,(identity,prior) in enumerate(estimates['actors'].items()):
        a=copy.deepcopy(prototype);support=prior['role']=='support'
        a['personnel']=(prior['personnel']['minimum']+prior['personnel']['maximum'])//2
        a['position']=copy.deepcopy(prior['position']['center']);a['position']['lat']+=(n%3)*.001
        a.update(type='炮兵' if support else '步兵',speed=2.5 if support else 3,
                 attack_range_m=300 if support else 800,ground_control_radius_km=.2,assumption=NOTE+' '+prior['assumption'])
        a['equipment']=dict(armor=0,artillery=prior['equipment']['artillery']['minimum'] if support else 2,
            air_defense=0,engineer=2 if not support else 0,transport=12 if not support else 6)
        a['formation'].update(role=prior['role'],motorized=False,shells=a['equipment']['artillery']*150,
            fuel_liters=0,signal=80,fatigue=10,dispersion_km2=.2 if support else 4)
        a['logistics'].update(food=80,ammo=80)
        if identity=='ww2.jp.division106':a['logistics'].update(food=15,ammo=25)
        p['actors'][identity]=a
        p['campaign']['arrivals'][identity].update(not_before=p['clock']['start'],assumption=NOTE+' 示例假设开局在估计区域可受令，不等于史实同时在场；不锁定后续历史调令。')
        p['campaign']['fortifications'][identity].update(integrity=15 if identity.startswith('ww2.jp.') else 5,degradation_per_shell=.05,assumption=NOTE)
    for team,row in p['support'].items():
        row.update(position={'lat':center['lat']+(-.08 if team=='red' else .02),'lng':center['lng']},stock=5000 if team=='red' else 800,assumption=NOTE)
        row['inventory'].update(shells=5000,materials=500,spares=100,fuel_liters=0,aa_rounds=0)
    p['facility'].update(center)
    p['goal'].update(objective=copy.deepcopy(center),exit={'lat':center['lat'],'lng':center['lng']-.10},
        radius_km=3,deadline_turn=120,required_turns=2,required_survivors=1,termination_mode='objectives',description=NOTE,assumption=NOTE)
    p['rules']['required_survivors']=1
    p['campaign']['surrender'].update(enabled=False,range_m=100,suppression_threshold=90,ammo_threshold=0,assumption=NOTE)
    p['campaign']['objective'].update(relief_regions=[{'center':{'lat':center['lat']-.10,'lng':center['lng']-.10},'radius_km':2}],min_force_fraction=.4,assumption=NOTE)
    p['campaign']['assumption']=NOTE
    p['support_dynamics']=dict(version='time-sustainment-1',food_work_per_hour=.7,move_factor=1.5,
        shortage_fatigue_per_hour=1,recovery_hours_per_fed_hour=.5,incapacity_after_hours=48,
        incapacity_fraction_per_hour=.0005,assumption=NOTE+' 100工作量约143待命小时，仅为编组覆盖先验，不将出发时六日份视为6日开局尚存六日粮。')
    for node in p['campaign_plan']['nodes']:
        node.update(hold_seconds=3600,assumption=NOTE)
        condition=node['condition']
        if condition['kind']=='preserve':condition['minimum_fraction']=.4
        else:
            point=copy.deepcopy(center);radius=3
            if node['id']=='red_block':point={'lat':center['lat']-.10,'lng':center['lng']-.10};radius=2
            elif node['id']=='blue_exit':point={'lat':center['lat'],'lng':center['lng']-.10};radius=2
            condition.update(region={'center':point,'radius_km':radius},minimum_personnel=500)
    p['campaign_plan']['assumption']=NOTE+'双边目标是声明的代理条件，不证明真实解围。'
    p['assumptions']=NOTE
    return s,p
