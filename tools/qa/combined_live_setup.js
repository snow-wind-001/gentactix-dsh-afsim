async page => {
  const base='http://127.0.0.1:8700';
  const assert=(ok,text)=>{if(!ok)throw new Error(text);};
  await page.setViewportSize({width:1440,height:1000});
  const healthy=await page.request.get(base+'/api/health');assert(healthy.ok(),'backend not ready');
  await page.goto('http://127.0.0.1:18901/?combined_demo='+Date.now());
  await page.getByRole('textbox',{name:'搜索战役'}).fill('湘西');
  await page.locator('.battle-option').first().click();
  await page.getByRole('button',{name:/继续配置/}).click();
  await page.getByTestId('execution-backend').selectOption('afsim');
  await page.waitForFunction(()=>document.querySelector('#draft-mission')?.value==='CA-AJ18-v1');
  const initReady=page.waitForResponse(r=>r.url().endsWith('/init'),{timeout:90000});
  await page.getByRole('button',{name:'创建并进入推演',exact:true}).click();
  const response=await initReady,snapshot=await response.json();assert(response.ok(),JSON.stringify(snapshot));
  assert(snapshot.war_state.combined_arms.version==='combined-arms-teaching-1','wrong model');
  await page.getByRole('button',{name:'兵种与保障',exact:true}).click();
  await page.getByTestId('combined-arms').waitFor();
  assert(await page.getByTestId('combined-unit').count()===6,'missing regimental groups');
  await page.evaluate(id=>{window.combinedDemo={id,turns:[]};},snapshot.session_id);
  await page.screenshot({path:'.cache/qa/combined-arms/initial-wide.png'});
  return {passed:true,session_id:snapshot.session_id,model:snapshot.war_state.combined_arms.version,
    uniform_default:true,units:6,force_people:snapshot.war_state.red_units.map(u=>u.personnel.current)};
}
