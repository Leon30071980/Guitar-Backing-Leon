"use strict";
/* Stato di preparazione e pannelli compatti - PC e iPhone.
 * Play non deve partire finche' base, mixer e caricamento karaoke non sono pronti.
 */
(function () {
  const flags={audio:false,mixer:false,lyrics:false};
  let loaded=false;
  let errorMessage='';
  let phaseMessage='Preparazione del brano...';
  const audio=document.getElementById('audio-player') || document.getElementById('player');
  const status=document.getElementById('playback-readiness');
  function isReady(){return loaded && flags.audio && flags.mixer && flags.lyrics && !errorMessage;}
  function refresh(){
    const ready=isReady();
    if(status){
      status.classList.remove('gbl-loading','gbl-ready','gbl-failed');
      status.classList.add(ready?'gbl-ready':errorMessage?'gbl-failed':'gbl-loading');
      status.textContent=ready?'✓ TUTTO PRONTO · PUÒ PREMERE PLAY':errorMessage?'⚠ '+errorMessage:'⏳ '+phaseMessage;
      status.setAttribute('aria-label',ready?'Riproduzione pronta':errorMessage?'Preparazione non riuscita':'Preparazione in corso');
    }
    const smallTag=document.getElementById('player-ready-tag');
    if(smallTag){smallTag.textContent=ready?'PRONTA':errorMessage?'ERRORE':'PREPARAZIONE';smallTag.classList.toggle('gbl-tag-ready',ready);smallTag.classList.toggle('gbl-tag-wait',!ready&&!errorMessage);}
    document.dispatchEvent(new Event('gbl-readiness-change'));
  }
  function reset(){
    loaded=true;errorMessage='';phaseMessage='Caricamento traccia audio...';
    flags.audio=false;flags.mixer=false;flags.lyrics=false;
    if(audio && !audio.paused)audio.pause();
    refresh();
  }
  function setAudio(value){
    flags.audio=Boolean(value);
    if(flags.audio && !flags.mixer) phaseMessage='Preparazione mixer...';
    if(flags.audio && flags.mixer && !flags.lyrics)phaseMessage='Preparazione karaoke...';
    refresh();
  }
  function setMixer(value,reason=''){
    flags.mixer=Boolean(value);
    if(!value && reason)errorMessage=String(reason);
    else if(value)errorMessage='';
    phaseMessage=value?(flags.lyrics?'Verifica audio...':'Caricamento testo karaoke...'):'Preparazione mixer...';
    refresh();
  }
  function setLyrics(value=true){
    flags.lyrics=Boolean(value);
    if(!flags.lyrics)phaseMessage='Caricamento testo karaoke...';
    else if(!flags.mixer)phaseMessage='Preparazione mixer...';
    refresh();
  }
  function fail(message){errorMessage=String(message||'Preparazione non riuscita');refresh();}
  if(audio){
    audio.addEventListener('canplay',()=>{if(loaded)setAudio(true);});
    audio.addEventListener('error',()=>{if(loaded)fail('Audio non disponibile. Riapra il brano.');});
    audio.addEventListener('emptied',()=>{if(loaded && !audio.getAttribute('src'))setAudio(false);});
  }
  function initCollapse(){
    // I contenuti non sono rimossi dal DOM: dati, event handlers e traccia audio restano intatti.
    const panels=[...document.querySelectorAll('.panel')];
    for(const panel of panels){
      let heading=[...panel.children].find(x=>x.classList?.contains('panel-heading')||x.classList?.contains('section-head'));
      if(!heading){
        const h=[...panel.children].find(x=>x.tagName==='H2');
        if(!h)continue;
        heading=document.createElement('div');heading.className='gbl-panel-head';
        panel.insertBefore(heading,h);heading.appendChild(h);
      }
      heading.classList.add('gbl-collapse-heading');
      if(heading.querySelector('.gbl-collapse-btn'))continue;
      const btn=document.createElement('button');btn.type='button';btn.className='secondary gbl-collapse-btn';
      btn.textContent='−';btn.title='Riduci pannello';btn.setAttribute('aria-expanded','true');btn.setAttribute('aria-label','Riduci pannello');
      btn.addEventListener('click',()=>{
        const collapsed=panel.classList.toggle('gbl-panel-collapsed');
        btn.textContent=collapsed?'+':'−';btn.title=collapsed?'Apri pannello':'Riduci pannello';btn.setAttribute('aria-label',btn.title);btn.setAttribute('aria-expanded',String(!collapsed));
      });
      heading.appendChild(btn);
    }
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',initCollapse,{once:true});
  else initCollapse();
  window.GuitarAppReady={reset,setAudio,setMixer,setLyrics,fail,isReady};
  refresh();
})();
