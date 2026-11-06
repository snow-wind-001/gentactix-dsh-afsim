<script setup lang="ts">
import {computed,nextTick,onBeforeUnmount,ref,watch} from 'vue';
import {api,ApiError} from '../api';
import {stepDurationSeconds} from '../timeSteps';
import {historicalCampaignGoalAllowed} from '../historicalGoals';
import AviationParametersEditor from './AviationParametersEditor.vue';
import CrossingParametersEditor from './CrossingParametersEditor.vue';
import FormationPartsEditor from './FormationPartsEditor.vue';
import CampaignParametersEditor from './CampaignParametersEditor.vue';
import CampaignObjectives from './CampaignObjectives.vue';
import CampaignGoalInputs from './CampaignGoalInputs.vue';
import SustainmentPanel from './SustainmentPanel.vue';
import SupportDynamicsEditor from './SupportDynamicsEditor.vue';
import SplitSupplyEditor from './SplitSupplyEditor.vue';
import SupplyScheduleEditor from './SupplyScheduleEditor.vue';
import FireAccountingEditor from './FireAccountingEditor.vue';
import FixedParameterInputs from './FixedParameterInputs.vue';
import OperationBoundaryEditor from './OperationBoundaryEditor.vue';
import {formationPartIssues,formationPartName,formationPartsPreview} from '../formation-parts';
import type {HistoricalAssemblyProgress,HistoricalConfigurationRevision,HistoricalFixedInput,HistoricalParameters,HistoricalScenarioBasis,HistoricalScenarioDraft,MapPoint,WarState,RuntimeProgress} from '../types';
const props=defineProps<{battle:string;timeStep:string;purpose?:string;executionBackend:'afsim'|'narrative';busy:boolean}>();
const emit=defineEmits<{change:[value:HistoricalParameters|null];valid:[value:boolean];available:[value:boolean];'draft-id':[value:string|null];preview:[value:WarState|null];selection:[value:{team:string;name:string}|null];'pick-map':[label:string];busy:[label:string];feedback:[message:string];status:[label:string]}>();
const basis=ref<HistoricalScenarioBasis|null>(null),draft=ref<HistoricalScenarioDraft|null>(null),value=ref<HistoricalParameters|null>(null);
const calculationUnitIds=computed(()=>new Set(basis.value?.actors.map(unit=>unit.id)??[]));
const assemblyRevision=ref<HistoricalConfigurationRevision|null>(null);
const loading=ref(false),working=ref(false),error=ref(''),phase=ref(''),instruction=ref(''),verified=ref(''),selected=ref('');
const selectedPart=ref<string|null>(null);
const fixedParameters=ref<HistoricalFixedInput[]>([]),fixedReady=ref(true);
const preflightAttempted=ref(false);
const verificationSignature=()=>JSON.stringify({parameters:value.value,fixed_parameters:fixedParameters.value});
function acceptDraft(result:HistoricalScenarioDraft){
 assemblyRevision.value=null;
 value.value=result.parameters;draft.value=result;
 const window=result.parameters.campaign_scope?.window;
 scopeChoice.value=window?'window':result.parameters.campaign_scope?'campaign':'phase';
 windowChoice.value=window?window.id+'@'+window.version:'';
 fixedParameters.value=JSON.parse(JSON.stringify(result.construction.fixed_parameters?.values??[]));
 verified.value=verificationSignature();
}
function applyFixed(row:HistoricalFixedInput){
 if(!value.value)return;let node:Record<string,unknown>=value.value;
 for(const key of row.path.slice(0,-1)){const child=node[key];if(!child||typeof child!=='object'||Array.isArray(child))return;node=child as Record<string,unknown>;}
 if(row.path.at(-1)! in node)node[row.path.at(-1)!]=row.value;
}
function changeFixed(rows:HistoricalFixedInput[]){
 const previous=new Map(fixedParameters.value.map(row=>[JSON.stringify(row.path),row.value]));
 for(const row of rows)if(previous.get(JSON.stringify(row.path))!==row.value)applyFixed(row);
 fixedParameters.value=rows;verified.value='';recoveryId.value='';
}
const selectedRegion=ref<number|null>(null);
const selectedGoal=ref<string|null>(null);
const boundaryPick=ref<{key:'center'|'inside'|'outside';route:number}|null>(null);
const requireFerry=ref(false),requireTimeSustainment=ref(true),requireSupplySchedule=ref(false);
const requireMovementFeedback=ref(false);
const requireClassifiedFire=ref(false);
const requireLiveDensity=ref(false);
const requireSuppressionCarry=ref(false);
const terminationMode=ref<'objectives'|'deadline'>(props.purpose==='synthetic'?'deadline':'objectives');
const objectiveDriven=computed(()=>terminationMode.value==='objectives');
const sourceVersion=ref('');
const scopeChoice=ref<''|'phase'|'campaign'|'window'>('');
const forceScope=computed<'phase'|'campaign'>(()=>scopeChoice.value==='campaign'||scopeChoice.value==='window'?'campaign':'phase');
const windowChoice=ref('');
const windowCatalog=ref<NonNullable<HistoricalScenarioBasis['available_campaign_windows']>>([]);
const versionCatalog=ref<NonNullable<HistoricalScenarioBasis['versions']>>([]);
const showWindowVersions=ref(false);
const visibleWindows=computed(()=>{
 if(showWindowVersions.value)return windowCatalog.value;
 const latest=new Map<string,NonNullable<HistoricalScenarioBasis['available_campaign_windows']>[number]>();
 for(const window of windowCatalog.value){
  const previous=latest.get(window.id);
  if(!previous||window.version.localeCompare(previous.version,'en',{numeric:true})>0)latest.set(window.id,window);
 }
 const rows=[...latest.values()];
 const pinned=windowCatalog.value.find(w=>w.id+'@'+w.version===windowChoice.value);
 if(pinned&&!rows.some(w=>w.id===pinned.id&&w.version===pinned.version))rows.push(pinned);
 return rows;
});
const scopeSelected=computed(()=>!!scopeChoice.value&&(scopeChoice.value!=='window'||!!windowChoice.value));
const scopeResolved=computed(()=>{
 const b=basis.value;if(!scopeSelected.value||!b)return false;
 if(!b.ready)return true;
 const window=b.campaign_window;
 return (b.force_scope??'phase')===forceScope.value&&b.initial?.version===sourceVersion.value&&
  (scopeChoice.value==='window'?!!window&&window.id+'@'+window.version===windowChoice.value:!window);
});
const windowPresenceLabels:Record<string,string>={reported_action:'窗口内有行动记载',window_reference:'窗口参战参考',prior_reference:'窗口之前的参考，持续在场待核',departure_only:'只核启程，尚未核定到场'};
const recoveryId=ref('');
const assemblyRecovery=ref<HistoricalAssemblyProgress|null>(null);
type ConfigurationChoice=Pick<HistoricalAssemblyProgress,'execution_backend'|'time_step'|'termination_mode'|'required_models'>;
function configurationChoiceIssue(item:ConfigurationChoice){
 if(item.execution_backend!==props.executionBackend||stepDurationSeconds(item.time_step)!==stepDurationSeconds(props.timeStep)||item.termination_mode!==terminationMode.value){
  return `请先匹配保存条件：${item.execution_backend==='afsim'?'AFSIM':'DSH独立'} · ${item.time_step} · ${item.termination_mode==='objectives'?'以目标完成为主':'限时完成'}。`;
 }
 if(JSON.stringify([...item.required_models].sort())!==JSON.stringify([...requiredModels.value].sort())){
  const labels:Record<string,string>={'classified-indirect-1':'分类炮弹计量','live-footprint-density-1':'动态目标密度','live-footprint-density-2':'动态密度与连续压制余量','time-sustainment-1':'时间粮秣','personnel-rations-1':'人员粮秣','scheduled-supply-1':'定时补给','movement-feedback-1':'运动与疲劳反馈','formation-ferry-1':'舟艇运输'};
  return '保存时要求的模型：'+(item.required_models.map(v=>labels[v]??v).join('、')||'无附加模型')+'；请先匹配上方选项。';
 }
 return '';
}
function resumeIssue(item:HistoricalAssemblyProgress){
 if(item.active)return '此草稿仍在生成，请等待原任务结束';
 return configurationChoiceIssue(item);
}
function failedRequest(e:unknown){
 error.value=String(e);recoveryId.value=e instanceof ApiError?e.configurationId??'':'';
 assemblyRecovery.value=e instanceof ApiError?e.assemblyProgress??null:null;
 if(assemblyRecovery.value&&basis.value){
  basis.value.pending_assemblies=[assemblyRecovery.value,...(basis.value.pending_assemblies??[]).filter(r=>r.id!==assemblyRecovery.value!.id)];
 }
}
const rationModel=ref<'time-sustainment-1'|'personnel-rations-1'>('time-sustainment-1');
const requiredModels=computed(()=>[...(requireFerry.value?['formation-ferry-1']:[]),...(requireTimeSustainment.value||requireSupplySchedule.value?[rationModel.value]:[]),...(requireSupplySchedule.value?['scheduled-supply-1']:[]),...(requireMovementFeedback.value?['movement-feedback-1']:[]),...(requireClassifiedFire.value?['classified-indirect-1']:[]),...(requireSuppressionCarry.value?['live-footprint-density-2']:requireLiveDensity.value?['live-footprint-density-1']:[])]);
let generation=0,controller:AbortController|undefined,operationId='';
const progress=ref<RuntimeProgress|null>(null),progressUnavailable=ref(false);
let progressTimer:ReturnType<typeof setTimeout>|undefined,progressController:AbortController|undefined;
const stageLabel=computed(()=>{
 if(progressUnavailable.value)return '正在生成配置；暂未取得进度状态';
 const p=progress.value;if(!p)return '正在等待模型与配置校验…';
 if(p.phase==='afsim_load')return '完整配置已校验，正在实际装载AFSIM…';
 if(p.phase==='scenario_resume')return `正在恢复DSH原生会话 · 已保存 ${p.completed_actors??0} / ${p.total_actors??0} 个单位`;
 if(p.runtime_state==='retry_wait')return `模型请求等待重试${p.retry_attempt?' · 第'+p.retry_attempt+'次':''}；已保存草稿继续保留`;
 if(p.runtime_state==='retrying')return 'DSH正在重试模型请求；尚未完成配置';
 if(p.runtime_state==='compacting')return 'DSH正在压缩上下文；尚未完成配置';
 if(p.runtime_state==='compaction_failed')return '上下文压缩未完成，等待运行结果';
 if(p.phase==='scenario_receipt_recovery')return '参数已保存，正在重新核对生成回执…';
 if(p.configuration_stage==='final')return '正在核对全部单位与可计算目标…';
 if(p.configuration_stage==='globals')return '正在配置时钟、地域、目标与保障…';
 if(p.configuration_stage?.startsWith('actors:'))return `正在填写部队参数 · 已完成 ${p.completed_actors??0} / ${p.total_actors??0} 个单位`;
 return p.phase==='scenario_validation'?'正在校验完整配置…':(p.label??'正在生成配置…');
});
function stopProgress(){if(progressTimer)clearTimeout(progressTimer);progressTimer=undefined;progressController?.abort();progressController=undefined;}
function startProgress(id:string){
 stopProgress();progress.value=null;progressUnavailable.value=false;progressController=new AbortController();const signal=progressController.signal;
 const poll=async()=>{
  if(!working.value||operationId!==id||signal.aborted)return;
  try{const result=await api.scenarioProgress(id,signal);if(operationId===id&&!signal.aborted){progress.value=result.progress;progressUnavailable.value=false;}}
  catch{if(!signal.aborted&&operationId===id)progressUnavailable.value=true;}
  if(working.value&&operationId===id&&!signal.aborted)progressTimer=setTimeout(()=>void poll(),1000);
 };
 void poll();
}
const equipment=[['armor','装甲车辆'],['artillery','火炮'],['air_defense','防空火器'],['engineer','工兵作业组'],['transport','运输单元']] as const;
function clear(){draft.value=null;value.value=null;assemblyRevision.value=null;fixedParameters.value=[];preflightAttempted.value=false;verified.value='';selected.value='';selectedPart.value=null;selectedRegion.value=null;selectedGoal.value=null;boundaryPick.value=null;recoveryId.value='';assemblyRecovery.value=null;}
async function load(requestedPhase?:string,requestedVersion=sourceVersion.value){
 const current=++generation;controller?.abort();controller=new AbortController();clear();basis.value=null;error.value='';loading.value=true;
 if(!props.battle){loading.value=false;return;}
 try{const [windowId,windowVersion]=windowChoice.value.split('@');const result=await api.historicalScenarioBasis(props.battle,requestedPhase,controller.signal,requestedVersion||undefined,terminationMode.value,forceScope.value,windowId||undefined,windowVersion||undefined);if(current!==generation)return;basis.value=result;windowCatalog.value=result.available_campaign_windows??[];versionCatalog.value=result.versions??[];phase.value=result.initial?.phase_id??'';sourceVersion.value=result.initial?.version??'';}
 catch(e){if(current===generation)error.value=String(e);}finally{if(current===generation)loading.value=false;}
}
function clearScopeRequest(){generation++;controller?.abort();loading.value=false;clear();error.value='';}
function chooseScope(){
 windowChoice.value='';clearScopeRequest();
 if(!scopeChoice.value||scopeChoice.value==='window')return;
 // Cumulative OOB is an explicit latest-version choice, never same-day attendance.
 if(scopeChoice.value==='campaign')sourceVersion.value=[...versionCatalog.value].sort((a,b)=>a.version.localeCompare(b.version,'en',{numeric:true})).at(-1)?.version??sourceVersion.value;
 void load(undefined,sourceVersion.value);
}
function changeWindow(){sourceVersion.value='';if(!windowChoice.value){clearScopeRequest();return;}void load(undefined,'');}
async function chooseAlternative(choice:NonNullable<HistoricalScenarioBasis['configuration_alternatives']>[number]){
 if(loading.value||working.value||props.busy)return;
 windowChoice.value='';sourceVersion.value=choice.version;scopeChoice.value=choice.force_scope;
 await load(choice.phase_id,choice.version);
}
watch(()=>props.battle,()=>{instruction.value='';requireFerry.value=false;requireTimeSustainment.value=true;rationModel.value='time-sustainment-1';requireSupplySchedule.value=false;requireMovementFeedback.value=false;requireClassifiedFire.value=false;requireLiveDensity.value=false;requireSuppressionCarry.value=false;scopeChoice.value='';sourceVersion.value='';windowChoice.value='';windowCatalog.value=[];versionCatalog.value=[];showWindowVersions.value=false;void load();},{immediate:true});
// A verified historical configuration is also the synthetic seed. Preserve its
// explicit termination choice when switching purpose; changing it would clear
// the parent while ScenarioComposer is deriving from it.
watch(()=>props.purpose,purpose=>{if(!draft.value)terminationMode.value=purpose==='synthetic'?'deadline':'objectives';});
watch(terminationMode,()=>{void load(phase.value||undefined);});
watch([requireFerry,requireTimeSustainment,rationModel,requireSupplySchedule,requireMovementFeedback,requireClassifiedFire,requireLiveDensity,requireSuppressionCarry],()=>{verified.value='';recoveryId.value='';});
watch(requireSupplySchedule,enabled=>{if(enabled)requireTimeSustainment.value=true;});
watch(()=>props.executionBackend,()=>{recoveryId.value='';});
watch(()=>props.timeStep,step=>{recoveryId.value='';if(value.value){value.value.clock.time_step=step;verified.value='';}});
watch(value,()=>{recoveryId.value='';},{deep:true});
onBeforeUnmount(()=>{generation++;controller?.abort();stopProgress();if(working.value&&operationId)void api.cancelScenario(operationId).catch(()=>{});});
const stepWindowIssue=computed(()=>{
 if(objectiveDriven.value)return '';
 const window=basis.value?.execution_window,seconds=stepDurationSeconds(props.timeStep);
 if(!window?.start||seconds===null)return '';
 // Source windows are naive local times; append Z to compare wall-clock spans
 // without introducing the operator machine's historical DST offset.
 const span=(Date.parse(window.end+'Z')-Date.parse(window.start+'Z'))/1000;
 return Number.isFinite(span)&&seconds>span?`所选回合跨度${props.timeStep}超过本阶段计算窗口（${span/3600}小时），无法容纳一整轮。请在上方减小回合跨度后生成；当前选择不会自动更改。`:'';
});
const available=computed(()=>scopeResolved.value&&!!basis.value?.ready&&!loading.value&&!stepWindowIssue.value);
const readinessStatus=computed(()=>{
 if(loading.value)return '正在读取所选历史范围…';
 if(!scopeSelected.value)return scopeChoice.value==='window'?'请选择会战窗口，明确日期与方向范围。':'请先选择限定会战窗口、累计参战编制或局部阶段。';
 if(!basis.value?.ready)return basis.value?.error||'所选范围尚未就绪，请检查资料或重新读取。';
 if(!scopeResolved.value)return '当前资料与所选范围不一致，请重新读取。';
 return stepWindowIssue.value;
});
watch([working,stageLabel,readinessStatus],()=>emit('status',working.value?stageLabel.value:readinessStatus.value),{immediate:true});
const goalProfiles=[['assault','地域夺控'],['delay','迟滞存续'],['breakout','突围通路'],['crossing','完成渡运与集结'],['rail','交通破袭'],['underground','隐蔽存续'],['reception','停战接收']] as const;
const blueProfiles=new Set<string>(['assault','delay','breakout','crossing']);
const goalOwner=computed<'red'|'blue'>({get:()=>value.value?.goal.team??'red',set:team=>{
 if(!value.value)return;value.value.goal.team=team;
 const count=basis.value?.actors.filter(u=>u.team===team).length??1;
 const required=Math.max(1,Math.min(value.value.goal.required_survivors,count));
 value.value.goal.required_survivors=required;value.value.rules.required_survivors=required;
}});
const goalProfile=computed<HistoricalParameters['goal']['profile']>({get:()=>value.value?.goal.profile??'assault',set:profile=>{
 if(value.value){value.value.goal.profile=profile;value.value.rules.goal_profile=profile;
  if(value.value.campaign){if(profile==='delay'&&value.value.campaign_scope)value.value.campaign.objective_policy='defensive-delay-1';else delete value.value.campaign.objective_policy;}
 }
}});
function enableDefensiveDelay(){if(value.value?.campaign){value.value.campaign.objective_policy='defensive-delay-1';verified.value='';}}
async function restoreCompleted(item:NonNullable<HistoricalScenarioBasis['completed_configurations']>[number]){
 if(working.value||props.busy)return;const current=generation;working.value=true;error.value='';emit('busy','正在读取已验证的想定配置…');
 try{const result=await api.readHistoricalScenario(item.id);if(current===generation)acceptDraft(result);}
 catch(e){if(current===generation)failedRequest(e);}finally{working.value=false;emit('busy','');}
}
const survivors=computed<number>({get:()=>value.value?.goal.required_survivors??1,set:n=>{
 if(value.value){value.value.goal.required_survivors=n;value.value.rules.required_survivors=n;}
}});
const goalActorCount=computed(()=>basis.value?.actors.filter(u=>u.team===goalOwner.value).length??0);
const usesProgress=computed(()=>objectiveDriven.value||!value.value?.campaign&&!['delay','underground'].includes(goalProfile.value));
const usesExit=computed(()=>['delay','breakout'].includes(goalProfile.value));
const usesSurvivors=computed(()=>['delay','breakout','crossing'].includes(goalProfile.value));
const goalHelp=computed(()=>{
 if(value.value?.campaign_plan)return '按会战目标图逐方向评分；各节点分别规定阵营、地域、保持时间及前置条件，最终按双方目标组合结算';
 if(value.value?.campaign?.objective_policy==='defensive-delay-1')return '按已入场编组数、已入场人员保持比例及出口未被突破连续达标；未到场单位不计存续。参考据点与阻援区域不要求己方夺占。';
 if(value.value?.campaign)return objectiveDriven.value?'据点、全部阻援区域控制与兵力保存同时满足，并保持指定回合后结算':'在截止回合同时满足据点控制、全部阻援区域控制与兵力保存；占点不会提前结算';
 let text=basis.value?.goal_semantics?.[goalProfile.value]??'';
 const labels:Record<string,string>={目标方:goalOwner.value==='red'?'红方':'蓝方',对方:goalOwner.value==='red'?'蓝方':'红方',
  required_turns:String(value.value?.goal.required_turns??1),required_survivors:String(value.value?.goal.required_survivors??1),
  objective:'目标点',exit:'出口',network:'交通完整度',accepted:'接收标志'};
 for(const [key,label] of Object.entries(labels))text=text.replaceAll(key,label);
 return text;
});
const goalValid=computed(()=>{
 const p=value.value;if(!p)return false;const g=p.goal;
 const point=(v:MapPoint)=>Number.isFinite(v.lat)&&Number.isFinite(v.lng)&&Math.abs(v.lat)<=90&&Math.abs(v.lng)<=180;
 return ['red','blue'].includes(g.team??'red')&&(goalOwner.value!=='blue'||blueProfiles.has(g.profile))&&
  goalProfiles.some(([id])=>id===g.profile)&&[g.deadline_turn,g.required_turns,g.required_survivors].every(n=>Number.isInteger(n)&&n>0&&n<=100000)&&
  (g.profile!=='crossing'||!!p.facility.crossing_model)&&
  (objectiveDriven.value||!usesProgress.value||g.required_turns<=g.deadline_turn)&&g.required_survivors<=goalActorCount.value&&
  historicalCampaignGoalAllowed(p,basis.value?.interaction)&&
  Number.isFinite(g.radius_km)&&g.radius_km>=.01&&g.radius_km<=p.area.radius_km&&point(g.objective)&&point(g.exit);
});
const fieldValid=computed(()=>goalValid.value&&!!value.value&&!formationPartIssues(value.value.partitions,value.value.actors).length&&Object.values(value.value.actors).every(p=>Number.isInteger(p.personnel)&&p.personnel>0&&Number.isFinite(p.position.lat)&&Number.isFinite(p.position.lng)&&equipment.every(([key])=>Number.isInteger(p.equipment[key])&&p.equipment[key]>=0)));
const preflightIssue=computed(()=>{
 if(!scopeSelected.value)return scopeChoice.value==='window'?'请先选择会战窗口，明确日期与方向范围。':'请先选择推演范围：限定会战窗口、累计参战编制或局部阶段。';
 if(!fixedReady.value)return '请修正生成前指定的数值，或启用它需要的保障模型。';
 if(!available.value)return stepWindowIssue.value||'历史初态尚未就绪，请检查阶段资料或等待读取完成。';
 if((draft.value||assemblyRevision.value)&&!fieldValid.value)return '历史配置校验失败：请检查人员、装备、部署位置、编组划分和战役目标。';
 return '';
});
const feedback=computed(()=>error.value||(preflightAttempted.value?preflightIssue.value:''));
watch(feedback,message=>emit('feedback',message));
const valid=computed(()=>scopeResolved.value&&fixedReady.value&&fieldValid.value&&(value.value?.goal.termination_mode??'deadline')===terminationMode.value&&(!requireTimeSustainment.value||!!value.value?.support_dynamics)&&(!requireSupplySchedule.value||!!value.value?.supply_schedule)&&(!requireMovementFeedback.value||!!value.value?.movement_feedback)&&(!requireClassifiedFire.value||!!value.value?.fire_accounting)&&(!requireLiveDensity.value||!!value.value?.fire_dynamics)&&(!requireSuppressionCarry.value||value.value?.fire_dynamics?.version==='live-footprint-density-2')&&(!requireFerry.value||!!value.value?.facility.crossing_model?.ferry)&&!!draft.value&&draft.value.execution_backend===props.executionBackend&&verified.value===verificationSignature()&&!working.value&&!loading.value);
const preview=computed<WarState|null>(()=>{
 if(!draft.value||!value.value)return null;
 const world=formationPartsPreview(draft.value.preview_world,value.value.actors,value.value.partitions);
 if(world.combined_arms){world.combined_arms.bridge=JSON.parse(JSON.stringify(value.value.facility));if(world.mission?.definition.combined_rules)world.mission.definition.combined_rules.bridge_enabled=!!value.value.rules.bridge_enabled;}
 if(world.mission&&goalValid.value){const g=value.value.goal;
  if(value.value.campaign_plan)world.mission.definition.campaign_plan=JSON.parse(JSON.stringify(value.value.campaign_plan));
  if(value.value.operation_boundary)world.mission.definition.operation_boundary=JSON.parse(JSON.stringify(value.value.operation_boundary));
  else delete world.mission.definition.operation_boundary;
  Object.assign(world.mission.definition,{objective_team:g.team??'red',termination_mode:g.termination_mode??'deadline',objective:{...g.objective},exit:{...g.exit},goal_radius_km:g.radius_km,deadline_turn:g.deadline_turn,required_turns:g.required_turns});
  if(value.value.campaign)world.mission.definition.campaign_definition={...JSON.parse(JSON.stringify(value.value.campaign)),objective:{...JSON.parse(JSON.stringify(value.value.campaign.objective)),town:{center:{...g.objective},radius_km:g.radius_km}}};
 }
 world.source_note='具名历史单位配置草稿；地图部署与缺载数值为显式模型估计，未开始推演。';return world;
});
watch(available,v=>emit('available',v),{immediate:true});
watch([value,valid,draft],()=>{emit('change',value.value?JSON.parse(JSON.stringify(value.value)):null);emit('valid',valid.value);emit('draft-id',valid.value?draft.value!.id:null);},{deep:true,immediate:true});
watch(preview,v=>emit('preview',v),{immediate:true});
watch([selected,selectedPart],([id,partId])=>{const u=basis.value?.actors.find(u=>u.id===id);const part=value.value?.partitions?.groups[id]?.parts.find(p=>p.id===partId);emit('selection',u?{team:u.team,name:part?formationPartName(u.name,part.label):u.name}:null);});
async function generate(){
 if(!available.value||!fixedReady.value||working.value||props.busy)return;const current=generation;working.value=true;error.value='';recoveryId.value='';assemblyRecovery.value=null;emit('busy','DSH正在调用具名历史单位skill生成参数…');operationId=crypto.randomUUID().replaceAll('-','');
 startProgress(operationId);
 try{const [windowId,windowVersion]=windowChoice.value.split('@');const r=await api.buildHistoricalScenario(props.battle,phase.value,instruction.value,operationId,props.executionBackend,props.timeStep,requiredModels.value,sourceVersion.value||undefined,terminationMode.value,forceScope.value,windowId||undefined,windowVersion||undefined,fixedParameters.value);if(current!==generation)return;
  acceptDraft(r);
 }catch(e){if(current===generation)failedRequest(e);}finally{stopProgress();working.value=false;emit('busy','');}
}
async function resumeAssembly(item:HistoricalAssemblyProgress,rebuild=false){
 if(resumeIssue(item)||working.value||props.busy)return;const current=generation;
 working.value=true;error.value='';assemblyRecovery.value=item;emit('busy',rebuild?'正在重建未完成片的DSH会话；已校验参数保留…':'正在继续已保存的分片配置…');operationId=crypto.randomUUID().replaceAll('-','');startProgress(operationId);
 try{const result=await api.resumeHistoricalScenario(item.id,operationId,rebuild);if(current!==generation)return;
  acceptDraft(result);assemblyRecovery.value=null;recoveryId.value='';
  if(basis.value)basis.value.pending_assemblies=(basis.value.pending_assemblies??[]).filter(r=>r.id!==item.id);
 }catch(e){if(current===generation)failedRequest(e);}finally{stopProgress();working.value=false;emit('busy','');}
}
async function reviseAssembly(item:HistoricalAssemblyProgress){
 if(resumeIssue(item)||working.value||props.busy)return;const current=generation;
 working.value=true;error.value='';emit('busy','正在读取原DSH失败配置，原草稿保持不变…');
 try{const result=await api.readFailedHistoricalRevision(item.id);if(current!==generation)return;
  if(result.initial.definition_hash!==basis.value?.initial?.definition_hash||result.initial.phase_id!==basis.value?.initial?.phase_id)throw Error('失败配置与当前史料版本或阶段不一致，请重新选择');
  draft.value=null;assemblyRevision.value=result;value.value=result.parameters;
  fixedParameters.value=JSON.parse(JSON.stringify(result.fixed_parameters?.values??[]));
  verified.value='';assemblyRecovery.value=null;recoveryId.value='';
 }catch(e){if(current===generation)error.value=String(e);}finally{working.value=false;emit('busy','');}
}
async function retryLoad(){
 if(!recoveryId.value||working.value||props.busy)return;const current=generation;
 working.value=true;error.value='';emit('busy','正在装载已保存的想定参数…');operationId=crypto.randomUUID().replaceAll('-','');startProgress(operationId);
 try{const r=await api.retryHistoricalLoad(recoveryId.value,operationId);if(current!==generation)return;
  acceptDraft(r);recoveryId.value='';if(basis.value)basis.value.pending_configurations=[];
 }catch(e){if(current===generation){error.value=String(e);if(e instanceof ApiError&&e.configurationId)recoveryId.value=e.configurationId;}}
 finally{stopProgress();working.value=false;emit('busy','');}
}
async function validate(){
 const parent=draft.value?.id??assemblyRevision.value?.id;
 if(!value.value||!parent||!fieldValid.value||!fixedReady.value||working.value||props.busy)return;working.value=true;error.value='';emit('busy',props.executionBackend==='afsim'?'AFSIM正在验证历史单位部署…':'正在验证历史单位DSH配置…');operationId=crypto.randomUUID().replaceAll('-','');
 startProgress(operationId);
 try{const r=await api.validateHistoricalScenario(value.value,parent,operationId,props.executionBackend,requiredModels.value,fixedParameters.value);acceptDraft(r);}
 catch(e){error.value=String(e);recoveryId.value=e instanceof ApiError?e.configurationId??'':'';}finally{stopProgress();working.value=false;emit('busy','');}
}
function pick(id:string){if(!draft.value||working.value||props.busy)return;boundaryPick.value=null;selectedGoal.value=null;selectedRegion.value=null;selected.value=id;selectedPart.value=value.value?.partitions?.groups[id]?.parts[0]?.id??null;emit('pick-map',basis.value?.actors.find(u=>u.id===id)?.name??id);}
function pickPart(input:{actorId:string;partId:string}){if(!draft.value||working.value||props.busy)return;boundaryPick.value=null;selectedGoal.value=null;selectedRegion.value=null;selected.value=input.actorId;selectedPart.value=input.partId;emit('pick-map',value.value?.partitions?.groups[input.actorId]?.parts.find(p=>p.id===input.partId)?.label??input.partId);}
function pickRegion(index:number){if(!draft.value||working.value||props.busy)return;boundaryPick.value=null;selectedGoal.value=null;selected.value='';selectedPart.value=null;selectedRegion.value=index;emit('pick-map',`阻援区域 ${index+1}`);}
function pickGoal(id:string){if(!draft.value||working.value||props.busy)return;boundaryPick.value=null;selectedRegion.value=null;selected.value='';selectedPart.value=null;selectedGoal.value=id;emit('pick-map',value.value?.campaign_plan?.nodes.find(n=>n.id===id)?.label??id);}
function selectUnit(team:string,name:string){
 const unit=(team==='red'?preview.value?.red_units:preview.value?.blue_units)?.find(u=>u.name===name);
 if(unit?.formation_part){pickPart({actorId:unit.formation_part.group_id,partId:unit.formation_part.part_id});return;}
 const u=basis.value?.actors.find(u=>u.team===team&&u.name===name);if(u)pick(u.id);
}
function pickBoundary(key:'center'|'inside'|'outside',route:number){
 if(!draft.value||working.value||props.busy)return;
 selectedGoal.value=null;selectedRegion.value=null;selected.value='';selectedPart.value=null;boundaryPick.value={key,route};
 emit('pick-map',key==='center'?'作战区中心':key==='inside'?'通路区内点':'通路区外点');
}
function placeSelected(point:MapPoint){
 if(working.value||props.busy)return;
 if(boundaryPick.value&&value.value?.operation_boundary){
  const config=value.value.operation_boundary,{key,route}=boundaryPick.value;
  if(key==='center')config.center={...point};else if(config.routes[route])config.routes[route]![key]={...point};
  boundaryPick.value=null;return;
 }
 if(selectedGoal.value){const region=value.value?.campaign_plan?.nodes.find(n=>n.id===selectedGoal.value)?.condition.region;if(region)region.center={...point};return;}
 if(selectedRegion.value!==null){const region=value.value?.campaign?.objective.relief_regions[selectedRegion.value];if(region)region.center={...point};return;}
 const part=value.value?.partitions?.groups[selected.value]?.parts.find(p=>p.id===selectedPart.value);
 const p=part??value.value?.actors[selected.value];if(p)p.position={...point};
}
async function cancel(){if(working.value&&operationId)try{await api.cancelScenario(operationId);}catch(e){error.value=String(e);}}
async function prepare(){
 if(working.value||props.busy)return false;
 preflightAttempted.value=true;
 if(preflightIssue.value)return false;
 if(assemblyRevision.value)await validate();
 else if(assemblyRecovery.value&&!draft.value)await resumeAssembly(assemblyRecovery.value);
 else if(!draft.value)await generate();else if(!valid.value)await validate();
 await nextTick();
 if(!valid.value&&!error.value)error.value='当前配置尚未满足所选引擎与必需模型的要求，请检查配置后重新生成。';
 return valid.value;
}
defineExpose({prepare,placeSelected,selectUnit,cancel});
</script>

<template>
 <section class="historical-setup" data-testid="historical-setup" aria-label="具名历史单位配置" :aria-busy="working">
  <p v-if="loading" role="status">正在核对历史编制与阶段…</p>
  <p v-if="error" role="alert" class="bad">{{error}} <button v-if="!working" @click="load(scopeChoice==='window'?undefined:phase)">重新读取</button></p>
  <div v-if="recoveryId" role="status"><p>参数已保存，尚未装载成功。重试沿用同一配置；若要改变需求，请重新生成。</p><button type="button" data-testid="retry-historical-load" :disabled="busy||working" @click="retryLoad">重试装载已保存配置</button></div>
  <fieldset class="scope-entry" data-testid="historical-scope-choice">
   <legend>推演范围</legend>
   <label>编制范围<select v-model="scopeChoice" :disabled="busy||working||loading&&!windowCatalog.length&&!versionCatalog.length" aria-label="编制范围" @change="chooseScope"><option value="">请选择会战或局部范围</option><option value="window" :disabled="!windowCatalog.length">限定会战窗口 · 指定日期与方向</option><option value="campaign">累计参战编制 · 分批部署</option><option value="phase">已核局部阶段 · 战术研究</option></select></label>
   <p v-if="!scopeChoice" class="note" role="status" data-testid="historical-scope-prompt">先明确本次推演范围，再生成初态。会战可选择多军协同窗口或累计编制；局部阶段仅覆盖已登记战斗。当前尚未请求模型。</p>
   <label v-if="scopeChoice==='window'">会战窗口<select v-model="windowChoice" :disabled="busy||working" aria-label="会战窗口" @change="changeWindow"><option value="">选择日期与方向范围</option><option v-for="w in visibleWindows" :key="w.id+'@'+w.version" :value="w.id+'@'+w.version">{{w.label}} · {{w.version}}</option></select></label>
   <label v-if="scopeChoice==='window'&&windowCatalog.length>visibleWindows.length||scopeChoice==='window'&&showWindowVersions" class="model-requirement"><input type="checkbox" v-model="showWindowVersions" :disabled="busy||working" aria-label="显示旧窗口版本">显示旧窗口版本</label>
   <p v-if="scopeChoice==='window'&&!windowChoice" class="note" role="status">请选择一个有明确日期与方向的窗口；局部窗口不代表整个会战。</p>
   <p v-if="scopeChoice==='campaign'" class="note">首次选择采用最新收录资料，可在下方切换版本。累计参战不是同日到场，须明确分批部署和保障。</p>
   <p v-if="scopeResolved&&basis?.ready" class="scope-summary" data-testid="historical-scope-summary"><b>{{basis.actors.length}} 个初态计算身份</b> · {{scopeChoice==='window'?'限定会战窗口':scopeChoice==='campaign'?'累计参战编制':'局部阶段'}} · 资料 {{basis.initial?.version}}。缺载兵额、装备与部署仍须显式估计。</p>
  </fieldset>
  <template v-if="basis&&scopeResolved">
   <label>战局结束方式<select v-model="terminationMode" aria-label="战局结束方式" :disabled="busy||working||loading"><option value="objectives">以目标完成为主（不设时间截止）</option><option value="deadline">限时完成（到期结算）</option></select></label>
   <p class="note" data-testid="termination-policy">{{objectiveDriven?'达到目标或目标方失去全部可用人员后结算；史料日期不作为自动结束时间。':'到达截止轮数时按目标完成情况结算，适用于限时练习。'}}改变结束方式需要重新生成配置。</p>
   <h3>{{purpose==='synthetic'?'1. 共同历史初态基础':'历史部队与计算阶段'}}</h3>
   <details v-if="basis.completed_configurations?.length&&!draft" data-testid="completed-historical-configurations"><summary>已验证的历史想定 · {{basis.completed_configurations.length}}份</summary>
    <p>读取已保存参数和验证记录，不重新请求模型；修改后仍须重新验证。</p>
    <article v-for="item in basis.completed_configurations" :key="item.id"><span>{{item.id.slice(0,8)}} · {{item.actor_count}}单位 · {{item.time_step}} · {{item.execution_backend==='afsim'?'AFSIM':'DSH'}}</span>
     <p v-if="configurationChoiceIssue(item)" :id="`configuration-choice-${item.id}`" :data-restore-issue="item.id" class="note" role="status">{{configurationChoiceIssue(item)}}</p>
     <button type="button" :data-open-configuration="item.id" :disabled="busy||working||!!configurationChoiceIssue(item)" :title="configurationChoiceIssue(item)||'读取已保存参数，不重新调用模型'" :aria-describedby="configurationChoiceIssue(item)?`configuration-choice-${item.id}`:undefined" @click="restoreCompleted(item)">读取这份想定</button>
    </article>
   </details>
   <p v-if="forceScope==='campaign'&&!basis.campaign_window" class="gap">累计参战序列并非同日部署。需补全到场、保障和多方向目标；缺载的下级番号与战场不会自动生成。可切换较新的史料版本查看补充编制。</p>
   <p v-if="basis.campaign_window" class="gap" data-testid="campaign-window-scope">窗口绑定史料 {{basis.initial?.version}} 与起始阶段；切回累计序列后可更改。<br>模型起点 {{basis.campaign_window.definition.bounds.start.replace('T',' ')}}，资料参考至 {{basis.campaign_window.definition.bounds.end.replace('T',' ')}}；开放推演仍按目标结束，日期不自动触发命令。<br>{{basis.actors.length}}个计算身份是建模候选，不是{{basis.actors.length}}个完整建制同时在场；人数、装备、到场与部署仍须显式估计。</p>
   <details v-if="basis.campaign_window" data-testid="campaign-window-evidence"><summary>窗口投入范围与未核项</summary><p>{{basis.campaign_window.definition.limitations}}</p>
    <article v-for="u in basis.actors" :key="u.id"><b>{{u.name}}</b><small>{{windowPresenceLabels[u.window_scope?.presence_basis??'']??'投入范围待核'}}</small><p>{{u.window_scope?.extent}}</p>
     <p v-if="u.window_scope?.parameter_estimates" :data-estimate-actor="u.id">本模型人数可选 {{u.window_scope.parameter_estimates.personnel.minimum}}—{{u.window_scope.parameter_estimates.personnel.maximum}} 人；初始位置工作半径 {{u.window_scope.parameter_estimates.position.radius_km}} km。人工设定的探索边界，非史实上下限或阵位精度。</p>
    </article>
   </details>
   <label v-if="value?.campaign_scope">会战到场计划边界<input v-model="value.campaign_scope.planning_end" :readonly="!!basis.campaign_window" aria-label="会战到场计划边界" placeholder="1938-10-27 00:00"></label>
   <label v-if="value?.campaign_scope">会战部署估计依据<textarea v-model="value.campaign_scope.assumption" aria-label="会战部署估计依据"></textarea></label>
   <details v-if="value?.campaign_scope?.remainders" data-testid="campaign-remainders"><summary>上级未细分余部：{{Object.keys(value.campaign_scope.remainders).length}} 项范围声明</summary>
    <p>仅列出下级不能证明整军完整。未列余部保持未知且未投入，不会自动补兵；完整覆盖须有来源。</p>
    <div v-for="(r,id) in value.campaign_scope.remainders" :key="id">
     <label>{{id}}<select v-model="r.policy" :aria-label="`${id}余部处理`"><option :value="null">待说明</option><option value="excluded_unquantified">余部未知且未投入</option><option value="covered_by_children">来源证明下级完整覆盖</option></select></label>
     <label>范围依据<textarea v-model="r.assumption" :aria-label="`${id}余部依据`"></textarea></label>
    </div>
   </details>
   <label v-if="(basis.versions?.length??0)>1">史料档案版本<select v-model="sourceVersion" :disabled="busy||working||!!basis.campaign_window" aria-label="史料档案版本" @change="load(undefined,sourceVersion)"><option v-for="v in basis.versions" :key="v.version" :value="v.version">{{v.version}}{{v.default?' · 默认':''}}</option></select></label>
   <p v-if="(basis.versions?.length??0)>1" class="note">版本选择决定本局的单位与阶段依据，生成后随草稿冻结。新增档案不代表整场历史推演已经验收。</p>
   <details v-if="basis.pending_configurations?.length&&!draft" data-testid="pending-historical-configurations"><summary>已保存但尚未装载的配置 · {{basis.pending_configurations.length}}份</summary><p>以下配置与当前史料版本和阶段一致，可直接重试装载。执行引擎和回合跨度须与保存时一致。</p><div v-for="item in basis.pending_configurations" :key="item.id"><span>{{item.id.slice(0,8)}} · {{item.execution_backend==='afsim'?'AFSIM':'DSH'}} · {{item.time_step}}</span><button type="button" :data-retry-configuration="item.id" :disabled="busy||working||item.execution_backend!==executionBackend||stepDurationSeconds(item.time_step)!==stepDurationSeconds(timeStep)||(item.termination_mode??'deadline')!==terminationMode" @click="recoveryId=item.id;retryLoad()">装载这份配置</button></div></details>
   <label v-if="basis.phases.length">起始阶段<select v-model="phase" :disabled="busy||working||!!basis.campaign_window" aria-label="历史起始阶段" @change="load(phase)"><option v-for="p in basis.phases" :key="p.id" :value="p.id">{{p.label}} · {{p.date}}{{p.ready?'':' · 尚缺绑定'}}</option></select></label>
   <p v-if="basis.execution_window" class="gap" data-testid="historical-window">{{objectiveDriven?'史料参考时间窗':'当前计算窗口'}}<template v-if="basis.execution_window.start"> <time :datetime="basis.execution_window.start">{{basis.execution_window.start.replace('T',' ')}}</time> 至</template><template v-else>截止</template> <time :datetime="basis.execution_window.end">{{basis.execution_window.end.replace('T',' ')}}</time>。{{basis.execution_window.note}}<template v-if="objectiveDriven">允许从历史初态继续推演到窗外；后续援军与事件不会自动补入，延伸结果为反事实估计。</template></p>
   <p v-if="stepWindowIssue" class="gap" role="alert" data-testid="historical-step-gap">{{stepWindowIssue}}</p>
   <p v-if="basis.geographic_scope" class="note" data-testid="historical-region">阶段地域参考：{{basis.geographic_scope.center.lat.toFixed(5)}}, {{basis.geographic_scope.center.lng.toFixed(5)}}，计算范围半径 {{basis.geographic_scope.radius_km}} km。{{basis.geographic_scope.note}}</p>
   <p v-if="basis.interaction" class="note" data-testid="historical-noncontact-scope"><b>非接敌转移阶段</b> · {{basis.interaction.scope}} 本窗不生成场外对手；不是整个战役不存在敌军。</p>
   <details v-if="basis.excluded_references?.length" data-testid="historical-exclusions"><summary>保留但不在本局初态部署的参考 · {{basis.excluded_references.length}}项</summary><p v-for="u in basis.excluded_references" :key="u.id">{{u.name}} · {{u.status==='later_participant'?'后续参战，当前未到场':'未纳入当前计算范围，不代表史实未参战'}}</p></details>
   <p v-if="!basis.ready" role="status" data-testid="historical-configuration-gap" class="gap">{{basis.error}}。请选择有依据的阶段；本入口不自动替换为教学编组。</p>
   <section v-if="!basis.ready&&basis.configuration_alternatives?.length" data-testid="historical-configuration-alternatives" aria-label="可选的计算范围">
    <p class="note">当前选择未通过准入。下列入口需要您明确选择，系统不会自动改动版本或把累计参战当作同日部署。</p>
    <article v-for="choice in basis.configuration_alternatives" :key="choice.version+':'+choice.force_scope">
     <p>{{choice.scope}} · 地面 {{choice.actor_count}} 个计算单位，航空 {{choice.aviation_count}} 个资源池</p>
     <button type="button" :disabled="busy||working||loading" :data-admission-choice="choice.version+':'+choice.force_scope" @click="chooseAlternative(choice)">选择 {{choice.version}} · {{choice.force_scope==='campaign'?'会战编制与分批到场':'局部阶段'}} · {{choice.label}}</button>
    </article>
   </section>
   <template v-else>
    <p v-if="!basis.campaign_window" class="note">{{basis.scope}}。缺载人数、装备与部署按明确说明的模型参数处理；真实番号与隶属只读。当前仅覆盖本阶段档案登记，完整性见来源说明。</p>
    <details v-if="basis.input_constraints" data-testid="historical-input-constraints"><summary>史料参考与输入约束 · 数值范围、入口区域仍含建模假设</summary>
     <article v-for="r in basis.input_constraints.personnel" :key="r.unit_id"><b>{{basis.actors.find(a=>a.id===r.unit_id)?.name??r.unit_id}} · {{r.minimum}}—{{r.maximum}}人</b><p>{{r.reported}}</p><p>{{r.assumption}}</p></article>
     <article v-for="r in basis.input_constraints.entries" :key="r.id"><b>{{r.reference_kind==='departure'?'启程参考':'接敌参考'}} · {{r.label}}</b><p>{{r.earliest}} — {{r.latest}}；<template v-if="r.region">参考区域 {{r.region.center.lat}}, {{r.region.center.lng}}，半径{{r.region.radius_km}}公里。</template><template v-else>未据此推定接敌位置与时刻。</template></p><p>{{r.assumption}}</p><p v-for="e in r.evidence" :key="e.source_id+e.locator"><a :href="basis.initial?.definition.sources[e.source_id]?.url" target="_blank" rel="noopener noreferrer">{{basis.initial?.definition.sources[e.source_id]?.title}}</a>：{{e.locator}}</p></article>
    </details>
    <div v-if="basis.objective_guidance" class="goal-source" data-testid="historical-goal-guidance"><b>阶段任务建议 · {{basis.objective_guidance.objective_label}}</b><p>{{basis.objective_guidance.scope_note}}</p><details><summary>来源与未覆盖过程</summary><p v-for="s in basis.objective_guidance.sources" :key="s.id"><a :href="s.url" target="_blank" rel="noopener noreferrer">{{s.title}}</a>：{{s.locator}}</p><p>尚未覆盖：{{basis.objective_guidance.not_covered.join('；')}}。</p></details></div>
    <details data-testid="historical-basis">
     <summary>真实部队与史料来源 · {{basis.actors.length}}个计算候选／{{basis.initial?.definition.units.length??0}}个身份档案</summary>
     <p class="note">身份档案包括上级、下级和不同日期的参考，不能相加为同时到场部队或总人数。未单独计兵不等于未参战；计算候选仍须生成参数并完整校验。</p>
     <article v-for="u in basis.initial?.definition.units" :key="u.id" :data-source-unit="u.id" :data-computation-scope="calculationUnitIds.has(u.id)?'candidate':'reference'">
      <b>{{u.name}}</b><small>{{u.echelon}} · {{u.id}} · {{calculationUnitIds.has(u.id)?'本页独立计算候选':u.role==='command'?'指挥／统计参考，不作为等额步兵':'参考身份，本页不单独计兵'}}</small>
      <p v-for="(e,i) in u.evidence" :key="i"><a :href="basis.initial?.definition.sources[e.source_id]?.url" target="_blank" rel="noopener noreferrer">{{basis.initial?.definition.sources[e.source_id]?.title}}</a>：{{e.locator}}</p>
     </article>
     <p v-for="note in basis.initial?.definition.coverage.notes" :key="note">{{note}}</p>
    </details>
    <p class="note" data-testid="historical-selected-step">回合跨度 {{timeStep}}，按上方选择生成；更改后需重新验证阶段时间范围与截止轮数。</p>
    <label>计算参数与推演目标需求<textarea v-model="instruction" rows="3" maxlength="4000" :disabled="busy||working" placeholder="描述所选阶段、双方部署意图和目标；回合跨度以上方选择为准，缺载数值将说明估计依据。"></textarea></label>
    <label class="model-requirement"><input type="checkbox" v-model="requireTimeSustainment" :disabled="busy||working||requireSupplySchedule||!!assemblyRevision" aria-label="生成时必须按时间计算粮秣">要求按时间计算粮秣与缺粮影响</label>
    <label v-if="requireTimeSustainment||requireSupplySchedule">生成时采用的耗粮模型<select v-model="rationModel" aria-label="生成时采用的耗粮模型" :disabled="busy||working||!!assemblyRevision"><option value="time-sustainment-1">按编组工作量（原模型）</option><option value="personnel-rations-1">按人数与粮食质量</option></select></label>
    <p v-if="draft&&requireTimeSustainment&&value?.support_dynamics?.version!==rationModel" class="gap" role="status">草稿耗粮模型与当前生成要求不一致，请切换下方模型并重新验证，或重新生成。不会自动转换既有库存。</p>
    <label class="model-requirement"><input type="checkbox" v-model="requireMovementFeedback" :disabled="busy||working||!!assemblyRevision" aria-label="生成时必须校验运动与疲劳反馈">要求按通信、疲劳、压制与燃油约束机动</label>
    <label class="model-requirement"><input type="checkbox" v-model="requireClassifiedFire" :disabled="busy||working||!!assemblyRevision" aria-label="生成时必须使用分类炮弹计量">要求炮击按分类炮弹记账</label>
    <label class="model-requirement"><input type="checkbox" v-model="requireLiveDensity" :disabled="busy||working||!!assemblyRevision" aria-label="生成时必须使用动态密度">要求同批射击前更新目标密度</label>
    <label class="model-requirement"><input type="checkbox" v-model="requireSuppressionCarry" :disabled="busy||working||!!assemblyRevision" aria-label="生成时必须保留连续压制余量">要求跨轮保留压制余量（同时使用动态密度）</label>
    <p v-if="requireSuppressionCarry&&draft&&value?.fire_dynamics?.version!=='live-footprint-density-2'" class="gap" role="status">当前草稿未采用连续压制版本，请重新生成或明确选择后再验证。</p>
    <p v-if="requireLiveDensity&&draft&&!value?.fire_dynamics" class="gap" role="status">草稿缺少动态密度火力过程选择，请补齐并重新验证，或重新生成。</p>
    <p v-if="requireClassifiedFire&&draft&&!value?.fire_accounting" class="gap" role="status">草稿缺少分类炮弹计量选择，请补齐并重新验证，或重新生成。</p>
    <p v-if="value?.movement_feedback" class="note" data-testid="movement-feedback-enabled">本配置已启用机动与疲劳反馈：普通陆地命令按有效路段，桥梁与舟艇按通路回执校验；船载位移与陆地消耗分开。{{value.movement_feedback.assumption}}</p>
    <p v-if="requireMovementFeedback&&draft&&!value?.movement_feedback" class="gap" role="status">当前草稿缺少运动反馈规则，请重新生成并验证。不会自动改写旧对局。</p>
    <p v-if="requireTimeSustainment&&draft&&!value?.support_dynamics" class="gap" role="status">当前草稿缺少按时耗粮模型。请重新生成，或在下方粮秣配置中启用并填写后验证；不会自动退回每回合规则。</p>
    <label class="model-requirement"><input type="checkbox" v-model="requireSupplySchedule" :disabled="busy||working||requireFerry||!!assemblyRevision" aria-label="生成时必须配置定时补给">要求定时补给与仓库共享装卸能力（陆上服务）</label>
    <p v-if="requireSupplySchedule&&draft&&!value?.supply_schedule" class="gap" role="status">当前草稿缺少定时补给。请重新生成，或启用下方定时补给并填写、重新验证。</p>
    <label class="model-requirement"><input type="checkbox" v-model="requireFerry" :disabled="busy||working||requireSupplySchedule||!!assemblyRevision" aria-label="生成时必须配置舟艇">生成舟艇运输模型</label>
    <p v-if="requireFerry&&draft&&!value?.facility.crossing_model?.ferry" class="gap" role="status">当前草稿缺少舟艇。请重新生成，或在下方渡河配置中启用并填写舟艇后验证。</p>
    <FixedParameterInputs :model-value="fixedParameters" :fields="basis.fixed_parameter_fields??[]" :parameters="value" :required-models="requiredModels" :disabled="busy||working||!!assemblyRevision" @update:model-value="changeFixed" @valid="fixedReady=$event" @apply="applyFixed" />
    <details v-if="basis.pending_assemblies?.length&&!draft&&!assemblyRevision" data-testid="pending-historical-assemblies" :open="!!assemblyRecovery">
     <summary>可继续的分片草稿 · {{basis.pending_assemblies.length}}份</summary>
     <p>沿用已保存的史料、需求与固定数值，只继续未完成分片；不会采用本页后来改动的输入。全部单位校验和所选引擎装载成功后，才可创建战局。</p>
     <article v-for="item in basis.pending_assemblies" :key="item.id" :data-assembly-id="item.id">
      <b>已校验 {{item.validated_actors}} / {{item.total_actors}} 个单位{{item.status==='configured'?' · 待装载':''}}</b>
      <small>{{item.id.slice(0,8)}} · {{item.execution_backend==='afsim'?'AFSIM':'DSH'}} · {{item.time_step}} · {{item.required_models.join('、')||'无附加保障模型'}} · {{item.fixed_count}}项固定值</small>
      <p v-if="resumeIssue(item)" class="note">{{resumeIssue(item)}}</p>
      <button type="button" :data-resume-assembly="item.id" :disabled="busy||working||!!resumeIssue(item)" @click="resumeAssembly(item)">继续已保存的分片配置</button>
      <template v-if="item.can_rebuild_failed_session">
       <p class="note">若原会话反复无法提交，可重建尚未写入的失败单位片会话。已校验单位和旧会话轨迹保留，新会话将重新读取本片资料。</p>
       <button type="button" :data-rebuild-assembly="item.id" :disabled="busy||working||!!resumeIssue(item)" @click="resumeAssembly(item,true)">重建失败分片会话并继续</button>
      </template>
      <template v-if="item.can_revise_configuration">
       <p class="note">最终校验失败时，可读取原参数，修正后另存新想定。原草稿、DSH会话与失败记录不改动；修订仍须完整校验。</p>
       <button type="button" :data-revise-assembly="item.id" :disabled="busy||working||!!resumeIssue(item)" @click="reviseAssembly(item)">修订失败配置（保留原草稿）</button>
      </template>
     </article>
    </details>
    <button @click="generate" :disabled="busy||working||!available||!fixedReady" data-testid="generate-historical-scenario">{{assemblyRecovery?'重新生成全部（新草稿）':'DSH调用历史单位skill生成并验证'}}</button>
    <p v-if="working" role="status" aria-live="polite" data-testid="historical-build-progress">{{stageLabel}}</p>
    <p v-if="!draft&&!assemblyRevision" class="note">生成前不放置虚构军标。配置完成后，可编辑估计参数并在地图选择部署位置。</p>
    <section v-if="assemblyRevision" class="note" role="status" data-testid="failed-configuration-revision">
     <b>正在修订未通过完整校验的DSH配置</b><p>{{assemblyRevision.last_error}}</p>
     <p v-if="assemblyRevision.validation_error" class="bad">当前输入校验：{{assemblyRevision.validation_error}}</p>
     <table v-if="assemblyRevision.food_loading_errors.length" data-testid="original-food-loading-errors"><caption>原草稿初粮问题（容量来自模型假设；编辑后需重新校验）</caption><thead><tr><th>单位</th><th>原粮食工作量</th><th>携行容量工作量</th><th>原粮食／容量 kg</th></tr></thead><tbody><tr v-for="row in assemblyRevision.food_loading_errors" :key="row.unit"><td>{{basis.actors.find(u=>u.id===row.unit)?.name??row.unit}}</td><td>{{row.food_work}}</td><td>{{row.capacity_work}}</td><td>{{row.food_mass_kg}}／{{row.capacity_kg}}</td></tr></tbody></table>
     <p>原始记录 {{assemblyRevision.id.slice(0,8)}} 保留。请在下方参数栏修正，再完整验证；验证成功后提供地图预览和新想定。原固定数值与模型要求保持；本页修订不调用DSH重写参数。</p>
     <button type="button" :disabled="busy||working" @click="clear()">退出修订</button>
    </section>
    <template v-if="(draft||assemblyRevision)&&value">
     <div v-if="value.campaign&&value.campaign_scope&&!value.campaign_plan&&value.goal.profile==='delay'&&!value.campaign.objective_policy" role="status" data-testid="legacy-campaign-delay"><p>此旧配置声明迟滞目标，但其原规则按据点夺控判定。请明确启用防御迟滞规则并重新验证；旧存档不会自动更改。</p><button type="button" :disabled="busy||working" @click="enableDefensiveDelay">启用防御迟滞规则</button></div>
     <p :class="valid?'verified':'note'" role="status" data-testid="historical-validation">{{valid?(executionBackend==='afsim'?'当前具名单位配置已通过AFSIM实际装载；可创建战局。':'当前具名单位配置已校验；未启动AFSIM，可创建DSH战局。'):'配置或执行引擎已改变；创建前需要重新验证。'}}</p>
     <details v-if="draft"><summary>DSH生成时的估计依据与限制（编辑后需复核）</summary><p>{{draft.construction.explanation}}</p><p>{{value.clock.assumption}}</p><small>{{draft.construction.skill}} · {{draft.afsim?draft.afsim.entity_count+'个原生作战实体':'DSH配置校验'}} · {{draft.id}}</small></details>
     <p v-if="valid&&draft" class="note" data-testid="verified-objective">{{draft.preview_world.mission?.definition.goal}}</p>
     <p v-if="value.campaign_plan" class="note" data-testid="campaign-graph-help">{{goalHelp}}。</p>
     <SustainmentPanel v-if="valid&&draft?.sustainment" :value="draft.sustainment" />
     <CampaignObjectives v-if="value.campaign_plan&&draft?.preview_world.campaign_plan" :configuration="value.campaign_plan" :state="draft.preview_world.campaign_plan" :required-turns="value.goal.required_turns" />
     <CampaignGoalInputs v-if="value.campaign_plan" :value="value.campaign_plan" :disabled="busy||working" @pick-goal="pickGoal" />
     <fieldset v-if="!value.campaign_plan" :disabled="busy||working" class="goal-editor" data-testid="historical-goal-editor"><legend>{{value.campaign?'据点目标与战役截止':'局部目标与判定条件'}}</legend>
      <div class="grid"><label>目标方<select v-model="goalOwner" aria-label="目标方"><option value="red" :disabled="!!basis.interaction&&!basis.interaction.active_teams.includes('red')">红方</option><option value="blue" :disabled="!blueProfiles.has(goalProfile)||!!basis.interaction&&!basis.interaction.active_teams.includes('blue')">蓝方</option></select></label>
       <label>目标类型<select v-model="goalProfile" aria-label="目标类型" :disabled="!!value.campaign&&!value.campaign_scope"><option v-for="[id,label] in goalProfiles" :key="id" :value="id" :disabled="goalOwner==='blue'&&!blueProfiles.has(id)||!!basis.interaction&&!['crossing','breakout'].includes(id)||!!value.campaign&&!['assault','delay'].includes(id)">{{label}}</option></select></label>
       <label>{{objectiveDriven?'滚动规划参考轮数':'截止回合'}}<input type="number" v-model.number="value.goal.deadline_turn" min="1" max="100000" aria-label="目标截止回合"></label>
       <label>连续达标回合<input type="number" v-model.number="value.goal.required_turns" :disabled="!usesProgress" min="1" :max="objectiveDriven?100000:value.goal.deadline_turn" aria-label="目标连续回合"></label>
       <label>存续编组门槛<input type="number" v-model.number="survivors" :disabled="!usesSurvivors" min="1" :max="goalActorCount" aria-label="目标存续编组"></label>
       <label>目标半径 km<input type="number" v-model.number="value.goal.radius_km" :disabled="!['assault','crossing'].includes(goalProfile)" min="0.01" :max="value.area.radius_km" step="0.05" aria-label="目标半径"></label>
       <label>目标纬度<input type="number" v-model.number="value.goal.objective.lat" :disabled="!['assault','crossing'].includes(goalProfile)" min="-90" max="90" step="0.0001" aria-label="目标纬度"></label>
       <label>目标经度<input type="number" v-model.number="value.goal.objective.lng" :disabled="!['assault','crossing'].includes(goalProfile)" min="-180" max="180" step="0.0001" aria-label="目标经度"></label>
       <template v-if="usesExit"><label>出口纬度<input type="number" v-model.number="value.goal.exit.lat" min="-90" max="90" step="0.0001" aria-label="出口纬度"></label><label>出口经度<input type="number" v-model.number="value.goal.exit.lng" min="-180" max="180" step="0.0001" aria-label="出口经度"></label></template>
      </div><p class="note">{{goalHelp}}。存续门槛按目标方编组数量计算，当前{{goalActorCount}}个；目标方不等于用户操纵方。{{objectiveDriven?'未达成时继续推演，不因参考轮数到期判负。':basis.interaction?'未达成时记录转移目标失败，不产生虚构对手胜利。':'未达成时由另一方获胜。'}}</p>
      <p v-if="!goalValid" class="bad" role="status">请核对目标方、正整数门槛、连续回合与截止，以及有效坐标和范围。</p>
      <p v-else-if="!valid" class="note" role="status">目标属于未验证草稿；重新校验后更新正式判定说明。</p>
     </fieldset>
     <CampaignParametersEditor v-if="value.campaign" :value="value.campaign" :actors="basis.actors" :partitions="value.partitions" :constraints="basis.input_constraints" :center="value.area.center" :disabled="busy||working" :objective-graph="!!value.campaign_plan" :non-contact="!!basis.interaction" @pick-region="pickRegion" />
     <OperationBoundaryEditor :model-value="value.operation_boundary" :area="value.area" :compatible="!!value.campaign_plan" :disabled="busy||working" @pick="pickBoundary" @update:model-value="v=>{if(value){if(v)value.operation_boundary=v;else delete value.operation_boundary;}}" />
     <CrossingParametersEditor :facility="value.facility" :rules="value.rules" :disabled="busy||working" />
     <FormationPartsEditor v-model="value.partitions" :actors="value.actors" :basis="basis.actors" :disabled="busy||working" @select="pickPart" />
     <p class="note" data-testid="current-configuration-clock">当前计算起点 {{value.clock.start}} · {{value.clock.time_step}}/轮 · {{objectiveDriven?'按目标完成，不设自动截止':'截止第'+value.goal.deadline_turn+'轮'}}。</p>
     <details v-for="u in basis.actors" :key="u.id" class="actor" :open="purpose!=='synthetic'" :data-historical-actor="u.id"><summary>{{u.team==='red'?'红方':'蓝方'}} · {{u.name}} · {{u.echelon}}</summary>
      <p v-if="u.window_scope" class="note">{{u.window_scope.extent}}</p>
      <fieldset :disabled="busy||working"><small>{{u.id}} · 番号不可编辑</small><button @click="pick(u.id)" :disabled="!draft" :title="!draft?'完整校验成功后可编辑地图部署':undefined" :aria-label="`地图部署${u.name}`">地图部署</button>
       <p>位置 {{value.actors[u.id]!.position.lat.toFixed(5)}}, {{value.actors[u.id]!.position.lng.toFixed(5)}}（计算部署）</p>
       <div class="grid"><label>人员（估计/人）<input type="number" v-model.number="value.actors[u.id]!.personnel" :min="u.window_scope?.parameter_estimates?.personnel.minimum??1" :max="u.window_scope?.parameter_estimates?.personnel.maximum??100000000" :readonly="u.facts.personnel.value!==null" :aria-label="`${u.name}人员`"></label>
        <label v-for="[key,label] in equipment" :key="key">{{label}}<input type="number" v-model.number="value.actors[u.id]!.equipment[key]" min="0" :aria-label="`${u.name}${label}`"></label>
        <label>速度 km/h<input type="number" v-model.number="value.actors[u.id]!.speed" min="0" step="0.1"></label><label>直射范围 m<input type="number" v-model.number="value.actors[u.id]!.attack_range_m" min="0"></label>
        <label>粮食工作量<input type="number" v-model.number="value.actors[u.id]!.logistics.food" min="0" max="100"></label><label>弹药工作量<input type="number" v-model.number="value.actors[u.id]!.logistics.ammo" min="0" max="100"></label>
       </div><label>估计依据<textarea v-model="value.actors[u.id]!.assumption" rows="2"></textarea></label>
      </fieldset>
     </details>
     <AviationParametersEditor v-if="value.aviation" :parameters="value.aviation" :identities="basis.aviation" :disabled="busy||working" />
     <SupportDynamicsEditor :model-value="value.support_dynamics" :scheduled="!!value.supply_schedule" :disabled="busy||working" @update:model-value="v=>{if(value){if(v){value.support_dynamics=v;rationModel=v.version;}else delete value.support_dynamics;}}" />
     <FireAccountingEditor :model-value="value.fire_accounting" :dynamics="value.fire_dynamics" :disabled="busy||working" @update:model-value="v=>{if(value){if(v)value.fire_accounting=v;else delete value.fire_accounting;}}" @update:dynamics="v=>{if(value){if(v)value.fire_dynamics=v;else delete value.fire_dynamics;}}" />
     <SplitSupplyEditor :model-value="value.supply_distribution" :disabled="busy||working" @update:model-value="v=>{if(value){if(v)value.supply_distribution=v;else delete value.supply_distribution;}}" />
     <SupplyScheduleEditor :model-value="value.supply_schedule" :node-ids="(basis.interaction?.active_teams??['red','blue']).map(team=>team+'-historical-supply')" :compatible="!!value.support_dynamics&&!!value.supply_distribution&&value.rules.bridge_enabled===false" :disabled="busy||working" @update:model-value="v=>{if(value){if(v)value.supply_schedule=v;else delete value.supply_schedule;}}" />
     <button @click="validate" :disabled="busy||working||!fieldValid||!fixedReady||valid" data-testid="validate-historical-scenario">{{executionBackend==='afsim'?'重新装载验证历史配置':'重新校验DSH配置'}}</button>
    </template>
   </template>
  </template>
 </section>
</template>

<style scoped>
.historical-setup{border-block:1px solid #294553;padding:14px 0;margin:12px 0;font-size:12px;line-height:1.6}h3{font-size:14px;margin:0 0 10px}.note,small{color:#9db6c5}.gap{border-left:2px solid #e0ba76;padding-left:12px;color:#e0c18b}.verified{color:#85cfa9}label{display:block;margin-top:9px;color:#aec6d2}input,select,textarea{display:block;width:100%;box-sizing:border-box;margin-top:4px}fieldset{border:0;padding:12px 0;min-width:0}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px 12px}.actor{border-top:1px solid #294553;padding-top:10px;margin-top:14px}summary{cursor:pointer;color:#cfdee4}small{display:block;overflow-wrap:anywhere}button{font-size:11px;margin-top:8px}article{border-bottom:1px solid #294553;padding:8px 0}a{color:#8cd9d0}@media(max-width:600px){.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
.goal-source{border-left:2px solid #7dbcc1;padding:8px 12px;margin:10px 0;color:#b8cdd7}.goal-source p{margin:6px 0}.goal-editor{border-block:1px solid #294553;margin:12px 0}.goal-editor legend{color:#cfdee4;padding-right:10px}
.model-requirement{display:flex;align-items:center;gap:8px}.model-requirement input{width:auto;margin:0}
.scope-entry{border-bottom:1px solid #294553}.scope-entry legend{font-size:14px;color:#cfdee4}.scope-summary{color:#c5dbe5;overflow-wrap:anywhere}.scope-summary b{color:#91d8cc}
</style>
