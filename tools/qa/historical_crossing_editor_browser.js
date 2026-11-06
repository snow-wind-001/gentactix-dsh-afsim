async page=>{
 const base='http://127.0.0.1:18998',checks=[],errors=[];
 const check=(v,s)=>{if(!v)throw new Error(s);checks.push(s)};page.on('pageerror',e=>errors.push(e.message));
 const list=await(await page.request.get(base+'/api/sessions')).json();
 for(const row of list.sessions.filter(s=>s.scenario==='乌江后续通行QA-narrative')){
  for(let i=0;i<600;i++){
   const state=await(await page.request.get(base+'/api/sessions/'+row.session_id+'/progress')).json();
   if(!state.active)break;
   await page.waitForTimeout(1000);
  }
 }
 await page.context().addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};localStorage.removeItem('gentactix-session')});
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:18981/?qa=crossing-editor');
 await page.getByLabel('搜索战役',{exact:true}).fill('强渡乌江');await page.locator('.battle-option').filter({hasText:'强渡乌江'}).click();await page.getByRole('button',{name:'继续配置'}).click();
 await page.locator('#draft-mode').selectOption('historical');await page.getByTestId('execution-backend').selectOption('afsim');const c=page.getByTestId('historical-setup');
 await c.getByTestId('generate-historical-scenario').waitFor();
 const instruction='仅follow_on_jan3桥成后局部，所有以下数值是软件QA估计而非史实实力或历史水文。1935-01-03 12:00开始，每轮30分钟共6轮；center27.3148,107.402半径30km，terrain_factor1.5。goal red/crossing、required_survivors2、required_turns1、deadline_turn6、objective和exit=27.3158,107.402，半径0.1km。5个真实ID：军委纵队1600人位置27.3138,107.402；红5军团当地3000人位置27.3137,107.402；三个黔军团各当地1000人，位置27.33,107.40、27.331,107.402、27.332,107.404。所有type步兵、speed3km/h、自卫射程500m、地面控制0.1km、motorized=false；纵队role=support，其余infantry。装备仅运输单元分别4、6、2、2、2，其余全0。全员food=ammo80，fatigue=suppression=entrenchment=0，dispersion_km2=3，protection0.1，signal100、intel_confidence80、intel_age_min0；fuel_liters、spares、materials、shells、aa_rounds、reload_remaining均0。support红27.31,107.402、蓝27.34,107.402；stock和五类inventory全0。rules桥约束true、air_support=false、motorized=false、convoy_km_per_turn10、required_survivors2，command_base_s、command_signal_s、command_distance_s_per_km均0，其余保留模板。facility沿用id，名称江界河后续通行计算通道，坐标center，progress=integrity100、materials0、capacity2、used0。crossing_model为formation-crossing-1；barrier.a=27.3148,107.397、b=27.3148,107.407，banks.a=27.3145,107.402、b=27.3151,107.402；throughput_work_per_hour15000，equipment_work为armor10,artillery5,air_defense5,engineer0,transport2；build_progress_per_engineer_hour10、supply_work_per_unit100。assumption明确几何、数量和能力全是QA估计，不能声称模拟此前舟筏突击与桥头夺取。真实调用skill、basis和校验，实际装载AFSIM。';
 await c.getByLabel('计算参数与推演目标需求').fill(instruction);
 const built=page.waitForResponse(r=>r.url().endsWith('/api/historical-scenarios/build')&&r.request().method()==='POST',{timeout:600000});
 await c.getByTestId('generate-historical-scenario').click();const br=await built;check(br.ok(),'normal UI DSH build succeeds');const draft=await br.json();
 const editor=c.getByTestId('crossing-editor');await editor.waitFor();await editor.locator('summary').click();
 check(await editor.getByLabel('使用版本化渡运模型').isChecked(),'required crossing capability is shown');
 check(await c.getByLabel('目标类型').inputValue()==='crossing','crossing goal is editable');
 check(await c.getByLabel('目标半径',{exact:false}).isEnabled(),'crossing goal location/radius controls enabled');
 const rate=editor.getByLabel('渡运每小时吞吐');check(await rate.inputValue()==='15000','generated throughput rendered');
 await rate.fill('0');await rate.blur();check(!(await c.getByTestId('historical-validation').innerText()).includes('已通过AFSIM'),'edit invalidates prior validation');
 let response=page.waitForResponse(r=>r.url().endsWith('/api/historical-scenarios/validate')&&r.request().method()==='POST');
 await c.getByTestId('validate-historical-scenario').click();let r=await response;check(!r.ok(),'zero throughput is rejected by real backend');
 await rate.fill('12000');await rate.blur();await editor.getByLabel('渡运估计依据').fill('QA将吞吐改为12000工作量每小时；几何和能力均为未标定估计，不是1935年河槽。');
 response=page.waitForResponse(r=>r.url().endsWith('/api/historical-scenarios/validate')&&r.request().method()==='POST');
 await c.getByTestId('validate-historical-scenario').click();r=await response;check(r.ok(),'edited facility actually reloads native AFSIM');const validated=await r.json();
 check(validated.parameters.facility.crossing_model.throughput_work_per_hour===12000,'backend keeps edited throughput');
 check(validated.initial.definition.units.every(u=>Object.values(u.facts).every(f=>f.value===null)),'editing estimates preserves unknown historical facts');
 check(draft.parameters.facility.crossing_model.throughput_work_per_hour===15000,'original draft data unchanged');
 check(await page.locator('.crossing-corridor').count()===1,'configuration map preview renders corridor');
 await page.screenshot({path:'.cache/qa/river-crossing/editor-1440.png'});
 await page.setViewportSize({width:900,height:1000});check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'editor fits 900px');
 await page.screenshot({path:'.cache/qa/river-crossing/editor-900.png'});check(!errors.length,'no editor page exceptions');
 return{passed:true,checks,route_mocks:false,original_draft_id:draft.id,edited_draft_id:validated.id};
}
