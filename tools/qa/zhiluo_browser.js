async page=>{
 const checks=[],errors=[];const check=(v,s)=>{if(!v)throw new Error(s);checks.push(s);};
 page.on('pageerror',e=>errors.push(e.message));
 await page.context().addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};localStorage.removeItem('gentactix-session');});
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:18981/?qa=zhiluo-'+Date.now());
 await page.getByLabel('搜索战役').fill('直罗镇');await page.locator('.battle-option').first().click();
 await page.getByRole('button',{name:/继续配置/}).click();
 await page.getByTestId('execution-backend').selectOption('afsim');await page.locator('#draft-mode').selectOption('historical');
 await page.getByLabel('历史起始阶段').selectOption('first_attack');await page.getByTestId('historical-window').waitFor();
 const win=await page.getByTestId('historical-window').innerText();
 check(win.includes('06:00')&&win.includes('14:00'),'source-bound calculation window displayed');
 check(win.includes('假设'),'dawn conversion remains labeled as a model assumption');
 await page.getByTestId('historical-basis').locator('summary').click();
 const actors=await page.getByTestId('historical-setup').innerText();
 check(actors.includes('红1军团')&&actors.includes('红15军团')&&actors.includes('第109师'),'three first-attack identities displayed');
 check(!actors.includes('红方教学步兵团'),'no representative teaching formation replaces historical IDs');
 check(await page.getByTestId('generate-historical-scenario').isEnabled(),'source phase can enter native DSH configuration');
 check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'1440 no overflow');
 await page.screenshot({path:'.cache/qa/change-paging/zhiluo-source-1440.png'});
 await page.setViewportSize({width:900,height:1000});
 check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'900 no overflow');
 await page.screenshot({path:'.cache/qa/change-paging/zhiluo-source-900.png'});
 check(!errors.length,'no page exceptions after isolated backend selection');
 return {passed:true,checks,route_mocks:false};
}
