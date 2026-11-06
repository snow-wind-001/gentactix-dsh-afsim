<script setup lang="ts">
import {computed,onBeforeUnmount,ref,watch} from 'vue';
import {api,ApiError} from '../api';
import type {CommandView,ForceView,FormationConversionRequest,FormationConversionCommit,FormationConversionPreview,FormationConversionResponse} from '../types';

const props=defineProps<{sessionId:string;view:ForceView;selectedIds:string[];busy:boolean;readonly?:boolean;productMode?:'analysis'|'historical'|'synthetic';
 submit:(sid:string,request:FormationConversionCommit)=>Promise<FormationConversionResponse>}>();
const emit=defineEmits<{'select-unit':[value:{team:string;name:string}];refresh:[]}>();
const units=ref<CommandView|null>(null),kind=ref<'split'|'merge'>('split'),ids=ref<string[]>([]);
type PartDraft={id:string;label:string;committed:number;historical_unit_id?:string};
const allocations=ref<PartDraft[]>([]),assumption=ref(''),working=ref(false),error=ref(''),notice=ref('');
const preview=ref<FormationConversionPreview|null>(null),basis=ref<FormationConversionRequest|null>(null);
const pending=ref<FormationConversionCommit|null>(null),receipt=ref<FormationConversionResponse|null>(null);
let generation=0,disposed=false,part=0;
const key=(sid:string)=>'gentactix-formation-pending:'+sid;
const eligible=computed(()=>units.value?.units.filter(u=>u.present&&u.controllable&&!u.ambiguous)??[]);
const source=computed(()=>units.value?.units.find(u=>u.id===ids.value[0]));
const committed=computed(()=>ids.value.length===1?source.value?.personnel?.committed:undefined);
const historical=computed(()=>props.productMode!=='synthetic');
const sourceNode=computed(()=>{
 const id=ids.value.length===1?source.value?.id:undefined;
 const candidates=props.view.nodes.filter(n=>id&&n.execution_ids.includes(id)&&
  !props.view.nodes.some(child=>child.parent_id===n.id&&child.execution_ids.includes(id)));
 return candidates.length===1?candidates[0]:undefined;
});
const historicalChildren=computed(()=>props.view.nodes.filter(n=>n.parent_id===sourceNode.value?.id&&
 n.presence==='reported_present'&&['formation','support'].includes(n.role)));
const historicalIds=computed(()=>allocations.value.map(a=>a.historical_unit_id));
const needsResidual=computed(()=>historical.value&&sourceNode.value&&
 (sourceNode.value.children_coverage?.status!=='complete'||sourceNode.value.children.some(id=>!historicalIds.value.includes(id)))&&
 !historicalIds.value.includes('__residual__'));
const canAdd=computed(()=>allocations.value.length<32&&!!committed.value&&(!historical.value||historicalChildren.value.length>0&&
 (historicalChildren.value.some(n=>!historicalIds.value.includes(n.id))||!historicalIds.value.includes('__residual__'))));
const locked=computed(()=>props.busy||working.value||!!pending.value||props.readonly);
const request=computed<FormationConversionRequest>(()=>({expected_turn:props.view.turn,revision:props.view.command_revision,
 world_version:props.view.world_version,organization_revision:props.view.revision,kind:kind.value,unit_ids:[...ids.value],
 ...(kind.value==='split'?{allocations:allocations.value.map(a=>historical.value?
  {id:a.id,historical_unit_id:a.historical_unit_id==='__residual__'?null:a.historical_unit_id??null,committed:a.committed}:
  {id:a.id,label:a.label,committed:a.committed})}:{}),assumption:assumption.value.trim()}));
const fingerprint=computed(()=>JSON.stringify(request.value));
const duplicateLabels=computed(()=>new Set(allocations.value.map(a=>a.label.trim())).size!==allocations.value.length);
const valid=computed(()=>assumption.value.trim()&&ids.value.every(id=>eligible.value.some(u=>u.id===id))&&
 (kind.value==='merge'?ids.value.length>=2&&ids.value.length<=32:ids.value.length===1&&allocations.value.length>=2&&allocations.value.length<=32&&
 allocations.value.every(a=>Number.isInteger(a.committed)&&a.committed>0)&&
 (historical.value?!!sourceNode.value&&!needsResidual.value&&new Set(historicalIds.value).size===allocations.value.length&&
  allocations.value.every(a=>a.historical_unit_id==='__residual__'||historicalChildren.value.some(n=>n.id===a.historical_unit_id)):
  !duplicateLabels.value&&allocations.value.every(a=>a.label.trim()&&a.label.length<=40))&&
 allocations.value.reduce((n,a)=>n+a.committed,0)===committed.value));
const resultUnits=computed(()=>{
 const current=new Set(Object.values(receipt.value?.conversion_result.current_command_map??{}).flat());
 return units.value?.units.filter(u=>current.has(u.id))??[];
});
const equipmentLabels:Record<string,string>={armor:'装甲装备',artillery:'火炮',air_defense:'防空装备',engineer:'工兵装备',transport:'运输装备'};
const stockLabels:Record<string,string>={fuel_liters:'燃油（升）',spares:'备件',materials:'施工耗材',shells:'炮弹',aa_rounds:'防空弹药'};
const allocated=computed(()=>allocations.value.reduce((n,a)=>n+(Number.isFinite(a.committed)?a.committed:0),0));
function invalidate(){if(!pending.value){preview.value=null;basis.value=null;receipt.value=null;notice.value='';}}
watch(fingerprint,invalidate);
watch(()=>JSON.stringify([kind.value,ids.value,committed.value,props.productMode,sourceNode.value?.id,historicalChildren.value.map(n=>n.id)]),()=>{
 if(pending.value||kind.value!=='split')return;
 const n=committed.value;
 if(typeof n==='number'&&n>=2&&(!historical.value||historicalChildren.value.length)){part=2;
  allocations.value=[{id:'p1',label:'甲分队（估计）',historical_unit_id:historicalChildren.value[0]?.id,committed:Math.floor(n/2)},
   {id:'p2',label:'乙分队（估计）',historical_unit_id:'__residual__',committed:n-Math.floor(n/2)}];}
 else allocations.value=[];
});
watch(()=>props.selectedIds,values=>{if(!pending.value&&!working.value)ids.value=[...values];},{deep:true});
watch(()=>[props.view.world_version,props.view.command_revision,props.view.revision],()=>{invalidate();void loadUnits();});
async function loadUnits(){
 const sid=props.sessionId,g=++generation;
 try{const value=await api.commands(sid);if(!disposed&&g===generation&&sid===props.sessionId)units.value=value;}
 catch(e){if(!disposed&&g===generation)error.value='执行单位读取失败：'+String(e);}
}
watch(()=>props.sessionId,()=>{
 generation++;preview.value=null;basis.value=null;receipt.value=null;units.value=null;ids.value=[];
 pending.value=null;error.value='';notice.value='';
 try{
  const raw=localStorage.getItem(key(props.sessionId));
  if(raw){const value=JSON.parse(raw) as FormationConversionCommit;
   if(!value||typeof value.commit_id!=='string'||!/^[a-f0-9]{32}$/.test(value.commit_id)||!Array.isArray(value.unit_ids))throw Error('原提交请求损坏');
   pending.value=value;notice.value='检测到待核实的实体转换，请使用原请求查询／重试，不会生成第二笔转换。';}
 }catch(e){error.value='待核实记录无法读取：'+String(e);}
 void loadUnits();
},{immediate:true});
onBeforeUnmount(()=>{disposed=true;generation++;});
function addPart(){
 if(!canAdd.value)return;
 if(historical.value){
  const next=historicalChildren.value.find(n=>!historicalIds.value.includes(n.id));
  allocations.value.push({id:'p'+(++part),label:next?.name??'未分配余部（估计）',historical_unit_id:next?.id??'__residual__',committed:1});return;
 }
 const used=new Set(allocations.value.map(a=>a.label.trim()));let label:string;
 do{label=`第${++part}分队（估计）`;}while(used.has(label));
 allocations.value.push({id:'p'+part,label,committed:1});
}
async function showPreview(offset=0){
 if(locked.value||!valid.value)return;
 working.value=true;error.value='';const sid=props.sessionId,input=fingerprint.value;
 const value=offset&&basis.value?basis.value:JSON.parse(input) as FormationConversionRequest;
 try{
  const result=await api.previewFormation(sid,{...value,offset,limit:8,...(offset&&preview.value?{view_version:preview.value.view_version}:{})});
  if(!disposed&&sid===props.sessionId&&input===fingerprint.value){basis.value=value;preview.value=result;}
 }catch(e){if(!disposed&&sid===props.sessionId){error.value=String(e);preview.value=null;basis.value=null;if(e instanceof ApiError&&e.status===409)emit('refresh');}}
 finally{if(!disposed&&sid===props.sessionId)working.value=false;}
}
async function commit(){
 if(props.busy||working.value||props.readonly)return;
 const sid=props.sessionId;
 if(!pending.value){
  if(!preview.value||!basis.value||!valid.value)return;
  const value={...basis.value,view_version:preview.value.view_version,commit_id:crypto.randomUUID().replaceAll('-','')};
  try{localStorage.setItem(key(sid),JSON.stringify(value));pending.value=value;}
  catch(e){error.value='无法保存重试凭据，本次尚未提交：'+String(e);return;}
 }
 const original=pending.value!;working.value=true;error.value='';
 try{
  const result=await props.submit(sid,original);
  localStorage.removeItem(key(sid));
  if(disposed||sid!==props.sessionId)return;
  pending.value=null;preview.value=null;basis.value=null;ids.value=[];
  await loadUnits();receipt.value=result;
  notice.value=result.conversion_result.replayed?'已核对原提交并恢复当前身份，未重复转换。':'实体编组已保存；时钟未推进，原伤损与库存继续保留。';
 }catch(e){
  if(disposed||sid!==props.sessionId)return;
  if(e instanceof ApiError&&(e.status===409||e.status===422)){
   localStorage.removeItem(key(sid));pending.value=null;preview.value=null;basis.value=null;
   error.value=String(e)+'；本请求已明确拒收，请刷新后重新预览。';emit('refresh');
  }else error.value='提交结果待核实，原请求已保留。请使用同请求重试：'+String(e);
 }finally{if(!disposed&&sid===props.sessionId)working.value=false;}
}
</script>

<template>
 <section class="conversion" data-testid="formation-conversion" aria-label="运行中实体分合兵">
  <h4>实体分合兵</h4>
  <p>改变当前执行单位，人员、装备与库存随之交接。临时任务群仅调整指挥关系，两者分别操作；估计分队不代表新增历史番号。</p>
  <p v-if="historical">历史战局仅可选择冻结资料中本阶段在场的直接下级。投入分配仍须注明估计依据，不代表史实兵额；覆盖缺载时保留余部。</p>
  <p v-if="error" role="alert" class="error">{{error}}</p><p v-if="notice" role="status">{{notice}}</p>
  <p v-if="working" role="status">{{pending?'正在核对并保存编组…':'正在核对分配与交接…'}}</p>
  <fieldset :disabled="!!locked">
   <label>实体转换方式<select v-model="kind" aria-label="实体转换方式"><option value="split">分兵：一个单位细分</option><option value="merge">合兵：兼容分队合并</option></select></label>
   <label>实体转换单位<select v-model="ids" multiple size="5" aria-label="实体转换单位"><option v-for="u in eligible" :key="u.id" :value="u.id">{{u.team==='red'?'红':'蓝'}} · {{u.name}} · 投入{{u.personnel?.committed??'未知'}}／可用{{u.personnel?.current??'未知'}}人</option></select></label>
   <p>按Ctrl／Command可选择多个单位；也可先勾选上方编制树。本次选择{{ids.length}}个，合兵最多32个。</p>
   <template v-if="kind==='split'">
    <p>原投入{{committed??'未登记'}}人，已分配{{allocated}}人；合计必须相等，伤损不补满。</p>
    <p v-if="historical&&!historicalChildren.length">当前冻结资料未载本阶段可用的直接下级，不能虚构历史番号分兵。可先补充并验证新版资料。</p>
    <p v-if="needsResidual" role="alert" class="error">下级覆盖未证明完整，须保留未分配余部，不能将全部兵力假定为已列下级。</p>
    <p v-if="!historical&&duplicateLabels" role="alert" class="error">分队名称不可重复，请为每个执行身份设置不同名称。</p>
    <div v-for="(row,index) in allocations" :key="row.id" class="allocation" data-testid="formation-allocation">
     <label v-if="historical">分队{{index+1}}历史身份<select v-model="row.historical_unit_id" :aria-label="`分队${index+1}历史身份`">
      <option v-for="child in historicalChildren" :key="child.id" :value="child.id" :disabled="allocations.some(other=>other.id!==row.id&&other.historical_unit_id===child.id)">{{child.name}} · 本阶段在场</option>
      <option value="__residual__" :disabled="allocations.some(other=>other.id!==row.id&&other.historical_unit_id==='__residual__')">未分配余部（估计）</option>
     </select></label>
     <label v-else>分队{{index+1}}名称<input v-model="row.label" :aria-label="`分队${index+1}名称`" maxlength="40"></label>
     <label>投入人数<input v-model.number="row.committed" type="number" min="1" step="1" :aria-label="`分队${index+1}投入人数`"></label>
     <button type="button" :disabled="allocations.length<=2" :aria-label="`删除分队${index+1}`" @click="allocations.splice(index,1)">删除</button>
    </div>
    <button type="button" :disabled="!canAdd" @click="addPart">增加分队</button>
   </template>
   <label>实体转换依据<textarea v-model="assumption" aria-label="实体转换依据" maxlength="2000" placeholder="说明分配或合并依据，以及估计边界"></textarea></label>
   <button type="button" :disabled="!valid" data-testid="formation-preview" @click="showPreview()">预览实体转换</button>
  </fieldset>
  <section v-if="preview" data-testid="formation-preview-result" aria-label="实体转换只读预览">
   <p role="status">只读预览，尚未保存。执行单位{{preview.ownership.current_entities}}→{{preview.ownership.candidate_entities}}，本次建议{{preview.total_rows}}个。</p>
   <table><caption>当前选中单位总账</caption><thead><tr><th>指标</th><th>转换前</th><th>转换后</th></tr></thead><tbody>
    <tr v-for="[field,label] in [['committed','原投入'],['current','可用人员'],['casualties','战斗减员'],['noncombat_losses','非战斗减员']]" :key="field"><th>{{label}}</th><td>{{preview.totals_before.personnel[field]}}</td><td>{{preview.totals_after.personnel[field]}}</td></tr>
    <tr v-for="field in ['food','ammo']" :key="field"><th>{{field==='food'?'粮食':'弹药'}}工作量</th><td>{{preview.totals_before.normalized_stock[field]}}</td><td>{{preview.totals_after.normalized_stock[field]}}</td></tr>
    <tr v-if="(preview.totals_after.fractional_debts.noncombat_remainder??0)>0" data-testid="formation-support-load"><th>保障失能负荷（待结算）</th><td>{{preview.totals_before.fractional_debts.noncombat_remainder}}</td><td>{{preview.totals_after.fractional_debts.noncombat_remainder}}</td></tr>
   </tbody></table>
   <p>交接{{preview.session_continuity.active_tasks}}项持续任务，{{preview.session_continuity.converted_source_commands}}个来源命令身份；不复制原生智能体会话记忆。物理过程尚未执行。</p>
   <details><summary>分类装备与绝对库存守恒</summary>
    <p v-for="(values,category) in preview.totals_after.equipment" :key="category">{{equipmentLabels[category]??category}}：可用{{preview.totals_before.equipment[category]?.operational}}→{{values.operational}}，损坏{{values.damaged}}，毁坏{{values.destroyed}}</p>
    <p v-for="(value,field) in preview.totals_after.absolute_stock" :key="field">{{stockLabels[field]??field}}：{{preview.totals_before.absolute_stock[field]}}→{{value}}</p>
   </details>
   <div class="proposed-list"><article v-for="row in preview.rows" :key="row.proposed_calculation_id"><b>{{row.name}}</b><p>投入{{row.personnel.committed}}，可用{{row.personnel.current}}，战斗减员{{row.personnel.casualties}}；仅为建议身份。</p></article></div>
   <div class="pages"><button type="button" :disabled="!!locked||preview.offset===0" @click="showPreview(Math.max(0,preview.offset-preview.limit))">上一页</button><span>{{preview.offset+1}}—{{preview.offset+preview.rows.length}}／{{preview.total_rows}}</span><button type="button" :disabled="!!locked||!preview.next_args" @click="showPreview(preview.next_args!.offset)">下一页</button></div>
   <p v-if="preview.policies.fractions" data-testid="formation-fraction-policy">{{preview.policies.fractions}}</p>
   <p>{{preview.policies.state}}</p><p>{{preview.policies.location}}</p>
   <button type="button" :disabled="!!locked||!preview.formal_commit_available" data-testid="formation-confirm" @click="commit">确认保存实体转换</button>
  </section>
  <section v-if="pending" data-testid="formation-pending" aria-label="实体转换结果待核实">
   <p>保留的原提交：{{pending.kind==='split'?'分兵':'合兵'}}，来源{{pending.unit_ids.length}}个。此时不能重新编辑或创建另一笔转换。</p>
   <button type="button" :disabled="props.busy||working||readonly" data-testid="formation-retry" @click="commit">使用原请求查询／重试</button>
  </section>
  <section v-if="receipt" data-testid="formation-saved" aria-label="已保存的实体转换">
   <p>已保存第{{receipt.conversion_result.registry_revision}}次实体转换。当前位置不变，集结仍需下达移动命令。</p>
   <button v-for="u in resultUnits" :key="u.id" type="button" :disabled="props.busy" :data-current-conversion-unit="u.id" @click="emit('select-unit',{team:u.team,name:u.name})">指挥{{u.name}}</button>
  </section>
 </section>
</template>

<style scoped>
.conversion{margin-block:18px;padding:12px;border:1px solid var(--line);border-radius:8px;background:#112b36}h4{margin:0 0 8px;color:#e8eff0;font-size:15px}p{margin-block:8px}fieldset{border:0;padding:0;margin:0}label{display:block}input,select,textarea{display:block;box-sizing:border-box;width:100%;margin:4px 0 10px}.allocation{display:grid;grid-template-columns:minmax(0,2fr) minmax(70px,1fr) auto;gap:7px;align-items:center}.allocation button{align-self:center}.error{color:#efb1a7}table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}th,td{text-align:right;padding:5px;border-bottom:1px solid var(--line)}th:first-child{text-align:left}caption{text-align:left;color:#d8e4e7}.proposed-list{max-height:240px;overflow:auto}article{padding:8px 0;border-bottom:1px solid var(--line)}.pages{display:flex;align-items:center;justify-content:space-between;gap:8px}button{margin:4px 4px 4px 0;font-size:11px}input:focus-visible,select:focus-visible,textarea:focus-visible,button:focus-visible{outline:2px solid #82d0d0;outline-offset:2px}
</style>
