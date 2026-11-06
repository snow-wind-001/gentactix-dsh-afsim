/** Opt-in real unit Agent and process execution after built-UI conversions. */
import fs from 'node:fs';
import {createRequire} from 'node:module';
if(!process.argv.includes('--live'))throw Error('Actual model/AFSIM calls require --live');
const require=createRequire(fs.realpathSync(process.argv[2]));const {chromium}=require('playwright-core');
const root='.cache/qa/formation-ui-2026-11-02',tag=process.argv[3]?.startsWith('--')?'actual-next':process.argv[3]??'actual-next',out=`${root}/${tag}`;
if(!/^[a-z0-9-]+$/.test(tag))throw Error('Invalid evidence tag');
if(fs.existsSync(out))throw Error('Preserve actual run; inspect instead of repeating');fs.mkdirSync(out);
const cases=JSON.parse(fs.readFileSync(`${root}/built-final/cases.json`)),api='http://127.0.0.1:19214/api',checks=[],errors=[];
const save=(n,v)=>fs.writeFileSync(`${out}/${n}.json`,JSON.stringify(v,null,2));
const check=(v,s)=>{if(!v)throw Error(s);checks.push(s);};
const call=async(method,path,value)=>{const r=await fetch(api+path,{method,headers:{'Content-Type':'application/json'},body:value===undefined?undefined:JSON.stringify(value)});if(!r.ok)throw Error(`${r.status}: ${await r.text()}`);return r.json();};
const get=p=>call('GET',p),browser=await chromium.launch({channel:'chrome',headless:true});
let page;
try{
    for(const engine of ['afsim','narrative']){
        const sid=cases[engine].session_id,base='/sessions/'+sid,q=await get(base+'/commands');
        const expectedTurn=q.turn+1;
        const task=(await get(base+'/force-organization/tasks')).rows[0];
        const members=(await get(base+'/force-organization/tasks?kind=members&task_id='+task.id)).rows;
        check(members.length===1&&members[0].executions===q.turn,engine+' original task has continuous inherited deliveries');
        const native=q.units.find(u=>u.present&&u.name==='第90师');
        check(q.unit_agents.length===1&&q.unit_agents[0]===native.id,engine+' Native unit policy retained through UI conversions');
        const excluded=new Set([...members.map(m=>m.unit_id),native.id]);
        check([...excluded].every(id=>q.units.some(u=>u.present&&u.id===id)),engine+' task and Agent resolved against current IDs');
        await call('PUT',base+'/commands',{expected_turn:q.turn,revision:q.revision,world_version:q.world_version,control_team:'red',director:true,no_fire:true,
            unit_agents:q.unit_agents,orders:q.units.filter(u=>u.available&&!excluded.has(u.id)).map(u=>({unit_id:u.id,action:'hold',duration:'next'})),
            intent:'实体分合兵界面后的真实运行验收：第90师原生Agent明确hold；保留原持续任务，其余人工待命；保留所有旧损伤，不新增交战。'});
        const before=(await get(base+'/export')).session;save(engine+'-before',before);
        page=await browser.newPage({viewport:{width:1440,height:1000}});page.on('pageerror',e=>errors.push(String(e)));
        await page.addInitScript(()=>window.gentactix={backendUrl:'http://127.0.0.1:19214'});
        await page.goto('http://127.0.0.1:19216/');await page.getByRole('tab',{name:/已保存战局/}).click();
        await page.locator(`[data-session-id="${sid}"] .open-battle`).click();await page.getByTestId('map-unit-locator').waitFor();
        const reply=page.waitForResponse(r=>r.url().endsWith(base+'/next')&&r.request().method()==='POST',{timeout:900000});
        const started=Date.now();console.log('Starting actual built UI round',engine,sid);
        await page.getByRole('button',{name:/推进一轮/}).first().click();
        const response=await reply;check(response.status()===200,engine+' actual next returned200: '+(response.status()!==200?await response.text():''));
        const publicReply=await response.json();save(engine+'-next-meta',publicReply.engine_meta);
        await page.locator('.workspace-clock b').filter({hasText:new RegExp('^T\\+'+expectedTurn+'$')}).waitFor({timeout:10000});
        const after=(await get(base+'/export')).session;save(engine+'-after',after);
        check(after.turn_count===expectedTurn&&after.war_state.simulation_clock.elapsed_seconds-before.war_state.simulation_clock.elapsed_seconds===900,engine+' one900second turn');
        check(after.war_state.formation_registry.transactions.length===2,engine+' runtime retains both UI conversions');
        const old=new Map([...before.war_state.red_units,...before.war_state.blue_units].map(u=>[u.name,u]));
        check([...after.war_state.red_units,...after.war_state.blue_units].every(u=>JSON.stringify(u.personnel)===JSON.stringify(old.get(u.name).personnel)),engine+' no artificial personnel replenishment or losses');
        check(after.war_state.blue_units[0].formation.reload_remaining_s===0,engine+' prior blue firing cooldown cleared');
        if(engine==='afsim')check(after.war_state.afsim.returncode===0&&after.war_state.afsim.effects_source==='afsim-native-teaching-1','actual AFSIM native process succeeded');
        else check(after.war_state.dsh_execution.effects_source==='dsh_model_estimate'&&!after.war_state.afsim,'actual DSH effects admitted through existing tools');
        const decisions=after.trajectory.at(-1).decisions.filter(d=>d.source==='native_unit_agent');
        check(decisions.length===1&&decisions[0].unit_id===native.id&&decisions[0].action==='hold',engine+' one genuine Native unit decision');
        const currentMembers=(await get(base+'/force-organization/tasks?kind=members&task_id='+task.id)).rows;
        check(currentMembers.length===1&&currentMembers[0].executions===expectedTurn,engine+' merged current task actor receives one more delivery');
        for(const [unit,binding] of Object.entries(before.command_state.agent_sessions))check(after.command_state.agent_sessions[unit]?.session_id===binding.session_id,engine+' same Native unit binding continues after cold restore');
        check(JSON.stringify(after.history.slice(1))===JSON.stringify(before.history)&&JSON.stringify(after.trajectory.slice(0,-1))===JSON.stringify(before.trajectory),engine+' original history retained while new turn appended');
        await page.screenshot({path:`${out}/${engine}-after.png`});
        save(engine+'-result',{passed:true,session_id:sid,turn:expectedTurn,seconds:(Date.now()-started)/1000,native_decisions:1,task_executions:expectedTurn});
        console.log('PASS actual built UI',engine,'T'+expectedTurn,Math.round((Date.now()-started)/1000)+'s');await page.close();page=null;
    }
    check(!errors.length,'no application exceptions');save('result',{passed:true,checks,count:checks.length,errors,
        scope:'One real post-conversion turn per backend in estimated QA scenario; not full history or effect calibration'});
}catch(error){save('result',{passed:false,error:String(error),checks,errors});if(page)await page.screenshot({path:`${out}/failure.png`});throw error;}
finally{await browser.close();}
