async page=>{
 const checks=[],check=(v,s)=>{if(!v)throw new Error(s);checks.push(s);};
 await page.context().addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};localStorage.removeItem('gentactix-session');});
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:18981/?qa=shared-baseline');
 await page.getByLabel('搜索战役').fill('台儿庄战役');await page.locator('.battle-option').first().click();
 await page.getByRole('button',{name:/继续配置/}).click();await page.getByTestId('execution-backend').selectOption('afsim');
 const battle=await page.locator('#draft-battle').inputValue();
 await page.locator('#draft-mode').selectOption('synthetic');await page.getByTestId('historical-setup').waitFor();
 check(await page.locator('#draft-mission').count()===0,'normal synthetic entry does not select a CA representative template');
 check((await page.getByTestId('shared-initial-note').innerText()).includes('相同'),'shared source-first workflow explained');
 await page.locator('#draft-battle').selectOption({label:'长平之战'});await page.getByTestId('historical-configuration-gap').waitFor();
 check(await page.locator('.nato-marker').count()===0&&await page.getByTestId('synthetic-setup').count()===0,'unprofiled synthetic battle shows its gap rather than invented units');
 await page.locator('#draft-battle').selectOption(battle);await page.getByTestId('generate-historical-scenario').waitFor();
 await page.locator('#draft-mode').selectOption('historical');await page.locator('#draft-step').selectOption('15分钟');
 await page.getByLabel('计算参数与推演目标需求').fill('同一历史初态派生合成演习的QA。台儿庄3月24—28日阶段，只用真实ID第31师与濑谷支队。红本地6000、蓝本地3000，均步兵徒步speed3、直射1000m、ground_control_radius_km0.5；不是史实实到。五类装备及shells/aa_rounds/fuel_liters/spares/materials全0，为本局无重装备配额，不代表历史没有。红在台儿庄参考点北约300m、蓝再北300m，明确估计、非历史街巷。1938-03-24 08:00开始，按启动页15分钟16轮至12:00。area中心台儿庄，半径8km，terrain_factor1.5。双方logistics food/ammo100，support.stock0及inventory五项均0，不补给。formation.role infantry、motorized false、fatigue10、suppression0、entrenchment10、dispersion_km2 3、protection0.15、signal100、intel_confidence100、intel_age_min0、reload_remaining0。规则direct_range_m1000、artillery_range_m12000、armor_range_m3000。goal delay第16轮截止，红至少1可用，蓝未到红后约3km出口600m内，required_turns1。桥梁和航空关闭。其他规则沿用模板并说明先验，史料近3000不作扣兵配额。真实skill、basis、validate与AFSIM装载。');
 const waiting=page.waitForRequest(r=>r.url().endsWith('/api/historical-scenarios/build')&&r.method()==='POST');
 await page.getByTestId('generate-historical-scenario').click();const request=(await waiting).postDataJSON();
 check(request.time_step==='15分钟','baseline generator obeys structured selected timestep');
 await page.screenshot({path:'.cache/qa/shared-baseline/building.png'});
 return {checks,operation_id:request.operation_id,route_mocks:false};
}
