async page=>{
 const api='http://127.0.0.1:18998',ui='http://127.0.0.1:18981/',sid='5116dde98ec3',legacy='44cf8714ebe2',checks=[],errors=[];
 const check=(ok,label)=>{if(!ok)throw new Error(label);checks.push(label);};
 const error=e=>errors.push(e.message);page.on('pageerror',error);
 await page.context().addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};});
 await page.goto(ui);await page.evaluate(id=>localStorage.setItem('gentactix-session',id),sid);
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});await page.goto(ui+'?qa=weapon-ranges-'+Date.now());
  await page.getByRole('button',{name:'返回当前战局',exact:true}).click();await page.getByTestId('map-workbench').waitFor();
  check(await page.locator('.nato-marker').count()===3,width+' three actual historical-ID QA entities');
  check(await page.locator('.bf-aggregate-min-range').count()===3,width+' three actual artillery minimum-range rings');
  await page.getByTestId('command-toggle').click();await page.getByTestId('command-panel').waitFor();
  const v=await(await page.request.get(api+'/api/sessions/'+sid+'/commands')).json(),u=v.units.find(x=>x.team==='red');
  await page.getByLabel('单位名单（含无坐标单位）').selectOption(u.id);
  await page.getByTestId('unit-action').selectOption('fire');
  check((await page.getByTestId('selected-weapon-range').innerText()).includes('0—800 m'),width+' direct self-defense range');
  await page.getByTestId('unit-action').selectOption('bombard');
  check((await page.getByTestId('selected-weapon-range').innerText()).includes('300—12000 m'),width+' indirect minimum and maximum range');
  check(await page.getByTestId('weapon-warning').count()===0,width+' no legacy warning on corrected inputs');
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),width+' no document overflow');
  await page.screenshot({path:'.cache/qa/weapon-ranges/command-'+width+'.png'});
  await page.getByTestId('command-toggle').click();
  // Dispatch a real DOM hover to Leaflet's generated engagement shape; no API replacement.
  const shapes=page.locator('path.leaflet-interactive');let found=false;
  for(let i=0;i<await shapes.count();i++){
   const shape=shapes.nth(i),dash=(await shape.getAttribute('stroke-dasharray')||'').replace(/[, ]+/g,' ').trim();
   if(dash==='6 4'){await shape.dispatchEvent('mouseover',{clientX:350,clientY:400});found=true;break;}
  }
  check(found,width+' native-fired engagement polygon rendered');
  const text=await page.locator('.leaflet-tooltip').allTextContents();
  check(text.some(x=>x.includes('炮击射程 12000')&&x.includes('14400')&&x.includes('非杀伤半径')),width+' actual tooltip uses indirect range and labeled display radius');
 }
 await page.evaluate(id=>localStorage.setItem('gentactix-session',id),legacy);await page.goto(ui+'?qa=old-range');
 await page.getByRole('button',{name:'返回当前战局',exact:true}).click();await page.getByTestId('map-workbench').waitFor();
 await page.getByTestId('command-toggle').click();
 const v=await(await page.request.get(api+'/api/sessions/'+legacy+'/commands')).json(),gun=v.units.find(x=>x.name==='美第99野战炮兵营C连');
 await page.getByLabel('单位名单（含无坐标单位）').selectOption(gun.id);
 const warning=await page.getByTestId('weapon-warning').innerText();
 check(warning.includes('8000')&&warning.includes('保留旧参数'),'legacy suspicion displayed without silently changing frozen range');
 await page.screenshot({path:'.cache/qa/weapon-ranges/legacy-warning.png'});
 check(!errors.length,'no page exceptions');page.removeListener('pageerror',error);
 return {passed:true,checks,session_id:sid,legacy_session_id:legacy,route_mocks:false};
}
