// Real guest source lifecycle check. No model configuration or inference.
import {execFileSync} from 'node:child_process';
import {writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
const root=process.cwd();
const {ObservationFrameSource}=await import(resolve(root,'work/midscene/packages/computer/dist/es/index.mjs'));
const guest=(...args)=>execFileSync('bash',[resolve(root,'ci/guest.sh'),...args],{cwd:root,encoding:'utf8',timeout:10000}).trim();
const active=()=>JSON.parse(guest('native-status')).capture_pids;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const results=[];
if(active().length)throw Error('Capture helper remained after initial native preflight');
for(let i=0;i<3;i++){
 const source=ObservationFrameSource.start({command:'bash',args:[resolve(root,'ci/guest.sh'),'native-source']});
 let frame;
 try{
  for(let j=0;j<150;j++){frame=source.latest();if(frame)break;await sleep(20);}
  if(!frame)throw Error('No baseline in source lifecycle check');
  const pids=active();if(pids.length!==1 || !frame.frameId.startsWith(`${pids[0]}-`))throw Error('Unexpected concurrent capture producers');
  const before=performance.now();await source.stop();
  let remaining;
  for(let j=0;j<30;j++){remaining=active();if(!remaining.length)break;await sleep(100);}
  if(remaining.length)throw Error('Native producer leaked after stop');
  if(!(await source.decode([frame]))[0].startsWith('data:image/png;base64,'))throw Error('Issued frame lost after stopping');
  results.push({iteration:i,clockId:frame.timing.clockId,frameId:frame.frameId,stopVerifiedMs:performance.now()-before,remainingCapturePids:remaining});
 }finally{await source.stop();}
}
writeFileSync(resolve(root,'review-artifacts/versions/native-lifecycle.json'),JSON.stringify(results,null,2));
console.log('PASS: three real guest source lifecycles; zero capture producers after each stop; no inference.');
