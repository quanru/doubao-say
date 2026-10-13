import { agentForComputer } from '@midscene/computer';
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
const root=process.env.ACCEPTANCE_ROOT;if(!root)throw Error('Missing root');
const out=resolve(root,'review-artifacts');
const guest=(...args)=>execFileSync('bash',[resolve(root,'ci/guest.sh'),...args],{cwd:root,encoding:'utf8',timeout:30000}).trim();
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const state=readFileSync(resolve(root,'work/session-state'),'utf8').trim().split('\n');
const key=(...keys)=>execFileSync('python3',[resolve(root,'scripts/qmp-key.py'),state[1],...keys,'--disposable-vm'],{encoding:'utf8',timeout:10000});
const snapshot=name=>JSON.parse(guest('snapshot',name));
const identity=s=>s.processes.map(p=>[p.pid,p.start_ticks,p.comm]).sort().toString();
let agent;const results=[];
try {
 agent=await agentForComputer({headless:false,keepXvfbAliveUntilProcessExit:true,generateReport:true,reportFileName:'omarchy-15184-real-desktop'});
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
 for(let i=0;i<20;i++){
  guest('focus');await sleep(150+((i*137)%500));
  const trial=`switch${String(i).padStart(2,'0')}`;
  guest('capture',trial,...box.map(String));
  let ready=false;for(let j=0;j<40;j++){try{guest('ready',trial);ready=true;break;}catch{await sleep(50);}}
  if(!ready)throw Error('Guest capture did not become ready');
  key('shift');await sleep(3300);
  const s=stable();const expected=i%2===0?'2':'1';
  if(s.active!==expected)throw Error(`${trial}: wrong actual input state`);
  results.push({trial,expectedState:expected,status:'TIMING_PENDING_PIXEL_REVIEW'});
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
  await agent.aiAct('In the real Fcitx 5 Configuration window, remove only Pinyin from the current input-method list. Keep Keyboard - English (US). Click Apply to save. Do not restart Fcitx or the desktop shell.');
  await sleep(5000);const removed=stable();if(JSON.stringify(removed.info).includes('pinyin'))throw Error('Pinyin still registered after GUI removal');
  guest('screenshot',`success-config-remove-${round}`);
  let removedVisual=true;try{await agent.aiAssert('The left Current Input Method list has only Keyboard - English (US), without Pinyin. The desktop top-right bar has no EN or 拼 text.');}catch(error){removedVisual=false;results.push({trial:`config-remove-visual-${round}`,status:'VISUAL_ASSERTION_FAILED_REQUIRES_REVIEW',message:String(error)});process.exitCode=1;}
  await agent.aiAct('If Only Show Current Language is checked, uncheck it. Otherwise do nothing. Do not scroll or change input methods.');
  await agent.aiTap('Search Input Method text field above the right-hand Available Input Method list');
  key('ctrl','a');await sleep(150);
  for(const k of ['p','i','n','y','i','n']){key(k);await sleep(120);}
  await sleep(500);guest('screenshot',`search-pinyin-${round}`);
  await agent.aiAct('The Available Input Method list is filtered by the search text pinyin. Select Pinyin in the right-hand list, click the LEFT-pointing arrow between the lists to add it to Current Input Method alongside Keyboard - English (US), then click Apply. Do not scroll, restart Fcitx or restart the shell.');
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
