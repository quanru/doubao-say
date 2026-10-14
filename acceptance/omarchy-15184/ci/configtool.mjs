// Real Qt widgets discovered read-only through AT-SPI; QMP clicks/keys; no AI.
import {execFileSync} from 'node:child_process';
import {readFileSync,writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
const root=process.env.ACCEPTANCE_ROOT,out=resolve(root,'review-artifacts');
const {agentForComputer}=await import(resolve(root,'work/midscene/packages/computer/dist/es/index.mjs'));
const guest=(...a)=>execFileSync('bash',[resolve(root,'ci/guest.sh'),...a],{cwd:root,encoding:'utf8',timeout:30000}).trim();
const socket=readFileSync(resolve(root,'work/session-state'),'utf8').trim().split('\n')[1];
const key=(...keys)=>execFileSync('python3',[resolve(root,'scripts/qmp-key.py'),socket,...keys,'--disposable-vm'],{encoding:'utf8',timeout:10000});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let seq=0,agent;const results=[];
const snapshot=()=>JSON.parse(guest('snapshot',`gui-state-${seq++}`));
const identity=s=>s.processes.map(p=>[p.pid,p.start_ticks,p.comm]).sort().toString();
const methods=s=>s.info.data[1].map(x=>x[0]);
function target(selector){return JSON.parse(guest('configtool-target',selector,`gui-target-${seq++}`));}
async function click(selector){const t=target(selector);execFileSync('python3',[resolve(root,'scripts/qmp-click.py'),socket,String(t.x),String(t.y),'--disposable-vm'],{timeout:10000});await sleep(250);return t;}
async function evidence(name){guest('screenshot',name);await agent.recordToReport(name,{content:'真实 Qt 配置工具；AT-SPI 只读定位，QMP 鼠标和键盘操作；截图用于复核，未用模型判定。'});}
try{
 agent=await agentForComputer({headless:false,keepXvfbAliveUntilProcessExit:true,generateReport:true,reportFileName:'omarchy-15184-configtool-no-model'});
 guest('focus');await sleep(300);
 const baseline=snapshot(),ids=identity(baseline),original=methods(baseline),textBefore=guest('committed-text');
 // Make the GUI search field receive Latin text using a real in-app key.
 if(baseline.active==='2'){key('shift');await sleep(500);}
 if(snapshot().active!=='1')throw Error('Latin input context was not established for GUI search');
 if(JSON.stringify(original)!==JSON.stringify(['keyboard-us','pinyin']))throw Error('Require original exact keyboard-us + pinyin list');
 async function expect(expected){let s;for(let j=0;j<40;j++){s=snapshot();if(identity(s)!==ids)throw Error('Shell/indicator/fcitx restarted during GUI test');if(JSON.stringify(methods(s))===JSON.stringify(expected))return s;await sleep(100);}throw Error('GUI Apply did not produce exact expected method list: '+JSON.stringify(s));}
 guest('configtool');await sleep(1800);target('dump');await evidence('gui-initial');
 // Disable the language filter in the actual GUI and enter the exact search text.
 const language=target('language');if(language.node.checked)await click('language');
 await click('search');key('ctrl','a');for(const k of ['p','i','n','y','i','n'])key(k);
 await sleep(400);await evidence('gui-filter-pinyin');
 for(let i=0;i<3;i++){
  const round=i+1;
  const removeSelection=await click('current-pinyin');await click('remove');await evidence(`gui-${round}-remove-before-apply`);
  await click('apply');const removed=await expect(['keyboard-us']);await sleep(700);await evidence(`gui-${round}-removed`);guest('resource-sample',`gui-${round}-single-method-resource`);
  const addSelection=await click('available-pinyin');await click('add');await evidence(`gui-${round}-add-before-apply`);
  await click('apply');const restored=await expect(original);await sleep(700);await evidence(`gui-${round}-restored`);
  results.push({round,status:'OPERATIONS_PASS_VISUAL_REVIEW_PENDING',removeSelection,addSelection,removed,restored,processesUnchanged:true,controllerWrites:false});
 }
 guest('focus');let s=snapshot();if(s.active!=='2'){key('meta_l','i');await sleep(500);}s=snapshot();if(s.current!=='pinyin'||s.active!=='2')throw Error('Restored exact Pinyin engine is not usable');
 for(const k of ['n','i','h','a','o','spc','ret'])key(k);await sleep(500);const textAfter=guest('committed');if((textAfter.match(/你好/g)||[]).length!==(textBefore.match(/你好/g)||[]).length+1)throw Error('No fresh Chinese commit after GUI restoration');await expect(original);await evidence('gui-final-restored-pinyin');
 results.push({case:'restore-original-list-and-compose',status:'PASS',original,processesUnchanged:true,committedBefore:textBefore,committedAfter:textAfter});
}catch(error){results.push({status:'BLOCKED_OR_FAILED',message:String(error)});process.exitCode=1;try{guest('screenshot','gui-failure');guest('configtool-target','dump','gui-failure');}catch{}}
finally{writeFileSync(resolve(out,'gui-results.json'),JSON.stringify(results,null,2));if(agent)await agent.destroy();}
