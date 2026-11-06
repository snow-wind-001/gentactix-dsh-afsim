async page=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.context().addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};localStorage.removeItem('gentactix-session');});
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:18981/?qa=ww2-phase-'+Date.now());
 await page.getByLabel('搜索战役').fill('台儿庄战役');await page.locator('.battle-option').first().click();
 await page.getByRole('button',{name:/继续配置/}).click();await page.getByTestId('execution-backend').selectOption('afsim');
 await page.locator('#draft-mode').selectOption('historical');
 await page.getByTestId('generate-historical-scenario').waitFor();
 const phase=await page.getByLabel('历史起始阶段').inputValue();
 if(phase!=='urban_opening')throw new Error('Dedicated battle did not default to its sourced opening phase');
 const history=page.getByRole('checkbox',{name:/本地史料约束/});if(!await history.isChecked())await history.check();
 await page.getByLabel('计算参数与推演目标需求').fill('台儿庄24—28日前期的具名单位局部QA。只用该阶段的第31师和濑谷支队真实ID，不加入坂本或整个两师团。缺载字段全部明确估计，不能冒充史实人数/阵地/效能：31师本地投入6000、濑谷支队本地3000人，均为徒步步兵，自卫1000米；无装甲/火炮/防空配额，无航空，不代表史实没有这些兵器。以台儿庄现代参考点为局部示意，红在其北约300米、蓝再向北300米，不是历史具体街巷。1938-03-24 08:00开始、30分钟一轮、8轮至12:00。地形因子1.5、范围8公里，士气等合理估计，粮弹工作量80。目标delay：8轮截止红方至少一个可用单位且蓝方未到红后方约3公里出口，是局部QA条件。禁用桥梁假障碍；31师死伤近3000和全战役统计只能参考，不作必扣指标。请真实使用skill/基础/校验并AFSIM装载。');
 const pending=page.waitForRequest(r=>r.url().endsWith('/api/historical-scenarios/build')&&r.method()==='POST');
 await page.getByTestId('generate-historical-scenario').click();const request=(await pending).postDataJSON();
 await page.getByTestId('historical-build-progress').waitFor();
 await page.screenshot({path:'.cache/qa/ww2-phases/taierzhuang-build.png'});
 if(errors.length)throw new Error(errors.join('; '));
 return {operation_id:request.operation_id,battle:request.battle,phase_id:request.phase_id,use_rag:await history.isChecked(),route_mocks:false};
}
