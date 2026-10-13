"""Optional single-worker HTTP cap for an approved OpenAI-compatible endpoint.
No credentials stored or logged. Not a monetary cap; not live-provider tested.
Requires explicit CLI approval flag; bind only to localhost in disposable CI.
"""
import argparse,json,time,threading,http.client,urllib.parse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--upstream',required=True);p.add_argument('--model',required=True)
p.add_argument('--approved-model-use',action='store_true',required=True)
p.add_argument('--max-requests',type=int,default=60);p.add_argument('--max-output-tokens',type=int,default=1024)
p.add_argument('--output-field',choices=['max_tokens','max_completion_tokens','max_output_tokens'],default='max_tokens')
p.add_argument('--duration-seconds',type=int,default=3600);p.add_argument('--port',type=int,default=18784)
a=p.parse_args();u=urllib.parse.urlsplit(a.upstream)
if u.scheme!='https' or not u.hostname or u.username or u.password or u.query or u.fragment:raise SystemExit('Expected an HTTPS base URL without credentials/query')
if min(a.max_requests,a.max_output_tokens,a.duration_seconds)<=0:raise SystemExit('Caps must be positive')
lock=threading.Lock();counter=0;deadline=time.monotonic()+a.duration_seconds
class Gate(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def reply(self,status,body):
  self.send_response(status);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps(body).encode())
 def do_POST(self):
  global counter
  path=self.path.removeprefix('/v1')
  if path not in ['/chat/completions','/responses']:return self.reply(403,{'error':'unsupported endpoint'})
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
  except (ValueError,TypeError):return self.reply(400,{'error':'invalid request or unsupported model/stream/batch'})
  with lock:
   if counter>=a.max_requests or time.monotonic()>=deadline:return self.reply(429,{'error':'hard request/time cap reached'})
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
   print(json.dumps({'request_number':number,'status':response.status,'usage':usage}),flush=True)
  except Exception:
   print(json.dumps({'request_number':number,'status':'transport_failure'}),flush=True)
   self.reply(502,{'error':'upstream transport failure','request_number':number})
  finally:conn.close()
ThreadingHTTPServer(('127.0.0.1',a.port),Gate).serve_forever()
