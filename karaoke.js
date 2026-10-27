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
  // Le sezioni strumentali hanno una timeline armonica indipendente dalle parole.
  // Sono rese anche per pause brevi se vi sono cambi di accordo; nessun cambio
  // puo' sparire solo perche' non esiste una parola a cui agganciarlo.
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
    const hasChordChange=(start,end)=>chords.filter(c=>c.chord!=='N' && c.start>=start-.0001 && c.start<end-.0001).length;
    const meaningfulGap=(start,end)=>{
      const length=end-start;
      // Una pausa breve con un solo cambio non deve oscurare l'ANTEPRIMA
      // della frase successiva: il cambio e' mostrato nel ponte strumentale.
      // Gli assoli e i veri intermezzi restano invece sezioni autonome.
      return length>=5.0 || (length>=1.3 && hasChordChange(start,end)>=2);
    };
    const phrases=[];
    for(const w of words){
      const tail=phrases[phrases.length-1];
      // Alcune importazioni A&S conservano lo stesso numero di verso anche ai
      // lati di un assolo: spezzarlo qui evita di nascondere la pausa nel verso.
      if(!tail || tail.line!==w.line || (w.start-tail.end>=.45 && meaningfulGap(tail.end,w.start))){
        phrases.push({type:'words',line:w.line,start:w.start,end:w.end,words:[w]});
      }else{tail.words.push(w);tail.end=Math.max(tail.end,w.end);}
    }
    const segments=[];
    function addGap(start,end,position){
      if(end-start<.05)return;
      if(!phrases.length || meaningfulGap(start,end)){
        const name=!phrases.length?'Parte strumentale':position==='start'?'Intro strumentale':
          position==='end'?'Finale strumentale':'Intermezzo / assolo';
        segments.push({type:'instrumental',start,end,label:name});
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
  function make({root,formatChord=(s=>s),onSeek,onWordClick,onChordClick,isEditing=()=>false}) {
    let model={segments:[],words:[],chords:[],duration:0};
    let lyricsOffset=0, originalWords=[],originalChords=[],originalDuration=0;
    let rows=[],wordEls=[],currentRow=-1,currentChord=-2,lastTickTime=0;
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
      // Solo leggio a tre righe: nessun riquadro separato attuale/prossimo.
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
        const following=model.segments[index+1];
        const bridgeEnd=!instrumental && following?.type==='words' ? following.start : segment.end;
        const bridgeMarkers=[];
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
        const anchoredWords=new Set(instrumental?[]:segment.words.map(w=>w.index));
        // La priorita' e' musicale: durante l'assolo contano i timestamp,
        // anche se l'importatore aveva associato l'accordo a un indice parola.
        const instrumentalAt=time=>model.segments.some(s=>s.type==='instrumental' &&
          time>=s.start-.0001 && time<s.end-.0001);
        if(instrumental){
          if(carried>=0)markerIndices.push(carried); // accordo gia' attivo all'inizio
          model.chords.forEach((c,i)=>{
            if(c.start>=segment.start-.0001 && c.start<segment.end-.0001)markerIndices.push(i);
          });
        }else{
          // Mostra sul primo vocabolo anche l'accordo gia' in corso quando
          // inizia un verso, inclusa l'anteprima del verso successivo.
          // Non si genera un nuovo cambio: e' soltanto una ripetizione visiva.
          if(carried>=0 && model.chords[carried].chord!=='N' &&
             model.chords[carried].start<=segment.start+.04)markerIndices.push(carried);
          model.chords.forEach((c,i)=>{
            if(instrumentalAt(c.start))return; // evita doppi marker nei versi
            if(Number.isInteger(c.word_index) && anchoredWords.has(c.word_index))markerIndices.push(i);
            else if(c.start>=segment.start-.0001 && c.start<bridgeEnd-.0001)markerIndices.push(i);
          });
        }
        const unique=[...new Set(markerIndices)].sort((a,b)=>model.chords[a].start-model.chords[b].start);
        const wordChords=new Map();
        unique.forEach(idx=>{
          const chord=model.chords[idx],label=String(formatChord(chord.chord)||'—');
          if(chord.chord==='N'||label==='—')return;
          const wrap=makeEl('span','gbl-chord-with-tip');
          const btn=makeEl('button','karaoke-time-chord',label);
          wrap.append(btn);
          if(window.GuitarChordTools?.diagram && label!=='—')wrap.append(window.GuitarChordTools.diagram(label));
          btn.type='button';btn.title=`${label} · ${stamp(chord.start)} (${chord.start.toFixed(2)} s)`;
          btn.addEventListener('click',()=>isEditing() && onChordClick ? onChordClick(idx) : onSeek?.(chord.start));
          if(instrumental){strip.append(wrap);}
          else if(chord.start>=segment.end-.001 && chord.start<bridgeEnd-.001){
            bridgeMarkers.push(wrap);
          }else {
            // A&S restituisce un indice esatto della parola. Per gli accordi AI
            // privi di indice usiamo la parola temporalmente piu' vicina.
            const anchored=Number.isInteger(chord.word_index)?
              segment.words.find(w=>w.index===chord.word_index &&
                Math.abs(w.start-chord.start)<Math.max(1.6,w.end-w.start+.4)):null;
            const nearest=anchored || segment.words.reduce((best,w)=>
              (!best || Math.abs(w.start-chord.start)<Math.abs(best.start-chord.start))?w:best,null);
            if(nearest){
              if(!wordChords.has(nearest.index))wordChords.set(nearest.index,[]);
              wordChords.get(nearest.index).push(wrap);
            }
          }
          markers.push({button:btn,index:idx});
        });
        if(instrumental){
          if(!markers.length){
            strip.append(makeEl('span','karaoke-instrumental-missing',
              'Accordi non disponibili: aggiungere i cambi dal pannello 03 sul PC'));
          }
          section.append(strip);
        }
        if(!markers.length)section.className+=' karaoke-no-local-chords';
        if(!instrumental){
          segment.words.forEach(word=>{
            const btn=makeEl('button','karaoke-time-word',String(word.text||''));
            btn.type='button';btn.title=`${word.start.toFixed(2)}–${word.end.toFixed(2)} s`;
            btn.addEventListener('click',()=>isEditing()?onWordClick?.(word.index):onSeek?.(word.start));
            const pair=makeEl('span','karaoke-word-pair');
            const above=makeEl('span','karaoke-word-above');
            for(const marker of wordChords.get(word.index)||[])above.append(marker);
            pair.append(above,btn);text.append(pair);
            wordEls.push({button:btn,word});
          });
        }else{
          text.append(makeEl('span','karaoke-instrumental-label','♪ Intervallo musicale'));
        }
        section.append(text);
        if(bridgeMarkers.length){
          const bridge=makeEl('div','karaoke-bridge-chords');
          bridge.append(makeEl('span','karaoke-bridge-label','♪'));
          for(const marker of bridgeMarkers)bridge.append(marker);
          section.append(bridge);
        }
        score.append(section);
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
      let rowIndex=-1;
      for(let i=0;i<rows.length;i++){
        if(rows[i].focusStart<=t+.0001)rowIndex=i;else break;
      }
      if(rowIndex<0&&rows.length)rowIndex=0;
      const shifted=rowIndex!==currentRow;
      if(shifted){
        rows.forEach((row,i)=>{
          row.section.classList.toggle('line-current',i===rowIndex);
          row.section.classList.toggle('karaoke-prev',i===rowIndex-1);
          row.section.classList.toggle('karaoke-next',i===rowIndex+1);
          row.section.setAttribute('aria-hidden',Math.abs(i-rowIndex)>1?'true':'false');
        });
        currentRow=rowIndex;
      }
      const idx=chordAt(model.chords,t);
      if(idx!==currentChord||shifted){
        for(const row of rows)for(const marker of row.chordMarkers){
          const active=marker.index===idx && row.section.classList.contains('line-current');
          marker.button.classList.toggle('current',active);
          marker.button.setAttribute('aria-current',active?'true':'false');
          if(active){
            const strip=marker.button.closest('.karaoke-fixed-chords');
            if(strip && strip.scrollWidth>strip.clientWidth){
              strip.scrollLeft=Math.max(0,marker.button.parentElement.offsetLeft-strip.clientWidth/3);
            }
          }
        }
        currentChord=idx;
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
