import SwiftUI
import UniformTypeIdentifiers

struct KaraokeHome: View {
    @StateObject private var engine = KaraokePreviewEngine()
    @StateObject private var audio = LeonAudioPlayer()
    @StateObject private var drive = GoogleDriveLibrary()
    @State private var importerVisible = false
    @State private var loadingSong = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 15) {
                Text("Guitar Leon · CarPlay Karaoke").font(.title2.bold())
                Text("v1.5 — Audio + Google Drive · chitarra sempre ON")
                    .font(.caption).foregroundStyle(.secondary)
                HStack {
                    Text("Libreria Google Drive").font(.headline)
                    Spacer()
                    if drive.connected {
                        Button("Aggiorna") { Task { await drive.refreshLibrary() } }
                            .disabled(drive.loading || loadingSong)
                    }
                }
                Text(drive.message).font(.footnote).foregroundStyle(.secondary)
                if !drive.connected || drive.songs.isEmpty {
                    Button("Collega Google Drive") { Task { await drive.connect() } }
                        .buttonStyle(.borderedProminent)
                        .disabled(drive.loading || !drive.configured)
                }
                if drive.loading || loadingSong { ProgressView() }
                if drive.connected {
                    if drive.songs.isEmpty {
                        Text("Nessun brano visibile nell'indice.").font(.footnote)
                    } else {
                        Text("Tocca il brano: testo e basi musicali verranno scaricati da Drive.")
                            .font(.footnote)
                        ForEach(drive.songs) { song in
                            Button { Task { await selectSong(song) } } label: {
                                HStack {
                                    VStack(alignment: .leading, spacing: 3) {
                                        Text(song.name).font(.body).lineLimit(2)
                                        if !song.canPlay {
                                            Text("Audio full / no_vocals non presente")
                                                .font(.caption).foregroundStyle(.orange)
                                        } else if !song.hasLyrics {
                                            Text("Karaoke non disponibile").font(.caption).foregroundStyle(.secondary)
                                        }
                                    }
                                    Spacer()
                                    if drive.selected == song.id { Image(systemName: "checkmark.circle.fill") }
                                }
                            }
                            .disabled(!song.canPlay || !song.hasLyrics || loadingSong)
                        }
                    }
                    Button("Scollega Google") {
                        audio.stop(); engine.stop(); drive.disconnect()
                    }.font(.footnote).tint(.secondary)
                }
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
                            else { engine.audioStart(); audio.play() }
                        }.buttonStyle(.borderedProminent)
                        Button("■ Stop") {
                            audio.pause(); audio.seek(to: 0); engine.stop()
                        }.buttonStyle(.bordered)
                        Button(audio.vocalsEnabled ? "Voce ON" : "Voce OFF") { audio.toggleVocals() }
                            .buttonStyle(.borderedProminent)
                            .tint(audio.vocalsEnabled ? .green : .orange)
                    }
                    Text("Chitarra: sempre ON").font(.footnote.bold())
                    Text(audio.message).font(.footnote).foregroundStyle(.secondary)
                } else {
                    Text("Il lettore audio si attiva dopo aver selezionato un brano Drive.")
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
                if !audio.ready {
                    HStack {
                        Button("− 1 s") { engine.seek(to: engine.position - 1) }
                        Spacer()
                        Text("Riallineamento prova").font(.caption)
                        Spacer()
                        Button("+ 1 s") { engine.seek(to: engine.position + 1) }
                    }
                }
                Text(engine.feedback).font(.footnote).foregroundStyle(.secondary)
                Text("Le Live Activities possono rallentare o fermare il cambio frase con iPhone bloccato: il test su CarPlay resta necessario.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            .padding()
        }
        .onOpenURL { url in
            audio.stop()
            engine.applyBridgeURL(url)
        }
        .task {
            audio.onProgress = { p, active in engine.syncAudio(time: p, isPlaying: active) }
            await drive.onLaunch()
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

    private func selectSong(_ song: LeonDriveSong) async {
        guard !loadingSong else { return }
        loadingSong = true
        audio.stop()
        engine.stop()
        defer { loadingSong = false }
        do {
            // Titolo, parole e due mix provengono dallo STESSO elemento di libreria.json.
            let lyrics = try await drive.fetchLyrics(for: song)
            try engine.importLyrics(data: lyrics, filename: "testo.json", displayTitle: song.name)
            audio.message = "Scaricamento della base con voce..."
            let full = try await drive.downloadTrack(for: song, mix: "full")
            audio.message = "Scaricamento della base senza voce..."
            let noVocals = try await drive.downloadTrack(for: song, mix: "no_vocals")
            try audio.load(fullURL: full, noVocalsURL: noVocals, title: song.name)
            drive.selected = song.id
            engine.feedback = "Brano pronto: premi Play. Testo sincronizzato al lettore audio."
        } catch {
            audio.stop()
            engine.feedback = "Brano non pronto: \(error.localizedDescription)"
        }
    }
}
