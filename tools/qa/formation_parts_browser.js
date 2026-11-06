async page=>{
 const base='http://127.0.0.1:18998',checks=[],errors=[];
 const check=(ok,label)=>{if(!ok)throw Error(label);checks.push(label)};
 page.on('pageerror',e=>errors.push(e.message));
 await page.context().addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};const id=new URL(location.href).searchParams.get('qa-session');if(id)localStorage.setItem('gentactix-session',id);else localStorage.removeItem('gentactix-session')});
 for(const [engine,sid] of [['afsim','e4a44b75bb76'],['narrative','5acfbb41fff9']]){
  const state=await(await page.request.get(base+'/api/sessions/'+sid)).json();
  check(state.turn_count===1,engine+' actual committed T1 exists');
  const parts=state.war_state.red_units.filter(u=>u.formation_part);
  check(parts.length===2&&parts.reduce((n,u)=>n+u.personnel.current,0)===1600,engine+' two native/API parts conserve parent');
  for(const width of [1440,900]){
   await page.setViewportSize({width,height:1000});await page.goto('http://127.0.0.1:18981/?qa=parts-v1&qa-session='+sid);
   await page.waitForFunction(()=>document.querySelector('[data-testid="map-workbench"]')||[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='返回当前战局'));
   const resume=page.getByRole('button',{name:'返回当前战局',exact:true});if(await resume.isVisible())await resume.click();
   await page.getByTestId('map-workbench').waitFor();await page.waitForFunction(()=>!document.querySelector('.desktop-root.operation-running'));
   check(await page.locator('.nato-marker').count()===6,engine+'/'+width+' renders six live leaves with no extra parent');
   await page.getByTestId('analysis-tab-combined').click();const panel=page.getByTestId('combined-arms');await panel.waitFor();
   const group=panel.getByTestId('formation-group-row');check(await group.count()===1,engine+'/'+width+' one parent ledger');
   const text=await group.innerText();check(text.includes('1600 / 投入 1600')&&text.includes('2个计算分队'),engine+'/'+width+' correct personnel total');
   const food=Number(/折合粮食 ([\d.]+)/.exec(text)?.[1]);
   const expected=parts.reduce((n,u)=>n+u.logistics.food*u.formation_part.numerator/u.formation_part.denominator,0);
   check(Math.abs(food-expected)<=.0001,engine+'/'+width+' weighted food matches actual turn rather than summing normalized stocks');
   check(await panel.getByTestId('formation-part-basis').count()===2,engine+'/'+width+' both calculation identities explicitly labeled');
   const toggle=page.getByTestId('command-toggle');await toggle.click();const command=page.getByTestId('command-panel');
   const units=command.getByLabel('单位名单（含无坐标单位）');let ids=[];
   for(const part of parts){const option=units.locator('option').filter({hasText:part.name});check(await option.count()===1,engine+'/'+width+' distinct command entry '+part.formation_part.part_id);ids.push(await option.getAttribute('value'));await units.selectOption(ids.at(-1));check((await command.innerText()).includes('人员 '+part.personnel.current),engine+'/'+width+' selected part count is not parent count')}
   check(ids[0]!==ids[1],engine+'/'+width+' commands address different IDs');
   await command.getByRole('button',{name:'收起指挥面板'}).click();
   check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),engine+'/'+width+' no page overflow');
   await page.screenshot({path:'.cache/qa/formation-partitions/'+engine+'-'+width+'.png'});
  }
 }
 check(!errors.length,'no application page exceptions');return{passed:true,checks,route_mocks:false};
}
