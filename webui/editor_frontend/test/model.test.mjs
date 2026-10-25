import {test} from 'node:test';
import assert from 'node:assert/strict';
import {clampTime,changeEvent,timecode} from '../src/model.mjs';
test('playhead stays within available media and tolerates unloaded metadata',()=>{
  assert.equal(clampTime(-4,20),0);assert.equal(clampTime(21,20),20);assert.equal(clampTime(NaN,20),0);
  assert.equal(timecode(65.5),'01:05.50');
});
test('timeline edits preserve stable scene identity and caption revision tokens',()=>{
  assert.deepEqual(changeEvent({effectId:'visual',scene_id:7},2,5,'v',true),{kind:'resize',scene_id:7,duration:3,revision:'v'});
  assert.deepEqual(changeEvent({effectId:'captions',index:3},2,5,'v'),{kind:'caption',index:3,start:2,end:5,revision:'v'});
  assert.equal(changeEvent({effectId:'narration'},2,5,'v'),null);
});
