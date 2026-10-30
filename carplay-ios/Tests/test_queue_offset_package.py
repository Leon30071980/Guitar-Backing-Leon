"""Verifica strutturale dei collegamenti fra coda, lettore e Live Activity.
La compilazione Swift completa richiede Xcode su macOS.
"""
from pathlib import Path
root=Path(__file__).resolve().parents[1]
ui=(root/'App/KaraokeHome.swift').read_text()
player=(root/'App/LeonAudioPlayer.swift').read_text()
engine=(root/'App/KaraokePreviewEngine.swift').read_text()
drive=(root/'App/GoogleDriveLibrary.swift').read_text()
model=(root/'App/LeonQueueModel.swift').read_text()
clock=(root/'Shared/KaraokeAttributes.swift').read_text()
lyric=(root/'Shared/LeonLyricsTiming.swift').read_text()
checks=[
 ('coda multipla', 'queue.enqueue(song.id)' in ui),
 ('riordino coda', 'queue.move(id, direction: direction)' in ui),
 ('salvataggio coda', 'UserDefaults.standard.set(queue.ids' in ui),
 ('ripristino coda', 'UserDefaults.standard.stringArray(forKey:' in ui),
 ('controllo prossimo', 'await nextSong()' in ui),
 ('controllo precedente', 'await previousSong()' in ui),
 ('passaggio automatico', 'audio.onFinished' in ui),
 ('comando CarPlay prossimo', 'remote.nextTrackCommand.addTarget' in player),
 ('comando CarPlay precedente', 'remote.previousTrackCommand.addTarget' in player),
 ('completamento audio delegate', 'audioPlayerDidFinishPlaying' in player),
 ('una sola transizione', 'guard playing else { return } // due MP3' in player),
 ('un download per file', 'inFlightAudio' in drive),
 ('correzione sola visualizzazione', 'displayedPosition' in engine),
 ('offset in Live Activity', 'anchorPosition: displayedPosition' in engine),
 ('offset persistente', 'UserDefaults.standard.set(rounded' in engine),
 ('offset regolabile', 'in: -3...3, step: 0.1' in ui),
 ('offset senza cambio audio', 'audioTime - normalizedOffset(offset)' in lyric),
 ('tempo negativo ante prima strofa', 'return state.anchorPosition + elapsed' in clock),
 ('nessuna modifica Web', not (root.parent/'web').exists()),
 ('info.plist iOS', (root/'App/Info.plist').exists())
]
for title, ok in checks:
    if not ok: raise AssertionError(title)
print(f'PASS {len(checks)} verifiche struttura v1.6')
