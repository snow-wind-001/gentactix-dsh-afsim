<script setup lang="ts">
import { computed } from 'vue';
import type { WarState,SustainmentView } from '../types';
import SustainmentPanel from './SustainmentPanel.vue';
import {formationGroupSummaries} from '../formation-parts';
import {formatObservationAge} from '../timeSteps';
const props=defineProps<{ world: WarState;sustainment?:SustainmentView|null }>();
const interaction=computed(()=>props.world.historical_initial?.definition.phases.find(p=>p.id===props.world.historical_initial?.phase_id)?.interaction);
const parentGroups=computed(()=>formationGroupSummaries(props.world));
const ledger=computed(()=>Object.fromEntries((props.world.mission?.ledger??[]).map(r=>[r.unit,r])));
const estimatedFire=computed(()=>{
 const receipt=props.world.dsh_execution?.fire_ledger;
 if(receipt?.version!=='dsh-fire-estimate-1'||receipt.source!=='dsh_model_estimate'||receipt.turn!==props.world.mission?.turn||!Array.isArray(receipt.units))return {};
 return Object.fromEntries(receipt.units.filter(r=>r&&typeof r.unit==='string'&&[r.delay_s,r.fire_cycles,r.active_fire_s,r.reload_remaining_s].every(Number.isFinite)&&[r.first_fire_s,r.last_fire_s].every(n=>n===null||Number.isFinite(n))).map(r=>[r.unit,r]));
});
const rows=computed(()=>[...(props.world.red_units ?? []).map(u=>({...u,team:'红方',combatReview:reviews.value[u.name||''],supplyLedger:ledger.value[u.name||''],fireEstimate:estimatedFire.value[u.name||'']})),...(props.world.blue_units ?? []).map(u=>({...u,team:'蓝方',combatReview:reviews.value[u.name||''],supplyLedger:ledger.value[u.name||''],fireEstimate:estimatedFire.value[u.name||'']}))]);
const usesFuel=computed(()=>rows.value.some(u=>u.formation?.motorized??props.world.mission?.definition.combined_rules?.motorized));
const reference=computed(()=>props.world.combat_reference);
const dynamicDensity=computed(()=>reference.value?.fire_dynamics??props.world.mission?.definition.fire_dynamics);
const assessment=computed(()=>props.world.combat_assessment);
const reviews=computed(()=>Object.fromEntries((assessment.value?.units??[]).map(r=>[r.name,r])));
const reviewIssues:Record<string,string>={sustained_fire_low_attrition:'持续火力下减员过低，需要复核接敌、掩护、弹耗及效能参数',fire_receipt_missing:'缺本轮火力回执，不能认定持续交火'};
const block:Record<string,string>={'0':'命令已执行','1':'桥梁未开放','2':'通行容量不足','3':'离开渡河走廊','4':'目标超出武器射程','5':'目标低于最小射程','6':'炮弹不足','7':'炮兵冷却中','8':'弹药工作量不足','9':'目标已失能','10':'燃油限制机动'};
function executionStatus(receipt:Record<string,number|string>){
 const reason=Number(receipt.blocked)>0?(block[String(receipt.blocked)]??'执行受阻，见原生回执'):'';
 if(receipt.command_done===0)return '命令未执行'+(reason?' · '+reason:'');
 if(reason)return reason;
 return receipt.command_done===1?'命令已执行':'执行完成状态未载';
}
const labels:Record<string,string>={hold:'待命',move:'移动',fire:'攻击',bombard:'炮击',suppress:'压制',fortify:'构筑',build_bridge:'架桥/修桥',demolish:'破坏桥梁',repair_equipment:'装备维修',recon:'侦察',restore_comms:'恢复联络',resupply:'补给',conceal:'隐蔽',air_support:'航空支援',accept:'接收',sabotage:'破袭交通',repair:'修复交通'};
const resources:Record<string,string>={fuel_liters:'燃油（升）',spares:'备件（件）',materials:'施工耗材（包）',shells:'炮弹（发）',aa_rounds:'防空弹药（发）'};
const ferryPhases:Record<string,string>={idle:'靠岸待命',loading:'装载',outbound:'载客航行',unloading:'抵岸卸载',returning:'空艇返航'};
const ferryEvents:Record<string,string>={loading:'开始装载',boarded:'登船出发',landed:'完成登岸',returned:'空艇抵岸',cancelled:'取消装载',repositioning:'空艇调岸'};
const resourceFlow=(r:Record<string,number>)=>Object.entries(resources).map(([k,label])=>`${label} ${r[k]??0}`).join(' · ');
const nativeReceipt=(u:{formation?:{last_execution?:{turn?:number}}})=>!props.world.dsh_execution&&u.formation?.last_execution?.turn===props.world.mission?.turn;
const firingOrder=(name:string)=>props.world.mission?.last_orders?.some(o=>o.unit===name&&['fire','bombard','suppress'].includes(o.action));
const estimatedStops:Record<string,string>={none:'本轮正常结束',ammo:'弹药不足',range:'超出射程',too_close:'低于最小射程',no_shells:'炮弹不足',target_unavailable:'目标失能',actor_unavailable:'本单位失能',uncertain:'中断原因尚不确定',command_pending:'本轮联络尚未完成',reload_pending:'本轮装填尚未完成'};
</script>

<template>
  <section v-if="world.combined_arms" class="combined-panel" aria-label="兵种与保障模型" data-testid="combined-arms">
    <div class="model-title"><strong>兵种与保障 · {{world.dsh_execution?'DSH模型估计':world.mission?.definition.historical_calculation?'AFSIM 历史单位参数化模型':'AFSIM 原生教学模型'}}</strong><code>{{ world.combined_arms.version }}</code></div>
    <p v-if="interaction" class="muted" data-testid="noncontact-execution-scope"><b>非接敌转移阶段</b> · {{interaction.scope}} 场外追兵不自动生成在场单位。</p>
    <p v-if="world.dsh_execution" class="muted">AFSIM关闭；本页过程变化为DSH估计，初态数量与规则仍可校验。</p>
    <details v-if="world.dsh_execution?.events?.length"><summary>DSH本轮过程事件（模型估计）</summary><p v-for="(event,i) in world.dsh_execution.events" :key="i">{{event.unit||event.type||'过程'}} · {{event.description||labels[event.action||'']||event.action}}<span v-if="event.seconds!==undefined"> · 回合内第{{event.seconds}}秒（发生时点）</span></p></details>
    <p class="muted">{{ world.combined_arms.source }}。地图为全知教学视图；指挥情报年龄影响效能，不代表真实传感器探测。</p>
    <p v-if="!world.dsh_execution" class="muted" data-testid="native-fire-time-scope">原生周期覆盖按轮末截断，不含上轮周期尾段；跨轮累计指标不等于实际接敌或持续受火时长。<span v-if="dynamicDensity">本局已选择动态共享密度，双方同批射击前更新；完整时间收敛仍须验收。</span><span v-else>当前间瞄目标密度在轮初取样，改变步长可能改变毁伤。</span></p>
    <SustainmentPanel v-if="sustainment" :value="sustainment" />
    <details v-if="parentGroups.length" data-testid="formation-group-ledger" open><summary>父单位与分队总账 · {{parentGroups.length}}个父单位</summary>
     <p>父单位不额外生成平台或兵力；下面是互斥分队的合计。各分队粮弹值为0–100归一化覆盖，收支按初始人员占比折合父编组工作量，绝对装备与库存直接相加。</p>
     <article v-for="group in parentGroups" :key="group.id" data-testid="formation-group-row"><b>{{group.name}}</b> · {{group.parts.length}}个计算分队 · 可用 {{group.current}} / 投入 {{group.committed}} 人 · 战斗减员 {{group.casualties}} 人<p>折合粮食 {{group.food.toFixed(4)}} · 弹药 {{group.ammo.toFixed(4)}} 工作量</p><p>{{group.assumption}}</p></article>
    </details>
    <div v-if="assessment" class="combat-review" data-testid="combat-assessment" :class="{pending:assessment.status==='review_required'}">
      <b>{{assessment.status==='review_required'?'战损效能待复核':'历史同窗口标定待完成'}}</b>
      <p>本轮历时 {{assessment.elapsed_seconds/60}} 分钟（{{assessment.elapsed_seconds}}秒）；减员按实际执行账统计。阵亡属于死伤分项，不能把战斗减员全部称为战死。</p>
      <details><summary>周期覆盖与复核依据</summary><p>{{assessment.note}}</p></details>
    </div>
    <details v-if="world.combined_arms.bridge.ferry_state" open data-testid="ferry-state"><summary>舟艇与登岸回执 · {{world.combined_arms.bridge.ferry_state.source==='afsim_native_estimate'?'AFSIM原生':'计算初态/DSH估计'}}</summary>
     <p>船位与乘载编组独立记账；登船不等于登岸，不另增加船员兵力。未建仓库跨河货运、水流、沉船或船上射击。</p>
     <article v-for="boat in world.combined_arms.bridge.ferry_state.boats" :key="boat.id" data-testid="ferry-state-row"><b>{{world.combined_arms.bridge.crossing_model?.ferry?.boats.find(b=>b.id===boat.id)?.name??boat.id}}</b> · {{ferryPhases[boat.phase]}}<p>舟位 {{boat.lat.toFixed(6)}}, {{boat.lng.toFixed(6)}} · 装卸剩余 {{boat.remaining_s.toFixed(1)}} 秒 · 完成登岸 {{boat.trips}} 航次</p><p>乘载 {{boat.passenger??'空艇'}} · 登船时 {{boat.manifest_personnel}} 人 · 装备工作量 {{boat.manifest_equipment_work}}</p></article>
     <p v-for="(event,i) in world.combined_arms.bridge.ferry_state.events" :key="i">第{{event.seconds.toFixed(1)}}秒 · {{event.boat_id}} · {{event.unit??'空艇'}} · {{ferryEvents[event.phase]??event.phase}}</p>
    </details>
    <details v-if="reference" data-testid="combat-reference"><summary>历史战损参照与当前火力模型</summary>
      <p>{{reference.scope}}。分队火力周期：直射{{reference.direct_cycle_s}}秒、炮击{{reference.artillery_cycle_s}}秒基础周期；实际受装填、射程、通信、压制和弹药约束。</p>
      <p v-for="note in reference.assumptions" :key="note">{{note}}</p>
      <p v-if="reference.benchmark.local_reference">{{reference.benchmark.local_reference}}</p>
      <p>{{reference.benchmark.scope}}；{{reference.benchmark.limitations||'不自动补齐缺载统计，也不强制推演复现战果。'}}</p>
      <article v-for="(row,i) in reference.benchmark.figures" :key="i" class="reference-row"><b>{{row.side}} · {{row.metric}}：{{row.value??'未核'}}{{row.qualifier}}</b><p>{{row.scope}}。{{row.note}}</p><a v-for="(source,j) in row.sources" :key="j" :href="source.url" target="_blank" rel="noopener noreferrer">{{source.title}} </a></article>
      <p v-for="s in reference.sources" :key="s.url"><a :href="s.url" target="_blank" rel="noopener noreferrer">{{s.title}}</a> · {{s.scope}}</p>
    </details>
    <template v-if="world.mission?.definition.combined_rules?.bridge_enabled!==false">
    <div v-for="site in [world.combined_arms.bridge,...(world.combined_arms.bridge.crossing_network?.sites??[])]" :key="site.id" class="facility" data-testid="combined-bridge"><b>{{ site.name }}</b> · 施工 {{ site.progress }}% · 完整度 {{ site.integrity }}% · 桥材组件 {{ site.materials }} 包
     <template v-if="site.crossing_model"> · 吞吐 {{site.crossing_model.throughput_work_per_hour}} 工作量/小时<p>计算通道与能力为显式估计；不是历史水文或单兵分岸模型。</p>
      <p v-if="site.crossing_receipt" data-testid="crossing-capacity">第{{site.crossing_receipt.turn}}轮 · 编组 {{site.crossing_receipt.used_work.toFixed(2)}} + 物资 {{site.crossing_receipt.cargo_work.toFixed(2)}} / {{site.crossing_receipt.budget_work.toFixed(2)}} 工作量；{{site.crossing_receipt.source==='afsim_native_estimate'?'AFSIM执行回执':'DSH估计回执'}}。</p>
     </template><template v-else> · 本轮通行 {{ site.used }} / {{ site.capacity }} 批次</template>
    </div>
    </template>
    <details><summary>仓库分类库存</summary><p v-for="(d,side) in world.combined_arms.depots" :key="side">{{ side === 'red' ? '红方' : '蓝方' }}：炮弹 {{ d.shells }} 发，防空弹药 {{ d.aa_rounds }} 发，备件 {{ d.spares }} 件，施工耗材 {{ d.materials }} 包<span v-if="usesFuel">，燃油 {{ d.fuel_liters }} 升</span></p></details>
    <article v-for="u in rows" :key="u.team + u.name" class="formation" data-testid="combined-unit">
      <template v-if="u.formation">
        <p v-if="u.crossing" data-testid="crossing-task">渡运{{ {queued:'排队',transit:'通过中',completed:'已通过',cancelled:'已撤销'}[u.crossing.status] }} · 当前任务已服务 {{u.crossing.served_work.toFixed(2)}} / {{u.crossing.required_work.toFixed(2)}} 工作量 · 第{{u.crossing.turn}}轮增量 {{u.crossing.last_work.toFixed(2)}}。整建制状态不等于已渡个人数。<span v-if="u.crossing.status==='cancelled'">旧服务消耗不退回；重新下达移动会建立新任务。</span></p>
        <div class="model-title"><b>{{ u.team }} · {{ u.name }}</b><span>可用人员 {{ u.personnel?.current ?? '未知' }} / {{ u.personnel?.committed ?? '未知' }} · 战斗减员 {{ u.personnel?.casualties ?? '未知' }}</span></div>
        <p v-if="u.formation_part" data-testid="formation-part-basis">历史父单位 {{u.formation_part.parent_name}} · 互斥计算分队 · 初始人数比重 {{(100*u.formation_part.numerator/u.formation_part.denominator).toFixed(3)}}%。粮弹为分队归一化覆盖，收支是父编组等效工作量；不是另一份父兵力。</p>
        <p data-testid="casualty-breakdown">阵亡估计 {{u.personnel?.killed??'未分'}} · 负伤估计 {{u.personnel?.wounded??'未分'}} · 失踪 {{u.personnel?.missing??'未分'}} · 被俘 {{u.personnel?.captured??'未分'}} · 既有待分类 {{u.personnel?.unclassified_casualties??'未分'}} · 非战斗减员 {{u.personnel?.noncombat_losses??'未知'}}<br><small>战斗减员率 {{u.personnel?.committed?((u.personnel.casualties/u.personnel.committed)*100).toFixed(2)+'%':'未知'}} · {{u.personnel?.breakdown_source||'旧记录未区分死伤，不能把战斗减员全部当成阵亡。'}}</small></p>
        <div v-if="u.fireEstimate" data-testid="model-fire-receipt" class="combat-review">
          <b>DSH射击过程估计 · 非原生遥测</b>
          <p>联络等待 {{u.fireEstimate.delay_s}} 秒 · 发射 {{u.fireEstimate.fire_cycles}} 周期 · 估计有效火力 {{(u.fireEstimate.active_fire_s/60).toFixed(1)}} 分钟。</p>
          <p>首发／末发为回合内 {{u.fireEstimate.first_fire_s??'未发生'}}／{{u.fireEstimate.last_fire_s??'未发生'}} 秒（发生时点） · 轮末装填剩余 {{u.fireEstimate.reload_remaining_s}} 秒 · {{estimatedStops[u.fireEstimate.stop_reason]??'见估计说明'}}。</p>
          <p>{{u.fireEstimate.assumptions}}</p>
        </div>
        <p v-else-if="world.dsh_execution&&firingOrder(u.name||'')" data-testid="model-fire-receipt-missing">此记录缺少本轮射击过程估计，不能补认持续交火时长或原生回执。</p>
        <div v-if="u.combatReview" data-testid="unit-combat-review">
          <p data-testid="turn-capture-breakdown">本轮被俘 {{u.combatReview.turn_captured??'未分类'}} 人 · 本轮负伤估计 {{u.combatReview.turn_wounded??'未分类'}} 人 · 本轮失踪 {{u.combatReview.turn_missing??'未分类'}} 人。被俘单列，不计为火力击杀。</p>
          <p v-if="u.combatReview.order_interruption==='captured_before_execution'" data-testid="capture-order-interruption">原生受降记录与本轮零射击回执一致：部队被俘，原射击命令未能执行。</p>
          <p>本轮减员 {{u.combatReview.turn_casualties}} 人（{{u.combatReview.turn_casualty_pct??'未知'}}%） · 本轮阵亡估计 {{u.combatReview.turn_killed===null?'未分类':u.combatReview.turn_killed+' 人'}}<br>来袭周期覆盖指标：本轮 {{u.combatReview.incoming_max_fire_s===null?'未知':(u.combatReview.incoming_max_fire_s!/60).toFixed(1)+' 分钟'}} · 自第{{assessment?.tracked_from_turn}}轮起累计指标 {{assessment?.source==='dsh_model_estimate'?'未知':(u.combatReview.tracked_incoming_max_fire_s/60).toFixed(1)+' 分钟'}}<span v-if="!u.combatReview.tracked_fire_time_complete">（回执缺载，仅记录已知部分）</span></p>
          <p v-for="issue in u.combatReview.issues" :key="issue" class="review-issue">{{reviewIssues[issue]||issue}}</p>
          <p v-if="u.combatReview.historical_reference" data-testid="unit-history-reference">同番号历史参照：{{u.combatReview.historical_reference!.name}}。<template v-if="u.combatReview.historical_reference!.metric_summary">{{u.combatReview.historical_reference!.metric_summary}}投入人数{{u.combatReview.historical_reference!.committed_approx===null?'未核':u.combatReview.historical_reference!.committed_approx+' 人'}}。</template><template v-else>投入约 {{u.combatReview.historical_reference!.committed_approx??'未核'}} 人、死伤约 {{u.combatReview.historical_reference!.casualties_approx??'未核'}} 人。</template>{{u.combatReview.historical_reference!.note}}<a :href="u.combatReview.historical_reference!.source.url" target="_blank" rel="noopener noreferrer">查看来源</a></p>
        </div>
        <p><span v-if="u.formation.motorized!==undefined">{{u.formation.motorized?'摩托化机动':'非摩托化机动'}} · </span>疲劳 {{ u.formation.fatigue }} · 压制 {{ u.formation.suppression }} · 工事 {{ u.formation.entrenchment }} · 展开面积 {{ u.formation.dispersion_km2 }} km² · 防护系数 {{ u.formation.protection }}</p>
        <p>炮弹 {{ u.formation.shells }} 发 · 防空弹药 {{ u.formation.aa_rounds }} 发 · 备件 {{ u.formation.spares }} 件 · 施工耗材 {{ u.formation.materials }} 包<span v-if="u.formation.motorized??world.mission?.definition.combined_rules?.motorized"> · 燃油 {{ u.formation.fuel_liters }} 升</span> · 炮兵冷却 {{u.formation.reload_remaining_s!==undefined?u.formation.reload_remaining_s+'秒':u.formation.reload_remaining+'装填周期（旧记录）'}}</p>
        <p>联络状态 {{ u.formation.signal }} / 100 · 情报年龄 {{ formatObservationAge(u.formation.intel_age_min) }} · 置信值约 {{ Number(u.formation.intel_confidence.toFixed(2)) }} / 100</p>
        <p class="muted">恢复联络不刷新情报；地图显示单位不等于部队已实时探测。</p>
        <p v-if="u.supplyLedger" data-testid="unit-supply-route">补给交通线：{{u.supplyLedger.supply_status}} · 粮食工作量 {{u.logistics?.food??'未知'}} · 弹药工作量 {{u.logistics?.ammo??'未知'}}。{{u.supplyLedger.source==='dsh_model_estimate'?'连通与过程为DSH估计，非原生运输回执。':'到货按实际回执；命令执行不等于补给成功。'}}</p>
        <div v-if="u.supplyLedger?.delivery_basis==='declared_gross_estimate'" data-testid="dsh-resource-ledger">
          <p>本轮估计收支：毛到货 {{u.supplyLedger.delivery}} 份 · 粮食消耗 {{u.supplyLedger.food_spent}} · 弹药工作量消耗 {{u.supplyLedger.ammo_spent}}；库存守恒已核对，不代表运输过程或历史耗用率已标定。</p>
          <p v-if="u.supplyLedger.received">分类估计到货：{{resourceFlow(u.supplyLedger.received)}}</p>
          <p v-if="u.supplyLedger.spent">分类估计消耗：{{resourceFlow(u.supplyLedger.spent)}}</p>
        </div>
        <template v-if="nativeReceipt(u)">
          <p v-if="u.formation.last_density_sample && u.formation.last_density_sample.turn===world.mission?.turn" data-testid="native-density-sample">最后一次火力前同批采样：轮内 {{u.formation.last_density_sample.sample_s.toFixed(3)}} 秒 · 本单位可用 {{u.formation.last_density_sample.own_current}} 人 · 同根同位置共享 {{u.formation.last_density_sample.footprint_current}} / 投入 {{u.formation.last_density_sample.footprint_committed}} 人。采样后仍可能发生毁伤，人数不等同期末状态。</p>
          <p v-if="u.formation.last_execution">本轮请求 {{ labels[String(u.formation.last_execution.action)] ?? u.formation.last_execution.action }} · 联络等待预算 {{ u.formation.last_execution.delay_s }} 秒 · {{ executionStatus(u.formation.last_execution) }} · 实际行军 {{ (Number(u.formation.last_execution.distance_milli)/1000).toFixed(1) }} 米 · 防空消耗 {{ u.formation.last_execution.aa_spent }} 发 · 修复 {{ u.formation.last_execution.repaired }} 件 · 到货 {{ Number(u.formation.last_execution.delivery_tons_milli)/1000 }} 吨</p>
          <p v-if="u.formation.last_execution && ['bombard','suppress'].includes(String(u.formation.last_execution.action))">本轮炮弹发射 {{ u.formation.last_execution.shots }} 发；净库存不变时，仍需结合到货与发射记录判断消耗。</p>
          <p v-if="u.formation.last_execution?.received_shells!==undefined" data-testid="classified-receipt">本轮分类到货（原生回执，轮末入账）：炮弹 {{u.formation.last_execution.received_shells}} 发 · 防空弹药 {{u.formation.last_execution.received_aa_rounds}} 发 · 燃油 {{u.formation.last_execution.received_fuel_liters}} 升 · 备件 {{u.formation.last_execution.received_spares}} 件 · 施工耗材 {{u.formation.last_execution.received_materials}} 包。</p>
          <p v-if="u.formation.last_execution?.fire_cycles!==undefined" data-testid="fire-cycles">本轮火力周期 {{u.formation.last_execution.fire_cycles}} 次 · 本轮新发射周期覆盖 {{(Number(u.formation.last_execution.active_fire_s)/60).toFixed(1)}} 分钟<span v-if="Number(u.formation.last_execution.fire_stop_reason)>0"> · 后续停止：{{block[String(u.formation.last_execution.fire_stop_reason)]||'见执行回执'}}</span></p>
          <p v-if="u.formation.last_execution?.small_arms_rounds_estimate!==undefined">本轮小武器射击尝试约 {{Number(u.formation.last_execution.small_arms_rounds_estimate).toLocaleString()}} 发（模型估计；库存仍按弹药工作量约束）</p>
        </template>
        <div class="table-scroll"><table><thead><tr><th>装备分类</th><th>投入</th><th>可用</th><th>待修</th><th>毁损</th></tr></thead><tbody><tr v-for="e in u.equipment" :key="e.category"><td>{{ e.name }}</td><td>{{ e.committed }}</td><td>{{ e.operational }}</td><td>{{ e.damaged }}</td><td>{{ e.destroyed }}</td></tr></tbody></table></div>
      </template>
    </article>
  </section>
</template>

<style scoped>
.combined-panel { color:#c9dbe4; font-size:12px; } .model-title { display:flex; justify-content:space-between; flex-wrap:wrap; gap:8px 20px; color:#e7d19c; } code,.muted { color:#8faeba; overflow-wrap:anywhere; }
p { margin:7px 0; line-height:1.7; } .facility { padding:10px 12px; border-left:2px solid #73c9bd; background:#0c2938; line-height:1.8; margin:10px 0; } .formation { padding:14px 0; border-top:1px solid #284956; }
.table-scroll { overflow:auto; } table { border-collapse:collapse; width:100%; min-width:350px; } td,th { padding:7px 10px; text-align:left; border-bottom:1px solid #25424f; font-variant-numeric:tabular-nums; } summary { cursor:pointer; }
.reference-row{border-top:1px solid #294553;padding:9px 0}a{color:#8cd9d0}small{color:#9fb6c2}
.combat-review{border-left:2px solid #80b9c6;padding:10px 12px;margin:10px 0;background:#102c38}.combat-review.pending{border-color:#e4b45d}.review-issue{color:#ebc781}
</style>
