async page=>{
 await page.context().addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};localStorage.removeItem('gentactix-session');});
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:18981/?qa=korean-first-'+Date.now());
 await page.getByLabel('搜索战役').fill('第一次战役');await page.locator('.battle-option').first().click();
 await page.getByRole('button',{name:/继续配置/}).click();
 await page.getByTestId('execution-backend').selectOption('afsim');await page.locator('#draft-mode').selectOption('historical');
 await page.getByLabel('历史起始阶段').selectOption('liangshuidong_opening');await page.getByTestId('historical-window').waitFor();
 const text=await page.getByTestId('historical-window').innerText();
 if(!text.includes('10:20')||!text.includes('12:00'))throw new Error('The full bound window is not visible');
 await page.getByLabel('计算参数与推演目标需求').fill('两水洞开局参数化QA，1950-10-25 10:20开始，30分钟一轮、3轮到11:50，不能越过12时后续援兵边界。只使用354团与韩军第2团加强第3营两个真实ID，其他部队保留参考不提前部署。人数估计红方2500、蓝方650，并非史实实到量。地域采用已有温井地名参考40.11083/125.89694以北8公里内，现代地名Unsan不能混成云山旧城。两支部队相距约500米，步兵直射范围约1000米。红方徒步motorized=false、燃油0；蓝方汽车搭载motorized=true、燃油1000。坦克、防空0；此段双方可用火炮配额设0，注明模型未分配，不宣称历史没有炮兵，也不以缴获12门当可用数。粮弹工作量80，其余保障合理估计。目标assault，objective为蓝方当前接敌地域，required_turns=2，required_survivors=1，桥梁禁用。不要把历史战果设置为扣兵目标。所有数值、装备配额、库存和坐标逐项说明QA估计，非完整复原或历史效能标定。');
 const pending=page.waitForRequest(r=>r.url().endsWith('/api/historical-scenarios/build')&&r.method()==='POST');
 await page.getByTestId('generate-historical-scenario').click();
 const submitted=(await pending).postDataJSON();await page.getByTestId('historical-build-progress').waitFor();
 await page.screenshot({path:'.cache/qa/korean-first/build-start.png'});
 return {operation_id:submitted.operation_id,battle:submitted.battle,phase_id:submitted.phase_id,window:text,route_mocks:false};
}
