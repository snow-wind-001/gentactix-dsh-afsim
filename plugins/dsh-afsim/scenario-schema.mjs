/** Native model-facing guidance; authoritative scope/fact checks stay in Python. */
const number={type:'number'},integer={type:'integer',minimum:0},text={type:'string'};
const shape=properties=>({type:'object',properties,required:Object.keys(properties),additionalProperties:false});
const point=shape({lat:number,lng:number});
const inventory=shape({fuel_liters:integer,spares:integer,materials:integer,shells:integer,aa_rounds:integer});
const crossing=shape({version:{type:'string',enum:['formation-crossing-1']},barrier:shape({a:point,b:point}),banks:shape({a:point,b:point}),
  throughput_work_per_hour:number,equipment_work:shape({armor:number,artillery:number,air_defense:number,engineer:number,transport:number}),
  build_progress_per_engineer_hour:number,supply_work_per_unit:number,assumption:text});
crossing.properties.ferry=shape({version:{type:'string',enum:['formation-ferry-1']},assumption:text,
  boats:{type:'array',minItems:1,maxItems:8,items:shape({id:text,name:text,team:{type:'string',enum:['red','blue']},
    seats:{type:'integer',minimum:1,maximum:10000},equipment_work_capacity:number,speed_mps:number,
    load_seconds:number,unload_seconds:number,initial_bank:{type:'string',enum:['a','b']},assumption:text})}});
const facility=shape({id:text,name:text,lat:number,lng:number,progress:integer,integrity:integer,materials:integer,capacity:integer,used:integer});
facility.properties.crossing_model=crossing; // Optional; old frozen configurations remain valid.
const goal=shape({profile:{type:'string',enum:['assault','delay','breakout','crossing','rail','underground','reception']},objective:point,exit:point,
  radius_km:number,deadline_turn:{type:'integer',minimum:1},required_turns:{type:'integer',minimum:1},required_survivors:{type:'integer',minimum:1},description:text,assumption:text});
goal.properties.team={type:'string',enum:['red','blue']};
goal.properties.termination_mode={type:'string',enum:['objectives','deadline']};
const actor=shape({
  personnel:{type:'integer',minimum:1},position:point,
  equipment:shape({armor:integer,artillery:integer,air_defense:integer,engineer:integer,transport:integer}),
  type:text,speed:number,attack_range_m:number,ground_control_radius_km:number,
  logistics:shape({food:number,ammo:number}),
  formation:shape({role:{type:'string',enum:['infantry','armor','support']},motorized:{type:'boolean'},
    fatigue:integer,suppression:integer,entrenchment:integer,dispersion_km2:number,protection:number,
    fuel_liters:integer,spares:integer,materials:integer,shells:integer,aa_rounds:integer,reload_remaining:integer,
    intel_age_min:integer,intel_confidence:integer,signal:integer}),
  assumption:text,
});
const equipment=shape({armor:integer,artillery:integer,air_defense:integer,engineer:integer,transport:integer});
const part=shape({id:text,label:text,personnel:{type:'integer',minimum:1},position:point,equipment,
  resources:inventory,dispersion_km2:number,assumption:text});
const partitions=shape({version:{type:'string',enum:['formation-partitions-1','formation-partitions-2']},
  groups:{type:'object',description:'默认{}。仅显式需要分岸/分遣时，键为本阶段已有历史父单位ID；父单位不额外作为战斗实体。',
    additionalProperties:shape({assumption:text,parts:{type:'array',minItems:2,maxItems:32,items:part}})}});
const schedule=shape({not_before:text,assumption:text});
schedule.properties.event_kind={type:'string',enum:['departure','battlefield_entry']};
schedule.properties.reference_id=text;
const arrival={...schedule,properties:{...schedule.properties,parts:{type:'object',additionalProperties:schedule}}};
const region=shape({center:point,radius_km:number});
const campaign=shape({version:{type:'string',enum:['combined-operation-1']},
  arrivals:{type:'object',additionalProperties:arrival},
  fortifications:{type:'object',additionalProperties:shape({integrity:number,degradation_per_shell:number,assumption:text})},
  surrender:shape({enabled:{type:'boolean'},range_m:number,suppression_threshold:number,ammo_threshold:number,assumption:text}),
  objective:shape({relief_regions:{type:'array',minItems:1,maxItems:6,items:region},min_force_fraction:number,assumption:text}),assumption:text});
export const configurationPatchSchema={type:'object',additionalProperties:false,
  description:'直接提交可编辑配置内容，不加configuration包装。单位分片只提交actors且覆盖本片全部ID；公共条件分片提交其余字段。不要提交字符串化JSON、只读身份或assigned_actor_ids。',
  properties:{
    actors:{type:'object',description:'键为get_scenario_basis分配的真实ID，值为该单位完整参数。',additionalProperties:actor},
    clock:shape({start:text,time_step:text,assumption:text}),
    area:shape({center:point,radius_km:number,terrain_factor:number,assumption:text}),
    rules:{type:'object',description:'完整保留本片模板规则字段，只填写允许估计的数值与目标；不提交脚本。',additionalProperties:true},
    support:shape({red:shape({position:point,stock:number,inventory,assumption:text}),blue:shape({position:point,stock:number,inventory,assumption:text})}),
    facility,goal,partitions,campaign,
    campaign_scope:shape({version:{type:'string',enum:['campaign-oob-deployment-1','campaign-oob-deployment-2']},planning_end:text,assumption:text,
      remainders:{type:'object',additionalProperties:shape({policy:{type:'string',enum:['excluded_unquantified','covered_by_children']},assumption:text})}}),
    oob_coverage:shape({version:{type:'string',enum:['historical-oob-coverage-1']},
      remainders:{type:'object',additionalProperties:shape({policy:{type:'string',enum:['excluded_unquantified','covered_by_children']},assumption:text})}}),
    initial_command:shape({version:{type:'string',enum:['historical-command-baseline-1']},assumption:text}),
    support_dynamics:{anyOf:[shape({version:{type:'string',enum:['time-sustainment-1']},
      food_work_per_hour:number,move_factor:number,shortage_fatigue_per_hour:number,recovery_hours_per_fed_hour:number,
      incapacity_after_hours:number,incapacity_fraction_per_hour:number,assumption:text}),
      shape({version:{type:'string',enum:['personnel-rations-1']},ration_kg_per_person_day:number,
        food_kg_per_work:number,carried_kg_per_committed_person:number,move_factor:number,
        shortage_fatigue_per_hour:number,recovery_hours_per_fed_hour:number,
        incapacity_after_hours:number,incapacity_fraction_per_hour:number,assumption:text})]},
    movement_feedback:shape({version:{type:'string',enum:['movement-feedback-1']},assumption:text}),
    fire_accounting:shape({version:{type:'string',enum:['classified-indirect-1']},assumption:text}),
    supply_distribution:shape({version:{type:'string',enum:['split-stocks-1']},food_mass_share:number,
      priority:{type:'string',enum:['food','ammo']},assumption:text}),
    terrain_model:{type:'object',description:'显式有限屏障、道路与遮挡参数，字段沿用本次skill模板，由宿主验证；不是DEM。',additionalProperties:true},
    operation_boundary:shape({version:{type:'string',enum:['operation-boundary-1']},center:point,radius_km:number,assumption:text,
      routes:{type:'array',minItems:1,maxItems:64,items:shape({id:text,team:{type:'string',enum:['red','blue']},
        inside:point,outside:point,corridor_km:number,assumption:text})}}),
    campaign_lifecycle:shape({version:{type:'string',enum:['campaign-lifecycle-1']},
      phases:{type:'array',minItems:2,maxItems:256,items:shape({id:text,label:text,
        goal_ids:{type:'array',items:text},minimum_duration_seconds:integer,
        operation_ids:{type:'array',maxItems:16,uniqueItems:true,items:text},assumption:text})},
      finish_policy:{type:'string',enum:['all_phases','goal_outcomes']},assumption:text}),
    assumptions:text,
  }};
