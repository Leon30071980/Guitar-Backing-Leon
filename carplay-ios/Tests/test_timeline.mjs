import assert from 'node:assert/strict';
import {normalize,atTime,clamp} from '../Preview/timeline.mjs';
const items={offset_seconds:0.4,words:[{start:1,end:2,text:'CIAO',line:0},{start:2,end:3,text:'MONDO',line:0},{start:5,end:6,text:'NUOVO',line:1},{start:6,end:7,text:'GIORNO',line:1}]};
const data=normalize(items);assert.equal(data.length,2);assert.equal(data[0].start,1.4);assert.equal(data[0].text,'CIAO MONDO');assert.equal(data[1].text,'NUOVO GIORNO');assert.equal(atTime(data,4.2),0);assert.equal(atTime(data,5.2),1);assert.equal(clamp(-10,20),0);assert.equal(clamp(25,20),20);
const noChords=normalize({words:[{start:0,end:1,text:'TEST',line:0}],chords:[{start:0,end:1,chord:'Am'}]});assert.equal(noChords[0].text,'TEST');
console.log('OK: frasi, tempo, offset, accordi esclusi');
