"""Execute production policy against mocked HTTPS transport; never contacts provider."""
import sys,tempfile,threading,json,io,urllib.request,urllib.error,http.client
from pathlib import Path
from http.server import ThreadingHTTPServer
root=Path(__file__).resolve().parents[1]
calls=[]
class Response:
 status=200
 def read(self,*a):return json.dumps({'usage':{'prompt_tokens':100,'completion_tokens':100},'choices':[]}).encode()
class Connection:
 debuglevel=0
 def __init__(self,*a,**k):pass
 def request(self,method,path,body,headers):calls.append(json.loads(body))
 def getresponse(self):return Response()
 def close(self):pass
http.client.HTTPSConnection=Connection
with tempfile.TemporaryDirectory() as d:
 sys.argv=['gate','--upstream','https://ark.cn-beijing.volces.com/api/v3','--model','doubao-seed-2-1-turbo-260628','--approved-model-use','--budget-micro','1700000','--ledger',d+'/money.jsonl']
 source=(root/'scripts/budget-gate.py').read_text().rsplit("ThreadingHTTPServer(('127.0.0.1'",1)[0]
 ns={'__file__':str(root/'scripts/budget-gate.py')};exec(compile(source,ns['__file__'],'exec'),ns)
 server=ThreadingHTTPServer(('127.0.0.1',0),ns['Gate']);threading.Thread(target=server.serve_forever,daemon=True).start()
 def send(extra):
  data={'model':sys.argv[4],'messages':[{'role':'user','content':'safe local test'}],**extra}
  c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
  c.request('POST','/chat/completions',json.dumps(data),{'Content-Type':'application/json'})
  r=c.getresponse();status=r.status;r.read();c.close();return status
 assert send({'tools':[{'type':'web_search'}]})==400
 assert send({'stream':True})==400
 assert send({'max_tokens':999999})==200
 assert calls[-1]['max_completion_tokens']==4096 and 'max_tokens' not in calls[-1]
 assert calls[-1]['service_tier']=='default'
 # Confirm that any malformed/unknown usage keeps the full reservation.
 Response.read=lambda self,*a:b'{}'
 assert send({})==200
 assert send({})==429
 assert len(calls)==2
 server.shutdown();server.server_close();ns['money'].file.close()
print('PASS: real production policy, fixed output/tier, forbidden tools/stream, monetary exhaustion, unknown usage retention. Mock HTTPS only.')
