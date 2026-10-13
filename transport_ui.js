"use strict";
/* Guitar Backing Leon 2.13: player unico, timeline sincronizzate, espansione fullscreen.
 * Non viene creato alcun secondo elemento audio; anche su iOS la vista estesa
 * si limita a riposizionare i pannelli, senza interrompere la riproduzione. */
(function(){
  const clamp=(n,min,max)=>Math.max(min,Math.min(max,n));
  const fmt=(n)=>{const t=Math.floor(Math.max(0,Number(n)||0));return `${Math.floor(t/60)}:${String(t%60).padStart(2,'0')}`;};
  function attach({audio,getDuration=()=>0,onSeek=()=>{}}){
    const transports=[...document.querySelectorAll('.section-transport')];
    const buttons=[...document.querySelectorAll('.section-fullscreen')];
    let expanded=null, savedScroll=0, savedFocus=null, native=false;
    let frame=0, lastFrame=0;
    function duration(){
      const a=Number(audio.duration);
      const fallback=Number(getDuration());
      return Number.isFinite(a)&&a>0?a:(Number.isFinite(fallback)&&fallback>0?fallback:0);
    }
    const usable=()=>Boolean(audio.currentSrc||audio.getAttribute('src'));
    function update(){
      const active=usable();const playing=active&&!audio.paused&&!audio.ended;
      const len=duration();const t=clamp(Number(audio.currentTime)||0,0,len||Number(audio.currentTime)||0);
      for(const toolbar of transports){
        const play=toolbar.querySelector('.section-play');
        const stop=toolbar.querySelector('.section-stop');
        const slider=toolbar.querySelector('.section-seek');
        const clock=toolbar.querySelector('.section-clock');
        const total=toolbar.querySelector('.section-duration');
        play.disabled=stop.disabled=slider.disabled=!active;
        play.textContent=playing?'❚❚ Pausa':'▶ Play';
        play.setAttribute('aria-label',playing?'Pausa':'Riproduci il brano');
        clock.textContent=fmt(t);total.textContent=fmt(len);
        slider.max=String(Math.max(.1,len));
        if(slider.dataset.seeking!=='true')slider.value=String(clamp(t,0,Math.max(.1,len)));
        slider.style.setProperty('--seek-ratio',`${len?clamp(t/len*100,0,100):0}%`);
        slider.setAttribute('aria-valuetext',`${fmt(t)} di ${fmt(len)}`);
      }
      for(const button of buttons){button.disabled=!active;}
    }
    function frameUpdate(now){
      if(audio.paused||audio.ended){frame=0;return;}
      if(now-lastFrame>50){lastFrame=now;update();}
      frame=requestAnimationFrame(frameUpdate);
    }
    for(const toolbar of transports){
      toolbar.querySelector('.section-play').addEventListener('click',()=>{
        if(audio.paused||audio.ended)audio.play().catch(()=>{});else audio.pause();update();
      });
      toolbar.querySelector('.section-stop').addEventListener('click',()=>{
        audio.pause();if(usable())audio.currentTime=0;onSeek();update();
      });
      const slider=toolbar.querySelector('.section-seek');
      slider.addEventListener('pointerdown',()=>{slider.dataset.seeking='true';});
      slider.addEventListener('pointerup',()=>{slider.dataset.seeking='false';update();});
      slider.addEventListener('pointercancel',()=>{slider.dataset.seeking='false';update();});
      slider.addEventListener('input',()=>{
        if(!usable())return;
        const target=clamp(Number(slider.value)||0,0,duration());
        if(Number.isFinite(target))audio.currentTime=target;
        onSeek();update();
      });
      slider.addEventListener('change',()=>{slider.dataset.seeking='false';update();});
    }
    function clearExpanded(){
      if(!expanded)return;
      const panel=expanded;
      expanded=null;native=false;
      panel.classList.remove('gbl-fullscreen','gbl-fullscreen-fallback');
      document.documentElement.classList.remove('gbl-expanded-active');
      document.body.classList.remove('gbl-expanded-active');
      buttons.forEach(b=>{
        b.setAttribute('aria-expanded','false');b.textContent='⛶ Tutto schermo';
        b.setAttribute('aria-label','Espandi '+(b.dataset.target==='chords-panel'?'accordi':'karaoke')+' a tutto schermo');
      });
      window.scrollTo({top:savedScroll,behavior:'auto'});
      if(savedFocus?.isConnected){try{savedFocus.focus({preventScroll:true});}catch{}}
    }
    async function closeExpanded(){
      if(!expanded)return;
      if(document.fullscreenElement){
        try{await document.exitFullscreen();}catch{clearExpanded();}
        if(expanded&&!document.fullscreenElement)clearExpanded();
      }else clearExpanded();
    }
    async function openExpanded(panel,button){
      if(expanded===panel){await closeExpanded();return;}
      if(expanded)await closeExpanded();
      savedScroll=window.scrollY;savedFocus=document.activeElement;
      expanded=panel;
      panel.classList.add('gbl-fullscreen');
      document.documentElement.classList.add('gbl-expanded-active');
      document.body.classList.add('gbl-expanded-active');
      buttons.forEach(b=>{
        const own=b===button;
        b.setAttribute('aria-expanded',own?'true':'false');
        b.textContent=own?'⤢ Riduci':'⛶ Tutto schermo';
        b.setAttribute('aria-label',own?'Esci da tutto schermo':'Espandi a tutto schermo');
      });
      // Fullscreen nativo dove supportato, fallback CSS per Safari iOS e PWA.
      try{
        if(typeof panel.requestFullscreen!=='function')throw Error('Fullscreen nativo non supportato');
        await panel.requestFullscreen({navigationUI:'hide'});
        native=true;
      }catch{
        native=false;
        if(expanded===panel)panel.classList.add('gbl-fullscreen-fallback');
      }
      panel.scrollTop=0;
      button.focus({preventScroll:true});
      update();
    }
    buttons.forEach(button=>button.addEventListener('click',()=>{
      const panel=document.getElementById(button.dataset.target);
      if(panel&&!panel.hidden)openExpanded(panel,button);
    }));
    document.addEventListener('fullscreenchange',()=>{
      if(expanded){
        if(document.fullscreenElement===expanded){native=true;expanded.classList.remove('gbl-fullscreen-fallback');}
        else if(native)clearExpanded();
      }
    });
    document.addEventListener('keydown',e=>{
      if(e.key==='Escape'&&expanded){e.preventDefault();closeExpanded();}
    });
    ['play','pause','ended','loadstart','loadedmetadata','durationchange','timeupdate','seeked','emptied','ratechange'].forEach(event=>{
      audio.addEventListener(event,()=>{
        update();
        if(event==='play'&&!frame)frame=requestAnimationFrame(frameUpdate);
        if(['pause','ended'].includes(event)&&frame){cancelAnimationFrame(frame);frame=0;}
      });
    });
    queueMicrotask(update);
    return {update,closeExpanded,isExpanded:()=>Boolean(expanded)};
  }
  window.GuitarTransport={attach};
})();
