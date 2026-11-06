async page=>{
 const checks=[],errors=[],requests=[],check=(v,s)=>{if(!v)throw new Error(s);checks.push(s);};
 const error=e=>errors.push(e.message),request=r=>requests.push(r.url());page.on('pageerror',error);page.on('request',request);
 await page.context().addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};localStorage.removeItem('gentactix-session');});
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:18981/?qa=shared-compatibility');
 await page.getByLabel('搜索战役').fill('长平');await page.locator('.battle-option').first().click();await page.getByRole('button',{name:/继续配置/}).click();
 await page.locator('#draft-mode').selectOption('synthetic');await page.getByTestId('historical-configuration-gap').waitFor();
 check(await page.locator('#draft-synthetic-basis').inputValue()==='shared'&&!requests.some(u=>u.endsWith('/api/missions')),'default synthetic path neither loads nor selects representative templates');
 check(await page.locator('.nato-marker').count()===0&&await page.getByTestId('launch-start').isDisabled(),'unprofiled shared initial state is explicit and cannot launch invented forces');
 await page.locator('#draft-step').selectOption('15分钟');
 await page.context().setOffline(true);await page.locator('#draft-synthetic-basis').selectOption('representative');
 await page.getByRole('button',{name:'重新读取兼容模板',exact:true}).waitFor();
 check(await page.getByTestId('launch-start').isDisabled(),'failed optional catalog load does not enable creation');
 await page.context().setOffline(false);await page.getByRole('button',{name:'重新读取兼容模板',exact:true}).click();
 await page.getByTestId('scenario-basis').waitFor();
 check((await page.getByTestId('representative-scope').innerText()).includes('不保证')&&await page.locator('#draft-mission option').count()>0,'explicit compatibility selection retains source-based teaching capability and labels its limits');
 check(await page.locator('#draft-step').isDisabled()&&await page.locator('.nato-marker').count()>0,'compatible template has its own fixed step and visible source seed');
 await page.locator('#draft-synthetic-basis').selectOption('shared');await page.getByTestId('historical-configuration-gap').waitFor();
 check(await page.locator('#draft-step').inputValue()==='15分钟'&&await page.locator('#draft-step').isEnabled(),'leaving compatibility restores the selected shared step');
 check(await page.locator('#draft-mission').count()===0&&await page.locator('.nato-marker').count()===0,'shared source gap is restored without leaked representative markers');
 await page.locator('#draft-mode').selectOption('historical');
 check(await page.locator('#draft-synthetic-basis').count()===0&&await page.getByTestId('launch-start').isDisabled(),'historical simulation never substitutes the compatibility template');
 for(const width of [1440,900]){await page.setViewportSize({width,height:1000});check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),width+' source gap fits viewport');await page.screenshot({path:'.cache/qa/shared-baseline/gap-'+width+'.png'});}
 check(errors.length===0,'no browser page exceptions');page.removeListener('pageerror',error);page.removeListener('request',request);
 return {passed:true,checks,route_mocks:false,network_failure:'real browser offline then online recovery'};
}
