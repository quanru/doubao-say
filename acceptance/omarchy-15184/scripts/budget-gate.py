"""Optional single-worker HTTP cap for an approved OpenAI-compatible endpoint.
No credentials stored or logged. Production requires a run-bound monetary allocation.
Requires explicit CLI approval flag; bind only to localhost in disposable CI.
"""
import argparse,json,time,threading,http.client,urllib.parse,importlib.util
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--upstream',required=True);p.add_argument('--model',required=True)
p.add_argument('--approved-model-use',action='store_true',required=True)
p.add_argument('--max-requests',type=int,default=60);p.add_argument('--max-output-tokens',type=int,default=1024)
p.add_argument('--output-field',choices=['max_tokens','max_completion_tokens','max_output_tokens'],default='max_tokens')
p.add_argument('--duration-seconds',type=int,default=3600);p.add_argument('--port',type=int,default=18784)
p.add_argument('--budget-micro',type=int);p.add_argument('--ledger')
a=p.parse_args();u=urllib.parse.urlsplit(a.upstream)
if u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment:raise SystemExit('Expected an HTTPS base URL without credentials/query')
if min(a.max_requests,a.max_output_tokens,a.duration_seconds)<=0:raise SystemExit('Caps must be positive')
money=None
if u.hostname not in ['127.0.0.1','localhost']:
 if a.model!='doubao-seed-2-1-turbo-260628' or u.hostname!='ark.cn-beijing.volces.com' or u.path.rstrip('/')!='/api/v3':raise SystemExit('Provider/model differs from audited price policy')
 if not a.budget_micro or not a.ledger:raise SystemExit('Missing durable run budget')
 spec=importlib.util.spec_from_file_location('money',Path(__file__).with_name('money-ledger.py'));mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
 money=mod.Ledger(a.ledger,a.budget_micro,1695744)
lock=threading.Lock();counter=0;next_start=0;deadline=time.monotonic()+a.duration_seconds
class Gate(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def reply(self,status,body):
  self.send_response(status);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps(body).encode())
 def do_POST(self):
  global counter,next_start
  path=self.path.removeprefix('/v1')
  if path not in ['/chat/completions']:return self.reply(403,{'error':'unsupported endpoint'})
  try:
   size=int(self.headers.get('Content-Length','0'))
   if not 0<size<=8*1024*1024:raise ValueError()
   body=json.loads(self.rfile.read(size))
   if body.get('model')!=a.model:raise ValueError()
   # Reject streams so every request has a bounded lifetime and complete usage.
   if body.get('stream'):raise ValueError()
   body.pop('max_tokens',None);body.pop('max_completion_tokens',None);body.pop('max_output_tokens',None)
   body[a.output_field if path=='/chat/completions' else 'max_output_tokens']=a.max_output_tokens
   if body.get('n',1)!=1:raise ValueError()
   if money:
    # Closed parameter set excludes paid server-side tools, audio, tiers, batching,
    # continuation state and remote media. GUI screenshots and text only.
    allowed={'model','messages','stream','n','max_tokens','max_completion_tokens','temperature','top_p','response_format','stop','thinking','reasoning_effort'}
    if set(body)-allowed:raise ValueError()
    for msg in body.get('messages',[]):
     content=msg.get('content')
     if isinstance(content,str):continue
     if not isinstance(content,list):raise ValueError()
     for part in content:
      if part.get('type')=='text' and isinstance(part.get('text'),str):continue
      if part.get('type')=='image_url' and part.get('image_url',{}).get('url','').startswith(('data:image/png;base64,','data:image/jpeg;base64,')):continue
      raise ValueError()
    body.pop('max_tokens',None)
    body['max_completion_tokens']=4096
    body['service_tier']='default'
  except (ValueError,TypeError):return self.reply(400,{'error':'invalid request or unsupported model/stream/batch'})
  with lock:
   if counter>=a.max_requests or time.monotonic()>=deadline:return self.reply(429,{'error':'hard request/time cap reached'})
   if money:
    time.sleep(max(0,next_start-time.monotonic()))
    next_start=time.monotonic()+20
    if time.monotonic()>=deadline:return self.reply(429,{'error':'hard time cap reached'})
    reservation=money.reserve()
    if reservation is None:return self.reply(429,{'error':'hard monetary cap reached'})
   counter+=1;number=counter
  raw=json.dumps(body).encode();conn=http.client.HTTPSConnection(u.hostname,u.port or 443,timeout=90)
  try:
   headers={'Content-Type':'application/json'}
   if self.headers.get('Authorization'):headers['Authorization']=self.headers['Authorization']
   conn.request('POST',u.path.rstrip('/')+path,body=raw,headers=headers)
   response=conn.getresponse();data=response.read(16*1024*1024)
   if response.status>=300:
    self.reply(502,{'error':'upstream failure','request_number':number,'upstream_status':response.status})
   else:
    self.send_response(response.status);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(data)
   usage={}
   try:
    raw_usage=json.loads(data).get('usage',{})
    usage={k:v for k,v in raw_usage.items() if isinstance(v,(int,float)) and not isinstance(v,bool)}
   except (ValueError,AttributeError):pass
   if money and 200<=response.status<300:
    with lock:money.settle(reservation,usage.get('prompt_tokens'),usage.get('completion_tokens'))
   print(json.dumps({'request_number':number,'status':response.status,'usage':usage,'accounted_micro_cny':money.used if money else None}),flush=True)
  except Exception:
   print(json.dumps({'request_number':number,'status':'transport_failure'}),flush=True)
   self.reply(502,{'error':'upstream transport failure','request_number':number})
  finally:conn.close()
ThreadingHTTPServer(('127.0.0.1',a.port),Gate).serve_forever()
