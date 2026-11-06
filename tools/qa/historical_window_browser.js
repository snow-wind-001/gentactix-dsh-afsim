async page => {
 const checks=[],errors=[];let builds=0;
 const check=(v,s)=>{if(!v)throw Error(s);checks.push(s)};
 await page.context().addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};localStorage.removeItem('gentactix-session')});
 page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/api/historical-scenarios/build'))builds++});
 await page.goto('http://127.0.0.1:18981/?qa=historical-window-v2');
 await page.getByLabel('搜索战役').fill('衡阳保卫战');await page.locator('.battle-option').first().click();
 await page.getByRole('button',{name:/继续配置/}).click();await page.getByTestId('historical-basis').waitFor();
 for(const purpose of ['historical','synthetic']){
  await page.locator('#draft-mode').selectOption(purpose);
  for(const engine of ['afsim','narrative']){
   await page.getByTestId('execution-backend').selectOption(engine);await page.locator('#draft-step').selectOption('1天');
   check(await page.getByTestId('generate-historical-scenario').isDisabled(),purpose+'/'+engine+' blocks impossible day before model');
   check(await page.getByTestId('launch-start').isDisabled(),purpose+'/'+engine+' primary launch also blocked');
   check((await page.getByTestId('historical-step-gap').innerText()).includes('计算窗口'),purpose+'/'+engine+' explains actual window');
   check(await page.locator('#draft-step').inputValue()==='1天',purpose+'/'+engine+' never silently rewrites selected duration');
   await page.locator('#draft-step').selectOption('15分钟');
   check(await page.getByTestId('generate-historical-scenario').isEnabled(),purpose+'/'+engine+' valid quarter hour can generate');
   check(await page.getByTestId('historical-step-gap').count()===0,purpose+'/'+engine+' warning clears reactively');
  }
 }
 await page.locator('#draft-mode').selectOption('historical');await page.getByTestId('execution-backend').selectOption('afsim');
 await page.locator('#draft-step').selectOption('1天');
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});await page.getByTestId('historical-step-gap').scrollIntoViewIfNeeded();
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),width+' no overflow');
  await page.screenshot({path:'.cache/qa/catalog-expansion/window-'+width+'.png'});
 }
 check(builds===0,'no model build request for validation-only checks');check(!errors.length,'no application page errors');
 return {passed:true,checks,route_mocks:false,build_requests:builds};
}
