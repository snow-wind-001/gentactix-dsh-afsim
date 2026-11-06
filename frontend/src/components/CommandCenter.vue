<script setup lang="ts">
const taskRoleLabels:Record<string,string>={maneuver:"机动／突击",fire_support:"炮兵支援",engineer:"工程",reserve:"预备／掩护",sustain:"本单位补给"};
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { api, ApiError } from '../api';
import { latLng } from 'leaflet';
import {stepDurationSeconds,formatObservationAge} from '../timeSteps';
import {supplyIndex} from '../tactical';
import UnitInspector from './UnitInspector.vue';
import type { CommandView, CommandUnit, OrderDraft, MapPoint, CommandPreview, CommandProposal, CommandRevision, Snapshot, UnitDecision, CounterfactualResult } from '../types';

const props = defineProps<{ sessionId: string; snap: Snapshot; busy: boolean }>();
const selectedSupply = computed(()=>{
  const entry=data.value?.units.find(u=>u.id===selectedId.value);
  const units=entry?.team==='red'?props.snap.war_state?.red_units:props.snap.war_state?.blue_units;
  const unit=units?.find(u=>u.name===entry?.name);
  return unit?supplyIndex(unit):null;
});
const emit = defineEmits<{ preview: [value: CommandPreview | null]; picking: [value: 'move' | 'fire' | null];
  queueChanged: [];
  opened: [value: boolean];
  selected: [value: { team: string; name: string } | null]; busy: [value: string]; snapshot: [value: Snapshot] }>();
const data = ref<CommandView | null>(null), opened = ref(false), localBusy = ref(false), error = ref('');
watch(opened, value => emit('opened', value));
const selectedId = ref(''), picking = ref<'move' | 'fire' | null>(null), action = ref('hold');
const conversionChoices=ref<string[]>([]);
const duration = ref<OrderDraft['duration']>('next'), endTurn=ref(1), destination = ref<MapPoint | null>(null), targetId = ref(''), airPool = ref('');
const participation=ref<OrderDraft['participation']|''>('');
const participationLabels={withdraw:'退出当前作战',reenter:'重新投入'};
const intent = ref(''), noFire = ref(false), controlTeam = ref('red'), director = ref(false);
const text = ref(''), inputScope = ref<'unit' | 'global'>('unit'), inputMode = ref<'order' | 'consult'>('order');
const consultAnswer = ref('');
const proposal = ref<CommandProposal | null>(null), decisions = ref<UnitDecision[]>([]), decisionTotal = ref(0), offset = ref(0);
const recordOpen = ref(false), unitMenu = ref<HTMLSelectElement | null>(null), pickButton = ref<HTMLButtonElement | null>(null);
const comparison = ref<{ result: CounterfactualResult; unit: string; turn: number } | null>(null);
const proposalContext = ref(''), proposalText = ref('');
const receiptTurn = ref<number | null>(null);
const drafts = new Map<string, { action: string; duration: OrderDraft['duration']; endTurn:number;destination: MapPoint | null; targetId: string; airPool:string;participation:OrderDraft['participation']|'' }>();
const batch = ref<(CommandRevision & { batch_id: string; instruction: string }) | null>(null);
const selected = computed(() => data.value?.units.find(u => u.id === selectedId.value));
const selectedRaw=computed(()=>{
 const entry=selected.value,units=entry?.team==='red'?props.snap.war_state?.red_units:props.snap.war_state?.blue_units;
 const matches=units?.filter(u=>u.name===entry?.name)??[];return matches.length===1?matches[0]!:null;
});
const selectedSymbol=computed(()=>{const e=props.snap.plotting?.units.find(r=>r.team===selected.value?.team&&r.name===selected.value?.name);return e?props.snap.plotting?.unit_symbols[e.id]:undefined;});
const languageDetails=ref<HTMLDetailsElement|null>(null);
const actionMenu=ref<HTMLSelectElement|null>(null);
function prepareInspectorOrder(kind:string){if(!canCommand.value||locked.value||!selected.value?.capabilities.actions.includes(kind))return;if(action.value!==kind){duration.value='next';participation.value='';}action.value=kind;if(kind==='move')startPick();else void nextTick(()=>{actionMenu.value?.scrollIntoView({block:'nearest'});actionMenu.value?.focus();});}
function inspectorLanguage(){if(!canCommand.value||locked.value)return;inputScope.value='unit';inputMode.value='order';if(languageDetails.value){languageDetails.value.open=true;languageDetails.value.scrollIntoView({block:'nearest'});void nextTick(()=>languageDetails.value?.querySelector('textarea')?.focus());}}
const distanceKm = computed(() => selected.value?.position && destination.value ?
  latLng(selected.value.position.lat, selected.value.position.lng).distanceTo(latLng(destination.value.lat, destination.value.lng)) / 1000 : null);
const locked = computed(() => props.busy || localBusy.value);
const canCommand = computed(() => !!selected.value?.controllable && !!selected.value.capabilities.enabled && !data.value?.read_only);
const nativeEnabled = computed(() => props.snap.causal?.runtime.enabled !== false);
const labels: Record<string, string> = { hold: '待命', move: '移动', fire: '攻击', resupply: '补给', sabotage: '破袭交通', repair: '修复交通', conceal: '隐蔽', air_support: '航空支援', accept: '接收', bombard:'炮击', suppress:'火力压制', fortify:'构筑工事', build_bridge:'架桥/修复桥梁', demolish:'破坏桥梁', repair_equipment:'装备维修', recon:'侦察', restore_comms:'恢复联络',capture:'接近受降' };
const sources: Record<string, string> = { human: '人工命令', model_batch: '批量模型规划', native_unit_agent: 'DSH 原生单位 Agent', default_hold: '规则默认待命', unavailable: '单位失能／退役', missing: '依据缺失', added_this_turn: '本轮新增，未参与起始规划', model_reconstruction: '模型历史重建', model_declared: '模型声明' };
const statuses: Record<string, string> = { queued: '待执行', executing: '持续执行', blocked: '暂停', completed: '完成', cancelled: '已撤销', recorded: '已记录', expired: '已终止' };
const inputContext = computed(() => JSON.stringify([props.sessionId, props.snap.turn_count, data.value?.revision,
  data.value?.world_version, data.value?.epoch, selectedId.value, inputMode.value, inputScope.value,
  text.value, destination.value, action.value, duration.value, endTurn.value, targetId.value, airPool.value, participation.value,intent.value, noFire.value, controlTeam.value, director.value]));
const observationContext = computed(() => JSON.stringify([props.sessionId, selectedId.value, props.snap.turn_count,
  data.value?.world_version, data.value?.revision]));
watch(inputContext, () => { proposal.value = null; proposalContext.value = ''; }, { flush: 'sync' });
watch(observationContext, () => { comparison.value = null; decisions.value = []; recordOpen.value = false; }, { flush: 'sync' });
const permitted = (id: string) => director.value || data.value?.units.find(u => u.id === id)?.team === controlTeam.value;
const scopeChanges = computed(() => ({ orders: data.value?.orders.filter(o => !permitted(o.unit_id)) ?? [],
  agents: data.value?.unit_agents.filter(id => !permitted(id)) ?? [] }));
const needsScopeCleanup = computed(() => scopeChanges.value.orders.length + scopeChanges.value.agents.length > 0);
const unitName = (id: string) => data.value?.units.find(u => u.id === id)?.name ?? id;
const revision = (): CommandRevision => { if (!data.value) throw new Error('命令观察尚未加载'); return { expected_turn: data.value.turn, revision: data.value.revision, world_version: data.value.world_version }; };
const clean = (o: OrderDraft): OrderDraft => ({ ...(o.id ? { id: o.id } : {}), unit_id: o.unit_id, action: o.action, duration: o.duration,
  ...(o.duration==='until_turn'?{end_turn:o.end_turn}:{}),
  ...(o.participation?{participation:o.participation}:{}),
  ...(o.destination ? { destination: o.destination } : {}), ...(o.target_id ? { target_id: o.target_id } : {}), ...(o.air_pool ? {air_pool:o.air_pool} : {}) });
function endTime(turn:number|undefined){
 const now=props.snap.war_state?.current_time,step=stepDurationSeconds(props.snap.time_step);
 if(!now||!data.value||!Number.isInteger(turn)||step===null||!/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?$/.test(now))return '时间无法换算，以回合号为准';
 const timestamp=Date.parse(now.replace(' ','T')+'Z')+((turn as number)-data.value.turn)*step*1000;
 return Number.isFinite(timestamp)?new Date(timestamp).toISOString().slice(0,19).replace('T',' '):'时间无法换算，以回合号为准';
}

let refreshSequence=0,mapSelectionSequence=0;
let pendingObservation:{sid:string;promise:Promise<boolean>}|null=null;
function refresh(){
 const entry={sid:props.sessionId,promise:readCommands()};pendingObservation=entry;
 void entry.promise.finally(()=>{if(pendingObservation===entry)pendingObservation=null;});
 return entry.promise;
}
async function readCommands() {
  const sequence=++refreshSequence;
  try {
    const sid = props.sessionId, result = await api.commands(sid);
    if (sid !== props.sessionId || sequence!==refreshSequence || result.turn<props.snap.turn_count) return false;
    data.value = result; error.value = ''; intent.value = result.intent; noFire.value = result.no_fire;
    controlTeam.value = result.control_team; director.value = result.director;
    const current=result.units.find(u=>u.id===selectedId.value);
    if(current&&!current.capabilities.actions.includes(action.value)){action.value='hold';participation.value='';}
    if(participation.value&&!current?.capabilities.participation?.choices.includes(participation.value))participation.value='';
    if (selectedId.value && !result.units.some(u => u.id === selectedId.value)) selectedId.value = '';
    return true;
  } catch (e) { if(sequence===refreshSequence)error.value = `指挥数据加载失败：${e}`; return false; }
}
watch(() => [props.sessionId, props.snap.turn_count], (_v, old) => {
  if (old && old[0] !== props.sessionId) { data.value = null; selectedId.value = ''; conversionChoices.value=[];drafts.clear(); proposal.value = null; comparison.value = null; consultAnswer.value = ''; decisions.value = []; opened.value = false; batch.value = null; stopPick(); }
  void refresh();
}, { immediate: true });
watch([selected, destination, action], () => {
  emit('selected', selected.value ? { team: selected.value.team, name: selected.value.name } : null);
  emit('preview', action.value === 'move' && selected.value?.position ? {
    origin: selected.value.position, destination: destination.value, moveKm: selected.value.capabilities.move_km } : null);
});
function pointLabel(point: Partial<MapPoint> | null | undefined) { return point && typeof point.lat === 'number' && typeof point.lng === 'number' && Number.isFinite(point.lat) && Number.isFinite(point.lng) ? `${point.lat.toFixed(5)}, ${point.lng.toFixed(5)}` : '未记录'; }
function budgetNumber(value:number|null) {return value===null?'未知':value.toLocaleString('zh-CN',{maximumSignificantDigits:6});}
function stopPick() { picking.value = null; emit('picking', null); }
function choose(id: string) {
  conversionChoices.value=[];
  if (selectedId.value) drafts.set(selectedId.value, { action: action.value, duration: duration.value, endTurn:endTurn.value,destination: destination.value, targetId: targetId.value, airPool:airPool.value,participation:participation.value });
  selectedId.value = id; opened.value = true; stopPick(); recordOpen.value = false;
  const old = drafts.get(id), queued = data.value?.orders.find(o => o.unit_id === id);
  action.value = old?.action ?? queued?.action ?? 'hold'; duration.value = old?.duration ?? queued?.duration ?? 'next';
  endTurn.value=old?.endTurn??queued?.end_turn??(data.value?.turn??0)+1;
  destination.value = old?.destination ?? queued?.destination ?? null; targetId.value = old?.targetId ?? queued?.target_id ?? '';
  airPool.value=old?.airPool??queued?.air_pool??'';
  participation.value=old?.participation??queued?.participation??'';
  if(participation.value&&!selected.value?.capabilities.participation?.choices.includes(participation.value))participation.value='';
  proposal.value = null;
  void nextTick(() => unitMenu.value?.focus());
}
async function select(team: string, name: string) {
  const request=++mapSelectionSequence,sid=props.sessionId;
  if(!data.value){
    opened.value=true;
    const fetched=await(pendingObservation?.sid===sid?pendingObservation.promise:refresh());
    if(!fetched)return;
  }
  if(request!==mapSelectionSequence||sid!==props.sessionId)return;
  const matches=data.value?.units.filter(u=>u.team===team&&u.name===name)??[];
  if(matches.length!==1){error.value='当前名单没有唯一匹配的单位，请刷新后重新选择';opened.value=true;return;}
  const unit=matches[0]!;
  if (picking.value === 'fire' && selected.value && team !== selected.value.team) {
    targetId.value = unit.id; stopPick(); opened.value = true; void nextTick(() => pickButton.value?.focus()); return;
  }
  choose(unit.id);
}
function mapTarget(point: MapPoint) {
  if (picking.value !== 'move') return;
  destination.value = point; stopPick(); opened.value = true; void nextTick(() => pickButton.value?.focus());
}
function startPick() {
  picking.value = ['fire','air_support','bombard','suppress','capture'].includes(action.value) ? 'fire' : 'move'; emit('picking', picking.value);
}
function escape(e: KeyboardEvent) {
  if (e.key === 'Escape' && picking.value) { stopPick(); opened.value = true; void nextTick(() => pickButton.value?.focus()); }
}
onMounted(() => window.addEventListener('keydown', escape));
onBeforeUnmount(() => window.removeEventListener('keydown', escape));
async function operation(label: string, fn: () => Promise<void>, model = false) {
  error.value = ''; localBusy.value = true;
  emit('busy', model ? label : '指挥操作：' + label);
  try { await fn(); } catch (e) { error.value = String(e); } finally { localBusy.value = false; emit('busy', ''); }
}
async function save(orders = data.value?.orders.map(clean) ?? [], proposalId?: string, agents = data.value?.unit_agents ?? [], resets: string[] = [], scopeConfirmed = false, policy?: { intent: string; no_fire: boolean }) {
  if (needsScopeCleanup.value && !scopeConfirmed) throw new Error('控制范围变更将影响旧命令或 Agent，请先核对并确认切换');
  data.value = await api.saveCommands(props.sessionId, { ...revision(), orders, control_team: controlTeam.value,
    director: director.value, no_fire: policy?.no_fire ?? noFire.value, intent: policy?.intent ?? intent.value, unit_agents: agents, reset_agents: resets, proposal_id: proposalId });
  intent.value = data.value.intent; noFire.value = data.value.no_fire;
  batch.value = null; proposal.value = null;
  emit('queueChanged');
}
function cancelScopeChange() {
  if (!data.value) return;
  controlTeam.value = data.value.control_team; director.value = data.value.director;
}
function confirmScopeChange() { return operation('切换控制范围', () => save(
  data.value?.orders.filter(o => permitted(o.unit_id)).map(clean), undefined,
  data.value?.unit_agents.filter(permitted), [], true)); }
function enqueue() { return operation('保存命令', async () => {
  if (!selected.value || !canCommand.value) throw new Error('当前单位不可指挥');
  const draft: OrderDraft = { unit_id: selected.value.id, action: action.value, duration: duration.value };
  if(duration.value==='until_turn'){
    if(!Number.isInteger(endTurn.value)||endTurn.value<=(data.value?.turn??0)||endTurn.value>(data.value?.turn??0)+1000)throw new Error('请选择未来1至1000回合内的截止回合');
    draft.end_turn=endTurn.value;
  }
  const current = data.value?.orders.find(o => o.unit_id === draft.unit_id);
  if (current?.id) draft.id = current.id;
  if (action.value === 'move') { if (!destination.value) throw new Error('请先在地图选择目的地'); draft.destination = destination.value; }
  if(action.value==='move'&&participation.value){
    if(!selected.value.capabilities.participation?.enabled||!selected.value.capabilities.participation.choices.includes(participation.value))throw new Error('参与状态已变化，请刷新后选择有效的退出或重新投入命令');
    draft.participation=participation.value;draft.duration='until_arrived';
  }
  if (['fire','bombard','suppress','capture'].includes(action.value) || action.value === 'air_support') { if (!targetId.value) throw new Error('请选择敌方目标'); draft.target_id = targetId.value; }
  if(action.value==='air_support'&&selected.value.capabilities.air_pools?.length){
    const pools=selected.value.capabilities.air_pools;const id=airPool.value||(pools.length===1?pools[0]!.id:'');
    if(!pools.some(p=>p.id===id))throw new Error('请选择本方可用航空部队');draft.air_pool=id;
  }
  await save([...(data.value?.orders.filter(o => o.unit_id !== draft.unit_id).map(clean) ?? []), draft]);
}); }
function remove(id: string) { return operation('撤销命令', async () => { data.value = await api.cancelCommand(props.sessionId, id, revision()); batch.value = null; emit('queueChanged'); }); }
function toggleAgent(u: CommandUnit, checked: boolean) { return operation('设置原生单位 Agent', async () => {
  const ids = new Set(data.value?.unit_agents ?? []); if (checked) ids.add(u.id); else ids.delete(u.id);
  await save(undefined, undefined, [...ids]);
}); }
function resolve() { return operation('DSH 正在解析指挥…', async () => {
  proposal.value = null; proposalContext.value = '';
  if (!text.value.trim()) return;
  if (inputMode.value === 'consult') {
    const response = await api.chat(props.sessionId, text.value);
    consultAnswer.value = response.chat_messages.at(-1)?.content ?? '未返回答复';
    emit('snapshot', response); return;
  }
  const context = inputContext.value, original = text.value;
  const result = await api.resolveCommands(props.sessionId, { ...revision(), text: original,
    selected_units: inputScope.value === 'unit' && selected.value ? [selected.value.id] : [], map_target: destination.value });
  if (context !== inputContext.value) { error.value = '解析期间输入或战局已改变，旧草稿已丢弃，请重新解析'; return; }
  proposalContext.value = context; proposalText.value = original; proposal.value = result;
}, true); }
function confirmProposal() { return operation('确认命令草稿', async () => {
  const draft = proposal.value;
  if (!draft || draft.status !== 'draft' || proposalContext.value !== inputContext.value) throw new Error('输入或战局已改变，请重新解析草稿');
  await save(draft.orders, draft.id, undefined, [], false, { intent: draft.intent, no_fire: draft.no_fire });
}); }
async function records(page = 0) {
  await operation('读取决策', async () => {
    const context = observationContext.value;
    const result = await api.unitDecisions(props.sessionId, selectedId.value, page,
      typeof receiptTurn.value === 'number' ? receiptTurn.value : undefined);
    if (context === observationContext.value) { decisions.value = result.items; decisionTotal.value = result.total; offset.value = page; recordOpen.value = true; }
  });
}
function compareHold() { return operation('只读命令对照', async () => {
  if (!selected.value || !data.value) return;
  const context = observationContext.value, unit = selected.value.name, turn = data.value.turn;
  comparison.value = null;
  const result = await api.compareCommands(props.sessionId, { ...revision(), turn,
    orders: [{ unit_id: selected.value.id, action: 'hold', duration: 'next' }] });
  if (context === observationContext.value) comparison.value = { result, unit, turn };
}); }
async function next(instruction: string) {
  // A snapshot can arrive before its asynchronous command-view watcher. Always
  // obtain a current revision for a new batch; retain an uncertain existing
  // batch verbatim so retry still uses server-side idempotency.
  if (!batch.value || batch.value.instruction!==instruction) {
    if(!await refresh())throw new Error('命令版本尚未刷新，请重试；未提交新批次');
  }
  if (!data.value?.enabled) return api.next(props.sessionId, instruction);
  if (!batch.value || batch.value.instruction !== instruction) batch.value = { ...revision(), batch_id: crypto.randomUUID(), instruction };
  try {
    const result = await api.next(props.sessionId, instruction, batch.value);
    batch.value = null; return result;
  } catch (e) {
    // A 409 explicitly rejects execution; a lost network reply may already be committed.
    if (e instanceof ApiError && e.status === 409) { batch.value = null; await refresh(); }
    throw e;
  }
}
function branch() { return operation('建立开放分支', async () => { emit('snapshot', await api.openBranch(props.sessionId, revision())); }); }
async function applyConversion(mapping:Record<string,string[]>){
 const previous=selectedId.value,sid=props.sessionId,wasOpened=opened.value;
 drafts.clear();selectedId.value='';conversionChoices.value=[];proposal.value=null;comparison.value=null;
 consultAnswer.value='';text.value='';destination.value=null;targetId.value='';airPool.value='';participation.value='';
 action.value='hold';duration.value='next';batch.value=null;recordOpen.value=false;stopPick();
 // Let the snapshot prop watcher start its ordinary refresh first; this explicit
 // refresh then owns the latest sequence rather than losing the identity handoff.
 await nextTick();
 if(!await refresh()||props.sessionId!==sid)return;
 const candidates=[...new Set(mapping[previous]??(previous?[previous]:[]))].filter(id=>data.value?.units.some(u=>u.id===id&&u.present));
 if(candidates.length===1){choose(candidates[0]!);opened.value=wasOpened;}
 else if(candidates.length>1){conversionChoices.value=candidates;opened.value=true;}
}
function close(){mapSelectionSequence++;opened.value=false;stopPick();}
defineExpose({ select, mapTarget, next, refresh, applyConversion,close });
</script>

<template>
  <div class="command-launch"><button data-testid="command-toggle" @click="opened = !opened" :aria-expanded="opened">单位指挥 · {{ data?.orders.length ?? 0 }} 项命令</button></div>
  <div v-if="picking" class="pick-banner" role="status">{{ picking === 'move' ? '单击地图选择目的地' : '点击敌方军标或在目标名单选择' }} · <button @click="stopPick(); opened = true">取消选点 (Esc)</button></div>
  <section v-show="opened && !picking" class="command-panel" aria-label="战棋指挥面板" data-testid="command-panel">
    <header><b>战棋指挥</b><button @click="close" aria-label="收起指挥面板">×</button></header>
    <p v-if="error" role="alert" class="error">{{ error }} <button @click="refresh">刷新版本</button></p>
    <p v-if="!data&&!error" role="status">正在读取单位指挥数据…</p>
    <template v-if="data">
      <p class="muted">T+{{ data.turn }} · 修订 {{ data.revision }} · {{ data.read_only ? '历史回放，只读' : '确认入队后，下一轮统一执行' }}</p>
      <button @click="refresh" :disabled="locked">刷新命令</button>
      <button v-if="data.read_only" @click="branch" :disabled="locked">从当前态势建立开放分支</button>
      <section v-if="conversionChoices.length" data-testid="conversion-selection" aria-label="请选择转换后的当前单位">
        <p role="status">原单位已变为多个当前执行单位，请明确选择一个；旧草稿已清除。</p>
        <button v-for="id in conversionChoices" :key="id" type="button" :disabled="locked" @click="choose(id)">选择{{data.units.find(u=>u.id===id)?.name??id}}</button>
      </section>
      <label>单位名单（含无坐标单位）<select ref="unitMenu" :value="selectedId" @change="choose(($event.target as HTMLSelectElement).value)"><option value="">选择单位</option><option v-for="u in data.units" :key="u.id" :value="u.id">{{ u.team === 'red' ? '红' : '蓝' }} · {{ u.name }}{{ !u.present ? '（已退役）' : u.ambiguous ? '（同名不可指挥）' : '' }}</option></select></label>
      <template v-if="selected">
        <p><b>{{ selected.name }}</b> · {{ selected.available ? '可用' : '失能' }} · {{ selected.position ? '已知位置' : '坐标未记录' }}</p>
        <UnitInspector v-if="snap.war_state" :unit="selectedRaw" :world="snap.war_state" :team="selected.team" :turn="snap.turn_count" :command="data.turn===snap.turn_count?selected:undefined" :agent="data.turn===snap.turn_count?data.unit_agents.includes(selected.id):undefined" :symbol-id="selectedSymbol" :busy="locked" :read-only="data.read_only" @prepare-order="prepareInspectorOrder" @language="inspectorLanguage" />
        <p class="muted" data-testid="selected-unit-resources">{{ selected.type ?? '兵种未记录' }} · 人员 {{ selected.personnel?.current ?? '未记录' }} · 粮食 {{ selected.logistics?.food ?? '未记录' }} · 弹药 {{ selected.logistics?.ammo ?? '未记录' }} · 补给指数 {{selectedSupply??'未记录'}} · 直射范围 {{ selected.attack_range ?? '未记录' }} m</p>
        <p v-if="selected.personnel_strength_pct!==undefined" class="muted" data-testid="selected-unit-strength">人员保有率 {{selected.personnel_strength_pct}}%（现有／累计投入，非核定编制满员率）</p>
        <p v-for="warning in selected.capabilities.weapon_warnings??[]" :key="warning" class="muted" data-testid="weapon-warning">{{warning}}</p>
        <p class="muted" v-if="!canCommand">{{ selected.capabilities.reason || '无指挥权限；双边控制需启用导演模式并保存' }}</p>
        <p v-if="selected.capabilities.arrival?.status==='staging'" class="muted" data-testid="unit-arrival">{{selected.capabilities.arrival.event_kind==='departure'?'待启程': '待入场'}} · {{selected.capabilities.arrival.not_before}}起可参与行动（计算时点估计）。{{selected.capabilities.arrival.event_kind==='departure'?'解锁后仍须按命令行军，不表示已接敌。':selected.capabilities.arrival.event_kind==='battlefield_entry'?'从配置的前沿区域参与，不模拟此前驻地行程。':''}}保留人员装备账，可待命、补给、侦察或恢复联络。</p>
        <p v-if="selected.capabilities.participation" class="muted" data-testid="unit-participation-status">当前参与：{{selected.capabilities.participation.label}}<template v-if="selected.capabilities.participation.operation_zone"> · 作战区{{selected.capabilities.participation.operation_zone==='inside'?'内':'外'}}</template> · {{selected.capabilities.participation.controls_objectives?'可承担作战目标':'暂不承担作战目标'}}。后方仍保留实际位置、伤损与库存，可受到攻击。</p>
        <label>行动<select ref="actionMenu" data-testid="unit-action" v-model="action" :disabled="locked || !canCommand" @change="duration = 'next';participation='' "><option v-for="a in selected.capabilities.actions" :key="a" :value="a">{{ labels[a] ?? a }}</option></select></label>
        <p v-if="selected.capabilities.weapon_limits_m?.[action]" class="muted" data-testid="selected-weapon-range">当前动作射程 {{selected.capabilities.weapon_limits_m[action]!.min_range_m}}—{{selected.capabilities.weapon_limits_m[action]!.max_range_m}} m；射程不代表通视、命中或行动已获准。</p>
        <template v-if="['hold','recon','restore_comms'].includes(action)">
          <label>持续方式<select v-model="duration" :disabled="locked||!canCommand" aria-label="准备行动持续方式"><option value="next">仅下一回合</option><option value="until_turn">持续至指定回合</option></select></label>
          <template v-if="duration==='until_turn'"><label>截止回合（含）<input v-model.number="endTurn" type="number" :min="data.turn+1" :max="data.turn+1000" step="1" :disabled="locked||!canCommand" aria-label="准备行动截止回合"></label><p class="muted" data-testid="preparation-deadline">持续到T+{{endTurn}}结束，预计{{endTime(endTurn)}}（战局当地时间）。期间每轮执行此命令，可提前撤销；到期后交回规划器。不是回合内定时器。</p></template>
        </template>
        <template v-if="action === 'move'">
          <label v-if="selected.capabilities.participation">参与方式<select v-model="participation" data-testid="unit-participation" aria-label="单位参与方式" :disabled="locked||!canCommand||!selected.capabilities.participation.enabled" @change="participation&&(duration='until_arrived')"><option value="">普通机动</option><option v-for="kind in selected.capabilities.participation.choices" :key="kind" :value="kind">{{participationLabels[kind]}}</option></select></label>
          <p v-if="participation" class="muted" data-testid="participation-intent">{{participation==='withdraw'?'到达地图指定地域后转为后方待命':'到达地图指定地域后重新投入'}}；确认入队仅保存意图，实际回执才改变状态。</p>
          <div v-if="participation&&selected.capabilities.operation_routes?.length" data-testid="operation-route-command">
           <label>已登记出入通路<select aria-label="选择已登记出入通路" :disabled="locked||!canCommand" @change="destination=selected.capabilities.operation_routes?.find(r=>r.id===($event.target as HTMLSelectElement).value)?.[participation==='withdraw'?'outside':'inside']??null;duration='until_arrived'">
            <option value="">选择已登记通路目的地</option><option v-for="route in selected.capabilities.operation_routes" :key="route.id" :value="route.id" :disabled="!route.on_corridor">{{route.id}}{{route.on_corridor?'':' · 请先到通路范围'}}</option>
           </select></label>
           <p class="muted">跨界须沿登记通路。区外到达后记为场外待命；确认入队不会提前改变实际状态。</p>
           <template v-if="selected.capabilities.participation?.operation_zone==='inside'"><button v-for="route in selected.capabilities.operation_routes.filter(r=>!r.on_corridor)" :key="route.id" type="button" :disabled="locked||!canCommand" @click="destination={...route.inside};participation='';duration='until_arrived'">先机动至{{route.id}}区内点</button></template>
          </div>
          <label>持续方式<select v-model="duration" :disabled="locked || !canCommand"><option value="next" :disabled="!!participation">仅下一回合</option><option value="until_arrived">到达前持续（每轮限速）</option></select></label>
          <p class="muted">每轮 {{ selected.capabilities.move_km.toFixed(2) }} km · {{ selected.capabilities.movement_basis }}</p>
          <p data-testid="map-destination">{{ destination ? `目的地 ${destination.lat.toFixed(5)}, ${destination.lng.toFixed(5)}` : '目的地未选择' }}</p>
          <p v-if="distanceKm !== null" data-testid="movement-distance">直线 {{ distanceKm.toFixed(2) }} km<template v-if="snap.war_state?.combined_arms?.bridge.crossing_model"> · 渡运须另计排队与通道时间；距离不代表本轮可到达</template><template v-else> · 本轮后预计剩余 {{ Math.max(0, distanceKm - selected.capabilities.move_km).toFixed(2) }} km</template></p>
          <p class="muted" v-if="distanceKm !== null && distanceKm > selected.capabilities.move_km && duration === 'next'">单轮超距，请选择持续移动或重新选点；未执行。</p>
          <button ref="pickButton" @click="startPick" :disabled="locked || !canCommand || !selected.position">地图选目的地</button>
        </template>
        <template v-if="['fire','bombard','suppress','capture'].includes(action) || action === 'air_support'">
          <p v-if="action==='capture'" class="muted">受降须接近{{selected.capabilities.capture_range_m}}米，并满足目标压制或弹药条件；不会无条件清空敌方。</p>
          <p v-if="['bombard','suppress'].includes(action)" class="muted">间瞄火力消耗实际炮弹，发射后需冷却。</p>
          <label v-if="action==='air_support'&&selected.capabilities.air_pools?.length">航空部队<select v-model="airPool" :disabled="locked||!canCommand" aria-label="航空资源池"><option value="">{{selected.capabilities.air_pools.length===1?'自动使用唯一可用部队':'请选择航空部队'}}</option><option v-for="pool in selected.capabilities.air_pools" :key="pool.id" :value="pool.id">{{pool.name}} · {{pool.package}}架/任务</option></select></label>
          <label>敌方目标<select v-model="targetId" :disabled="locked || !canCommand" aria-label="敌方目标"><option value="">选择目标</option><option v-for="u in data.units.filter(u => u.team !== selected?.team && u.present && u.available && !u.ambiguous && u.capabilities.arrival?.status!=='staging')" :key="u.id" :value="u.id">{{ u.name }}</option></select></label>
          <button ref="pickButton" @click="startPick" :disabled="locked || !canCommand">地图选目标</button>
        </template>
        <button class="primary" data-testid="enqueue-order" @click="enqueue" :disabled="locked || !canCommand">校验并加入队列</button>
        <p v-if="selected.formation" class="muted">炮弹 {{ selected.formation.shells }} 发 · 防空弹药 {{ selected.formation.aa_rounds }} 发 · 冷却 {{ selected.formation.reload_remaining_s!==undefined?selected.formation.reload_remaining_s+' 秒':selected.formation.reload_remaining+' 装填周期（旧记录）' }} · 疲劳 {{ selected.formation.fatigue }} · 压制 {{ selected.formation.suppression }} · 情报年龄 {{ formatObservationAge(selected.formation.intel_age_min) }}</p>
        <details v-if="selected.fire_resources" data-testid="fire-resource-budget">
          <summary>火力资源预算 · 当前库存</summary>
          <p class="muted">已提交 T+{{selected.fire_resources.stock_snapshot.turn??'未知'}} 余额，含已结算到货；用于后续命令预算，不是上一轮期初。</p>
          <p>{{selected.fire_resources.ammo_work.applies_to?'自卫直射弹药工作量':'弹药工作量'}} {{budgetNumber(selected.fire_resources.ammo_work.on_hand)}}；每周期 {{budgetNumber(selected.fire_resources.ammo_work.per_cycle)}}，仅按当前工作量最多 {{budgetNumber(selected.fire_resources.ammo_work.cycles_from_on_hand)}} 个{{selected.fire_resources.ammo_work.applies_to?'直射':'射击'}}周期。</p>
          <p v-if="selected.fire_resources.ammo_work.applies_to">本局炮击与压制按分类炮弹扣账，不额外消耗直射工作量。</p>
          <p v-if="selected.fire_resources.indirect">可用火炮 {{budgetNumber(selected.fire_resources.indirect.operational_guns)}} 门，炮弹 {{budgetNumber(selected.fire_resources.indirect.shells)}} 发。按每周期最多 {{budgetNumber(selected.fire_resources.indirect.shells_per_cycle_ceiling)}} 发，折合 {{budgetNumber(selected.fire_resources.indirect.full_salvos_at_ceiling)}} 次完整齐射、余 {{budgetNumber(selected.fire_resources.indirect.remaining_shells)}} 发。<template v-if="selected.fire_resources.indirect.partial_salvo_possible">余弹可部分发射。</template></p>
          <p>{{selected.fire_resources.delivery_timing==='turn_end_only'?'本局补给在轮末到货，下轮才可用于射击。':'本局按登记时点到货，可供其后射击；此处未计未来到货。'}}</p>
          <small class="muted">{{selected.fire_resources.ammo_work.applies_to?'通用直射弹药与分类炮弹分账，不互相兑换。':'工作量与炮弹独立约束，不互相兑换。'}}预算不含同根共享额度；还受通信、装填、目标、地形和时间约束，不代表实际射击次数或战果。</small>
        </details>
        <label><input type="checkbox" :checked="data.unit_agents.includes(selected.id)" @change="toggleAgent(selected, ($event.target as HTMLInputElement).checked)" :disabled="locked || !canCommand || (!nativeEnabled && !data.unit_agents.includes(selected.id))" />启用此单位的 DSH 原生 Agent</label>
        <p v-if="!nativeEnabled" class="muted">原生运行时未启用；请关闭已启用的单位 Agent 后继续人工或批量规划。</p>
        <p class="muted">仅未被人工接管的启用单位调用；复用原生会话、事件、预算与取消。</p>
        <button v-if="data.unit_agents.includes(selected.id)" @click="operation('明确重建单位会话记忆', () => save(undefined, undefined, data?.unit_agents, [selectedId]))" :disabled="locked || !canCommand || !nativeEnabled">重建此单位 Agent（清空会话记忆，保留原日志）</button>
        <button @click="records()" :disabled="locked">本单位决策／执行回执</button>
        <button v-if="snap.war_state?.mission || snap.settings?.execution_backend === 'afsim'" @click="compareHold" :disabled="locked || data.turn < 1">只读对照：上轮本单位待命</button>
        <div v-if="comparison" data-testid="unit-comparison"><b>T+{{ comparison.turn }} · {{ comparison.unit }} · 只读命令对照</b><p>{{ comparison.result.scope }}</p><p v-for="m in comparison.result.metrics" :key="m.metric">{{ m.metric }}：{{ m.factual }} → {{ m.alternative }}（{{ m.delta }}）</p></div>
      </template>
      <details><summary>控制范围与全局约束</summary>
        <label>控制方<select v-model="controlTeam" :disabled="locked || data.read_only"><option value="red">红方</option><option value="blue">蓝方</option></select></label>
        <label><input type="checkbox" v-model="director" :disabled="locked || data.read_only" />教学导演：允许控制双方</label>
        <label><input type="checkbox" v-model="noFire" :disabled="locked || data.read_only" />控制方禁止主动射击（硬约束）</label>
        <label>全局意图（软偏好）<textarea v-model="intent" rows="2" maxlength="4000" :disabled="locked || data.read_only"></textarea></label>
        <div v-if="needsScopeCleanup" data-testid="scope-transition" role="status">
          <p>切换后下列记录超出控制范围，确认后才会处理：</p>
          <p v-for="o in scopeChanges.orders" :key="o.id">撤销命令：{{ unitName(o.unit_id) }} · {{ labels[o.action] ?? o.action }}</p>
          <p v-for="id in scopeChanges.agents" :key="id">停用单位 Agent：{{ unitName(id) }}（保留历史会话与决策记录）</p>
          <button @click="confirmScopeChange" :disabled="locked || data.read_only">确认切换并处理旧命令与 Agent</button><button @click="cancelScopeChange" :disabled="locked">取消切换</button>
        </div>
        <button @click="operation('保存约束', () => save())" :disabled="locked || data.read_only || needsScopeCleanup">保存控制设置</button>
      </details>
      <details open><summary>命令队列 · {{ data.orders.length }}</summary>
        <p v-if="!data.orders.length" class="muted">暂无已确认命令。下令不会立即改变战局。</p>
        <article class="queued" v-for="o in data.orders" :key="o.id" :data-command-id="o.id"><b>{{ data.units.find(u => u.id === o.unit_id)?.name ?? '退役单位' }}</b> · {{ labels[o.action] ?? o.action }}<template v-if="o.participation"> · {{participationLabels[o.participation]}}</template> · {{ statuses[o.status] ?? o.status }}<p v-if="o.reason">{{ o.reason }}</p><span v-if="o.duration === 'until_arrived'">持续至到达</span><span v-if="o.duration==='until_turn'">持续至T+{{o.end_turn}}结束 · {{endTime(o.end_turn)}}</span><button @click="choose(o.unit_id)" :disabled="locked || data.read_only">编辑</button><button @click="remove(o.id)" :disabled="locked || data.read_only">撤销</button></article>
      </details>
      <details ref="languageDetails"><summary>自然语言：单位／全局控制</summary>
        <label>用途<select v-model="inputMode" aria-label="自然语言控制用途"><option value="order">下令：先解析草稿</option><option value="consult">咨询：只读问答</option></select></label>
        <label>范围<select v-model="inputScope" aria-label="自然语言控制范围"><option value="unit" :disabled="!selected">当前单位</option><option value="global">当前控制方全部单位</option></select></label>
        <label>指挥内容<textarea v-model="text" maxlength="4000" rows="3" placeholder="前往地图选定位置，其余单位待命。" :disabled="locked"></textarea></label>
        <button @click="resolve" :disabled="locked || !text.trim() || (data.read_only && inputMode === 'order') || (inputScope === 'unit' && !selected)">{{ inputMode === 'consult' ? '发送咨询' : 'DSH 解析为草稿' }}</button>
        <p v-if="consultAnswer" class="consult-result">只读答复：{{ consultAnswer }}</p>
        <div v-if="proposal" class="proposal">
          <b>{{ proposal.status === 'draft' ? '待确认草稿' : '需要澄清，未下令' }}</b>
          <p>解析原文：{{ proposalText }}</p><p v-for="q in proposal.clarifications" :key="q">{{ q }}</p>
          <p v-for="o in proposal.orders" :key="o.unit_id">{{ unitName(o.unit_id) }} · {{ labels[o.action] ?? o.action }}<template v-if="o.participation"> · {{participationLabels[o.participation]}}</template><template v-if="o.destination"> → {{ pointLabel(o.destination) }}</template><template v-if="o.target_id"> → {{ unitName(o.target_id) }}</template><template v-if="o.air_pool"> · 航空池 {{o.air_pool}}</template> · <template v-if="o.duration==='until_turn'">持续至T+{{o.end_turn}}结束 · {{endTime(o.end_turn)}}（战局当地时间）</template><template v-else>{{ o.duration === 'until_arrived' ? '持续至到达' : '仅下一回合' }}</template></p>
          <p>{{ proposal.intent }} · 禁止射击 {{ proposal.no_fire ? '开启' : '关闭' }}</p>
          <button @click="confirmProposal" :disabled="locked || proposal.status !== 'draft'">确认草稿并入队</button><button @click="proposal = null" :disabled="locked">丢弃草稿</button>
        </div>
      </details>
      <section v-if="recordOpen" aria-label="单位决策记录"><b>决策记录 · {{ decisionTotal }} 项</b><label>指定回合（留空查看全部）<input type="number" v-model.number="receiptTurn" min="0" :max="snap.turn_count" :disabled="locked" /></label><button @click="records()" :disabled="locked">应用回合筛选</button><p v-if="!decisionTotal">尚无本单位决策记录</p><article class="receipt" v-for="r in decisions" :key="r.id"><b>T+{{ r.turn }} · {{ sources[r.source] ?? r.source }} · {{ statuses[r.status] ?? r.status }}</b><p>{{ labels[r.action] ?? r.action }} · {{ r.rationale || '未记录公开依据' }}</p><p v-if="r.planned">计划：{{ labels[r.planned.action ?? ''] ?? r.planned.action }}<template v-if="r.planned.action === 'move'"> → {{ pointLabel(r.planned.destination ?? { lat: r.planned.lat, lng: r.planned.lng }) }}</template><template v-if="r.goal"> · 任务目的地 {{ pointLabel(r.goal) }}</template></p><p v-if="r.task_context">兵团分工：{{taskRoleLabels[r.task_context.role]??r.task_context.role}} · {{r.task_context.reason}}</p><p>实际位置：{{ pointLabel(r.before_position) }} → {{ pointLabel(r.after_position) }}</p><p v-if="r.before_personnel || r.after_personnel">人员：{{ r.before_personnel?.current ?? '未记录' }} → {{ r.after_personnel?.current ?? '未记录' }}</p><p v-if="r.before_logistics || r.after_logistics">粮食：{{ r.before_logistics?.food ?? '未记录' }} → {{ r.after_logistics?.food ?? '未记录' }} · 弹药：{{ r.before_logistics?.ammo ?? '未记录' }} → {{ r.after_logistics?.ammo ?? '未记录' }}</p><p v-if="r.ledger">本轮到货 {{ r.ledger.delivery ?? '未记录' }} · 弹药消耗 {{ r.ledger.ammo_spent ?? '未记录' }}（教学工作单位）</p><p v-if="r.expected_effect">预期：{{ r.expected_effect }}</p><p v-if="r.reason">{{ r.reason }}</p><p class="muted">{{ r.history_status }}{{ r.outcome_basis === 'dsh_model_estimate' ? 'DSH估计运动、交战、战损与补给；程序校验命令、账目与目标' : r.outcome_basis === 'afsim_native_teaching_results' ? 'AFSIM实际位移、人员装备、库存与目标来自后台教学模型' : r.outcome_basis === 'afsim_motion_and_teaching_rules' ? 'AFSIM实际位移；消耗与目标由教学规则结算' : r.outcome_basis === 'afsim_observed_motion_other_effects_unmodeled' ? 'AFSIM实际位移；其余效果尚未建模' : r.outcome_basis === 'movement_verified_other_effects_model_estimated' ? '位移已核验；其余战果仍为模型估计' : r.outcome_basis === 'position_unknown_other_effects_model_estimated' ? '位置未知，保持原未知状态待命；其他效果为模型估计' : '' }}</p><code v-for="id in r.run_ids" :key="id">{{ id }}</code><code v-if="r.dsh_event_ref">{{ r.dsh_event_ref.session_id }} : {{ r.dsh_event_ref.seq }}</code></article><button @click="records(Math.max(0, offset - 25))" :disabled="locked || offset === 0">上一页</button><button @click="records(offset + 25)" :disabled="locked || offset + 25 >= decisionTotal">下一页</button></section>
    </template>
  </section>
</template>

<style scoped>
.command-launch { position: absolute; top: 58px; right: 12px; z-index: 700; }
.command-launch button { background: #143c50; box-shadow: 0 3px 12px #0005; }
.command-panel { position: absolute; top: 100px; right: 12px; z-index: 710; width: 430px; max-width: calc(100% - 24px); max-height: calc(100% - 110px); overflow: auto; padding: 14px; background: var(--panel, #102c3f); border: 1px solid var(--line); border-radius: 8px; box-shadow: 0 8px 32px #0006; font-size: 12px; }
header { position: sticky; top: -14px; z-index: 2; display: flex; justify-content: space-between; align-items: center; background: var(--panel, #102c3f); }
label { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 9px 0; }
label:has(select), label:has(textarea) { display: block; }
select, textarea { width: 100%; margin-top: 4px; }
button { padding: 6px 9px; margin: 3px 4px 3px 0; font-size: 12px; }
details, .queued, .receipt { padding-top: 9px; margin-top: 9px; border-top: 1px solid var(--line); }
summary { cursor: pointer; font-weight: 600; }
code { display: block; overflow-wrap: anywhere; font-size: 10px; }
.pick-banner { position: absolute; top: 60px; left: 65px; right: 12px; z-index: 720; padding: 8px; background: #143c50; border: 1px solid var(--accent); }
.proposal { border-left: 2px solid var(--accent); padding-left: 10px; }
@media (max-width: 700px) { .command-panel { top: auto; bottom: 8px; right: 8px; max-height: 72%; width: min(340px, calc(100% - 16px)); } .command-launch { top: 55px; } }
</style>
