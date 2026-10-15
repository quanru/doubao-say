// Actual QMP input + deterministic Midscene screenshots. No inference or stubs.
import {execFileSync} from 'node:child_process';
import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {resolve} from 'node:path';
import {windowPointToOutput} from './coordinates.mjs';
const root=process.env.ACCEPTANCE_ROOT,out=resolve(root,'review-artifacts');
const {agentForComputer}=await import(resolve(root,'work/midscene/packages/computer/dist/es/index.mjs'));
const guest=(...args)=>execFileSync('bash',[resolve(root,'ci/guest.sh'),...args],{cwd:root,encoding:'utf8',timeout:45000}).trim();
const socket=readFileSync(resolve(root,'work/session-state'),'utf8').trim().split('\n')[1];
const script=(name,...args)=>execFileSync('python3',[resolve(root,'scripts',name),socket,...args,'--disposable-vm'],{encoding:'utf8',timeout:15000});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const state=()=>JSON.parse(guest('state'));
const key=(...args)=>script('qmp-key.py',...args);
function point(s,offsetY=0){
 const g=JSON.parse(guest('geometry')),{x,y}=windowPointToOutput(s,g,offsetY);
 return {x,y,geometry:g,source:s};
}
const geometryTrace=[];let viewportSequence=0;
function saveGeometry(entry){geometryTrace.push(entry);writeFileSync(resolve(out,'geometry-trace.json'),JSON.stringify(geometryTrace,null,2));}
async function stableGeometry(){
 let previous,stable=0;
 for(let i=0;i<16;i++){
  const observed=state(),geometry=JSON.parse(guest('geometry'));
  const signature=JSON.stringify({x:observed.x,y:observed.y,width:observed.width,height:observed.height,popup:observed.popup,geometry});
  stable=signature===previous?stable+1:0;previous=signature;
  if(stable>=2)return {observed,geometry};
  await sleep(150);
 }
 throw Error('Gallery geometry did not stabilize');
}
async function ensureVisible(){
 for(let attempt=0;attempt<18;attempt++){
  const {observed:s,geometry:g}=await stableGeometry(),m=g.monitor,c=g.client;
  const top=(c.at[1]+s.y-m.y)*m.scale,bottom=top+s.height*m.scale;
  // Leave room for the real popup below the trigger, not merely its center.
  if(top>=90 && bottom<=m.height-180){saveGeometry({operation:'visible-stable',observed:s,geometry:g});return s;}
  if(s.popup)throw Error('Open popup trigger outside safe view; refusing blind input');
  const x=Math.round((c.at[0]+c.size[0]-28-m.x)*m.scale),y=Math.round((c.at[1]+c.size[1]/2-m.y)*m.scale);
  if(x<0||x>=m.width||y<0||y>=m.height)throw Error('ScrollView wheel point outside output');
  const id=`viewport-${++viewportSequence}`,direction=bottom>m.height-180?'down':'up';
  guest('screenshot',id+'-before');
  script('qmp-wheel.py','move','--x',String(x),'--y',String(y));await sleep(150);wheel(direction);await sleep(300);
  guest('screenshot',id+'-after');
  saveGeometry({operation:'real-scrollview-wheel',id,direction,x,y,before:s,geometry:g,after:state()});
  await agent.recordToReport(id+' real ScrollView wheel '+direction,{content:'Viewport correction through real QMP input; no direct scrolling or product state assignment.'});
 }
 throw Error('Could not bring real dropdown into safe view within 18 wheel events');
}
async function move(){
 for(let attempt=0;attempt<4;attempt++){
  const s=await ensureVisible(),p=point(s);script('qmp-wheel.py','move','--x',String(p.x),'--y',String(p.y));await sleep(250);
  const {observed}=await stableGeometry(),now=point(observed);
  saveGeometry({operation:'move-and-hit-check',point:p,afterMove:observed,currentPoint:now});
  if(observed.pointerHover && now.x===p.x && now.y===p.y){
   writeFileSync(resolve(out,'latest-input-mapping.json'),JSON.stringify({point:p,afterMove:observed},null,2));return observed;
  }
 }
 throw Error('Pointer hit and stable target position could not be established');
}
async function click(){const s=await move(),p=point(s);script('qmp-click.py',String(p.x),String(p.y));}
async function openMode(mode,tag){
 script('qmp-wheel.py','move','--x','0','--y','0');
 guest('mode',mode,...(tag?[tag]:[]));guest('focus-gallery');await ensureVisible();
}
const wheel=d=>script('qmp-wheel.py',d);
const results=[];let agent,n=0;let suiteComplete=false;
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
   await openMode(mode);n=0;
   let s=await capture(mode,'diagnostic-initial',{});
   await move(s);wheel('down');s=await capture(mode,'diagnostic-wheel',{});
   await click(s);s=await capture(mode,'diagnostic-click-open',{});
   key('ret');s=await capture(mode,'diagnostic-enter',{});
   findings.push({mode,color:s.colorProbe,focus:s.focusChain,windowActive:s.windowActive,value:s.value,popup:s.popup});
  }
  writeFileSync(resolve(out,'diagnostic-findings.json'),JSON.stringify(findings,null,2));
  throw Error('DIAGNOSTIC ONLY: Color resolution and focus captured; full acceptance not run');
 }
 // Diagnose the original QMP route BEFORE creating any additional virtual device.
 await openMode('candidate','hid-diagnostic');n=0;
 let ds=await capture('hid-diagnostic','before-wheel-left',{});await move(ds);
 const probeBefore=JSON.parse(guest('probe','start'));wheel('left');
 const probeAfter=JSON.parse(guest('probe','end'));
 await capture('hid-diagnostic','after-wheel-left',{});
 writeFileSync(resolve(out,'qmp-horizontal-actual-events.json'),JSON.stringify({before:probeBefore,after:probeAfter,interpretation:'Diagnostic only. Classify actual EV_REL codes; never assume QMP button name proves axis.'},null,2));
 writeFileSync(resolve(out,'uinput-device.json'),guest('probe','create'));
 for(const mode of ['baseline','candidate']){
  await openMode(mode);n=0;
  let s=await capture(mode,'initial-unmatched',{value:'Clock',popup:false});
  if(!s.colorProbe.unqualifiedPalette || !s.colorProbe.qualifiedPalette)throw Error('Runtime Color palette precondition failed');
  await move(s);wheel('down');
  s=await capture(mode,'unmatched-wheel-down',{value:mode==='candidate'?'omarchy.clock':'Clock',popup:false});
  if(mode==='baseline'){
   // Establish matched selection via the real popup before closed-wheel comparison.
   await click(s);await sleep(300);key('ret');
   s=await capture(mode,'click-keyboard-first',{value:'omarchy.clock',popup:false});
  }
  for(const [dir,want,label] of [['down','omarchy.weather','down-middle'],['down','omarchy.power','down-last'],['down','omarchy.power','clamp-last'],['up','omarchy.weather','up-middle'],['up','omarchy.clock','up-first'],['up','omarchy.clock','clamp-first']]){
   await move(s);wheel(dir);s=await capture(mode,label,{value:mode==='candidate'?want:'omarchy.clock',popup:false});
  }
  await click(s);s=await capture(mode,'popup-open',{value:'omarchy.clock',popup:true});
  await move(s);wheel('down');s=await capture(mode,'popup-trigger-wheel',{value:'omarchy.clock',popup:true});
  key('esc');s=await capture(mode,'escape',{value:'omarchy.clock',popup:false});
  await click(s);await sleep(250);key('down');key('ret');
  s=await capture(mode,'keyboard-select-middle',{value:'omarchy.weather',popup:false});
  await click(s);await sleep(250);key('up');key('ret');
  s=await capture(mode,'keyboard-select-first',{value:'omarchy.clock',popup:false});
  // Click the first visible option at popup-relative row center; retain image before.
  await click(s);await capture(mode,'before-option-click',{value:'omarchy.clock',popup:true});
  const freshOptionState=(await stableGeometry()).observed;
  const optionPoint=point(freshOptionState,freshOptionState.height/2+freshOptionState.row/2+4);script('qmp-click.py',String(optionPoint.x),String(optionPoint.y));
  s=await capture(mode,'option-click',{value:'omarchy.clock',popup:false});
  for(const [dir,value] of [['left',-1],['right',1]]){
   await move(s);guest('probe','start');guest('probe','horizontal',String(value));
   const proof=JSON.parse(guest('probe','end'));
   writeFileSync(resolve(out,`${mode}-horizontal-${dir}-events.json`),JSON.stringify(proof,null,2));
   const device=proof.devices.find(d=>d.name==='Omarchy13930 horizontal test mouse');
   if(!device || !proof.events.some(e=>e.device===device.path && e.type===2 && e.code===6 && e.value===value) || proof.events.some(e=>e.type===2 && e.code===8 && e.value!==0))throw Error('Horizontal evdev delivery not proven, or contaminated by vertical events');
   s=await capture(mode,`horizontal-${dir}-rel-hwheel-verified`,{value:'omarchy.clock',popup:false});
  }
 }
 suiteComplete=true;
}catch(e){writeFileSync(resolve(out,'failure.json'),JSON.stringify({error:String(e),stack:e.stack},null,2));process.exitCode=1;try{guest('screenshot','failure');if(agent)await agent.recordToReport('FAILED: '+String(e));}catch{}}
finally{
 writeFileSync(resolve(out,'coverage.json'),JSON.stringify({complete:suiteComplete,core:suiteComplete?'automated checks complete; independent image review pending':'FAILED_OR_INCOMPLETE',horizontal:suiteComplete?'Linux uinput REL_HWHEEL delivered and observed on evdev for both baseline/head; no vertical contamination':'FAILED_OR_INCOMPLETE',fine_grained_touchpad:'NOT COVERED; discrete virtual mouse is not a touchpad',model_calls:0,scope:'real shared-component dev gallery; not business-panel E2E'},null,2));
 if(agent)await agent.destroy();
}
