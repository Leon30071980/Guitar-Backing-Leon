"use strict";
/* Guitar Backing Leon 2.19.9: schermo acceso finché il brano è in esecuzione.
 * Non aggira il blocco di sistema: utilizza la Screen Wake Lock API standard. */
(function(){
  const audio=document.getElementById('player');
  const toolbar=document.getElementById('global-transport');
  if(!audio||!toolbar)return;
  const label=document.createElement('span');
  label.id='screen-wake-status';label.setAttribute('role','status');
  toolbar.append(label);
  let sentinel=null,pending=false,attemptId=0;
  const supported=()=>Boolean(navigator.wakeLock?.request);
  const playing=()=>!audio.paused&&!audio.ended&&Boolean(audio.currentSrc||audio.getAttribute('src'));
  const visible=()=>document.visibilityState!=='hidden';
  function status(state,message){label.dataset.status=state;label.textContent=message;}
  async function releaseWake(){
    // Invalidate requests already in progress, e.g. a quick Play->Pause.
    attemptId++;
    const old=sentinel;sentinel=null;
    status('','');
    if(old&&!old.released){try{await old.release();}catch(_){}}
  }
  async function requestWake(){
    if(!playing()||!visible())return;
    if(!supported()){
      status('unsupported','Schermo: blocco automatico gestito da iOS');return;
    }
    if(sentinel&&!sentinel.released)return;
    if(pending)return;
    const token=++attemptId;
    pending=true;
    try{
      const lock=await navigator.wakeLock.request('screen');
      if(token!==attemptId||!playing()||!visible()){
        try{await lock.release();}catch(_){}return;
      }
      sentinel=lock;
      status('active','☀ Schermo mantenuto acceso durante Play');
      lock.addEventListener('release',()=>{
        if(sentinel!==lock)return;
        sentinel=null;
        if(playing()&&visible())status('unavailable','Schermo: blocco non disponibile');
        else status('','');
      });
    }catch(_){
      if(token===attemptId)status('unavailable','Schermo: mantenimento non consentito da iOS');
    }finally{
      pending=false;
      // A new Play can happen while a previous asynchronous request is being released.
      if(token!==attemptId&&playing()&&visible()&&(!sentinel||sentinel.released))
        queueMicrotask(requestWake);
    }
  }
  audio.addEventListener('play',requestWake);
  ['pause','ended','emptied'].forEach(event=>audio.addEventListener(event,releaseWake));
  document.addEventListener('visibilitychange',()=>{
    if(!visible())releaseWake();
    else if(playing())requestWake();
  });
  window.addEventListener('pageshow',()=>{if(playing())requestWake();});
  window.addEventListener('pagehide',releaseWake);
})();
