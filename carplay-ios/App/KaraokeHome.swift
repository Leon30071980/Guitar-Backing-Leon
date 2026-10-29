import SwiftUI
import UniformTypeIdentifiers

struct KaraokeHome: View {
    @StateObject private var engine = KaraokePreviewEngine()
    @State private var importerVisible = false
    @StateObject private var drive = GoogleDriveLibrary()
    @State private var loadingSong = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 15) {
                Text("Guitar Leon · CarPlay Karaoke").font(.title2.bold())
                Text("v1.4 — Libreria Google Drive privata")
                    .font(.caption).foregroundStyle(.secondary)
                Group {
                    HStack {
                        Text("Libreria Google Drive").font(.headline)
                        Spacer()
                        if drive.connected {
                            Button("Aggiorna") { Task { await drive.refreshLibrary() } }
                                .disabled(drive.loading)
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
                            Text("Seleziona il brano: il testo verrà scaricato automaticamente, senza import manuale.")
                                .font(.footnote)
                            ForEach(drive.songs) { song in
                                Button {
                                    Task {
                                        guard !loadingSong else { return }
                                        loadingSong = true
                                        defer { loadingSong = false }
                                        do {
                                            let lyrics = try await drive.fetchLyrics(for: song)
                                            try engine.importLyrics(data: lyrics, filename: "testo.json", displayTitle: song.name)
                                            drive.selected = song.id
                                        } catch { engine.feedback = error.localizedDescription }
                                    }
                                } label: {
                                    HStack {
                                        VStack(alignment: .leading) {
                                            Text(song.name).font(.body).lineLimit(2)
                                            if !song.hasLyrics {
                                                Text("Testo non disponibile").font(.caption).foregroundStyle(.secondary)
                                            }
                                        }
                                        Spacer()
                                        if drive.selected == song.id { Image(systemName: "checkmark.circle.fill") }
                                    }
                                }
                                .disabled(!song.hasLyrics || loadingSong)
                            }
                        }
                        Button("Scollega Google") { drive.disconnect() }
                            .font(.footnote).tint(.secondary)
                    }
                }
                Divider()
                                Text("Anteprima riquadro CarPlay").font(.headline)
                VStack {
                    Text(engine.current.uppercased())
                        .font(.system(size: 25, weight: .heavy, design: .rounded))
                        .minimumScaleFactor(0.5)
                        .lineLimit(2)
                        .multilineTextAlignment(.center)
                        .foregroundStyle(.white)
                        .frame(width: 230, height: 90)
                }
                .frame(maxWidth: .infinity)
                .background(.black, in: RoundedRectangle(cornerRadius: 14))
                Text(engine.songTitle).font(.subheadline.bold())
                HStack {
                    Button("Importa lyrics.json") { importerVisible = true }
                        .buttonStyle(.borderedProminent)
                    Button(engine.playing ? "Riprendi" : "Avvia prova") { engine.start() }
                        .buttonStyle(.bordered)
                }
                HStack {
                    Button("Pausa") { engine.pause() }.buttonStyle(.bordered)
                    Button("Stop") { engine.stop() }.buttonStyle(.bordered)
                    Button("Da capo") { engine.seek(to: 0) }.buttonStyle(.bordered)
                }
                Text("Posizione: \(Int(engine.position)) s / \(Int(engine.duration)) s")
                Slider(value: Binding(get: { engine.position },
                                      set: { engine.seek(to: $0) }),
                       in: 0...max(1, engine.duration))
                HStack {
                    Button("− 1 s") { engine.seek(to: engine.position - 1) }
                    Spacer()
                    Text("Riallineamento manuale").font(.caption)
                    Spacer()
                    Button("+ 1 s") { engine.seek(to: engine.position + 1) }
                }
                Text(engine.feedback).font(.footnote).foregroundStyle(.secondary)
                Divider()
                Text("Limite della prova").font(.headline)
                Text("La timeline viene calcolata dall'orologio nella Live Activity: l'aggiornamento visivo in background può essere ritardato da iOS. Con ?carplay=1 la PWA può passare titolo, frasi e tempo al Companion. Dopo il passaggio non riceve aggiornamenti automatici da Safari. Il login Google della PWA resta nel browser originale.")
                    .font(.footnote)
            }
            .padding()
        }
        .onOpenURL { url in engine.applyBridgeURL(url) }
        .task { await drive.onLaunch() }
        .fileImporter(isPresented: $importerVisible, allowedContentTypes: [.json]) { result in
            do {
                let url = try result.get()
                let access = url.startAccessingSecurityScopedResource()
                defer { if access { url.stopAccessingSecurityScopedResource() } }
                try engine.importLyrics(data: Data(contentsOf: url), filename: url.lastPathComponent)
            } catch { engine.feedback = "Importazione fallita: \(error.localizedDescription)" }
        }
    }
}
