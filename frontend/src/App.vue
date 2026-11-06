<script setup lang="ts">
// 薄 UI 编排：与 app.py 的侧栏/地图/战报三区结构对齐，
// 所有「数据实况」caption（交战统计、史料注入、守恒提示）照搬旧版文案口径。
import { computed, nextTick, onMounted, onBeforeUnmount, reactive, ref, watch } from "vue";
import { api } from "./api";
import type { Battle, Health, NumericFlag, Snapshot, CommandPreview, ScenarioSelection, RuntimeProgress, RuntimeOperation, SyntheticConfiguration, Notice,FormationConversionCommit } from "./types";
import AFSimPanel from './components/AFSimPanel.vue';
import AirOperationsPanel from './components/AirOperationsPanel.vue';
import CombinedArmsPanel from './components/CombinedArmsPanel.vue';
import HistoryReplayPanel from './components/HistoryReplayPanel.vue';
import HistoricalRosterPanel from './components/HistoricalRosterPanel.vue';
import CommandCenter from './components/CommandCenter.vue';
import UnitInspector from './components/UnitInspector.vue';
import ForceOrganizationPanel from './components/ForceOrganizationPanel.vue';
import MilitaryPlottingPanel from './components/MilitaryPlottingPanel.vue';
import type {PlotItem,PlottingView,MapPoint} from './types';
import ImportSession from './components/ImportSession.vue';
import MissionPanel from "./components/MissionPanel.vue";
import { normalizeStep, stepOptions } from "./timeSteps";
import MapView from "./components/MapView.vue";
import MapWorkbench from './components/MapWorkbench.vue';
import appPackage from '../package.json';
import BattlefieldPanel from "./components/BattlefieldPanel.vue";
import AdjudicationPanel from "./components/AdjudicationPanel.vue";
import CausalPanel from "./components/CausalPanel.vue";
import LlmSettings from "./components/LlmSettings.vue";
import LaunchScreen from './components/LaunchScreen.vue';
import { RENDERER_VERSION, summarizeEngagements } from "./tactical";
import { mdToHtml } from "./markdown";

const TIME_STEPS = computed(() => stepOptions(opts.time_step));
const appVersion = appPackage.version;
const turnInstruction = ref("");
const commandCenter = ref<InstanceType<typeof CommandCenter> | null>(null);
const commandPreview = ref<CommandPreview | null>(null);
const selectedUnit = ref<{ team: string; name: string } | null>(null);
const commandPicking = ref<'move' | 'fire' | null>(null);
const forcePanel=ref<InstanceType<typeof ForceOrganizationPanel>|null>(null),forcePicking=ref(false);
function pickForceTarget(){forcePicking.value=true;commandCenter.value?.close();plotPicking.value=false;workbench.value?.focusMap();}
function mapCommandTarget(point:MapPoint){if(forcePicking.value){forcePanel.value?.mapPoint(point);forcePicking.value=false;workbench.value?.openAnalysis('forces');}else commandCenter.value?.mapTarget(point);}
function selectMapUnit(team:string,name:string){workbench.value?.focusMap();if(strictReplay.value)selectedUnit.value={team,name};else commandCenter.value?.select(team,name);}
async function forceChanged(){await commandCenter.value?.refresh();}
async function submitFormation(sid:string,request:FormationConversionCommit){
 if(busy.value)throw Error('当前操作尚未完成，请稍后使用原请求重试');
 busy.value='正在保存实体编组…';
 try{
  const response=await api.commitFormation(sid,request);
  const current=await api.get(sid);
  if(sessionId.value===sid){
   commandSnapshot(current);selectedUnit.value=null;commandPreview.value=null;
   await commandCenter.value?.applyConversion(response.conversion_result.current_command_map);
   await forcePanel.value?.refresh();
  }
  return response;
 }finally{if(sessionId.value===sid)busy.value='';}
}

const plottingPanel=ref<InstanceType<typeof MilitaryPlottingPanel>|null>(null);
const plotPicking=ref(false),plotPreview=ref<PlotItem[]>([]);
function plottingChanged(value:PlottingView){if(snap.value)snap.value={...snap.value,plotting:value};}
function plottingPick(value:boolean){plotPicking.value=value;if(value){commandCenter.value?.close();workbench.value?.focusMap();}}
async function selectPlotting(id:string){tab.value='plotting';workbench.value?.openAnalysis('plotting');await nextTick();plottingPanel.value?.edit(id);}
function plottingPoint(point:MapPoint){plottingPanel.value?.mapPoint(point);}
function commandSnapshot(value: Snapshot) {
  if (value.session_id !== sessionId.value) { sessionId.value = value.session_id; localStorage.setItem('gentactix-session', value.session_id); restoreOptions(value); }
  apply(value);
}

const health = ref<Health | null>(null);
const battles = ref<Battle[]>([]);
const corpus = ref<{ files: number; chunks: number; chars: number; dir: string } | null>(null);
const snap = ref<Snapshot | null>(null);
const sessionId = ref<string>("");
const recentSessions = ref<{ session_id: string; turn_count: number; scenario: string }[]>([]);
const screen = ref<'launch' | 'workspace'>('launch');
const settingsDialog = ref<HTMLDialogElement | null>(null);
const importDialog = ref<InstanceType<typeof ImportSession> | null>(null);
function openImport() { if (!busy.value) void importDialog.value?.open(); }
async function importedSession(value: Snapshot) {
  commandSnapshot(value); restoreOptions(value); screen.value = 'workspace';
  recoverRunningOperation(value.session_id);
  try { recentSessions.value = (await api.sessions()).sessions; } catch { /* Session is already restored. */ }
}
const deleteDialog = ref<HTMLDialogElement | null>(null);
const pendingDelete = ref<{ session_id: string; turn_count: number; scenario: string } | null>(null);
const deleting = ref(false);
const deleteError = ref('');
const settingsPanel = ref<InstanceType<typeof LlmSettings> | null>(null);
const workbench = ref<InstanceType<typeof MapWorkbench> | null>(null);
let unsubscribeMenu: (() => void) | undefined;
function openSettings() { settingsDialog.value?.showModal(); void settingsPanel.value?.reload(); }
async function requestDelete(saved: { session_id: string; turn_count: number; scenario: string }) {
  if (busy.value) return;
  pendingDelete.value = saved; deleteError.value = '';
  await nextTick(); deleteDialog.value?.showModal();
}
async function confirmDelete() {
  const saved = pendingDelete.value;
  if (!saved || deleting.value || busy.value) return;
  deleting.value = true; busy.value = '正在删除存档…'; deleteError.value = '';
  try {
    await api.deleteSession(saved.session_id);
    recentSessions.value = recentSessions.value.filter(s => s.session_id !== saved.session_id);
    if (sessionId.value === saved.session_id) {
      sessionId.value = ''; snap.value = null; screen.value = 'launch';
      progress.value = {}; notices.value = []; error.value = ''; chatInput.value = '';
      tab.value = 'reports';
    }
    if (localStorage.getItem('gentactix-session') === saved.session_id) localStorage.removeItem('gentactix-session');
    deleteDialog.value?.close(); pendingDelete.value = null;
    await nextTick();
    document.querySelector<HTMLButtonElement>('.creation-modes button[aria-selected="true"]')?.focus();
  } catch (e) { deleteError.value = String(e); }
  finally { deleting.value = false; busy.value = ''; }
}
async function resumeSession(id: string) {
  if (await run('正在载入战局…', () => api.get(id), false)) {
    if (snap.value) restoreOptions(snap.value);
    sessionId.value = id; localStorage.setItem('gentactix-session', id); screen.value = 'workspace';
    recoverRunningOperation(id);
  }
}
function startScenario(value: ScenarioSelection) {
  if (value.execution_backend === 'afsim') { opts.use_agent_tools = false; opts.use_live_intel = false; opts.agent_mode = 'native'; }
  Object.assign(opts, value); if (value.mission_id||value.historical_parameters) { opts.use_agent_tools = false; opts.use_live_intel = false; } void init();
}
onBeforeUnmount(() => unsubscribeMenu?.());

const opts = reactive({
  scenario: "长平之战，前262年，秦赵上党对峙",
  time_step: "30分钟",
  use_adjudicator: false,
  battle: "" as string, // "" = 自动匹配
  use_rag: false, // 与旧 Streamlit 侧栏同默认：默认关闭，开启才受史料约束
  use_live_intel: false,
  use_agent_tools: false, // 智能体回合：默认关，开启后每回合多次模型往返
  persist_roles: true,
  agent_mode: 'native',
  simulation_mode: 'open', mission_id: '' as string | null,
  product_mode: undefined as ScenarioSelection['product_mode'],
  execution_backend: 'narrative' as 'narrative' | 'afsim',
  synthetic_configuration: null as SyntheticConfiguration | null,
  scenario_draft_id: null as string | null,
  historical_parameters:null as ScenarioSelection['historical_parameters'],
  historical_source_version:null as string|null,
});

const selftest = ref(false);
const ragOpen = ref(false);

// 战役文件里的 time_step 提示：选中某场战役即预填建议回合跨度
const battleHint = computed(() => battles.value.find((b) => b.name === opts.battle)?.time_step ?? "");
function applyBattleHint() {
  const hint = battleHint.value;
  opts.mission_id = '';
  opts.synthetic_configuration = null;
  opts.scenario_draft_id = null;
  opts.historical_parameters=null;
  opts.historical_source_version=null;
  if (hint) opts.time_step = normalizeStep(hint);
}

const busy = ref("");
const progress = ref<RuntimeProgress>({});
const operationOutcome = ref<'success' | 'failed' | 'cancelled' | null>(null);
const cancelPending = ref(false), progressDisconnected = ref(false);
const recoveredOperation=ref<{sid:string;id:string|null;activeSeen:boolean;settling:number}|null>(null);
function recoverRunningOperation(sid:string){
  if(!sid||sid!==sessionId.value||busy.value)return;
  recoveredOperation.value={sid,id:null,activeSeen:false,settling:0};
  operationOutcome.value=null;progress.value={};cancelPending.value=false;busy.value='正在确认后台任务…';
}
function setChildBusy(label: string) {
  if(recoveredOperation.value)return;
  if (label && !busy.value) { operationOutcome.value = null; progress.value = {}; error.value = ''; }
  busy.value = label;
}
watch([busy, sessionId], ([label, sid], old, cleanup) => {
  if (sid !== old?.[1]) { progress.value = {}; operationOutcome.value = null; }
  progressDisconnected.value = false;
  if (!sid) return;
  if(recoveredOperation.value?.sid!==sid)recoveredOperation.value=null;
  let active = true, seenActive = false;
  let timer: ReturnType<typeof setTimeout> | undefined, request: AbortController | undefined;
  const poll = async () => {
    request = new AbortController();
    const timeout = setTimeout(() => request?.abort(), 5000);
    try {
      const data = await api.progress(sid, request.signal);
      if (active) {
        seenActive ||= data.active;
        if (data.active) progress.value = {...data.progress,operation_id:data.operation_id??data.progress.operation_id};
        else if (data.last_operation?.operation_id === progress.value.operation_id)
          progress.value = {...data.last_operation,receiving:!!busy.value};
        else if (seenActive) progress.value = {...progress.value,receiving:true};
        progressDisconnected.value = false;
        if(data.active){
          if(!busy.value){
            recoveredOperation.value={sid,id:data.operation_id??null,activeSeen:true,settling:0};
            operationOutcome.value=null;error.value='';cancelPending.value=false;busy.value=data.progress.label||'后台任务进行中…';
          }
          const recovered=recoveredOperation.value;
          if(recovered?.sid===sid){
            recovered.id=data.operation_id??recovered.id;recovered.activeSeen=true;recovered.settling=0;
            screen.value='workspace';
          }
        }else if(recoveredOperation.value?.sid===sid){
          const recovered=recoveredOperation.value;
          const failed=recovered.id&&data.failed_operation?.operation_id===recovered.id?data.failed_operation:null;
          const completed=recovered.id&&data.completed_operation?.operation_id===recovered.id?data.completed_operation:null;
          const terminal:RuntimeOperation|null=recovered.activeSeen
            ? failed ? {...failed,outcome:failed.cancelled?'cancelled':'failed'}
              : completed ? {...completed,outcome:'success'} : null
            : data.last_operation??null;
          // An observer can end just before its artifact is stored. Stay unknown.
          if(recovered.activeSeen&&!terminal&&++recovered.settling<3)return;
          if(recovered.activeSeen||terminal){
            const fresh=await api.get(sid,request.signal);
            if(!active||sessionId.value!==sid)return;
            apply(fresh);
            if(terminal){
              progress.value={...terminal,receiving:false};
              operationOutcome.value=terminal.outcome;
              if(terminal.outcome!=='success')error.value=terminal.error||'后台任务未提交，请查看运行摘要。';
              else {error.value='';notices.value=[{level:'info',message:'后台任务已完成，已刷新当前战局。'}];}
            }else{
              operationOutcome.value=null;
              notices.value=[{level:'warning',message:'后台任务已结束并刷新战局；结束结果未确认，请查看运行摘要。'}];
            }
          }else if(data.failed_operation){
            operationOutcome.value=null;
            notices.value=[{level:'warning',message:'此旧存档保留未提交的失败记录，操作先后顺序未登记：'+(data.failed_operation.error||'请查看运行摘要。')}];
          }
          recoveredOperation.value=null;busy.value='';cancelPending.value=false;
        }
      }
    } catch { if (active) progressDisconnected.value = true; }
    finally { clearTimeout(timeout); if (active) timer = setTimeout(poll, busy.value?1000:3000); }
  };
  void poll();
  cleanup(() => { active = false; request?.abort(); if (timer) clearTimeout(timer); });
});
const error = ref("");
const notices = ref<Notice[]>([]);
const importantNotices=computed(()=>notices.value.filter(n=>n.level==='warning'||n.level==='error'));
const routineNotices=computed(()=>notices.value.filter(n=>n.level!=='warning'&&n.level!=='error'));
watch(notices,(messages,_previous,cleanup)=>{
  if(messages.length){const timer=setTimeout(()=>{notices.value=[];},12000);cleanup(()=>clearTimeout(timer));}
});
type AnalysisTab = 'forces' | 'reports' | 'history' | 'roster' | 'battlefield' | 'air' | 'combined' | 'adjudication' | 'causal' | 'review' | 'chat' | 'summary' | 'plotting';
const tab = ref<AnalysisTab>('reports');
const analysisTabs = computed(() => [
  {id:'reports',label:'动态战报',short:'战报'},
  {id:'roster',label:'历史部队编制',short:'编制'},
  ...(!strictReplay.value?[{id:'forces',label:'兵团指挥与编组',short:'兵团'}]:[]),
  {id:'plotting',label:'军事标图',short:'标图'},
  ...(strictReplay.value ? [{id:'history',label:'史料事件与来源',short:'史料'}] : [{id:'battlefield',label:'态势与战损',short:'战损'}]),
  ...(snap.value?.war_state?.air_operations ? [{id:'air',label:'航空任务',short:'航空'}] : []),
  ...(snap.value?.war_state?.combined_arms ? [{id:'combined',label:'兵种与保障',short:'保障'}] : []),
  ...(!strictReplay.value ? [{id:'adjudication',label:'裁决与守恒',short:'裁决'},{id:'causal',label:'因果与轨迹',short:'因果'}] : []),
  {id:'review',label:'参谋长复盘',short:'复盘'}, {id:'chat',label:'璇玑问答',short:'问答'},
  {id:'summary',label:'运行摘要与数据质量',short:'摘要'},
]);
function selectAnalysis(id: string) { if (analysisTabs.value.some(t => t.id === id)) tab.value = id as AnalysisTab; }
const turnComplete = computed(() => snap.value?.war_state?.mission?.status === 'completed' || snap.value?.war_state?.history_replay?.status === 'completed');
const strictReplay = computed(() => !!snap.value?.war_state?.history_replay);
const replaySelectedUnit=computed(()=>{const s=selectedUnit.value;if(!s)return null;const units=s.team==='red'?snap.value?.war_state?.red_units:snap.value?.war_state?.blue_units;const rows=units?.filter(u=>u.name===s.name)??[];return rows.length===1?rows[0]!:null;});
const replaySelectedSymbol=computed(()=>{const selected=selectedUnit.value;const entry=snap.value?.plotting?.units.find(u=>u.team===selected?.team&&u.name===selected?.name);return entry?snap.value?.plotting?.unit_symbols[entry.id]:undefined;});
const executionLabel = computed(() => snap.value?.settings?.product_mode ?
  ({analysis:'历史战役回溯分析',historical:'历史战局推演',synthetic:'合成教学演习'}[snap.value.settings.product_mode]+' · '+(snap.value.settings.execution_backend==='afsim'?'DSH + AFSIM':'DSH独立推演')) : strictReplay.value ? '历史战役回溯分析'
  : snap.value?.war_state?.mission ? '合成教学演习'
  : snap.value?.settings?.execution_backend === 'afsim' ? '历史战局推演 · 仅运动预览' : '历史战局推演 · 模型叙事');
const chatInput = ref("");

onMounted(async () => {
  document.title = `GenTactix-DSH ${appVersion} · 历史战役推演工作台`;
  unsubscribeMenu = window.gentactix?.onMenuAction?.((action) => {
    if (action === 'open-llm-settings') openSettings();
    if (action === 'new-scenario' && !busy.value) screen.value = 'launch';
  });
  for (let attempt = 0; attempt < 3; attempt++) {
    if (await refreshBackend()) break;
    await new Promise(resolve => setTimeout(resolve, 1200));
  }
});
async function refreshBackend() {
  error.value = '';
  try {
    health.value = await api.health();
    if (!health.value.runtime?.enabled) opts.agent_mode = 'json';
    battles.value = (await api.battles()).battles;
    corpus.value = await api.corpus(); // 开局前也要显示「已索引 N 文件」，与旧侧栏一致
    try { recentSessions.value = (await api.sessions()).sessions.filter(s => s.initialized); }
    catch { recentSessions.value = []; }
    const saved = localStorage.getItem('gentactix-session');
    if (saved) {
      try { const savedState = await api.get(saved); apply(savedState); restoreOptions(savedState); sessionId.value = saved; recoverRunningOperation(saved); }
      catch { localStorage.removeItem('gentactix-session'); }
    }
    return true;
  } catch (e) {
    error.value = `后端未就绪：${e}`;
    return false;
  }
}

function restoreOptions(s: Snapshot) {
  Object.assign(opts, { scenario: s.scenario, time_step: normalizeStep(s.time_step), simulation_mode: 'open', mission_id: '', execution_backend: 'narrative', product_mode:undefined,synthetic_configuration:null,scenario_draft_id:null,historical_parameters:null,historical_source_version:null,
    battle: s.adjudication.battle_choice || '', use_adjudicator: s.adjudication.enabled,
    use_rag: s.rag.enabled, ...s.settings });
  const binding=s.war_state?.mission?.definition.historical_calculation;
  if(s.settings?.product_mode==='analysis')opts.historical_source_version=s.war_state?.historical_initial?.version??null;
  if(binding&&s.settings?.product_mode==='historical'){
    opts.historical_parameters=JSON.parse(JSON.stringify(binding.parameters));
    opts.mission_id='';
  }
}

function apply(s: Snapshot) {
  if(snap.value?.session_id!==s.session_id){selectedUnit.value=null;commandPreview.value=null;commandPicking.value=null;}
  if (s.war_state?.history_replay && !snap.value?.war_state?.history_replay) tab.value = 'history';
  if (!s.war_state?.history_replay && tab.value === 'history') tab.value = 'reports';
  snap.value = s;
  if (s.war_state) recentSessions.value = [{ session_id: s.session_id, turn_count: s.turn_count, scenario: s.scenario },
    ...recentSessions.value.filter(item => item.session_id !== s.session_id)];
  notices.value = s.notices;
}

async function run(label: string, fn: () => Promise<Snapshot>, presentOutcome = true) {
  const previousOperation = snap.value?.engine_meta?.operation_id;
  operationOutcome.value = null; progress.value = {}; cancelPending.value = false;
  busy.value = label;
  error.value = "";
  try {
    await nextTick();
    const value=await fn(); apply(value);
    if(presentOutcome&&value.engine_meta?.operation_id&&value.engine_meta.operation_id!==previousOperation)
      progress.value={...value.engine_meta};
    operationOutcome.value = presentOutcome ? 'success' : null;
    return true;
  } catch (e) {
    error.value = String(e);
    operationOutcome.value = /已取消|用户.*取消/.test(error.value) ? 'cancelled' : 'failed';
    return false;
  } finally {
    busy.value = ""; cancelPending.value = false;
  }
}

async function init() {
  if (busy.value) return;
  operationOutcome.value = null;
  error.value = "";
  if (!opts.scenario.trim()) { error.value = "请先输入推演场景"; return; }
  if (opts.use_agent_tools && opts.agent_mode === 'native' && !health.value?.runtime?.enabled) {
    error.value = '后端未启用原生运行时插件，请重启新版后端或选择兼容JSON模式'; return;
  }
  busy.value = "创建会话…";
  const previousSession = sessionId.value;
  try {
    const { session_id } = await api.createSession({
      scenario: opts.scenario,
      time_step: opts.time_step,
      use_adjudicator: opts.use_adjudicator,
      battle: opts.battle || null,
      use_rag: opts.use_rag,
      use_live_intel: opts.use_live_intel,
      use_agent_tools: opts.use_agent_tools,
      persist_roles: opts.persist_roles,
      agent_mode: opts.agent_mode, simulation_mode: opts.simulation_mode, mission_id: opts.mission_id || null,
      execution_backend: opts.execution_backend,
      synthetic_configuration: opts.synthetic_configuration,
      scenario_draft_id: opts.scenario_draft_id,
      product_mode:opts.product_mode,
      historical_parameters:opts.historical_parameters,
      historical_source_version:opts.historical_source_version,
    });
    sessionId.value = session_id;
  } catch (e) {
    busy.value = "";
    error.value = String(e);
    return;
  }
  const succeeded = await run(opts.simulation_mode==='replay'?'正在读取史料关键节点…':opts.execution_backend==='afsim'?'正在装载AFSIM初态…':'DSH正在初始化战局…', () => api.init(sessionId.value));
  if (succeeded) {
    localStorage.setItem('gentactix-session', sessionId.value);
    screen.value = 'workspace';
  } else sessionId.value = previousSession;
}

const next = async () => { if (busy.value) return; if (await run(strictReplay.value ? (opts.execution_backend==='afsim'?'AFSIM正在重现下一史料事件…':'DSH正在讲解下一史料事件…') : `正在推演未来 ${snap.value?.time_step ?? ""} 的战况…`, () => strictReplay.value ? api.nextHistory(sessionId.value, snap.value!.turn_count) : commandCenter.value?.next(turnInstruction.value) ?? api.next(sessionId.value, turnInstruction.value))) turnInstruction.value = ""; };
const review = () => !busy.value && run("参谋长正在深度复盘…", () => api.review(sessionId.value));

async function cancel() {
  if (cancelPending.value) return;
  cancelPending.value = true;
  try { const response = await api.cancel(sessionId.value); notices.value = [{level:'info',message:response.note}]; }
  catch (e) { cancelPending.value = false; error.value = String(e); }
}

async function sendChat() {
  const q = chatInput.value.trim();
  if (!q || !sessionId.value || busy.value) return;
  chatInput.value = "";
  const previousMessages = snap.value?.chat_messages.slice() ?? [];
  if (snap.value) snap.value.chat_messages.push({ role: "user", content: q });
  if (!await run("璇玑思考中…", () => api.chat(sessionId.value, q))) {
    if (snap.value) snap.value.chat_messages = previousMessages;
    chatInput.value = q;
  }
}

const exporting=ref(false);
async function exportJson(compact=true) {
  if (!sessionId.value||exporting.value) return;
  exporting.value=true;
  try {
    const file=await api.exportFile(sessionId.value,compact);
    const url = URL.createObjectURL(file.blob);
    const link = document.createElement('a');
    link.href = url; link.download = file.filename;
    link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (e) { error.value = `导出失败：${e}`; }
  finally{exporting.value=false;}
}

const hasState = () => !!snap.value?.war_state;

// ---- 地图下方「数据实况」：与 app.py 的 caption 同一口径 ----
const engStats = computed(() => snap.value?.war_state ? summarizeEngagements(snap.value.war_state) : null);
const engCaption = computed(() => {
  const e = engStats.value;
  if (!e) return "";
  if (snap.value?.settings?.execution_backend === 'afsim' && !selftest.value) {
    const tasks = snap.value.war_state?.air_operations?.missions ?? [];
    if (snap.value.afsim?.phase === 'initial_state_validation') return 'AFSIM初态已载入，战局尚未推进；暂无本轮交战与航空事件。';
    return `本轮AFSIM记录：地面交战 ${e.valid} 处；航空任务 ${tasks.length} 项（打击 ${tasks.filter(t => t.outcome === 'strike').length}，中止 ${tasks.filter(t => t.outcome === 'aborted').length}）。航空任务独立显示航路与战果，不计入地面射界扇区。`;
  }
  if (e.total === 0) {
    return `⚔️ 本回合交战：0 处 —— AI 未输出 engagements（双方尚未接触），所以地图上没有扇区可画，` +
      `不是渲染失效。可展开侧栏「🔧 渲染自检」一键验证（当前渲染器 ${RENDERER_VERSION}）。`;
  }
  const parts = [`定向扇区 ${e.sector} 处`];
  if (e.ring) parts.push(`降级空心环 ${e.ring} 处（AI 未给攻击方位）`);
  let note = "";
  if (e.skipped) {
    const unique = [...new Set(e.reasons)].join("、");
    note = ` · ⚠️ 另有 ${e.skipped} 处被丢弃：${unique}`;
  }
  return `⚔️ 本回合交战：${e.valid} 处（${parts.join("；")}）${note}`;
});

const ragLast = computed(() => snap.value?.rag.last ?? null);
const ragMapCaption = computed(() => {
  const m = ragLast.value;
  if (!m?.enabled) return "";
  if (m.injected) {
    const first = m.hits[0];
    return `📚 本回合注入史料 ${m.injected} 段 · 主要来源：${first?.doc_title ?? ""}·${first?.section ?? ""}`;
  }
  return `📚 本回合无史料注入：${m.note} —— 数字与时间线不可追溯，仅作推演参考。`;
});

// ---- 裁决实况（旧版地图下方的汇总 caption + 越界警告，一眼可扫） ----
const adjLast = computed(() => snap.value?.adjudication.last ?? null);
const violations = computed(() => snap.value?.adjudication.violations ?? []);
const adjCaption = computed(() => {
  const a = adjLast.value;
  if (!a) return "";
  const s = a.summary;
  return `⚖️ 裁决 ${a.version} · 指纹 ${a.fingerprint}：单位 ${s.units} · 本回合可接触 ${s.can_contact} · ` +
    `粮道被断 ${s.supply_cut} · 被围 ${s.encircled}（半包围 ${s.partial}）· 退路已断 ${s.retreat_cut} · ` +
    `士气崩溃 ${s.morale_broken} / 动摇 ${s.morale_shaken}`;
});

// ---- 守恒面板：名单回填 / 歼灭 / 可疑 / 数值异常（app.py 同款文案） ----
const roster = computed(() => snap.value?.integrity.roster ?? null);
const numericFlags = computed(() => snap.value?.integrity.numeric_flags ?? []);
function flagLine(f: NumericFlag): string {
  if (f.kind === "hp_gain") return `${f.name} hp ${f.prev} → ${f.new}（+${f.delta}）`;
  if (f.kind === "hp_zero_alive") return `${f.name} hp 已归零但仍在编制里（地图会留一个满编军标）`;
  return `${f.name} hp 为负（${f.new}）`;
}
</script>

<template>
  <div class="desktop-root" :class="{ 'workspace-mode': screen === 'workspace', 'operation-running': !!busy }">
  <LaunchScreen v-if="screen === 'launch'" :battles="battles" :health="health" :busy="busy" :error="error" :can-resume="hasState()" :recent-sessions="recentSessions" @settings="openSettings" @import="openImport" @resume="screen = 'workspace'" @start="startScenario" @reconnect="refreshBackend" @resume-session="resumeSession" @delete-session="requestDelete" @cancel="cancel" @busy="setChildBusy" />
  <template v-else>
  <header class="workspace-command-bar">
    <div class="product-mark"><img :src="'./icons/gentactix.png'" alt=""><strong>GenTactix <span>DSH</span></strong><span class="layout-version">地图工作台 · {{ appVersion }}</span></div>
    <div class="workspace-clock" v-if="hasState()" :title="snap!.war_state!.current_time"><b>{{ strictReplay ? '史料事件 ' + (snap!.turn_count + 1) : 'T+' + snap!.turn_count }}</b><span :title="snap!.war_state!.current_time">{{ snap!.war_state!.current_time }}</span></div>
    <div class="workspace-quick-actions"><span id="workspace-operation-status"></span><span v-if="!busy" class="workspace-mode-label" data-testid="execution-kind">{{ executionLabel }}{{ turnComplete ? (strictReplay ? ' · 史料帧已读完' : ' · 局部目标：' + (snap?.war_state?.mission?.winner === 'red' ? '红方胜' : snap?.war_state?.mission?.winner === 'blue' ? '蓝方胜' : '目标未达成')) : '' }}</span><button v-if="busy&&(!recoveredOperation||recoveredOperation.activeSeen)" @click="cancel" :disabled="cancelPending">{{ cancelPending ? '取消中' : '取消' }}</button><button class="advance-button" @click="next" :disabled="!!busy || !hasState() || turnComplete" :aria-label="strictReplay ? '推进下一史料事件' : '推进一轮'">{{ busy ? '处理中' : strictReplay ? '下一事件' : '推进一轮' }} <span aria-hidden="true">→</span></button></div>
  </header>
  <div v-if="turnComplete&&snap?.war_state?.mission" class="phase-outcome" data-testid="phase-outcome" role="status"><span><strong>本阶段已结算</strong> · {{snap.war_state.mission.reason}}。{{snap.war_state.mission.reason==='截止回合目标未达成'?'当前存档采用限时规则；到期后停止推进。':'继续推演按钮已停用，原战局与决策记录已保留。'}}</span><button @click="workbench?.openStatus()">查看目标与结算</button></div>
  <MapWorkbench ref="workbench" :tabs="analysisTabs" :active-tab="tab" :picking="!!commandPicking||plotPicking||forcePicking" :busy="busy" :progress="progress" :outcome="operationOutcome" :error="error" :cancelling="cancelPending" :disconnected="progressDisconnected" @select="selectAnalysis" @panel-open="commandCenter?.close()">
    <template #left><div class="sidebar">
      <div class="health" v-if="health">
        <span class="dot" :class="health.harness_started ? 'on' : 'idle'"></span>
        {{ health.engine }} · {{ health.model }}<br/>
        <small>{{ health.base_url }}</small>
      </div>
      <div class="health bad" v-else>后端未连接</div>
      <p v-if="health?.build?.restart_required" class="bad" role="alert">后端源码已更新，当前进程需要重启；请先保存战局。</p>

      <label>推演场景</label>
      <textarea v-model="opts.scenario" rows="3" :disabled="!!busy"></textarea>

      <label>当前使用类型</label><p class="muted">{{ executionLabel }}。更改类型请从想定管理新建，保留当前战局。</p>
      <label for="workspace-executor">执行后端（初始化时生效）</label><select id="workspace-executor" v-model="opts.execution_backend" :disabled="!!busy || opts.simulation_mode === 'replay'" @change="opts.execution_backend === 'afsim' && (opts.use_agent_tools = false, opts.use_live_intel = false)"><option value="narrative">模型叙事推演</option><option value="afsim" :disabled="!health?.afsim?.available">DSH 控制 · AFSIM 后台推演</option></select>
      <label v-if="opts.simulation_mode !== 'replay'">⏱️ 单回合时间跨度</label>
      <select v-if="opts.simulation_mode !== 'replay'" v-model="opts.time_step" :disabled="!!busy || !!opts.mission_id">
        <option v-for="t in TIME_STEPS" :key="t">{{ t }}</option>
      </select>

      <label class="toggle"><input type="checkbox" v-model="opts.use_adjudicator" :disabled="!!busy" />
        ⚖️ 启用确定性裁决（几何层，默认关闭）</label>
        <p v-if="opts.use_adjudicator" class="muted">内核 <code>{{ health?.adjudicator_version ?? "未知" }}</code> · 只裁决<b>机动 / 补给 / 包围</b>，不裁决伤亡数字。</p>
        <label>🎯 战场裁决库</label>
        <select v-model="opts.battle" :disabled="!!busy" @change="applyBattleHint">
          <option value="">自动匹配（按场景描述）</option>
          <option v-for="b in battles" :key="b.name" :value="b.name">{{ b.name }}</option>
        </select>
        <p class="muted" v-if="battles.length === 0">裁决库为空：adjudication/ 下还没有战役文件，将使用默认几何。</p>
        <p class="muted" v-else-if="battleHint && opts.simulation_mode !== 'replay'">这场战役建议回合跨度 <b>{{ battleHint }}</b>；实际可用机动距离受规则与状态约束。</p>
      <p class="muted" v-if="opts.simulation_mode === 'replay'">严格回放按史料事件推进；固定回合跨度与开放几何、战损规则不参与历史结果重现。</p>
      <p class="muted" v-else-if="!opts.use_adjudicator && !opts.mission_id">{{ opts.execution_backend === 'afsim' ? '几何审计关闭；AFSIM仍执行已支持的运动模型，未知战损与库存不凭空补造。' : '裁决已关闭：模型自行推演走位与胜负，同一想定两次运行结果不同。' }}</p>

      <label class="toggle"><input type="checkbox" v-model="opts.use_agent_tools" :disabled="!!busy || !!opts.mission_id || opts.execution_backend === 'afsim'" />
        🤖 智能体回合（先侦察试算、后下令，默认关闭）</label>
      <p class="muted" v-if="opts.mission_id">{{ snap?.settings?.execution_backend === 'afsim' ? 'DSH按需观察并下令，AFSIM后台执行教学模型和产生数据；旧工具循环不参与。' : '固定局部想定使用DSH命令生成和事件轨迹，状态由程序结算；领域工具循环暂不接入此模式。' }}</p>
      <p class="muted" v-if="opts.use_agent_tools">
        原生模式使用运行时步骤与工具预算；兼容模式至多4次JSON往返。<b>耗时显著增加</b>；
        工具全部只读，战局仍由系统统一提交。</p>
      <select v-if="opts.use_agent_tools" v-model="opts.agent_mode" :disabled="!!busy" aria-label="智能体工具模式"><option value="native" :disabled="!health?.runtime?.enabled">DSH原生领域工具</option><option value="json">兼容JSON协议</option></select>
      <p v-if="opts.use_agent_tools && !health?.runtime?.enabled" class="muted">原生插件未加载，当前使用兼容JSON协议。</p>
      <label class="toggle"><input type="checkbox" v-model="opts.persist_roles" :disabled="!!busy" />连续角色记忆（决策轨迹始终记录）</label>
      <p v-if="opts.execution_backend === 'afsim' && opts.simulation_mode !== 'replay'" class="muted">AFSIM全局规划每轮读取最新状态，不回带完整战史；独立单位Agent仍保留原生会话，人工命令优先。</p>

      <label class="toggle"><input type="checkbox" v-model="opts.use_rag" :disabled="!!busy" />
        📚 启用史料检索（RAG）</label>
      <p class="muted" v-if="!opts.use_rag">未开启：模型凭自身历史知识推演，<b>数字与时间线不可追溯</b>。</p>
      <p class="bad" v-else-if="corpus && corpus.chunks === 0">
        ⚠️ 史料库为空（{{ corpus.dir }}）。本次推演仍由模型自由发挥，<b>没有史料约束</b>。</p>
      <p class="muted" v-else-if="corpus">
        已索引 {{ corpus.files }} 个文件 / {{ corpus.chunks }} 个片段（{{ corpus.chars.toLocaleString() }} 字）
      </p>

      <div class="expander" v-if="opts.use_rag && ragLast">
        <button class="link" @click="ragOpen = !ragOpen">
          📚 最近一次注入（{{ ragLast.injected }}/{{ ragLast.hits.length }} 段）{{ ragOpen ? "▾" : "▸" }}</button>
        <template v-if="ragOpen">
          <p class="muted" v-if="ragLast.note">{{ ragLast.note }}</p>
          <p class="muted" v-if="ragLast.hits.length === 0">查询：<code>{{ ragLast.query.slice(0, 60) }}</code></p>
          <div v-for="(h, i) in ragLast.hits" :key="i" class="hit">
            <b>{{ h.section }}</b> <code>{{ h.source }}</code>
            <p class="muted">{{ h.preview }}</p>
          </div>
          <p class="muted">若这里的内容与战报不符，说明模型没有遵守史料约束，应以史料为准。</p>
        </template>
      </div>

      <div class="expander">
        <label class="toggle"><input type="checkbox" v-model="selftest" :disabled="!!busy" />
          🔧 叠加 1 个示例交战扇区</label>
        <p class="muted">只在地图渲染时临时加一个虚构交战，不写入战局数据，关掉即消失。
          用来区分「渲染失效」和「本回合确实没交战」。</p>
        <p class="muted">渲染器版本：<code>{{ RENDERER_VERSION }}</code> · 交战图形：定向扇区；AI 未给攻击方位时降级为空心虚线环。</p>
      </div>

    </div></template>
    <template #controls>
      <nav class="workspace-app-actions" aria-label="工作台菜单"><button @click="screen = 'launch'" :disabled="!!busy">想定管理</button><button @click="openSettings">模型配置</button><button @click="openImport" :disabled="!!busy">导入战局</button><button @click="exportJson(true)" :disabled="!hasState()||exporting" title="紧凑保存全部战局和历史，可直接导入恢复">{{exporting?'正在导出…':'导出战局'}}</button><button @click="exportJson(false)" :disabled="!hasState()||exporting" title="为旧版工具导出展开的JSON，文件较大">兼容导出</button></nav>
      <div class="workspace-operations">
      <label for="turn-instruction">本轮决策意图</label><textarea id="turn-instruction" v-model="turnInstruction" maxlength="4000" rows="3" :disabled="!!busy || !hasState() || strictReplay" :placeholder="strictReplay ? '严格史料重现不接受作战命令；请新建开放推演改变决策。' : '例如：红方先补给再推进；蓝方保卫目标。'"></textarea>
      <p class="muted">{{ strictReplay ? '按审订事件帧推进，日期与钟点保持史料精度；未载数据不补齐。' : '侧栏想定设置在重新初始化时生效；本轮意图仅影响下一轮决策。' }}</p>
      <div class="buttons">
        <button v-if="busy && sessionId" class="cancel" @click="cancel">取消当前操作</button>
        <button class="primary" @click="init" :disabled="!!busy">🚀 初始化沙盘</button>
        <button @click="next" :disabled="!!busy || !hasState() || snap?.war_state?.mission?.status === 'completed' || snap?.war_state?.history_replay?.status === 'completed'">{{ strictReplay ? '⏩ 下一史料事件' : '⏩ 下一轮推演' }}</button>
        <button @click="review" :disabled="!!busy || !hasState()">🧐 呼叫总参谋长复盘</button>
        <button @click="exportJson(true)" :disabled="!hasState()||exporting">{{exporting?'正在导出…':'📦 导出完整战局存档'}}</button>
      </div>
      </div>
    </template>
    <template #status>
      <p v-if="busy" class="workspace-empty">新任务正在处理。以下仍是最近一次已提交的结果，完成校验后才会更新战局。</p>
      <MissionPanel v-if="snap?.war_state?.mission" :mission="snap.war_state.mission" :campaign="snap.war_state.campaign" :plan="snap.war_state.campaign_plan" :lifecycle="snap.war_state.campaign_lifecycle" :readiness="snap.resource_readiness" :session-id="sessionId" :busy="!!busy" :current-time="snap.war_state.current_time" :model-estimated="!!snap.war_state.dsh_execution" @snapshot="importedSession" @busy="setChildBusy($event?'正在装载连续阶段…':'')" />
      <AFSimPanel v-if="snap?.settings?.execution_backend === 'afsim'" :evidence="snap?.afsim" :modeled="!!snap?.war_state?.mission" :host-goals="!!snap?.war_state?.campaign_plan" />
      <p v-if="!snap?.war_state?.mission && snap?.settings?.execution_backend !== 'afsim'" class="workspace-empty">当前为模型叙事推演；目标和结果见战报，未使用AFSIM执行。</p>
    </template>
    <template #map>
      <div class="map-wrap command-workspace" v-if="hasState()">
        <MapView :snap="snap" :selftest="selftest" :command-preview="commandPreview" :selected-unit="selectedUnit" :picking="forcePicking?'move':commandPicking" :plot-picking="plotPicking" :plot-preview="plotPreview" @plot-point="plottingPoint" @plot-select="selectPlotting" toolbar-target="#workbench-map-tools"
          @unit-select="selectMapUnit" @map-target="mapCommandTarget" />
        <CommandCenter v-if="snap && !strictReplay" ref="commandCenter" :session-id="sessionId" :snap="snap" :busy="!!busy"
          @preview="commandPreview = $event" @selected="selectedUnit = $event" @picking="commandPicking = $event"
          @busy="setChildBusy" @snapshot="commandSnapshot" @queue-changed="forcePanel?.refresh()" @opened="value => { if (value) workbench?.focusMap(); }" />
        <aside v-if="strictReplay&&selectedUnit&&snap?.war_state" class="replay-unit-inspector" aria-label="史料单位参数"><header><b>史料单位 · 只读</b><button type="button" aria-label="关闭单位资料" @click="selectedUnit=null">×</button></header><UnitInspector :unit="replaySelectedUnit" :symbol-id="replaySelectedSymbol" :world="snap.war_state" :team="selectedUnit.team" :turn="snap.turn_count" read-only /></aside>
      </div>
      <div class="idle" v-else>
        <img :src="'./logo.png'" alt="GenTactix" class="idle-logo" @error="($event.target as HTMLImageElement).style.display='none'" />
        <h3>系统处于最高物理静默状态</h3>
        <p>打开左侧想定与控制完成设置，再从上方推演操作初始化沙盘。</p>
      </div>

    </template>
    <template #analysis><section class="tab-body" v-if="snap">
        <div v-if="tab === 'summary'">      <div class="strip summary-content" v-if="hasState()">
        <p class="caption" v-if="snap?.branch_origin">开放假设分支 · 来源 {{ snap.branch_origin.session_id }} / T+{{ snap.branch_origin.turn }} · {{ snap.branch_origin.basis }}</p>
        <p class="caption">{{ strictReplay ? '史料未载的部署和逐帧战损为未知，不显示为0或满编。' : engCaption }}</p>
        <p class="caption" v-if="ragMapCaption">{{ ragMapCaption }}</p>
        <p class="caption" v-if="adjCaption">{{ adjCaption }}</p>
        <p class="caption" v-if="snap?.engine_meta && !snap?.afsim?.model_skipped">
          🔎 {{ snap.engine_meta.label }} · finish_reason <code>{{ snap.engine_meta.finish_reason ?? "未知" }}</code>
          · {{ snap.engine_meta.turns }} 轮 / {{ snap.engine_meta.steps }} 步
          · {{ snap.engine_meta.tokens }} tok · 用时 {{ (snap.engine_meta.elapsed_ms / 1000).toFixed(1) }}s
        </p>
        <p class="warnbox" v-if="snap && snap.adjudication.enabled && violations.length">
          ⚠️ 上回合有 <b>{{ violations.length }}</b> 个单位的位移超出裁决上限：
          {{ violations.map((v) => `${v.name} 实走 ${v.moved_km?.toFixed(1)} km（上限 ${v.allowed_km?.toFixed(1)} km，超 ${v.over_km?.toFixed(1)} km）`).join("；") }}。
          裁决器不修正坐标（硬拉可能把部队拖进河里），只如实记录。
        </p>

        <p class="warnbox" v-if="roster && (roster.recovered.length || roster.structure_missing?.length)">
          🔁 上回合有 <b>{{ roster.recovered.length }}</b> 个单位的返回里凭空消失，已按上一回合快照回填：
          {{ roster.recovered.map((e) => `${e.name}（hp ${e.hp}）`).join("、") || "无" }}。
          <template v-if="roster.structure_missing?.length">结构层面：{{ roster.structure_missing.join("；") }}。</template>
          战局状态是<b>整体替换</b>的，漏返回的单位下一回合连名字都不会出现在 prompt 里 ——
          它永远补不回来，所以这里必须补。若这支部队确实已被歼灭，应写进 eliminated 声明；没有声明的消失一律当作漏返回。
        </p>
        <p class="caption" v-if="roster?.eliminated?.length">
          ☠️ 本回合确认歼灭 <b>{{ roster.eliminated.length }}</b> 个：
          {{ roster.eliminated.map((e) => `${e.name}（${e.why}）`).join("、") }}
        </p>
        <p class="caption" v-if="roster?.suspected?.length">
          ☑️ 这些单位的消失已被回填，但上一回合 hp 已经很低，也可能确实被歼灭：
          {{ roster.suspected.map((e) => `${e.name}（上回合 hp ${e.hp}）`).join("、") }}。
          下一回合若确认歼灭，请让模型写进 eliminated。
        </p>
        <p class="warnbox" v-if="numericFlags.length">
          📉 数值守恒提示：{{ numericFlags.map(flagLine).join("；") }}。
          <b>没有自动改</b> —— 兵力上涨可能是援军抵达或就地整补（合法），也可能是模型漏减（误差）。
          系统不替你判断，只把可疑处摆出来。
        </p>
      </div>
</div>
        <div v-else-if="tab === 'reports'" class="reports">
          <p v-if="!snap.history.length" class="muted">尚无战报。请点击「🚀 初始化沙盘」开始推演。</p>
          <article v-for="(h, i) in snap.history" :key="i" v-memo="[h]" class="report" v-html="mdToHtml(h)"></article>
        </div>

        <HistoryReplayPanel v-else-if="tab === 'history' && snap.war_state?.history_replay" :data="snap.war_state.history_replay" />
        <ForceOrganizationPanel v-else-if="tab === 'forces' && !strictReplay" ref="forcePanel" :session-id="sessionId" :turn="snap.turn_count" :busy="!!busy" :product-mode="snap.settings?.product_mode ?? undefined" :submit-conversion="submitFormation" @changed="forceChanged" @pick-map="pickForceTarget" @unit-select="value=>{workbench?.focusMap();commandCenter?.select(value.team,value.name);}" />
        <HistoricalRosterPanel v-else-if="tab === 'roster'" :battle="snap.adjudication.battle_choice??''" :initial="snap.war_state?.historical_initial" :operation-bound="!!snap.war_state?.mission?.definition.historical_calculation" />
        <BattlefieldPanel v-else-if="tab === 'battlefield'" :view="snap.battlefield" />
        <AirOperationsPanel v-else-if="tab === 'air' && snap.war_state?.air_operations" :data="snap.war_state.air_operations" :availability="snap.aviation_availability" />
        <CombinedArmsPanel v-else-if="tab === 'combined' && snap.war_state" :world="snap.war_state" :sustainment="snap.sustainment" />
        <AdjudicationPanel v-else-if="tab === 'adjudication'" :snap="snap" />
        <CausalPanel v-else-if="tab === 'causal'" :session-id="sessionId" :snap="snap" :busy="busy" @busy="setChildBusy" />

        <div v-else-if="tab === 'review'" class="review">
          <template v-if="snap.review.text">
            <h4>🦅 战局深度复盘</h4>
            <details v-if="snap.review.reasoning"><summary>💡 参谋长的推演思维链 (CoT)</summary>
              <p v-html="mdToHtml(snap.review.reasoning)"></p></details>
            <article v-html="mdToHtml(snap.review.text)"></article>
          </template>
          <p v-else class="muted">尚未复盘。点「呼叫总参谋长复盘」让深度模型通读全部战报。</p>
        </div>

        <div v-else-if="tab === 'chat'" class="chat">
          <div class="chat-log">
            <p v-if="!snap.chat_messages.length" class="muted">沙盘启动后，可在此直接向总参谋长璇玑提问。</p>
            <div v-for="(m, i) in snap.chat_messages" :key="i" v-memo="[m.content, m.reasoning]" :class="['msg', m.role]">
              <b>{{ m.role === "user" ? "统帅" : "璇玑" }}</b>
              <div class="message-content" v-html="mdToHtml(m.content)"></div>
              <details v-if="m.reasoning"><summary>💡 璇玑思维链 (CoT)</summary>
                <p v-html="mdToHtml(m.reasoning)"></p></details>
            </div>
          </div>
          <div class="chat-input">
            <input v-model="chatInput" placeholder="向总参谋长璇玑提问（如：帮我评估当前优势在哪方？）" @keyup.enter="sendChat" :disabled="!!busy || !hasState()" />
            <button @click="sendChat" :disabled="!!busy || !hasState()">发送</button>
          </div>
        </div>
      <MilitaryPlottingPanel v-show="tab==='plotting'" ref="plottingPanel" :session-id="sessionId" :turn="snap.turn_count" :busy="!!busy" @changed="plottingChanged" @preview="plotPreview=$event" @picking="plottingPick" @reopen="workbench?.openAnalysis('plotting')" @busy="setChildBusy" />
    </section></template>
    <template #feedback>
      <div v-if="plotPicking" class="plot-pick-banner" role="status">军事标图选点 · 已选{{plotPreview[0]?.points.length??0}}点<button @click="plottingPanel?.finish()">完成选点</button><button @click="plottingPanel?.cancelPick()">取消选点 (Esc)</button></div>
      <p v-if="error" class="workspace-status-message error" role="alert">{{ error }}</p>
      <div v-if="importantNotices.length" class="workspace-important-notices" aria-live="polite">
        <div v-for="(n,i) in importantNotices" :key="i" class="workspace-status-message" :class="{error:n.level==='error'}" role="alert">{{n.message}}</div>
      </div>
      <details v-if="routineNotices.length" class="workspace-notice-summary" data-testid="routine-notices">
        <summary>已记录 {{routineNotices.length}} 条运行提示 · 查看详情</summary>
        <div class="workspace-notice-log"><div v-for="(n,i) in routineNotices" :key="i" class="workspace-status-message">{{n.message}}</div></div>
      </details>
    </template>
  </MapWorkbench>
  </template>
  <ImportSession ref="importDialog" @imported="importedSession" />
  <dialog ref="deleteDialog" class="settings-dialog tactical-window delete-dialog" aria-labelledby="delete-title" aria-describedby="delete-scope" @cancel="event => { if (deleting) event.preventDefault(); }">
    <header class="window-heading"><span class="window-index">SAVED BATTLE</span><h2 id="delete-title">删除已保存战局</h2></header>
    <div class="delete-content" v-if="pendingDelete">
      <p class="delete-scenario">{{ pendingDelete.scenario }}</p>
      <p>已推进 {{ pendingDelete.turn_count }} 回合 · {{ pendingDelete.session_id }}</p>
      <p id="delete-scope">将删除此战局的本机存档并从列表移除，需要保留时请先打开战局并导出。底层审计轨迹仍保留，其他战局及模型配置不受影响。</p>
      <p v-if="pendingDelete.session_id === sessionId">这是当前打开的战局；删除后将清空当前界面。</p>
      <p v-if="deleteError" class="bad" role="alert">{{ deleteError }}</p>
    </div>
    <footer class="window-footer"><button autofocus :disabled="deleting" @click="deleteDialog?.close()">取消</button><button class="danger-action" :disabled="deleting" @click="confirmDelete">{{ deleting ? '正在删除…' : '确认删除' }}</button></footer>
  </dialog>
  <dialog ref="settingsDialog" class="settings-dialog tactical-window" aria-labelledby="settings-title">
    <header class="window-heading"><span class="window-index">RUNTIME</span><h2 id="settings-title">DSH · LLM配置</h2><button @click="settingsDialog?.close()" aria-label="关闭模型配置">×</button></header>
    <LlmSettings ref="settingsPanel" embedded :disabled="!!busy" @changed="async () => { health = await api.health(); }" @busy="setChildBusy" />
    <footer class="window-footer"><span>配置保存在本机 · 密钥不回显</span><button @click="settingsDialog?.close()">完成</button></footer>
  </dialog>
  </div>
</template>
