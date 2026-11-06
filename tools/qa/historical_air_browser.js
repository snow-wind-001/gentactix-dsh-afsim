async page=>{
 const checks=[],errors=[],check=(v,s)=>{if(!v)throw new Error(s);checks.push(s)};
 page.on('pageerror',e=>errors.push(e.message));
 await page.context().addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};localStorage.removeItem('gentactix-session')});
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:18981/?qa=historical-air');
 await page.getByLabel('搜索战役',{exact:true}).fill('湘西');await page.locator('.battle-option').filter({hasText:'湘西会战'}).click();
 await page.getByRole('button',{name:'继续配置'}).click();await page.locator('#draft-mode').selectOption('historical');await page.getByTestId('execution-backend').selectOption('afsim');
 const composer=page.getByTestId('historical-setup');await composer.getByTestId('historical-goal-guidance').waitFor();
 check(await composer.getByLabel('历史起始阶段').inputValue()==='dongkou_late_april','normal launch selects sourced local phase');
 check((await composer.getByTestId('historical-basis').locator('summary').innerText()).includes('2个'),'aviation is not an invented ground formation');
 check((await composer.getByTestId('historical-window').innerText()).includes('1945-04-25 18:00'),'phase model window and source limits visible');
 await page.screenshot({path:'.cache/qa/historical-air/launch-1440.png'});
 const listing=await(await page.request.get('http://127.0.0.1:18998/api/sessions')).json();
 for(const engine of ['afsim','narrative']){
  let row;
  for(const candidate of listing.sessions.filter(s=>s.scenario==='湘西航空资源QA-'+engine)){
   const snapshot=await(await page.request.get('http://127.0.0.1:18998/api/sessions/'+candidate.session_id)).json();
   if(!snapshot.branch_origin){row=candidate;break;}
  }
  check(!!row,engine+' actual original owned session exists, excluding comparison branches');
  const progress=await(await page.request.get('http://127.0.0.1:18998/api/sessions/'+row.session_id+'/progress')).json();check(!progress.active,engine+' result is committed and idle');
  const snapshot=await(await page.request.get('http://127.0.0.1:18998/api/sessions/'+row.session_id)).json();
  for(const width of [1440,900]){
   await page.context().addInitScript(sid=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};localStorage.setItem('gentactix-session',sid)},row.session_id);
   await page.setViewportSize({width,height:1000});await page.goto('http://127.0.0.1:18981/?qa=air-results');
   await page.getByRole('button',{name:'返回当前战局',exact:true}).click();await page.getByTestId('map-workbench').waitFor();
   await page.waitForFunction(()=>!document.querySelector('.desktop-root.operation-running'),{},{timeout:15000});
   check(await page.locator('.nato-marker').count()===2,engine+'/'+width+' exact two source ground actors on map');
   await page.getByTestId('analysis-tab-air').click();const panel=page.getByTestId('air-operations');await panel.waitFor();
   const text=await panel.innerText();check(text.includes('第五大队')&&text.includes('逐部队资源账'),engine+'/'+width+' named pool account visible');
   check(text.includes('航空弹药 6')&&text.includes('航空燃油 12'),engine+'/'+width+' actual independent stock visible');
   check(text.includes(engine==='afsim'?'AFSIM原生任务回传':'DSH过程估计'),engine+'/'+width+' actual execution source distinguished');
   check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),engine+'/'+width+' no page overflow');
   await page.screenshot({path:'.cache/qa/historical-air/'+engine+'-'+width+'.png'});
   await page.getByTestId('command-toggle').click();const command=page.getByTestId('command-panel');
   const selector=command.locator('select').first();const red= snapshot.war_state.red_units[0].name;
   const options=await selector.locator('option').evaluateAll(o=>o.map(e=>({value:e.value,text:e.textContent})));
   const unit=options.find(o=>o.text.includes(red));check(!!unit,engine+'/'+width+' historical unit selectable');await selector.selectOption(unit.value);
   await command.getByTestId('unit-action').selectOption('air_support');await command.getByLabel('航空资源池',{exact:true}).selectOption('ww2.cacw.group5');
   await command.getByLabel('敌方目标',{exact:true}).selectOption({label:snapshot.war_state.blue_units[0].name});
   const saved=page.waitForResponse(r=>r.request().method()==='PUT'&&r.url().endsWith('/commands')&&r.status()===200);
   await command.getByTestId('enqueue-order').click();await saved;
   const queue=await(await page.request.get('http://127.0.0.1:18998/api/sessions/'+row.session_id+'/commands')).json();
   check(queue.orders.some(o=>o.air_pool==='ww2.cacw.group5'&&o.action==='air_support'),engine+'/'+width+' pool retained through real visual queue API');
   // No execution; clear only this owned QA queue so later checks remain readonly.
   await page.request.put('http://127.0.0.1:18998/api/sessions/'+row.session_id+'/commands',{data:{expected_turn:queue.turn,revision:queue.revision,world_version:queue.world_version,control_team:'red',director:false,no_fire:false,orders:[],unit_agents:[]}});
  }
 }
 check(!errors.length,'no browser exceptions');return {passed:true,checks,route_mocks:false};
}
