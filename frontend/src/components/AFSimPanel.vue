<script setup lang="ts">
import type { AFSimEvidence } from '../types';
defineProps<{ evidence: AFSimEvidence | null | undefined; modeled?: boolean;hostGoals?:boolean }>();
</script>

<template>
  <section class="afsim-panel" aria-label="AFSIM执行状态" data-testid="afsim-status">
    <header><strong>DSH 控制 · AFSIM 执行</strong><span role="status">{{ !evidence ? '等待执行证据' : evidence.source !== 'dsh_native_mcp_controller' ? '测试数据' : evidence.status === 'completed' && evidence.returncode === 0 ? evidence.phase === 'historical_replay' ? '来源帧校验完成' : '实际执行完成' : '尚未完成' }}</span></header>
    <template v-if="evidence?.phase === 'historical_replay'">
      <p>严格来源事件帧已由AFSIM实际执行并核对回执；未调用模型生成状态，未运行开放战损规则。</p>
      <p>地名参考点 {{ evidence.entity_count }} 个；执行用时 {{ ((evidence.wall_ms ?? 0) / 1000).toFixed(2) }}s。后台1秒仅为帧调度时间，历史时间以史料事件为准。</p>
      <p v-if="evidence.historical_roster_count!==undefined" data-testid="historical-execution-scope">历史编制参考 {{evidence.historical_roster_count}} 条；作战实体 {{evidence.combat_entity_count??'未知'}} 个。{{evidence.battlefield_initialized===false?'尚未建立可计算交战的战场初态。':''}}</p>
      <details><summary>运行证据</summary><p>{{ evidence.scope }}</p><code>{{ evidence.process_id }}</code></details>
    </template>
    <template v-else-if="evidence">
      <p v-if="!modeled" class="motion-only" role="note" data-testid="motion-only-warning"><b>仅运动验证：未启用交战结算。</b> 即使双方进入射程，本路径也不会计算开火、伤亡或补给消耗；需要可计算交战时须另选已登记规则的初态。</p>
      <div class="afsim-metrics"><span>已回传编组 <b>{{ evidence.entity_count ?? '未知' }}</b></span><span v-if="evidence.air_task_count">航空任务 <b>{{ evidence.air_task_count }}</b></span><span>执行用时 <b>{{ ((evidence.wall_ms ?? 0) / 1000).toFixed(2) }}s</b></span><span v-if="evidence.phase !== 'initial_state_validation'">仿真跨度 <b>{{ evidence.seconds }}s</b></span></div>
      <p v-if="evidence.phase === 'initial_state_validation'">初态载入已核验；战局时钟尚未推进。</p>
      <p v-else>{{ evidence.model_skipped ? '本轮命令已覆盖全部可行动单位，未额外调用全局规划模型；单位Agent的调用见决策记录。' : '模型只读取局部观察并提交命令，本轮提示词 ' + (evidence.planner_prompt_chars ?? '未知') + ' 字符。' }}</p>
      <p>{{ evidence.effects_source?.startsWith('afsim-native-') ? hostGoals?'运动、人员装备和补给库存由AFSIM执行；会战目标由宿主读取物理结果评分。参数未作史实标定。':'运动、人员装备、补给库存与目标由AFSIM后台执行教学模型计算；参数仍未作史实标定。' : evidence.effects_source === 'teaching-rules-1' ? '旧版结果：AFSIM计算运动，程序执行教学规则。' : evidence.phase === 'initial_state_validation' ? '完整单位账保存在应用检查点，供后续按需读取。' : '运动由AFSIM计算；本场景尚未启用武器战损与补给效果模型，已有账本保持连续。' }}</p>
      <p v-if="evidence.excluded?.length">{{ evidence.excluded.length }} 个单位坐标未知，保留于战局账本；未虚构外部位置。</p>
      <details><summary>运行证据与能力范围</summary><p>{{ evidence.scope }}</p><p>版本 {{ evidence.version ?? '未记录' }} · 来源 {{ evidence.transport ?? '未记录' }}</p><code>{{ evidence.process_id }}</code><p v-for="id in evidence.dispatch_ids" :key="id"><code>{{ id }}</code></p></details>
    </template>
  </section>
</template>

<style scoped>
.afsim-panel { padding: 10px 16px; margin: 8px 12px; max-height: 180px; overflow-y: auto; border: 1px solid #294653; background: #0b202d; border-radius: 6px; color: #bdd0d8; font-size: 12px; }
header, .afsim-metrics { display: flex; align-items: center; gap: 12px 24px; flex-wrap: wrap; }
header { justify-content: space-between; color: #e5d09e; } header span { color: #80cfbb; }
.afsim-metrics { margin: 10px 0; } .afsim-metrics b { color: #e3edf0; margin-left: 6px; }
p { margin: 6px 0; line-height: 1.6; } code { overflow-wrap: anywhere; }
summary { cursor: pointer; } details { margin-top: 8px; color: #9fb8c4; }
.motion-only { border-left: 2px solid #d9b86d; padding-left: 9px; color: #e0cc9b; }
</style>
