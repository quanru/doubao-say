export function windowPointToOutput(s, geometry, offsetY=0) {
 const m=geometry.monitor,c=geometry.client;
 if(m.transform!==0 || !(m.scale>0))throw Error('Unsupported monitor transform');
 const x=Math.round((c.at[0]+s.x+s.width/2-m.x)*m.scale);
 const y=Math.round((c.at[1]+s.y+s.height/2+offsetY-m.y)*m.scale);
 if(x<0||x>=m.width||y<0||y>=m.height)throw Error('Input point outside QMP display');
 return {x,y};
}
