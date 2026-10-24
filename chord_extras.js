/* Guitar Backing Leon 2.21.5: accordi originali/semplificati e diagrammi
   Solo visualizzazione: NON altera dati salvati o audio. */
(function(global){
 'use strict';
 const previous=global.GuitarChordTools;
 if(!previous || typeof previous.display!=='function')return;
 function simplify(raw){
   const source=String(raw||'').trim();
   const match=/^([A-G](?:#|b)?)(m(?!aj)|min|maj|M)?(.*)$/i.exec(source);
   if(!match || /^(?:N|NC)$/i.test(source))return source;
   const root=match[1], quality=match[2]||'', tail=match[3]||'';
   if(/(?:dim|aug|ø|°)/i.test(quality+tail))return source;
   if(!tail && quality!=='maj' && quality!=='M')return source;
   const minor=/^(?:m|min)$/i.test(quality);
   // Semplificazione armonica (non semplice cambio diteggiatura): 7, add,
   // sus, inversioni e maj7 vengono tolti solo nella visualizzazione.
   if(tail && !/^(?:(?:maj|M)?\d+|add\d+|sus\d*|[#b+\-]\d+|\/\w+)+$/i.test(tail))return source;
   return root+(minor?'m':'');
 }
 // Diteggiature didattiche 6a->1a corda, null=corda non suonata.
 const POS={
  C:[null,3,2,0,1,0],D:[null,null,0,2,3,2],E:[0,2,2,1,0,0],F:[1,3,3,2,1,1],G:[3,2,0,0,0,3],A:[null,0,2,2,2,0],B:[null,2,4,4,4,2],
  Am:[null,0,2,2,1,0],Bm:[null,2,4,4,3,2],Cm:[null,3,5,5,4,3],Dm:[null,null,0,2,3,1],Em:[0,2,2,0,0,0],Fm:[1,3,3,1,1,1],Gm:[3,5,5,3,3,3],
  'F#m':[2,4,4,2,2,2], 'C#m':[null,4,6,6,5,4], 'G#m':[4,6,6,4,4,4], 'Bb':[null,1,3,3,3,1], 'Eb':[null,6,8,8,8,6], 'Ab':[4,6,6,5,4,4], 'F#':[2,4,4,3,2,2],
  Aadd9:[null,0,2,4,2,0], Cadd9:[null,3,2,0,3,0], Eadd9:[0,2,4,1,0,0],
  E7:[0,2,0,1,0,0],A7:[null,0,2,0,2,0],D7:[null,null,0,2,1,2],G7:[3,2,0,0,0,1],B7:[null,2,1,2,0,2],C7:[null,3,2,3,1,0],
  Em7:[0,2,2,0,3,0],Am7:[null,0,2,0,1,0],Bm7:[null,2,4,2,3,2],Dm7:[null,null,0,2,1,1],
  Cmaj7:[null,3,2,0,0,0],Fmaj7:[null,null,3,2,1,0],Gmaj7:[3,2,0,0,0,2],
  Dsus4:[null,null,0,2,3,3],Asus2:[null,0,2,2,0,0],Asus4:[null,0,2,2,3,0],Dsus2:[null,null,0,2,3,0],Esus4:[0,2,2,2,0,0]
 };
 const NS='http://www.w3.org/2000/svg';
 function node(tag,attrs={},value){const el=document.createElementNS(NS,tag);Object.entries(attrs).forEach(([k,v])=>el.setAttribute(k,String(v)));if(value!==undefined)el.textContent=value;return el;}
 function diagram(chord){
  const name=String(chord||'').trim();
  const voicing=POS[name];
  const pane=document.createElement('span');pane.className='gbl-diagram';pane.setAttribute('role','tooltip');
  const heading=document.createElement('strong');heading.textContent=name;pane.append(heading);
  if(!voicing){const p=document.createElement('span');p.textContent='Diteggiatura non disponibile';pane.append(p);return pane;}
  const notes=voicing.filter(n=>typeof n==='number'&&n>0);
  const high=Math.max(...notes,0);
  const base=high>5?Math.max(1,Math.min(...notes)):1;
  const svg=node('svg',{viewBox:'0 0 152 150',width:152,height:150,'aria-label':`Diagramma accordo ${name}`,role:'img'});
  const x0=21,step=21,y0=29,fstep=21;
  for(let i=0;i<6;i++)svg.append(node('line',{x1:x0+i*step,x2:x0+i*step,y1:y0,y2:y0+5*fstep,stroke:'#a6bbbe','stroke-width':1.7}));
  for(let f=0;f<=5;f++)svg.append(node('line',{x1:x0,x2:x0+5*step,y1:y0+f*fstep,y2:y0+f*fstep,stroke:'#a6bbbe','stroke-width':f===0&&base===1?4:1.4}));
  if(base>1)svg.append(node('text',{x:5,y:y0+16,fill:'#d1e8e4','font-size':11},String(base)));
  voicing.forEach((f,i)=>{
   const x=x0+i*step;
   if(f===null){svg.append(node('text',{x,y:17,'text-anchor':'middle',fill:'#ffb4b4','font-size':14},'×'));return;}
   if(f===0){svg.append(node('circle',{cx:x,cy:13,r:5,fill:'none',stroke:'#befee3','stroke-width':1.7}));return;}
   svg.append(node('circle',{cx:x,cy:y0+(f-base+.5)*fstep,r:8.2,fill:'#73e4bd',stroke:'#183d40','stroke-width':1}));
  });
  pane.append(svg);
  const footer=document.createElement('span');footer.className='gbl-diagram-hint';footer.textContent='6ª → 1ª corda';pane.append(footer);
  return pane;
 }
 global.GuitarChordTools=Object.freeze({...previous,simplify,diagram});
})(window);
