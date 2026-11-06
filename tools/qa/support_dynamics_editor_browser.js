async page=>{
 const checks=[],errors=[];const check=(v,s)=>{if(!v)throw Error(s);checks.push(s)};
 page.on('pageerror',e=>errors.push(e.message));await page.setViewportSize({width:900,height:1000});
 await page.goto('http://127.0.0.1:18993/support-editor.html');
 const editor=page.getByTestId('support-dynamics-editor');await editor.locator('summary').click();
 check(await page.evaluate(()=>window.qa.value===undefined),'old configuration stays absent');
 const toggle=editor.getByRole('checkbox');await toggle.check();
 check(await page.evaluate(()=>window.qa.value.version==='time-sustainment-1'),'explicit opt-in emits model');
 await editor.getByLabel('待命耗粮（工作量/小时）',{exact:true}).fill('3.5');
 await editor.getByLabel('非战斗失能起算时长（小时）',{exact:true}).fill('72');
 check(await page.evaluate(()=>window.qa.value.food_work_per_hour===3.5&&window.qa.value.incapacity_after_hours===72),'edits emit independent numeric parameters');
 check((await editor.innerText()).includes('未经历史或生理标定'),'estimated assumptions visible');
 for(const width of [900,420]){
  await page.setViewportSize({width,height:1000});check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'no horizontal overflow '+width);
  await page.screenshot({path:`.cache/qa/support-dynamics-ui/editor-${width}.png`});
 }
 await page.evaluate(()=>window.qa.disabled=true);check(await toggle.isDisabled(),'busy toggle disabled');
 check(await editor.getByLabel('待命耗粮（工作量/小时）',{exact:true}).isDisabled(),'busy parameter editing disabled');
 await page.evaluate(()=>window.qa.disabled=false);await toggle.uncheck();
 check(await page.evaluate(()=>window.qa.value===undefined),'disable restores absent optional field');
 check(!errors.length,'no component exceptions');return{passed:true,checks,scope:'actual Vue component with isolated mutable props; no API mocks'};
}
