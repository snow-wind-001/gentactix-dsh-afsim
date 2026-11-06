async page => {
 const root='.cache/qa/fixed-parameters-2026-11-01/browser';
 const prior=page.__fixedPrior;if(!prior)throw Error('Explicit numerical QA priors required');
 page.__fixedBuild={status:'idle'};page.__fixedChecks=[];
 page.on('response',async r=>{if(r.url().endsWith('/api/historical-scenarios/build')&&r.request().method()==='POST'){
  page.__fixedBuild={status:'finished',http:r.status(),body:await r.json(),request:r.request().postDataJSON()};
 }});
 await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19131'});
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:19089/');
 await page.getByRole('textbox',{name:'搜索战役',exact:true}).fill('徐州');
 await page.locator('.battle-option').filter({hasText:'徐州会战总览'}).click();
 await page.getByRole('button',{name:/继续配置/}).click();
 await page.locator('#draft-mode').selectOption('historical');await page.locator('#draft-executor').selectOption('afsim');
 await page.locator('#draft-step').selectOption('6小时');
 const phase=page.getByLabel('历史起始阶段',{exact:true});await phase.locator('option[value="taierzhuang"]').waitFor({state:'attached'});await phase.selectOption('taierzhuang');
 const required=page.getByLabel('生成时必须配置定时补给',{exact:true});await required.check();
 const editor=page.getByTestId('fixed-parameter-inputs');await editor.waitFor();await editor.locator('summary').click();
 const basisResponse=await page.request.get('http://127.0.0.1:19131/api/historical-scenarios/basis?battle='+encodeURIComponent('抗日战争-徐州会战总览-1938.01至1938.05')+'&phase_id=taierzhuang&termination_mode=objectives');
 const basis=await basisResponse.json();if(!basisResponse.ok())throw Error('QA basis missing');
 const paths=[['area','center','lat'],['area','center','lng'],['area','radius_km'],['area','terrain_factor'],
  ['goal','objective','lat'],['goal','objective','lng'],['goal','exit','lat'],['goal','exit','lng'],
  ['goal','radius_km'],['goal','deadline_turn'],['goal','required_turns'],['goal','required_survivors'],
  ...['period_seconds','passive_work_per_hour','resupply_work_per_hour','convoy_speed_kph','loading_hours'].map(k=>['supply_schedule',k]),
  ['supply_schedule','warehouse_tons_per_hour','red-historical-supply'],['supply_schedule','warehouse_tons_per_hour','blue-historical-supply'],
  ['support_dynamics','food_work_per_hour'],...Object.keys(prior.actors).map(id=>['actors',id,'personnel'])];
 const fixed=[];
 for(const path of paths){
  const field=basis.fixed_parameter_fields.find(f=>JSON.stringify(f.path)===JSON.stringify(path));if(!field)throw Error('No fixed field '+JSON.stringify(path));
  let value=prior;for(const k of path)value=value[k];
  await page.getByLabel('固定参数配置对象',{exact:true}).selectOption(field.group);
  await page.getByLabel('固定参数数值项目',{exact:true}).selectOption(JSON.stringify(path));
  await page.getByLabel('固定参数指定数值',{exact:true}).fill(String(value));
  await page.getByTestId('add-fixed-parameter').click();fixed.push({path,value});
 }
 if(await editor.locator('li').count()!==fixed.length)throw Error('UI lost selected fixed values');
 await required.uncheck();if(!await page.getByTestId('generate-historical-scenario').isDisabled())throw Error('Missing model constraint silently discarded');
 page.__fixedChecks.push('required-model-off-blocks-generation');await required.check();
 if(!await page.getByTestId('generate-historical-scenario').isEnabled())throw Error('Restoring model did not unblock generation');
 page.__fixedChecks.push('restored-requirement-retains-fixed-values');
 await editor.scrollIntoViewIfNeeded();await page.screenshot({path:root+'/fixed-before-generation.png'});
 const actors=Object.fromEntries(Object.entries(prior.actors).map(([id,a])=>[id,{personnel:a.personnel,equipment:a.equipment,position:a.position,
  type:a.type,speed:a.speed,attack_range_m:a.attack_range_m,ground_control_radius_km:0,logistics:a.logistics,formation:a.formation}]));
 const instruction='这是固定数值的真实Native工具边界验收。所有人数、装备与部署是QA估计，不是史实。先读skill与basis。'+
  '为验证原子拒收，globals首次update仅尝试patch={"supply_schedule":{"passive_work_per_hour":1}}，须观察updated=false和fixed_parameter_conflicts；草稿及revision未改。'+
  '之后按basis.fixed_parameters与预填值完成正确公共条件，不修改固定数。不要重复故障。bridge_enabled=false，无航空任务，goal.team=red，termination_mode=objectives；其余规则沿模板。'+
  'assumptions逐项声明未标定；定时配送按分段先消耗后到货，不用旧轮末解释。单位保持真实ID与一部范围，按以下QA先验填入，其他字段在合法范围明确估计：'+JSON.stringify(actors)+
  '。每片只返回版本、哈希及简短说明，最终必须真实validate。';
 if(instruction.length>4000)throw Error('QA instruction over supported length '+instruction.length);
 await page.getByRole('textbox',{name:'计算参数与推演目标需求',exact:true}).fill(instruction);
 page.__expectedFixed=fixed;page.__fixedBuild={status:'pending',started:Date.now()};
 await page.getByTestId('generate-historical-scenario').click();
 return {started:true,fixed_fields:fixed.length,checks:page.__fixedChecks,instruction_chars:instruction.length,scope:'Actual UI-selected numerical constraints, configured real DSH Native and AFSIM load, deliberate one conflicting tool update'};
}
