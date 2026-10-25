'use strict';
/* Guitar Backing Leon 2.21.10 — mixer iOS/Android con UN SOLO orologio audio.
 * Tutti e quattro i mix sono decodificati in AudioBuffer e riprodotti
 * contemporaneamente dallo stesso AudioContext. Cambiare mix varia
 * soltanto i GainNode: nessun <audio> secondario, seek, pausa o riallineamento.
 * Il lettore HTML principale rimane il riferimento per UI, accordi e karaoke.
 */
window.GuitarContinuousMixer = (() => {
  const MODES = ['no_guitar','full','no_vocals','no_guitar_no_vocals'];
  // Limite prudenziale. Il browser può imporre restrizioni inferiori, soprattutto su iOS.
  const MAX_DECODED_BYTES = 600 * 1024 * 1024;
  const FADE_SECONDS = 0.022;
  function attach(master, onError = () => {}) {
    let ctx = null, masterNode = null, masterGain = null, outputGain = null;
    let buffers = new Map(), voices = new Map();
    let ready = false, active = false, selected = 'no_guitar', serial = 0;
    let lastError = '';
    let playGeneration = 0;

    function ensureContext() {
      if (!ctx) {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        if (!AudioContextClass) throw Error('Questo browser non supporta Web Audio.');
        ctx = new AudioContextClass();
      }
      return ctx;
    }
    function stopVoices() {
      ++playGeneration;
      for (const {node, gain} of voices.values()) {
        try { node.stop(); } catch (_) {}
        try { node.disconnect(); } catch (_) {}
        try { gain.disconnect(); } catch (_) {}
      }
      voices.clear();
    }
    function volume() {
      return master.muted ? 0 : Math.max(0, Math.min(1, Number(master.volume) || 0));
    }
    function setMix(instant = false) {
      if (!active || !ctx) return;
      const t = ctx.currentTime;
      for (const [key, item] of voices) {
        const to = key === selected ? 1 : 0;
        const g = item.gain.gain;
        g.cancelScheduledValues(t);
        if (instant) g.setValueAtTime(to, t);
        else {
          g.setValueAtTime(g.value, t);
          g.linearRampToValueAtTime(to, t + FADE_SECONDS);
        }
      }
    }
    function playVoices() {
      if (!active || master.paused || master.ended || !buffers.size || !ctx) return;
      stopVoices();
      const offset = Math.max(0, Number(master.currentTime) || 0);
      const duration = buffers.get('no_guitar').duration;
      if (offset >= duration - 0.005) return;
      const when = ctx.currentTime + 0.020;
      const rate = Math.max(.5, Math.min(2, Number(master.playbackRate) || 1));
      for (const key of MODES) {
        const node = ctx.createBufferSource();
        const gain = ctx.createGain();
        node.buffer = buffers.get(key);
        node.playbackRate.value = rate;
        gain.gain.value = key === selected ? 1 : 0;
        node.connect(gain).connect(outputGain);
        node.start(when, Math.min(offset, node.buffer.duration - 0.005));
        voices.set(key, {node, gain});
      }
      if (masterGain) masterGain.gain.setValueAtTime(0, ctx.currentTime);
    }
    function ensureMasterRoute() {
      if (masterNode) return;
      masterNode = ctx.createMediaElementSource(master);
      masterGain = ctx.createGain();
      outputGain = ctx.createGain();
      outputGain.gain.value = volume();
      masterNode.connect(masterGain).connect(ctx.destination);
      outputGain.connect(ctx.destination);
      masterGain.gain.value = 1;
    }
    function reset() {
      ++serial;
      active = false;
      ready = false;
      selected = 'no_guitar';
      lastError = '';
      stopVoices();
      buffers.clear();
      if (masterGain && ctx) masterGain.gain.setValueAtTime(1, ctx.currentTime);
    }
    async function prepare(urls) {
      reset();
      const generation = serial;
      if (!MODES.every(k => typeof urls?.[k] === 'string' && urls[k])) return false;
      const loaded = new Map();
      let size = 0;
      try {
        const audioContext = ensureContext();
        for (const key of MODES) {
          const response = await fetch(urls[key]);
          if (!response.ok) throw Error('Impossibile leggere la traccia ' + key);
          const raw = await response.arrayBuffer();
          if (serial !== generation) return false;
          const decoded = await audioContext.decodeAudioData(raw);
          if (serial !== generation) return false;
          size += decoded.length * decoded.numberOfChannels * 4;
          if (size > MAX_DECODED_BYTES) {
            const usedMiB = Math.ceil(size / (1024 * 1024));
            const maxMiB = Math.floor(MAX_DECODED_BYTES / (1024 * 1024));
            throw Error(`Audio decodificato: almeno ${usedMiB} MiB, limite ${maxMiB} MiB. Il mixer non è disponibile, ma la base rimane riproducibile.`);
          }
          loaded.set(key, decoded);
        }
        const ref = loaded.get('no_guitar').duration;
        if ([...loaded.values()].some(b => Math.abs(b.duration - ref) > .75)) {
          throw Error('Le tracce hanno durate differenti. Il mixer è disabilitato per evitare sfasamenti.');
        }
        if (serial !== generation) return false;
        buffers = loaded;
        ready = true;
        return true;
      } catch (e) {
        if (generation === serial) {
          reset();
          lastError = 'Mixer non disponibile: ' + (e?.message || String(e));
          onError(lastError);
        }
        return false;
      }
    }
    function activate() {
      if (!ready) return false;
      try {
        ensureContext();
        ensureMasterRoute();
        active = true;
        const generation = playGeneration;
        // Chiamata nel click su Voce/Chitarra: sblocca l'audio su iOS.
        const resumed = ctx.resume();
        Promise.resolve(resumed).then(() => {
          if (active && generation === playGeneration && !master.paused) playVoices();
        }).catch(e => onError('Audio non sbloccato: ' + e.message));
        if (ctx.state === 'running' && !master.paused) playVoices();
        return true;
      } catch (e) {
        active = false;
        if (masterGain && ctx) masterGain.gain.setValueAtTime(1, ctx.currentTime);
        onError('Mixer non attivabile: ' + e.message);
        return false;
      }
    }
    function select(mode) {
      if (!MODES.includes(mode) || !ready) return false;
      selected = mode;
      if (!active) return activate();
      // NON vengono mai fermati, riavviati o spostati i buffer quando cambia mix.
      setMix();
      return true;
    }
    master.addEventListener('playing', () => {
      if (!active) {
        if (ctx && masterNode) ctx.resume().catch(() => {});
        return;
      }
      ctx.resume().then(() => {
        if (active && !master.paused && !voices.size) playVoices();
      }).catch(e => onError('Premere Play per attivare l’audio: ' + e.message));
    });
    master.addEventListener('pause', () => { if (active) stopVoices(); });
    master.addEventListener('ended', () => { if (active) stopVoices(); });
    master.addEventListener('seeking', () => { if (active) stopVoices(); });
    master.addEventListener('seeked', () => {
      if (active && !master.paused) playVoices();
    });
    master.addEventListener('ratechange', () => {
      if (active && !master.paused && voices.size) playVoices();
    });
    master.addEventListener('volumechange', () => {
      if (active && outputGain && ctx) outputGain.gain.setValueAtTime(volume(), ctx.currentTime);
    });
    // Nessun riallineamento periodico: i 4 mix condividono lo STESSO orologio.
    return {
      prepare, select, reset,
      get ready() { return ready; },
      get error() { return lastError; },
      get active() { return active; },
      get mode() { return selected; },
    };
  }
  return {attach};
})();
