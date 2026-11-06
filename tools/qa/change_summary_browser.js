async page=>{
 const checks=[],errors=[],check=(v,s)=>{if(!v)throw new Error(s);checks.push(s);};
 const error=e=>errors.push(e.message);page.on('pageerror',error);
 await page.context().addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};localStorage.setItem('gentactix-session','ab9e42f20993');});
 for(const width of [1440,900]){
  await page.setViewportSize({width,height:1000});await page.goto('http://127.0.0.1:18981/?qa=aggregate');
  await page.getByRole('button',{name:'返回当前战局',exact:true}).click();await page.getByTestId('map-workbench').waitFor();
  await page.locator('#analysis-tab-chat').click();
  const latest=page.locator('.msg.assistant').last(),table=latest.locator('.markdown-table-scroll').first();
  await table.waitFor();check(await table.locator('tbody tr').count()===4,width+' actual four-unit analysis renders as a data table');
  for(const name of ['第31师','红方演习火力队','日军濑谷支队','蓝方演习装甲队'])check((await table.innerText()).includes(name),width+' '+name+' row retained');
  check(await table.locator('th[scope=col]').count()>=4,width+' table has semantic column headers');
  check(await table.evaluate(e=>e.scrollWidth>e.clientWidth),width+' wide analysis scrolls inside the table');
  await table.focus();await page.keyboard.press('ArrowRight');await page.waitForFunction(()=>{const e=document.activeElement;return e?.classList.contains('markdown-table-scroll')&&e.scrollLeft>0;});
  check(await table.evaluate(e=>e.scrollLeft>0),width+' table is keyboard scrollable');
  // Native keyboard scrolling animates; let it settle before the evidence image.
  await page.waitForTimeout(250);await table.evaluate(e=>e.scrollLeft=0);await table.scrollIntoViewIfNeeded();
  check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),width+' no document horizontal overflow');
  await page.screenshot({path:'.cache/qa/change-summary/table-'+width+'.png'});
 }
 check(errors.length===0,'no browser page exceptions');page.removeListener('pageerror',error);return {passed:true,checks,route_mocks:false};
}
