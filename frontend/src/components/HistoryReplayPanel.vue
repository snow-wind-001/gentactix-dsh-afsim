<script setup lang="ts">
import type { HistoryReplay } from '../types';
defineProps<{ data: HistoryReplay }>();
const scopeLabels:Record<string,string>={whole:'全建制',elements:'部分部队',reference:'仅关联参考'};
</script>
<template>
  <section class="history-replay" data-testid="history-replay" aria-label="严格史料重现">
    <header><strong>史料重现 · {{ data.cursor + 1 }} / {{ data.total }}</strong><span>{{ data.status === 'completed' ? '已到最后事件' : '按史料事件推进' }}</span></header>
    <h3>{{ data.event.date_label }}</h3><p>{{ data.event.event }}</p>
    <p>时间精度：{{ data.event.precision }} · 证据：{{ data.event.evidence_status || '史料卡摘编' }}</p>
    <p v-if="data.event.variant_group">存在并列来源说法，本帧不替代或叠加其他版本。</p>
    <p>{{ data.scope }} {{ data.evidence }}</p>
    <p v-if="data.ordering" data-testid="history-order-scope" class="muted">{{data.ordering.scope}}</p>
    <section v-if="data.source_operation" class="source-operation" data-testid="history-operation-binding">
      <strong>本事件部队与地域关联</strong>
      <p>{{data.source_operation.description}}</p>
      <p>具名单位：{{data.source_operation.units.map(u=>u.name).join('、')}}</p>
      <ul v-if="data.source_operation.unit_scopes" data-testid="history-unit-scopes" aria-label="本事件单位投入范围">
        <li v-for="(scope,identity) in data.source_operation.unit_scopes" :key="identity">
          <strong>{{data.source_operation.units.find(u=>u.id===identity)?.name??identity}} · {{scopeLabels[scope.extent]}}</strong>
          <p>{{scope.scope}}</p>
          <small v-for="ev in scope.evidence" :key="ev.source_id+ev.locator">出处定位：{{ev.locator}}</small>
        </li>
      </ul>
      <p v-else class="muted">本事件未单列各单位投入范围；关联名称不表示全建制到场或行动。</p>
      <p v-for="place in data.source_operation.places" :key="place.name">{{place.name}} · {{place.position?'地名/区域参考，非精确阵位':'坐标待核，未绘成部队位置'}}</p>
      <p v-for="ev in data.source_operation.evidence" :key="ev.source_id+ev.locator">出处定位：{{ev.locator}}</p>
      <p class="muted">{{data.source_operation.limitations}}</p>
    </section>
    <ul><li v-for="s in data.event.sources" :key="s.id || s.title"><a v-if="s.url" :href="s.url" target="_blank" rel="noopener noreferrer">{{ s.title }}</a><span v-else>{{ s.title }}</span><small v-if="s.publisher"> · {{ s.publisher }}</small></li></ul>
    <details v-if="data.forces.length"><summary>史料提及部队（不表示当前部署）</summary><p v-for="(f,i) in data.forces" :key="i">{{ f.side }} · {{ f.unit }}：{{ f.description }}</p></details>
    <details v-if="data.figures.length"><summary>统计口径（不扣为本帧损失）</summary><p v-for="(f,i) in data.figures" :key="i">{{ f.side }} · {{ f.metric }}：{{ f.value ?? '未知' }}{{ f.qualifier }}；{{ f.scope }}。{{ f.note }}</p></details>
    <p class="muted">需要改变决策时，请从想定管理创建开放推演。事件回放缺少完整部署，不能直接冒充可计算反事实。</p>
  </section>
</template>
<style scoped>
.history-replay { padding: 18px; color: #c9d7dc; font-size: 13px; line-height: 1.7; }
header { display: flex; justify-content: space-between; color: #e5d09e; gap: 12px; }
h3 { color: #e5edf0; } a { color: #87d5ce; } details { margin-top: 12px; } summary { cursor: pointer; }
.source-operation{margin-block:14px;padding:12px;border-left:2px solid #87b9b8;background:#102a37}.source-operation strong{color:#dce7e9}
</style>
