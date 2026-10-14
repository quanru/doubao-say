import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync, mkdirSync, copyFileSync } from 'node:fs';
import { resolve } from 'node:path';
const root=process.env.ACCEPTANCE_ROOT;if(!root)throw Error('Missing root');
const out=resolve(root,'review-artifacts');
const {agentForComputer,ObservationFrameSource}=await import(resolve(root,'work/midscene/packages/computer/dist/es/index.mjs'));
const {basename}=await import('node:path');
const guest=(...args)=>execFileSync('bash',[resolve(root,'ci/guest.sh'),...args],{cwd:root,encoding:'utf8',timeout:30000}).trim();
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const state=readFileSync(resolve(root,'work/session-state'),'utf8').trim().split('\n');
const key=(...keys)=>execFileSync('python3',[resolve(root,'scripts/qmp-key.py'),state[1],...keys,'--disposable-vm'],{encoding:'utf8',timeout:10000});
const snapshot=name=>JSON.parse(guest('snapshot',name));
const identity=s=>s.processes.map(p=>[p.pid,p.start_ticks,p.comm]).sort().toString();
let agent;const results=[];
try {
 agent=await agentForComputer({headless:false,keepXvfbAliveUntilProcessExit:true,generateReport:true,observationFrameSource:async()=>ObservationFrameSource.start({command:'bash',args:[resolve(root,'ci/guest.sh'),'native-source']}),reportFileName:'omarchy-15184-real-desktop'});
 await sleep(2000);guest('focus');await sleep(500);
 const initial=snapshot('ui-initial');const ids=identity(initial);
 let observation=0;const stable=()=>{const s=snapshot(`observation-${observation++}`);if(identity(s)!==ids)throw Error('Shell/fcitx/indicator process changed during measurement');return s;};
 try {
 // AltTriggerKeys can only return to an engine after leaving it with Shift.
 // Initial engine selection uses the actual compositor shortcut via QMP.
 if(initial.active!=='2'){key('meta_l','i');await sleep(700);}
 snapshot('engine-selected-before-shift-tests');
 if(stable().active!=='2')throw Error('Initial QMP Super+I did not select Pinyin');
 for(const k of ['n','i','h','a','o','spc','ret'])key(k);
 await sleep(700);guest('committed');guest('screenshot','success-composition');
 await agent.aiAssert('The focused terminal visibly contains committed Chinese text 你好, and the small text 拼 is visible in the desktop top-right bar.');
 const located=await agent.aiLocate('The small input-method text 拼 in the desktop top-right bar, immediately left of the next icon. Locate the text itself.');
 const center=located.center;
 if(!center || center.some(v=>!Number.isFinite(v)) || center[0]<1000 || center[0]>1190 || center[1]<0 || center[1]>26)throw Error('Invalid native-pixel label localization');
 const box=[Math.round(center[0])-18,0,36,26];
 writeFileSync(resolve(out,'roi.json'),JSON.stringify({box,located,source:'Midscene aiLocate screenshot-pixel center; padded label ROI; raw whole-bar frames retained'},null,2));
 guest('template','active',...box.map(String));
 key('shift');await sleep(800);if(stable().active!=='1')throw Error('Shift did not switch to Latin');
 await agent.aiAssert('The desktop top-right bar now displays the small text EN in place of the previous 拼 text.');
 guest('template','inactive',...box.map(String));
 guest('validate-templates');
 for(let i=0;i<40;i++){
  guest('focus');await sleep(150+((i*137)%500));
  const trial=`${i<20?'switch':'quick'}${String(i%20).padStart(2,'0')}`;
  guest('input-start',trial);
  let ready=false;for(let j=0;j<40;j++){try{guest('ready',trial);ready=true;break;}catch{await sleep(50);}}
  if(!ready)throw Error('Guest input reader did not become ready');
  const observer=await agent.startObserving({captureMode:'source',maxFrames:1000,watchdogMs:10000});
  await sleep(200);
  const holdMs=i<20?80:5;
  execFileSync('python3',[resolve(root,'scripts/qmp-key.py'),state[1],'shift','--hold-ms',String(holdMs),'--disposable-vm'],{timeout:10000});
  await sleep(1300);
  const input=JSON.parse(guest('input-end',trial));
  for(const e of input.events)observer.recordEvent({name:e.value===1?'keydown':e.value===0?'keyup':'repeat',timing:{clockId:input.clockId,kind:'input-event',startMs:(e.ns-1000)/1e6,endMs:(e.ns+1000)/1e6}});
  const observation=await observer.stop();
  const record=await observation.exportRecord();
  const dest=resolve(out,'observations',trial);mkdirSync(resolve(dest,'images'),{recursive:true});
  for(const frame of record.frames){const file=basename(frame.path);copyFileSync(frame.path,resolve(dest,'images',file));frame.path=`images/${file}`;}
  writeFileSync(resolve(dest,'observation.json'),JSON.stringify({...record,requestedHoldMs:holdMs},null,2));
  let capturePids;for(let j=0;j<20;j++){capturePids=JSON.parse(guest('native-status')).capture_pids;if(!capturePids.length)break;await sleep(50);}
  writeFileSync(resolve(dest,'cleanup.json'),JSON.stringify({remainingCapturePids:capturePids},null,2));
  if(capturePids.length)throw Error('Native capture producer remained after observation stop');
  if(i===0 || i===20){try{await observation.aiAssert('The input-method text in the top-right desktop bar changes from EN to 拼 during this recorded window.');}catch(error){results.push({trial:`${trial}-visual`,status:'VISUAL_ASSERTION_FAILED_REQUIRES_REVIEW',message:String(error)});process.exitCode=1;}}
  await observation.dispose();
  const s=stable();const expected=i%2===0?'2':'1';
  if(s.active!==expected)throw Error(`${trial}: wrong actual input state`);
  results.push({trial,expectedState:expected,requestedHoldMs:holdMs,frames:record.frames.length,droppedFrames:record.droppedFrames,status:'TIMING_PENDING_PIXEL_REVIEW'});
 }
 guest('screenshot','success-repeat-switch');
 } catch(error) {
  results.push({trial:'in-app-switching',status:'FAILED_OR_INCONCLUSIVE',message:String(error)});process.exitCode=1;
  try{guest('screenshot','failure-switching');}catch{}
 }
 // Continue the independent list-change case even when switching cannot complete.
 // Each list mutation is performed through the real configtool, not D-Bus setters.
 guest('configtool');await sleep(1000);
 for(let round=0;round<3;round++){
  await agent.aiTap('Input Method tab in the Fcitx 5 Configuration window');
  await agent.aiTap('Pinyin row in the left Current Input Method list');
  await agent.aiTap('RIGHT-pointing arrow between Current Input Method and Available Input Method, to remove the selected Pinyin');
  await agent.aiTap('Apply button at the bottom of the configuration window');
  await sleep(5000);const removed=stable();if(JSON.stringify(removed.info).includes('pinyin'))throw Error('Pinyin still registered after GUI removal');
  guest('screenshot',`success-config-remove-${round}`);
  let removedVisual=true;try{await agent.aiAssert('The left Current Input Method list has only Keyboard - English (US), without Pinyin. The desktop top-right bar has no EN or 拼 text.');}catch(error){removedVisual=false;results.push({trial:`config-remove-visual-${round}`,status:'VISUAL_ASSERTION_FAILED_REQUIRES_REVIEW',message:String(error)});process.exitCode=1;}
  if(await agent.aiBoolean('Is the Only Show Current Language checkbox visibly present and checked in the Input Method tab?')) await agent.aiTap('Only Show Current Language checkbox');
  await agent.aiTap('Search Input Method text field above the right-hand Available Input Method list');
  key('ctrl','a','--hold-ms','15');await sleep(150);
  for(const k of ['p','i','n','y','i','n']){key(k,'--hold-ms','15');await sleep(120);}
  await sleep(500);guest('screenshot',`search-pinyin-${round}`);
  await agent.aiAssert('The Available Input Method search field contains exactly pinyin, and a selectable Pinyin row is visible in the right list.');
  await agent.aiTap('Pinyin row in the right Available Input Method list');
  await agent.aiTap('LEFT-pointing arrow between the two lists, to add Pinyin');
  await agent.aiTap('Apply button at the bottom of the configuration window');
  await sleep(5000);const added=stable();if(!JSON.stringify(added.info).includes('pinyin'))throw Error('Pinyin missing after GUI addition');
  guest('screenshot',`success-config-add-${round}`);
  let addedVisual=true;try{await agent.aiAssert('Pinyin appears in the left Current Input Method list alongside Keyboard - English (US), and the small EN text is visible in the desktop top-right bar, outside the configuration window.');}catch(error){addedVisual=false;results.push({trial:`config-add-visual-${round}`,status:'VISUAL_ASSERTION_FAILED_REQUIRES_REVIEW',message:String(error)});process.exitCode=1;}
  results.push({trial:`config-round-${round}`,status:removedVisual&&addedVisual?'GUI_LIST_AND_VISUAL_CHECK_PASSED':'GUI_LIST_VERIFIED_VISUAL_REVIEW_REQUIRED',removedVisual,addedVisual,shellUnchanged:true,observationWindowMs:5000});
 }
 const final=stable();
 if(JSON.stringify(final.info)!==JSON.stringify(initial.info))throw Error('GUI method-list restoration differs from initial list');
 guest('screenshot','success-gui-restored');
 results.push({trial:'gui-list-restore',status:'PASSED'});
} catch(error){
 results.push({status:'BLOCKED_OR_FAILED',message:String(error)});process.exitCode=1;
 try{guest('screenshot','failure-ui');}catch{}
} finally{
 writeFileSync(resolve(out,'ui-results.json'),JSON.stringify(results,null,2));
 if(agent)await agent.destroy();
}
