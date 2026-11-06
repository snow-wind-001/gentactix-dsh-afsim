"""Explicit numerical QA inputs over the new sourced phases, never a seed in production."""
import copy
from datetime import datetime

from gentactix import historical_initial as hi, historical_operations as ho, combined_arms

NOTE='软件QA估计；本地投入、五类装备、库存、部署与效能非史实实到量，不由战果反推兵力，不强制历史胜负。'


def inputs(profile_id,phase_id=None):
    row=next(r for r in hi.catalog() if r['profile_id']==profile_id)
    definition=hi.definition(row['battle'])
    phase=next(p for p in definition['phases'] if p['id']==phase_id) if phase_id else definition['phases'][1]
    snapshot=hi.initial(row['battle'],phase['id'])['historical_initial']
    values=ho.configuration_template(snapshot);center=copy.deepcopy(phase['geographic_scope']['center'])
    by_id={u['id']:u for u in definition['units']}
    indices={'red':0,'blue':0}
    for identity,actor in values['actors'].items():
        source=by_id[identity];team=source['team'];i=indices[team];indices[team]+=1
        artillery=source['role']=='support';scout='recon_squad' in identity
        count=12 if scout else 135 if 'koyangdae_garrison' in identity else 250 if artillery else 500 if '营' in source['echelon'] else 1600 if '团' in source['echelon'] else 4500
        equipment={'armor':0,'artillery':4 if artillery else 0,'air_defense':0,'engineer':0,'transport':4 if team=='blue' else 0}
        actor.update(personnel=count,type='侦察' if scout else '炮兵' if artillery else '步兵',speed=3,
            attack_range_m=800 if artillery else 1000,ground_control_radius_km=.25,
            position={'lat':center['lat']+(-1 if team=='red' else 1)*(.0025 if not artillery else .015),
                      'lng':center['lng']+i*.0015},equipment=equipment,logistics={'food':80,'ammo':80},
            formation={'role':'support' if artillery else 'infantry','motorized':team=='blue',
                'fatigue':10,'suppression':0,'entrenchment':15,'dispersion_km2':.05 if scout else 1,
                'protection':.15,'fuel_liters':1000 if team=='blue' else 0,'spares':4,'materials':4,
                'shells':240 if artillery else 0,'aa_rounds':0,'reload_remaining':0,
                'intel_age_min':0,'intel_confidence':80,'signal':90},assumption=NOTE)
    available=(datetime.fromisoformat(phase['execution_window']['end'])-datetime.fromisoformat(phase['execution_window']['start'])).total_seconds()
    deadline=min(8,int(available//1800))
    defending=profile_id in ('KW02-second','KW06-autumn1951','KW08-sangganling')
    profile='delay' if defending else 'assault'
    values.update(clock={'start':phase['execution_window']['start'].replace('T',' '),'time_step':'30分钟','assumption':NOTE},
        area={'center':center,'radius_km':min(3,phase['geographic_scope']['radius_km']/2),'terrain_factor':1.5,'assumption':NOTE},
        assumptions=NOTE)
    values['rules']={**copy.deepcopy(combined_arms.RULES),'era':'korea','air_support':False,'motorized':True,
        'goal_profile':profile,'required_survivors':1,'convoy_km_per_turn':3,'bridge_enabled':False}
    values['support']={team:{'position':{'lat':center['lat']+sign*.015,'lng':center['lng']},'stock':300,
        'inventory':{'fuel_liters':3000,'spares':30,'materials':30,'shells':3000,'aa_rounds':0},'assumption':NOTE}
        for team,sign in (('red',-1),('blue',1))}
    values['facility']={'id':'calculation-hub','name':'计算汇总点（非史实桥梁）',**center,
        'progress':0,'integrity':0,'materials':0,'capacity':0,'used':0}
    values['goal']={'profile':profile,'objective':center,'exit':{'lat':center['lat']-.02,'lng':center['lng']},
        'radius_km':.2,'deadline_turn':deadline,'required_turns':2,'required_survivors':1,
        'description':'局部软件验收目标，不代表全战役胜负或必达战果。','assumption':NOTE}
    return snapshot,values
