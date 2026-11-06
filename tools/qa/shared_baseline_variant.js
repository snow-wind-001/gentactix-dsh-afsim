async page=>{
 const checks=[],check=(v,s)=>{if(!v)throw new Error(s);checks.push(s);};
 await page.waitForFunction(()=>document.querySelector('[data-testid=historical-validation]')?.textContent?.includes('AFSIM实际装载'),{},{timeout:360000});
 const copying=page.waitForResponse(r=>r.url().endsWith('/api/scenarios/from-historical'));
 await page.locator('#draft-mode').selectOption('synthetic');const copied=await copying,copy=await copied.json();
 check(copied.status()===200,'normal purpose switch derives the existing verified history draft');
 const draft=copy.draft,base=draft.historical_base.parameters;
 for(const row of [...draft.configuration.teams.red,...draft.configuration.teams.blue]){
  const original=base.actors[row.basis_id];check(row.personnel===original.personnel&&row.food===original.logistics.food&&row.ammo===original.logistics.ammo,'default derived personnel and stock equal historical baseline');
  check(JSON.stringify(row.position)===JSON.stringify(original.position)&&JSON.stringify(row.equipment)===JSON.stringify(original.equipment),'default derived equipment and positions equal historical baseline');
 }
 await page.getByTestId('synthetic-setup').waitFor();
 await page.waitForFunction(()=>document.querySelector('[data-testid=scenario-validation]')?.textContent?.includes('AFSIM已装载'));
 check(await page.locator('[data-testid=synthetic-red] details.formation').count()===1&&await page.locator('[data-testid=synthetic-blue] details.formation').count()===1,'all sourced baseline actors retained without generic replacements');
 await page.getByTestId('synthetic-setup').scrollIntoViewIfNeeded();await page.screenshot({path:'.cache/qa/shared-baseline/default-derived.png'});
 await page.getByLabel('演习变体需求').fill('从此冻结历史初态生成合成演习QA，不能改来源版本或basis_id，所有改动为演习假设。红蓝各2编组：红第31师保持6000人与初始装备/粮弹/位置不变；红新增名称“红方演习火力队”，同红basis_id，1200人，炮兵8门、运输4辆，其余装备0，炮弹400发、燃油1000升、food/ammo100、fatigue10。新增红方在原红位置向东约1km，范围内，与蓝方至少300m以满足间瞄最小射程。蓝濑谷原3000人保留初始配置；蓝新增名称“蓝方演习装甲队”，同蓝basis_id，900人、装甲4辆运输4辆其余0，fuel_liters2000、shells0、aa_rounds0、food/ammo100、fatigue10，位于蓝原点以东约100m，不超过原红1000m射程。所有row保留种子全部字段。clock/goal/rules从源基线继承，不要求胜负或伤亡配额。真实读取本次skill/get_scenario_basis并validate配置，最后宿主实际装载AFSIM。');
 const waiting=page.waitForRequest(r=>r.url().endsWith('/api/scenarios/build')&&r.method()==='POST');
 await page.getByTestId('generate-scenario').click();const request=(await waiting).postDataJSON();
 check(request.historical_draft_id===draft.construction.base_draft_id,'native variant generator remains bound to this exact historical draft');
 return {passed:true,checks,base_draft_id:request.historical_draft_id,default_draft_id:draft.id,operation_id:request.operation_id,route_mocks:false};
}
