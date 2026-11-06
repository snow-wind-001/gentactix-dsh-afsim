async page=>{
 const api='http://127.0.0.1:18992',ui='http://127.0.0.1:18981/',checks=[];
 await page.context().addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:18992'};});
 const response=await page.request.get(api+'/api/sessions');if(!response.ok())throw new Error(await response.text());
 let selected;
 for(const saved of (await response.json()).sessions){
  const r=await page.request.get(api+'/api/sessions/'+saved.session_id);if(!r.ok())continue;
  const s=await r.json();if(s.war_state?.mission?.id.startsWith('HO-')&&s.war_state.engagements.length===2){selected=s;break;}
 }
 if(!selected)throw new Error('Run actual named-unit combat first');
 const errors=[],error=e=>errors.push(e.message);page.on('pageerror',error);
 function check(ok,label){if(!ok)throw new Error(label);checks.push(label);}
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});await page.goto(ui);
  await page.evaluate(id=>localStorage.setItem('gentactix-session',id),selected.session_id);await page.reload();
  await page.getByRole('button',{name:'返回当前战局',exact:true}).click();await page.getByTestId('map-workbench').waitFor();
  await page.locator('.nato-marker').first().waitFor();
  check(await page.locator('.nato-marker').count()===3,`${width}: real native positions render three military symbols`);
  await page.getByRole('button',{name:'红方 第31师',exact:true}).click();
  await page.getByTestId('command-panel').waitFor();
  check(await page.getByTestId('unit-action').isEnabled(),`${width}: named unit command control available`);
  const actions=await page.getByTestId('unit-action').locator('option').allTextContents();
  check(actions.includes('攻击')&&actions.includes('移动'),`${width}: native motion and fire actions available`);
  check(!actions.includes('架桥/修桥'),`${width}: nonexistent bridge is not offered as an action`);
  await page.locator('#analysis-tab-combined').click();await page.getByTestId('combined-arms').waitFor();
  check(await page.getByTestId('combined-unit').count()===3,`${width}: personnel, equipment and support per actual actor`);
  check(await page.getByTestId('combined-bridge').count()===0,`${width}: calculation hub is not displayed as historical bridge`);
  check((await page.getByTestId('combined-arms').innerText()).includes('参数化'),`${width}: calculation assumptions visibly labeled`);
  await page.screenshot({path:`.cache/qa/historical-operations/workbench-${width}.png`});
 }
 check(errors.length===0,'No page errors');page.removeListener('pageerror',error);
 return {passed:true,session_id:selected.session_id,checks,scope:'Named-unit parameterized QA; not complete historical reconstruction',user_sessions_modified:false};
}
