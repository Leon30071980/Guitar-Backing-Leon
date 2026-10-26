"use strict";
/* 2.21.12: richiesta automatica Screen Wake Lock su iPhone e Android.
   I browser possono negarla per risparmio energetico, background o compatibilità. */
(function(){
  const message=document.getElementById('screen-wake-message');
  let lock=null,pending=false,attempt=0;
  const supported=()=>Boolean(window.isSecureContext && navigator.wakeLock?.request);
  const visible=()=>document.visibilityState==='visible';
  const inform=text=>{if(message){message.textContent=text||'';message.hidden=!text;}};
  async function wake(){
    if(!visible()||!supported()||pending||(lock&&!lock.released))return;
    pending=true;const generation=attempt;
    try{
      const current=await navigator.wakeLock.request('screen');
      if(generation!==attempt||!visible()){
        try{await current.release();}catch(_){}
        return;
      }
      lock=current;inform('');
      current.addEventListener('release',()=>{if(lock===current)lock=null;});
    }catch(error){
      if(generation===attempt)inform('Il dispositivo non consente di mantenere acceso lo schermo. Verificare le impostazioni di risparmio energetico.');
    }finally{pending=false;}
  }
  function release(){
    attempt++;const old=lock;lock=null;
    if(old&&!old.released)old.release().catch(()=>{});
  }
  document.addEventListener('visibilitychange',()=>{
    if(!visible())release();else {inform('');void wake();}
  });
  window.addEventListener('pageshow',()=>{void wake();});
  window.addEventListener('pagehide',release);
  // Safari può richiedere un primo gesto dell'utente.
  ['pointerdown','touchstart','keydown'].forEach(type=>document.addEventListener(type,()=>{void wake();},{capture:true,passive:type!=='keydown'}));
  if(!supported())inform('Blocco schermo non supportato su questo browser: aggiornare Safari o Chrome.');
  else void wake();
})();
