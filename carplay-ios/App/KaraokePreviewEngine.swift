import ActivityKit
import Foundation

@MainActor
final class KaraokePreviewEngine: ObservableObject {
    @Published var songTitle = "PROVA KARAOKE"
    @Published var phrases: [LeonPhrase] = [
        LeonPhrase(start: 0, end: 4, text: "LA MUSICA CI ACCOMPAGNA"),
        LeonPhrase(start: 4, end: 9, text: "SEGUI LE PAROLE INSIEME A NOI"),
        LeonPhrase(start: 9, end: 14, text: "IL RITMO CONTINUA A SUONARE"),
        LeonPhrase(start: 14, end: 20, text: "LA PROSSIMA FRASE ARRIVERÀ")
    ]
    @Published var position = 0.0
    @Published private(set) var offsetSeconds = UserDefaults.standard.double(forKey: "leon.karaoke.lyricsOffset.v1")
    @Published var playing = false
    @Published var feedback = "Modalità laboratorio: il lettore PWA originale non è ancora collegato."
    private var activity: Activity<LeonKaraokeAttributes>?
    private var timer: Timer?
    private var lastDate = Date()
    private var cachedLines: [LeonTimedLine] = []
    private var wasTruncated = false
    private var lastWindowEnd = 0.0
    private var externalHasMore = false
    private var audioControlled = false
    private var lastPublishedPhrase = ""
    private var lastPublishDate = Date.distantPast

    // Segno intuitivo: +0.5s RITARDA le parole rispetto all'audio.
    // Un valore negativo le anticipa. Non alteriamo la velocità del brano.
    var displayedPosition: Double { LeonLyricsTiming.displayedTime(audioTime: position, offset: offsetSeconds) }
    var current: String {
        guard let i = LeonPhrasing.index(at: displayedPosition, in: phrases) else { return "" }
        return phrases[i].text
    }
    var duration: Double { phrases.last?.end ?? 0 }

    func setOffset(_ seconds: Double) {
        guard seconds.isFinite else { return }
        let rounded = LeonLyricsTiming.normalizedOffset(seconds)
        guard rounded != offsetSeconds else { return }
        offsetSeconds = rounded
        UserDefaults.standard.set(rounded, forKey: "leon.karaoke.lyricsOffset.v1")
        rebuildLines()
        lastPublishedPhrase = current
        lastPublishDate = .now
        Task { await publish() }
    }

    func importLyrics(data: Data, filename: String, displayTitle: String? = nil) throws {
        guard data.count < 2_000_000 else { throw CocoaError(.fileReadTooLarge) }
        let file = try JSONDecoder().decode(LeonLyricsFile.self, from: data)
        let parsed = LeonPhrasing.phrases(from: file)
        guard !parsed.isEmpty else { throw CocoaError(.fileReadCorruptFile) }
        stop()
        externalHasMore = false
        phrases = parsed
        songTitle = displayTitle ?? filename.replacingOccurrences(of: ".json", with: "")
        rebuildLines()
        feedback = "Caricati \(file.words.count) vocaboli, \(parsed.count) frasi. \(wasTruncated ? "Testo lungo: verrà inviato a finestre mentre l'app è attiva." : "Timeline completa e compatta.")"
    }

    private func rebuildLines() {
        // Manteniamo 3.500 byte al massimo per il ContentState, incluse
        // codifiche UTF-8, caratteri Unicode ed escape JSON.
        var fitted: [LeonTimedLine] = []
        let startIndex = max(0, phrases.lastIndex(where: { $0.start <= displayedPosition }) ?? 0)
        for phrase in phrases.dropFirst(startIndex) {
            let one = LeonTimedLine(d: Int((phrase.start * 10).rounded()),
                                    e: Int((phrase.end * 10).rounded()),
                                    v: phrase.text)
            let proposal = fitted + [one]
            let test = LeonKaraokeAttributes.ContentState(
                anchorEpoch: Date().timeIntervalSince1970,
                anchorPosition: 0, isPlaying: true,
                phraseFallback: "", hasMore: true, lines: proposal)
            guard let bytes = try? JSONEncoder().encode(test), bytes.count <= 3_500 else { break }
            fitted.append(one)
        }
        cachedLines = fitted
        wasTruncated = externalHasMore || startIndex + fitted.count < phrases.count
        lastWindowEnd = Double(fitted.last?.e ?? 0) / 10
    }

    func start() { audioControlled = false; begin(shouldPlay: true) }

    func audioStart() {
        audioControlled = true
        begin(shouldPlay: true)
    }

    func syncAudio(time: Double, isPlaying: Bool) {
        // L'audio e' l'unica sorgente di verita' per il tempo karaoke.
        audioControlled = true
        position = min(max(0, time), duration)
        let changed = playing != isPlaying
        playing = isPlaying
        lastDate = Date()
        let phrase = current
        if wasTruncated && displayedPosition >= lastWindowEnd - 8 { rebuildLines() }
        // L'aggiornamento del ContentState e' una richiesta; iOS puo' comunque
        // diradare l'effettivo ridisegno della schermata di blocco / CarPlay.
        if changed || (phrase != lastPublishedPhrase && Date().timeIntervalSince(lastPublishDate) >= 2.0) {
            lastPublishedPhrase = phrase
            lastPublishDate = Date()
            Task { await publish() }
        }
    }

    private func begin(shouldPlay: Bool) {
        guard ActivityAuthorizationInfo().areActivitiesEnabled else {
            feedback = "Attiva Live Activities nelle Impostazioni iPhone per Leon Karaoke."
            return
        }
        rebuildLines()
        playing = shouldPlay
        lastDate = Date()
        if activity == nil {
            do {
                let attr = LeonKaraokeAttributes(songTitle: songTitle)
                activity = try Activity.request(attributes: attr,
                    content: ActivityContent(state: state(), staleDate: nil))
            } catch {
                feedback = "Avvio Live Activity fallito: \(error.localizedDescription)"
                playing = false
                return
            }
        }
        timer?.invalidate()
        timer = nil
        if shouldPlay && !audioControlled {
            timer = Timer.scheduledTimer(withTimeInterval: 0.25, repeats: true) { [weak self] _ in
                Task { @MainActor in self?.tick() }
            }
        }
        feedback = "Timeline temporizzata inviata alla Live Activity. Verifica dimensioni e aggiornamento su CarPlay reale. \(wasTruncated ? "Testo lungo: finestre aggiornate finché l’app è attiva." : "")"
        Task { await publish() }
    }

    // Dati passati esplicitamente dalla PWA via URL schema da un click utente.
    // Il Companion e' un visualizzatore: NON puo' osservare Safari in background.
    func applyBridgeURL(_ url: URL) {
        guard url.scheme?.lowercased() == "guitarleoncarplay", url.host == "sync",
              let component = URLComponents(url: url, resolvingAgainstBaseURL: false),
              let base64 = component.queryItems?.first(where: { $0.name == "data" })?.value,
              base64.count <= 12000 else {
            feedback = "Collegamento CarPlay non valido."
            return
        }
        let normalized = base64.replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
        let padded = normalized + String(repeating: "=", count: (4 - normalized.count % 4) % 4)
        guard let json = Data(base64Encoded: padded), json.count <= 4096,
              let item = try? JSONDecoder().decode(LeonBridgeSnapshot.self, from: json),
              item.v == 1, !item.l.isEmpty, item.l.count <= 36,
              item.p.isFinite, item.p >= 0, item.p < 86400,
              item.d.isFinite, item.d >= 0, item.d < 86400,
              item.l.allSatisfy({ $0.d >= 0 && $0.e > $0.d && $0.e < 864000 && $0.v.count <= 100 })
        else { feedback = "Dati del brano assenti o non validi."; return }
        stop()
        externalHasMore = item.h
        songTitle = String(item.t.prefix(85))
        phrases = item.l.map { LeonPhrase(start: Double($0.d)/10,
                                          end: Double($0.e)/10,
                                          text: $0.v) }
        position = item.p
        rebuildLines()
        feedback = "Ricevuti \(phrases.count) versi dalla PWA. Play/Pausa successivi richiedono un nuovo invio manuale dalla PWA."
        begin(shouldPlay: item.r)
    }

    func pause() {
        if playing && !audioControlled { advanceClock() }
        playing = false
        timer?.invalidate()
        timer = nil
        Task { await publish() }
    }

    func seek(to seconds: Double) {
        position = min(max(0, seconds), duration)
        lastDate = Date()
        rebuildLines()
        Task { await publish() }
    }

    func stop() {
        playing = false
        audioControlled = false
        lastPublishedPhrase = ""
        timer?.invalidate()
        timer = nil
        position = 0
        let old = activity
        activity = nil
        if let old { Task { await old.end(nil, dismissalPolicy: .immediate) } }
    }

    private func state() -> LeonKaraokeAttributes.ContentState {
        .init(anchorEpoch: Date().timeIntervalSince1970,
              anchorPosition: displayedPosition,
              isPlaying: playing,
              phraseFallback: current,
              hasMore: wasTruncated,
              lines: cachedLines)
    }

    private func advanceClock() {
        guard playing else { return }
        let now = Date()
        position = min(duration, position + max(0, now.timeIntervalSince(lastDate)))
        lastDate = now
    }

    private func tick() {
        advanceClock()
        if playing && wasTruncated && displayedPosition >= lastWindowEnd - 8 {
            rebuildLines()
            Task { await publish() }
        }
        if playing && position >= duration {
            playing = false
            timer?.invalidate()
            timer = nil
            Task { await publish() }
        }
    }

    private func publish() async {
        guard let activity else { return }
        await activity.update(ActivityContent(state: state(), staleDate: nil))
    }
}

// Finestra privata di frasi ricevuta dalla pagina web, mai token Google Drive.
private struct LeonBridgeSnapshot: Decodable {
    let v: Int
    let t: String
    let p: Double
    let d: Double
    let r: Bool
    let h: Bool
    let l: [LeonTimedLine]
}
