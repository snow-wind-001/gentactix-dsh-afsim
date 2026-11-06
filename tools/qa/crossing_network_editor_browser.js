async page=>{
 const checks=[],errors=[];const check=(v,s)=>{if(!v)throw new Error(s);checks.push(s)};
 page.on('pageerror',e=>errors.push(e.message));await page.setViewportSize({width:900,height:1000});
 await page.goto('http://127.0.0.1:18991/network-editor.html');await page.getByTestId('crossing-editor').first().locator('summary').first().click();
 check(await page.getByTestId('crossing-site-row').count()===1,'existing independent site loaded');
 check(await page.getByLabel('使用舟艇运输').count()===0,'network cannot silently enable incompatible boats');
 await page.getByRole('button',{name:'增加独立渡点',exact:true}).click();
 check(await page.getByTestId('crossing-site-row').count()===2,'add independent draft site');
 check(await page.evaluate(()=>window.qa.facility.crossing_network.sites[1].crossing_model.assumption===''),'new site requires its own input basis');
 const primary=page.getByTestId('crossing-editor').first();await primary.getByLabel('barrier-a纬度',{exact:true}).fill('31.7345');
 await page.waitForFunction(()=>window.qa.facility.crossing_network.sites.every(s=>s.crossing_model.barrier.a.lat===31.7345));
 check(true,'shared river input propagates to all sites');
 const second=page.getByTestId('crossing-site-row').first();await second.locator('summary').click();
 await second.getByLabel('渡运每小时吞吐',{exact:true}).fill('650');
 check(await page.evaluate(()=>window.qa.facility.crossing_model.throughput_work_per_hour===1000&&window.qa.facility.crossing_network.sites[0].crossing_model.throughput_work_per_hour===650),'editing one capacity does not change another');
 check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'900px editor fits without horizontal overflow');
 await page.screenshot({path:'.cache/qa/crossing-network-ui-2026-10-29/editor-900.png'});
 await page.evaluate(()=>window.qa.disabled=true);
 check(await page.getByRole('button',{name:'增加独立渡点',exact:true}).isDisabled(),'busy editor disables additions');
 await page.evaluate(()=>window.qa.disabled=false);
 await page.getByTestId('crossing-site-row').last().getByRole('button',{name:/^移除渡点 /}).click();
 check(await page.getByTestId('crossing-site-row').count()===1,'removing one preserves the other');
 await page.getByTestId('crossing-site-row').first().getByRole('button',{name:/^移除渡点 /}).click();
 check(await page.evaluate(()=>!window.qa.facility.crossing_network),'removing final additional site restores single-site schema');
 check(await page.getByLabel('使用舟艇运输').count()===1,'single-site boat choice returns');
 check(!errors.length,'no component exceptions');return{passed:true,checks,scope:'actual component, isolated input fixture; no product API changes'};
}
