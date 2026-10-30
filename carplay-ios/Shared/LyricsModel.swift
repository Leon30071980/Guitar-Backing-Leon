import Foundation

struct LeonWord: Codable, Hashable {
    let start: Double
    let end: Double
    let text: String
    let line: Int
}

struct LeonLyricsFile: Decodable {
    var words: [LeonWord]
    var offset_seconds: Double?
}

struct LeonPhrase: Hashable {
    var start: Double
    var end: Double
    var text: String
}

// Same timestamps as Guitar Backing Leon v2.63: no chord data is imported.
// Combine extremely long lines to fit the limited Live Activity tile.
enum LeonPhrasing {
    static func phrases(from file: LeonLyricsFile, maximumLength: Int = 52) -> [LeonPhrase] {
        let offset = file.offset_seconds ?? 0
        let sorted = file.words.filter { $0.end > $0.start && !$0.text.isEmpty }
            .sorted { $0.start < $1.start }
        var result: [LeonPhrase] = []
        var pending: [LeonWord] = []
        func flush() {
            guard let first = pending.first, let last = pending.last else { return }
            result.append(LeonPhrase(start: max(0, first.start + offset),
                                     end: max(0.01, last.end + offset),
                                     text: pending.map(\.text).joined(separator: " ")))
            pending.removeAll()
        }
        for word in sorted {
            let candidate = (pending.map(\.text) + [word.text]).joined(separator: " ")
            if let last = pending.last, (word.line != last.line || candidate.count > maximumLength) {
                flush()
            }
            pending.append(word)
        }
        flush()
        return result
    }

    static func index(at time: Double, in phrases: [LeonPhrase]) -> Int? {
        guard !phrases.isEmpty else { return nil }
        // Preview the next verse slightly before its beginning, as on the PWA.
        guard time + 0.25 >= phrases[0].start else { return nil }
        if let i = phrases.indices.last(where: { phrases[$0].start <= time + 0.25 }) { return i }
        return nil
    }
}
