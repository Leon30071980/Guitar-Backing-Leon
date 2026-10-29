/* Guitar Backing Leon web v2.65: comando CarPlay esplicito.
   Nessun reload, nessun tap sulla versione, nessuna modifica OAuth.
   Il Companion nativo iOS resta necessario per la Live Activity su CarPlay.
*/
(()=>{
  'use strict';
  const button=document.getElementById('gbl-carplay-send');
  const status=document.getElementById('gbl-carplay-status');
  if(!button)return;

  function message(text){
    if(status){status.textContent=text;status.hidden=false;}
  }
  function snapshot(){
    try{
      return typeof window.GBLCarPlaySource==='function'?window.GBLCarPlaySource():null;
    }catch(error){return null;}
  }
  function refresh(){
    const song=snapshot();
    const ready=!!(song?.songId&&Array.isArray(song.words)&&song.words.length);
    button.setAttribute('aria-label',ready?'Invia parole sincronizzate al Companion CarPlay':'CarPlay: seleziona un brano con karaoke pronto');
    button.title=ready?'Invia testo e posizione al Companion iOS':'Seleziona un brano e attendi il caricamento del karaoke';
    button.classList.toggle('gbl-carplay-ready',ready);
    // Il pulsante resta premibile per spiegare quale requisito manca.
  }
  function send(){
    const protocol=window.GuitarCarPlayProtocol;
    if(!protocol||typeof protocol.link!=='function'){
      message('Modulo CarPlay non caricato. Verifica carplay_protocol.js e ricarica la pagina.');
      return false;
    }
    const song=snapshot();
    if(!song?.songId){
      message('Prima seleziona una canzone nella libreria.');
      return false;
    }
    if(!Array.isArray(song.words)||!song.words.length){
      message('Attendi il caricamento del testo karaoke per questo brano.');
      return false;
    }
    try{
      const link=protocol.link(song);
      if(typeof link!=='string'||!link.startsWith('guitarleoncarplay://sync?data='))throw new Error('Link non valido');
      message('Apertura di CarPlay Companion… Il Companion iOS deve essere installato; questo pulsante non apre direttamente lo schermo dell’auto.');
      // Apertura ESPLICITA dell'app nativa; non ricarica Guitar Backing Leon.
      window.location.assign(link);
      return true;
    }catch(error){
      message('Non è stato possibile preparare il karaoke per CarPlay.');
      return false;
    }
  }
  button.addEventListener('click',event=>{
    event.preventDefault();
    event.stopPropagation();
    send();
  });
  document.addEventListener('gbl:carplay-update',refresh);
  window.GuitarCarPlayBridge=Object.freeze({
    getSnapshot:snapshot,
    prepare:()=>{const s=snapshot();return s&&window.GuitarCarPlayProtocol?.windowed?.(s)||null;},
    open:send
  });
  refresh();
})();
