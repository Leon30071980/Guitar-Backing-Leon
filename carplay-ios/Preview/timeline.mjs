export function normalize(input,maxChars=52){
  const words=(input?.words||[]).filter(x=>Number.isFinite(+x.start)&&Number.isFinite(+x.end)&&+x.end>+x.start&&String(x.text||'').trim())
     .map(x=>({...x,start:+x.start,end:+x.end,line:+x.line||0})).sort((a,b)=>a.start-b.start);
  const offset=Number(input?.offset_seconds)||0;
  const phrases=[];let chunk=[];
  const flush=()=>{if(!chunk.length)return;phrases.push({start:Math.max(0,chunk[0].start+offset),end:Math.max(0,chunk.at(-1).end+offset),text:chunk.map(x=>x.text).join(' ')});chunk=[];};
  for(const word of words){
    const joined=[...chunk,word].map(x=>x.text).join(' ');
    if(chunk.length&&(word.line!==chunk.at(-1).line||joined.length>maxChars))flush();
    chunk.push(word);
  }
  flush();return phrases;
}
export function atTime(phrases,time){
  if(!phrases.length)return -1;
  for(let i=phrases.length-1;i>=0;i--)if(phrases[i].start<=time+0.25)return i;
  return 0;
}
export function clamp(t,end){return Math.max(0,Math.min(end,Number(t)||0));}
