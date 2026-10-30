import AVFAudio
import Foundation
import MediaPlayer

// Lettore iPhone nativo: due mix MP3 identici come durata, sempre in esecuzione
// in parallelo. Si sente una sola traccia per volta; la chitarra resta ON.
// Il tempo del karaoke viene letto dal player, mai da un cronometro indipendente.
@MainActor
final class LeonAudioPlayer: ObservableObject {
    @Published private(set) var ready = false
    @Published private(set) var playing = false
    @Published private(set) var vocalsEnabled = true
    @Published private(set) var position = 0.0
    @Published private(set) var duration = 0.0
    @Published var message = "Seleziona un brano dalla libreria Drive."
    var onProgress: ((Double, Bool) -> Void)?

    private var full: AVAudioPlayer?
    private var noVocals: AVAudioPlayer?
    private var timer: Timer?
    private var title = ""
    private var lastNowPlayingAt = Date.distantPast
    private var notifications: [NSObjectProtocol] = []

    init() {
        // Per comandi auricolare/CarPlay standard, non controlli personalizzati.
        let remote = MPRemoteCommandCenter.shared()
        remote.playCommand.addTarget { [weak self] _ in
            Task { @MainActor in self?.play() }
            return .success
        }
        remote.pauseCommand.addTarget { [weak self] _ in
            Task { @MainActor in self?.pause() }
            return .success
        }
        notifications.append(NotificationCenter.default.addObserver(
            forName: AVAudioSession.interruptionNotification, object: nil, queue: .main
        ) { [weak self] note in
            let kind = (note.userInfo?[AVAudioSessionInterruptionTypeKey] as? UInt)
                .flatMap(AVAudioSession.InterruptionType.init(rawValue:))
            if kind == .began { Task { @MainActor in self?.pause() } }
        })
    }

    func load(fullURL: URL, noVocalsURL: URL, title: String) throws {
        stop()
        let a = try AVAudioPlayer(contentsOf: fullURL)
        let b = try AVAudioPlayer(contentsOf: noVocalsURL)
        guard a.prepareToPlay(), b.prepareToPlay() else {
            throw NSError(domain: "LeonAudio", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: "Impossibile decodificare le basi MP3."])
        }
        guard abs(a.duration - b.duration) < 1.5 else {
            throw NSError(domain: "LeonAudio", code: 2,
                          userInfo: [NSLocalizedDescriptionKey: "Le basi non sono sincronizzabili (durate diverse)."])
        }
        a.volume = vocalsEnabled ? 1 : 0
        b.volume = vocalsEnabled ? 0 : 1
        full = a
        noVocals = b
        self.title = title
        duration = min(a.duration, b.duration)
        position = 0
        ready = true
        message = "Audio pronto: voce commutabile, chitarra sempre ON."
        updateNowPlaying()
        onProgress?(0, false)
    }

    func play() {
        guard ready, let a = full, let b = noVocals else { return }
        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.playback, mode: .default)
            try session.setActive(true)
        } catch {
            message = "Audio iOS non disponibile: \(error.localizedDescription)"
            return
        }
        let seek = min(position, max(0, duration - 0.05))
        if seek >= duration - 0.05 && duration > 0 { position = 0 }
        a.currentTime = position
        b.currentTime = position
        a.volume = vocalsEnabled ? 1 : 0
        b.volume = vocalsEnabled ? 0 : 1
        let at = max(a.deviceCurrentTime, b.deviceCurrentTime) + 0.18
        let p1 = a.play(atTime: at)
        let p2 = b.play(atTime: at)
        guard p1 && p2 else {
            a.stop(); b.stop()
            playing = false
            message = "Impossibile avviare contemporaneamente le due basi."
            return
        }
        playing = true
        startClock()
        updateNowPlaying()
        onProgress?(position, true)
    }

    func pause() {
        guard ready else { return }
        if playing { syncPosition() }
        full?.pause()
        noVocals?.pause()
        playing = false
        timer?.invalidate(); timer = nil
        updateNowPlaying()
        onProgress?(position, false)
    }

    func stop() {
        timer?.invalidate(); timer = nil
        full?.stop(); noVocals?.stop()
        full = nil; noVocals = nil
        ready = false; playing = false; position = 0; duration = 0
        MPNowPlayingInfoCenter.default().nowPlayingInfo = nil
        onProgress?(0, false)
    }

    func seek(to seconds: Double) {
        guard ready else { return }
        let p = min(max(0, seconds), max(0, duration - 0.01))
        let wasPlaying = playing
        if wasPlaying {
            full?.pause(); noVocals?.pause()
        }
        position = p
        full?.currentTime = p
        noVocals?.currentTime = p
        if wasPlaying { play() }
        else { updateNowPlaying(); onProgress?(position, false) }
    }

    func toggleVocals() {
        guard ready else { return }
        vocalsEnabled.toggle()
        // Con le due basi attive il cambio non richiede seek/stop.
        full?.setVolume(vocalsEnabled ? 1 : 0, fadeDuration: 0.08)
        noVocals?.setVolume(vocalsEnabled ? 0 : 1, fadeDuration: 0.08)
        message = vocalsEnabled ? "Voce ON · chitarra ON" : "Voce OFF · chitarra ON"
    }

    private func startClock() {
        timer?.invalidate()
        timer = Timer.scheduledTimer(withTimeInterval: 0.25, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.tick() }
        }
    }

    private func syncPosition() {
        guard let a = full, let b = noVocals else { return }
        let master = vocalsEnabled ? a : b
        position = min(duration, max(0, master.currentTime))
        // Il player silenziato può divergere su alcuni iPhone: riallinearlo.
        let silent = vocalsEnabled ? b : a
        if abs(silent.currentTime - position) > 0.09 { silent.currentTime = position }
    }

    private func tick() {
        guard playing else { return }
        syncPosition()
        if position >= duration - 0.15 || (full?.isPlaying == false && noVocals?.isPlaying == false) {
            full?.stop(); noVocals?.stop()
            playing = false
            position = duration
            timer?.invalidate(); timer = nil
        }
        if Date().timeIntervalSince(lastNowPlayingAt) >= 1 {
            updateNowPlaying()
            lastNowPlayingAt = Date()
        }
        onProgress?(position, playing)
    }

    private func updateNowPlaying() {
        guard ready else { return }
        MPNowPlayingInfoCenter.default().nowPlayingInfo = [
            MPMediaItemPropertyTitle: title,
            MPMediaItemPropertyArtist: "Guitar Backing Leon",
            MPMediaItemPropertyPlaybackDuration: duration,
            MPNowPlayingInfoPropertyElapsedPlaybackTime: position,
            MPNowPlayingInfoPropertyPlaybackRate: playing ? 1.0 : 0.0
        ]
    }
}
