import assert from 'node:assert/strict';
import {normalize} from '../Preview/timeline.mjs';
import {linesFromPhrases,displayFromState,timeFromAnchor,anchorAt} from '../Preview/live_clock.mjs';
const phrases=normalize({words:[
 {start:7,end:8,text:'UN',line:0},{start:8,end:11,text:'PRIMO VERSO',line:0},
 {start:18,end:19,text:'UN',line:1},{start:19,end:21,text:'ALTRO VERSO',line:1}
]});
const {lines,truncated}=linesFromPhrases(phrases);
assert.equal(truncated,false); assert.equal(lines.length,2);
let state=anchorAt(0,true,lines,100);
assert.equal(displayFromState(state,101),'♪ INTRO STRUMENTALE');
assert.equal(displayFromState(state,108),'UN PRIMO VERSO');
assert.equal(displayFromState(state,114),'♪ INTERMEZZO');
assert.equal(displayFromState(state,119),'UN ALTRO VERSO');
state=anchorAt(10,false,lines,100);
assert.equal(timeFromAnchor(state,300),10);
assert.equal(displayFromState(state,300),'UN PRIMO VERSO');
state=anchorAt(19,true,lines,500);
assert.equal(displayFromState(state,500),'UN ALTRO VERSO');
assert.equal(displayFromState(state,502),'UN ALTRO VERSO');
const long=Array.from({length:200},(_,i)=>({start:i*5,end:i*5+4,text:'TESTO VERSO RIPETUTO IN SIMULAZIONE '+i+' ✓'}));
const packed=linesFromPhrases(long);
assert.equal(packed.truncated,true);
assert.ok(new TextEncoder().encode(JSON.stringify(anchorAt(0,true,packed.lines,1790000000.123))).length<=3500);
assert.ok(packed.lines.length>2);
const paused=anchorAt(19,false,packed.lines,10,true);
assert.equal(timeFromAnchor(paused,1000),19);
assert.equal(displayFromState(anchorAt(1000,true,packed.lines,10,true),10),'♪ KARAOKE IN ATTESA');
console.log('OK: intro, pause, seeking, intermezzi, vincolo 3.5 KB');
