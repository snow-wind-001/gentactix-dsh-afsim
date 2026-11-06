async page=>{
 await page.getByTestId('command-toggle').click();
 const panel=page.getByTestId('command-panel');
 await panel.getByText('控制范围与全局约束',{exact:true}).click();
 await panel.getByLabel('教学导演：允许控制双方').check();
 await panel.getByLabel('全局意图（软偏好）').fill(
  '当前是车桥完整窗口的首轮01:50至02:20，单位和装备参数为明确估计。DSH负责本轮双方全部19个实体的命令，AFSIM独立计算结果。'+
  '调用get_afsim_observation分两页读取全部单位（limit=16，offset=0及next_offset），不要遗漏等待援军。'+
  '红方第7团两路按现有位置向车桥目标区接近；炮兵若目标已在间瞄射程且有炮弹可支援压制，否则先机动；外围阻援、警戒和预备队守各自地域或隐蔽，不一起冲入车桥。'+
  '日伪守备队根据所见可执行范围防御，未接敌不虚构射击；尚未到达not_before的淮安四批援军及曹甸部必须明确hold，不能提前行动。'+
  '必要时用evaluate_action核对移动或炮击，命令使用真实unit_id，每个可用实体均给出rationale。不要输出或修改war_state，不预定历史伤亡或胜方。');
 const saved=page.waitForResponse(r=>r.url().endsWith('/commands')&&r.request().method()==='PUT');
 await panel.getByRole('button',{name:'保存控制设置',exact:true}).click();
 if(!(await saved).ok())throw Error('global intent was not saved');
 await page.getByTestId('command-toggle').click();
 await page.evaluate(()=>{window.__cheqiaoFirstTurn=null});
 page.on('response',async r=>{if(r.url().endsWith('/next')&&r.request().method()==='POST'){
  const d=await r.json();await page.evaluate(x=>{window.__cheqiaoFirstTurn=x},{status:r.status(),turn:d.turn_count,error:d.detail});
 }});
 await page.getByRole('button',{name:'推进一轮',exact:false}).first().click();
 return {started:true,scope:'actual UI global intent; DSH selects actions and AFSIM executes all nineteen entities',route_mocks:false};
}
