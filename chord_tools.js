/* Guitar Backing Leon — simboli degli accordi e capotasto.
   Nessuna modifica all'audio o ai dati salvati su Drive. */
(function (global) {
  'use strict';
  const sharps = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'];
  const flats  = ['C','Db','D','Eb','E','F','Gb','G','Ab','A','Bb','B'];
  const index = new Map(sharps.map((name, i) => [name, i]));
  flats.forEach((name, i) => index.set(name, i));

  function noteAt(name, capo, useFlats) {
    const n = index.get(name);
    if (n === undefined) return null;
    return (useFlats ? flats : sharps)[(n - capo + 120) % 12];
  }

  function display(chord, capo = 0) {
    const raw = String(chord ?? '').trim();
    if (!raw || /^(?:N|N\.C\.|NC)$/i.test(raw)) return '—';
    const amount = Math.min(12, Math.max(0, Math.trunc(Number(capo) || 0)));
    if (amount === 0) return raw;
    const standardized = raw.replace(/♯/g, '#').replace(/♭/g, 'b');
    const match = /^([A-G](?:#|b)?)([^/]*?)(?:\/([A-G](?:#|b)?))?$/.exec(standardized);
    if (!match) return raw;
    const useFlats = match[1].includes('b') || (match[3] || '').includes('b');
    const root = noteAt(match[1], amount, useFlats);
    if (!root) return raw;
    const bass = match[3] ? noteAt(match[3], amount, useFlats) : null;
    return root + (match[2] || '') + (bass ? '/' + bass : '');
  }

  global.GuitarChordTools = Object.freeze({display});
})(window);
