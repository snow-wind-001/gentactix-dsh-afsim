async page=>{
 await page.context().addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:18997'};localStorage.removeItem('gentactix-session');});
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:18981/?qa=scenario-staging-'+Date.now());
 await page.getByLabel('搜索战役').fill('平型关');await page.locator('.battle-option').first().click();
 await page.getByRole('button',{name:/继续配置/}).click();
 await page.getByTestId('execution-backend').selectOption('afsim');
 await page.locator('#draft-mode').selectOption('historical');
 await page.getByLabel('历史起始阶段').selectOption('qiaogou');await page.getByTestId('historical-window').waitFor();
 await page.getByLabel('计算参数与推演目标需求').fill('乔沟地面窗口，1937-09-25 07:00起点，30分钟回合，12回合到13:00截止。目标delay，required_survivors=1。保留六个真实ID，外围和后续单位不提前到场。所有缺载人数、装备、部署与库存均为显式QA估计，不宣称完整重建或历史效能标定。红方团级约1000—1500人，蓝方车队或辎重队约300—400人。坦克、炮兵、防空均0；步兵直射范围约900—1100米。红方motorized=false、燃油0；蓝方motorized=true，燃油正值。双方粮弹工作量80，按部署方位展开，686保持来源区域约束；乔沟中心39.34/113.98，半径15km，terrain_factor=1.8为QA山地迟滞假设。允许部分单位在一两轮内机动接敌，预备队保持预备；exit置于局部战区西南边缘，不让单位初态已进入exit。非史实数值逐单位说明。');
 const request=page.waitForRequest(r=>r.url().endsWith('/api/historical-scenarios/build')&&r.method()==='POST');
 await page.getByTestId('generate-historical-scenario').click();
 const submitted=(await request).postDataJSON();
 await page.getByTestId('historical-build-progress').waitFor();
 await page.screenshot({path:'.cache/qa/scenario-staging/build-start.png'});
 return {operation_id:submitted.operation_id,battle:submitted.battle,phase_id:submitted.phase_id,execution_backend:submitted.execution_backend,progress:await page.getByTestId('historical-build-progress').innerText(),route_mocks:false};
}
