async page=>{
 const checks=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
 function check(ok,label){if(!ok)throw new Error(label);checks.push(label);}
 await page.context().addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:18995'};localStorage.removeItem('gentactix-session');});
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:18981/');
 await page.getByLabel('搜索战役').fill('徐州会战');await page.locator('.battle-option').first().click();await page.getByRole('button',{name:/继续配置/}).click();
 await page.getByLabel('历史起始阶段').selectOption('taierzhuang_opening');await page.getByTestId('historical-basis').waitFor();
 check((await page.getByTestId('historical-basis').innerText()).includes('2个不重叠计算单位'),'opening binds two actors, not later Sakamoto');
 await page.getByTestId('historical-exclusions').locator('summary').click();
 check((await page.getByTestId('historical-exclusions').innerText()).includes('坂本支队'),'later unit remains visibly retained as source reference');
 await page.getByLabel('历史起始阶段').selectOption('taierzhuang');await page.getByTestId('historical-basis').waitFor();
 check((await page.getByTestId('historical-basis').innerText()).includes('3个不重叠计算单位'),'later phase binds its three actors');
 await page.getByRole('button',{name:'返回选择',exact:true}).click();await page.getByLabel('搜索战役').fill('平型关');await page.locator('.battle-option').first().click();await page.getByRole('button',{name:/继续配置/}).click();
 await page.getByLabel('历史起始阶段').selectOption('qiaogou');await page.getByTestId('historical-window').waitFor();
 check((await page.getByTestId('historical-window').innerText()).includes('13:00'),'supported ground-model boundary visible');
 check((await page.getByTestId('historical-basis').innerText()).includes('6个不重叠计算单位'),'six sourced actors available in normal entry');
 await page.getByTestId('historical-exclusions').locator('summary').click();const excluded=await page.getByTestId('historical-exclusions').innerText();
 check(excluded.includes('独立团')&&excluded.includes('骑兵营')&&excluded.includes('日机'),'outside and later source identities visible without invented map actors');
 check(await page.locator('.nato-marker').count()===0,'no unit markers invented before parameter generation');
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),width+' no horizontal overflow');
  await page.screenshot({path:'.cache/qa/historical-attendance/phase-'+width+'.png'});
 }
 check(errors.length===0,'No page errors');return {passed:true,checks,route_mocks:false};
}
