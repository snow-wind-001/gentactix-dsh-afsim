<script setup lang="ts">
import {ref,computed,watch,onMounted,onBeforeUnmount} from 'vue';
import {api} from '../api';
import {militarySymbols,symbolById,militarySvg} from '../militarySymbols';
import type {PlotItem,PlottingView,PlotProposal,MapPoint} from '../types';
const props=defineProps<{sessionId:string;turn:number;busy:boolean}>();
const emit=defineEmits<{changed:[v:PlottingView];preview:[items:PlotItem[]];picking:[value:boolean];reopen:[];busy:[label:string]}>();
const data=ref<PlottingView|null>(null),error=ref(''),working=ref(false),query=ref(''),text=ref('');
const picking=ref(false),proposal=ref<PlotProposal|null>(null),unitId=ref(''),unitIcon=ref('');
const reference=ref<{id:string;name_zh:string;source_pdf_page:number;source_figure:string}[]>([]),referenceQuery=ref(''),referenceImage=ref(''),referenceLabel=ref('');
const fresh=():PlotItem=>({id:crypto.randomUUID().replaceAll('-',''),symbol_id:'hq',label:'',team:'neutral',status:'assumed',points:[],source:'教学标注',visible:true});
const draft=ref<PlotItem>(fresh());
const base=ref<{revision:number;turn:number;world_version:string}|null>(null);
const spec=computed(()=>symbolById(draft.value.symbol_id));
const rows=computed(()=>militarySymbols.filter(x=>!query.value||[x.label,x.id,...x.source_ids].some(v=>v.toLowerCase().includes(query.value.toLowerCase()))));
const locked=computed(()=>props.busy||working.value);
const stale=computed(()=>!data.value||!base.value||base.value.world_version!==data.value.world_version||base.value.revision!==data.value.revision);
const canSave=computed(()=>!locked.value&&!stale.value&&draft.value.points.length>=(spec.value.geometry==='point'?1:spec.value.geometry==='line'?2:3));
function context(){if(!data.value)throw new Error('标图尚未载入');return{revision:data.value.revision,turn:data.value.turn,world_version:data.value.world_version};}
function reset(){draft.value=fresh();base.value=data.value?context():null;proposal.value=null;setPick(false);}
function setPick(v:boolean){picking.value=v;emit('picking',v);}
let generation=0;
async function load(resetDraft=false){const token=++generation;try{const result=await api.plotting(props.sessionId);if(token!==generation)return;data.value=result;if(resetDraft||!base.value)reset();}catch(e){error.value=String(e);}}
watch(()=>[props.sessionId,props.turn],(now,old)=>{error.value='';setPick(false);proposal.value=null;void load(!old||now[0]!==old[0]);},{immediate:true});
watch([draft,proposal],()=>{emit('preview',proposal.value?.items??(draft.value.points.length?[JSON.parse(JSON.stringify(draft.value))]:[]));},{deep:true,immediate:true});
watch([text,()=>JSON.stringify(draft.value)],()=>{proposal.value=null;});
function choose(id:string){reset();draft.value.symbol_id=id;draft.value.label=symbolById(id).label;}
function finish(){setPick(false);emit('reopen');}
function mapPoint(point:MapPoint){if(!picking.value)return;if(spec.value.geometry==='point'){draft.value.points=[point];finish();}else if(draft.value.points.length<32)draft.value.points.push(point);}
function edit(id:string){const item=data.value?.items.find(x=>x.id===id);if(item){draft.value=JSON.parse(JSON.stringify(item));base.value=context();proposal.value=null;finish();}}
function escape(e:KeyboardEvent){if(e.key==='Escape'&&picking.value){e.preventDefault();finish();}}
onMounted(()=>window.addEventListener('keydown',escape));onBeforeUnmount(()=>{window.removeEventListener('keydown',escape);emit('preview',[]);emit('picking',false);});
async function save(items:PlotItem[],unit_symbols=data.value?.unit_symbols??{},ctx=base.value){if(!ctx)return;error.value='';working.value=true;try{const result=await api.savePlotting(props.sessionId,{...ctx,items,unit_symbols});data.value=result;emit('changed',result);reset();}catch(e){error.value=String(e);}finally{working.value=false;}}
function saveItem(){if(!data.value)return;void save([...data.value.items.filter(x=>x.id!==draft.value.id),JSON.parse(JSON.stringify(draft.value))]);}
function remove(id:string){if(data.value)void save(data.value.items.filter(x=>x.id!==id),data.value.unit_symbols,context());}
function toggle(id:string){if(data.value)void save(data.value.items.map(x=>x.id===id?{...x,visible:!x.visible}:x),data.value.unit_symbols,context());}
function saveUnit(){if(!data.value||!unitId.value)return;const values={...data.value.unit_symbols};if(unitIcon.value)values[unitId.value]=unitIcon.value;else delete values[unitId.value];void save(data.value.items,values,context());}
watch(unitId,()=>{unitIcon.value=data.value?.unit_symbols[unitId.value]??'';});
watch(()=>draft.value.unit_id,id=>{const unit=data.value?.units.find(u=>u.id===id);if(unit?.position)draft.value.points=[{...unit.position}];});
async function generate(){if(!data.value||!text.value.trim())return;error.value='';working.value=true;emit('busy','DSH正在按军事标图skill生成草稿…');try{proposal.value=await api.proposePlotting(props.sessionId,{...context(),text:text.value,points:draft.value.points});}catch(e){error.value=String(e);}finally{working.value=false;emit('busy','');}}
function accept(){if(!data.value||!proposal.value)return;const p=proposal.value;void save([...data.value.items,...p.items],data.value.unit_symbols,{revision:p.revision,turn:p.turn,world_version:p.world_version});}
async function searchReference(){try{reference.value=(await api.plottingReferences(referenceQuery.value)).items;}catch(e){error.value=String(e);}}
async function showReference(id:string){try{referenceImage.value='';const svg=await api.plottingReferenceSvg(id);referenceImage.value='data:image/svg+xml;base64,'+btoa(Array.from(new TextEncoder().encode(svg),b=>String.fromCharCode(b)).join(''));referenceLabel.value=id+' · 本地原图参考，非自动核实的历史符号';}catch(e){error.value=String(e);}}
defineExpose({mapPoint,finish,edit,cancelPick:finish});
</script>

<template>
 <section class="military-plotting" data-testid="military-plotting" aria-label="军事标图编辑器">
  <header><div><small>地图表达</small><h3>军事标图</h3></div><span>{{data?.items.length??0}} / 80</span></header>
  <p class="muted">图例、计划与来源独立保存；标注不会创建部队或改变战斗结果。</p>
  <p v-if="error" role="alert" class="bad">{{error}}</p>
  <button @click="error='';load(true)" :disabled="locked">刷新并开始新标注</button>
  <label>筛选符号<input v-model="query" placeholder="兵种、设施、路线或来源编号" aria-label="筛选军事符号"></label>
  <div class="symbol-palette" aria-label="应用军标库"><button v-for="s in rows" :key="s.id" :class="{active:draft.symbol_id===s.id}" @click="choose(s.id)" :disabled="locked" :aria-pressed="draft.symbol_id===s.id" :aria-label="'选择符号 '+s.label" :data-symbol-id="s.id"><span v-html="militarySvg(s.id)"></span><span>{{s.label}}</span></button></div>
  <p class="muted">{{militarySymbols.length}}个统一矢量图例；{{spec.geometry==='point'?'点定位':spec.geometry==='line'?'实际顶点路线':'实际顶点地域'}} · {{spec.id==='hq'?'定位：旗杆脚':'定位：登记锚点'}}。{{spec.meaning}}</p>
  <fieldset :disabled="locked">
   <label>标注名称<input v-model="draft.label" maxlength="80" aria-label="标注名称"></label>
   <div class="two"><label>阵营<select v-model="draft.team" aria-label="标注阵营"><option value="red">红方</option><option value="blue">蓝方</option><option value="neutral">中性</option></select></label><label>依据<select v-model="draft.status" aria-label="标注依据"><option value="assumed">教学假设</option><option value="planned">行动计划</option><option value="observed">观察/史料说明</option></select></label></div>
   <label>来源或估计说明<input v-model="draft.source" maxlength="300" aria-label="标注来源"></label>
   <label v-if="spec.geometry==='point'">位置绑定<select v-model="draft.unit_id" aria-label="绑定标注单位"><option :value="undefined">固定地图位置</option><option v-for="u in data?.units.filter(x=>x.position)??[]" :key="u.id" :value="u.id">跟随：{{u.name}}</option></select></label>
   <div class="plot-actions"><button @click="setPick(true)" data-testid="plot-pick">{{draft.points.length?'重新/继续地图选点':'在地图选点'}}</button><button @click="draft.points.pop()" :disabled="!draft.points.length">撤销上个点</button><button @click="draft.points=[]" :disabled="!draft.points.length">清空点位</button></div>
   <p class="point-summary" data-testid="plot-points">{{draft.points.length}}个顶点 · {{draft.points.map(p=>p.lat.toFixed(4)+','+p.lng.toFixed(4)).join(' → ')||'尚未落位'}}</p>
   <button class="primary" @click="saveItem" :disabled="!canSave" data-testid="plot-save">保存标注</button><span v-if="stale" class="bad">草稿依据已改变，请刷新后编辑。</span>
  </fieldset>
  <details v-if="spec.source_ids.length"><summary>图形出处参考</summary><button v-for="id in spec.source_ids" :key="id" @click="showReference(id)">{{id}} · 查看原图</button></details>
  <section class="plot-language"><h4>DSH辅助标图</h4><textarea v-model="text" :disabled="locked" rows="3" maxlength="3000" placeholder="例如：给已有补给节点加图例，或将地图选点绘为红方计划进攻路线。" aria-label="军事标图需求"></textarea><button @click="generate" :disabled="locked||!text.trim()||!data" data-testid="plot-generate">调用标图skill生成草稿</button><p class="muted">只使用选点或已知坐标；先检索图例、校验，再预览确认。</p>
   <div v-if="proposal" data-testid="plot-proposal"><b>待确认 · {{proposal.items.length}}项标注</b><p>{{proposal.explanation}}</p><p v-for="item in proposal.items" :key="item.id">{{symbolById(item.symbol_id).label}} · {{item.label}} · {{item.points.length}}顶点</p><button @click="accept" :disabled="locked" data-testid="plot-accept">确认加入标图</button><button @click="proposal=null">丢弃草稿</button></div>
  </section>
  <details><summary>部队显示符号</summary><p class="muted">只改变图例，不改变部队类型、装备或性能。</p><label>选择部队<select v-model="unitId" aria-label="选择标图部队"><option value="">请选择</option><option v-for="u in data?.units??[]" :key="u.id" :value="u.id">{{u.team==='red'?'红':'蓝'}} · {{u.name}}</option></select></label><label>显示图例<select v-model="unitIcon" aria-label="部队显示符号"><option value="">按已知兵种/主要装备自动</option><option v-for="s in militarySymbols.filter(x=>x.geometry==='point')" :key="s.id" :value="s.id">{{s.label}}</option></select></label><button @click="saveUnit" :disabled="locked||!unitId">保存显示图例</button></details>
  <section class="saved-plots"><h4>已保存标注</h4><p v-if="!data?.items.length" class="muted">尚无标注。图层为空不代表缺少部队。</p><article v-for="item in data?.items??[]" :key="item.id"><div><b>{{item.label||symbolById(item.symbol_id).label}}</b><small>{{item.status==='planned'?'计划':item.status==='observed'?'来源说明':'假设'}} · {{item.team}}</small></div><button @click="edit(item.id)" :disabled="locked">编辑</button><button @click="toggle(item.id)" :disabled="locked">{{item.visible?'隐藏':'显示'}}</button><button @click="remove(item.id)" :disabled="locked">删除</button></article></section>
  <details><summary>本地原书素材参考（256例）</summary><p class="muted">原书自动笔画组不作独立军标；参考图不等于经过历史或标准认证。未安装原库时仍可使用上方图例。</p><input v-model="referenceQuery" placeholder="编号或原图名称" aria-label="检索原书符号"><button @click="searchReference">检索参考</button><button v-for="r in reference" :key="r.id" @click="showReference(r.id)">{{r.id}} · {{r.name_zh}} · PDF {{r.source_pdf_page}}页</button></details>
  <figure v-if="referenceImage" class="source-figure"><img :src="referenceImage" :alt="referenceLabel"><figcaption>{{referenceLabel}}</figcaption></figure>
 </section>
</template>

<style scoped>
.military-plotting{font-size:12px;line-height:1.65}header{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--line);padding-bottom:12px}h3{margin:0;color:#dce9ec;font-size:17px}small,.muted{color:#91adbb}header small{letter-spacing:2px}label{display:block;margin-top:10px;color:#b8ced8}input,select,textarea{display:block;width:100%;box-sizing:border-box;margin-top:5px}button{font-size:11px;padding:7px 9px;margin:3px 4px 3px 0}.symbol-palette{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:5px;margin:12px 0;max-height:245px;overflow:auto;border-block:1px solid var(--line);padding-block:8px}.symbol-palette button{margin:0;display:flex;align-items:center;flex-direction:column;gap:2px;min-width:0;padding:7px 3px;background:transparent;border-color:transparent;color:#a8c0ce;line-height:1.3}.symbol-palette button.active{background:#163543;border-color:#6caeb9;color:#e3eef1}.symbol-palette button>span:last-child{font-size:10px;max-width:100%;overflow-wrap:anywhere}.symbol-palette :deep(svg){width:30px;height:30px}fieldset{padding:0;border:0;min-width:0}.two{display:grid;grid-template-columns:1fr 1fr;gap:12px}.plot-actions{margin-top:12px}.point-summary{font-variant-numeric:tabular-nums;overflow-wrap:anywhere;color:#91adbb}.plot-language,.saved-plots,details{border-top:1px solid var(--line);margin-top:18px;padding-top:12px}summary{cursor:pointer}h4{margin:0 0 9px;color:#d9e7eb}.saved-plots article{border-bottom:1px solid #284354;padding:9px 0}.saved-plots article>div{display:flex;justify-content:space-between;gap:8px}.source-figure{margin:14px 0;background:#eceded;padding:12px;color:#203c49}.source-figure img{display:block;width:100%;max-height:200px;object-fit:contain}.source-figure figcaption{font-size:11px;margin-top:10px}@media(max-width:450px){.symbol-palette{grid-template-columns:repeat(3,minmax(0,1fr))}}
</style>
