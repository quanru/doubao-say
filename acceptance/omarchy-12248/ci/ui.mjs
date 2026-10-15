// Deterministic QMP input and genuine Midscene full-desktop reports. No inference.
import {execFileSync} from 'node:child_process';
import {readFileSync,writeFileSync,mkdirSync} from 'node:fs';
import {resolve} from 'node:path';
const root=process.env.ACCEPTANCE_ROOT,out=resolve(root,'review-artifacts');
const {agentForComputer}=await import(resolve(root,'work/midscene/packages/computer/dist/es/index.mjs'));
const guest=(...a)=>execFileSync('bash',[resolve(root,'ci/guest.sh'),...a],{cwd:root,encoding:'utf8',timeout:30000}).trim();
const state=readFileSync(resolve(root,'work/session-state'),'utf8').trim().split('\n');
const key=(...a)=>execFileSync('python3',[resolve(root,'scripts/qmp-key.py'),state[1],...a,'--disposable-vm'],{encoding:'utf8',timeout:10000});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let agent;const results=[],events=[];
const status=()=>JSON.parse(guest('status'));
const snap=n=>JSON.parse(guest('snapshot',n));
async function capture(id,content){guest('screenshot',id);await agent.recordToReport(id,{content});events.push({id,content,time:new Date().toISOString()});}
const writers=s=>s.processes.filter(p=>p.cmd.startsWith('dd ')&&p.cmd.includes('oflag=direct'));
const readers=s=>s.processes.filter(p=>p.cmd.startsWith('dd ')&&p.cmd.includes('iflag=direct'));
async function full(v){
 guest('open');let seenRead=false,seenWrite=false,seenStage=false,done=false;const captured=new Set(),trace=[];
 for(let i=0;i<220;i++){
  const s=status();trace.push(s);let phase='starting';
  if(readers(s).length){seenRead=true;phase='read';}
  else if(writers(s).length){phase=seenRead?'write':'stage';if(seenRead)seenWrite=true;else seenStage=true;}
  else if(seenWrite&&!s.processes.length){phase='complete';done=true;}
  if(phase!=='starting'&&!captured.has(phase)){
   // Let the real stdout parser and compositor present a sampled rate.
   await sleep(1300);const observed=snap(v+'-'+phase);
   await capture(v+'-'+phase,`Observed actual ${phase} disk I/O process state. UI appearance requires independent image review; no model assertions. Process snapshot: guest/${v}-${phase}.json`);
   captured.add(phase);
  }
  if(done)break;await sleep(250);
 }
 writeFileSync(resolve(out,v+'-trace.json'),JSON.stringify(trace,null,2));
 const end=snap(v+'-full-end');if(!seenStage||!seenRead||!seenWrite||!done||end.processes.length||end.temporary_files.length)throw Error(v+': missing phase or cleanup');
 results.push({case:v+'-full',status:'OBSERVED_PENDING_VISUAL_REVIEW',phases:[...captured]});key('esc');await sleep(500);
}
async function cancel(v){
 guest('open');let staging;
 for(let i=0;i<100;i++){const s=status();if(writers(s).length===4&&!readers(s).length){staging=s;break;}await sleep(100);}
 if(!staging)throw Error(v+': staging cancellation not observed');
 await sleep(1300);staging=snap(v+'-cancel-before');if(writers(staging).length!==4||readers(staging).length)throw Error(v+': staging ended before close');
 await capture(v+'-cancel-staging','Genuine staging writers and temporary files before QMP Escape.');
 const old=staging.processes.map(p=>[p.pid,p.start_ticks].join(':'));key('esc');await sleep(500);
 let end;const cleanup=[];
 for(let i=0;i<40;i++){end=status();cleanup.push(end);if(!end.processes.length&&!end.temporary_files.length)break;await sleep(100);}
 writeFileSync(resolve(out,v+'-cancel-trace.json'),JSON.stringify({old,cleanup},null,2));
 snap(v+'-cancel-after');await capture(v+'-cancel-closed','Panel closed; process and temporary-file cleanup are independently checked.');
 if(end.processes.length||end.temporary_files.length)throw Error(v+': background process or temporary-file leak after closing');
 results.push({case:v+'-cancel',status:'PROCESS_AND_FILE_CLEANUP_CONFIRMED',old});
 await full(v+'-reopen');
}
async function picker(v){
 const rounds=[];
 for(const round of ['cold','warm','index']){
  guest('picker-start',v,round);await sleep(1800);
  await capture(`${v}-picker-${round}-open`,'Fixed local red/green/blue PNGs; selected green. Cold/warm/index-only cache states are isolated.');
  key('right');await sleep(500);
  await capture(`${v}-picker-${round}-selected`,'QMP Right selects blue; Enter result checked against exact source path.');
  key('ret');let r={};
  for(let i=0;i<50;i++){r=JSON.parse(guest('picker-result',v,round));if('exit_code' in r)break;await sleep(100);}
  if(r.exit_code!==0||r.stdout.trim()!=='/tmp/pr12248/images/c-blue.png')throw Error(v+' '+round+': unexpected actual picker result '+JSON.stringify(r));
  rounds.push(r);await sleep(300);
 }
 if(rounds.some(r=>r.index!==rounds[0].index))throw Error(v+': index changed on warm or forced-row-rebuild open');
 results.push({case:v+'-image-picker',status:'RESULTS_IDENTICAL_PENDING_VISUAL_REVIEW',rounds:['cold','warm','index']});
}
try{
 agent=await agentForComputer({headless:false,keepXvfbAliveUntilProcessExit:true,generateReport:true,reportFileName:'omarchy-12248-no-model'});
 guest('picker-prepare');
 for(const v of ['baseline','head']){
  guest('switch',v);await capture(v+'-desktop','Installed exact baseline/head file hashes saved in guest metadata.');
  await full(v);await cancel(v);await picker(v);
 }
}catch(error){results.push({status:'FAILED_OR_BLOCKED',message:String(error)});process.exitCode=1;try{await capture('failure','Failure retained; not acceptance PASS.');}catch{}}
finally{
 writeFileSync(resolve(out,'results.json'),JSON.stringify(results,null,2));
 writeFileSync(resolve(out,'evidence-events.json'),JSON.stringify(events,null,2));
 writeFileSync(resolve(out,'model-usage.json'),JSON.stringify({requests:0,credentials_injected:false,cost_cny:0}));
 if(agent)await agent.destroy();
}
