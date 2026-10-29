/* Modulo opzionale. Nessuna modifica grafica se ?carplay=1 non e' attivo. */
(()=>{
  'use strict';
  const source=window.GBLCarPlaySource;
  const protocol=window.GuitarCarPlayProtocol;
  if(typeof source!=='function'||!protocol)return;
  let enabled=(new URLSearchParams(location.search)).get('carplay')==='1';
  try{enabled=enabled||localStorage.getItem('gbl-carplay-mode')==='1';}catch{}
  // L'iPhone PWA standalone non ha barra degli indirizzi. La modalita'
  // opzionale si attiva/disattiva toccando 4 volte "Web 2.64" nel footer.
  const footer=document.getElementById('web-build');
  let taps=0,firstTap=0;
  footer?.addEventListener('click',()=>{
    const now=Date.now();
    if(now-firstTap>3000){taps=0;firstTap=now;}
    if(++taps>=4){
      try{localStorage.setItem('gbl-carplay-mode',enabled?'0':'1');}catch{}
      location.reload();
    }
  });
  let lastSnapshot=null, button=null;
  function snapshot(){
    const data=source();
    if(!data||!data.songId)return null;
    return data;
  }
  function refresh(){
    lastSnapshot=snapshot();
    if(button){
      button.disabled=!lastSnapshot||!lastSnapshot.words?.length;
      button.title=lastSnapshot?.words?.length?'Trasferisci posizione e frasi al Companion iPhone':'Apri un brano con il karaoke pronto';
    }
  }
  function send(){
    refresh();
    if(!lastSnapshot||!lastSnapshot.words?.length){alert('Carica prima un brano con testo disponibile.');return;}
    const href=protocol.link(lastSnapshot);
    // Il passaggio e' una navigazione esplicita, NON una sincronizzazione background.
    window.location.href=href;
  }
  if(enabled){
    const actions=document.querySelector('.section-transport-actions')||document.querySelector('#transport-home');
    if(actions){
      button=document.createElement('button');
      button.type='button';button.className='secondary';
      button.id='gbl-carplay-send';button.textContent='CarPlay ↗';
      button.setAttribute('aria-label','Invia brano al visualizzatore karaoke CarPlay');
      button.title='Passa il brano al Companion nativo (richiede installazione)';
      button.addEventListener('click',send);actions.appendChild(button);
    }
  }
  document.addEventListener('gbl:carplay-update',refresh);
  window.GuitarCarPlayBridge=Object.freeze({getSnapshot:()=>snapshot(),prepare:()=>{const s=snapshot();return s?protocol.windowed(s):null;},open:send});
  refresh();
})();
