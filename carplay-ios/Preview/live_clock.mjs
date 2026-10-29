// Replica in JavaScript della timeline temporizzata per i test Windows.
// Non controlla il player della PWA, non comunica con Drive.
export function linesFromPhrases(phrases, limit=3500) {
  let lines=[];
  for (const p of phrases){
    const line={d:Math.round(p.start*10),e:Math.round(p.end*10),v:p.text};
    const proposed=[...lines,line];
    const content={anchorEpoch:1790000000.123,anchorPosition:0,isPlaying:true,phraseFallback:'',hasMore:true,lines:proposed};
    if(new TextEncoder().encode(JSON.stringify(content)).length>limit) break;
    lines=proposed;
  }
  return {lines, truncated:lines.length < phrases.length};
}
export function timeFromAnchor(state,epoch){
  return Math.max(0, (Number(state.anchorPosition)||0) + (state.isPlaying ? Math.max(0,epoch - state.anchorEpoch) : 0));
}
export function displayFromState(state,epoch){
  const lines=state.lines||[];
  if(!lines.length)return state.phraseFallback||'';
  const t=Math.floor((timeFromAnchor(state,epoch)+.25)*10);
  if(t < lines[0].d-3)return '♪ INTRO STRUMENTALE';
  let i=-1;
  for(let n=lines.length-1;n>=0;n--){if(lines[n].d<=t){i=n;break;}}
  if(i<0)return lines[0].v;
  if(t>lines[i].e+15)return i+1<lines.length?'♪ INTERMEZZO':state.hasMore?'♪ KARAOKE IN ATTESA':'♪ FINALE STRUMENTALE';
  return lines[i].v;
}
export function anchorAt(position,playing,lines=[],epoch=Date.now()/1000,hasMore=false){
  return {anchorEpoch:epoch,anchorPosition:position,isPlaying:playing,phraseFallback:'',hasMore,lines};
}
