"""Risincronizzazione A&S voce/audio senza cambiare lo spartito selezionato.

La struttura (testo, sigle, ancore editoriali) proviene da A&S.
I tempi delle parole vengono ricavati dalla voce isolata tramite forced alignment.
I cambi strumentali rimangono indipendenti dalla timeline vocale.
Questo modulo NON salva file: app.py gestisce backup e transazioni.
"""
from __future__ import annotations

from typing import Any


def source_text(score: dict) -> str:
    lines: list[list[str]] = []
    previous = None
    for word in score['words']:
        line_id = word['line']
        if previous != line_id:
            lines.append([])
            previous = line_id
        lines[-1].append(str(word['text']))
    text = '\n'.join(' '.join(line) for line in lines)
    if not 10 <= len(score['words']) <= 2500 or not text or len(text) > 20000:
        raise ValueError('Spartito A&S non adatto all’allineamento audio.')
    return text


def prepare_synced(score: dict, aligned: dict, previous_words: list[dict],
                   original_chords: list[dict], duration: float, *, provider: str = "accordiespartiti"):
    """Ricava un karaoke con tempi AUDIO e accordi/ancore dell'originale A&S.

    Non cerca di correggere le etichette armoniche, non inventa parole nei soli.
    Salva gli eventi con tempi attendibili; annota separatamente le righe
    dello spartito non temporizzabili, senza inventare cambi rapidissimi.
    """
    from as_audio_recovery import direct_as_words
    from as_import_core import align_words, merge_chords, _normalize
    from lyrics import validate_lyrics
    from karaoke_integrity import require_safe
    from difflib import SequenceMatcher

    source = score['words']
    audio_words = aligned.get('words') or []
    a = [_normalize(w['text']) for w in source]
    b = [_normalize(w.get('text', '')) for w in audio_words]
    matcher = SequenceMatcher(None, a, b, autojunk=False)
    exact = sum(i2-i1 for tag, i1, i2, _, _ in matcher.get_opcodes() if tag == 'equal')
    agreement = exact / max(1, len(a), len(b))
    if agreement < .68:
        raise ValueError(f'Il riconoscimento sulla voce non coincide abbastanza con A&S '
                         f'({agreement:.0%}). Nessuna modifica effettuata.')
    aligned_exact = direct_as_words(source, audio_words)
    if aligned_exact is not None:
        words = aligned_exact
    else:
        words, _ = align_words(source, audio_words)
    checked = validate_lyrics({'words': words, 'source':'accordiespartiti+voce',
                               'language':aligned.get('language','en')}, duration)
    require_safe(checked['words'], duration, context='Sincronizzazione A&S sulla voce')
    # Gli eventi dell'intro sono temporizzati rispetto all'inizio reale della voce,
    # gli accordi delle strofe sono agganciati alle nuove parole.
    chords, _count, fidelity = merge_chords(
        score['chords'], checked['words'], original_chords, duration,
        score.get('instrumental_intro'),score.get('unplaced_chord_rows'),
        with_fidelity=True, provider=provider)
    # Gli accordi non temporizzabili non invalidano parole e accordi validi.
    # Rimangono recuperabili come dati editoriali in lyrics.json, ma NON
    # vengono spacciati per cambi sincronizzati nel leggio.
    require_safe(checked['words'],duration,chords,context='Sincronizzazione completa A&S')
    old_first = float(previous_words[0]['start']) if previous_words else None
    new_first = float(checked['words'][0]['start'])
    old_offset = round(new_first-old_first,3) if old_first is not None else None
    # Nota: il primo accordo strumentale e' indipendente dalla prima parola.
    stats = {
        'source_words':len(source), 'source_chords':score.get('source_chord_count',len(chords)),
        'source_chords_preserved':fidelity['source_preserved'],
        'instrumental_events':fidelity['source_instrumental_preserved'],
        'first_voice_before':old_first, 'first_voice_after':new_first,
        'first_voice_shift':old_offset,'exact_word_agreement':round(agreement,3),
        'estimated_word_count':int(aligned.get('timing_estimated_word_count',0) or 0),
        'source_unplaced_chords':fidelity['source_unplaced_chords'],
        'source_unplaced_groups':fidelity['source_unplaced_groups'],
        'timing_review_required':bool(fidelity['source_unplaced_chords']),
    }
    return checked['words'], chords, stats
