"use strict";
/* Guitar Backing Leon 2.11 — lettura continua da chitarrista.
 * Un unico orologio: audio.currentTime. Gli accordi NON sono agganciati
 * ai confini delle parole. Nessuna riga artificiale per pause vocali brevi.
 * I dati non vengono modificati: questa e' solo una vista del karaoke.
 */
(function () {
  const num = value => Number(value);
  const valid = value => Number.isFinite(num(value));
  const clamp = (x,a,b) => Math.max(a,Math.min(b,x));
  const stamp = t => `${Math.floor(Math.max(0,t)/60)}:${String(Math.floor(Math.max(0,t)%60)).padStart(2,'0')}`;
  const makeEl = (tag, cls, label) => {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (label !== undefined) el.textContent = label;
    return el;
  };
  function chordAt(chords,t) {
    let lo=0, hi=chords.length;
    while (lo<hi) { const m=(lo+hi)>>1; if(chords[m].start<=t+0.0001)lo=m+1; else hi=m; }
    const idx=lo-1;
    return idx>=0 && t<chords[idx].end+0.0001 ? idx : -1;
  }
  // L'introduzione e gli assoli lunghi meritano una riga; una pausa di 3 s NO.
  function buildSegments(inputWords,inputChords,duration) {
    const words=(Array.isArray(inputWords)?inputWords:[]).map((w,index)=>({
      ...w,index,start:num(w.start),end:num(w.end),line:num(w.line)||0
    })).filter(w=>valid(w.start)&&valid(w.end)&&w.start>=0&&w.end>w.start)
      .sort((a,b)=>a.start-b.start||a.index-b.index);
    const chords=(Array.isArray(inputChords)?inputChords:[]).map(c=>({
      ...c,start:num(c.start),end:num(c.end)
    })).filter(c=>valid(c.start)&&valid(c.end)&&c.end>c.start)
      .sort((a,b)=>a.start-b.start);
    const last=Math.max(0,...words.map(w=>w.end),...chords.map(c=>c.end));
    const length=valid(duration)&&num(duration)>0?Math.max(num(duration),last):last;
    const phrases=[];
    for(const w of words){
      const tail=phrases[phrases.length-1];
      if(!tail || tail.line!==w.line || w.start-tail.end>1.6){
        phrases.push({type:'words',line:w.line,start:w.start,end:w.end,words:[w]});
      }else{tail.words.push(w);tail.end=Math.max(tail.end,w.end);}
    }
    const segments=[];
    function addGap(start,end,position){
      const gap=end-start;
      if(gap<.05)return;
      const changes=chords.filter(c=>c.start>=start-0.02&&c.start<end-0.02).length;
      // In assenza totale di parole, il karaoke resta utilizzabile solo con accordi.
      const noLyrics=phrases.length===0;
      const show=noLyrics || (position==='start'&&gap>=3) ||
        (position==='middle'&&gap>=10&&changes>=1) ||
        (position==='end'&&gap>=10&&changes>=1);
      if(show){
        segments.push({type:'instrumental',start,end,
          label:position==='start'?'Intro strumentale':position==='end'?'Finale strumentale':'Interludio strumentale'});
      }
    }
    let cursor=0;
    phrases.forEach((phrase,i)=>{
      addGap(cursor,phrase.start,i===0?'start':'middle');
      segments.push(phrase);
      cursor=Math.max(cursor,phrase.end);
    });
    addGap(cursor,length,phrases.length?'end':'start');
    return {segments,chords,words,duration:length};
  }
  function make({root,formatChord=(s=>s),onSeek,onWordClick,isEditing=()=>false}) {
    let model={segments:[],words:[],chords:[],duration:0};
    let lyricsOffset=0, originalWords=[], originalChords=[], originalDuration=0;
    let rows=[],wordEls=[],currentRow=-1,currentChord=-2,lastHorizontalTime=-1;
    let nowEl=null,nextEl=null,untilEl=null,fillEl=null;
    function makeTimeMap(segment,baseWidth){
      let xEnd=0;
      const anchors=[{t:segment.start,x:0}],positions=[];
      for (const w of segment.words){
        const text=String(w.text||'');
        const width=clamp(text.length*9+21,38,255);
        const x=positions.length ? Math.max((w.start-segment.start)*69,xEnd+13) : 0;
        positions.push({word:w,x,width});
        anchors.push({t:w.start,x});
        xEnd=x+width;
      }
      const width=Math.max(baseWidth,xEnd+26);
      anchors.push({t:segment.end,x:width});
      function map(t){
        if(t<=anchors[0].t)return 0;
        for(let i=1;i<anchors.length;i++){
          if(t<=anchors[i].t){
            const a=anchors[i-1],b=anchors[i];
            return clamp(a.x+(b.x-a.x)*((t-a.t)/Math.max(.00001,b.t-a.t)),0,width);
          }
        }
        return width;
      }
      return {map,positions,width};
    }
    function render(words,chords=[],duration=0){
      originalWords=words||[];originalChords=chords||[];originalDuration=duration;
      root.replaceChildren();
      // Offset positivo = parole leggermente più tardi; gli accordi NON si spostano.
      const visualWords=(Array.isArray(words)?words:[]).map(w=>({...w,
        start:Math.max(0,Number(w.start)+lyricsOffset),
        end:Math.max(.01,Number(w.end)+lyricsOffset)}));
      model=buildSegments(visualWords,chords,duration);
      rows=[];wordEls=[];currentRow=-1;currentChord=-2;lastHorizontalTime=-1;
      const follow=makeEl('div','karaoke-follow');
      follow.setAttribute('aria-label','Accordo attuale e prossimo accordo');
      const top=makeEl('div','karaoke-follow-top');
      const block=makeEl('div','karaoke-follow-block');
      block.append(makeEl('span','karaoke-follow-caption','ACCORDO ATTUALE'));
      nowEl=makeEl('strong','karaoke-follow-now','—');block.append(nowEl);
      const upcoming=makeEl('div','karaoke-follow-block karaoke-follow-secondary');
      upcoming.append(makeEl('span','karaoke-follow-caption','PROSSIMO'));
      nextEl=makeEl('strong','karaoke-follow-next','—');upcoming.append(nextEl);
      untilEl=makeEl('span','karaoke-follow-until','');upcoming.append(untilEl);
      top.append(block,upcoming);follow.append(top);
      const rail=makeEl('div','karaoke-follow-rail');
      fillEl=makeEl('span','karaoke-follow-fill');rail.append(fillEl);follow.append(rail);
      root.append(follow);
      if(!model.segments.length){
        root.append(makeEl('p','karaoke-empty','Non sono ancora disponibili parole o accordi per questo brano.'));
        return;
      }
      model.segments.forEach((segment,index)=>{
        const instrumental=segment.type==='instrumental';
        const section=makeEl('section','karaoke-section '+(instrumental?'karaoke-instrumental':'karaoke-sung'));
        if(instrumental){
          const header=makeEl('div','karaoke-section-head',`♪ ${segment.label} · ${stamp(segment.start)}–${stamp(segment.end)}`);
          section.append(header);
        }
        const scroll=makeEl('div','karaoke-section-scroll');
        const stage=makeEl('div','karaoke-timed-stage');
        const period=Math.max(.1,segment.end-segment.start);
        let width=Math.max(300,Math.round(period*(instrumental?42:66))+42);
        let map,positions=[];
        if(!instrumental){
          const info=makeTimeMap(segment,width);
          map=info.map;positions=info.positions;width=info.width;
        } else {map=t=>clamp((t-segment.start)/period*width,0,width);}
        stage.style.width=`${Math.ceil(width)}px`;
        const markerIndices=[];
        const carried=chordAt(model.chords,segment.start);
        const prev=model.segments[index-1];
        // Mostra l'accordo d'ingresso solo se non viene gia' ripetuto dal verso precedente.
        const enteredDuringGap=carried>=0 && prev && model.chords[carried].start>prev.end+0.01;
        if(carried>=0 && (index===0 || enteredDuringGap))markerIndices.push(carried);
        model.chords.forEach((c,i)=>{
          if(c.start>=segment.start-.0001 && c.start<segment.end-.0001)markerIndices.push(i);
        });
        const unique=[...new Set(markerIndices)].sort((a,b)=>model.chords[a].start-model.chords[b].start);
        const laneEnds=[-100,-100];
        const chordMarkers=[];
        for(const idx of unique){
          const chord=model.chords[idx];
          const at=clamp(chord.start,segment.start,segment.end);
          const x=map(at);
          const label=String(formatChord(chord.chord)||'—');
          // Sopprimere i marker "nessun accordo"; il tempo continua normalmente.
          if(label==='—'||chord.chord==='N')continue;
          const btn=makeEl('button','karaoke-time-chord',label);
          btn.type='button';
          btn.title=`${label} · ${stamp(chord.start)} (${chord.start.toFixed(2)} s)`;
          const w=clamp(label.length*9+25,46,100);
          let lane=laneEnds.findIndex(end=>x>=end+6);
          if(lane<0)lane=laneEnds.indexOf(Math.min(...laneEnds));
          laneEnds[lane]=x+w;
          btn.style.left=`${Math.round(x)}px`;
          btn.style.top=`${3+lane*25}px`;
          btn.addEventListener('click',()=>onSeek?.(chord.start));
          stage.append(btn);
          chordMarkers.push({button:btn,index:idx});
        }
        if(!instrumental && chordMarkers.length===0) section.className+=' karaoke-no-local-chords';
        if(!instrumental){
          positions.forEach(({word,x})=>{
            const button=makeEl('button','karaoke-time-word',String(word.text||''));
            button.type='button';
            button.title=`${word.start.toFixed(2)}–${word.end.toFixed(2)} s`;
            button.style.left=`${Math.round(x)}px`;
            button.addEventListener('click',()=>isEditing()?onWordClick?.(word.index):onSeek?.(word.start));
            stage.append(button);
            wordEls.push({button,word});
          });
        }
        scroll.append(stage);section.append(scroll);root.append(section);
        rows.push({section,scroll,segment,map,chordMarkers});
      });
    }
    function tick(time,autoScroll=true){
      const t=Math.max(0,num(time)||0);
      for(const {button,word} of wordEls){
        button.classList.toggle('singing',t>=word.start && t<word.end);
        button.classList.toggle('sung',t>=word.end);
      }
      const idx=chordAt(model.chords,t);
      if(idx!==currentChord){
        for(const row of rows)for(const marker of row.chordMarkers){
          marker.button.classList.toggle('current',marker.index===idx);
        }
        currentChord=idx;
      }
      const chord=idx>=0?model.chords[idx]:null;
      if(nowEl)nowEl.textContent=chord?String(formatChord(chord.chord)||'—'):'—';
      let upcoming=null;
      for(const candidate of model.chords){
        if(candidate.start>t+.001 && candidate.chord!=='N' && (!chord || candidate.chord!==chord.chord)){
          upcoming=candidate;break;
        }
      }
      if(nextEl)nextEl.textContent=upcoming?String(formatChord(upcoming.chord)||'—'):'—';
      if(untilEl)untilEl.textContent=upcoming?`tra ${Math.max(0,upcoming.start-t).toFixed(1)} s`:'';
      if(fillEl){
        const progress=chord?100*clamp((t-chord.start)/Math.max(.001,chord.end-chord.start),0,1):0;
        fillEl.style.width=`${progress.toFixed(1)}%`;
      }
      // Se non si canta per pochi secondi, lasciare evidenziato il verso precedente.
      // Gli accordi cambiano COMUNQUE al timestamp esatto tramite la barra sopra.
      let rowIndex=-1;
      for(let i=0;i<rows.length;i++){
        if(rows[i].segment.start<=t+.0001)rowIndex=i;
        else break;
      }
      if(rowIndex<0 && rows.length)rowIndex=0;
      if(rowIndex!==currentRow){
        rows.forEach((row,i)=>row.section.classList.toggle('line-current',i===rowIndex));
        if(autoScroll && rowIndex>=0 && !isEditing() && root.clientHeight>0 && root.scrollHeight>root.clientHeight){
          const line=rows[rowIndex].section;
          const y=line.getBoundingClientRect().top-root.getBoundingClientRect().top+root.scrollTop;
          const target=Math.max(0,y-root.clientHeight*.35);
          if(Math.abs(target-root.scrollTop)>28)root.scrollTo?.({top:target,behavior:'smooth'});
        }
        currentRow=rowIndex;
      }
      if(autoScroll&&rowIndex>=0&&!isEditing()&&Math.abs(t-lastHorizontalTime)>.1){
        const row=rows[rowIndex];
        const center=row.map(clamp(t,row.segment.start,row.segment.end));
        const viewport=row.scroll.clientWidth||320;
        const left=Math.max(0,center-viewport*.34);
        // Solo il verso attivo si muove orizzontalmente.
        if(Math.abs((row.scroll.scrollLeft||0)-left)>9){
          row.scroll.scrollTo?.({left,behavior:'auto'});
        }
        lastHorizontalTime=t;
      }
    }
    function setOffset(value){
      const n=Number(value);
      lyricsOffset=Number.isFinite(n)?Math.max(-5,Math.min(5,n)):0;
      render(originalWords,originalChords,originalDuration);
    }
    return {render,tick,setOffset,getOffset:()=>lyricsOffset};
  }
  window.GuitarKaraoke={make,buildSegments,chordAt};
})();
