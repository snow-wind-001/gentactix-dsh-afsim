"""Source-backed identities with explicit synthetic calculation parameters for QA."""
import copy
from gentactix import missions


def mixed_air_capture():
    from tools.qa.historical_air_fixture import inputs
    from gentactix import historical_operations as ho,historical_initial as hi,campaign,formation_parts
    from verify_dsh_aviation import result as air_result
    source,p=inputs();phase=next(r for r in source['definition']['phases'] if r['id']==source['phase_id'])
    phase['process_requirements']=[dict(kind='combined_operation',scope='QA非史实',evidence=copy.deepcopy(phase['evidence']))]
    phase['execution_window']=dict(start='1945-04-25T06:00',end='1945-04-25T09:00',kind='model_scope_limit',note='QA',evidence=copy.deepcopy(phase['evidence']))
    source['definition_hash']=hi.digest(source['definition'])
    cfg=campaign.template(source,list(p['actors']));cfg['assumption']='QA'
    for row in cfg['arrivals'].values():row.update(not_before='1945-04-25T06:00',assumption='QA')
    for row in cfg['fortifications'].values():row.update(integrity=0,degradation_per_shell=.5,assumption='QA')
    cfg['surrender'].update(enabled=True,range_m=1000,suppression_threshold=80,ammo_threshold=0,assumption='QA');p['campaign']=cfg
    p['goal']['profile']='assault';p['rules']['goal_profile']='assault'
    cfg['objective'].update(relief_regions=[dict(center=copy.deepcopy(p['goal']['objective']),radius_km=.4)],min_force_fraction=.1,assumption='QA')
    p['actors']['ww2.jp.division116']['formation']['suppression']=90
    u=p['actors']['ww2.cn.division57'];resources=('fuel_liters','spares','materials','shells','aa_rounds')
    p['partitions']=dict(version='formation-partitions-1',groups={'ww2.cn.division57':dict(assumption='QA',parts=[
        dict(id=x,label=x,personnel=u['personnel']//2,position=copy.deepcopy(u['position']),
            equipment={k:n//2 for k,n in u['equipment'].items()},resources={k:u['formation'][k]//2 for k in resources},
            dispersion_km2=u['formation']['dispersion_km2'],assumption='QA') for x in ('a','b')])})
    world=ho.initial(source,p);value=air_result(world);target=world['blue_units'][0];actor=world['red_units'][1]
    value['orders'][1]=dict(unit=actor['name'],action='capture',target=target['name'])
    index={u['name']:u for _,u in missions.units(world)}
    for row in value['resource_ledger']['units']:row['food_spent']*=formation_parts.scale(index[row['unit']])
    next(r for r in value['unit_updates'] if r['unit']==target['name'])['personnel']={
        'current':target['personnel']['current']-14,'casualties':target['personnel']['casualties']+14}
    value['aviation']['missions'][0]['personnel_effect']=4
    value['campaign']=dict(actors={name:{k:copy.deepcopy(row[k]) for k in
        ('active','fortification_integrity','base_entrenchment','captured_this_turn')} for name,row in world['campaign']['actors'].items()})
    value['campaign']['actors'][target['name']]['captured_this_turn']=10
    next(r for r in value['unit_updates'] if r['unit']==target['name'])['personnel']['captured']=10
    requester=world['red_units'][0]
    value['engagements']=[dict(attacker=requester['name'],attacker_team='red',attacker_pos=[requester['lat'],requester['lng']],
        target=target['name'],lat=target['lat'],lng=target['lng'],weapon_action='air_support')]
    return world,value,target,actor
