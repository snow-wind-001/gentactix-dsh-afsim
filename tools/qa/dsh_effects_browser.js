async page=>{
 const checks=[],errors=[],tiles=[],check=(v,s)=>{if(!v)throw new Error(s);checks.push(s);};
 page.on('pageerror',e=>errors.push(e.message));
 const base='http://127.0.0.1:18998/api/sessions/';
 const active=await(await page.request.get(base+'eaeef815d631/progress')).json();
 check(!active.active,'real DSH step and readonly branch have ended');
 for(const [sid,engine] of [['247d1dcbe874','afsim'],['eaeef815d631','narrative']]){
  await page.context().addInitScript(sid=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};localStorage.setItem('gentactix-session',sid)},sid);
  for(const width of [1440,900]){
   await page.setViewportSize({width,height:1000});await page.goto('http://127.0.0.1:18981/?qa=command-effects');
   await page.getByRole('button',{name:'返回当前战局',exact:true}).click();await page.getByTestId('map-workbench').waitFor();
   await page.waitForFunction(()=>!document.querySelector('.desktop-root.operation-running'),{},{timeout:15000});
   const snapshot=await(await page.request.get(base+sid)).json(),world=snapshot.war_state;
   await page.getByTestId('analysis-tab-combined').click();const panel=page.getByTestId('combined-arms');await panel.waitFor();
   for(const team of ['red','blue']){
    const u=world[team+'_units'][0],row=panel.locator('article').filter({hasText:u.name});
    const text=await row.innerText();
    check(text.includes('可用人员 '+u.personnel.current)&&text.includes('战斗减员 '+u.personnel.casualties),engine+'/'+width+'/'+team+' actual personnel and losses are visible');
    if(engine==='afsim')check(text.includes('本轮火力周期 '+u.formation.last_execution.fire_cycles),width+'/'+team+' actual native firing cycles visible');
   }
   check(await panel.getByTestId('fire-cycles').count()===(engine==='afsim'?2:0),engine+'/'+width+' model estimates never masquerade as native firing receipts');
   await page.getByTestId('analysis-tab-combined').click();await page.getByTestId('command-toggle').click();
   const command=page.getByTestId('command-panel');
   for(const team of ['red','blue']){
    const view=await(await page.request.get(base+sid+'/commands')).json(),u=view.units.find(u=>u.team===team);
    await command.getByLabel('单位名单（含无坐标单位）').selectOption(u.id);
    const response=page.waitForResponse(r=>r.url().includes('/unit-decisions?')&&r.status()===200);
    await command.getByRole('button',{name:'本单位决策／执行回执',exact:true}).click();await response;
    const records=command.getByRole('region',{name:'单位决策记录'});await records.waitFor();
    check((await records.innerText()).includes('T+'+world.mission.turn),engine+'/'+width+'/'+team+' latest unit decision/receipt is accessible');
   }
   await command.getByRole('button',{name:'收起指挥面板',exact:true}).click();await page.getByTestId('analysis-tab-combined').click();
   check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),engine+'/'+width+' no page overflow');
   await page.waitForFunction(()=>{const imgs=[...document.querySelectorAll('.leaflet-tile-pane img')];return imgs.length>0&&imgs.every(i=>i.complete)},{},{timeout:10000}).catch(()=>{});
   tiles.push({engine,width,...await page.evaluate(()=>{const imgs=[...document.querySelectorAll('.leaflet-tile-pane img')];return {requested:imgs.length,loaded:imgs.filter(i=>i.complete&&i.naturalWidth>0).length,pending:imgs.filter(i=>!i.complete).length,failed:imgs.filter(i=>i.complete&&!i.naturalWidth).length}})});
   await page.screenshot({path:'.cache/qa/dsh-effects/browser-'+engine+'-'+width+'.png'});
  }
 }
 check(errors.length===0,'no page exceptions during command and effect inspection');return {passed:true,checks,tiles,route_mocks:false};
}
