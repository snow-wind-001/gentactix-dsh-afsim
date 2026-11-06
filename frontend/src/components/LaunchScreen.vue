<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue';
import type { ScenarioSelection, Battle, Health, MissionDefinition, SyntheticConfiguration, HistoricalParameters, WarState, Snapshot, MapPoint } from '../types';
import { api } from '../api';
import { normalizeStep, stepOptions } from '../timeSteps';
import MapView from './MapView.vue';
import ScenarioComposer from './ScenarioComposer.vue';
import HistoricalScenarioComposer from './HistoricalScenarioComposer.vue';

const props = defineProps<{ battles: Battle[]; health: Health | null; busy: string; error: string; canResume: boolean; recentSessions: { session_id: string; turn_count: number; scenario: string }[] }>();
const emit = defineEmits<{ settings: []; import: []; resume: []; reconnect: []; cancel: []; busy:[label:string]; resumeSession: [id: string]; deleteSession: [session: { session_id: string; turn_count: number; scenario: string }]; start: [value: ScenarioSelection] }>();
const minimized = ref(false);
const mode = ref<'catalog' | 'assistant' | 'recent'>('catalog');
const query = ref('');
const family = ref('all');
const phase = ref<'select' | 'configure'>('select');
const selected = ref<Battle | null>(null);
const draft = reactive({ scenario: '', battle: '', time_step: '30分钟', use_rag: true, use_adjudicator: false, simulation_mode: 'open', mission_id: '', execution_backend: 'narrative' as 'narrative' | 'afsim' });
const managedScenario = ref('');
const productMode = ref<'analysis'|'historical'|'synthetic'>('historical');
const sourceVersions=ref<{version:string;default:boolean;coverage:{notes:string[]}}[]>([]),sourceVersion=ref(''),sourceLoading=ref(false),sourceError=ref('');
const sourceNotes=computed(()=>sourceVersions.value.find(v=>v.version===sourceVersion.value)?.coverage.notes??[]);
let sourceGeneration=0;
watch([()=>draft.battle,productMode],async()=>{
 const generation=++sourceGeneration;sourceVersions.value=[];sourceVersion.value='';sourceError.value='';sourceLoading.value=false;
 if(productMode.value!=='analysis'||!draft.battle)return;sourceLoading.value=true;
 try{const r=await api.historicalInitial(draft.battle);if(generation!==sourceGeneration)return;
  sourceVersions.value=r.versions??[];sourceVersion.value=r.initial?.version??'';
 }catch(e){if(generation===sourceGeneration)sourceError.value='回溯版本读取失败：'+String(e);}
 finally{if(generation===sourceGeneration)sourceLoading.value=false;}
});
const syntheticBasis=ref<'shared'|'representative'>('shared');
const compatibility=computed(()=>productMode.value==='synthetic'&&syntheticBasis.value==='representative');
const sharedStep=ref(draft.time_step);
watch(()=>draft.time_step,value=>{if(!compatibility.value)sharedStep.value=value;});
const missions=ref<MissionDefinition[]>([]),missionError=ref(''),catalogLoading=ref(false);
async function loadCompatibleMissions(){
 if(catalogLoading.value)return;catalogLoading.value=true;missionError.value='';
 try{missions.value=(await api.missions()).missions;}catch(e){missionError.value='兼容教学模板读取失败：'+String(e);}finally{catalogLoading.value=false;}
}
watch(compatibility,enabled=>{if(enabled&&!missions.value.length)void loadCompatibleMissions();});
const availableMissions=computed(()=>missions.value.filter(m=>m.battle===draft.battle&&m.combined_rules));
const localMission=computed(()=>compatibility.value?availableMissions.value.find(m=>m.id===draft.mission_id):undefined);
const customValid = ref(true);
const customConfiguration = ref<SyntheticConfiguration|null>(null);
const composer = ref<InstanceType<typeof ScenarioComposer>|null>(null);
const historicalComposer=ref<InstanceType<typeof HistoricalScenarioComposer>|null>(null);
const historicalParameters=ref<HistoricalParameters|null>(null),historicalValid=ref(false),historicalAvailable=ref(false),historicalDraftId=ref<string|null>(null);
function activeComposer(){return productMode.value==='synthetic'&&composer.value?composer.value:historicalComposer.value;}
const configurationDraftId = ref<string|null>(null), historicalPreview=ref<WarState|null>(null),syntheticPreview=ref<WarState|null>(null);
const previewWorld=computed(()=>productMode.value==='synthetic'?(syntheticPreview.value??(compatibility.value?null:historicalPreview.value)):historicalPreview.value);
const starting=ref(false);
const launchIssue=ref(''),operationDetail=ref(''),elapsedSeconds=ref(0);
let waitingTimer:ReturnType<typeof setInterval>|undefined;
const preparing=computed(()=>starting.value||!!props.busy);
const configurationError=computed(()=>props.health?.model_config?.error||'');
const launchFailure=computed(()=>configurationError.value||launchIssue.value||(!preparing.value?props.error:''));
watch(preparing,value=>{
 if(waitingTimer)clearInterval(waitingTimer);waitingTimer=undefined;
 if(value){const began=Date.now();elapsedSeconds.value=0;waitingTimer=setInterval(()=>{elapsedSeconds.value=Math.floor((Date.now()-began)/1000);},1000);}
});
onBeforeUnmount(()=>{if(waitingTimer)clearInterval(waitingTimer);});
function composerFeedback(message:string){launchIssue.value=message;}
const mapSelection = ref<{team:string;name:string}|null>(null);
const mapPickLabel = ref<string|null>(null);
function beginMapPick(label?:string) {mapPickLabel.value=label??mapSelection.value?.name??'部队';minimized.value=true;}
function cancelMapPick() {mapPickLabel.value=null;minimized.value=false;}
const composerBusy=ref(false);
function composerStatus(label:string){composerBusy.value=!!label;if(label)operationDetail.value=label;emit('busy',label);}
const previewSnapshot = computed(() => phase.value === 'configure' && (needsConfiguration.value||needsHistorical.value) && previewWorld.value
  ? {session_id:'scenario-draft-'+draft.mission_id, war_state:previewWorld.value,last_war_state:null} as Snapshot : null);
function placeMap(point:MapPoint) {if(!mapPickLabel.value)return;activeComposer()?.placeSelected(point);cancelMapPick();}
function showScenarioManager() {if(!minimized.value)phase.value='select';cancelMapPick();}
watch(productMode, value => {
  draft.simulation_mode = value === 'analysis' ? 'replay' : 'open';
  customValid.value = true; customConfiguration.value = null;
  configurationDraftId.value=null;syntheticPreview.value=null;mapSelection.value=null;
  if(value==='analysis'){historicalParameters.value=null;historicalValid.value=false;historicalAvailable.value=false;historicalDraftId.value=null;historicalPreview.value=null;}
});
watch([()=>draft.battle,productMode,()=>draft.execution_backend,syntheticBasis,phase,configurationDraftId,historicalDraftId],()=>{launchIssue.value='';mapPickLabel.value=null;});
const backendChosen = ref(false);
const afsimReady = computed(() => !!props.health?.afsim?.available && props.health?.runtime?.enabled !== false);
watch(afsimReady, available => {
  if (!backendChosen.value) draft.execution_backend = available ? 'afsim' : 'narrative';
}, { immediate: true });
const messages = ref<{ role: string; content: string }[]>([]);
const question = ref('');
const planning = ref(false);
const planError = ref('');
const sources = ref<{ source: string; section: string }[]>([]);
const ready = ref(false);
const steps = computed(() => stepOptions(draft.time_step));
watch(() => draft.simulation_mode, value => { if (value === 'replay') {
  draft.use_rag = true; draft.use_adjudicator = false;
} });
const needsConfiguration = computed(() => productMode.value === 'synthetic');
const needsHistorical = computed(() => productMode.value === 'historical'||productMode.value==='synthetic'&&!compatibility.value);
const startDisabled = computed(() => !!props.busy || !draft.scenario.trim()||(productMode.value==='analysis'&&(sourceLoading.value||!!sourceError.value))||(needsHistorical.value&&!historicalAvailable.value)||(compatibility.value&&!localMission.value)|| (!!configurationError.value&&(needsHistorical.value||needsConfiguration.value)));
function submitScenario() {
  if (startDisabled.value || (needsConfiguration.value && (!customValid.value || !configurationDraftId.value))) return false;
  if(needsHistorical.value&&(!historicalValid.value||!historicalDraftId.value||!historicalParameters.value))return false;
  emit('start', { ...draft, synthetic_configuration:needsConfiguration.value?customConfiguration.value:null,
    historical_parameters:productMode.value==='historical'?historicalParameters.value:null,
    historical_source_version:productMode.value==='analysis'?(sourceVersion.value||null):null,
    scenario_draft_id:needsConfiguration.value?configurationDraftId.value:historicalDraftId.value,
    product_mode:productMode.value, scenario:draft.scenario });
  return true;
}
async function start() {
  if (startDisabled.value||starting.value) return;starting.value=true;
  launchIssue.value='';operationDetail.value='正在准备配置…';
  try{
  if(needsHistorical.value&&(!historicalValid.value||!historicalDraftId.value)){
    if(!historicalComposer.value||!await historicalComposer.value.prepare()){
      await nextTick();if(!launchIssue.value)launchIssue.value='历史配置未通过校验，请检查所选阶段、必需模型和估计参数。';return;
    }
    await nextTick();
  }
  if (needsConfiguration.value && (!customValid.value || !configurationDraftId.value)) {
    if (!composer.value || !await composer.value.prepare()) {
      await nextTick();if(!launchIssue.value)launchIssue.value='合成配置未通过校验，请检查名称、人员、装备数量和部署位置。';return;
    }
    await nextTick();
  }
  if(!submitScenario())launchIssue.value='配置尚未就绪，未创建战局。请修正提示后重试。';
  }catch(e){launchIssue.value=e instanceof Error?e.message:String(e);
  }finally{starting.value=false;}
}
watch([()=>draft.battle,productMode,()=>draft.execution_backend,compatibility,missions], () => {
  draft.mission_id=compatibility.value?(availableMissions.value.some(m=>m.id===draft.mission_id)?draft.mission_id:availableMissions.value[0]?.id??''):'';
},{immediate:true});
watch(()=>historicalDraftId.value,()=>{if(!compatibility.value){customConfiguration.value=null;customValid.value=false;configurationDraftId.value=null;syntheticPreview.value=null;mapSelection.value=null;}});
watch(compatibility,enabled=>{if(!enabled)draft.time_step=sharedStep.value;customConfiguration.value=null;customValid.value=false;configurationDraftId.value=null;syntheticPreview.value=null;mapSelection.value=null;});
watch(()=>draft.mission_id,()=>{if(compatibility.value){customConfiguration.value=null;customValid.value=false;configurationDraftId.value=null;syntheticPreview.value=null;mapSelection.value=null;}});
watch(localMission,m=>{if(m){draft.time_step=normalizeStep(m.time_step);draft.use_adjudicator=true;draft.use_rag=true;}});
watch(() => [draft.battle, draft.simulation_mode, draft.execution_backend, draft.mission_id,productMode.value], () => {
  const text = draft.simulation_mode === 'replay'
    ? `${draft.battle}。严格史料事件重现；未载部署、钟点与逐帧损失保持未知。`
    : productMode.value==='historical' ? `${draft.battle}。选择有史料依据的阶段和真实部队，缺载数量与部署单独标注估计；允许改变指挥与结果。`
    : compatibility.value ? `${draft.battle}。兼容代表编组合成教学：单位参考有来源，人数、装备、库存和部署为演习估计，不保证与历史战局为同一初态。`
    : productMode.value==='synthetic' ? `${draft.battle}。从同一份已验证具名历史初态派生合成演习，允许修改人数、装备、部署和编组数量；源历史快照保持只读。`
    : draft.mission_id === '__choose__' ? `${draft.battle}。初态和计算范围待选择。`
    : draft.execution_backend === 'afsim'
      ? `${draft.battle}。根据资料生成局部部署，仅验证运动，不计算交战、战损或补给效果；生成内容不自动视为历史实际部署。`
      : `${draft.battle}。按战役开始时的历史态势部署，保留双方兵力、后勤与地形约束。`;
  if (!draft.scenario || draft.scenario === managedScenario.value) draft.scenario = text;
  managedScenario.value = text;
});
const filtered = computed(() => props.battles.filter(b => (family.value !== 'korea' || b.name.startsWith('抗美援朝-')) && b.name.includes(query.value.trim()))
  .sort((a, b) => (a.name.match(/\d{4}\.\d{2}\.\d{2}/)?.[0] || '').localeCompare(b.name.match(/\d{4}\.\d{2}\.\d{2}/)?.[0] || '')));
function selectBattle(battle: Battle) {
  selected.value = battle;
  managedScenario.value = '';
  Object.assign(draft, { battle: battle.name, scenario: '', mission_id: '', time_step: productMode.value==='historical'?'30分钟':normalizeStep(battle.time_step || '30分钟'), use_rag: true });
}
function shortName(name: string) { return name.replace(/^抗美援朝-/, '').replace(/-\d{4}.*$/, ''); }
function dates(name: string) { return name.match(/\d{4}[.\d至—-]+/)?.[0] || '历史场景'; }
async function ask() {
  if (!question.value.trim() || planning.value || props.busy) return;
  const submitted = question.value.trim();
  messages.value.push({ role: 'user', content: submitted });
  question.value = ''; planning.value = true; planError.value = '';
  try {
    const data = await api.planScenario(messages.value.slice(-12));
    messages.value.push({ role: 'assistant', content: data.reply });
    ready.value = data.ready; sources.value = data.sources;
    if (data.ready) Object.assign(draft, { scenario: data.scenario, battle: data.battle, time_step: normalizeStep(data.time_step) });
  } catch (e) { planError.value = String(e); messages.value.pop(); question.value = submitted; }
  finally { planning.value = false; }
}
</script>

<template>
  <main class="launch-screen">
    <div class="launch-map"><MapView :snap="previewSnapshot" :selftest="false" :overview="true" :selected-unit="mapSelection" :picking="previewSnapshot && mapPickLabel ? 'move' : null" @unit-select="(team,name) => activeComposer()?.selectUnit(team,name)" @map-target="placeMap" /></div>
    <div v-if="previewSnapshot && minimized" class="draft-map-prompt" role="status">{{mapPickLabel ? '正在设置 '+mapPickLabel+' · 点击地图放置（计算草稿）' : '想定配置已收起；草稿保持不变'}}<button @click="cancelMapPick">返回配置</button></div>
    <header class="command-bar">
      <div class="product-mark"><img :src="'./icons/gentactix.png'" alt=""><div><strong>GenTactix <span>DSH</span></strong><small>历史战役推演工作台</small></div></div>
      <nav aria-label="应用菜单"><button class="active" @click="showScenarioManager">想定管理</button><button @click="emit('settings')">模型配置</button><button @click="emit('import')" :disabled="!!busy">导入战局</button><button v-if="canResume" @click="emit('resume')">返回当前战局</button></nav>
      <div class="connection-state"><i :class="{ online: health }"></i>{{ health ? '后端就绪' : '后端未连接' }}</div>
    </header>

    <section v-show="!minimized" class="scenario-window tactical-window" aria-labelledby="scenario-title">
      <div class="window-heading"><span class="window-index">SCENARIO</span><h1 id="scenario-title">{{ phase === 'select' ? '创建推演想定' : '确认想定参数' }}</h1><span class="window-count">{{ phase === 'select' ? '01 / 02' : '02 / 02' }}</span><button @click="minimized = true" :disabled="!!busy" aria-label="收起想定窗口">×</button></div>
      <p v-if="error && phase === 'select'" class="launch-error" role="alert">{{ error }} <button @click="emit('reconnect')">重新连接</button></p>
      <template v-if="phase === 'select'">
        <div class="creation-modes" role="tablist" aria-label="想定创建方式">
          <button role="tab" :aria-selected="mode === 'catalog'" :class="{ active: mode === 'catalog' }" @click="mode = 'catalog'">战役资料库 <span>{{ battles.length }}</span></button>
          <button role="tab" :aria-selected="mode === 'assistant'" :class="{ active: mode === 'assistant' }" @click="mode = 'assistant'">问答生成</button>
          <button role="tab" :aria-selected="mode === 'recent'" :class="{ active: mode === 'recent' }" @click="mode = 'recent'">已保存战局 <span>{{ recentSessions.length }}</span></button>
        </div>
        <div v-if="mode === 'catalog'" class="catalog-body" role="tabpanel">
          <label class="search-field"><span>搜索</span><input v-model="query" placeholder="名称、年代或战役关键词" aria-label="搜索战役"></label>
          <div class="catalog-filter"><button :class="{ active: family === 'all' }" @click="family = 'all'">全部战役</button><button :class="{ active: family === 'korea' }" @click="family = 'korea'">抗美援朝</button><small>{{ filtered.length }} 项</small></div>
          <div class="battle-list" aria-label="可选战役">
            <button v-for="(b, i) in filtered" :key="b.name" class="battle-option" :class="{ selected: selected?.name === b.name }" :aria-pressed="selected?.name === b.name" @click="selectBattle(b)">
              <span class="battle-index">{{ String(i + 1).padStart(2, '0') }}</span><span><strong>{{ shortName(b.name) }}</strong><small>{{ dates(b.name) }} · 建议 {{ b.time_step || '30分钟' }}/回合</small></span><span class="selection-check">{{ selected?.name === b.name ? '已选' : '选择' }}</span>
            </button>
            <p v-if="!filtered.length" class="empty-catalog">{{ battles.length ? '没有匹配的战役。试试其他关键词，或通过问答创建想定。' : '正在载入战役目录；如后端未连接，请先检查服务。' }}</p>
          </div>
          <div class="selection-summary"><small>当前选择</small><strong>{{ selected ? shortName(selected.name) : '请选择一场战役' }}</strong><p>史料、裁决参数与场景范围将随战役载入。</p></div>
        </div>
        <div v-else-if="mode === 'assistant'" class="assistant-body" role="tabpanel">
          <p class="muted">描述战役、时间范围和关注的问题，助手将整理可编辑的想定草案。</p>
          <div class="planning-messages" aria-live="polite">
            <p v-if="!messages.length" class="assistant-placeholder">例如：以1952年上甘岭为背景，重点观察坑道补给与炮兵协同，每15分钟推进一次。</p>
            <article v-for="(m, i) in messages" :key="i" :class="m.role"><small>{{ m.role === 'user' ? '你的需求' : '想定助手' }}</small><p>{{ m.content }}</p></article>
            <p v-if="planning" role="status">正在通过DSH整理想定…</p>
          </div>
          <form @submit.prevent="ask" class="planning-input"><label for="scenario-question">你的想定需求</label><textarea id="scenario-question" v-model="question" rows="3" :disabled="planning || !!busy" placeholder="输入历史背景或希望观察的决策…"></textarea><button :disabled="planning || !!busy || !question.trim()">发送需求</button></form>
          <p v-if="planError" class="bad" role="alert">{{ planError }}</p>
          <small v-if="sources.length" class="muted">本地参考：{{ sources.map(s => s.section).join('、') }}</small>
          <p v-if="ready" class="draft-ready">想定草案已就绪，可进入下一步编辑确认。</p>
        </div>
        <div v-else class="recent-battles" role="tabpanel">
          <p v-if="!recentSessions.length" class="empty-catalog">暂无已保存战局。可从战役资料库或问答生成开始新的推演。</p>
          <article v-for="s in recentSessions" :key="s.session_id" class="saved-battle" :data-session-id="s.session_id">
            <button class="open-battle" :disabled="!!busy" @click="emit('resumeSession', s.session_id)"><span><strong>{{ s.scenario }}</strong><small>已推进 {{ s.turn_count }} 回合 · {{ s.session_id }}</small></span><span>打开战局 →</span></button>
            <button class="delete-battle" :disabled="!!busy" :aria-label="`删除战局 ${s.session_id}`" @click="emit('deleteSession', s)">删除</button>
          </article>
        </div>
        <footer class="window-footer"><span>{{ mode === 'recent' ? '恢复保存的态势、回合与分析记录' : '选定想定后，再配置推演规则' }}</span><button v-if="mode !== 'recent'" class="primary" :disabled="!!busy || planning || (mode === 'catalog' ? !selected : !ready)" @click="phase = 'configure'">继续配置 <span>→</span></button></footer>
      </template>
      <template v-else>
        <div class="scenario-form">
          <label for="draft-scenario">想定与推演目标</label><textarea id="draft-scenario" v-model="draft.scenario" rows="6" :disabled="!!busy"></textarea>
          <div class="config-row"><div><label for="draft-battle">关联战役资料</label><select id="draft-battle" v-model="draft.battle" :disabled="!!busy"><option value="">请选择战役资料</option><option v-for="b in battles" :key="b.name" :value="b.name">{{ b.name }}</option></select></div><div><label for="draft-step">回合跨度</label><select id="draft-step" v-model="draft.time_step" :disabled="!!busy||!!localMission"><option v-for="step in steps" :key="step">{{ step }}</option></select></div></div>
          <label for="draft-executor">执行引擎（三种用途均可选择）</label><select id="draft-executor" data-testid="execution-backend" v-model="draft.execution_backend" :disabled="!!busy" @change="backendChosen = true"><option value="narrative">DSH 独立推演（不启动AFSIM）</option><option value="afsim" :disabled="!afsimReady">DSH 规划 + AFSIM 计算</option></select>
          <p class="muted" data-testid="executor-scope">{{draft.execution_backend==='afsim'?'AFSIM执行运动和已登记的过程计算，DSH负责规划；回溯分析按来源事件推进。':productMode==='analysis'?'不启动AFSIM。DSH讲解当前来源节点；关键事件与次序保持史实，模型解释单独标识。':'不启动AFSIM。由DSH承担推演；程序保留状态、命令、人员装备账校验，过程结果标为模型估计。'}}</p>
          <label for="draft-mode">使用类型</label><select id="draft-mode" v-model="productMode" :disabled="!!busy"><option value="analysis" :disabled="!draft.battle">历史战役回溯分析</option><option value="historical">历史战局推演</option><option value="synthetic" :disabled="!draft.battle">合成教学演习</option></select>
          <template v-if="productMode==='analysis'">
            <label for="replay-source-version">回溯史料版本</label><select id="replay-source-version" v-model="sourceVersion" :disabled="!!busy||sourceLoading"><option v-if="!sourceVersions.length" value="">{{sourceLoading?'正在读取版本…':'默认资料版本'}}</option><option v-for="v in sourceVersions" :key="v.version" :value="v.version">{{v.version}}{{v.default?' · 默认':''}}</option></select>
            <p v-if="sourceError" role="alert" class="bad">{{sourceError}}</p><details v-if="sourceNotes.length"><summary>所选版本覆盖范围</summary><p v-for="note in sourceNotes" :key="note" class="muted">{{note}}</p></details>
          </template>
          <template v-if="needsConfiguration"><label for="draft-synthetic-basis">合成演习基础</label><select id="draft-synthetic-basis" v-model="syntheticBasis" :disabled="!!busy"><option value="shared">同一历史初态（默认）</option><option value="representative">兼容教学模板（代表编组）</option></select></template>
          <p v-if="needsConfiguration&&!compatibility" class="muted" data-testid="shared-initial-note">先生成并验证与历史战局相同的具名初态；默认完整继承，再在下方修改双方人数、装备、库存、部署与编组数量。源历史事实保持只读。</p>
          <template v-if="compatibility"><p class="muted" data-testid="representative-scope">仅用于合成教学的代表编组；人数、装备与部署为演习估计，不保证与历史战局同一初态，不冒充完整历史部署。</p><label for="draft-mission">兼容教学规则</label><select id="draft-mission" v-model="draft.mission_id" :disabled="!!busy||catalogLoading"><option v-for="m in availableMissions" :key="m.id" :value="m.id">{{m.title}}</option></select><p v-if="missionError" class="bad" role="alert">{{missionError}} <button type="button" @click="loadCompatibleMissions" :disabled="catalogLoading">重新读取兼容模板</button></p></template>
          <p v-if="productMode === 'historical'" class="muted" data-testid="initial-capability-note">使用有出处的真实部队与阶段，允许改变决策和历史结果。缺载数值由专用DSH skill生成并说明估计；完整战役覆盖仍以档案为准，不使用教学代表编组。</p>
          <HistoricalScenarioComposer v-if="productMode!=='analysis'" v-show="needsHistorical" ref="historicalComposer" :battle="draft.battle" :purpose="productMode" :time-step="compatibility?sharedStep:draft.time_step" :execution-backend="draft.execution_backend" :busy="!!busy" @change="historicalParameters=$event" @valid="historicalValid=$event" @available="historicalAvailable=$event" @draft-id="historicalDraftId=$event" @preview="historicalPreview=$event" @selection="mapSelection=$event" @pick-map="beginMapPick" @busy="composerStatus" @feedback="needsHistorical&&composerFeedback($event)" @status="needsHistorical&&(operationDetail=$event)" />
          <ScenarioComposer v-if="needsConfiguration&&(compatibility?!!localMission:historicalValid&&!!historicalDraftId)" :key="compatibility?'legacy-'+draft.mission_id:historicalDraftId??''" ref="composer" :mission-id="compatibility?draft.mission_id:''" :source-draft-id="compatibility?undefined:historicalDraftId??undefined" :execution-backend="draft.execution_backend" :busy="!!busy" @change="customConfiguration=$event" @valid="customValid=$event" @draft-id="configurationDraftId=$event" @preview="syntheticPreview=$event" @selection="mapSelection=$event" @pick-map="beginMapPick" @busy="composerStatus" @feedback="composerFeedback" />
          <p v-if="!needsHistorical" class="muted">{{ draft.simulation_mode === 'replay' ? '按审订史料逐事件重现，关键节点与顺序必须符合史实。DSH不能改写事件；未载部署、轨迹和逐帧损失保持未知。回溯不接受改写史实的作战命令。' : compatibility ? '兼容模板经DSH skill配置和所选引擎验证后创建；交战、战损与补给按已登记规则执行，演习结果允许偏离历史。' : '过程由DSH生成，允许偏离历史结果。' }}</p>
          <label class="rule-option"><input type="checkbox" v-model="draft.use_rag" :disabled="!!busy"><span><strong>本地史料约束</strong><small>检索关联战役资料，并保留来源</small></span></label>
          <label class="rule-option"><input type="checkbox" v-model="draft.use_adjudicator" :disabled="!!busy || draft.simulation_mode === 'replay'"><span><strong>确定性几何裁决</strong><small>开放推演裁决机动、接触、补给和包围；史料重现不重新裁决</small></span></label>
          <p class="muted">当前模型：{{ health?.model || '尚未连接' }} · 生成后进入推演工作台。</p>
        </div>
        <div v-if="preparing" class="launch-feedback" data-testid="launch-feedback" role="status" aria-live="polite"><span class="waiting-dot" aria-hidden="true"></span><span>{{operationDetail||busy||'正在准备配置…'}}<small>已等待 {{elapsedSeconds}} 秒 · 结果返回后自动继续</small></span></div>
        <div v-if="launchFailure" class="launch-feedback launch-failure" data-testid="launch-error" role="alert"><span>{{launchFailure}}</span><button v-if="configurationError" type="button" @click="emit('settings')">打开模型配置</button></div>
        <div class="history-next-hint" role="status">{{needsHistorical&&!historicalAvailable?(operationDetail||'请完成上方范围选择，并核对所选历史资料。'):(needsConfiguration&&!configurationDraftId)||(needsHistorical&&!historicalDraftId)?'下一步会生成或重新验证当前配置，完成后创建战局。':productMode==='analysis'?'下一步按来源节点启动回溯分析。':'下一步由所选引擎创建并初始化战局。'}}</div>
        <footer class="window-footer"><button v-if="!busy" @click="phase = 'select'">返回选择</button><button v-else @click="composerBusy ? activeComposer()?.cancel() : emit('cancel')">{{composerBusy ? '取消想定操作' : '取消初始化'}}</button><button class="primary" data-testid="launch-start" @click="start" :disabled="startDisabled||starting">{{ busy||starting ? '正在处理…' : (needsConfiguration&&!configurationDraftId)||(needsHistorical&&!historicalDraftId) ? '生成/验证配置并进入 →' : productMode === 'analysis' ? '进入回溯分析' : '创建并进入推演' }}</button></footer>
      </template>
    </section>
    <div class="overview-label"><span>中国及周边 · 地理总览</span><small>可拖动与缩放地图</small></div>
    <footer class="launch-status"><span>沈阳理工大学装备工程学院深度学习实验室</span><span>{{ health?.runtime?.connected ? 'DSH · Native已连接' : health?.runtime?.enabled ? 'DSH · 原生插件待启动' : 'DSH · JSON兼容模式' }}</span><a href="https://github.com/pystrategylab/Gentactix" target="_blank" rel="noopener noreferrer">致谢 pystrategylab / Gentactix</a></footer>
  </main>
</template>

<style scoped>
.launch-feedback{padding:12px 24px;border-top:1px solid var(--line);background:#102c3e;color:#c5e4ed;font-size:12px;line-height:1.6;flex-shrink:0;display:flex;align-items:center;gap:10px;overflow-wrap:anywhere;max-height:140px;overflow-y:auto;}
.launch-feedback small{display:block;color:var(--muted);font-size:11px;}
.launch-failure{background:#3b2227;color:#ffd0c8;align-items:flex-start;}
.launch-failure>span{flex:1;min-width:0;}.launch-failure button{flex-shrink:0;font-size:11px;}
.waiting-dot{width:7px;height:7px;border-radius:50%;background:#6dd3d0;flex-shrink:0;animation:launch-wait 1.5s ease-in-out infinite;}
@keyframes launch-wait{50%{opacity:.35;}}
@media(prefers-reduced-motion:reduce){.waiting-dot{animation:none;}}
.history-next-hint {padding:10px 24px;border-top:1px solid var(--line);color:var(--muted);font-size:12px;flex-shrink:0;}
@media(max-width:600px){.history-next-hint{padding:9px 14px;}.launch-feedback{padding:10px 14px;}.launch-failure{flex-wrap:wrap;}}
.draft-map-prompt {position:absolute;top:80px;left:50%;transform:translateX(-50%);z-index:900;max-width:85vw;padding:12px 16px;background:#102a3a;color:#c8dfe8;border:1px solid #416779;border-radius:8px;font-size:12px;display:flex;align-items:center;gap:12px;}.draft-map-prompt button{white-space:nowrap;}
</style>
