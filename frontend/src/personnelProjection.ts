import type {Unit} from './types';

export function personnelStrengthPct(unit:Unit):number|null{
 const p=unit.personnel,current=p?.current,committed=p?.committed;
 if(typeof current!=='number'||typeof committed!=='number'||!Number.isSafeInteger(current)||!Number.isSafeInteger(committed)||current<0||committed<=0||current>committed)return null;
 const scaled=current*10000;
 if(!Number.isSafeInteger(scaled))return null;
 let whole=Math.floor(scaled/committed);const remainder=scaled-whole*committed;
 if(remainder*2>committed||(remainder*2===committed&&whole%2===1))whole++;
 return whole/100;
}

export function unitInactive(unit:Unit):boolean{
 const current=unit.personnel?.current;
 if(Number.isSafeInteger(current)&&current!>=0)return current===0;
 const hp=unit.hp??unit['HP']??unit['health']??unit['兵力'];
 return hp!=null&&hp!==''&&typeof hp!=='boolean'&&Number.isFinite(Number(hp))&&Number(hp)<=0;
}
