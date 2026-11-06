import data from '../../gentactix/military_symbols.json';
import { classifyUnit } from './unitTypes';
import type { Unit } from './types';
import {unitInactive} from './personnelProjection';
export interface MilitarySymbol {id:string;label:string;category:string;geometry:'point'|'line'|'area';path:string;anchor:number[];source_ids:string[];meaning:string;design:string}
export const militarySymbols=data.symbols as MilitarySymbol[];
export const symbolById=(id:string)=>militarySymbols.find(x=>x.id===id)||militarySymbols[0];
export const teamColor=(team:string)=>({red:'#ef8882',blue:'#8abcf3',neutral:'#e7d6a6'}[team]||'#e7d6a6');
const escape=(v:unknown)=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]!));
export function militarySvg(id:string,team='neutral',inactive=false){
 const s=symbolById(id);
 return `<svg class="military-symbol" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="36" height="36" aria-hidden="true"><path d="${escape(s.path)}" fill="none" stroke="${teamColor(team)}" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round"/>${inactive?'<path d="M4 4l16 16M20 4 4 20" fill="none" stroke="#d5dce0" stroke-width="1.7"/>':''}</svg>`;
}
export function unitSymbolId(unit:Unit):string{
 const kind=String(unit.type??unit['类型']??unit['兵种']??unit.unit_type??'').toLowerCase();
 const profile=classifyUnit(kind);
 const role=unit.formation?.role;
 const count=(key:string)=>Array.isArray(unit.equipment)?unit.equipment.find(e=>e.category===key)?.operational??0:0;
 if(role==='support'&&count('artillery')>0)return 'artillery';
 if(role==='armor'&&count('armor')>0)return 'armor';
 const mapping:Record<string,string>=data.unit_profile_symbols;
 if(profile&&mapping[profile.id])return mapping[profile.id];
 for(const [words,id] of [[['防空','anti-air','air defense'],'air-defense'],[['炮','artillery'],'artillery'],[['舰','船','naval','ship'],'naval'],[['航空','飞机','fighter','aircraft'],'aircraft'],[['骑兵','cavalry'],'cavalry'],[['坦克','装甲','tank','armor'],'armor'],[['步兵','陆战','infantry','marine'],'infantry']] as [string[],string][])if(words.some(k=>kind.includes(k)))return id;
 return 'unknown';
}
export function unitMilitaryHtml(unit:Unit,team:string,override?:string){
 const id=override&&militarySymbols.some(x=>x.id===override&&x.geometry==='point')?override:unitSymbolId(unit);
 const inactive=unitInactive(unit);
 const name=unit.name??unit['名称']??unit['单位名称']??unit['部队名称']??unit.unit_name??'未知单位';
 return `<div class="military-unit ${inactive?'unit-inactive':'unit-active'}">${militarySvg(id,team,inactive)}<span class="unit-name">${escape(name)}${inactive?' · 已失能':''}</span></div>`;
}
