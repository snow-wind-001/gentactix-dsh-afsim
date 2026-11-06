async page=>{
 const tiles=[],checks=[],errors=[],check=(v,s)=>{if(!v)throw new Error(s);checks.push(s);};
 page.on('pageerror',e=>errors.push(e.message));
 for(const [sid,engine,kind] of [['67fcfbc193d8','narrative','new'],['7f23bf817b9a','afsim','native'],['a1823edb93b4','narrative','legacy']]){
  await page.context().addInitScript(sid=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};localStorage.setItem('gentactix-session',sid);},sid);
  for(const width of [1440,900]){
   await page.setViewportSize({width,height:1000});await page.goto('http://127.0.0.1:18981/?qa=dsh-resources');
   await page.getByRole('button',{name:'返回当前战局',exact:true}).click();await page.getByTestId('map-workbench').waitFor();
   if(kind==='new')check(await page.getByRole('button',{name:'推进一轮',exact:true}).isDisabled(),width+' settled six-turn goal disables further advance');
   const current=await(await page.request.get('http://127.0.0.1:18998/api/sessions/'+sid)).json();
   await page.getByTestId('top-status').click();const mission=page.getByTestId('mission-panel');
   await mission.getByText('目标进度、补给账与重放凭据',{exact:true}).click();
   const table=mission.getByTestId('mission-resource-table');await table.focus();
   check(await table.evaluate(e=>e===document.activeElement),kind+'/'+width+' resource table is keyboard focusable');
   check((await table.innerText()).includes('粮食消耗')&&(await table.innerText()).includes('弹药消耗'),kind+'/'+width+' spending and balances are separate columns');
   const source=await mission.getByTestId('mission-resource-source').innerText();
   check(source.includes(kind==='new'?'毛到货':kind==='legacy'?'旧DSH':'每份到货'),kind+'/'+width+' correct source and legacy semantics');
   check(!source.includes(kind==='new'?'净增加量':kind==='native'?'旧DSH':'已核对'),kind+'/'+width+' no unsupported accounting claim');
   await page.getByTestId('top-status').click();await page.getByTestId('analysis-tab-combined').click();
   const panel=page.getByTestId('combined-arms');await panel.waitFor();
   const estimated=panel.getByTestId('dsh-resource-ledger'),native=panel.getByTestId('classified-receipt');
   check(await estimated.count()===(kind==='new'?2:0),kind+'/'+width+' estimated receipt visibility matches the committed schema');
   check(await native.count()===(kind==='native'?2:0),kind+'/'+width+' old native execution data never looks like a model receipt');
   if(kind==='new'){
    const texts=await estimated.allTextContents();
    for(const [i,r] of current.war_state.mission.ledger.entries())check(texts[i].includes('粮食消耗 '+r.food_spent),width+' actual checked spending visible for '+r.unit);
   }
   check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),kind+'/'+width+' no document overflow');
   await page.waitForFunction(()=>{const images=[...document.querySelectorAll('.leaflet-tile-pane img')];return images.length>0&&images.every(i=>i.complete);},{},{timeout:10000}).catch(()=>{});
   tiles.push({kind,width,...await page.evaluate(()=>{const images=[...document.querySelectorAll('.leaflet-tile-pane img')];return {requested:images.length,loaded:images.filter(i=>i.complete&&i.naturalWidth>0).length,pending:images.filter(i=>!i.complete).length,failed:images.filter(i=>i.complete&&!i.naturalWidth).length};})});
   await page.screenshot({path:'.cache/qa/dsh-resources/browser-'+kind+'-'+width+'.png'});
  }
 }
 check(errors.length===0,'no page exceptions across the three stored receipt formats');
 return {passed:true,checks,tiles,route_mocks:false};
}
