"""Controlli offline sulla struttura Audio v1.5 (la prova funzionale richiede iPhone)."""
from pathlib import Path
import plistlib
root=Path(__file__).resolve().parents[1]
audio=(root/'App/LeonAudioPlayer.swift').read_text()
drive=(root/'App/GoogleDriveLibrary.swift').read_text()
engine=(root/'App/KaraokePreviewEngine.swift').read_text()
home=(root/'App/KaraokeHome.swift').read_text()
plist=plistlib.loads((root/'App/Info.plist').read_bytes())
assert plist['CFBundleShortVersionString']=='1.5'
assert 'audio' in plist['UIBackgroundModes']
assert 'AVAudioSession.sharedInstance()' in audio
assert 'setCategory(.playback' in audio
assert 'AVAudioPlayer(contentsOf:' in audio
assert 'play(atTime:' in audio
assert '"full"' in drive and '"no_vocals"' in drive
assert 'downloadTrack(for song:' in drive
assert 'try await URLSession.shared.download(for: req)' in drive
assert 'setVolume(' in audio
assert 'noVocals?.setVolume(' in audio
assert 'audio.onProgress' in home and 'engine.syncAudio' in home
assert 'audioControlled' in engine
assert 'CarPlay' in home
assert 'Chitarra: sempre ON' in home
assert '.cachesDirectory' in drive
assert 'accessToken' in drive and 'Bearer ' in drive
assert 'config.js' not in audio
print('PASS 18 verifiche offline Audio v1.5')
