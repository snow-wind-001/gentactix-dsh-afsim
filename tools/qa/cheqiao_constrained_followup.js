async page=>{
 const panel=page.getByTestId('command-panel');
 if(!await panel.isVisible())await page.getByTestId('command-toggle').click();
 const scope=panel.locator('details').filter({has:page.getByText('控制范围与全局约束',{exact:true})});
 if(await scope.getAttribute('open')===null)await scope.locator('summary').click();
 await panel.getByLabel('全局意图（软偏好）').fill(
  '车桥1.2.0历史条件下的开放推演基线。以后每轮以get_afsim_observation返回的当前时间、位置、装备、弹药和入场状态为准，不重复首轮时间。'+
  'DSH控制双方全部计算实体，AFSIM执行运动、交火和补给。使用分页读完态势并按需evaluate_action校验；每个实体都有明确命令与公开理由，不输出war_state或预制伤亡。'+
  '第7团北路与西南路按各自攻击方向接近镇内伪军守备，已接敌可攻击/压制、未接敌继续有效接近，不反复停在射程外；若补给或损失限制行动则说明实际约束。'+
  '来源记炮兵09时抵近支援，09时之前以侦察和准备为主；之后依据目标、射程、炮弹与冷却决定支援。外围阻援、警戒及预备队履行各自任务，不全军冲向镇中心。'+
  '蓝方守备自主根据实际威胁防御、射击、补给或必要撤离，不因红方有人工意图就漏掉蓝方决策。后续援军解锁前待命；解锁后依据入场位置和态势尝试突破阻援或协同，不再从淮安城区计算一次行军。'+
  '历史过程用于策略参考，开放推演允许不同结果；不要强制历史胜负、伤亡或投降。');
 const save=page.waitForResponse(r=>r.url().endsWith('/commands')&&r.request().method()==='PUT');
 await panel.getByRole('button',{name:'保存控制设置',exact:true}).click();
 if(!(await save).ok())throw Error('Global policy not saved');
 await panel.getByRole('button',{name:'收起指挥面板',exact:true}).click();
 const turns=[];
 for(let index=0;index<3;index++){
  const response=page.waitForResponse(r=>r.url().endsWith('/next')&&r.request().method()==='POST',{timeout:1200000});
  await page.getByRole('button',{name:'推进一轮',exact:false}).first().click();
  const raw=await response,d=await raw.json();
  if(!raw.ok())return {passed:false,turns,error:d.detail,status:raw.status(),mocks:false};
  const w=d.war_state;
  turns.push({turn:d.turn_count,time:w.current_time,native:w.afsim?.returncode,
   units:w.red_units.length+w.blue_units.length,
   red_losses:w.red_units.reduce((n,u)=>n+u.personnel.casualties,0),
   blue_losses:w.blue_units.reduce((n,u)=>n+u.personnel.casualties,0),
   engagements:w.engagements.length,dsh_ms:d.engine_meta?.elapsed_ms});
  await page.waitForFunction(()=>!document.querySelector('.desktop-root.operation-running'));
 }
 await page.screenshot({path:'.cache/qa/cheqiao-complete/constrained/turn4-1440.png'});
 return {passed:true,turns,mocks:false};
}
