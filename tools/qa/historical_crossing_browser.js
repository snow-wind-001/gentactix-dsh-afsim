async page=>{
 const base='http://127.0.0.1:18998',checks=[],errors=[];
 const check=(v,s)=>{if(!v)throw new Error(s);checks.push(s)};page.on('pageerror',e=>errors.push(e.message));
 await page.context().addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};const id=new URL(location.href).searchParams.get('qa-session');if(id)localStorage.setItem('gentactix-session',id);else localStorage.removeItem('gentactix-session');});
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:18981/?qa=crossing-launch');
 await page.getByLabel('搜索战役',{exact:true}).fill('强渡乌江');await page.locator('.battle-option').filter({hasText:'强渡乌江'}).click();await page.getByRole('button',{name:'继续配置'}).click();await page.locator('#draft-mode').selectOption('historical');
 const c=page.getByTestId('historical-setup');await c.getByTestId('historical-goal-guidance').waitFor();
 check(await c.getByLabel('历史起始阶段').inputValue()==='follow_on_jan3','normal historical launch selects sourced post-bridge phase');
 check((await c.getByTestId('historical-window').innerText()).includes('1935-01-03 17:00'),'phase scope and end time visible');
 check((await c.getByTestId('historical-goal-guidance').innerText()).includes('通行'),'crossing task guidance visible');
 await c.getByLabel('历史起始阶段').selectOption('campaign_reference');await c.getByTestId('historical-configuration-gap').waitFor();
 check(await c.getByTestId('generate-historical-scenario').count()===0,'unbound cumulative reference does not create fake combat roster');
 await c.getByLabel('历史起始阶段').selectOption('follow_on_jan3');await c.getByTestId('generate-historical-scenario').waitFor();
 await page.screenshot({path:'.cache/qa/river-crossing/launch-1440.png'});
 for(const engine of ['afsim','narrative']){
  let chosen;
  for(let attempt=0;attempt<600&&!chosen;attempt++){
   const list=await(await page.request.get(base+'/api/sessions')).json();
   for(const row of list.sessions.filter(s=>s.scenario==='乌江后续通行QA-'+engine)){
   const state=await(await page.request.get(base+'/api/sessions/'+row.session_id)).json();
   if(state.branch_origin||state.turn_count!==1)continue;
   if(engine==='afsim'&&state.war_state.afsim.motion_revision!==6)continue;
   if(state.war_state.red_units.reduce((n,u)=>n+(u.crossing?.last_work??0),0)<=0)continue;
   chosen=state;break;
   }
   if(!chosen)await page.waitForTimeout(1000);
  }
  check(!!chosen,engine+' completed real owned test world exists');
  const sid=chosen.session_id;
  for(const width of [1440,900]){
   await page.setViewportSize({width,height:1000});await page.goto('http://127.0.0.1:18981/?qa-session='+sid);
   await page.waitForFunction(()=>document.querySelector('[data-testid="map-workbench"]')||[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='返回当前战局'));
   const resume=page.getByRole('button',{name:'返回当前战局',exact:true});if(await resume.isVisible())await resume.click();await page.getByTestId('map-workbench').waitFor();
   await page.waitForFunction(()=>!document.querySelector('.desktop-root.operation-running'));
   check(await page.locator('.nato-marker').count()===5,engine+'/'+width+' exact five source formations rendered');
   check(await page.locator('.crossing-barrier').count()===1&&await page.locator('.crossing-corridor').count()===1,engine+'/'+width+' finite river and bank corridor drawn');
   await page.getByTestId('analysis-tab-combined').click();const panel=page.getByTestId('combined-arms');await panel.waitFor();
   check(await panel.getByTestId('crossing-task').count()===2,engine+'/'+width+' both actual crossing task accounts shown');
   const receipt=await panel.getByTestId('crossing-capacity').innerText();
   check(receipt.includes('7500')&&receipt.includes(engine==='afsim'?'AFSIM执行回执':'DSH估计回执'),engine+'/'+width+' actual capacity and provenance shown');
   check((await panel.innerText()).includes('不是历史水文或单兵分岸模型'),engine+'/'+width+' scope is explicit');
   check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),engine+'/'+width+' no page overflow');
   await page.screenshot({path:'.cache/qa/river-crossing/'+engine+'-'+width+'.png'});
  }
 }
 check(!errors.length,'no page exceptions');return{passed:true,checks,route_mocks:false};
}
