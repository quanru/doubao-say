// Fixed no-model discovery and observation-perturbation comparison.
import {execFileSync} from 'node:child_process';
import {mkdirSync,writeFileSync,readFileSync} from 'node:fs';
import {resolve} from 'node:path';
const root=process.cwd(),out=resolve(root,'review-artifacts');
const {RegionObservation}=await import(resolve(root,'work/midscene/packages/computer/dist/es/index.mjs'));
const guest=(...a)=>execFileSync('bash',['ci/guest.sh',...a],{cwd:root,encoding:'utf8',timeout:30000}).trim();
const state=readFileSync('work/session-state','utf8').trim().split('\n');
const key=(...a)=>execFileSync('python3',['scripts/qmp-key.py',state[1],...a,'--disposable-vm'],{cwd:root,timeout:10000});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const geometry={outputIndex:0,x:0,y:0,width:1280,height:28,scale:1,outputWidth:1280,outputHeight:800,transform:0};
const modes=['discovery','plain','passive','feedback','pixels'];
for(const mode of modes){
 guest('probe-mode',mode,mode);await sleep(1000);guest('probe-health',mode);console.log(`Real shell/probe healthy: ${mode}`);guest('focus');
 if(JSON.parse(guest('snapshot',`preflight-${mode}-initial`)).active!=='2'){key('meta_l','i');await sleep(700);}
 for(let i=0;i<4;i++){
  const name=`probe${mode}${i}`;guest('input-start',name);let ready=false;for(let j=0;j<50;j++){try{guest('ready',name);ready=true;break;}catch{await sleep(30);}}if(!ready)throw Error('Input baseline missing');
  const s=RegionObservation.start({command:'bash',args:[resolve(root,'ci/guest.sh'),'native-region'],geometry,maxFrames:1000});
  let input;try{for(let j=0;j<150&&!s.frames().length;j++)await sleep(20);if(!s.frames().length)throw Error('No source baseline');await sleep(200);key('shift','--hold-ms','80');await sleep(1000);input=JSON.parse(guest('input-end',name));}finally{await s.stop();}
  const d=resolve(out,'presentation-preflight',mode,String(i));mkdirSync(d,{recursive:true});
  const frames=s.frames().map((f,j)=>{const path=`${j}.png`;writeFileSync(resolve(d,path),f.png);return {frameId:f.frameId,timing:f.timing,geometry:f.geometry,path};});
  writeFileSync(resolve(d,'record.json'),JSON.stringify({input,frames},null,2));
  let pids;for(let j=0;j<30;j++){pids=JSON.parse(guest('native-status')).capture_pids;if(!pids.length)break;await sleep(50);}if(pids.length)throw Error('Native producer leaked');
 }
 guest('screenshot',`success-probe-${mode}`);
 if(['discovery','feedback'].includes(mode)){const d=resolve(out,'presentation-preflight',mode);writeFileSync(resolve(d,'protocol.json'),guest('probe-discovery',mode));}
 if(['passive','feedback','pixels'].includes(mode)){
  const d=resolve(out,'presentation-preflight',mode);writeFileSync(resolve(d,'events.jsonl'),guest('probe-events',mode)+'\n');
  const images=JSON.parse(guest('probe-pixels',mode));for(const [name,b64] of Object.entries(images))writeFileSync(resolve(d,name),Buffer.from(b64,'base64'));
 }
}
execFileSync('python3',['ci/presentation/verify-preflight.py'],{cwd:root,stdio:'inherit'});
// Keep pixels observer for fixed trials, with no restarts inside the trial set.
