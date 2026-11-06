import type {MapPoint,Snapshot} from './types';
import {toFloat} from './tactical';

export interface MapUnitEntry {
 id:string;name:string;team:'red'|'blue';source_id:string;echelon:string;position:MapPoint|null;status:string;
}
export interface ProjectedUnit {id:string;x:number;y:number}
export interface UnitOverlapGroup {ids:string[];x:number;y:number}

export function mapUnitEntries(snap:Snapshot|null):MapUnitEntry[]{
 const world=snap?.war_state;if(!world)return [];
 const registered=new Map((snap?.plotting?.units??[]).map(r=>[JSON.stringify([r.team,r.name]),r.id]));
 const participation=new Map(Object.values(world.unit_participation?.actors??{}).map(r=>[JSON.stringify([r.team,r.name]),r.status]));
 const labels:Record<string,string>={reserve:'后方待命',returning:'返场途中',withdrawing:'退出途中',staging:'待入场',deployed:'在场作战',offmap:'场外待命'};
 return (['red','blue'] as const).flatMap(team=>(world[`${team}_units`]??[]).map(unit=>{
  const name=String(unit.name??''),key=JSON.stringify([team,name]),lat=toFloat(unit.lat),lng=toFloat(unit.lng);
  const position=lat===null||lng===null?null:{lat,lng};
  const staged=world.campaign?.actors[name]?.active===false;
  return {id:registered.get(key)??JSON.stringify([team,unit.calculation_unit_id??unit.exercise_unit_id??unit.historical_unit_id??name]),
   name,team,source_id:String(unit.historical_unit_id??unit.exercise_unit_id??''),echelon:String(unit.echelon??''),position,
   status:!position?'部署未知':staged?'待入场 · 计算部署':labels[participation.get(key)??'']??'已定位'};
 }));
}

export function unitOverlapGroups(points:ProjectedUnit[],width:number,height:number):UnitOverlapGroup[]{
 const half=18,rows=points.filter(p=>Number.isFinite(p.x)&&Number.isFinite(p.y)&&p.x>=-half&&p.x<=width+half&&p.y>=-half&&p.y<=height+half)
  .slice().sort((a,b)=>a.id<b.id?-1:a.id>b.id?1:0);
 const parent=rows.map((_,i)=>i);
 const root=(i:number):number=>{while(parent[i]!==i){parent[i]=parent[parent[i]];i=parent[i];}return i;};
 for(let i=0;i<rows.length;i++)for(let j=0;j<i;j++){
  if(Math.abs(rows[i].x-rows[j].x)<=36&&Math.abs(rows[i].y-rows[j].y)<=36)parent[root(i)]=root(j);
 }
 const groups=new Map<number,ProjectedUnit[]>();
 rows.forEach((r,i)=>{const key=root(i);if(!groups.has(key))groups.set(key,[]);groups.get(key)!.push(r);});
 return [...groups.values()].map(g=>({ids:g.map(r=>r.id),x:Math.min(width-44,Math.max(20,Math.max(...g.map(r=>r.x))+21)),
  y:Math.min(height-20,Math.max(20,Math.min(...g.map(r=>r.y))-15))}));
}
