async page => {
 const checks=[],errors=[],requestErrors=[],cancelledTiles=[],check=(v,s)=>{if(!v)throw Error(s);checks.push(s)};
 page.on('pageerror',e=>errors.push(e.message));
 page.on('requestfailed',r=>{
  const failure={url:r.url(),error:r.failure()?.errorText};
  if(failure.error==='net::ERR_ABORTED'&&failure.url.startsWith('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/'))cancelledTiles.push(failure);
  else requestErrors.push(failure);
 });
 await page.context().addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};const id=new URL(location.href).searchParams.get('qa-session');if(id)localStorage.setItem('gentactix-session',id)});
 const cases=[['native','c8fba5cfae70'],['estimated','b9e368f0887c'],['legacy','6da184510a7a'],['waiting','b900452d71fc']];
 for(const [kind,sid] of cases){
  const response=await page.request.get('http://127.0.0.1:18998/api/sessions/'+sid),session=await response.json(),world=session.war_state;
  check(response.ok()&&session.turn_count>0,kind+' committed real session exists');
  const estimated=world.dsh_execution?.fire_ledger;
  for(const width of [1440,900]){
   const label=kind+'/'+width;
   await page.setViewportSize({width,height:1000});await page.goto('http://127.0.0.1:18981/?qa=fire-process&qa-session='+sid);
   await page.getByRole('button',{name:'返回当前战局',exact:true}).click();await page.getByTestId('map-workbench').waitFor();
   check(await page.locator('.nato-marker').count()===2,label+' both real units on map');
   for(let i=0;i<3;i++)await page.locator('.leaflet-control-zoom-in').click();
   await page.waitForFunction(()=>{const tiles=[...document.querySelectorAll('img.leaflet-tile')];return tiles.length>0&&tiles.every(i=>i.complete&&i.naturalWidth>0)},null,{timeout:60000});
   check(true,label+' visible map tiles loaded');
   await page.getByTestId('analysis-tab-combined').click();const panel=page.getByTestId('combined-arms');await panel.waitFor();
   const receipts=panel.getByTestId('model-fire-receipt'),missing=panel.getByTestId('model-fire-receipt-missing');
   check(await panel.getByTestId('combined-unit').count()===2,label+' both accounting cards');
   if(kind==='estimated'||kind==='waiting'){
    check(await receipts.count()===2&&await missing.count()===0,label+' current model estimates visible');
    for(let i=0;i<2;i++){
     const text=await receipts.nth(i).innerText(),r=estimated.units[i];
     check(text.includes('非原生遥测')&&text.includes('联络等待 '+r.delay_s+' 秒')&&text.includes('发射 '+r.fire_cycles+' 周期'),label+' actual estimated source and cycles '+i);
     if(kind==='waiting')check(text.includes('未发生／未发生')&&text.includes('本轮联络尚未完成'),label+' zero-fire waiting does not invent shots '+i);
    }
    check(await panel.getByTestId('fire-cycles').count()===0,label+' no stale native firing receipt');
    await receipts.first().scrollIntoViewIfNeeded();
   }else if(kind==='legacy'){
    check(await receipts.count()===0&&await missing.count()===2,label+' legacy process remains missing');
    check((await missing.first().innerText()).includes('不能补认持续交火时长'),label+' missing duration explained');
    await missing.first().scrollIntoViewIfNeeded();
   }else{
    check(await receipts.count()===0&&await missing.count()===0,label+' native result not relabeled as DSH');
    check(await panel.getByTestId('fire-cycles').count()===2,label+' original native receipts retained');
    await panel.getByTestId('fire-cycles').first().scrollIntoViewIfNeeded();
   }
   check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),label+' no horizontal page overflow');
   await page.screenshot({path:'.cache/qa/fire-process/'+kind+'-'+width+'.png'});
   await page.getByTestId('focus-map').click();check(!await page.getByTestId('analysis-panel').isVisible(),label+' analysis drawer collapses');
  }
 }
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});await page.goto('http://127.0.0.1:18981/?qa=fire-review&qa-session=b9e368f0887c');
  await page.getByRole('button',{name:'返回当前战局',exact:true}).click();await page.getByTestId('map-workbench').waitFor();
  await page.getByTestId('analysis-tab-chat').click();
  const answer=page.locator('.msg.assistant .message-content').last();await answer.waitFor();
  const text=await answer.innerText();
  check(text.includes('已实际调用')&&text.includes('不属于 AFSIM 原生遥测'), 'review/'+width+' actual tool-based response has source label');
  check(await answer.locator('table').count()>0&&text.includes('757')&&text.includes('38'),'review/'+width+' real numerical response table renders');
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'review/'+width+' table stays within page');
  await answer.locator('table').first().scrollIntoViewIfNeeded();
  await page.screenshot({path:'.cache/qa/fire-process/review-'+width+'.png'});
 }
 check(!errors.length,'no application page exceptions');
 check(!requestErrors.length,'no unexpected request failures: '+JSON.stringify(requestErrors));
 return{passed:true,checks,route_mocks:false,cancelled_tiles_during_zoom_or_navigation:cancelledTiles.length,scope:'current actual native and DSH results, legacy missing evidence, and zero-fire waiting'};
}
