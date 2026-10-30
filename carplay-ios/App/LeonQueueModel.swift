import Foundation

// La coda conserva solo ID dell'indice Drive: nessun audio o credenziale nel repository.
// Gli ID sono univoci, l'ordine e la posizione sono gestiti localmente nell'app.
struct LeonQueueModel: Equatable {
    private(set) var ids: [String]
    private(set) var activeID: String?

    init(ids: [String] = [], activeID: String? = nil) {
        var seen = Set<String>()
        self.ids = ids.filter { !$0.isEmpty && seen.insert($0).inserted }
        self.activeID = activeID.flatMap { self.ids.contains($0) ? $0 : nil }
    }

    var count: Int { ids.count }
    var activeIndex: Int? { activeID.flatMap { ids.firstIndex(of: $0) } }
    var nextID: String? {
        guard let i = activeIndex, ids.indices.contains(i + 1) else { return nil }
        return ids[i + 1]
    }
    var previousID: String? {
        guard let i = activeIndex, i > 0 else { return nil }
        return ids[i - 1]
    }

    @discardableResult mutating func enqueue(_ id: String) -> Bool {
        guard !id.isEmpty, !ids.contains(id) else { return false }
        ids.append(id)
        return true
    }

    mutating func activate(_ id: String) {
        enqueue(id)
        activeID = id
    }

    @discardableResult mutating func advance() -> String? {
        guard let nextID else { return nil }
        activeID = nextID
        return nextID
    }

    @discardableResult mutating func rewind() -> String? {
        guard let previousID else { return nil }
        activeID = previousID
        return previousID
    }

    mutating func move(_ id: String, direction: Int) {
        guard let i = ids.firstIndex(of: id), (direction == -1 || direction == 1),
              ids.indices.contains(i + direction) else { return }
        ids.swapAt(i, i + direction)
    }

    mutating func remove(_ id: String) {
        guard let i = ids.firstIndex(of: id) else { return }
        ids.remove(at: i)
        if activeID == id { activeID = nil }
    }

    mutating func clearUpcoming() {
        ids = activeID.map { [$0] } ?? []
    }

    mutating func retain(availableIDs: Set<String>) {
        ids.removeAll { !availableIDs.contains($0) }
        if let activeID, !ids.contains(activeID) { self.activeID = nil }
    }
}
