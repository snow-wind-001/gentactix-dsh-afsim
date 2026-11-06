/** Complete read-only leaf projection; original values stay in the snapshot. */
import type {CommandUnit,Unit,WarState} from './types';
export interface ParameterRow {path:string;label:string;value:unknown}
const labels:Record<string,string>={unit:'单位',command:'指挥观测',rules:'共享裁决规则',profile:'火力参照',supply_node:'绑定补给节点',personnel:'人员',equipment:'装备',formation:'编组状态',logistics:'随队物资',name:'名称',type:'兵种',current:'现有人员',committed:'累计投入',casualties:'累计战斗减员',noncombat_losses:'非战斗损失',killed:'阵亡',wounded:'负伤',missing:'失踪',captured:'被俘',unclassified_casualties:'未分类减员',category:'装备类别',operational:'可用',damaged:'受损',destroyed:'损毁',food:'粮食工作量',ammo:'通用弹药工作量',fuel_liters:'燃油（升）',shells:'炮弹（发）',aa_rounds:'防空弹药（发）',spares:'备件（件）',materials:'工程耗材（包）',fatigue:'疲劳',suppression:'压制',entrenchment:'工事',protection:'防护系数',dispersion_km2:'展开面积（km²）',signal:'联络状态',intel_age_min:'情报时效（分钟）',intel_confidence:'情报可信度',reload_remaining_s:'装填余时（秒）',reload_remaining:'旧装填周期',role:'编组角色',motorized:'摩托化',lat:'纬度（度）',lng:'经度（度）',speed:'配置速度（km/h）',attack_range:'直射射程（米）',ground_control_radius_km:'地面控制半径（km）',hp:'状态指数',morale:'士气',supply:'补给指数',supply_node_id:'补给节点',source:'来源说明',calculation_source:'计算来源',parameter_sources:'参数来源',historical_unit_id:'历史单位ID',exercise_unit_id:'演习单位ID',calculation_unit_id:'计算身份',parent_id:'行政上级ID',echelon:'层级',historical_evidence:'史料定位',historical_reference:'历史参考',last_execution:'最近原生执行回执',last_density_sample:'最近密度采样',turn:'记录回合',version:'版本',damage_load:'装备毁伤余量',combat_damage_remainder:'人员毁伤余量',fatality_remainder:'阵亡分类余量',crossing:'渡运任务',sustainment:'保障过程',runtime_allocation:'运行中重编归属',source_historical_unit_id:'派生来源单位',formation_part:'互斥计算分队',assumption:'估计依据',scope:'适用范围',position:'位置'};
Object.assign(labels,{suppression_carry_ticks:'压制余量（固定刻度）',suppression_state:'连续压制精度',units_per_point:'每压制点刻度数',gain_quantum:'来袭量化精度',clock_resolution_ms:'时钟精度（毫秒）'});
Object.assign(labels,{fuel_credit_microliters:'燃油小数余量（微升）',fatigue_carry_ticks:'疲劳小数余量（百万分之一分）',motion_task:'持续移动任务',wait_remaining_ms:'通信等待余时（毫秒）',feedback_remaining_ms:'运动反馈余时（毫秒）'});
Object.assign(labels,{campaign_actor:'战役过程状态',active:'已到场可参与',base_entrenchment:'工事基准',fortification_integrity:'工事完整度（%）',base_protection:'原始防护系数',captured_this_turn:'本轮被俘人数',fortification_components:'工事分组参数'});

/** Match the selected live name; missing state stays missing, without fallback. */
export function unitParameterContext(world:WarState,unit:Unit|null,command?:CommandUnit){
 return {unit,rules:world.mission?.definition.combined_rules,profile:world.combat_reference,
  supply_node:world.supply_nodes?.find(node=>node.id===unit?.supply_node_id),command,
  campaign_actor:unit?.name?world.campaign?.actors[unit.name]:undefined};
}

export function physicalFormationValues(value:unknown):{fuel_liters:number|null;fatigue:number|null;precision:'physical'|'legacy'|'unknown'}{
 const unknown={fuel_liters:null,fatigue:null,precision:'unknown' as const};
 if(!value||typeof value!=='object')return unknown;
 const f=value as Record<string,unknown>;
 const finite=(v:unknown):v is number=>typeof v==='number'&&Number.isFinite(v);
 if(!('fuel_credit_microliters'in f)&&!('fatigue_carry_ticks'in f))return {
  fuel_liters:finite(f.fuel_liters)&&f.fuel_liters>=0?f.fuel_liters:null,
  fatigue:finite(f.fatigue)&&f.fatigue>=0&&f.fatigue<=100?f.fatigue:null,precision:'legacy'};
 const integer=(v:unknown,max:number):v is number=>finite(v)&&Number.isInteger(v)&&v>=0&&v<=max;
 if(!integer(f.fuel_liters,10000000)||!integer(f.fatigue,100)||
    !integer(f.fuel_credit_microliters,999999)||!integer(f.fatigue_carry_ticks,999999)||
    f.fatigue===100&&f.fatigue_carry_ticks!==0)return unknown;
 return {fuel_liters:f.fuel_liters+f.fuel_credit_microliters/1000000,
  fatigue:f.fatigue+f.fatigue_carry_ticks/1000000,precision:'physical'};
}
export function parameterLabel(path:string):string{
 return path.replace(/\[(\d+)\]/g,'.$1').split('.').map(key=>/^\d+$/.test(key)?`第${Number(key)+1}项`:Object.hasOwn(labels,key)?labels[key]:key).join(' › ');
}
export function parameterValue(value:unknown):string{
 if(value===null||value===undefined)return '未记录';
 if(value==='')return '未填写';if(typeof value==='boolean')return value?'是':'否';
 if(typeof value==='number')return Number.isFinite(value)?String(value):'不可用（非有限数）';
 return typeof value==='object'?JSON.stringify(value):String(value);
}
export function parameterRows(value:unknown):ParameterRow[]{
 const rows:ParameterRow[]=[],ancestors=new WeakSet<object>();
 const visit=(item:unknown,path:string)=>{
  if(item!==null&&typeof item==='object'){
   if(ancestors.has(item)){rows.push({path,label:parameterLabel(path),value:'循环引用'});return;}
   const entries=Object.entries(item);if(entries.length){ancestors.add(item);for(const[key,next]of entries)visit(next,Array.isArray(item)?`${path}[${key}]`:path?`${path}.${key}`:key);ancestors.delete(item);return;}
  }
  rows.push({path,label:parameterLabel(path),value:item});
 };visit(value,'');return rows;
}
export const filterParameters=(rows:ParameterRow[],query:string):ParameterRow[]=>{
 const q=query.trim().toLocaleLowerCase();return q?rows.filter(row=>`${row.path} ${row.label} ${parameterValue(row.value)}`.toLocaleLowerCase().includes(q)):rows;
};

/** Cumulative equipment unavailability, never infer missing counts as zero. */
export function equipmentUnavailablePct(entry:{committed?:unknown;operational?:unknown;damaged?:unknown;destroyed?:unknown}):number|null{
 const counts=[entry.committed,entry.operational,entry.damaged,entry.destroyed];
 if(!counts.every(n=>typeof n==='number'&&Number.isSafeInteger(n)&&n>=0))return null;
 const [total,available,damaged,destroyed]=counts as number[];
 if(!total||available!+damaged!+destroyed!==total)return null;
 return (damaged!+destroyed!)*100/total;
}
