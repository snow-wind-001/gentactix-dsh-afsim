async page => {
  const base='http://127.0.0.1:8700';
  const {id}=await page.evaluate(()=>window.combinedDemo);
  if(!id)throw new Error('run setup first');
  const before=await(await page.request.get(`${base}/api/sessions/${id}`)).json();
  if(before.war_state.mission.status==='completed')return{completed:true,turn:before.turn_count,winner:before.war_state.mission.winner};
  const t=before.turn_count;
  const instructions=[
    '团级综合教学验收，双方均由DSH决策。红方争取控制桥东目标；蓝方阻止其达成。首轮红方步兵向教学桥梁西侧约200米靠近，为后续施工准备；红方机动团先维修现有待修运输装备；红方支援团可压制敌方目标。蓝方按防御目标自主选择。先用evaluate_action核验拟用命令；不得在700米外架桥，不得虚构战果。',
    '根据最新实际位置与原生回执继续。红方以工兵构桥、炮兵掩护、航空支援配合夺取目标；本轮可由一个红方单位请求一次航空支援，其余单位不得重复申请。蓝方可侦察、构筑、防空与火力反击。先核验所有候选动作；资源和冷却优先。',
    '继续各自目标。优先完成已开始的桥梁施工；可用炮兵可以压制/炮击，冷却单位可侦察或补给；蓝方根据最新态势防御。不要把教学坐标或数量写成史实。',
    '桥梁开放后，红方以可用单位跨河控制目标，注意共享通行容量；桥未开放则先解决施工。蓝方可阻止红方控制目标。使用实际库存和最近位置核验命令。',
  ];
  const instruction=instructions[t]??'继续双方战役目标，结合疲劳、压制、情报年龄、炮兵冷却、油弹库存、桥梁容量和目标占领状态决策；必要时休整、侦察、修复、补给。可用空中支援可由一个红方单位请求，不要重复申请。先用evaluate_action核验，禁止虚构状态或绕过资源约束。';
  await page.getByLabel('本轮决策意图').fill(instruction);
  const done=page.waitForResponse(r=>r.url().endsWith('/next'),{timeout:900000});
  await page.getByRole('button',{name:'⏩ 下一轮推演',exact:true}).click();
  const response=await done,snapshot=await response.json();
  if(!response.ok())throw new Error(JSON.stringify(snapshot));
  if(snapshot.turn_count!==t+1)throw new Error('turn did not advance');
  const w=snapshot.war_state;
  if(w.simulation_clock.elapsed_seconds!==snapshot.turn_count*1800)throw new Error('clock mismatch');
  const all=[...w.red_units,...w.blue_units];
  for(const u of all){const p=u.personnel;if(p.committed!==p.current+p.casualties+p.noncombat_losses)throw new Error('personnel not conserved');
    for(const e of u.equipment)if(e.committed!==e.operational+e.damaged+e.destroyed)throw new Error('equipment not conserved');}
  const view=await(await page.request.get(`${base}/api/sessions/${id}/unit-decisions`)).json();
  const summary={turn:snapshot.turn_count,clock:w.current_time,status:w.mission.status,winner:w.mission.winner,
    bridge:w.combined_arms.bridge.progress,crossings:w.combined_arms.bridge.used,
    casualties:all.map(u=>({unit:u.name,current:u.personnel.current,casualties:u.personnel.casualties,
      action:u.formation.last_execution.action,suppression:u.formation.suppression,
      shots:u.formation.last_execution.shots,aa_spent:u.formation.last_execution.aa_spent,blocked:u.formation.last_execution.blocked})),
    air_tasks:w.air_operations?.missions.length??0,model_skipped:snapshot.afsim.model_skipped,
    native_process:snapshot.afsim.process_id,decisions_total:view.total,engine_ms:snapshot.engine_meta?.elapsed_ms};
  await page.evaluate(summary=>window.combinedDemo.turns.push(summary),summary);
  await page.getByRole('button',{name:'兵种与保障',exact:true}).click();
  await page.getByTestId('combined-arms').waitFor();
  return {passed:true,session_id:id,...summary};
}
