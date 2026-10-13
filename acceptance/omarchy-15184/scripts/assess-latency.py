"""Assess calibrated intervals from real captures; does not generate measurements.
CSV columns: trial,input_lo_ns,input_hi_ns,visible_lo_ns,visible_hi_ns,evidence
All bounds must use the same calibrated monotonic clock. See RUNBOOK.md.
"""
import csv,json,sys
results=[]
with open(sys.argv[1],newline='') as f:
 for r in csv.DictReader(f):
  a,b,c,d=[int(r[k]) for k in ['input_lo_ns','input_hi_ns','visible_lo_ns','visible_hi_ns']]
  if a>b or c>d or not r['evidence']:raise ValueError('Invalid bounds or missing evidence')
  lo=max(0,c-b)/1e6;hi=(d-a)/1e6
  if hi<0:raise ValueError('Visual state precedes input')
  status='PASS' if hi<=500 else 'FAIL' if lo>500 else 'INCONCLUSIVE'
  results.append({'trial':r['trial'],'lower_ms':lo,'upper_ms':hi,'status':status,'evidence':r['evidence']})
print(json.dumps(results,indent=2))
if not results:raise SystemExit('No trials; not a pass')
