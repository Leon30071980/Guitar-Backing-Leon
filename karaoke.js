"use strict";
/* Guitar Backing Leon 2.16.2 — lettura continua da chitarrista.
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
      if(!tail || tail.line!==w.line){
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
  // Anticipo SOLO del focus visivo: i timestamp di accordi e parole restano identici.
  const FOCUS_PREVIEW_SECONDS = 0.35;
  const MAX_EARLY_CHORD_SECONDS = 4;

  function focusStartForSegment(segment, previous, chords) {
    if (segment.type !== 'words') return segment.start;
    let focus = Math.max(0, segment.start - FOCUS_PREVIEW_SECONDS);

    // Un accordo iniziato nella pausa dopo il verso precedente può introdurre
    // il verso nuovo. Lo associamo solo se è ancora attivo alla prima parola,
    // evitando di prendere accordi di strofe precedenti o di lunghi interludi.
    if (previous?.type === 'words') {
      const idx = chordAt(chords, segment.start);
      const entry = idx >= 0 ? chords[idx] : null;
      if (entry && entry.chord !== 'N' &&
          entry.start >= previous.end - 0.0001 &&
          entry.start < segment.start - 0.0001 &&
          segment.start - entry.start <= MAX_EARLY_CHORD_SECONDS) {
        focus = Math.min(focus, Math.max(0, entry.start - FOCUS_PREVIEW_SECONDS));
      }
      // Non passare al verso nuovo prima che finisca il testo ancora cantato.
      focus = Math.max(focus, previous.end);
    }
    return focus;
  }

  // Il karaoke è un leggio a tre posizioni fisse: precedente / corrente / prossimo.
  // Mai scorrere il testo in funzione dei secondi. Solo i colori cambiano parola per parola.
  function make({root,formatChord=(s=>s),onSeek,onWordClick,isEditing=()=>false}) {
    let model={segments:[],words:[],chords:[],duration:0};
    let lyricsOffset=0, originalWords=[],originalChords=[],originalDuration=0;
    let rows=[],wordEls=[],currentRow=-1,currentChord=-2,lastTickTime=0;
    let nowEl=null,nextEl=null,untilEl=null,fillEl=null;
    const ZOOM_KEY='gbl-karaoke-zoom';
    const ZOOM_MIN=.8,ZOOM_MAX=2.2,ZOOM_STEP=.2;
    let lyricScale=1;
    try {
      const saved=Number(localStorage.getItem(ZOOM_KEY));
      if(Number.isFinite(saved)&&saved>=ZOOM_MIN&&saved<=ZOOM_MAX)lyricScale=saved;
    }catch(_){}
    const buttonById=id=>typeof document.getElementById==='function'?document.getElementById(id):null;
    const zoomOut=buttonById('karaoke-zoom-out'),zoomIn=buttonById('karaoke-zoom-in'),zoomReset=buttonById('karaoke-zoom-reset');
    function applyZoomStyle(){
      root.style?.setProperty?.('--gbl-lyric-scale',String(lyricScale));
    }
    function updateZoomControls(){
      if(zoomReset){zoomReset.textContent=`${Math.round(lyricScale*100)}%`;zoomReset.title='Ripristina al 100%';}
      if(zoomOut)zoomOut.disabled=lyricScale<=ZOOM_MIN+.001;
      if(zoomIn)zoomIn.disabled=lyricScale>=ZOOM_MAX-.001;
    }
    function setZoom(value){
      const n=Number(value);
      if(!Number.isFinite(n))return;
      const next=Math.round(clamp(n,ZOOM_MIN,ZOOM_MAX)*100)/100;
      if(next===lyricScale)return;
      lyricScale=next;
      try{localStorage.setItem(ZOOM_KEY,String(lyricScale));}catch(_){}
      applyZoomStyle();updateZoomControls();
      // No rebuilding: preserves focus, highlighted word, seek state and DOM nodes.
    }
    zoomOut?.addEventListener('click',()=>setZoom(lyricScale-ZOOM_STEP));
    zoomIn?.addEventListener('click',()=>setZoom(lyricScale+ZOOM_STEP));
    zoomReset?.addEventListener('click',()=>setZoom(1));
    applyZoomStyle();updateZoomControls();

    function render(words,chords=[],duration=0){
      originalWords=words||[];originalChords=chords||[];originalDuration=duration;
      root.replaceChildren();
      const correctedTime=t=>Math.max(0,Number(t)+lyricsOffset);
      const visualWords=(Array.isArray(words)?words:[]).map(w=>{
        const start=correctedTime(w.start),end=correctedTime(w.end);
        return {...w,start,end:Math.max(start+.015,end)};
      });
      model=buildSegments(visualWords,chords,duration);
      rows=[];wordEls=[];currentRow=-1;currentChord=-2;
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
      const score=makeEl('div','karaoke-fixed-score');
      score.setAttribute('aria-label','Leggio karaoke: verso precedente, corrente e successivo');
      root.append(score);
      model.segments.forEach((segment,index)=>{
        const instrumental=segment.type==='instrumental';
        const previous=model.segments[index-1];
        const stanzaBreak=!instrumental && previous?.type==='words' && segment.line-previous.line>1;
        const section=makeEl('section','karaoke-section karaoke-fixed-line '+(instrumental?'karaoke-instrumental':'karaoke-sung')+(stanzaBreak?' karaoke-stanza-start':''));
        const header=makeEl('div','karaoke-fixed-label',instrumental?`♪ ${segment.label}`:`VERSO ${segment.line+1}`);
        section.append(header);
        const text=makeEl('div','karaoke-fixed-words');
        // Accord badges follow their timestamps, but live on a compact row;
        // they never stretch words according to their time coordinates.
        const strip=makeEl('div','karaoke-fixed-chords');
        const markers=[];
        const carried=chordAt(model.chords,segment.start);
        const enteredDuringGap=carried>=0 && previous && model.chords[carried].start>previous.end+0.01;
        const markerIndices=[];
        if(carried>=0&&(index===0||enteredDuringGap))markerIndices.push(carried);
        model.chords.forEach((c,i)=>{
          if(c.start>=segment.start-.0001&&c.start<segment.end-.0001)markerIndices.push(i);
        });
        const unique=[...new Set(markerIndices)].sort((a,b)=>model.chords[a].start-model.chords[b].start);
        unique.forEach(idx=>{
          const chord=model.chords[idx],label=String(formatChord(chord.chord)||'—');
          if(chord.chord==='N'||label==='—')return;
          const btn=makeEl('button','karaoke-time-chord',label);
          btn.type='button';btn.title=`${label} · ${stamp(chord.start)} (${chord.start.toFixed(2)} s)`;
          btn.addEventListener('click',()=>onSeek?.(chord.start));
          strip.append(btn);markers.push({button:btn,index:idx});
        });
        section.append(strip);
        if(!markers.length)section.className+=' karaoke-no-local-chords';
        if(!instrumental){
          segment.words.forEach(word=>{
            const btn=makeEl('button','karaoke-time-word',String(word.text||''));
            btn.type='button';btn.title=`${word.start.toFixed(2)}–${word.end.toFixed(2)} s`;
            btn.addEventListener('click',()=>isEditing()?onWordClick?.(word.index):onSeek?.(word.start));
            text.append(btn);wordEls.push({button:btn,word});
          });
        }else{
          text.append(makeEl('span','karaoke-instrumental-label','♪ Intervallo musicale'));
        }
        section.append(text);score.append(section);
        rows.push({section,segment,chordMarkers:markers,focusStart:focusStartForSegment(segment,previous,model.chords)});
      });
      tick(lastTickTime,false);
    }
    function tick(time,_autoScroll=true){
      const t=Math.max(0,num(time)||0);
      lastTickTime=t;
      for(const {button,word} of wordEls){
        button.classList.toggle('singing',t>=word.start&&t<word.end);
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
        if(candidate.start>t+.001&&candidate.chord!=='N'&&(!chord||candidate.chord!==chord.chord)){
          upcoming=candidate;break;
        }
      }
      if(nextEl)nextEl.textContent=upcoming?String(formatChord(upcoming.chord)||'—'):'—';
      if(untilEl)untilEl.textContent=upcoming?`tra ${Math.max(0,upcoming.start-t).toFixed(1)} s`:'';
      if(fillEl){
        const progress=chord?100*clamp((t-chord.start)/Math.max(.001,chord.end-chord.start),0,1):0;
        fillEl.style.width=`${progress.toFixed(1)}%`;
      }
      let rowIndex=-1;
      for(let i=0;i<rows.length;i++){
        if(rows[i].focusStart<=t+.0001)rowIndex=i;else break;
      }
      if(rowIndex<0&&rows.length)rowIndex=0;
      if(rowIndex!==currentRow){
        rows.forEach((row,i)=>{
          row.section.classList.toggle('line-current',i===rowIndex);
          row.section.classList.toggle('karaoke-prev',i===rowIndex-1);
          row.section.classList.toggle('karaoke-next',i===rowIndex+1);
          row.section.setAttribute('aria-hidden',Math.abs(i-rowIndex)>1?'true':'false');
        });
        currentRow=rowIndex;
      }
      // Intentional: no scrollTo(), no scrollLeft, no moving timeline.
    }
    function setOffset(value){
      const n=Number(value);
      lyricsOffset=Number.isFinite(n)?Math.max(-5,Math.min(5,n)):0;
      render(originalWords,originalChords,originalDuration);
    }
    return {render,tick,setOffset,getOffset:()=>lyricsOffset,setZoom,getZoom:()=>lyricScale};
  }
  window.GuitarKaraoke={make,buildSegments,chordAt};
})();
