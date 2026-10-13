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
 if(initial.active!=='2'){key('shift');await sleep(700);}
 if(stable().active!=='2')throw Error('Configured Shift did not activate Pinyin');
 for(const k of ['n','i','h','a','o','spc','ret'])key(k);
 await sleep(700);guest('committed');guest('screenshot','success-composition');
 await agent.aiAssert('This is a real Omarchy desktop. The focused terminal visibly contains committed Chinese text (你好 or another Han-character Pinyin candidate), and the input-method indicator is visible in the top bar.');
 const roi=await agent.aiQuery('Return JSON {x:number,y:number,width:number,height:number} in screenshot pixels for a tight rectangle containing only the top-bar input-method text label. Exclude the clock, mouse cursor and other icons. Do not choose the terminal. Screen is 1280 by 800.');
 const box=['x','y','width','height'].map(k=>Math.round(roi[k]));
 if(box.some(v=>!Number.isFinite(v)) || box[2]<4 || box[2]>256 || box[3]<4 || box[3]>100)throw Error('Invalid indicator ROI');
 writeFileSync(resolve(out,'roi.json'),JSON.stringify({box,source:'Midscene localization; human review required'},null,2));
 guest('template','active',...box.map(String));
 key('shift');await sleep(800);if(stable().active!=='1')throw Error('Shift did not switch to Latin');
 await agent.aiAssert('The top-bar input-method indicator now displays the Latin/direct-input state, different from the previous Chinese input state.');
 guest('template','inactive',...box.map(String));
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
  await agent.aiAssert('The real Fcitx configuration list has only Keyboard - English (US), without Pinyin. The keyboard/input-method text indicator in the Omarchy top bar is hidden, because only one keyboard layout and one input method remain. No stale EN, en or Chinese input-method label remains.');
  await agent.aiAct('In the real Fcitx 5 Configuration window add the Pinyin input method to the current group, alongside Keyboard - English (US). If needed disable Only Show Current Language, search Pinyin, select it and confirm. Click Apply to save. Do not restart Fcitx or the desktop shell.');
  await sleep(5000);const added=stable();if(!JSON.stringify(added.info).includes('pinyin'))throw Error('Pinyin missing after GUI addition');
  guest('screenshot',`success-config-add-${round}`);
  await agent.aiAssert('Pinyin is visible in the real Fcitx input-method list, and the Omarchy top-bar input-method indicator is present and reflects the available methods.');
  results.push({trial:`config-round-${round}`,status:'GUI_LIST_AND_VISUAL_CHECK_PASSED',shellUnchanged:true,observationWindowMs:5000});
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
