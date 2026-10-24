/* Guitar Backing Leon — integrazione A&S senza modificare l'audio o config.js.
 * Da includere dopo app.js, con <script defer src="./as_corrector.js"></script>.
 * Funziona nell'interfaccia web del PC quando l'app Flask locale è attiva.
 */
(() => {
  'use strict';
  const ENDPOINT='http://127.0.0.1:8765/api/as/';
  const $as=id=>document.getElementById(id);
  const el=(tag,props={},content='')=>{
    const node=document.createElement(tag);Object.assign(node,props);
    if(content)node.textContent=content;return node;
  };
  const css=`
  .as-dialog{border:1px solid #4b5563;border-radius:14px;background:#111827;color:#f9fafb;width:min(96vw,650px);max-height:90vh;overflow-y:auto;padding:20px;box-shadow:0 18px 65px #0009;font:inherit}
  .as-dialog::backdrop{background:#000a}.as-dialog label{display:grid;gap:5px;margin:10px 0}.as-dialog input[type=text],.as-dialog input[type=url]{width:100%;padding:11px;border-radius:8px;border:1px solid #6b7280;background:#1f2937;color:inherit;font:inherit}
  .as-dialog .as-row{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}.as-dialog button{cursor:pointer;border-radius:7px;border:1px solid #4b5563;padding:9px 12px;background:#374151;color:#fff;font:inherit}.as-dialog button:disabled{opacity:.45;cursor:wait}.as-dialog button.as-main{background:#2563eb;border-color:#2563eb;font-weight:700}
  .as-dialog .as-hint{color:#cbd5e1;font-size:.88em}.as-dialog #as-state{min-height:1.7em;margin-top:12px}.as-dialog .as-choices{max-height:180px;overflow:auto;display:grid;gap:5px}.as-dialog .as-choice{width:100%;text-align:left}.as-dialog .as-options{display:flex;gap:16px;flex-wrap:wrap;margin:10px 0}.as-dialog .as-options label{display:flex;flex-direction:row;gap:6px}
  .as-dialog .as-summary{padding:10px;background:#1f2937;border-radius:9px;margin:12px 0;white-space:pre-wrap}.as-dialog small{color:#cbd5e1}
  `;
  const style=el('style');style.textContent=css;document.head.append(style);
  const btn=el('button',{id:'as-correct-trigger',type:'button',className:'secondary'},'🎼 Correggi tramite A&S');
  const bar=document.querySelector('#karaoke-panel .karaoke-heading-actions') || document.querySelector('#karaoke-panel .panel-heading');
  if(!bar)return;
  bar.prepend(btn);
  const dlg=el('dialog',{className:'as-dialog'});
  dlg.innerHTML=`<h2>Correggi tramite A&S</h2>
    <p class="as-hint">Importa privatamente testo e accordi dalle pagine pubbliche di Accordi e Spartiti. Il PC Windows deve essere acceso, con il server Guitar Backing Leon avviato. Non sono richieste password A&S.</p>
    <label>Titolo del brano<input id="as-title" type="text" maxlength="90" autocomplete="off"></label>
    <label>Artista<input id="as-artist" type="text" maxlength="90" autocomplete="off"></label>
    <div class="as-row"><button id="as-search" type="button">Cerca brano su A&S</button></div>
    <div id="as-matches" class="as-choices"></div>
    <label>URL del brano A&S (se lo conosce)<input id="as-url" type="url" placeholder="https://www.accordiespartiti.it/accordi/…"></label>
    <div class="as-row"><button id="as-preview" type="button">Importa e confronta</button></div>
    <div id="as-state" role="status" aria-live="polite"></div>
    <div id="as-result" hidden>
      <div class="as-summary" id="as-summary"></div>
      <div class="as-options"><label><input id="as-fix-lyrics" type="checkbox" checked> Correggi parole</label>
      <label><input id="as-fix-chords" type="checkbox" checked> Correggi accordi</label></div>
      <p class="as-hint">Controlli titolo e artista prima di applicare. La sincronizzazione deriva dall'audio e resta una stima; gli accordi vanno verificati a orecchio.</p>
      <div class="as-row"><button id="as-save" type="button" class="as-main">Applica e salva nella libreria privata</button></div>
    </div><div class="as-row"><button id="as-close" type="button">Annulla / Chiudi</button></div>`;
  document.body.append(dlg);
  const state=(message,error=false)=>{const p=$as('as-state');p.textContent=message;p.style.color=error?'#fda4af':'#bfdbfe';};
  let preview=null, selectedId=null, busy=false;
  const disable=(on)=>{busy=on;['as-search','as-preview','as-save'].forEach(id=>{const node=$as(id);if(node)node.disabled=on;});};
  const show=()=>{
    if(typeof current==='undefined'||!current){alert('Selezionare prima una canzone.');return;}
    selectedId=String(current.id);
    preview=null;$as('as-result').hidden=true;$as('as-matches').replaceChildren();
    const name=String(current.name||'').replace(/\.(?:mp3|wav|flac|m4a)$/i,'');
    const bits=name.split(/\s+[-–]\s+/);
    $as('as-title').value=bits[0]||name;$as('as-artist').value=bits.length>1?bits.slice(1).join(' - '):'';
    $as('as-url').value='';state('');dlg.showModal();
  };
  btn.addEventListener('click',show);
  $as('as-close').addEventListener('click',()=>{if(!busy)dlg.close();});
  async function call(action,payload){
    let response;
    try{response=await fetch(ENDPOINT+action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});}
    catch(err){throw new Error('Impossibile contattare il server locale. Avviare Guitar Backing Leon sul PC (porta 8765), quindi riprovare. Da iPhone il servizio locale non è raggiungibile.');}
    const result=await response.json().catch(()=>({}));
    if(!response.ok)throw new Error(result.error||'Importazione non disponibile (HTTP '+response.status+').');
    return result;
  }
  $as('as-search').addEventListener('click',async()=>{
    disable(true);state('Ricerca nel catalogo A&S...');$as('as-matches').replaceChildren();
    try{
      const results=await call('search',{title:$as('as-title').value,artist:$as('as-artist').value});
      if(!results.matches?.length){state('Nessun risultato: può inserire direttamente l’URL della scheda A&S.');return;}
      const container=$as('as-matches');
      results.matches.forEach(item=>{
        const choice=el('button',{className:'as-choice',type:'button'},item.title);
        choice.addEventListener('click',()=>{$as('as-url').value=item.url;state('Scheda selezionata. Cliccare Importa e confronta.');});
        container.append(choice);
      });
      state(`${results.matches.length} scheda/e candidate: scelga quella della stessa registrazione.`);
    }catch(e){state(e.message,true);}finally{disable(false);}
  });
  $as('as-preview').addEventListener('click',async()=>{
    if(!current||String(current.id)!==selectedId){state('Il brano selezionato è cambiato: riaprire la finestra.',true);return;}
    const url=$as('as-url').value.trim();if(!url){state('Selezionare un risultato o inserire un URL A&S.',true);return;}
    if(typeof karaokeWords==='undefined'||karaokeWords.length<3){state('Serve il karaoke AI già elaborato per riallineare le parole.',true);return;}
    disable(true);$as('as-result').hidden=true;state('Lettura A&S e confronto con i tempi AI...');
    try{
      preview=await call('preview',{url,words:karaokeWords,chords:current.chords||[],duration:current.duration||0});
      if(String(current.id)!==selectedId)throw new Error('È stato cambiato il brano durante l’importazione.');
      const st=preview.stats;
      $as('as-summary').textContent=`Parole A&S: ${st.source_words} · corrispondenza AI: ${Math.round(100*st.text_match)}%\nAccordi A&S collegati alle parole: ${st.source_chords} · eventi finali: ${st.final_chord_events}\nAnteprima testo corretto: ${preview.words.slice(0,12).map(w=>w.text).join(' ')} ...\nFonte: ${preview.url}`;
      $as('as-result').hidden=false;state('Anteprima pronta. Il salvataggio avverrà solo dopo conferma.');
    }catch(e){preview=null;state(e.message,true);}finally{disable(false);}
  });
  async function updateFile(fileId,json){
    return api(`${UPLOAD}/${encodeURIComponent(fileId)}?uploadType=media&fields=id`,{
      method:'PATCH',headers:{'Content-Type':'application/json'},
      body:new Blob([JSON.stringify(json,null,2)],{type:'application/json'})
    });
  }
  $as('as-save').addEventListener('click',async()=>{
    if(!preview||!current||String(current.id)!==selectedId){state('L’anteprima non appartiene più al brano selezionato.',true);return;}
    const fixLyrics=$as('as-fix-lyrics').checked,fixChords=$as('as-fix-chords').checked;
    if(!fixLyrics&&!fixChords){state('Selezionare almeno una correzione.',true);return;}
    if(fixLyrics&&!current.lyricsFileId){state('Generare il file karaoke dal PC prima di usare la correzione A&S.',true);return;}
    if(!confirm('Salvare le correzioni A&S nel Suo Google Drive privato? Il PC non deve sincronizzare contemporaneamente.'))return;
    disable(true);state('Salvataggio su Google Drive in corso...');
    try{
      const song=current;
      // Rilettura dell'indice per non sovrascrivere altri brani aggiornati nel frattempo.
      const index=await jsonFile(tree.index);
      const entry=(index.songs||[]).find(x=>String(x.id)===selectedId);
      if(!entry)throw new Error('Brano non più presente nell’indice Drive. Aggiornare la libreria.');
      if(fixLyrics){
        const oldData=await jsonFile(song.lyricsFileId);
        const newData={...oldData,as_backup_words:oldData.as_backup_words||oldData.words,words:preview.words,source:'accordiespartiti',source_url:preview.url,
          corrected_at:new Date().toISOString(),alignment_confidence:preview.stats.text_match};
        await updateFile(song.lyricsFileId,newData);
      }
      if(fixChords){
        entry.chords_as_backup=entry.chords_as_backup||entry.chords;
        entry.chords=preview.chords;entry.chord_source='accordiespartiti';
        entry.chord_source_url=preview.url;
        await cloudSaveIndex(index);
      }
      if(fixLyrics)karaokeWords=preview.words;
      if(fixChords){song.chords=preview.chords;song.chord_source='accordiespartiti';}
      if(fixLyrics||fixChords){
        renderChords(song.chords||[]);
        karaokeView.render(karaokeWords,song.chords||[],Number(song.duration)||0);
        karaokeView.tick($as('player').currentTime,false);
        syncChords();
        $as('chord-engine-source').textContent=fixChords?'Accordi importati da A&S (verificare a orecchio).':$as('chord-engine-source').textContent;
        $as('karaoke-status').textContent=`${karaokeWords.length} parole · Correzione A&S salvata nella libreria privata.`;
      }
      preview=null;$as('as-result').hidden=true;
      state('Correzione salvata su Drive. Può chiudere la finestra e suonare il brano.');
    }catch(e){state('Salvataggio non completato: '+e.message+'. Verificare e aggiornare la libreria prima di riprovare.',true);}
    finally{disable(false);}
  });
})();
