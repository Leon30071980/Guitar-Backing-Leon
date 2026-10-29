/* Guitar Backing Leon v2.64 — protocollo CarPlay locale.
   Esporta SOLTANTO versi e posizione, mai URL Drive, token o audio.
   Questo modulo non comunica da solo con ActivityKit in background. */
(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.GuitarCarPlayProtocol=api;
})(typeof window!=='undefined'?window:null,function(){
  'use strict';
  const numeric=x=>Number.isFinite(Number(x))?Number(x):0;
  const clamp=(x,lo,hi)=>Math.max(lo,Math.min(hi,x));
  function phrases(words, offset=0){
    const ordered=(Array.isArray(words)?words:[]).filter(w=>w&&typeof w.text==='string'&&w.text.trim()&&Number.isFinite(Number(w.start))&&Number.isFinite(Number(w.end))&&Number(w.end)>Number(w.start))
      .slice(0,3000).sort((a,b)=>numeric(a.start)-numeric(b.start));
    const items=[];let p=[];
    function flush(){if(!p.length)return;items.push({d:Math.max(0,Math.round((numeric(p[0].start)+offset)*10)),e:Math.max(1,Math.round((numeric(p[p.length-1].end)+offset)*10)),v:p.map(w=>w.text.trim()).join(' ').slice(0,90)});p=[];}
    for(const word of ordered){
      let extended=(p.map(w=>w.text.trim()).join(' ')+' '+word.text.trim()).trim();
      if(p.length&&(numeric(p[p.length-1].line)!==numeric(word.line)||extended.length>49||numeric(word.start)-numeric(p[p.length-1].end)>2.5)){flush();}
      p.push(word);
    }
    flush();
    return items.filter(x=>x.e>x.d);
  }
  function windowed(snapshot){
    const all=phrases(snapshot.words,clamp(numeric(snapshot.offset),-6,6));
    const pos=clamp(numeric(snapshot.position),0,86400);
    const index=all.findIndex(x=>x.e>=Math.round(pos*10)-2);
    const current=index===-1?Math.max(0,all.length-1):index;
    const first=Math.max(0,current-2);
    const t=String(snapshot.title||'BRANO').slice(0,85);
    // Margin below ActivityKit 4KB, URL encoded size and iOS routing limits.
    const data={v:1,t,p:Math.round(pos*10)/10,d:Math.max(0,numeric(snapshot.duration)),r:!!snapshot.playing,h:false,l:[]};
    for(let i=first;i<all.length&&i<first+24;i++){
      const next={...data,l:[...data.l,all[i]],h:i+1<all.length};
      if(utf8(JSON.stringify(next))>2300)break;
      data.l.push(all[i]);
      data.h=i+1<all.length;
    }
    if(!data.l.length&&all.length){data.l.push({...all[first],v:all[first].v.slice(0,45)});data.h=first+1<all.length;}
    return data;
  }
  const utf8=s=>new TextEncoder().encode(s).length;
  function base64url(str){
    const bytes=new TextEncoder().encode(str);let binary='';for(const b of bytes)binary+=String.fromCharCode(b);
    return btoa(binary).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
  }
  function link(snapshot){return 'guitarleoncarplay://sync?data='+base64url(JSON.stringify(windowed(snapshot)));}
  return Object.freeze({phrases,windowed,link,utf8});
});
