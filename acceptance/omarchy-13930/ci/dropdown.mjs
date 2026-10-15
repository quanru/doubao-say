// Actual QMP input + deterministic Midscene screenshots. No inference or stubs.
import {execFileSync} from 'node:child_process';
import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {resolve} from 'node:path';
const root=process.env.ACCEPTANCE_ROOT,out=resolve(root,'review-artifacts');
const {agentForComputer}=await import(resolve(root,'work/midscene/packages/computer/dist/es/index.mjs'));
const guest=(...args)=>execFileSync('bash',[resolve(root,'ci/guest.sh'),...args],{cwd:root,encoding:'utf8',timeout:45000}).trim();
const socket=readFileSync(resolve(root,'work/session-state'),'utf8').trim().split('\n')[1];
const script=(name,...args)=>execFileSync('python3',[resolve(root,'scripts',name),socket,...args,'--disposable-vm'],{encoding:'utf8',timeout:15000});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const state=()=>JSON.parse(guest('state'));
const key=(...args)=>script('qmp-key.py',...args);
const move=s=>script('qmp-wheel.py','move','--x',String(Math.round(s.x+s.width/2)),'--y',String(Math.round(s.y+s.height/2)));
const click=s=>script('qmp-click.py',String(Math.round(s.x+s.width/2)),String(Math.round(s.y+s.height/2)));
const wheel=d=>script('qmp-wheel.py',d);
const results=[];let agent,n=0;
async function capture(mode,label,expect){
 await sleep(400);const observed=state(),id=`${mode}-${String(++n).padStart(2,'0')}-${label}`;
 guest('screenshot',id);guest('desktop-state',id);
 await agent.recordToReport(id,{content:JSON.stringify({id,observed,expected:expect,actionSource:'real QMP; state from read-only gallery observer; independent screenshot review required'})});
 const pass=Object.entries(expect).every(([k,v])=>observed[k]===v);
 results.push({id,mode,label,observed,expected:expect,pass,screenshot:`guest/${id}.png`});
 writeFileSync(resolve(out,'steps.json'),JSON.stringify(results,null,2));
 if(!pass)throw Error(`${id}: expected ${JSON.stringify(expect)}, actual ${JSON.stringify(observed)}`);
 return observed;
}
try{
 mkdirSync(out,{recursive:true});
 writeFileSync(resolve(out,'qmp-schema.json'),script('qmp-wheel.py','schema'));
 agent=await agentForComputer({headless:false,keepXvfbAliveUntilProcessExit:true,generateReport:true,reportFileName:'omarchy-13930-real-gallery-no-model'});
 if(process.env.ACCEPTANCE_DIAGNOSTIC==='1') {
  const findings=[];
  for(const mode of ['baseline','candidate']){
   guest('mode',mode);n=0;
   let s=await capture(mode,'diagnostic-initial',{});
   move(s);wheel('down');s=await capture(mode,'diagnostic-wheel',{});
   click(s);s=await capture(mode,'diagnostic-click-open',{});
   key('ret');s=await capture(mode,'diagnostic-enter',{});
   findings.push({mode,color:s.colorProbe,focus:s.focusChain,windowActive:s.windowActive,value:s.value,popup:s.popup});
  }
  writeFileSync(resolve(out,'diagnostic-findings.json'),JSON.stringify(findings,null,2));
  throw Error('DIAGNOSTIC ONLY: Color resolution and focus captured; full acceptance not run');
 }
 for(const mode of ['baseline','candidate']){
  guest('mode',mode);n=0;
  let s=await capture(mode,'initial-unmatched',{value:'Clock',popup:false});
  move(s);wheel('down');
  s=await capture(mode,'unmatched-wheel-down',{value:mode==='candidate'?'omarchy.clock':'Clock',popup:false});
  if(mode==='baseline'){
   // Establish matched selection via the real popup before closed-wheel comparison.
   click(s);await sleep(300);key('ret');
   s=await capture(mode,'click-keyboard-first',{value:'omarchy.clock',popup:false});
  }
  for(const [dir,want,label] of [['down','omarchy.weather','down-middle'],['down','omarchy.power','down-last'],['down','omarchy.power','clamp-last'],['up','omarchy.weather','up-middle'],['up','omarchy.clock','up-first'],['up','omarchy.clock','clamp-first']]){
   move(s);wheel(dir);s=await capture(mode,label,{value:mode==='candidate'?want:'omarchy.clock',popup:false});
  }
  click(s);s=await capture(mode,'popup-open',{value:'omarchy.clock',popup:true});
  move(s);wheel('down');s=await capture(mode,'popup-trigger-wheel',{value:'omarchy.clock',popup:true});
  key('esc');s=await capture(mode,'escape',{value:'omarchy.clock',popup:false});
  click(s);await sleep(250);key('down');key('ret');
  s=await capture(mode,'keyboard-select-middle',{value:'omarchy.weather',popup:false});
  click(s);await sleep(250);key('up');key('ret');
  s=await capture(mode,'keyboard-select-first',{value:'omarchy.clock',popup:false});
  // Click the first visible option at popup-relative row center; retain image before.
  click(s);await capture(mode,'before-option-click',{value:'omarchy.clock',popup:true});
  script('qmp-click.py',String(Math.round(s.x+s.width/2)),String(Math.round(s.y+s.height+s.row/2+4)));
  s=await capture(mode,'option-click',{value:'omarchy.clock',popup:false});
  for(const dir of ['left','right']){move(s);wheel(dir);s=await capture(mode,`horizontal-${dir}-delivery-unverified`,{value:'omarchy.clock',popup:false});}
 }
 writeFileSync(resolve(out,'coverage.json'),JSON.stringify({core:'automated state checks complete; independent images pending',horizontal:'QMP acknowledged and no selection change; guest delivery NOT established, no coverage claim',fine_grained_touchpad:'NOT COVERED: discrete QMP buttons do not simulate high-resolution wheel',model_calls:0,scope:'real shared-component dev gallery; not business-panel E2E'},null,2));
}catch(e){writeFileSync(resolve(out,'failure.json'),JSON.stringify({error:String(e),stack:e.stack},null,2));process.exitCode=1;try{guest('screenshot','failure');if(agent)await agent.recordToReport('FAILED: '+String(e));}catch{}}
finally{if(agent)await agent.destroy();}
