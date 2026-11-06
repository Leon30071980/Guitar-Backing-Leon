"""v2.66 PC: verified source selection and conservative automatic correction.

Network access is limited to the source allowlists already implemented in
as_import_core and tabs_chords_import. This module does not mutate song files.
"""
from __future__ import annotations
import copy
import hashlib
import math
from typing import Any

PROVIDERS = {'as': 'Accordi e Spartiti', 'ct': 'Ultimate Guitar (C&T)'}


def source_score(provider: str, url: str) -> tuple[str, dict]:
    """Validate HTTPS host/path, fetch the actual page, then parse its score."""
    if provider == 'as':
        from as_import_core import safe_url, _fetch, parse_html
        safe = safe_url(url)
        score = parse_html(_fetch(safe))
    elif provider == 'ct':
        from tabs_chords_import import safe_url, _fetch, _extract_score, _normalize_score
        from as_import_core import parse_score
        safe = safe_url(url)
        score = parse_score(_normalize_score(_extract_score(_fetch(safe))))
    else:
        raise ValueError('Fonte non supportata. Scegliere A&S oppure C&T.')
    if not 10 <= len(score.get('words', [])) <= 2500 or not score.get('chords'):
        raise ValueError('Lo spartito non contiene abbastanza testo e accordi.')
    if len(score.get('chords', [])) > 2000:
        raise ValueError('La scheda contiene troppi accordi.')
    return safe, score


def file_revision(lyrics_bytes: bytes, result_bytes: bytes) -> str:
    return hashlib.sha256(lyrics_bytes + result_bytes).hexdigest()


def source_summary(score: dict) -> dict:
    from as_playback_sync import source_text
    text = source_text(score)
    return {
        'words': len(score['words']),
        'chords': int(score.get('source_chord_count', len(score['chords']))),
        'instrumental_groups': len(score.get('unplaced_chord_rows', [])),
        'text_preview': ' '.join(text.split()[:16])[:230],
    }


def safety_review(words: list, chords: list, duration: float, stats: dict,
                  *, guitar_available: bool) -> list[str]:
    """Block automatic saving whenever there is material uncertainty.

    Not an assertion that the music is 100% correct; even accepted results must
    be checked by listening. Never interpret an unlabeled audio note as a chord.
    """
    from karaoke_integrity import audit_words, audit_chords
    issues = audit_words(words, duration) + audit_chords(chords, duration, words)
    if not words or not chords:
        return issues + ['Testo o accordi mancanti.']
    if not math.isfinite(float(duration)) or float(duration) <= 0:
        return issues + ['Durata non valida.']
    if abs(float(chords[0]['start'])) > .1 or abs(float(chords[-1]['end'])-duration) > .25:
        issues.append('La timeline degli accordi non copre il brano.')
    for a,b in zip(chords, chords[1:]):
        if abs(float(a['end'])-float(b['start'])) > .035:
            issues.append('La timeline degli accordi contiene un salto.')
            break
    missing = int(stats.get('source_unplaced_chords', 0) or 0)
    if missing:
        issues.append(f'{missing} accordi della fonte non sono collocabili con affidabilità.')
    agreement = float(stats.get('exact_word_agreement', 0) or 0)
    if agreement < .85:
        issues.append(f'Corrispondenza testo-voce {agreement:.0%}: richiede verifica.')
    estimated = int(stats.get('estimated_word_count', 0) or 0)
    if estimated > max(2, round(len(words) * .02)):
        issues.append(f'{estimated} parole con tempi stimati: verifica manuale necessaria.')
    if not guitar_available:
        issues.append('Chitarra isolata non disponibile: i cambi armonici non possono essere verificati sull’audio.')
    refined = int(stats.get('instrumental_refined', 0) or 0)
    estimated_chords = int(stats.get('instrumental_estimated', 0) or 0)
    if estimated_chords >= 4 and estimated_chords > refined * 2:
        issues.append(f'{estimated_chords} cambi strumentali sono ancora prevalentemente stimati.')
    return issues[:12]


def make_candidate(original_lyrics: dict, original_song: dict, words: list, chords: list,
                   stats: dict, provider: str, url: str, stamp: str) -> tuple[dict, dict]:
    source = 'accordiespartiti' if provider == 'as' else 'ultimate-guitar'
    lyrics = copy.deepcopy(original_lyrics)
    lyrics.update(words=words, source=f'{source}+voce', source_url=url,
                  lyrics_provider=PROVIDERS[provider], edited=True,
                  offset_seconds=0.0, timing_method='stable-ts-small+'+PROVIDERS[provider],
                  playback_sync_date=stamp, playback_sync_stats=stats,
                  as_unplaced_chord_groups=(stats.get('source_unplaced_groups',[]) if provider=='as' else []),
                  timing_estimated_word_count=int(stats.get('estimated_word_count',0) or 0),
                  timing_review_needed=False)
    lyrics['as_correction_date' if provider=='as' else 'tabs_correction_date']=stamp
    song = dict(original_song)
    song.update(chords=chords, chord_source=source,
                lyrics_status='ready', lyrics_error='', lyrics_count=len(words))
    return lyrics, song
