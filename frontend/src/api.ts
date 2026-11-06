import type { Battle, CausalAnalysis, CounterfactualResult, Health, Snapshot, LlmConfig, MissionDefinition, RuntimeProgress,
  CommandView, CommandRevision, OrderDraft, MapPoint, CommandProposal, UnitDecision, ImportPreview } from "./types";

declare global {
  interface Window { gentactix?: { backendUrl: string; onMenuAction?: (callback: (action: 'open-llm-settings' | 'new-scenario') => void) => () => void } }
}

const BASE = window.gentactix?.backendUrl ?? "http://127.0.0.1:8700";

export class ApiError extends Error {
  constructor(public readonly status: number, detail: string, public readonly configurationId?:string,
    public readonly assemblyProgress?:import('./types').HistoricalAssemblyProgress) { super(detail); this.name = 'ApiError'; }
}

async function requestText(method: string, path: string, payload?: unknown, signal?: AbortSignal): Promise<string> {
  const res = await fetch(BASE + path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: payload === undefined ? undefined : JSON.stringify(payload),
    signal,
  });
  const text = await res.text();
  if (!res.ok) {
    let detail = text,configurationId:string|undefined,assemblyProgress:import('./types').HistoricalAssemblyProgress|undefined;
    try {
      const raw=JSON.parse(text).detail??text;
      detail=typeof raw==='object'&&typeof raw?.message==='string'?raw.message:String(raw);
      if(typeof raw?.configuration_id==='string'&&/^[a-f0-9]{32}$/.test(raw.configuration_id))configurationId=raw.configuration_id;
      if(typeof raw?.assembly_id==='string'&&/^[a-f0-9]{32}$/.test(raw.assembly_id)&&raw.assembly_progress?.id===raw.assembly_id)assemblyProgress=raw.assembly_progress;
    } catch { /* 保留原文 */ }
    throw new ApiError(res.status, detail, configurationId,assemblyProgress);
  }
  return text;
}

async function request<T>(method: string, path: string, payload?: unknown, signal?: AbortSignal): Promise<T> {
  return JSON.parse(await requestText(method,path,payload,signal)) as T;
}

async function exportFile(sid:string,compact=true):Promise<{blob:Blob;filename:string}> {
  const response=await fetch(`${BASE}/api/sessions/${sid}/export${compact?'?compact=true':''}`);
  if(!response.ok){
    let detail=await response.text();
    try{detail=String(JSON.parse(detail).detail??detail);}catch{/* Keep the server's text. */}
    throw new ApiError(response.status,detail);
  }
  const disposition=response.headers.get('Content-Disposition')??'';
  const encoded=/filename\*=UTF-8''([^;]+)/i.exec(disposition);
  const ascii=/filename="([^"]+)"/i.exec(disposition);
  let filename=ascii?.[1]??`GenTactix_${sid}.json`;
  if(encoded){try{filename=decodeURIComponent(encoded[1]);}catch{/* Use ASCII fallback. */}}
  return {blob:await response.blob(),filename};
}

export const api = {
  objectiveBranch:(sid:string,world_version:string)=>request<Snapshot>('POST',`/api/sessions/${sid}/objective-branch`,{world_version}),
  phaseCandidates:(sid:string)=>request<{world_version:string;items:{id:string;label:string;start:string}[]}>('GET',`/api/sessions/${sid}/phase-continuation`),
  previewPhase:(sid:string,draft_id:string,world_version:string)=>request<{handoff:{carried:{name:string;current:number;casualties:number}[];entered:{name:string}[];exited:{name:string}[]};start:string;units:number;organization_revision:number;command_revision:number;command_handoff:{carried:{command_id:string}[];blocked:{command_id:string;reason:string}[];terminated:{command_id:string;reason:string}[];exited_members:{group_id:string;leaf_key:string}[];initial_command?:import('./types').InitialCommandHandoff}}> ('POST',`/api/sessions/${sid}/phase-continuation/preview`,{draft_id,world_version}),
  continuePhase:(sid:string,draft_id:string,world_version:string,revisions?:{organization_revision:number;command_revision:number})=>request<Snapshot>('POST',`/api/sessions/${sid}/phase-continuation`,{draft_id,world_version,...revisions}),
  historicalInitial:(battle:string,signal?:AbortSignal,version?:string)=>request<import('./types').HistoricalInitialPreview>(
    'GET',`/api/historical-initial?battle=${encodeURIComponent(battle)}${version?'&version='+encodeURIComponent(version):''}`,undefined,signal),
  historicalScenarioBasis:(battle:string,phase?:string,signal?:AbortSignal,version?:string,termination_mode?:'objectives'|'deadline',force_scope:'phase'|'campaign'='phase',campaign_window_id?:string,campaign_window_version?:string)=>request<import('./types').HistoricalScenarioBasis>(
    'GET',`/api/historical-scenarios/basis?battle=${encodeURIComponent(battle)}${phase?'&phase_id='+encodeURIComponent(phase):''}${version?'&version='+encodeURIComponent(version):''}${termination_mode?'&termination_mode='+termination_mode:''}&force_scope=${force_scope}${campaign_window_id?'&campaign_window_id='+encodeURIComponent(campaign_window_id):''}${campaign_window_version?'&campaign_window_version='+encodeURIComponent(campaign_window_version):''}`,undefined,signal),
  buildHistoricalScenario:(battle:string,phase_id:string,instruction:string,operation_id:string,execution_backend:string,time_step:string,required_models:string[]=[],version?:string,termination_mode:'objectives'|'deadline'='objectives',force_scope:'phase'|'campaign'='phase',campaign_window_id?:string,campaign_window_version?:string,fixed_parameters:import('./types').HistoricalFixedInput[]=[])=>
    request<import('./types').HistoricalScenarioDraft>('POST','/api/historical-scenarios/build',{battle,phase_id,instruction,operation_id,execution_backend,time_step,required_models,version,termination_mode,force_scope,campaign_window_id,campaign_window_version,fixed_parameters}),
  validateHistoricalScenario:(parameters:import('./types').HistoricalParameters,parent_draft_id:string,operation_id:string,execution_backend:string,required_models:string[]=[],fixed_parameters?:import('./types').HistoricalFixedInput[])=>
    request<import('./types').HistoricalScenarioDraft>('POST','/api/historical-scenarios/validate',{parameters,parent_draft_id,operation_id,execution_backend,required_models,fixed_parameters}),
  retryHistoricalLoad:(configuration_id:string,operation_id:string)=>request<import('./types').HistoricalScenarioDraft>(
    'POST','/api/historical-scenarios/retry-load',{configuration_id,operation_id}),
  resumeHistoricalScenario:(assembly_id:string,operation_id:string,rebuild_failed_session=false)=>request<import('./types').HistoricalScenarioDraft>(
    'POST','/api/historical-scenarios/resume',{assembly_id,operation_id,...(rebuild_failed_session?{rebuild_failed_session:true}:{})}),
  readFailedHistoricalRevision:(id:string)=>request<import('./types').HistoricalConfigurationRevision>(
    'GET',`/api/historical-scenarios/assemblies/${id}/revision`),
  readHistoricalScenario:(id:string)=>request<import('./types').HistoricalScenarioDraft>('GET',`/api/historical-scenarios/drafts/${id}`),
  deriveHistoricalScenario:(base_draft_id:string,operation_id:string,execution_backend:string)=>
    request<import('./types').ScenarioBasis & {draft:import('./types').ScenarioDraft}>('POST','/api/scenarios/from-historical',{base_draft_id,operation_id,execution_backend}),
  plottingCatalog:()=>request<{version:string;symbols:import('./militarySymbols').MilitarySymbol[];reference:{independent_examples:number}}>('GET','/api/plotting/catalog'),
  plotting:(sid:string)=>request<import('./types').PlottingView>('GET',`/api/sessions/${sid}/plotting`),
  savePlotting:(sid:string,value:Pick<import('./types').PlottingView,'revision'|'turn'|'world_version'|'items'|'unit_symbols'>)=>request<import('./types').PlottingView>('PUT',`/api/sessions/${sid}/plotting`,value),
  proposePlotting:(sid:string,value:{revision:number;turn:number;world_version:string;text:string;points:MapPoint[]})=>request<import('./types').PlotProposal>('POST',`/api/sessions/${sid}/plotting/propose`,value),
  plottingReferences:(query:string)=>request<{total:number;items:{id:string;name_zh:string;source_pdf_page:number;source_figure:string}[]}>('GET',`/api/plotting/reference?query=${encodeURIComponent(query)}`),
  plottingReferenceSvg:(id:string)=>requestText('GET',`/api/plotting/reference/${encodeURIComponent(id)}.svg`),
  health: () => request<Health>("GET", "/api/health"),
  llmConfig: () => request<LlmConfig>('GET', '/api/llm/config'),
  saveLlmConfig: (value: { base_url: string; model: string; api_key: string | null; max_tokens: number; context_window: number; timeout_seconds: number; clear_api_key?: boolean; role_policies?: LlmConfig['role_policies']; max_steps?: number; max_tool_calls?: number }) => request<LlmConfig>('PUT', '/api/llm/config', value),
  testLlm: () => request<{ ok: boolean; model: string }>('POST', '/api/llm/test'),
  planScenario: (messages: { role: string; content: string }[]) => request<{ reply: string; ready: boolean; scenario: string; battle: string; time_step: string; sources: { source: string; section: string }[] }>('POST', '/api/scenarios/plan', { messages }),
  missions: () => request<{ missions: MissionDefinition[] }>("GET", "/api/missions"),
  syntheticConfiguration: (id: string) => request<import('./types').SyntheticConfiguration>('GET', `/api/missions/${encodeURIComponent(id)}/configuration`),
  scenarioBasis: (id: string) => request<import('./types').ScenarioBasis>('GET', `/api/scenarios/basis/${encodeURIComponent(id)}`),
  buildScenario: (mission_id:string,instruction:string,operation_id:string,execution_backend:'afsim'|'narrative'='afsim',historical_draft_id?:string) => request<import('./types').ScenarioDraft>('POST','/api/scenarios/build',{mission_id,instruction,operation_id,execution_backend,historical_draft_id}),
  validateScenario: (mission_id:string,configuration:import('./types').SyntheticConfiguration,parent_draft_id:string,operation_id:string,execution_backend:'afsim'|'narrative'='afsim') => request<import('./types').ScenarioDraft>('POST','/api/scenarios/validate',{mission_id,configuration,parent_draft_id,operation_id,execution_backend}),
  cancelScenario: (operation_id:string) => request<{ok:boolean}>('POST',`/api/scenarios/operations/${operation_id}/cancel`),
  scenarioProgress: (operation_id:string,signal?:AbortSignal) => request<{active:boolean;cancel_requested:boolean;progress:import('./types').RuntimeProgress|null}>('GET',`/api/scenarios/operations/${operation_id}/progress`,undefined,signal),
  battles: () => request<{ battles: Battle[] }>("GET", "/api/battles"),
  corpus: () => request<{ files: number; chunks: number; chars: number; dir: string }>("GET", "/api/corpus"),
  sessions: () => request<{ sessions: { session_id: string; turn_count: number; scenario: string; initialized: boolean }[] }>('GET', '/api/sessions'),
  previewImport: (payload: Record<string, unknown>) => request<ImportPreview>('POST', '/api/sessions/import/preview', payload),
  importSession: (payload: Record<string, unknown>) => request<{ session_id: string; turn_count: number }>('POST', '/api/sessions/import', payload),
  deleteSession: (sid: string) => request<{ ok: boolean; session_id: string; audit_retained: boolean }>('DELETE', `/api/sessions/${sid}`),
  createSession: (opts: {
    scenario: string; time_step: string; use_adjudicator: boolean;
    battle: string | null; use_rag: boolean; use_live_intel: boolean;
    use_agent_tools: boolean;
    persist_roles?: boolean;
    agent_mode?: string; simulation_mode?: string; mission_id?: string | null;
    execution_backend?: 'narrative' | 'afsim';
    synthetic_configuration?: import('./types').SyntheticConfiguration | null;
    scenario_draft_id?: string | null;
    product_mode?: 'analysis'|'historical'|'synthetic';
    historical_source_version?:string|null;
    historical_initial_version?:string|null;
    historical_parameters?: Record<string,unknown> | null;
  }) => request<{ session_id: string }>("POST", "/api/sessions", opts),
  init: (sid: string) => request<Snapshot>("POST", `/api/sessions/${sid}/init`),
  next: (sid: string, instruction = "", batch?: CommandRevision & { batch_id: string }) => request<Snapshot>("POST", `/api/sessions/${sid}/next`, { instruction, ...batch }),
  nextHistory: (sid: string, expected_turn: number) => request<Snapshot>('POST', `/api/sessions/${sid}/next`, { expected_turn }),
  forces:(sid:string)=>request<import('./types').ForceView>('GET',`/api/sessions/${sid}/force-organization`),
  previewFormation:(sid:string,value:import('./types').FormationConversionRequest&{offset?:number;limit?:number;view_version?:string})=>request<import('./types').FormationConversionPreview>('POST',`/api/sessions/${sid}/force-organization/conversion-preview`,value),
  commitFormation:(sid:string,value:import('./types').FormationConversionCommit)=>request<import('./types').FormationConversionResponse>('POST',`/api/sessions/${sid}/force-organization/conversion-commit`,value),
  detachForces:(sid:string,value:import('./types').ForceRevision&{unit_ids:string[];label:string;assumption:string;parent_id?:string|null})=>request<import('./types').ForceView>('POST',`/api/sessions/${sid}/force-organization/detach`,value),
  mergeForces:(sid:string,value:import('./types').ForceRevision&{group_ids:string[];label:string;assumption:string})=>request<import('./types').ForceView>('POST',`/api/sessions/${sid}/force-organization/merge`,value),
  wrapForces:(sid:string,value:import('./types').ForceRevision&{group_ids:string[];label:string;assumption:string})=>request<import('./types').ForceView>('POST',`/api/sessions/${sid}/force-organization/wrap`,value),
  reparentForces:(sid:string,value:import('./types').ForceRevision&{group_id:string;parent_id:string|null;assumption:string})=>request<import('./types').ForceView>('POST',`/api/sessions/${sid}/force-organization/reparent`,value),
  forceOrder:(sid:string,value:import('./types').ForceRevision&{group_id:string;order:Record<string,unknown>})=>request<import('./types').ForceView>('POST',`/api/sessions/${sid}/force-organization/orders`,value),
  previewForceTask:(sid:string,value:import('./types').ForceRevision&{group_id:string;task:import('./types').ForceTask;replace_existing:boolean;execution?:import('./types').ForceTaskExecutionDefinition|null})=>request<import('./types').ForceTaskPreview>('POST',`/api/sessions/${sid}/force-organization/task-preview`,value),
  commitForceTask:(sid:string,value:import('./types').ForceRevision&{group_id:string;task:import('./types').ForceTask;replace_existing:boolean;preview_hash:string;execution?:import('./types').ForceTaskExecutionDefinition|null})=>request<import('./types').ForceView>('POST',`/api/sessions/${sid}/force-organization/tasks`,value),
  forceTasks:<T=import('./types').ForceTaskExecutionRow>(sid:string,args:Record<string,string|number>={})=>request<import('./types').ForceTaskPage<T>>('GET',`/api/sessions/${sid}/force-organization/tasks?`+new URLSearchParams(Object.entries(args).map(([k,v])=>[k,String(v)]))),
  cancelForceTask:(sid:string,value:import('./types').ForceRevision&{task_id:string})=>request<import('./types').ForceView>('POST',`/api/sessions/${sid}/force-organization/cancel-task`,value),
  campaignObjectives:(sid:string,args:Record<string,string|number>={})=>request<{nodes:(import('./types').CampaignGoalNode&{state:{status:string}})[];next_args:Record<string,string|number>|null}>('GET',`/api/sessions/${sid}/campaign-objectives?`+new URLSearchParams(Object.entries(args).map(([k,v])=>[k,String(v)]))),
  commands: (sid: string) => request<CommandView>('GET', `/api/sessions/${sid}/commands`),
  saveCommands: (sid: string, value: CommandRevision & { orders: OrderDraft[]; control_team: string; director: boolean; no_fire: boolean; intent: string; unit_agents: string[]; reset_agents?: string[]; proposal_id?: string }) => request<CommandView>('PUT', `/api/sessions/${sid}/commands`, value),
  cancelCommand: (sid: string, id: string, value: CommandRevision) => request<CommandView>('DELETE', `/api/sessions/${sid}/commands/${id}`, value),
  resolveCommands: (sid: string, value: CommandRevision & { text: string; selected_units: string[]; map_target: MapPoint | null }) => request<CommandProposal>('POST', `/api/sessions/${sid}/commands/resolve`, value),
  unitDecisions: (sid: string, id: string, offset = 0, turn?: number) => request<{ total: number; items: UnitDecision[] }>('GET', `/api/sessions/${sid}/unit-decisions?unit_id=${encodeURIComponent(id)}&offset=${offset}&limit=25${turn === undefined ? '' : `&start_turn=${turn}&end_turn=${turn}`}`),
  openBranch: (sid: string, revision: CommandRevision) => request<Snapshot>('POST', `/api/sessions/${sid}/commands/open-branch`, revision),
  compareCommands: (sid: string, value: CommandRevision & { turn: number; orders: OrderDraft[] }) => request<CounterfactualResult>('POST', `/api/sessions/${sid}/commands/compare`, value),
  review: (sid: string) => request<Snapshot>("POST", `/api/sessions/${sid}/review`),
  chat: (sid: string, message: string) =>
    request<Snapshot>("POST", `/api/sessions/${sid}/chat`, { message }),
  get: (sid: string, signal?:AbortSignal) => request<Snapshot>("GET", `/api/sessions/${sid}`,undefined,signal),
  cancel: (sid: string) => request<{ ok: boolean; note: string }>("POST", `/api/sessions/${sid}/cancel`),
  progress: (sid: string, signal?: AbortSignal) => request<{ active: boolean; progress: RuntimeProgress;operation_id?:string|null;
    completed_operation?:Omit<import('./types').RuntimeOperation,'outcome'>|null;
    failed_operation?:Omit<import('./types').RuntimeOperation,'outcome'>|null;
    last_operation?:import('./types').RuntimeOperation|null }>('GET', `/api/sessions/${sid}/progress`, undefined, signal),
  analysis: (sid: string) => request<CausalAnalysis>("GET", `/api/sessions/${sid}/analysis`),
  explain: (sid: string, explain = true) => request<CausalAnalysis>("POST", `/api/sessions/${sid}/analysis`, { explain }),
  counterfactual: (sid: string, payload: { turn: number; mode: string; undo?: { team: string; name: string }[]; instruction?: string; samples?: number; orders?: Record<string, unknown>[] }) =>
    request<CounterfactualResult>("POST", `/api/sessions/${sid}/counterfactual`, payload),
  trace: (sid: string, turn: number) => request<{ persistence: { session_id: string; status: string; found_events?: number; expected_events?: number }[] }>("GET", `/api/sessions/${sid}/traces/${turn}`),
  exportFile,
  exportUrl: (sid: string,compact=false) => `${BASE}/api/sessions/${sid}/export${compact?'?compact=true':''}`,
  exportSession: (sid: string) => request<Record<string, unknown>>('GET', `/api/sessions/${sid}/export`),
  exportSessionText: (sid: string,compact=false) => requestText('GET', `/api/sessions/${sid}/export${compact?'?compact=true':''}`),
};
