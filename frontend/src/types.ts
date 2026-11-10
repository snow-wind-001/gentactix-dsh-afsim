export interface Unit {
  formation_part?:FormationPartIdentity;
  calculation_unit_id?:string;
  exercise_unit_id?:string;
  crossing?:CrossingTask;
  formation?: FormationState;
  logistics?: {food:number;ammo:number};
  equipment?: { name: string; category?: string; committed: number; operational: number; damaged: number; destroyed: number }[];
  personnel?: { committed: number; current: number; casualties: number; noncombat_losses: number;
    killed?:number;wounded?:number;missing?:number;captured?:number;unclassified_casualties?:number;breakdown_source?:string };
  name?: string;
  type?: string;
  hp?: number;
  lat?: number;
  lng?: number;
  supply?: string;
  morale?: string;
  [key: string]: unknown;
}

export interface Engagement {
  lat?: number;
  lng?: number;
  description?: string;
  attacker?: string;
  attacker_pos?: [number, number];
  radius?: number;
  intensity?: number;
  [key: string]: unknown; // 中文键兜底（描述/战况/攻击方坐标…），与 viz.py 别名链同口径
}

export interface MissionDefinition {
  fire_dynamics?:FireDynamicsConfig;
  operation_boundary?:OperationBoundary;
  termination_mode?:'objectives'|'deadline';
  terrain_model?:{version:string;assumption:string;barriers:{id:string;a:MapPoint;b:MapPoint;blocks:string[];source:string}[];roads:{id:string;a:MapPoint;b:MapPoint;width_m:number;speed_factor:number;source:string}[]};
  campaign_definition?:CampaignConfiguration&{objective:CampaignConfiguration['objective']&{town:CampaignRegion}};
  campaign_plan?:CampaignPlanConfiguration;
  campaign_lifecycle?:CampaignLifecycleConfiguration;
  objective_team?:'red'|'blue';
  initial_state?:WarState;
  combined_rules?: { era: string; air_support: boolean; motorized: boolean; goal_profile: string; artillery_range_m: number; artillery_min_range_m?:number; aa_range_m: number; bridge_enabled?: boolean };
  historical_calculation?:{format:string;initial:HistoricalInitialSnapshot;parameters:Record<string,unknown>};
  id: string; battle: string; title: string; profile: string; assumptions: string;
  goal: string; time_step: string; deadline_turn: number; required_turns: number;
  objective: { lat: number; lng: number }; exit: { lat: number; lng: number }; goal_radius_km: number;
}
export interface SyntheticFormation {
  name: string; personnel: number; equipment: Record<'armor'|'artillery'|'air_defense'|'engineer'|'transport', number>;
  food: number; ammo: number; shells: number; aa_rounds: number; fuel_liters: number; fatigue: number;
  basis_id?: string; position?: MapPoint;
}
export interface SyntheticConfiguration {
  aviation?:Record<string,AviationParameters>;
  fire_accounting?:FireAccountingConfig;
  fire_dynamics?:FireDynamicsConfig;
  version: string; teams: {red:SyntheticFormation[]; blue:SyntheticFormation[]};
  historical_basis?: {battle:string; basis_hash:string};
}
export interface AviationParameters {
  availability?:{version:'air-availability-1';start:string|null;end:string|null;assumption:string};
  initial:{committed:number|null;ordnance:number|null;fuel:number|null};
  entry:{lat:number|null;lng:number|null};rules:Record<string,number>;assumption:string;
}
export interface ScenarioBasis {
  basis: {battle:string; card?:string; version?:string; phase_id?:string; scope:string; units:{id:string; team:string; name:string; context:string; sources:{id?:string; title?:string;url?:string}[]}[]; unknowns:string[]};
  configuration:SyntheticConfiguration; preview_world:WarState; estimates:string;
  configuration_limits?:{max_units_per_team:number};
  map_center:MapPoint; map_radius_km:number;
}
export interface ScenarioDraft {
  id:string; mission_id:string; configuration:SyntheticConfiguration; preview_world:WarState;
  definition_hash:string; afsim:AFSimEvidence|null; execution_backend?:'afsim'|'narrative'; construction:{source:string; skill:string; explanation?:string};
}
export interface HistoricalActorParameters {
  personnel:number; position:MapPoint; type:string; speed:number; attack_range_m:number;
  ground_control_radius_km:number; equipment:Record<'armor'|'artillery'|'air_defense'|'engineer'|'transport',number>;
  logistics:{food:number;ammo:number}; formation:Record<string,number|string>; assumption:string;
}
export interface CampaignWindowPin {
  format:'gentactix-campaign-window-1';id:string;version:string;definition_hash:string;
  definition:Record<string,unknown>&{label:string;limitations:string;start_phase_id:string;
    bounds:{start:string;end:string;kind:'model_scope_limit';note:string}};
}
export interface HistoricalParameters extends Record<string,unknown> {
  fire_accounting?:FireAccountingConfig;
  fire_dynamics?:FireDynamicsConfig;
  movement_feedback?:{version:'movement-feedback-1';assumption:string};
  operation_boundary?:OperationBoundary;
  initial_command?:{version:'historical-command-baseline-1';assumption:string};
  oob_coverage?:{version:'historical-oob-coverage-1';remainders:Record<string,{policy:'excluded_unquantified'|'covered_by_children'|null;assumption:string}>};
  campaign_scope?:{version:'campaign-oob-deployment-1'|'campaign-oob-deployment-2'|'campaign-oob-window-1';planning_end:string;assumption:string;window?:CampaignWindowPin;remainders?:Record<string,{policy:'excluded_unquantified'|'covered_by_children'|null;assumption:string}>};
  supply_distribution?:SplitSupply;
  supply_schedule?:SupplySchedule;
  support_dynamics?:SupportDynamics;
  campaign?:CampaignConfiguration;
  campaign_plan?:CampaignPlanConfiguration;
  campaign_lifecycle?:CampaignLifecycleConfiguration;
  partitions?:FormationPartitions;
  facility:CrossingFacility;
  aviation?:Record<string,AviationParameters>;
  goal:{termination_mode?:'objectives'|'deadline';team?:'red'|'blue';profile:'assault'|'delay'|'breakout'|'rail'|'underground'|'reception'|'crossing';
    objective:MapPoint;exit:MapPoint;radius_km:number;deadline_turn:number;required_turns:number;
    required_survivors:number;description:string;assumption:string};
  rules:Record<string,unknown>&{goal_profile:string;required_survivors:number};
  phase_id:string; actors:Record<string,HistoricalActorParameters>;
  clock:{start:string;time_step:string;assumption:string};
  area:{center:MapPoint;radius_km:number;terrain_factor:number;assumption:string};
  assumptions:string;
}
export interface HistoricalFixedInput {path:string[];value:number}
export interface HistoricalFixedField {path:string[];group:string;label:string;value:number|null;integer:boolean;required_models:string[]}
export interface HistoricalAssemblyProgress {
  id:string;execution_backend:'afsim'|'narrative';time_step:string;termination_mode:'objectives'|'deadline';
  required_models:string[];fixed_count:number;validated_actors:number;total_actors:number;completed_stages:number;
  failed_part:string|null;status:'running'|'interrupted'|'configured'|'loaded';saved_at:number;last_error:string;active?:boolean;
  can_rebuild_failed_session?:boolean;
  can_revise_configuration?:boolean;
}
export interface HistoricalConfigurationRevision {
  id:string;kind:'historical_configuration_revision';requires_validation:true;checkpoint_hash:string;
  parameters:HistoricalParameters;initial:HistoricalInitialSnapshot;execution_backend:'afsim'|'narrative';
  required_models:string[];fixed_parameters:{version:'fixed-scenario-input-1';values:HistoricalFixedInput[]}|null;
  last_error:string;validation_error:string|null;
  food_loading_errors:{unit:string;food_work:number;food_mass_kg:number;capacity_work:number;capacity_kg:number}[];scope:string;
}
export interface HistoricalScenarioBasis {
  configuration_alternatives?:{version:string;force_scope:'phase'|'campaign';phase_id:string;label:string;actor_count:number;aviation_count:number;scope:string}[];
  fixed_parameter_fields?:HistoricalFixedField[];
  force_scope?:'phase'|'campaign';
  campaign_window?:CampaignWindowPin|null;
  available_campaign_windows?:{id:string;version:string;label:string;start_phase_id:string}[];
  input_constraints?:HistoricalInputConstraints|null;
  pending_configurations?:{id:string;execution_backend:string;time_step:string;termination_mode?:'objectives'|'deadline';saved_at:number}[];
  pending_assemblies?:HistoricalAssemblyProgress[];
  completed_configurations?:{id:string;execution_backend:'afsim'|'narrative';time_step:string;termination_mode:'objectives'|'deadline';saved_at:number;required_models:string[];actor_count:number}[];
  versions?:{version:string;default:boolean;coverage:{notes:string[]}}[];
  interaction?:{kind:'non_contact_transfer';active_teams:('red'|'blue')[];scope:string;evidence:HistoricalEvidence[]}|null;
  aviation?:{id:string;name:string;team:'red'|'blue'}[];
  battle:string;initial:HistoricalInitialSnapshot|null;ready:boolean;error:string;scope:string;
  phases:{id:string;label:string;date:string;ready:boolean;error:string}[];
  actors:{id:string;name:string;team:'red'|'blue';echelon:string;facts:HistoricalRosterUnit['facts'];window_scope?:{extent:string;presence_basis:string;parameter_estimates?:{personnel:{minimum:number;maximum:number};equipment:Record<string,{minimum:number;maximum:number}>;role:string;position:{center:MapPoint;radius_km:number;assumption:string}}}}[];
  execution_window?:{start?:string;end:string;kind:'model_scope_limit';note:string}|null;
  geographic_scope?:{center:MapPoint;radius_km:number;kind:'model_scope_limit';note:string}|null;
  excluded_references?:{id:string;name:string;team:'red'|'blue';status:'later_participant'|'outside_scope'|'covered_reference'|'command_reference'|'after_window'|'outside_window'}[];
  objective_guidance?:{team:'red'|'blue';profile:string;objective_label:string;scope_note:string;not_covered:string[];
    sources:{id:string;title:string;url:string;locator:string}[]}|null;
  goal_semantics?:Record<string,string>;
}
export interface CampaignRegion {center:MapPoint;radius_km:number}
export type HistoricalEntryReference = {
  id:string;unit_id:string;label:string;earliest:string;latest:string;assumption:string;evidence:HistoricalEvidence[];
}&({reference_kind?:'contact';region:CampaignRegion}|{reference_kind:'departure';region:null});
export interface HistoricalInputConstraints {
  version:string;
  personnel:{unit_id:string;minimum:number;maximum:number;reported:string;assumption:string;evidence:HistoricalEvidence[]}[];
  entries:HistoricalEntryReference[];
}
export interface ArrivalSchedule {
  not_before:string;assumption:string;event_kind?:'departure'|'battlefield_entry';reference_id?:string;
}
export interface CampaignConfiguration {
  availability_mode?:'scheduled'|'immediate';
  objective_policy?:'defensive-delay-1';
  version:string;assumption:string;
  arrivals:Record<string,ArrivalSchedule&{parts?:Record<string,ArrivalSchedule>}>;
  fortifications:Record<string,{integrity:number;degradation_per_shell:number;assumption:string}>;
  surrender:{enabled:boolean;range_m:number;suppression_threshold:number;ammo_threshold:number;assumption:string};
  objective:{relief_regions:CampaignRegion[];min_force_fraction:number;assumption:string};
}
export interface CampaignState {
  version:string;source:string;turn:number;execution_source?:string;
  actors:Record<string,{active:boolean;fortification_integrity:number;base_protection:number;base_entrenchment:number;captured_this_turn:number;
    fortification_components?:{base_entrenchment:number;fortification_integrity:number}[]}>;
  objective:{town_control:boolean;relief_denied:boolean;force_preserved:boolean};
}
export interface CampaignGoalNode {
  id:string;label:string;team:'red'|'blue';unit_ids:string[];
  after:{mode:'all'|'any';node_ids:string[]};not_before_seconds:number;hold_seconds:number;latch:boolean;
  condition:{kind:string;region?:CampaignRegion;[key:string]:unknown};operation_ids:string[];assumption:string;
}
export interface CampaignPlanConfiguration {
  version:'campaign-objectives-1';nodes:CampaignGoalNode[];
  outcomes:Record<'red'|'blue',{mode:'all'|'any';node_ids:string[]}>;
  elimination_ends:boolean;assumption:string;
}
export interface CampaignPlanState {
  version:string;source:'host_goal_evaluator';turn:number;sample_at:number;plan_hash:string;state_hash:string;input_hash:string;
  nodes:Record<string,{status:string;condition:boolean;held_seconds:number;satisfied_since:number|null;completed_at:number|null;reason:string;metrics:Record<string,number|string|boolean>}>;
  outcomes:Record<'red'|'blue',boolean>;side_progress:Record<'red'|'blue',number>;resolution:'active'|'red'|'blue'|'draw';
  last_changes:{node_id:string;before:string;after:string;at_seconds:number}[];
}
export interface CampaignPlanMetrics {red:boolean;blue:boolean;completed_nodes:number;total_nodes:number;source:'host_goal_evaluator'}
export interface CampaignLifecyclePhase {id:string;label:string;goal_ids:string[];minimum_duration_seconds:number;operation_ids:string[];assumption:string}
export interface CampaignLifecycleConfiguration {version:'campaign-lifecycle-1';phases:CampaignLifecyclePhase[];finish_policy:'all_phases'|'goal_outcomes';assumption:string}
export interface CampaignLifecycleState {
 version:string;definition_hash:string;turn:number;sample_at:number;phase_index:number;last_sample_phase:number;
 status:'active'|'completed'|'interrupted';reason:string;state_hash:string;
 phases:Record<string,{status:'pending'|'active'|'completed';entered_at:number|null;completed_at:number|null;goal_evidence:Record<string,string>}>;
 last_changes:{phase_id:string;status:string;at_seconds:number}[];
}
export interface HistoricalScenarioDraft {
  sustainment?:SustainmentView|null;
  id:string;kind:'historical_operation';mission_id:string;initial:HistoricalInitialSnapshot;
  parameters:HistoricalParameters;preview_world:WarState;definition_hash:string;
  afsim:AFSimEvidence|null;execution_backend:'afsim'|'narrative';
  construction:{source:string;skill:string;explanation?:string;workflow?:string;page_size?:number;stages?:{part:string;session_id:string;completed_actors:number;total_actors:number}[];fixed_parameters?:{version:'fixed-scenario-input-1';values:HistoricalFixedInput[]};manual_revision?:boolean};
}
export interface MissionState {
  id: string; version: string; definition_hash: string; initial_hash: string;
  definition: MissionDefinition; turn: number; status: 'active' | 'completed'; winner: string | null;
  reason: string; progress: number; network: number; organization: number;
  metrics?: Record<string, number | boolean | CampaignState['objective'] | CampaignPlanMetrics>;
  last_orders: { unit: string; action: string; target?: string; lat?: number; lng?: number }[];
  ledger: { unit: string; action: string; supply_status: string; delivery: number; food_spent: number; ammo_spent: number; food_after: number; ammo_after: number; food_received?:number;ammo_received?:number;
    source?:string;delivery_basis?:string;received?:Record<string,number>;spent?:Record<string,number> }[];
}
export interface RuntimeProgress {
  operation_id?:string;started_at_ms?:number;wall_elapsed_ms?:number;clock_sampled_at_ms?:number;
  label?: string; turns?: number; steps?: number; tokens?: number; phase?: string;
  external_elapsed_ms?: number; receiving?: boolean;
  runtime_state?:'thinking'|'retry_wait'|'retrying'|'compacting'|'compaction_failed'|'receiving'|'checking';
  retry_attempt?:number;retry_delay_ms?:number;
  configuration_stage?:string;completed_stages?:number;total_stages?:number;completed_actors?:number;total_actors?:number;
}
export interface RuntimeOperation extends RuntimeProgress {
  operation_id:string;outcome:'success'|'failed'|'cancelled';
  finish_reason?:string|null;phase?:string;turn?:number;status?:string;error?:string;cancelled?:boolean;
}
export interface PlotItem {id:string;symbol_id:string;label:string;team:'red'|'blue'|'neutral';status:'planned'|'observed'|'assumed';points:MapPoint[];source:string;visible:boolean;unit_id?:string}
export interface PlottingView {version:string;revision:number;turn:number;world_version:string;items:PlotItem[];unit_symbols:Record<string,string>;scope:string;units:{id:string;name:string;team:string;position:MapPoint|null;present:boolean;auto_symbol:string}[]}
export interface PlotProposal {id:string;items:PlotItem[];explanation:string;revision:number;turn:number;world_version:string;construction:{source:string;skill:string;meta:{elapsed_ms:number}}}
export interface WarState {
  afsim?:AFSimEvidence|null;
  supply_nodes?:{id:string;name?:string;team?:string;lat?:number;lng?:number;stock?:number;[key:string]:unknown}[];
  unit_participation?:{version:string;actors:Record<string,{team:string;name:string;status:ParticipationStatus}>};
  campaign?:CampaignState;
  campaign_plan?:CampaignPlanState;
  campaign_lifecycle?:CampaignLifecycleState;
  formation_groups?:{version:'formation-partitions-1'|'formation-partitions-2';groups:FormationGroup[]};
  combat_reference?: CombatReference;
  combat_assessment?: {
    version:string;turn:number;source:string;elapsed_seconds:number;tracked_from_turn:number;
    status:'review_required'|'calibration_pending';historical_fit_verified:boolean;note:string;
    units:{name:string;team:string;committed:number;current:number;turn_casualties:number;turn_killed:number|null;
      turn_wounded?:number|null;turn_captured?:number|null;turn_missing?:number|null;turn_unclassified_casualties?:number|null;
      order_interruption?:'captured_before_execution'|null;
      turn_casualty_pct:number|null;incoming_max_fire_s:number|null;outgoing_fire_s:number|null;
      tracked_incoming_max_fire_s:number;tracked_fire_time_complete:boolean;tracked_casualties:number;fire_cycles:number|null;stop_reason:string|null;issues:string[];
      historical_reference?:{name:string;committed_approx:number|null;casualties_approx:number|null;metric_summary?:string;scope:string;note:string;source:{title:string;url:string}};
      historical_comparison?:string}[];
  };
  historical_initial?: HistoricalInitialSnapshot;
  dsh_execution?:{source:string;effects_source:string;model_skipped:boolean;phase?:string;resource_ledger_version?:string;command_validation_version?:string;
    fire_ledger?:{version:'dsh-fire-estimate-1';source:'dsh_model_estimate';turn:number;scope:string;
      units:{unit:string;action:'fire'|'bombard'|'suppress';target:string;delay_s:number;first_fire_s:number|null;last_fire_s:number|null;
        fire_cycles:number;active_fire_s:number;reload_remaining_s:number;stop_reason:string;assumptions:string}[]};
    events?:{unit?:string;action?:string;seconds?:number;status_code?:number;turn?:number;type?:string;description?:string;model_estimate?:boolean}[]};
  history_replay?: HistoryReplay;
  combined_arms?: { version: string; rules_hash: string; source: string;
    depots: Record<string, {fuel_liters: number; spares: number; materials: number; shells: number; aa_rounds: number}>;
    bridge: CrossingFacility;
    events: { unit: string; action: string; seconds: number; status_code: number }[] };
  air_operations?: AirOperations;
  mission?: MissionState;
  current_time?: string;
  current_terrain?: string;
  situation_report?: string;
  source_note?: string;
  red_units?: Unit[];
  blue_units?: Unit[];
  engagements?: Engagement[];
  eliminated?: string[];
  [key: string]: unknown;
}

export type PartEquipment=Record<'armor'|'artillery'|'air_defense'|'engineer'|'transport',number>;
export type PartResources=Record<'fuel_liters'|'spares'|'materials'|'shells'|'aa_rounds',number>;
export interface FormationPartInput {
  id:string;label:string;personnel:number;position:MapPoint;equipment:PartEquipment;
  resources:PartResources;dispersion_km2:number;assumption:string;
}
export interface FormationPartitions {version:'formation-partitions-1'|'formation-partitions-2';groups:Record<string,{assumption:string;parts:FormationPartInput[]}>}
export interface FormationPartIdentity {version:string;group_id:string;part_id:string;numerator:number;denominator:number;parent_name:string;assumption:string}
export interface FormationGroup {
  id:string;historical_unit_id:string;name:string;team:'red'|'blue';committed:number;
  equipment:PartEquipment;resources:PartResources;members:string[];assumption:string;
}

export interface CrossingModel {
  version:'formation-crossing-1'; barrier:{a:MapPoint;b:MapPoint};banks:{a:MapPoint;b:MapPoint};
  throughput_work_per_hour:number;equipment_work:Record<'armor'|'artillery'|'air_defense'|'engineer'|'transport',number>;
  build_progress_per_engineer_hour:number;supply_work_per_unit:number;assumption:string;
  ferry?:FerryConfig;
}
export interface FerryBoatConfig {id:string;name:string;team:'red'|'blue';seats:number;equipment_work_capacity:number;
 speed_mps:number;load_seconds:number;unload_seconds:number;initial_bank:'a'|'b';assumption:string}
export interface FerryConfig {version:'formation-ferry-1';assumption:string;boats:FerryBoatConfig[]}
export interface FerryState {version:'formation-ferry-1';turn:number;source:string;
 boats:{id:string;lat:number;lng:number;bank:'a'|'b';from_bank:'a'|'b';phase:'idle'|'loading'|'outbound'|'unloading'|'returning';
 remaining_s:number;passenger:string|null;manifest_personnel:number;manifest_equipment_work:number;trips:number}[];
 events:{boat_id:string;unit:string|null;phase:string;seconds:number;lat:number;lng:number}[]}
export interface CrossingTask {
  version:string;site_id:string;model_hash:string;from_bank:'a'|'b';target:MapPoint;required_work:number;served_work:number;
  status:'queued'|'transit'|'completed'|'cancelled';intent_id?:string;last_work:number;turn:number;source:string;events:{phase:string;seconds:number;lat:number;lng:number}[];
}
export interface CrossingFacility extends MapPoint {
  id:string;name:string;progress:number;integrity:number;materials:number;capacity:number;used:number;crossing_model?:CrossingModel;
  crossing_network?:{version:'formation-crossing-network-1';sites:CrossingFacility[]};
  ferry_state?:FerryState;
  crossing_receipt?:{used_work:number;cargo_work:number;budget_work:number;turn:number;source:string;scope:string};
}
export interface HistoricalEvidence { source_id: string; locator: string; note?: string }
export interface HistoricalRosterUnit {
  id: string; name: string; team: 'red'|'blue'; role: string; echelon: string; parent_id: string|null;
  evidence: HistoricalEvidence[];
  presence: {phase_id:string;status:string;evidence:HistoricalEvidence[]}[];
  facts: {
    personnel: {value:number|null;evidence:HistoricalEvidence[];scope:string};
    equipment: {value:unknown[]|null;evidence:HistoricalEvidence[];scope:string};
    position: {value:{kind:string;lat:number;lng:number;uncertainty_km:number;phase_id:string}|null;evidence:HistoricalEvidence[];scope:string};
  };
}
export interface HistoricalInitialSnapshot {
  format: string; profile_id: string; version: string; definition_hash: string; phase_id: string;
  definition: {
    battle:string; coverage:{order_of_battle_complete:boolean;opening_deployment_complete:boolean;strength_complete:boolean;notes:string[]};
    phases:{id:string;label:string;date:{label:string;precision:string};interaction?:HistoricalScenarioBasis['interaction'];execution_window?:HistoricalScenarioBasis['execution_window']}[];
    sources:Record<string,{title:string;url:string;publisher:string;evidence_kind:string;original_archive_examined:boolean;limitations:string}>;
    units:HistoricalRosterUnit[];
  };
}
export interface HistoricalInitialPreview {
  battle:string;status:'partial'|'not_profiled';initial:HistoricalInitialSnapshot|null;
  readiness:null|{roster_count:number;command_count:number;located_unit_count:number;unknown_position_count:number;ready_for_process_simulation:boolean;missing:string[]};
  versions?:{version:string;default:boolean;coverage:{notes:string[]}}[];
}

export interface HistoryReplay {
  ordering?:{version:'dated-events-1';scope:string};
  source_operation?:{id:string;phase_id:string;kind:string;date:{label:string;precision:string};description:string;limitations:string;
    unit_ids:string[];units:{id:string;name:string;team:string}[];
    unit_scopes?:Record<string,{extent:'whole'|'elements'|'reference';scope:string;evidence:{source_id:string;locator:string}[]}>;
    places:{name:string;position:{lat:number;lng:number;uncertainty_km:number;note:string}|null}[];
    evidence:{source_id:string;locator:string}[];
    relations:{id:string;kind:string;parent_id:string;child_id:string;scope:string}[]};
  version: string; battle: string; cursor: number; total: number; status: string; scope: string; evidence: string;
  dataset_hash: string; outcome: string;
  event: { date_label: string; precision: string; event: string; evidence_status?: string;
    variant_group?: string; sources: {id?: string; title: string; url?: string; publisher?: string}[] };
  geo_references: {name: string; lat: number; lng: number; kind: string; metadata: {uncertainty_km?: number; source_url?: string}}[];
  forces: {side: string; unit: string; description: string}[];
  figures: {side: string; metric: string; value: unknown; qualifier?: string; scope: string; note?: string}[];
}

export interface FormationState {
  last_density_sample?:NativeDensitySample;
  motorized?:boolean;
  fuel_credit_microliters?:number;fatigue_carry_ticks?:number;
  motion_task?:{version:'continuous-motion-task-1';intent_id:string|null;target:{lat:number;lng:number}|null;
    status:'idle'|'waiting'|'moving'|'arrived'|'blocked';wait_remaining_ms:number;speed_mps:number;feedback_remaining_ms:number};
  role: string; fatigue: number; suppression: number; entrenchment: number; protection: number; dispersion_km2: number;
  fuel_liters: number; spares: number; materials: number; shells: number; aa_rounds: number; reload_remaining: number;
  intel_age_min: number; intel_confidence: number; signal: number;
  reload_remaining_s?:number;combat_damage_remainder?:number;fatality_remainder?:number;
  last_execution?: { [key: string]: number | string };
}

export interface CombatReference {
  fire_dynamics?:FireDynamicsConfig;
  version:string;combat_revision:number;direct_cycle_s:number;artillery_cycle_s:number;ammo_per_cycle:number;fatality_share:number;
  scope:string;assumptions:string[];sources:{title:string;url:string;scope:string}[];
  benchmark:{battle:string;status:string;scope:string;limitations?:string;local_reference?:string;
    figures:{side:string;metric:string;value:unknown;qualifier?:string;scope:string;note?:string;evidence_status?:string;
      sources:{title:string;url:string}[]}[]};
}

export interface AirOperations {
  pools?:Record<string,AirOperations['assets'][string]&{name:string;team:'red'|'blue';historical_unit_id:string}>;
  version: string; assumptions: string; last_turn: number;
  assets: Record<string, { committed: number; ready: number; destroyed: number; sorties: number; ordnance: number; fuel: number }>;
  recent_missions?: AirOperations['missions'];
  missions: { id: string; team: string; requester: string; target: string; turn: number; package: number;
    pool_id?:string;source?:string;
    entry: {lat: number; lng: number}; aim: {lat: number; lng: number}; altitude_m: number;
    status: string; outcome: string; aircraft_lost: number; personnel_effect: number; equipment_effect: number;
    ordnance_spent: number; fuel_spent: number; effect_basis: string;
    target_turn_effects?: { basis: string; ground_casualties: number; air_casualties: number; air_equipment_destroyed: number };
    events: {phase: string; seconds: number; lat: number; lng: number}[] }[];
}

export interface AdjUnit {
  name: string;
  team: "red" | "blue";
  type: string;
  lat: number;
  lng: number;
  speed_kmh: number;
  reach_km: number;
  nearest_enemy?: string | null;
  nearest_enemy_km?: number | null;
  can_contact: boolean;
  hours_to_contact?: number | null;
  supply: string;
  cut_by?: string | null;
  sealed_ratio: number;
  encirclement: string;
  retreat: string;
  morale_state: string;
}

export interface Adjudication {
  version: string;
  turn: number;
  time_step: string;
  hours: number;
  terrain: string;
  terrain_factor: number;
  terrain_source?: string; // 模型地形标签 / 战役参数库配置
  contact_km: number;
  control_radius_km: number;
  units: AdjUnit[];
  skipped_units: unknown[];
  facts: string[];
  summary: Record<string, number>;
  deterministic: boolean;
  digest: string;
  fingerprint: string;
}

export interface Battle {
  name: string;
  time_step: string; // 战役文件建议的回合跨度；"" = 无建议
}

export interface BattleSpec {
  name: string;
  summary: string;
  source: string | null; // 参数文件路径；null = 默认几何
  source_kind: string;   // library / corpus / default
  time_step_hint: string;
  calibrated: boolean; // 兼容字段，仅表示存在显式参数
  validation_status?: string; // teaching_estimate / unverified；不等于参数已配置
  errors: string[];
  warnings: string[];
  table: unknown;
}

export interface RagMeta {
  phase: string;
  query: string;
  enabled: boolean;
  hits: { doc_title: string; section: string; source: string; score: number; preview: string }[];
  injected: number;
  note: string;
}

export interface RosterEntry {
  name: string;
  hp?: number;
  why?: string;
}

export interface RosterReport {
  recovered: RosterEntry[];
  eliminated: RosterEntry[];
  suspected: RosterEntry[];
  structure_missing?: string[];
  unnamed: number;
  duplicate: string[];
  prev_total: number;
  new_total: number;
  [key: string]: unknown;
}

export interface NumericFlag {
  kind: "hp_gain" | "hp_zero_alive" | "hp_negative";
  name: string;
  prev?: number;
  new?: number;
  delta?: number;
  [key: string]: unknown;
}

export interface Notice {
  level: string;
  message: string;
}

// 最近一次模型调用的观测元数据（finish_reason / 轮次 / 步数 / token / 用时）
export interface EngineMeta {
  label: string;
  finish_reason: string | null;
  turns: number;
  steps: number;
  tokens: number;
  elapsed_ms: number;
  operation_id?: string;
  started_at_ms?:number;wall_elapsed_ms?:number;clock_sampled_at_ms?:number;
  trace_runs?: number;
}

export interface AFSimEvidence {
  experimental_continuous?:boolean;
  historical_roster_count?: number; geographic_reference_count?: number;
  combat_entity_count?: number; battlefield_initialized?: boolean;
  source: string; status: string; returncode: number; phase?: string;
  entity_count: number; wall_ms: number; seconds: number; process_id?: string;
  dispatch_ids?: string[]; version?: string; scope?: string; transport?: string;
  model_skipped?: boolean; planner_prompt_chars?: number; world_chars?: number;
  effects_source?: string; excluded?: { team: string; name: string; reason: string }[];
  air_task_count?: number;
}

export interface ScenarioSelection {
  product_mode?:'analysis'|'historical'|'synthetic';
  historical_source_version?:string|null;
  scenario: string; battle: string; time_step: string; use_rag: boolean;
  use_adjudicator: boolean; simulation_mode: string; mission_id: string;
  execution_backend?: 'narrative' | 'afsim';
  synthetic_configuration?: SyntheticConfiguration | null;
  scenario_draft_id?: string | null;
  historical_parameters?: HistoricalParameters | null;
}

export interface SupportDynamics {
  version:'time-sustainment-1'|'personnel-rations-1';food_work_per_hour?:number;move_factor:number;
  ration_kg_per_person_day?:number;food_kg_per_work?:number;carried_kg_per_committed_person?:number;
  shortage_fatigue_per_hour:number;recovery_hours_per_fed_hour:number;
  incapacity_after_hours:number;incapacity_fraction_per_hour:number;assumption:string;
}
export interface SupplySchedule {
  version:'scheduled-supply-1';period_seconds:number;passive_work_per_hour:number;
  resupply_work_per_hour:number;convoy_speed_kph:number;loading_hours:number;
  warehouse_tons_per_hour:Record<string,number>;assumption:string;
}
export interface SustainmentView {
  horizon_kind?:'rolling_plan';
  supply_distribution?:SplitSupply;
  dynamics?:SupportDynamics;
  version:string;source:string;remaining_turns:number;step:string;scope:string;
  teams:Record<'red'|'blue',{
    available_units:number;parent_equivalents:number;waiting_count:number;
    on_hand_food:number;warehouse_packages:number;food_per_hold_round:number;minimum_hold_food:number;
    optimistic_food_shortfall:number;max_covered_hold_rounds:number|null;
    zero_food_count:number;full_ammo_blocks_food_count:number;
    max_shortage_hours?:number;last_noncombat_losses?:number;
    warehouse_food?:number;warehouse_ammo?:number;
    on_hand_food_kg?:number;warehouse_food_kg?:number;minimum_hold_food_kg?:number;
    food_per_hold_round_kg?:number;optimistic_food_shortfall_kg?:number;
  }>;
}
export interface SplitSupply {version:'split-stocks-1';food_mass_share:number;priority:'food'|'ammo';assumption:string;}
export interface Snapshot {
  aviation_availability?:Record<string,{version:string;status:'pending'|'active'|'expired';start:string;end:string|null;assumption:string}>;
  resource_readiness?: {horizon_kind?:'rolling_plan';remaining_hours:number;scope:string;units:{team:string;unit:string;food_hold_hours:number|null;food_move_hours:number|null;food_on_hand_kg?:number;food_capacity_kg?:number;ration_kg_per_person_day?:number;fire_work_minutes:number;artillery_minutes:number;warnings:string[]}[]}|null;
  sustainment?:SustainmentView|null;
  plotting?:PlottingView;
  afsim?: AFSimEvidence | null;
  session_id: string;
  scenario: string;
  turn_count: number;
  time_step: string;
  branch_origin?: { session_id: string; turn: number; basis: string } | null;
  settings?: { product_mode?:'analysis'|'historical'|'synthetic'|null; execution_backend?: 'narrative' | 'afsim'; simulation_mode?: 'open' | 'replay'; mission_id?: string | null; synthetic_configuration?: SyntheticConfiguration | null; use_agent_tools: boolean; persist_roles: boolean; agent_mode: string; use_live_intel: boolean };
  war_state: WarState | null;
  last_war_state: WarState | null;
  battlefield?: BattlefieldView;
  history: string[];
  review: { text: string | null; reasoning: string | null };
  chat_messages: { role: string; content: string; reasoning?: string }[];
  adjudication: {
    enabled: boolean;
    battle_choice: string | null;
    spec: BattleSpec | null;
    last: Adjudication | null;
    violations: { name: string; team?: string; moved_km?: number; allowed_km?: number; over_km?: number; [key: string]: unknown }[];
  };
  rag: { enabled: boolean; last: RagMeta | null; corpus: { files: number; chunks: number; chars: number; dir: string } };
  integrity: { roster: RosterReport | null; numeric_flags: NumericFlag[] };
  engine_meta?: EngineMeta | null;
  causal?: { record_count: number; latest_trace_id: string | null;
    runtime: { enabled: boolean; connected: boolean; ptc: boolean; mode?: string };
    plugins: { name: string; hooks: string[]; enabled: boolean }[] };
  notices: Notice[];
}

export interface TraceEvent { seq?: number; type: string; time?: number; name?: string; reason?: unknown;
  tools?: string[]; request_config?: { model?: string; maxTokens?: number; reasoningEffort?: string } }
export interface TraceRun { id: string; session_id: string; first_seq: number | null; last_seq: number | null;
  finish_reason: string; event_count: number; events: TraceEvent[]; evidence: string }
export interface DecisionTrace { id: string; turn: number; report: string; time_step: string;
  clock: { status: string; note?: string }; geometry_enabled: boolean; runs: TraceRun[];
  changes: { team: string; name: string; moved_km: number | null; status: string }[];
  decisions: { id: string; team: string; unit_name: string; action: string; rationale: string; expected_effect: string; source?: string; dsh_event_ref?: { session_id: string; seq: number } | null }[] }
export interface MetricContrast { metric: string; factual: number; alternative: number; delta: number }
export interface StatusContrast { team: string; name: string; field: string; factual: unknown; alternative: unknown }
export interface GeometryEffect { turn: number; team: string; name: string; moved_km: number; status_change_count: number;
  source_trace_id: string; metrics: MetricContrast[]; status_changes: StatusContrast[] }
export interface CounterfactualResult { id?: string; mode: string; read_only: boolean; turn: number;
  metrics?: MetricContrast[]; status_changes?: StatusContrast[]; instruction?: string; scope: string;
  samples?: { metrics: MetricContrast[]; admissible: boolean; control: { clock: { status: string } };
    intervention: { clock: { status: string } } }[]; limitations?: string[] }
export interface CausalAnalysis { scope: string; timeline: DecisionTrace[];
  turning_points: { trace_id: string; turn: number; label: string; status_changes: StatusContrast[] }[];
  attributions: { trace_id: string; turn: number; effects: GeometryEffect[]; evaluated_movers: number;
    total_movers: number; interactions: { units: string[]; nonadditive: boolean; joint_status_changes: number; single_counts_sum: number }[] }[];
  explanation: { summary: string; basis: string; hypotheses: { claim: string; evidence_ids: string[]; alternative: string; limitation: string }[] } | null;
  limits: string[]; counterfactuals: CounterfactualResult[] }

export type Position = [number, number];
export interface MapPoint { lat: number; lng: number }
export type ParticipationKind='withdraw'|'reenter';
export interface OperationBoundary {version:'operation-boundary-1';center:MapPoint;radius_km:number;assumption:string;
  routes:{id:string;team:'red'|'blue';inside:MapPoint;outside:MapPoint;corridor_km:number;assumption:string}[]}
export type ParticipationStatus='staging'|'deployed'|'withdrawing'|'reserve'|'returning'|'offmap';
export interface ParticipationView {entity_id:string;status:ParticipationStatus;label:string;readiness:'available'|'disabled';targetable:boolean;controls_objectives:boolean;
  operation_zone?:'inside'|'outside';
  pending:{id:string;kind:ParticipationKind;destination:MapPoint}|null;transition_count:number;scope:string;enabled:boolean;choices:ParticipationKind[]}
export interface FireAccountingConfig {version:'classified-indirect-1';assumption:string}
export interface FireDynamicsConfig {version:'live-footprint-density-1'|'live-footprint-density-2';assumption:string}
export interface NativeDensitySample {version:'live-footprint-density-1';source:'afsim_native';turn:number;sample_s:number;
  lat_cell:number;lng_cell:number;own_current:number;eligible:number;footprint_committed:number;footprint_current:number}
export interface FireResourceBudget {version:'fire-resource-budget-1';source:'configured_model_inputs';profile_hash:string;
  profile_source:'frozen_checkpoint'|'registered_model_profile';resource_scale:number;
  stock_snapshot:{turn:number|null;current_time:string|null;timing:'committed_state_after_turn';applies_to:'next_order_from_current_state';settled_deliveries_already_included:true};
  ammo_work:{on_hand:number|null;per_cycle:number;cycles_from_on_hand:number|null;applies_to?:string[]};
  indirect:{operational_guns:number|null;shells:number|null;shells_per_cycle_ceiling:number|null;
    full_salvos_at_ceiling:number|null;remaining_shells:number|null;partial_salvo_possible:boolean;shared_quota_included:false;generic_work_per_cycle?:number}|null;
  delivery_timing:'within_turn_events'|'turn_end_only';future_delivery_included:false;is_readiness_or_effect_prediction:false;scope:string}
export interface CommandUnit { id: string; team: string; name: string; present: boolean; ambiguous: boolean;
  fire_resources?:FireResourceBudget;
  formation?: FormationState;
  type?: string; hp?: number; personnel_strength_pct?:number; personnel?: { current?: number;committed?:number;casualties?:number } | null; equipment?: unknown;
  logistics?: { food?: number; ammo?: number } | null; attack_range?: number;
  position: MapPoint | null; available: boolean; controllable: boolean;
  capabilities: { actions: string[]; enabled: boolean; reason: string; move_km: number; movement_basis: string; unsupported: string[];
    arrival?:{status:'active'|'staging';not_before:string;source:'model_schedule';availability_mode?:'immediate';event_kind?:ArrivalSchedule['event_kind'];reference_id?:string};capture_range_m?:number;
    air_pools?:{id:string;name:string;package:number}[];
    participation?:ParticipationView;
    operation_routes?:{id:string;inside:MapPoint;outside:MapPoint;on_corridor:boolean}[];
    weapon_limits_m?:Record<string,{min_range_m:number;max_range_m:number}>;weapon_warnings?:string[] } }
export interface OrderDraft { id?: string; unit_id: string; action: string; duration: 'next' | 'until_arrived' | 'until_turn'; end_turn?:number;destination?: MapPoint; target_id?: string;air_pool?:string;participation?:ParticipationKind }
export interface QueuedOrder extends OrderDraft { id: string; status: string; reason?: string }
export interface CommandView { enabled: boolean; read_only: boolean; revision: number; world_version: string; turn: number; epoch: number;
  control_team: string; director: boolean; no_fire: boolean; intent: string; units: CommandUnit[];
  orders: QueuedOrder[]; unit_agents: string[] }
export interface CommandRevision { expected_turn: number; revision: number; world_version: string }
export interface CommandProposal { id: string; status: string; orders: OrderDraft[]; intent: string; no_fire: boolean; clarifications: string[] }
export interface ImportPreview { session_id: string; scenario: string; turn_count: number; time_step: string;
  simulation_mode: string; unit_count: number; order_count: number; agent_count: number; conflict: boolean; warnings: string[] }
export interface UnitDecision { id: string; turn: number; unit_id: string; unit_name: string; team: string; action: string;
  task_context?:{task_id:string;group_id:string;kind:string;role:string;reason:string;command_chain:string[];organization_revision:number};
  command_id?: string | null; planned?: { action?: string; lat?: number; lng?: number; destination?: MapPoint } | null;
  expected_effect?: string; goal?: MapPoint | null; before_personnel?: { current?: number } | null; after_personnel?: { current?: number } | null;
  before_logistics?: { food?: number; ammo?: number } | null; after_logistics?: { food?: number; ammo?: number } | null;
  ledger?: { delivery?: number; food_consumed?: number; ammo_spent?: number } | null;
  source: string; status: string; rationale: string; reason?: string; run_ids?: string[]; trace_id?: string;
  dsh_event_ref?: { session_id: string; seq: number } | null; history_status?: string;
  before_position?: MapPoint | null; after_position?: MapPoint | null; outcome_basis?: string }
export interface CommandPreview { origin: MapPoint; destination: MapPoint | null; moveKm: number }
export interface CountMetric {
  committed: number | null;
  current?: number | null;
  casualties?: number | null;
  noncombat_losses?: number | null;
  operational?: number | null;
  damaged?: number | null;
  destroyed?: number | null;
  name?: string;
  unit?: string;
  valid: boolean;
  note: string;
  source: string;
  carried_forward?: boolean;
  loss_rate: number | null;
  secondary_rate: number | null;
  readiness_rate: number | null;
}
export interface FireRange {
  name: string;
  team: "red" | "blue";
  position: Position;
  max_range_m: number;
  min_range_m: number;
  estimated: boolean;
  source: string;
}
export interface BattlefieldView {
  version: string;
  terrain: {
    label: string;
    factor: number | null;
    source: string | null;
    features: { name: string; kind: string; geometry: string; coordinates: Position[]; elevation_m: number | null; source: string }[];
  };
  fire_ranges: FireRange[];
  fields_of_fire: (FireRange & { bearing_deg: number; arc_deg: number; coordinates: Position[] })[];
  supply_nodes: { id: string; name: string; team: "red" | "blue"; position: Position; source: string }[];
  supply_lines: { name: string; team: "red" | "blue"; coordinates: Position[]; estimated: boolean; status: string; source: string; cut_by: string | null }[];
  losses: {
    units: { name: string; team: "red" | "blue"; status: string; personnel: CountMetric | null; equipment: CountMetric[] }[];
    teams: { team: "red" | "blue"; total_units: number; recorded_units: number; archived_units: number; active_current: number | null; personnel: CountMetric | null; equipment: CountMetric[] }[];
  };
  operational?: {
    note: string;
    units: { team: 'red' | 'blue'; name: string; active: boolean; status: string;
      baseline_hp: number | null; baseline_time: string | null; current_hp: number | null;
      previous_hp: number | null; hp_change: number | null; hp_decline: number | null;
      hp_decline_rate: number | null; morale: number | null; supply: number | null }[];
    teams: { team: 'red' | 'blue'; active_units: number; disabled_units: number;
      hp_recorded_units: number; comparable_units: number; changed_units: number;
      current_hp: number | null; hp_decline: number | null; hp_decline_rate: number | null;
      hp_change: number | null; mean_morale: number | null; mean_supply: number | null }[];
  };
  data_quality?: { key: string; label: string; recorded: number; total: number | null;
    status: 'available' | 'partial' | 'missing'; note: string }[];
  warnings: string[];
  notes: string[];
}

export interface Health {
  model_config?:{ready:boolean;error:string};
  afsim?: { available: boolean; verified: boolean; mode: string; missing: string[] };
  build?: { loaded_revision: string; disk_revision: string; restart_required: boolean; started_at: string; pid: number };
  status: string;
  engine: string;
  profile: string;
  model: string;
  base_url: string;
  dsh_home: string;
  harness_started: boolean;
  adjudicator_version?: string;
  runtime?: { enabled: boolean; connected: boolean; ptc: boolean; mode?: string };
}

export interface LlmConfig {
  base_url: string; model: string; max_tokens: number; context_window: number; timeout_seconds: number;
  provider: string; api_key_configured: boolean;
  role_policies: Record<string, { max_tokens: number; reasoning_effort: string | null }>;
  max_steps: number; max_tool_calls: number;
  storage: { path: string; encrypted: boolean; format: string; key_location: string; error: string };
  presets: { id: string; label: string; base_url: string; model: string }[];
}

export interface ForceTotals {units:number;committed:number|null;current:number|null;casualties:number|null;noncombat_losses:number|null;equipment:Record<string,number|null>}
export interface ForceNode {id:string;name:string;team:string;parent_id:string|null;role:string;echelon:string;presence:string;children:string[];execution_ids:string[];effective_execution_ids:string[];totals:ForceTotals;
 children_coverage?:{status:string;scope:string};
 command_parent_id?:string|null;command_children?:string[];command_execution_ids?:string[];command_totals?:ForceTotals;effective_command_totals?:ForceTotals}
export interface ForceGroup {id:string;label:string;team:string;parent_id:string|null;children:string[];depth:number;direct_member_ids:string[];member_ids:string[];assumption:string;totals:ForceTotals}
export interface ForceView {revision:number;command_revision:number;turn:number;world_version:string;nodes:ForceNode[];roots:string[];groups:ForceGroup[];execution_ids:string[];inactive_ids:string[];controllable_ids:string[];totals:Record<string,ForceTotals>;scope:string;targets:{id:string;name:string;team:string;available:boolean}[];
 participation_supported?:boolean;
 command_baseline?:{version:string;phase_id:string;source_definition_hash:string;binding_hash:string;assumption:string;scope:string};command_roots?:string[]}
export interface ForceRevision {expected_turn:number;revision:number;world_version:string;organization_revision:number}

export type FormationAllocation = {id:string;label:string;committed:number}|{id:string;historical_unit_id:string|null;committed:number};
export interface FormationConversionRequest extends ForceRevision {
  kind:'split'|'merge';unit_ids:string[];allocations?:FormationAllocation[];assumption:string;
}
export interface FormationConversionTotals {
  personnel:Record<string,number>;equipment:Record<string,Record<string,number>>;
  absolute_stock:Record<string,number>;normalized_stock:Record<string,number>;resource_scale:number;
  fractional_debts:Record<string,number>;
}
export interface FormationConversionPreview {
  ok:true;readonly:true;preview_only:true;runtime_admitted:false;kind:'split'|'merge';
  view_version:string;world_version:string;command_revision:number;organization_revision:number;
  totals_before:FormationConversionTotals;totals_after:FormationConversionTotals;
  rows:{name:string;proposed_calculation_id:string;personnel:Record<string,number>;
    equipment:Record<string,number|string>[];logistics:{food:number;ammo:number};resource_scale:number;position:MapPoint}[];
  total_rows:number;offset:number;limit:number;next_args:{offset:number}|null;
  ownership:{current_entities:number;candidate_entities:number;verified:boolean};
  session_continuity:{active_tasks:number;converted_source_commands:number;agent_sessions_cloned:boolean};
  policies:Record<string,string>;formal_commit_available:boolean;
}
export interface FormationConversionCommit extends FormationConversionRequest {view_version:string;commit_id:string}
export interface FormationConversionReceipt {
  replayed:boolean;runtime_admitted:boolean;physics_executed:boolean;registry_revision:number;commit_id:string;
  command_map:Record<string,string[]>;current_command_map:Record<string,string[]>;
}
export interface FormationConversionResponse extends ForceView {conversion_result:FormationConversionReceipt}
export interface InitialCommandHandoff {changed:boolean;scope:string;changes:{unit_id:string;name:string;before_parent:string|null;after_parent:string|null;before_name:string;after_name:string}[]}
export type ForceTaskRole='maneuver'|'fire_support'|'engineer'|'reserve'|'sustain';
export interface ForceTask {kind:'uniform'|'advance'|'assault'|'defend'|'withdraw'|'sustain';destination?:MapPoint;target_id?:string;roles?:Record<string,ForceTaskRole>;order?:Record<string,unknown>;end_turn?:number;participation?:ParticipationKind}
export interface ForceTaskPreview {preview_hash:string;candidate_count:number;conflict_count:number;rows:{unit_id:string;name:string;role:ForceTaskRole;reason:string;status:string;order:Record<string,unknown>|null;existing_order:{action:string}|null}[]}
export interface ForceTaskExecutionDefinition {
 version:'force-task-execution-1';label:string;not_before_turn:number;
 after:{mode:'all'|'any';task_ids:string[];goal_ids:string[]};
 finish:{kind:'arrived'}|{kind:'goal';goal_id:string}|{kind:'turn';end_turn:number;minimum_executions:number};assumption:string;
}
export interface ForceTaskExecutionRow {
 id:string;label:string;team:string;group_id:string;status:string;reason:string;can_cancel:boolean;
 definition:ForceTaskExecutionDefinition;member_count:number;member_sample:string[];
 member_args:Record<string,string|number>;event_args:Record<string,string|number>;
}
export interface ForceTaskExecutionMember {unit_id:string;name:string;status:string;reason:string;executions:number;last_receipt_id:string|null;last_order_id:string|null}
export interface ForceTaskPage<T=ForceTaskExecutionRow> {ok:boolean;readonly:boolean;kind:string;task_id:string|null;turn:number;view_version:string;total:number;offset:number;rows:T[];next_args:Record<string,string|number>|null;scope:string}
