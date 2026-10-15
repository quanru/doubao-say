"""Read-only shell.json timeline in the disposable guest; preserve exact bytes."""
import pathlib,json,time,hashlib,os,sys
R=pathlib.Path('/tmp/pr12248');E=R/'evidence/config';H=pathlib.Path.home();P=H/'.config/omarchy/shell.json'
def difference(a,b,path='$'):
 if type(a)!=type(b):return [{'path':path,'before':a,'after':b}]
 if isinstance(a,dict):
  out=[]
  for k in sorted(set(a)|set(b)):
   if k not in a:out.append({'path':path+'.'+k,'added':b[k]})
   elif k not in b:out.append({'path':path+'.'+k,'removed':a[k]})
   else:out+=difference(a[k],b[k],path+'.'+k)
  return out
 if isinstance(a,list):
  if len(a)!=len(b):return [{'path':path,'before':a,'after':b}]
  return [d for i,(x,y) in enumerate(zip(a,b)) for d in difference(x,y,path+'['+str(i)+']')]
 return [] if a==b else [{'path':path,'before':a,'after':b}]
def capture(label):
 E.mkdir(exist_ok=True,parents=True);exists=P.exists();b=P.read_bytes() if exists else b'';st=P.stat() if exists else None
 (E/(label+'.raw.json')).write_bytes(b)
 try:parsed=json.loads(b) if exists else None;error=None
 except Exception as e:parsed=None;error=str(e)
 base=R/'shell-config-backup';original=json.loads(base.read_bytes()) if base.exists() else None
 d={'label':label,'epoch_ns':time.time_ns(),'monotonic_ns':time.monotonic_ns(),'exists':exists,'sha256':hashlib.sha256(b).hexdigest() if exists else None,'mtime_ns':st.st_mtime_ns if st else None,'inode':st.st_ino if st else None,'mode':st.st_mode if st else None,'json_error':error,'structure_diff_from_backup':difference(original,parsed),'case':(R/'case-label').read_text() if (R/'case-label').exists() else 'bootstrap'}
 (E/(label+'.metadata.json')).write_text(json.dumps(d,indent=2));return d
if __name__=='__main__':
 last=None;i=0
 while not (R/'config-watch-stop').exists():
  try:
   st=P.stat();b=P.read_bytes();key=(hashlib.sha256(b).hexdigest(),st.st_mtime_ns)
  except FileNotFoundError:key=None
  if key!=last or i==0:
   capture('timeline-'+str(i).zfill(4));last=key;i+=1
  time.sleep(.1)
 capture('timeline-final');(R/'config-watch-done').touch()
