async page=>{
 const api='http://127.0.0.1:18998';
 await page.context().addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};localStorage.removeItem('gentactix-session');});
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:18981/?qa=selected-step');
 await page.getByLabel('搜索战役').fill('台儿庄战役');await page.locator('.battle-option').first().click();
 await page.getByRole('button',{name:/继续配置/}).click();
 await page.getByTestId('execution-backend').selectOption('afsim');
 await page.locator('#draft-mode').selectOption('historical');
 await page.getByTestId('generate-historical-scenario').waitFor();
 await page.locator('#draft-step').selectOption('15分钟');
 if(!(await page.getByTestId('historical-selected-step').innerText()).includes('15分钟'))throw new Error('Selected step not shown');
 await page.getByLabel('计算参数与推演目标需求').fill('台儿庄3月24—28日前期的具名单位局部QA。只用该阶段真实ID：红31师本地投入6000、蓝濑谷支队本地投入3000。人数装备部署和效能均明确为QA估计，非历史实到。步兵，直射1000米，速度3km/h，徒步。装备armor/artillery/air_defense/engineer/transport均0，shells/aa_rounds/fuel等无配额设0，不表示史实没有。红在台儿庄参考点北约300米、蓝再向北300米，不是精确历史街巷。1938-03-24 08:00开始，16轮；回合跨度严格遵守启动页15分钟，截止12:00。地形因子1.5，范围8公里，粮弹100，双方support.stock和inventory均0用于耗尽测试。goal=delay：16轮截止红方至少1可用单位且蓝方未进入红后方约3公里退出点600米内。required_turns=1。禁用桥梁和航空。formation展开3km2防护0.15工事10，疲劳10压制0通信100情报100。其他未知数值合理估计并说明。历史死伤近3000只作统计窗口不同的量级参考，不强制扣除。真实调用skill、基础、校验并装载AFSIM。');
 const waiting=page.waitForRequest(r=>r.url()===api+'/api/historical-scenarios/build'&&r.method()==='POST');
 await page.getByTestId('generate-historical-scenario').click();
 const request=(await waiting).postDataJSON();
 if(request.time_step!=='15分钟')throw new Error('Request lost selected timestep');
 await page.getByTestId('historical-build-progress').waitFor();
 await page.screenshot({path:'.cache/qa/selected-step/building.png'});
 return {time_step:request.time_step,operation_id:request.operation_id,phase_id:request.phase_id,route_mocks:false};
}
