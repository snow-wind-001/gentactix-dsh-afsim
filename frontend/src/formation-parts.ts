import type {FormationPartitions,HistoricalActorParameters,PartEquipment,PartResources,Unit,WarState} from './types';

export const partEquipmentKeys=['armor','artillery','air_defense','engineer','transport'] as const;
export const partResourceKeys=['fuel_liters','spares','materials','shells','aa_rounds'] as const;
export const formationPartName=(parent:string,label:string)=>`${parent} · ${label}（计算分队）`;
const clone=<T>(value:T):T=>JSON.parse(JSON.stringify(value)) as T;

export function formationPartIssues(config:FormationPartitions|undefined,actors:Record<string,HistoricalActorParameters>):string[]{
  if(!config)return[];const issues:string[]=[];
  for(const [id,g] of Object.entries(config.groups)){
    const parent=actors[id];if(!parent){issues.push(`未知父单位 ${id}`);continue;}
    const max=config.version==='formation-partitions-2'?32:8;
    if(g.parts.length<2||g.parts.length>max)issues.push(`${id}须为2至${max}个分队`);
    if(!g.assumption.trim())issues.push(`${id}缺少划分依据`);
    if(new Set(g.parts.map(p=>p.id)).size!==g.parts.length)issues.push(`${id}分队ID重复`);
    if(g.parts.reduce((n,p)=>n+p.personnel,0)!==parent.personnel)issues.push(`${id}人员合计须为${parent.personnel}人`);
    for(const k of partEquipmentKeys)if(g.parts.reduce((n,p)=>n+p.equipment[k],0)!==parent.equipment[k])issues.push(`${id}的${k}分配不守恒`);
    for(const k of partResourceKeys)if(g.parts.reduce((n,p)=>n+p.resources[k],0)!==Number(parent.formation[k]))issues.push(`${id}的${k}库存分配不守恒`);
    for(const p of g.parts){
      if(!/^[a-z0-9_]{1,32}$/.test(p.id)||!p.label.trim()||!p.assumption.trim())issues.push(`${id}分队身份或依据未填`);
      if(!Number.isInteger(p.personnel)||p.personnel<1)issues.push(`${id}分队人数须为正整数`);
      if([...partEquipmentKeys.map(k=>p.equipment[k]),...partResourceKeys.map(k=>p.resources[k])].some(n=>!Number.isInteger(n)||n<0))issues.push(`${id}分队装备和库存须为非负整数`);
      if(!Number.isFinite(p.position.lat)||!Number.isFinite(p.position.lng)||Math.abs(p.position.lat)>90||Math.abs(p.position.lng)>180)issues.push(`${id}分队部署坐标无效`);
      if(!Number.isFinite(p.dispersion_km2)||p.dispersion_km2<.001)issues.push(`${id}分队展开面积无效`);
    }
  }
  return issues;
}

/** Initial input preview only. Neither computes a turn nor changes a checkpoint. */
export function formationPartsPreview(input:WarState,actors:Record<string,HistoricalActorParameters>,config?:FormationPartitions):WarState{
  const world=clone(input),groups:NonNullable<WarState['formation_groups']>['groups']=[];
  for(const side of ['red','blue'] as const){
    const bases=new Map<string,Unit>();
    for(const unit of world[`${side}_units`]??[]){const id=unit.historical_unit_id;if(typeof id==='string'&&!bases.has(id))bases.set(id,unit);}
    const leaves:Unit[]=[];
    for(const [id,parent] of bases){
      const p=actors[id];if(!p){leaves.push(parent);continue;}
      const name=parent.formation_part?.parent_name??parent.name??id;
      Object.assign(parent,p.position,{name,type:p.type,speed:p.speed,attack_range:p.attack_range_m,
        ground_control_radius_km:p.ground_control_radius_km,
        personnel:{committed:p.personnel,current:p.personnel,casualties:0,noncombat_losses:0},logistics:clone(p.logistics)});
      delete parent.formation_part;delete parent.calculation_unit_id;delete parent.crossing;
      if(parent.formation)Object.assign(parent.formation,p.formation);
      for(const equipment of parent.equipment??[]){const k=equipment.category as keyof PartEquipment;Object.assign(equipment,{committed:p.equipment[k],operational:p.equipment[k],damaged:0,destroyed:0});}
      const group=config?.groups[id];if(!group){leaves.push(parent);continue;}
      const names:string[]=[];
      for(const part of group.parts){
        const leaf=clone(parent);leaf.name=formationPartName(name,part.label);leaf.calculation_unit_id=`${id}::${part.id}`;
        leaf.formation_part={version:config!.version,group_id:id,part_id:part.id,numerator:part.personnel,denominator:p.personnel,parent_name:name,assumption:part.assumption};
        Object.assign(leaf,part.position,{personnel:{committed:part.personnel,current:part.personnel,casualties:0,noncombat_losses:0}});
        if(leaf.formation)Object.assign(leaf.formation,part.resources,{dispersion_km2:part.dispersion_km2});
        for(const e of leaf.equipment??[]){const k=e.category as keyof PartEquipment;Object.assign(e,{committed:part.equipment[k],operational:part.equipment[k]});}
        names.push(leaf.name);leaves.push(leaf);
      }
      groups.push({id,historical_unit_id:id,name,team:side,committed:p.personnel,equipment:clone(p.equipment),
        resources:Object.fromEntries(partResourceKeys.map(k=>[k,Number(p.formation[k])])) as PartResources,members:names,assumption:group.assumption});
    }
    world[`${side}_units`]=leaves;
  }
  if(groups.length)world.formation_groups={version:config!.version,groups};else delete world.formation_groups;
  return world;
}

export function formationGroupSummaries(world:WarState){
  const units=[...(world.red_units??[]),...(world.blue_units??[])];
  return(world.formation_groups?.groups??[]).map(group=>{
    const parts=units.filter(u=>group.members.includes(u.name??''));
    return{...group,parts,current:parts.reduce((n,u)=>n+(u.personnel?.current??0),0),casualties:parts.reduce((n,u)=>n+(u.personnel?.casualties??0),0),
      food:parts.reduce((n,u)=>n+(u.logistics?.food??0)*(u.formation_part!.numerator/u.formation_part!.denominator),0),
      ammo:parts.reduce((n,u)=>n+(u.logistics?.ammo??0)*(u.formation_part!.numerator/u.formation_part!.denominator),0)};
  });
}
