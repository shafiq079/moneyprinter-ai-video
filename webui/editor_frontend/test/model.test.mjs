import {test} from 'node:test';
import assert from 'node:assert/strict';
import {clampTime,changeEvent,timecode,frameTime,rememberedTime} from '../src/model.mjs';
test('playhead stays within available media and tolerates unloaded metadata',()=>{
  assert.equal(clampTime(-4,20),0);assert.equal(clampTime(21,20),20);assert.equal(clampTime(NaN,20),0);
  assert.equal(timecode(65.5),'01:05.50');
});
test('timeline edits preserve stable scene identity and caption revision tokens',()=>{
  assert.deepEqual(changeEvent({effectId:'visual',scene_id:7},2,5,'v',true),{kind:'resize',scene_id:7,duration:3,revision:'v'});
  assert.deepEqual(changeEvent({effectId:'captions',index:3},2,5,'v'),{kind:'caption',index:3,start:2,end:5,revision:'v'});
  assert.equal(changeEvent({effectId:'narration'},2,5,'v'),null);
});

test('paused seeks land on a decoded output frame, including the last frame',()=>{
  assert.equal(frameTime(8,20),8);
  assert.equal(frameTime(20,20),599/30);
  assert.equal(frameTime(2.5+1/30,6),76/30);
  assert.equal(frameTime(-1,6),0);
});

test('music and SFX timeline events carry stable clip IDs and resize intent',()=>{
  assert.deepEqual(changeEvent({effectId:'sfx',clip_id:'stable'},1,2,'v'),
    {kind:'audio',clip_id:'stable',start:1,end:2,resize:false,revision:'v'});
  assert.equal(changeEvent({effectId:'music',clip_id:'stable'},.5,2,'v',true).resize,true);
});

test('reload playhead state is bounded and ignores broken or unavailable storage',()=>{
  assert.equal(rememberedTime({getItem:()=> '8.25'},'task:program',20),8.25);
  assert.equal(rememberedTime({getItem:()=> '900'},'task:program',20),20);
  assert.equal(rememberedTime({getItem:()=> 'NaN'},'task:program',20),null);
  assert.equal(rememberedTime({getItem:()=> null},'task:program',20),null);
  assert.equal(rememberedTime({getItem:()=>{throw Error('blocked');}},'task:program',20),null);
});
