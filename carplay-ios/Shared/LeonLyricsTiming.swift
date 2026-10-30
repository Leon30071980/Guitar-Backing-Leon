import Foundation

// Offset solo del karaoke: + ritarda il testo, - lo anticipa.
// Non modifica currentTime dei due lettori, la durata o la velocita' audio.
enum LeonLyricsTiming {
    static func normalizedOffset(_ seconds: Double) -> Double {
        guard seconds.isFinite else { return 0 }
        return (min(3, max(-3, seconds)) * 10).rounded() / 10
    }
    static func displayedTime(audioTime: Double, offset: Double) -> Double {
        audioTime - normalizedOffset(offset)
    }
}
