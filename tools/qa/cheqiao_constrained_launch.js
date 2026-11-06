async page=>{
 const build=await page.evaluate(()=>window.__cheqiaoFullQA.build);
 if(!build||build.status!==200)throw Error('Actual generation has not completed successfully');
 const setup=page.getByTestId('historical-setup');
 const parent=setup.locator('[data-campaign-actor="ww2.jp.huaian_relief"]');
 await parent.locator('summary').click();
 const kinds=await parent.locator('.part select[aria-label$="时点含义"]').evaluateAll(nodes=>nodes.map(x=>x.value));
 const refs=await parent.locator('.part select[aria-label$="史料时点参考"]').evaluateAll(nodes=>nodes.map(x=>x.value));
 if(kinds.length!==4||kinds.some(x=>x!=='battlefield_entry')||new Set(refs).size!==4)throw Error('UI lost typed batch schedules');
 await page.setViewportSize({width:900,height:1000});await parent.scrollIntoViewIfNeeded();
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('900px editor overflow');
 await page.screenshot({path:'.cache/qa/cheqiao-complete/constrained/typed-arrivals-900.png'});
 await page.setViewportSize({width:1440,height:1000});
 await page.getByTestId('launch-start').click();
 await page.getByTestId('map-workbench').waitFor({timeout:120000});
 await page.waitForFunction(()=>!document.querySelector('.desktop-root.operation-running'));
 const counts={units:await page.locator('.nato-marker').count(),waiting:await page.locator('.nato-marker.campaign-staging').count()};
 if(counts.units!==19||counts.waiting!==5)throw Error('Initial native roster does not match nineteen entities/five waiting');
 await page.screenshot({path:'.cache/qa/cheqiao-complete/constrained/initial-1440.png'});
 return {draft_id:build.id,session_id:await page.evaluate(()=>localStorage.getItem('gentactix-session')),counts,kinds,refs,mocks:false};
}
