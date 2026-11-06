import type { Unit, WarState } from './types';

export interface WeaponLimit { min_range_m:number; max_range_m:number }

// Render the same declared inputs used by native execution, not a new solver.
export function weaponLimits(world:WarState,unit:Unit):Record<string,WeaponLimit> {
 const cfg=world.mission?.definition.combined_rules;
 if(!cfg)return {};
 const result:Record<string,WeaponLimit>={};
 const direct=Number(unit.attack_range);
 if(Number.isFinite(direct))result.fire={min_range_m:0,max_range_m:direct};
 const issued=(category:string)=>unit.equipment?.some(e=>e.category===category&&(e.committed??e.operational)>0);
 if(issued('artillery'))for(const key of ['bombard','suppress'])
  result[key]={min_range_m:cfg.artillery_min_range_m??0,max_range_m:cfg.artillery_range_m};
 if(issued('air_defense'))result.air_defense={min_range_m:0,max_range_m:cfg.aa_range_m};
 return result;
}
