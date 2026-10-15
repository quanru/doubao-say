import pathlib,re,base64,hashlib,json,os,sys,math
s=pathlib.Path('/tmp/pr13930-existing.log').read_text()
m=re.search(r'PR13930_EVIDENCE_BEGIN (\d+) ([a-f0-9]{64})',s);assert m and 'PR13930_EVIDENCE_END' in s
d=base64.b64decode(''.join(re.findall(r'PR13930_EVIDENCE_DATA ([A-Za-z0-9+/=]+)',s)),validate=True)
assert len(d)==int(m[1]) and hashlib.sha256(d).hexdigest()==m[2]
size=1500000;count=math.ceil(len(d)/size)
print('RECOVERY_MANIFEST '+json.dumps({'bytes':len(d),'sha256':m[2],'chunk_size':size,'count':count,'source_job':116468073940}))
if len(sys.argv)==1:
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:f.write('chunks='+json.dumps(list(range(count)))+'\n')
else:
    index=int(sys.argv[1]);assert 0<=index<count;part=d[index*size:(index+1)*size]
    print('RECOVERY_CHUNK_BEGIN '+json.dumps({'index':index,'bytes':len(part),'sha256':hashlib.sha256(part).hexdigest()}))
    encoded=base64.b64encode(part).decode()
    for i in range(0,len(encoded),32000):print('RECOVERY_CHUNK_DATA '+encoded[i:i+32000])
    print('RECOVERY_CHUNK_END')
