async page => {
 const base='http://127.0.0.1:18998',checks=[],operations=[],errors=[];
 const check=(ok,label)=>{if(!ok)throw Error(label);checks.push(label)};
 await page.context().addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};localStorage.removeItem('gentactix-session')});
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/api/historical-scenarios/build'))operations.push(r.postDataJSON().operation_id)});
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:18981/?qa=catalog-builder-v1');
 await page.getByLabel('搜索战役').fill('衡阳保卫战');await page.locator('.battle-option').first().click();
 await page.getByRole('button',{name:/继续配置/}).click();await page.locator('#draft-mode').selectOption('historical');
 await page.getByTestId('execution-backend').selectOption('afsim');await page.locator('#draft-step').selectOption('15分钟');
 await page.getByTestId('historical-goal-guidance').waitFor();
 await page.getByLabel('计算参数与推演目标需求').fill(
 '显式QA配置，非史实实力表：1944年6月28日06:00起，15分钟/轮，8轮即2小时，局部迟滞目标归红方。'
 +'保留本阶段两个全部真实ID及原始unknown事实。红第30团人数1600，蓝张家山攻击部队2400；均为QA估计，不写成历史实到。'
 +'地域中心26.88946,112.61888，半径5公里；红位于26.88846,112.61888，蓝26.89146,112.61888，相距约334米，射程800米。'
 +'双方均徒步步兵，无装甲、炮兵、防空、航空或工兵；运输单元各8。粮弹覆盖80，油料1000升，备件20，材料0，炮弹0，防空弹0，疲劳10，压制0，工事10，展开3平方公里，防护0.15，信号90。'
 +'双方后勤点在中心南北约2公里，各库存480和分类库存，全部明确为QA。关闭桥梁与航空。目标出口在26.85,112.61888，所选窗口不能超14:00。'
 +'逐字段给出合理工作尺度及估计说明，真实身份只读。不要按历史结果填写必达伤亡，也不要发射程外炮击或创建教学代表编组。');
 const response=page.waitForResponse(r=>r.url().endsWith('/api/historical-scenarios/build')&&r.request().method()==='POST',{timeout:900000});
 await page.getByTestId('generate-historical-scenario').click();
 const r=await response;check(r.ok(),'normal UI actual DSH/native build succeeded: '+r.status());const draft=await r.json();
 check(draft.construction.source==='dsh_native_skill','configuration genuinely uses native DSH skill');
 check(draft.initial.definition.id==='AJ13-hengyang','source profile retained');
 check(Object.keys(draft.parameters.actors).length===2,'exactly two nonoverlapping sourced local actors');
 check(draft.parameters.clock.time_step==='15分钟','selected quarter-hour preserved');
 check(draft.initial.definition.units.every(u=>Object.values(u.facts).every(f=>f.value===null)),'model estimates do not become historical facts');
 await page.getByTestId('launch-start').click();await page.getByTestId('map-workbench').waitFor({timeout:180000});
 await page.waitForFunction(()=>!document.querySelector('.desktop-root.operation-running'),{timeout:180000});
 const sid=await page.evaluate(()=>localStorage.getItem('gentactix-session'));
 const state=await(await page.request.get(base+'/api/sessions/'+sid)).json();
 check(state.turn_count===0&&state.war_state.afsim.entity_count===2,'normal launch actually imports both native entities');
 check(await page.locator('.nato-marker').count()===2,'map uses two historical actors without duplicate headquarters');
 await page.locator('#analysis-tab-roster').click();const roster=page.getByTestId('historical-roster');await roster.waitFor();
 check((await roster.innerText()).includes('本局固定档案'),'roster is version-pinned to this created battle');
 check((await roster.innerText()).includes('未知'),'source unknown counts remain visibly unknown');
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),width+' workbench has no page overflow');
  await page.screenshot({path:'.cache/qa/catalog-expansion/builder-'+width+'.png'});
 }
 check(!errors.length,'no application page exceptions');
 return {passed:true,checks,operations,session_id:sid,draft_id:draft.id,route_mocks:false,scope:'real skill construction and native import; numbers are explicit QA assumptions'};
}
