'use strict';
/* Mixer senza sostituzione di src: 4 combinazioni MP3 sincronizzate sullo stesso
 * lettore visibile. Le sorgenti aggiuntive sono silenziose finche' l'utente
 * non abilita il mixer. Il cambio ON/OFF usa GainNode, non pause/load/seek.
 */
window.GuitarContinuousMixer = (() => {
  const MODES = ['no_guitar', 'full', 'no_vocals', 'no_guitar_no_vocals'];
  function attach(master, onError = () => {}) {
    let ctx=null, source=null, masterGain=null, followers=new Map(), ready=false;
    let active=false, selected='no_guitar', serial=0;
    function gain(value, target) {
      if(!ctx || !target)return;
      const at=ctx.currentTime;
      target.gain.cancelScheduledValues(at);
      target.gain.setTargetAtTime(value,at,0.014);
    }
    function apply(){
      if(!active)return;
      gain(selected==='no_guitar'?1:0,masterGain);
      for(const [key, item] of followers)gain(selected===key?1:0,item.gain);
    }
    function align(force=false){
      if(!active)return;
      const t=master.currentTime||0;
      for(const {audio} of followers.values()){
        if(audio.readyState>=1 && (force || Math.abs((audio.currentTime||0)-t)>.16)){
          try { audio.currentTime=t; } catch {}
        }
        audio.playbackRate=master.playbackRate||1;
      }
    }
    async function startFollowers(){
      let failed=false;
      align(true);
      const starts=[];
      for(const {audio} of followers.values()){
        if(master.paused)break;
        try {starts.push(Promise.resolve(audio.play()).catch(e=>{failed=true;onError('Una traccia del mixer non è riproducibile: '+e.message)}));}
        catch(e){failed=true;onError('Audio non disponibile: '+e.message);}
      }
      await Promise.all(starts);
      align(false);
      return !failed;
    }
    function destroyFollowers(){
      ++serial;
      ready=false; active=false; selected='no_guitar';
      if(masterGain)gain(1,masterGain);
      for(const item of followers.values()){
        item.audio.pause();
        item.audio.removeAttribute('src');
        item.audio.load();
        if(item.node)item.node.disconnect();
        if(item.gain)item.gain.disconnect();
      }
      followers.clear();
    }
    function makeReady(audio){
      if(audio.readyState>=3)return Promise.resolve();
      return new Promise((resolve,reject)=>{
        const timeout=setTimeout(()=>finish(new Error('Timeout caricamento traccia mixer')),25000);
        function finish(err){clearTimeout(timeout);audio.removeEventListener('canplay',ok);audio.removeEventListener('error',bad);err?reject(err):resolve();}
        function ok(){finish();}
        function bad(){finish(new Error('Una combinazione audio non può essere caricata.'));}
        audio.addEventListener('canplay',ok);audio.addEventListener('error',bad);
      });
    }
    async function prepare(urls){
      destroyFollowers();
      const mySerial=serial;
      if(!MODES.every(key=>typeof urls?.[key]==='string' && urls[key]))return false;
      try {
        for(const mode of MODES){
          if(mode==='no_guitar')continue;
          const a=new Audio();
          a.preload='auto';a.playsInline=true;
          a.src=urls[mode];
          a.load();
          followers.set(mode,{audio:a,node:null,gain:null});
        }
        await Promise.all([...followers.values()].map(item=>makeReady(item.audio)));
        if(serial!==mySerial)return false;
        ready=true;
        return true;
      }catch(e){
        if(serial===mySerial){destroyFollowers();onError(e.message);}
        return false;
      }
    }
    function activate(){
      if(!ready)return false;
      const AudioContextClass=window.AudioContext||window.webkitAudioContext;
      if(!AudioContextClass){onError('Questo browser non supporta il mixer continuo.');return false;}
      try {
        if(!ctx){
          ctx=new AudioContextClass();
          source=ctx.createMediaElementSource(master);
          masterGain=ctx.createGain();
          source.connect(masterGain).connect(ctx.destination);
        }
        // Mantiene il master udibile fino all'avvio delle altre tracce.
        masterGain.gain.value=1;
        for(const item of followers.values()){
          item.node=ctx.createMediaElementSource(item.audio);
          item.gain=ctx.createGain();
          item.gain.gain.value=0;
          item.node.connect(item.gain).connect(ctx.destination);
        }
        active=true;
        ctx.resume().catch(e=>onError('Sbloccare l’audio con Play: '+e.message));
        for(const item of followers.values())item.audio.volume=master.muted?0:master.volume;
        startFollowers().then(ok=>{if(active){if(!ok){selected='no_guitar';onError('Impossibile avviare tutte le tracce. Ripristinata la base.');}apply();}});
        return true;
      }catch(e){onError('Mixer continuo non disponibile: '+e.message);return false;}
    }
    function select(mode){
      if(!MODES.includes(mode) || !ready)return false;
      selected=mode;
      if(!active)return activate();
      apply();
      return true;
    }
    master.addEventListener('play',()=>{
      if(!active)return;
      if(ctx)ctx.resume().catch(()=>{});
      startFollowers().then(ok=>{if(!ok){selected='no_guitar';onError('Impossibile riprodurre le tracce aggiuntive.');}apply();});
    });
    master.addEventListener('pause',()=>{for(const {audio} of followers.values())audio.pause();});
    master.addEventListener('ended',()=>{for(const {audio} of followers.values())audio.pause();});
    master.addEventListener('seeking',()=>align(true));
    master.addEventListener('seeked',()=>align(true));
    master.addEventListener('ratechange',()=>align(false));
    master.addEventListener('timeupdate',()=>align(false));
    master.addEventListener('volumechange',()=>{
      if(!active || !ctx)return;
      // La scala volume del lettore visibile vale anche per le tracce nascoste.
      const volume=master.muted?0:master.volume;
      // La traccia master riceve gia' il volume HTML; le altre lo replicano.
      for(const item of followers.values())item.audio.volume=volume;
    });
    return {prepare,select,reset:destroyFollowers,get ready(){return ready;},get active(){return active;},get mode(){return selected;}};
  }
  return {attach};
})();
