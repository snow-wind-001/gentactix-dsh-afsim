<script setup lang="ts">
import {computed,ref,watch} from 'vue';
import {api,ApiError} from '../api';
import ForceTaskExecutionPanel from './ForceTaskExecutionPanel.vue';
import FormationConversionPanel from './FormationConversionPanel.vue';
import type {CommandUnit,ForceView,ForceNode,MapPoint,ForceTask,ForceTaskRole,ForceTaskPreview,ForceTaskExecutionDefinition,FormationConversionCommit,FormationConversionResponse} from '../types';
const props=defineProps<{sessionId:string;turn:number;busy:boolean;readonly?:boolean;productMode?:'analysis'|'historical'|'synthetic';
 submitConversion:(sid:string,request:FormationConversionCommit)=>Promise<FormationConversionResponse>}>();
const emit=defineEmits<{changed:[];'pick-map':[];selection:[ids:string[]];'unit-select':[value:{team:string;name:string}]}>();
const data=ref<ForceView|null>(null),loading=ref(false),working=ref(false),error=ref(''),notice=ref('');
const commandUnits=ref<CommandUnit[]>([]);
const search=ref(''),team=ref(''),selected=ref<string[]>([]),groups=ref<string[]>([]),target=ref('');
const hierarchy=ref<'historical'|'command'>('command');
const label=ref(''),assumption=ref(''),action=ref('hold'),destination=ref<MapPoint|null>(null),parent=ref('');
const taskKind=ref<ForceTask['kind']>('uniform'),enemy=ref(''),replaceExisting=ref(false);
const participation=ref<ForceTask['participation']|''>('');
const roles=ref<Record<string,ForceTaskRole|''>>({}),preview=ref<ForceTaskPreview|null>(null),previewDirty=ref(false);
const execution=ref<ForceTaskExecutionDefinition|null>(null);
const roleLabels:Record<ForceTaskRole,string>={maneuver:'机动／突击',fire_support:'炮兵支援',engineer:'工程',reserve:'预备／掩护',sustain:'本单位补给'};
const actionLabels:Record<string,string>={hold:'待命',move:'机动',fire:'直射攻击',bombard:'炮击',fortify:'构筑',resupply:'本单位补给',recon:'侦察'};
const selectedTeam=computed(()=>data.value?.groups.find(g=>g.id===target.value)?.team??data.value?.nodes.find(n=>n.id===target.value)?.team);
const taskInput=computed<ForceTask>(()=>taskKind.value==='uniform'?{kind:'uniform',order:{action:action.value,duration:action.value==='move'?'until_arrived':'next',...(action.value==='move'?{destination:destination.value,...(participation.value?{participation:participation.value}:{})}:{})}}:
 {kind:taskKind.value,...(destination.value&&['advance','assault','withdraw'].includes(taskKind.value)?{destination:destination.value}:{}),
 ...(participation.value&&['advance','withdraw'].includes(taskKind.value)?{participation:participation.value}:{}),
 ...(enemy.value&&['assault','defend'].includes(taskKind.value)?{target_id:enemy.value}:{}),
 roles:Object.fromEntries(Object.entries(roles.value).filter((r):r is [string,ForceTaskRole]=>!!r[1]))});
watch([taskInput,replaceExisting,target,execution],()=>{if(preview.value)previewDirty.value=true;},{deep:true});
watch(target,()=>{roles.value={};enemy.value='';});
watch([taskKind,action],()=>{participation.value='';});
let generation=0;
async function refresh(){const g=++generation;loading.value=true;error.value='';try{const [r,commands]=await Promise.all([api.forces(props.sessionId),api.commands(props.sessionId)]);if(g===generation){
 if(preview.value&&data.value&&(r.command_revision!==data.value.command_revision||r.revision!==data.value.revision))previewDirty.value=true;
 data.value=r;commandUnits.value=commands.world_version===r.world_version&&commands.revision===r.command_revision?commands.units:[];selected.value=selected.value.filter(i=>r.controllable_ids.includes(i));groups.value=groups.value.filter(i=>r.groups.some(g=>g.id===i));
}}catch(e){if(g===generation)error.value=String(e);}finally{if(g===generation)loading.value=false;}}
watch(()=>[props.sessionId,props.turn],()=>{selected.value=[];groups.value=[];target.value='';parent.value='';notice.value='';preview.value=null;roles.value={};void refresh();},{immediate:true});
const disabled=computed(()=>props.busy||working.value||loading.value||props.readonly);
const rows=computed(()=>{
 const v=data.value;if(!v)return[];
 const index=new Map(v.nodes.map(n=>[n.id,n]));const result:{node:ForceNode;depth:number}[]=[];
 function walk(id:string,depth:number){const n=index.get(id);if(!n)return;const q=search.value.trim();
  if((!team.value||n.team===team.value)&&(!q||n.name.includes(q)||n.id.includes(q)))result.push({node:n,depth});
  for(const child of hierarchy.value==='command'?(n.command_children??n.children):n.children)walk(child,depth+1);
 }
 for(const id of hierarchy.value==='command'?(v.command_roots??v.roots):v.roots)walk(id,0);return result;
});
function displayIds(node:ForceNode){return hierarchy.value==='command'?(node.command_execution_ids??node.execution_ids):node.execution_ids;}
function displayChildren(node:ForceNode){return hierarchy.value==='command'?(node.command_children??node.children):node.children;}
function displayTotals(node:ForceNode){return hierarchy.value==='command'?(node.command_totals??node.totals):node.totals;}
function directMembers(node:ForceNode){
 const descendants=new Set(displayChildren(node).flatMap(id=>{const child=data.value?.nodes.find(n=>n.id===id);return child?displayIds(child):[];}));
 const ids=displayIds(node).filter(id=>!descendants.has(id));
 return ids.length>1?commandUnits.value.filter(unit=>ids.includes(unit.id)&&unit.present):[];
}
function selectable(node:ForceNode){return displayIds(node).filter(i=>data.value?.controllable_ids.includes(i));}
function toggle(node:ForceNode){const ids=selectable(node),all=ids.length&&ids.every(i=>selected.value.includes(i));selected.value=all?selected.value.filter(i=>!ids.includes(i)):[...new Set([...selected.value,...ids])];emit('selection',selected.value);target.value=node.id;}
function revision(){const v=data.value!;return {expected_turn:v.turn,revision:v.command_revision,world_version:v.world_version,organization_revision:v.revision};}
async function run(kind:'detach'|'merge'|'wrap'|'reparent',groupId?:string){
 if(disabled.value||!data.value)return;working.value=true;error.value='';notice.value='';
 try{const base=revision();
  if(kind==='detach')data.value=await api.detachForces(props.sessionId,{...base,unit_ids:selected.value,label:label.value,assumption:assumption.value,parent_id:parent.value||null});
  else if(kind==='merge'||kind==='wrap')data.value=await api[kind==='merge'?'mergeForces':'wrapForces'](props.sessionId,{...base,group_ids:groups.value,label:label.value,assumption:assumption.value});
  else if(kind==='reparent')data.value=await api.reparentForces(props.sessionId,{...base,group_id:groupId!,parent_id:parent.value||null,assumption:assumption.value});
  preview.value=null;
  if(parent.value&&!data.value.groups.some(g=>g.id===parent.value))parent.value='';
  selected.value=[];groups.value=[];notice.value='临时配属已保存；位置、历史建制与资源账未改变。';emit('changed');
 }catch(e){error.value=String(e);await refresh().catch(()=>{});error.value=String(e);}finally{working.value=false;}
}
async function previewTask(){
 if(disabled.value||!target.value)return;working.value=true;error.value='';notice.value='';
 const input=JSON.stringify([target.value,taskInput.value,replaceExisting.value,execution.value]);
 try{const r=await api.previewForceTask(props.sessionId,{...revision(),group_id:target.value,task:taskInput.value,replace_existing:replaceExisting.value,execution:execution.value});
  if(input===JSON.stringify([target.value,taskInput.value,replaceExisting.value,execution.value])){preview.value=r;previewDirty.value=false;}
 }catch(e){if(e instanceof ApiError&&e.status===409){await refresh();error.value='战局或命令版本已刷新，请保留当前输入并重新预览。';}else error.value=String(e);}finally{working.value=false;}
}
async function confirmTask(){
 if(disabled.value||!preview.value||previewDirty.value)return;working.value=true;error.value='';
 try{data.value=await api.commitForceTask(props.sessionId,{...revision(),group_id:target.value,task:taskInput.value,
   replace_existing:replaceExisting.value,preview_hash:preview.value.preview_hash,execution:execution.value});
  preview.value=null;notice.value=execution.value?'持续任务已确认；按前置与当前权限逐轮执行，实际结果见任务与单位回执。':'群命令已暂存；点击推演后执行。已按预览处理原人工命令与受限单位。';emit('changed');
 }catch(e){error.value=String(e);previewDirty.value=true;await refresh();error.value=String(e);}finally{working.value=false;}
}
function mapPoint(point:MapPoint){destination.value=point;}
async function selectForConversion(id:string){
 await refresh();
 if(data.value?.controllable_ids.includes(id)){selected.value=[id];emit('selection',selected.value);}
 await new Promise<void>(resolve=>requestAnimationFrame(()=>resolve()));
 document.querySelector<HTMLElement>('[data-testid="formation-conversion"]')?.scrollIntoView({block:'start'});
}
function setRole(unitId:string,event:Event){roles.value[unitId]=(event.target as HTMLSelectElement).value as ForceTaskRole|'';}
defineExpose({refresh,mapPoint,selectForConversion});
</script>

<template>
 <section class="force-panel" data-testid="force-organization">
  <header><div><small>ORDER OF BATTLE</small><h3>兵团指挥与任务编组</h3></div><button type="button" :disabled="disabled" @click="refresh">刷新</button></header>
  <p>在编制树选择单位后使用下方“实体分合兵”，分出的单位可分别下令；历史建制保持可追溯。临时任务群调整指挥关系，不拆分人员装备。</p>
  <p v-if="loading" role="status">正在读取权威编制…</p><p v-if="error" role="alert" class="error">{{error}}</p><p v-if="notice" role="status">{{notice}}</p>
  <template v-if="data">
   <div class="strengths"><div v-for="side in ['red','blue']" :key="side"><small>{{side==='red'?'红方':'蓝方'}} · {{data.totals[side]?.units}}个执行单位</small><strong>{{data.totals[side]?.current??'未知'}}<span> 人</span></strong><small>累计战斗减员 {{data.totals[side]?.casualties??'未知'}}</small></div></div>
   <div class="filters"><label>搜索编制<input v-model="search" placeholder="番号或部队ID" aria-label="搜索编制"></label><label>阵营<select v-model="team" aria-label="编制阵营"><option value="">双方</option><option value="red">红方</option><option value="blue">蓝方</option></select></label></div>
   <template v-if="data.command_baseline"><label>编制关系视图<select v-model="hierarchy" aria-label="编制关系视图"><option value="command">初始作战指挥与当前权限</option><option value="historical">行政编制参考</option></select></label><p>{{data.command_baseline.scope}}</p><details><summary>开局指挥采用依据</summary><p>{{data.command_baseline.assumption}}</p></details></template>
   <div class="force-tree" role="group" :aria-label="data.command_baseline&&hierarchy==='command'?'初始作战指挥树':'历史编制树'">
    <div v-for="{node,depth} in rows" :key="node.id" class="tree-row" :class="node.team" :style="{'--depth':Math.min(depth,5)}" :data-force-node="node.id">
     <input type="checkbox" :aria-label="`选择${node.name}及已部署下级`" :disabled="disabled||!selectable(node).length" :checked="!!selectable(node).length&&selectable(node).every(i=>selected.includes(i))" @change="toggle(node)">
     <div class="node-content"><button type="button" class="node-name" @click="target=node.effective_execution_ids.length?node.id:''"><b>{{node.name}}</b><small>{{node.echelon}} · {{displayIds(node).length?`${displayChildren(node).length?'已部署下级汇总 ':''}${displayTotals(node).current??'未知'}人 / ${displayIds(node).length}执行单位`:'参考节点 · 无已部署下级'}}{{node.role==='command'?' · 指挥机关':''}} · 当前可指挥 {{node.effective_execution_ids.length}}</small><small v-if="displayChildren(node).length&&displayIds(node).length">汇总仅含本局已部署下级；未列余部不计入。</small></button>
      <div v-if="directMembers(node).length" class="direct-members" data-testid="force-direct-members"><button v-for="unit in directMembers(node)" :key="unit.id" type="button" @click="emit('unit-select',{team:unit.team,name:unit.name})">{{unit.name}} · {{unit.personnel?.current??'未知'}}人</button></div>
     </div>
    </div>
   </div>
   <FormationConversionPanel :session-id="sessionId" :view="data" :selected-ids="selected" :busy="!!disabled" :readonly="readonly" :product-mode="productMode"
    :submit="submitConversion" @refresh="refresh" @select-unit="emit('unit-select',$event)" />
   <fieldset :disabled="disabled" v-if="!readonly">
    <legend>临时配属 · 已选 {{selected.length}} 个下级</legend>
    <label>任务群名称<input v-model="label" maxlength="80" aria-label="任务群名称" placeholder="例如：北翼阻击群"></label>
    <label>配属依据<textarea v-model="assumption" maxlength="2000" aria-label="配属依据" placeholder="说明作战任务与临时配属理由"></textarea></label>
    <label>临时上级<select v-model="parent" aria-label="临时上级"><option value="">独立任务群／无临时上级</option><option v-for="g in data.groups.filter(g=>g.member_ids.every(i=>data?.controllable_ids.includes(i)))" :key="g.id" :value="g.id">{{'　'.repeat(Math.min(g.depth,8))}}{{g.label}}</option></select></label>
    <button type="button" :disabled="!selected.length||!label.trim()||!assumption.trim()" @click="run('detach')">分出所选下级为任务群</button>
    <h4 v-if="data.groups.length">当前任务指挥树</h4>
    <div v-for="g in data.groups" :key="g.id" class="task-row" :style="{marginLeft:Math.min(g.depth,10)*12+'px'}" :data-task-group="g.id" :data-command-depth="g.depth"><label><input type="checkbox" v-model="groups" :value="g.id" :aria-label="`合编选择${g.label}`">{{g.label}} · {{g.totals.units}}单位 / {{g.totals.current??'未知'}}人<br><small>直属 {{g.direct_member_ids.length}} 单位 · 下级群 {{g.children.length}}</small></label><button type="button" @click="target=g.id">选择下令</button><button type="button" :disabled="!assumption.trim()" :aria-label="`转隶${g.label}`" @click="run('reparent',g.id)">转至所选上级</button></div>
    <button type="button" :disabled="groups.length<2||!label.trim()||!assumption.trim()" @click="run('merge')">将所选任务群合编</button>
    <button type="button" :disabled="groups.length<2||!label.trim()||!assumption.trim()" @click="run('wrap')">保留下级并建立共同上级</button>
    <p>仅同级群可合编或建立共同上级。历史树保留来源关系；已临时配属部队通过当前指挥链下令，原有单位命令继续保留。</p>
    <hr><label>下令对象<select v-model="target" aria-label="兵团下令对象"><option value="">选择编制节点或任务群</option><optgroup label="历史节点 · 未临时配属下级"><option v-for="n in data.nodes.filter(n=>n.effective_execution_ids.length&&n.effective_execution_ids.every(i=>data?.controllable_ids.includes(i)))" :key="n.id" :value="n.id">{{n.name}} · {{n.effective_execution_ids.length}}单位</option></optgroup><optgroup label="临时任务群"><option v-for="g in data.groups.filter(g=>g.member_ids.every(i=>data?.controllable_ids.includes(i)))" :key="g.id" :value="g.id">{{g.label}} · {{g.member_ids.length}}单位</option></optgroup></select></label>
    <label>任务方式<select v-model="taskKind" aria-label="兵团任务方式"><option value="uniform">统一行动</option><option value="advance">整体前进</option><option value="assault">进攻与分工</option><option value="defend">防御与构筑</option><option value="withdraw">撤退／掩护</option><option value="sustain">各单位补给</option></select></label>
    <label v-if="taskKind==='uniform'">统一行动<select v-model="action" aria-label="兵团行动"><option value="hold">保持阵地</option><option value="recon">侦察</option><option value="resupply">补给</option><option value="move">向地图目标行军</option></select></label>
    <template v-if="data.participation_supported&&(taskKind==='advance'||taskKind==='withdraw'||taskKind==='uniform'&&action==='move')">
      <label>参与方式<select v-model="participation" data-testid="force-participation" aria-label="兵团参与方式"><option value="">普通机动，不改变参与状态</option><option v-if="taskKind!=='advance'" value="withdraw">到达后退出当前作战</option><option v-if="taskKind!=='withdraw'" value="reenter">到达后重新投入</option></select></label>
      <p v-if="participation">按每个下级实际到达结算；保留原伤损、库存和任务，后方仍可受到攻击。先预览受限成员，再确认。</p>
    </template>
    <label v-if="taskKind==='assault'||taskKind==='defend'">敌方目标<select v-model="enemy" aria-label="兵团任务敌方目标"><option value="">{{taskKind==='assault'?'请选择敌方单位':'未指定交战对象'}}</option><option v-for="u in data.targets.filter(u=>u.available&&u.team!==selectedTeam)" :key="u.id" :value="u.id">{{u.name}}</option></select></label>
    <template v-if="['advance','assault','withdraw'].includes(taskKind)||(taskKind==='uniform'&&action==='move')"><button type="button" @click="emit('pick-map')">在地图选择行军目标</button><p>{{destination?`${destination.lat.toFixed(5)}, ${destination.lng.toFixed(5)}`:'尚未选点'}} · 分别按各单位速度推进，不瞬移。</p></template>
    <label><input type="checkbox" v-model="replaceExisting" aria-label="允许覆盖已有人工命令">允许覆盖本次范围内已有人工命令（默认保留）</label>
    <ForceTaskExecutionPanel v-model="execution" :session-id="sessionId" :turn="turn" :revision="data.command_revision" :busy="!!disabled" :team="selectedTeam" :can-arrive="taskKind==='advance'||taskKind==='withdraw'||(taskKind==='uniform'&&action==='move')" @changed="refresh();emit('changed')" />
    <p v-if="data.inactive_ids.length">{{data.inactive_ids.length}}个执行单位已失能，保留原账；群命令仅对可行动下级入队。</p>
    <button type="button" :disabled="!target" @click="previewTask">预览兵团任务</button>
    <section v-if="preview" data-testid="force-task-preview" aria-label="兵团任务预览">
     <p role="status">预览：{{preview.candidate_count}} 项待暂存 · {{preview.conflict_count}} 项已有命令；尚未执行。</p>
     <p v-if="previewDirty" class="error">输入已改变，请重新预览后确认。</p>
     <div class="task-preview-list" style="max-height:340px;overflow:auto">
      <article v-for="r in preview.rows" :key="r.unit_id" :data-task-unit="r.unit_id"><b>{{r.name}}</b>
       <label v-if="taskKind!=='uniform'">分工<select :value="roles[r.unit_id]??''" :aria-label="`任务分工${r.name}`" @change="setRole(r.unit_id,$event)"><option value="">自动：按登记类型</option><option v-for="(text,value) in roleLabels" :key="value" :value="value">{{text}}</option></select></label>
       <p>{{r.existing_order&&!replaceExisting?'保留原命令：'+(actionLabels[r.existing_order.action]??r.existing_order.action):r.order?(actionLabels[String(r.order.action)]??r.order.action):'不行动'}} · {{r.reason}}</p>
      </article>
     </div>
     <button type="button" :disabled="previewDirty||!preview.candidate_count" @click="confirmTask">确认暂存兵团任务</button>
    </section>
   </fieldset>
  </template>
 </section>
</template>

<style scoped>
.node-content{flex:1;min-width:0}.direct-members{display:flex;flex-wrap:wrap;gap:4px;margin:6px 0 0 8px}.direct-members button{text-align:left;color:#c4e0df}
.force-panel{font-size:12px;line-height:1.6;color:#b9cbd3}header{display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line);padding-bottom:12px}h3{margin:2px 0;color:#e8eff0;font-size:17px}header small{letter-spacing:2px;color:#91afb9}.strengths{display:flex;gap:24px;padding:14px 0;border-block:1px solid var(--line)}.strengths>div{flex:1}.strengths small,.strengths strong{display:block}.strengths strong{color:#e6d3aa;font-size:23px;font-variant-numeric:tabular-nums}.strengths span{font-size:11px}.filters{display:grid;grid-template-columns:2fr 1fr;gap:8px;margin-block:12px}label{display:block}input:not([type=checkbox]),select,textarea{display:block;width:100%;box-sizing:border-box;margin:4px 0 10px}input[type=checkbox]{accent-color:#6ebfc5}.force-tree{max-height:410px;overflow:auto;border-block:1px solid var(--line)}.tree-row{display:flex;gap:7px;align-items:center;padding:7px 3px 7px calc(var(--depth)*11px + 3px);border-bottom:1px solid #2a414d;border-left:2px solid #588ba4}.tree-row.red{border-left-color:#ab7770}.node-name{display:block;text-align:left;flex:1;border:0;background:transparent;padding:0;color:#dce7e9}.node-name small{display:block;color:#8fa6b2;font-size:10px}.task-row{border-bottom:1px solid var(--line);padding-block:8px;display:flex;gap:6px;align-items:center;flex-wrap:wrap}.task-row label{flex:1}fieldset{border:0;margin:18px 0 0;padding:0}legend{color:#d8e4e7;margin-bottom:10px}button{font-size:11px;margin-block:3px}hr{border:0;border-top:1px solid var(--line);margin-block:16px}.error{color:#efb1a7}input:focus-visible,button:focus-visible,select:focus-visible,textarea:focus-visible{outline:2px solid #82d0d0;outline-offset:2px}
</style>
