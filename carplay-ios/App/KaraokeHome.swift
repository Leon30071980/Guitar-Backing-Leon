import SwiftUI
import UniformTypeIdentifiers

struct KaraokeHome: View {
    @StateObject private var engine = KaraokePreviewEngine()
    @StateObject private var audio = LeonAudioPlayer()
    @StateObject private var drive = GoogleDriveLibrary()
    @State private var importerVisible = false
    @State private var loadingSong = false
    @State private var queue = LeonQueueModel()
    @State private var search = ""
    @State private var queueMessage = "Aggiungi uno o più brani alla coda."

    private let savedQueueKey = "leon.karaoke.queue.v1"

    private var filteredSongs: [LeonDriveSong] {
        search.isEmpty ? drive.songs : drive.songs.filter { $0.name.localizedStandardContains(search) }
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 15) {
                Text("Guitar Leon · CarPlay Karaoke").font(.title2.bold())
                Text("v1.6 — Coda musicale + offset karaoke · chitarra sempre ON")
                    .font(.caption).foregroundStyle(.secondary)

                HStack {
                    Text("Libreria Google Drive").font(.headline)
                    Spacer()
                    if drive.connected {
                        Button("Aggiorna") { Task { await drive.refreshLibrary(); reconcileQueue() } }
                            .disabled(drive.loading || loadingSong)
                    }
                }
                Text(drive.message).font(.footnote).foregroundStyle(.secondary)
                if !drive.connected || drive.songs.isEmpty {
                    Button("Collega Google Drive") {
                        Task { await drive.connect(); reconcileQueue() }
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(drive.loading || !drive.configured)
                }
                if drive.loading || loadingSong { ProgressView("Preparazione del brano...") }

                if drive.connected {
                    if drive.songs.isEmpty {
                        Text("Nessun brano visibile nell'indice.").font(.footnote)
                    } else {
                        TextField("Cerca una canzone", text: $search)
                            .textFieldStyle(.roundedBorder)
                        Text("▶ Riproduci subito · + Aggiungi alla coda")
                            .font(.caption).foregroundStyle(.secondary)
                        ForEach(filteredSongs) { song in
                            HStack(spacing: 10) {
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(song.name).font(.subheadline).lineLimit(2)
                                    if !song.canPlay {
                                        Text("Audio full / no_vocals mancante")
                                            .font(.caption).foregroundStyle(.orange)
                                    } else if !song.hasLyrics {
                                        Text("Karaoke non disponibile")
                                            .font(.caption).foregroundStyle(.secondary)
                                    }
                                }
                                Spacer(minLength: 3)
                                if queue.ids.contains(song.id) {
                                    Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
                                }
                                Button {
                                    Task { await selectSong(song, autoplay: true) }
                                } label: { Image(systemName: "play.fill") }
                                    .accessibilityLabel("Riproduci \(song.name)")
                                    .disabled(!song.canPlay || !song.hasLyrics || loadingSong)
                                Button { addToQueue(song) } label: {
                                    Image(systemName: "plus.circle.fill")
                                }
                                    .accessibilityLabel("Aggiungi \(song.name) alla coda")
                                    .disabled(!song.canPlay || !song.hasLyrics || loadingSong || queue.ids.contains(song.id))
                            }
                            .padding(.vertical, 3)
                        }
                    }
                    Button("Scollega Google") {
                        audio.stop(); engine.stop(); drive.disconnect()
                        queue = LeonQueueModel()
                        persistQueue()
                    }.font(.footnote).tint(.secondary)
                }

                Divider()
                HStack {
                    Text("Coda di riproduzione").font(.headline)
                    Spacer()
                    Text("\(queue.count) brani").font(.caption).foregroundStyle(.secondary)
                }
                if queue.ids.isEmpty {
                    Text("La coda è vuota: usa + vicino ai brani della libreria.")
                        .font(.footnote).foregroundStyle(.secondary)
                } else {
                    ForEach(Array(queue.ids.enumerated()), id: \.element) { index, id in
                        HStack(spacing: 7) {
                            if queue.activeID == id {
                                Image(systemName: "speaker.wave.2.fill").foregroundStyle(.green)
                            } else {
                                Text("\(index + 1).").foregroundStyle(.secondary)
                            }
                            Text(drive.songs.first(where: { $0.id == id })?.name ?? id)
                                .font(.subheadline)
                                .lineLimit(2)
                            Spacer(minLength: 2)
                            Button { moveQueue(id, by: -1) } label: {
                                Image(systemName: "arrow.up")
                            }
                                .disabled(index == 0 || loadingSong)
                                .accessibilityLabel("Sposta brano in alto")
                            Button { moveQueue(id, by: 1) } label: {
                                Image(systemName: "arrow.down")
                            }
                                .disabled(index == queue.count - 1 || loadingSong)
                                .accessibilityLabel("Sposta brano in basso")
                            Button { removeFromQueue(id) } label: {
                                Image(systemName: "xmark.circle")
                            }
                                .disabled(queue.activeID == id || loadingSong)
                                .accessibilityLabel("Rimuovi brano dalla coda")
                        }
                        .padding(.vertical, 4)
                    }
                    HStack {
                        Button("▶ Riproduci coda") {
                            if let first = queue.activeID ?? queue.ids.first,
                               let song = drive.songs.first(where: { $0.id == first }) {
                                Task { await selectSong(song, autoplay: true) }
                            }
                        }
                            .buttonStyle(.borderedProminent)
                            .disabled(loadingSong || drive.loading)
                        Spacer()
                        Button("Svuota prossimi") {
                            queue.clearUpcoming(); persistQueue()
                        }.font(.footnote)
                    }
                }
                Text(queueMessage).font(.caption).foregroundStyle(.secondary)

                Divider()
                Text("Anteprima riquadro CarPlay").font(.headline)
                VStack {
                    Text(engine.current.uppercased())
                        .font(.system(size: 25, weight: .heavy, design: .rounded))
                        .minimumScaleFactor(0.5).lineLimit(2)
                        .multilineTextAlignment(.center).foregroundStyle(.white)
                        .frame(width: 230, height: 90)
                }
                .frame(maxWidth: .infinity)
                .background(.black, in: RoundedRectangle(cornerRadius: 14))
                Text(engine.songTitle).font(.subheadline.bold())
                if audio.ready {
                    HStack(spacing: 12) {
                        Button(audio.playing ? "Pausa" : "▶ Play") {
                            if audio.playing { audio.pause() }
                            else { audio.play(); if audio.playing { engine.audioStart() } }
                        }.buttonStyle(.borderedProminent)
                        Button("■ Stop") { audio.pause(); audio.seek(to: 0); engine.stop() }
                            .buttonStyle(.bordered)
                        Button(audio.vocalsEnabled ? "Voce ON" : "Voce OFF") { audio.toggleVocals() }
                            .buttonStyle(.borderedProminent)
                            .tint(audio.vocalsEnabled ? .green : .orange)
                    }
                    HStack(spacing: 18) {
                        Button { Task { await previousSong() } } label: {
                            Label("Precedente", systemImage: "backward.end.fill")
                        }
                        Button { Task { await nextSong() } } label: {
                            Label("Successivo", systemImage: "forward.end.fill")
                        }.disabled(queue.nextID == nil || loadingSong)
                    }.buttonStyle(.bordered)
                    Text("Chitarra: sempre ON").font(.footnote.bold())
                    Text(audio.message).font(.footnote).foregroundStyle(.secondary)
                } else {
                    Text("Scegli un brano dalla libreria o avvia la coda.")
                        .font(.footnote).foregroundStyle(.secondary)
                    Button("Importa lyrics.json (sola prova)") { importerVisible = true }
                        .buttonStyle(.bordered)
                    Button("Avvia prova senza audio") { engine.start() }.buttonStyle(.bordered)
                    HStack {
                        Button("Pausa") { engine.pause() }.buttonStyle(.bordered)
                        Button("Stop") { engine.stop() }.buttonStyle(.bordered)
                    }
                }

                let currentPosition = audio.ready ? audio.position : engine.position
                let currentDuration = audio.ready ? audio.duration : engine.duration
                Text("Posizione: \(Int(currentPosition)) s / \(Int(currentDuration)) s")
                Slider(value: Binding(get: { audio.ready ? audio.position : engine.position },
                                      set: { p in audio.ready ? audio.seek(to: p) : engine.seek(to: p) }),
                       in: 0...max(1, currentDuration))

                Divider()
                HStack {
                    Text("Sincronizzazione karaoke").font(.headline)
                    Spacer()
                    Text(String(format: "%+.1f s", engine.offsetSeconds))
                        .monospacedDigit().font(.subheadline.bold())
                }
                Text("Valore positivo: parole più tardi. Valore negativo: parole prima. La musica non cambia.")
                    .font(.footnote).foregroundStyle(.secondary)
                Slider(value: Binding(get: { engine.offsetSeconds }, set: { engine.setOffset($0) }),
                       in: -3...3, step: 0.1)
                    .accessibilityLabel("Ritardo delle parole rispetto all'audio")
                HStack {
                    Button("− 0,1 s") { engine.setOffset(engine.offsetSeconds - 0.1) }
                    Spacer()
                    Button("Azzera") { engine.setOffset(0) }
                    Spacer()
                    Button("+ 0,1 s") { engine.setOffset(engine.offsetSeconds + 0.1) }
                }.buttonStyle(.bordered)
                Text("Uscita audio: \(audio.audioRoute). Latenza segnalata da iOS: ~\(Int(audio.systemOutputLatency * 1000)) ms (stima parziale, non ritardo totale CarPlay).")
                    .font(.caption).foregroundStyle(.secondary)
                Text("Offset salvato sull'iPhone. Provalo sul display CarPlay da fermo.")
                    .font(.caption).foregroundStyle(.secondary)
                Text(engine.feedback).font(.footnote).foregroundStyle(.secondary)
                Text("Le Live Activities possono rallentare o fermare il cambio frase con iPhone bloccato: CarPlay reale va verificato.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            .padding()
        }
        .onOpenURL { url in
            audio.stop()
            engine.applyBridgeURL(url)
        }
        .task {
            queue = LeonQueueModel(ids: UserDefaults.standard.stringArray(forKey: savedQueueKey) ?? [])
            audio.onProgress = { [weak engine] p, active in
                engine?.syncAudio(time: p, isPlaying: active)
            }
            audio.onFinished = { Task { @MainActor in await nextSong(automatic: true) } }
            audio.onNext = { Task { @MainActor in await nextSong() } }
            audio.onPrevious = { Task { @MainActor in await previousSong() } }
            await drive.onLaunch()
            reconcileQueue()
        }
        .fileImporter(isPresented: $importerVisible, allowedContentTypes: [.json]) { result in
            do {
                let url = try result.get()
                let access = url.startAccessingSecurityScopedResource()
                defer { if access { url.stopAccessingSecurityScopedResource() } }
                audio.stop()
                try engine.importLyrics(data: Data(contentsOf: url), filename: url.lastPathComponent)
            } catch { engine.feedback = "Importazione fallita: \(error.localizedDescription)" }
        }
    }

    private func persistQueue() {
        UserDefaults.standard.set(queue.ids, forKey: savedQueueKey)
        audio.setSkipAvailability(previous: audio.ready || queue.previousID != nil,
                                  next: queue.nextID != nil)
    }

    private func reconcileQueue() {
        guard drive.connected, !drive.songs.isEmpty else { return }
        queue.retain(availableIDs: Set(drive.songs.map(\.id)))
        persistQueue()
    }

    private func addToQueue(_ song: LeonDriveSong) {
        if queue.enqueue(song.id) {
            queueMessage = "Aggiunto in coda: \(song.name)"
            persistQueue()
            if audio.playing { prefetchNextSong() }
        }
    }

    private func moveQueue(_ id: String, by direction: Int) {
        queue.move(id, direction: direction)
        persistQueue()
    }

    private func removeFromQueue(_ id: String) {
        guard queue.activeID != id else { return }
        queue.remove(id)
        persistQueue()
    }

    private func selectSong(_ song: LeonDriveSong, autoplay: Bool) async {
        guard !loadingSong, song.canPlay, song.hasLyrics else { return }
        loadingSong = true
        audio.stop()
        engine.stop()
        defer { loadingSong = false }
        do {
            // Titolo, versi e MP3 provengono da uno stesso record libreria.json.
            let lyrics = try await drive.fetchLyrics(for: song)
            try engine.importLyrics(data: lyrics, filename: "testo.json", displayTitle: song.name)
            audio.message = "Scaricamento della base con voce..."
            let full = try await drive.downloadTrack(for: song, mix: "full")
            audio.message = "Scaricamento della base senza voce..."
            let noVocals = try await drive.downloadTrack(for: song, mix: "no_vocals")
            try audio.load(fullURL: full, noVocalsURL: noVocals, title: song.name)
            queue.activate(song.id)
            persistQueue()
            drive.selected = song.id
            engine.feedback = "Brano pronto: testo sincronizzato all'audio, offset applicato."
            if autoplay {
                audio.play()
                if audio.playing { engine.audioStart() }
            }
            prefetchNextSong()
        } catch {
            audio.stop()
            queueMessage = "Impossibile preparare \(song.name): \(error.localizedDescription)"
            engine.feedback = queueMessage
        }
    }

    private func nextSong(automatic: Bool = false) async {
        guard !loadingSong else { return }
        guard let id = queue.nextID,
              let song = drive.songs.first(where: { $0.id == id }) else {
            if automatic { queueMessage = "Coda terminata." }
            return
        }
        await selectSong(song, autoplay: true)
    }

    private func previousSong() async {
        guard !loadingSong, audio.ready else { return }
        if audio.position > 3 {
            audio.seek(to: 0)
            return
        }
        guard let id = queue.previousID,
              let song = drive.songs.first(where: { $0.id == id }) else {
            audio.seek(to: 0)
            return
        }
        await selectSong(song, autoplay: true)
    }

    private func prefetchNextSong() {
        guard let id = queue.nextID,
              let song = drive.songs.first(where: { $0.id == id }) else { return }
        // Una sola canzone di anticipo, senza pubblicazione o duplicazione su Drive.
        Task { @MainActor in
            _ = try? await drive.fetchLyrics(for: song)
            _ = try? await drive.downloadTrack(for: song, mix: "full")
            _ = try? await drive.downloadTrack(for: song, mix: "no_vocals")
        }
    }
}
