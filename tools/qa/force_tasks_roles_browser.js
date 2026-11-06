async page=>{
 const base='http://127.0.0.1:19095/api/sessions/cccccccccccc';
 await page.addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:19095'};});
 await page.goto('http://127.0.0.1:19084');
 await page.evaluate(()=>localStorage.setItem('gentactix-session','cccccccccccc'));
 await page.reload();await page.getByRole('button',{name:'返回当前战局',exact:true}).click();
 await page.getByTestId('analysis-tab-forces').click();
 const panel=page.getByTestId('force-organization');
 await panel.locator('[data-task-group]').first().waitFor();
 const r=await page.request.get(base+'/force-organization');if(!r.ok())throw Error(await r.text());
 const org=await r.json();
 await panel.getByLabel('兵团下令对象',{exact:true}).selectOption(org.groups[0].id);
 await panel.getByLabel('兵团任务方式',{exact:true}).selectOption('defend');
 await panel.getByRole('button',{name:'预览兵团任务',exact:true}).click();
 const preview=panel.getByTestId('force-task-preview');await preview.waitFor();
 const roles=preview.getByRole('combobox'),count=await roles.count();
 if(count!==4)throw Error('Expected four role selectors');
 for(let i=0;i<count;i++){
  const actual=await roles.nth(i).evaluate(el=>({value:el.value,index:el.selectedIndex,text:el.selectedOptions[0]?.textContent}));
  if(actual.value!==''||actual.index!==0||!actual.text?.includes('自动'))throw Error('Automatic role is visually blank: '+JSON.stringify(actual));
 }
 await roles.first().selectOption('reserve');
 if(!await preview.getByRole('button',{name:'确认暂存兵团任务',exact:true}).isDisabled())throw Error('Role change must invalidate preview');
 await page.setViewportSize({width:900,height:1000});
 await preview.scrollIntoViewIfNeeded();
 await page.screenshot({path:'.cache/qa/force-tasks-2026-10-31/browser/roles-900.png'});
 return {passed:true,checks:['Four automatic roles visibly selected','Role change invalidates confirmation'],queue_changed:false};
}
