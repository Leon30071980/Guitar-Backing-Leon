"use strict";
/* Guitar Backing Leon 2.21.7 — Screen Wake Lock (iPhone/iPad/Android)
 * Tiene acceso lo schermo finché la web app è visibile, anche se il brano è in pausa.
 * Non può impedire blocchi espliciti, risparmio energia o passaggio in background.
 * Non richiede librerie, credenziali o un servizio esterno. */
(function () {
  const button = document.getElementById('screen-wake-toggle');
  const message = document.getElementById('screen-wake-message');
  if (!button) return;

  const KEY = 'gbl-screen-wake-enabled';
  let enabled = true; // Valore predefinito richiesto per il leggio: schermo acceso.
  try { enabled = window.localStorage.getItem(KEY) !== 'off'; } catch (_) {}
  let lock = null;
  let pending = false;
  let generation = 0;
  let lastError = '';

  const visible = () => document.visibilityState === 'visible';
  const supported = () => Boolean(window.isSecureContext && navigator.wakeLock && typeof navigator.wakeLock.request === 'function');
  const active = () => Boolean(lock && !lock.released);

  function showMessage(value) {
    if (!message) return;
    message.textContent = value || '';
    message.hidden = !value;
  }
  function render() {
    button.setAttribute('aria-pressed', enabled ? 'true' : 'false');
    if (!enabled) {
      button.dataset.state = 'off';
      button.textContent = '☾ Schermo OFF';
      button.title = 'Toccare per impedire lo standby mentre l’app è visibile';
      showMessage('');
    } else if (!supported()) {
      button.dataset.state = 'unavailable';
      button.textContent = '☀ Schermo non disponibile';
      button.title = 'Richiede HTTPS e un browser compatibile con Screen Wake Lock';
      showMessage('Questo browser non può impedire lo standby: usare Safari/Chrome aggiornato su HTTPS.');
    } else if (active()) {
      button.dataset.state = 'active';
      button.textContent = '☀ Schermo ON';
      button.title = 'Schermo mantenuto acceso finché l’app è visibile. Toccare per disattivare.';
      showMessage('');
    } else if (lastError && visible()) {
      button.dataset.state = 'unavailable';
      button.textContent = '☀ Schermo limitato';
      button.title = 'Il dispositivo ha rifiutato il blocco schermo: ' + lastError;
      showMessage('Lo schermo potrebbe spegnersi per le impostazioni del dispositivo o per il risparmio energetico. Provi a toccare la pagina.');
    } else {
      button.dataset.state = 'waiting';
      button.textContent = '☀ Schermo ON';
      button.title = 'Si attiva appena il browser lo consente, anche mentre la musica è in pausa.';
      showMessage('');
    }
  }
  function releaseWake() {
    generation++;
    const previous = lock;
    lock = null;
    if (previous && !previous.released) {
      try { void previous.release().catch(() => {}); } catch (_) {}
    }
    render();
  }
  async function acquireWake() {
    if (!enabled || !visible() || !supported() || active() || pending) return;
    pending = true;
    const requestedGeneration = generation;
    try {
      // Richiedere direttamente nel gestore dell'evento utente per Safari iOS.
      const acquired = await navigator.wakeLock.request('screen');
      if (!enabled || !visible() || requestedGeneration !== generation) {
        try { await acquired.release(); } catch (_) {}
        return;
      }
      lock = acquired;
      lastError = '';
      acquired.addEventListener('release', function () {
        if (lock !== acquired) return;
        lock = null;
        render();
        // Non ripetere richieste in loop se iOS o Android revocano il blocco.
        // Un nuovo tocco oppure il ritorno sull'app eseguiranno un nuovo tentativo.
      });
    } catch (err) {
      if (requestedGeneration === generation && enabled) {
        lastError = err && (err.name || err.message) || 'Richiesta non consentita';
      }
    } finally {
      pending = false;
      render();
    }
  }
  function setEnabled(next) {
    enabled = Boolean(next);
    lastError = '';
    try { window.localStorage.setItem(KEY, enabled ? 'on' : 'off'); } catch (_) {}
    if (!enabled) releaseWake();
    else { render(); void acquireWake(); }
  }
  button.addEventListener('click', function () { setEnabled(!enabled); });

  // I browser possono richiedere l'interazione iniziale con la pagina.
  // I listener NON alterano gli eventi del karaoke, del mixer o del player.
  document.addEventListener('pointerdown', function () { if (enabled) void acquireWake(); }, {capture:true,passive:true});
  document.addEventListener('touchstart', function () { if (enabled) void acquireWake(); }, {capture:true,passive:true});
  document.addEventListener('keydown', function () { if (enabled) void acquireWake(); }, {capture:true});
  document.addEventListener('visibilitychange', function () {
    if (!visible()) releaseWake();
    else if (enabled) {lastError = ''; render(); void acquireWake();}
  });
  window.addEventListener('pageshow', function () {if (enabled) void acquireWake();});
  window.addEventListener('pagehide', releaseWake);

  render();
  // Tentativo immediato: su browser che richiedono un gesto si riprova al primo tocco.
  if (enabled) void acquireWake();
})();
