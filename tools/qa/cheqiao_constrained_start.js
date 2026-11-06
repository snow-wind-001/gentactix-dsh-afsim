async page=>{
 const checks=[];const check=(ok,label)=>{if(!ok)throw Error(label);checks.push(label)};
 await page.goto('http://127.0.0.1:18987/');
 await page.setViewportSize({width:1440,height:1000});
 await page.getByLabel('搜索战役').fill('车桥');
 await page.locator('.battle-option').first().click();
 await page.getByRole('button',{name:/继续配置/}).click();
 await page.locator('#draft-mode').selectOption('historical');
 await page.locator('#draft-executor').selectOption('afsim');
 await page.locator('#draft-step').selectOption('30分钟');
 const c=page.getByTestId('historical-setup');
 await c.getByLabel('史料档案版本').selectOption('1.2.0');
 await c.getByLabel('历史起始阶段').selectOption('core_march5_6');
 await c.getByTestId('historical-basis').waitFor();
 check((await c.getByTestId('historical-basis').innerText()).includes('15个'),'full window exposes fifteen nonoverlapping historical actors');
 check((await c.getByTestId('historical-window').innerText()).includes('1944-03-06 06:20'),'full selected window is visible before generation');
 check((await c.getByTestId('historical-goal-guidance').innerText()).includes('阻援'),'combined operation guidance is visible');
 await c.getByLabel('计算参数与推演目标需求').fill(
  '配置车桥完整核心窗口，1944-03-05 01:50至03-06 06:20，30分钟，共57轮。'+
  '这是以具名历史部队为基础的开放推演，缺载数值、地形和部署明确估计；不是完整史实验收，不能写入固定历史伤亡、预定红方胜利或以同一数字混合6日/7日结局口径。'+
  '必须覆盖全部15个父单位：镇内主攻、西北芦家滩方向打援、南侧崔河方向警戒、北侧策应及后方预备队分别布置，不把所有部队塞进车桥。'+
  '现代地名参考只是战区定位；车桥据点中心使用33.46667,119.4作为粗地名参照，战术部署均另作估计，不据此声称1944年街区或地形已配准。'+
  '使用现有partitions把第7团分为两路互斥突击计算分队；把淮安援军分为4批互斥计算分队，保持父人数装备和绝对库存之和，禁止父单位重复计兵。'+
  '来源记载首批约15:15、第三批17:30，第二批16:00与第四批次日02:30作为明确的时段离散化假设；批次规模可参考240、200、100、120但标为选用口径的估计，不填回原始facts。'+
  '所有红方主攻/阻援/预备队可在开局处于各自地域，但后续援军必须填写not_before与parts覆盖，曹甸方向出援不得提前在镇内，出援时刻缺载单列假设。'+
  '据点目标与西北、南侧两个阻援区域分别设置，在截止回合检查控制与人员保存；开放推演目标不是历史固定胜负。'+
  '永久工事与受降过程明确配置。炮兵配属山炮/迫击炮能力以合理但未标定的库存和射程估计，不能发明航空或装甲单位；步兵徒步，运输和炮兵是否机动逐单位说明。'+
  '后勤点、运输能力和粮弹库存应使补给在空间上可达，但不无限补给。保留归一化粮弹与炮弹绝对库存区别，未知效能不得称已校准。'+
  '新增约束：遵守phase.input_constraints，日军镇内守备取45人为约40余人量级的计算值，不是当日名册；不得扩大到260。淮安4批全部选择battlefield_entry，各parts填写对应cq_huaian_1到cq_huaian_4的reference_id，初始位置在各参考region内，解锁前仅等待，不从淮安城区到时才出发。'+
  '第7团两分队应命名北路/西南路突击计算分队，两者均开局到场，不称先后梯队；围绕车桥现代地名点分别部署在北侧和西南侧近距位置，明确地形仍未配准。沿用来源攻击方位，而非西北/东南。'+
  '每片按工具反馈校验；globals定义的互斥分队人数装备库存必须由后续父单位分片逐项精确求和。最终用工具完整校验，不仅声称通过。');
 await page.evaluate(()=>{window.__cheqiaoFullQA={checks:[],build:null,request:null}});
 page.on('request',async req=>{if(req.url().endsWith('/api/historical-scenarios/build')){
  const p=req.postDataJSON();await page.evaluate(p=>{window.__cheqiaoFullQA.request={version:p.version,phase_id:p.phase_id,operation_id:p.operation_id,time_step:p.time_step}},p);
 }});
 page.on('response',async response=>{if(response.url().endsWith('/api/historical-scenarios/build')){
  const result=await response.json();await page.evaluate(({status,result})=>{window.__cheqiaoFullQA.build={status,id:result.id,error:result.detail,actors:result.parameters?Object.keys(result.parameters.actors).length:null}}, {status:response.status(),result});
 }});
 await c.getByTestId('generate-historical-scenario').click();
 await page.waitForFunction(()=>window.__cheqiaoFullQA.request!==null);
 return {checks,request:await page.evaluate(()=>window.__cheqiaoFullQA.request),route_mocks:false,build_pending:true};
}
