// No model access: independent RegionObservation + full-screen Agent evidence.
import {execFileSync} from 'node:child_process';
import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {resolve} from 'node:path';
const root=process.env.ACCEPTANCE_ROOT,mode=process.env.OBSERVATION_MODE;
if(!['plain','pixels'].includes(mode))throw Error('Explicit observation mode required');
const tag='formal'+mode,out=resolve(root,'review-artifacts',mode==='plain'?'plain':'.');
mkdirSync(resolve(out,'versions'),{recursive:true});
const {agentForComputer,RegionObservation}=await import(resolve(root,'work/midscene/packages/computer/dist/es/index.mjs'));
const guest=(...a)=>execFileSync('bash',[resolve(root,'ci/guest.sh'),...a],{cwd:root,encoding:'utf8',timeout:30000}).trim();
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const state=readFileSync(resolve(root,'work/session-state'),'utf8').trim().split('\n');
const key=(...keys)=>execFileSync('python3',[resolve(root,'scripts/qmp-key.py'),state[1],...keys,'--disposable-vm'],{encoding:'utf8',timeout:10000});
const snapshot=name=>JSON.parse(guest('snapshot',tag+'-'+name));
const identity=s=>s.processes.map(p=>[p.pid,p.start_ticks,p.comm]).sort().toString();
const geometry={outputIndex:0,x:0,y:0,width:1280,height:28,scale:1,outputWidth:1280,outputHeight:800,transform:0};
let agent;const results=[];
async function cleanup(){let pids;for(let i=0;i<30;i++){pids=JSON.parse(guest('native-status')).capture_pids;if(!pids.length)return {remainingCapturePids:pids};await sleep(50);}throw Error('Native region producer leaked');}
try{
 agent=await agentForComputer({headless:false,keepXvfbAliveUntilProcessExit:true,generateReport:true,reportFileName:'omarchy-15184-'+mode+'-roi-no-model'});
 guest('probe-mode',tag,mode);await sleep(2000);guest('probe-health',tag);guest('focus');await sleep(500);
 const initial=snapshot('roi-initial'),ids=identity(initial);let n=0;
 const stable=()=>{const s=snapshot(`observation-${n++}`);if(identity(s)!==ids)throw Error('Processes changed');return s;};
 // Exercise all three real region lifecycles before any input trials.
 const lifecycles=[];
 for(let i=0;i<3;i++){
  const source=RegionObservation.start({command:'bash',args:[resolve(root,'ci/guest.sh'),'native-region'],geometry,maxFrames:500});
  try{for(let j=0;j<150&&!source.frames().length;j++)await sleep(20);if(!source.frames().length)throw Error('No region baseline');}
  finally{await source.stop();}
  lifecycles.push({iteration:i,frameId:source.frames()[0].frameId,...await cleanup()});
 }
 writeFileSync(resolve(out,'versions/region-lifecycle.json'),JSON.stringify(lifecycles,null,2));
 if(initial.active!=='2'){key('meta_l','i');await sleep(700);}
 if(stable().active!=='2')throw Error('Pinyin not selected');
 for(const k of ['n','i','h','a','o','spc','ret'])key(k);
 await sleep(700);guest('committed');guest('screenshot',tag+'-success-composition');
 await agent.recordToReport('真实 Pinyin 已提交中文；完整桌面截图，无模型判断');
 const box=[1137,0,36,26];
 writeFileSync(resolve(out,'roi.json'),JSON.stringify({box,measurementGeometry:geometry,source:'Fixed prior reviewed label coordinates; independently compare full/ROI pixels; no new model localization'},null,2));
 guest('template','active',...box.map(String));key('shift');await sleep(800);
 if(stable().active!=='1')throw Error('Shift did not select Latin');
 guest('template','inactive',...box.map(String));guest('validate-templates');
 mkdirSync(resolve(out,'templates'),{recursive:true});for(const [name,b64] of Object.entries(JSON.parse(guest('template-export'))))writeFileSync(resolve(out,'templates',name+'.png'),Buffer.from(b64,'base64'));
 guest('resource-sample',tag+'-active-resource');
 guest('screenshot',tag+'-success-latin');await agent.recordToReport('真实 EN 模式；独立全屏截图');
 // Prespecified 20 normal 80ms presses then 20 short 5ms presses. No adaptive repeats.
 for(let i=0;i<40;i++){
  guest('focus');await sleep(150+((i*137)%500));
  const trial=`${i<20?'switch':'quick'}${String(i%20).padStart(2,'0')}`,inputId=tag+trial,holdMs=i<20?80:5;
  guest('input-start',inputId);let ready=false;
  for(let j=0;j<40;j++){try{guest('ready',inputId);ready=true;break;}catch{await sleep(50);}}
  if(!ready)throw Error('Input reader not ready');
  const source=RegionObservation.start({command:'bash',args:[resolve(root,'ci/guest.sh'),'native-region'],geometry,maxFrames:1000});
  let input;
  try{
   for(let j=0;j<150&&!source.frames().length;j++)await sleep(20);
   if(!source.frames().length)throw Error('No region baseline');
   await sleep(200);key('shift','--hold-ms',String(holdMs));await sleep(1300);
   input=JSON.parse(guest('input-end',inputId));
  }finally{await source.stop();}
  const frames=source.frames(),dest=resolve(out,'observations',trial);mkdirSync(resolve(dest,'images'),{recursive:true});
  const record={captureMode:'source',measurementChannel:'native-region',droppedFrames:0,requestedHoldMs:holdMs,
   events:input.events.map(e=>({name:e.value===1?'keydown':e.value===0?'keyup':'repeat',timing:{clockId:input.clockId,kind:'input-event',startMs:(e.ns-1000)/1e6,endMs:(e.ns+1000)/1e6}})),
   frames:frames.map((f,j)=>{const path=`images/${String(j).padStart(4,'0')}.png`;writeFileSync(resolve(dest,path),f.png);return {frameId:f.frameId,timing:f.timing,geometry:f.geometry,path};})};
  writeFileSync(resolve(dest,'observation.json'),JSON.stringify(record,null,2));
  writeFileSync(resolve(dest,'cleanup.json'),JSON.stringify(await cleanup(),null,2));
  guest('probe-health',tag);
  const s=stable(),expected=i%2===0?'2':'1';if(s.active!==expected)throw Error(`${trial}: wrong input state`);
  guest('screenshot',`${tag}-success-${trial}`);
  await agent.recordToReport(`${trial}: QMP Shift ${holdMs}ms；ROI 原始记录 observations/${trial}/observation.json`,{content:'全屏截图在计时窗口结束后采集；不能用此截图推断 500ms。'});
  results.push({trial,expectedState:expected,requestedHoldMs:holdMs,frames:frames.length,droppedFrames:0,status:'TIMING_PENDING_PIXEL_REVIEW'});
 }
 // GUI configuration is a separately recorded three-round suite after both fixed groups.
 if(mode==='pixels'){const pd=resolve(out,'presentation');mkdirSync(pd,{recursive:true});writeFileSync(resolve(pd,'events.jsonl'),guest('probe-events',tag)+'\n');for(const [name,b64] of Object.entries(JSON.parse(guest('probe-pixels',tag))))writeFileSync(resolve(pd,name),Buffer.from(b64,'base64'));}
 writeFileSync(resolve(out,'model-usage.json'),JSON.stringify({requests:0,cost_cny:0,credentials_injected:false,remaining_unallocated_cny:10,task_limit_cny:100},null,2));
}catch(error){results.push({status:'BLOCKED_OR_FAILED',message:String(error)});process.exitCode=1;try{guest('screenshot','failure-roi');}catch{}}
finally{writeFileSync(resolve(out,'ui-results.json'),JSON.stringify(results,null,2));if(agent)await agent.destroy();}
