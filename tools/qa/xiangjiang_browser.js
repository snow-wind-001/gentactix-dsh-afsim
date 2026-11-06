async page=>{
 const checks=[],errors=[],tiles=[],check=(v,s)=>{if(!v)throw new Error(s);checks.push(s)};
 page.on('pageerror',e=>errors.push(e.message));
 await page.context().addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};localStorage.removeItem('gentactix-session')});
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:18981/?qa=xiangjiang-launch');
 await page.getByLabel('搜索战役',{exact:true}).fill('湘江');await page.locator('.battle-option').filter({hasText:'湘江战役'}).click();
 await page.getByRole('button',{name:'继续配置'}).click();await page.locator('#draft-mode').selectOption('historical');await page.getByTestId('execution-backend').selectOption('afsim');
 const composer=page.getByTestId('historical-setup');await composer.getByTestId('historical-goal-guidance').waitFor();
 check(await composer.getByLabel('历史起始阶段').inputValue()==='xinxu_nov28','normal launch selects the supported Xinxu phase and discloses it');
 check((await composer.getByTestId('historical-basis').locator('summary').innerText()).includes('4个'),'Xinxu source actors are four non-overlapping formations');
 check((await composer.getByTestId('historical-window').innerText()).includes('1934-11-28 18:00'),'Xinxu first-day window is visible');
 const changed=page.waitForResponse(r=>r.url().includes('phase_id=guanghuapu_nov30_morning')&&r.status()===200);
 await composer.getByLabel('历史起始阶段').selectOption('guanghuapu_nov30_morning');await changed;
 await page.waitForFunction(()=>document.querySelector('[data-testid="historical-basis"] summary')?.textContent.includes('2个'));
 check((await composer.getByTestId('historical-window').innerText()).includes('1934-11-30 12:00'),'Guanghuapu morning stays separate from afternoon relief');
 await composer.getByLabel('历史起始阶段').selectOption('campaign_reference');await composer.getByTestId('historical-configuration-gap').waitFor();
 check(await composer.getByTestId('generate-historical-scenario').count()===0,'campaign reference cannot generate a false simultaneous deployment');
 check(await page.getByTestId('launch-start').isDisabled(),'unbound campaign reference cannot launch');
 await composer.getByLabel('历史起始阶段').selectOption('guanghuapu_nov30_morning');await composer.getByTestId('generate-historical-scenario').waitFor();
 check(await composer.getByTestId('generate-historical-scenario').isEnabled(),'supported local stage can use the normal DSH skill');
 await page.screenshot({path:'.cache/qa/xiangjiang/launch-1440.png'});
 const listing=await(await page.request.get('http://127.0.0.1:18998/api/sessions')).json();
 for(const [phase,count] of [['xinxu_nov28',4],['guanghuapu_nov30_morning',2]]){
  const row=listing.sessions.find(s=>s.scenario==='湘江具名历史局部QA-'+phase);check(!!row,phase+' actual completed owned session exists');
  for(const width of [1440,900]){
   await page.context().addInitScript(sid=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};localStorage.setItem('gentactix-session',sid)},row.session_id);
   await page.setViewportSize({width,height:1000});await page.goto('http://127.0.0.1:18981/?qa=xiangjiang-results');
   const active=await(await page.request.get('http://127.0.0.1:18998/api/sessions/'+row.session_id+'/progress')).json();
   if(active.active)throw new Error('Wait until actual model analysis ends before result inspection');
   await page.getByRole('button',{name:'返回当前战局',exact:true}).click();await page.getByTestId('map-workbench').waitFor();
   await page.waitForFunction(()=>!document.querySelector('.desktop-root.operation-running'),{},{timeout:15000});
   check(await page.locator('.nato-marker').count()===count,phase+'/'+width+' all actual actors are drawn on the map');
   check(await page.getByRole('button',{name:'推进一轮',exact:true}).isDisabled(),phase+'/'+width+' completed program objective cannot repeat losses');
   const snapshot=await(await page.request.get('http://127.0.0.1:18998/api/sessions/'+row.session_id)).json();
   await page.getByTestId('analysis-tab-combined').click();const panel=page.getByTestId('combined-arms');await panel.waitFor();
   check(await panel.getByTestId('combined-unit').count()===count,phase+'/'+width+' exact native actor count visible');
   for(const team of ['red','blue'])for(const u of snapshot.war_state[team+'_units']){
    const unit=panel.getByTestId('combined-unit').filter({hasText:u.name});const text=await unit.innerText();
    check(text.includes('可用人员 '+u.personnel.current)&&text.includes('战斗减员 '+u.personnel.casualties),phase+'/'+width+'/'+u.historical_unit_id+' real current personnel and losses visible');
   }
   check((await panel.getByTestId('combat-assessment').innerText()).includes('30 分钟'),phase+'/'+width+' final round remains 30 minutes');
   const ref=panel.getByTestId('unit-history-reference');
   check(await ref.count()===(phase.startsWith('guanghuapu')?1:0),phase+'/'+width+' historical loss reference attaches only to the same unit ID');
   if(phase.startsWith('guanghuapu')){check((await ref.innerText()).includes('400')&&(await ref.innerText()).includes('不是阵亡'),width+' 400 means reported casualties, no death quota');await ref.scrollIntoViewIfNeeded()}
   check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),phase+'/'+width+' no page overflow');
   await page.waitForFunction(()=>{const imgs=[...document.querySelectorAll('.leaflet-tile-pane img')];return imgs.length>0&&imgs.every(i=>i.complete)},{},{timeout:10000}).catch(()=>{});
   tiles.push({phase,width,...await page.evaluate(()=>{const imgs=[...document.querySelectorAll('.leaflet-tile-pane img')];return {requested:imgs.length,loaded:imgs.filter(i=>i.complete&&i.naturalWidth>0).length,pending:imgs.filter(i=>!i.complete).length,failed:imgs.filter(i=>i.complete&&!i.naturalWidth).length}})});
   await page.screenshot({path:'.cache/qa/xiangjiang/'+phase+'-'+width+'.png'});
  }
 }
 check(errors.length===0,'no page exceptions across launch and both actual native sessions');return {passed:true,checks,tiles,route_mocks:false};
}
