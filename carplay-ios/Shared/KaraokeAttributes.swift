import ActivityKit
import Foundation

// ActivityKit impone 4KB totali al payload aggiornato.
// Manteniamo la timeline compatta nel ContentState, senza App Group,
// API esterne, Google token o accordi.
struct LeonTimedLine: Codable, Hashable {
    var d: Int       // inizio in decimi di secondo
    var e: Int       // fine in decimi di secondo
    var v: String    // solo testo
}

struct LeonKaraokeAttributes: ActivityAttributes {
    struct ContentState: Codable, Hashable {
        var anchorEpoch: Double
        var anchorPosition: Double
        var isPlaying: Bool
        var phraseFallback: String
        var hasMore: Bool
        var lines: [LeonTimedLine]
    }
    let songTitle: String
}

// Con l'app sospesa il widget prova a ricavare il verso dall'ora corrente.
// L'OS puo' diradare o fermare i ridisegni di TimelineView: non e' garantita
// una cadenza al secondo in CarPlay reale.
enum LeonLiveClock {
    static func time(at now: Date, state: LeonKaraokeAttributes.ContentState) -> Double {
        let elapsed = state.isPlaying ? max(0, now.timeIntervalSince1970 - state.anchorEpoch) : 0
        return state.anchorPosition + elapsed
    }

    static func line(at now: Date, state: LeonKaraokeAttributes.ContentState) -> String {
        let tenth = Int((time(at: now, state: state) + 0.25) * 10)
        guard let first = state.lines.first else { return state.phraseFallback }
        if tenth < first.d - 3 { return "♪ INTRO STRUMENTALE" }
        guard let i = state.lines.lastIndex(where: { $0.d <= tenth }) else { return first.v }
        let line = state.lines[i]
        if tenth > line.e + 15 {
            if i + 1 < state.lines.count { return "♪ INTERMEZZO" }
            return state.hasMore ? "♪ KARAOKE IN ATTESA" : "♪ FINALE STRUMENTALE"
        }
        return line.v
    }
}
