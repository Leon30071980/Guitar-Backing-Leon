"""Test strutturali complementari della v1.7; iOS/Xcode non presenti su Linux."""
from pathlib import Path
import plistlib

root = Path(__file__).resolve().parents[1]
def src(p): return (root/p).read_text()
ui = src('App/KaraokeHome.swift')
engine = src('App/KaraokePreviewEngine.swift')
player = src('App/LeonAudioPlayer.swift')
control = src('App/LeonOffsetControl.swift')
widget = src('Widget/LeonKaraokeWidget.swift')
checks = {
    'ripresa app dal background': '.onChange(of: scenePhase)' in ui,
    'rilettura tempo AVAudioPlayer': 'audio.refreshProgress()' in ui and 'func refreshProgress()' in player,
    'riallineamento Activity su foreground': 'engine.reconcileOnForeground' in ui,
    'ripristino ActivityKit attività esistente': 'Activity<LeonKaraokeAttributes>.activities.first' in engine,
    'pulizia attività orfane': 'orphan.end(nil, dismissalPolicy: .immediate)' in engine,
    'snapshot su background': 'engine.snapshotOnBackground()' in ui,
    'pubblicazione per cambio frase': 'phrase != lastPublishedPhrase' in engine,
    'pubblicazione per cambio stato': 'changed || phrase' in engine,
    'heartbeat non continuo': '>= 8.0' in engine,
    'pubblicazioni serializzate': 'pendingPublish' in engine and 'publishing' in engine,
    'audio tempo vero': 'master.currentTime' in player,
    'audio timer modo common': 'RunLoop.main.add(clock, forMode: .common)' in player,
    'libreria collassabile': 'libraryExpanded.toggle()' in ui,
    'libreria chiusa al play riuscito': 'libraryExpanded = false' in ui,
    'libreria riapribile': 'Apri libreria' in ui,
    'offset control 46pt': 'private let thumb: CGFloat = 46' in control,
    'superficie drag 68pt': '.frame(height: 68)' in control,
    'pulsanti offset grande': 'minHeight: 52' in control,
    'step 0.1s': 'adjust(0.1)' in control,
    'step 0.5s': 'amount: 0.5' in control,
    'offset rispettato': 'LeonLyricsTiming.normalizedOffset' in control,
    'widget karaoke non rimosso': 'LeonLiveClock.line' in widget,
    'nessun file web nel pacchetto': not (root.parent/'web').exists(),
    'drive non alterato': 'func downloadTrack' in src('App/GoogleDriveLibrary.swift'),
}
with (root/'App/Info.plist').open('rb') as f: plist=plistlib.load(f)
checks['versione display 1.7']=plist['CFBundleShortVersionString']=='1.7'
checks['versione build 17']=plist['CFBundleVersion']=='17'
checks['background audio conservato']='audio' in plist['UIBackgroundModes']
failed = [name for name,ok in checks.items() if not ok]
if failed: raise AssertionError(', '.join(failed))
print(f'PASS {len(checks)} controlli strutturali v1.7')
