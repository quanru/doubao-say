"""Durable integer-micro-CNY reservations. No credentials or network access."""
import json, os, fcntl
from pathlib import Path

class Ledger:
 def __init__(self,path,limit_micro,request_max_micro):
  self.path=Path(path); self.limit=limit_micro; self.request_max=request_max_micro
  assert 0 < request_max_micro <= limit_micro <= 100_000_000
  self.path.parent.mkdir(parents=True,exist_ok=True)
  self.file=open(self.path,'a+',encoding='utf-8')
  fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB)
  self.file.seek(0); self.records=[json.loads(x) for x in self.file if x.strip()]
  self.pending={}; self.spent=0
  for r in self.records:
   if r['event']=='reserve': self.pending[r['id']]=r['micro_cny']
   elif r['event']=='settle':
    reserved=self.pending.pop(r['id']); assert 0<=r['micro_cny']<=reserved
    self.spent+=r['micro_cny']
  assert self.used<=self.limit
 @property
 def used(self): return self.spent+sum(self.pending.values())
 def write(self,r):
  self.file.write(json.dumps(r)+'\n');self.file.flush();os.fsync(self.file.fileno());self.records.append(r)
 def reserve(self):
  if self.used+self.request_max>self.limit: return None
  number=1+max([r['id'] for r in self.records] or [0])
  self.write({'event':'reserve','id':number,'micro_cny':self.request_max})
  self.pending[number]=self.request_max
  return number
 def settle(self,number,input_tokens,output_tokens):
  # Price ceiling 6/30 CNY per million, twice the observed official 3/15.
  # No discount/free-credit assumptions; unknown usage keeps full reservation.
  if type(input_tokens)!=int or not 0<=input_tokens<=262144 or type(output_tokens)!=int or not 0<=output_tokens<=4096: return False
  amount=input_tokens*6+output_tokens*30
  if amount>self.pending[number]:return False
  self.write({'event':'settle','id':number,'micro_cny':amount})
  del self.pending[number];self.spent+=amount
  return True
