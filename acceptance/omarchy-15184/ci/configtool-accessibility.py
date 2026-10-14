"""Read only Qt accessibility discovery. All actual clicks/keys come from QMP."""
import json,pathlib,sys,time,subprocess
import gi
gi.require_version('Atspi','2.0')
from gi.repository import Atspi
Atspi.init()
out=pathlib.Path('/tmp/pr15184/evidence');selector=sys.argv[1];tag=sys.argv[2]
assert tag.replace('-','').isalnum()
nodes=[]
def walk(a,path=(),depth=0):
 if depth>16:return
 try:
  state=a.get_state_set();rect=a.get_component_iface().get_extents(Atspi.CoordType.SCREEN)
  d={'path':list(path),'name':a.get_name() or '', 'description':a.get_description() or '', 'role':a.get_role_name(),'rect':[rect.x,rect.y,rect.width,rect.height],'showing':state.contains(Atspi.StateType.SHOWING),'enabled':state.contains(Atspi.StateType.ENABLED),'checked':state.contains(Atspi.StateType.CHECKED)}
 except Exception:
  d={'path':list(path),'name':a.get_name() or '', 'role':a.get_role_name(),'rect':[0,0,0,0],'showing':False,'enabled':False}
 nodes.append(d)
 for i in range(a.get_child_count()):
  try:walk(a.get_child_at_index(i),(*path,i),depth+1)
  except Exception:pass
for _ in range(40):
 desktop=Atspi.get_desktop(0);apps=[a for a in (desktop.get_child_at_index(i) for i in range(desktop.get_child_count())) if a and 'fcitx' in (a.get_name() or '').lower()]
 if apps:break
 time.sleep(.1)
for i,a in enumerate(apps):walk(a,(i,))
(out/(tag+'-a11y.json')).write_text(json.dumps(nodes,ensure_ascii=False,indent=2))
assert nodes,'Qt configtool did not expose accessibility; do not substitute backend edits'
visible=[n for n in nodes if n['showing'] and n['enabled'] and n['rect'][2]>0 and n['rect'][3]>0]
# Layout comes from pinned fcitx5-configtool 5.1.16 impage.ui: current list
# is left, available list is right, central IM buttons are below group buttons.
frames=[n for n in visible if n['role'] in ['frame','dialog']]
assert len(frames)==1,('Expected one configuration frame',frames)
x,y,w,h=frames[0]['rect'];mid=x+w/2
name=lambda n:n['name'].replace('&','').strip()
if selector in ['current-pinyin','available-pinyin']:
 candidates=[n for n in visible if name(n)=='Pinyin' and n['role'] in ['list item','table cell','tree item'] and ((n['rect'][0]+n['rect'][2]/2<mid)==(selector=='current-pinyin'))]
elif selector in ['add','remove']:
 candidates=[n for n in visible if name(n)==selector.title() and n.get('description')==selector.title() and n['role'] in ['button','push button','push button menu']]
 # Exact tooltips distinguish IM Add/Remove from Add Group/Delete Group.
elif selector=='apply':candidates=[n for n in visible if name(n)=='Apply' and n['role'] in ['button','push button']]
elif selector=='language':candidates=[n for n in visible if name(n)=='Only Show Current Language' and n['role']=='check box']
elif selector=='search':candidates=[n for n in visible if n['role'] in ['text','entry'] and n['rect'][0]>=mid]
elif selector=='dump':print(json.dumps({'nodes':len(nodes)}));raise SystemExit()
else:raise SystemExit('Unknown selector')
assert len(candidates)==1,('Ambiguous or missing exact UI target',selector,candidates)
n=candidates[0];nx,ny,nw,nh=n['rect'];cx,cy=nx+nw//2,ny+nh//2
# Wayland clients need not know their global origin. Translate the accessible
# frame-relative point using the compositor's real window origin, never assume 0,0.
clients=json.loads(subprocess.check_output(['hyprctl','-j','clients'],text=True))
clients=[c for c in clients if 'fcitx' in (c.get('class','')+' '+c.get('initialClass','')).lower()]
assert len(clients)==1,('Expected one actual configtool window',len(clients))
window=clients[0];assert abs(w-window['size'][0])<=8 and abs(h-window['size'][1])<=8,('Accessibility/compositor size mismatch',frames[0]['rect'],window['size'])
cx,cy=window['at'][0]+cx-x,window['at'][1]+cy-y
assert 0<=cx<1280 and 28<=cy<800,('UI target off screen',n)
result={'selector':selector,'x':cx,'y':cy,'node':n,'frame':frames[0],'window':{k:window.get(k) for k in ['class','at','size','pid']}}
(out/(tag+'-target.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2))
print(json.dumps(result))
