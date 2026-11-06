async page=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.context().addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};localStorage.removeItem('gentactix-session');});
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:18981/?qa=objective-team');
 await page.getByLabel('搜索战役').fill('夏秋季防御');await page.locator('.battle-option').first().click();
 await page.getByRole('button',{name:/继续配置/}).click();await page.getByTestId('execution-backend').selectOption('afsim');
 await page.locator('#draft-mode').selectOption('historical');await page.locator('#draft-step').selectOption('30分钟');
 await page.getByTestId('generate-historical-scenario').waitFor();
 if(await page.getByLabel('历史起始阶段').inputValue()!=='maryang_oct5')throw new Error('Wrong phase');
 const guidance=await page.getByTestId('historical-goal-guidance').innerText();
 if(!guidance.includes('第一线')||!guidance.includes('次日'))throw new Error('Source task scope absent');
 await page.getByLabel('计算参数与推演目标需求').fill('马良山10月5日第一线的开放推演软件验收。使用basis建议的蓝方assault目标，显式goal.team=blue，required_turns=2、deadline_turn=4、required_survivors=1、radius_km=0.2。不把次日主峰巩固和全程伤亡提前。所有数量/部署为QA估计，不是史实实到：571团1600人徒步，3RAR500人、4辆运输车、2000升燃油，均步兵speed3、直射1000米，其他四类装备0、无航空。采用geographic_scope.center为估计第一线目标点，红方初始在该点、蓝方南约650米；范围3公里、terrain_factor1.5。钟点从窗口起点、30分钟一轮；双方food/ammo80、fatigue10、suppression0、entrenchment15、protection0.15、dispersion1、signal90、intel_confidence80。无桥梁，双方后方各明确保障库存。出口在中心以南2公里。后续将通过开放指挥让红方后撤、蓝方接近，验证目标逻辑差异；不声称这是历史命令。真实读取skill、basis并校验完整配置，再装载AFSIM。');
 page.on('response',async response=>{
  if(response.url().endsWith('/api/historical-scenarios/build')&&response.request().method()==='POST')
   page.__objectiveBuildResponse={status:response.status(),body:await response.json()};
 });
 const pending=page.waitForRequest(r=>r.url().endsWith('/api/historical-scenarios/build')&&r.method()==='POST');
 await page.getByTestId('generate-historical-scenario').click();const request=(await pending).postDataJSON();
 page.__objectiveBuildRequest=request;
 await page.getByTestId('historical-build-progress').waitFor();
 await page.screenshot({path:'.cache/qa/objective-team/generating.png'});
 if(errors.length)throw new Error(errors.join('; '));
 return {passed:true,operation_id:request.operation_id,phase:request.phase_id,route_mocks:false};
}
