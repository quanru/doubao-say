import assert from 'node:assert/strict';
import {windowPointToOutput as point} from './coordinates.mjs';
// Regression fixture from run 38718038618 and independently inspected screenshot.
const control={x:32,y:385,width:240,height:28};
const geometry={client:{at:[12,38]},monitor:{x:0,y:0,scale:1,transform:0,width:1280,height:800}};
assert.deepEqual(point(control,geometry),{x:164,y:437});
// Run 38732887007: the trigger center was genuinely below the 800px output.
assert.throws(()=>point({...control,y:772},geometry),/outside QMP display/);
// Same logical arrangement on a scaled output to the right of another monitor.
assert.deepEqual(point(control,{client:{at:[1932,38]},monitor:{x:1920,y:0,scale:1.5,transform:0,width:1920,height:1200}}),{x:246,y:656});
assert.throws(()=>point(control,{...geometry,monitor:{...geometry.monitor,transform:1}}));
console.log('PASS: recovered-run coordinate regression, output origin/scale, unsupported transform guard');
