async page => {
 const base='http://127.0.0.1:18998',checks=[],errors=[];
 const check=(v,s)=>{if(!v)throw Error(s);checks.push(s)};
 page.on('pageerror',e=>errors.push(e.message));
 await page.context().addInitScript(()=>{window.gentactix={backendUrl:'http://127.0.0.1:18998'};const id=new URL(location.href).searchParams.get('qa-session');if(id)localStorage.setItem('gentactix-session',id)});
 for(const [engine,sid,losses] of [['afsim','f0c4e7d0b9d1',[21,22]],['narrative','6da184510a7a',[100,89]]]){
  for(const width of [1440,900]){
   await page.setViewportSize({width,height:1000});await page.goto('http://127.0.0.1:18981/?qa=catalog-results-v1&qa-session='+sid);
   await page.getByRole('button',{name:'返回当前战局',exact:true}).click();await page.getByTestId('map-workbench').waitFor();
   check(await page.locator('.nato-marker').count()===2,engine+'/'+width+' two real local identities on map');
   await page.getByTestId('analysis-tab-combined').click();const p=page.getByTestId('combined-arms');await p.waitFor();
   check((await p.locator('.model-title').first().innerText()).includes(engine==='afsim'?'AFSIM':'DSH模型估计'),engine+'/'+width+' correct computation provenance');
   check((await p.getByTestId('combat-assessment').innerText()).includes('15 分钟'),engine+'/'+width+' one round is fifteen minutes');
   const rows=p.getByTestId('combined-unit');check(await rows.count()===2,engine+'/'+width+' loss and support cards for both units');
   for(let i=0;i<2;i++)check((await rows.nth(i).innerText()).includes(String(losses[i])),engine+'/'+width+' actual nonzero loss visible '+i);
   check(await p.getByTestId('casualty-breakdown').count()===2,engine+'/'+width+' killed and wounded remain separate');
   check(await p.getByTestId('unit-supply-route').count()===2,engine+'/'+width+' both supply receipts visible');
   if(engine==='narrative')check((await p.innerText()).includes('AFSIM关闭'),engine+'/'+width+' estimated results do not claim native telemetry');
   await page.getByTestId('focus-map').click();check(!await page.getByTestId('analysis-panel').isVisible(),engine+'/'+width+' analysis drawer collapses');
   for(let n=0;n<3;n++)await page.locator('.leaflet-control-zoom-in').click();
   await page.waitForFunction(()=>[...document.querySelectorAll('img.leaflet-tile')].every(i=>i.complete&&i.naturalWidth>0),null,{timeout:60000});
   check(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),engine+'/'+width+' no page overflow');
   await page.screenshot({path:'.cache/qa/catalog-expansion/result-'+engine+'-'+width+'.png'});
  }
 }
 check(!errors.length,'no application page exceptions');return{passed:true,checks,route_mocks:false,scope:'two real committed results with different uncalibrated casualty models'};
}
