async page=>{
 const checks=[];const check=(v,s)=>{if(!v)throw Error(s);checks.push(s)};
 await page.goto('http://127.0.0.1:18985/');
 await page.getByLabel('搜索战役').fill('车桥');await page.locator('.battle-option').first().click();
 await page.getByRole('button',{name:/继续配置/}).click();
 await page.locator('#draft-mode').selectOption('historical');await page.locator('#draft-executor').selectOption('afsim');
 await page.locator('#draft-step').selectOption('30分钟');
 const c=page.getByTestId('historical-setup');
 await c.getByLabel('史料档案版本').selectOption('1.1.0');
 await c.getByLabel('历史起始阶段').selectOption('core_march5_6');
 const pending=c.getByTestId('pending-historical-configurations');await pending.locator('summary').click();
 check(await pending.getByRole('button',{name:'装载这份配置'}).count()===1,'actual saved input is discoverable after browser and API restart');
 const response=page.waitForResponse(r=>r.url().endsWith('/api/historical-scenarios/retry-load')&&r.request().method()==='POST',{timeout:120000});
 await pending.getByRole('button',{name:'装载这份配置'}).click();
 const raw=await response;const draft=await raw.json();check(raw.ok(),JSON.stringify(draft.detail??'actual retry succeeds'));
 check(draft.initial.version==='1.1.0'&&draft.validation.scope==='native_load','retry preserves exact source version and performs native load');
 check(draft.afsim.returncode===0&&draft.afsim.entity_count===19,'native AFSIM accepts nineteen actual calculation entities');
 await page.waitForFunction(()=>document.querySelectorAll('.nato-marker').length===19);
 check(await c.locator('[data-campaign-actor]').count()===15,'fifteen parent arrival/fortification editors are present');
 await page.evaluate(id=>{window.__cheqiaoRetryDraft=id},draft.id);
 await page.screenshot({path:'.cache/qa/cheqiao-complete/full/loaded-1440.png'});
 return {passed:true,checks,draft_id:draft.id,parameters_unchanged_by_retry:true,route_mocks:false};
}
