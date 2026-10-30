import Foundation

@main struct LeonQueueAndOffsetTests {
    static func main() {
        var q = LeonQueueModel(ids: ["a", "b", "b", "c"])
        precondition(q.ids == ["a", "b", "c"], "niente duplicati")
        precondition(!q.enqueue("c"))
        precondition(q.enqueue("d") && q.count == 4)
        q.activate("a")
        precondition(q.nextID == "b" && q.previousID == nil)
        precondition(q.advance() == "b")
        precondition(q.previousID == "a" && q.nextID == "c")
        q.move("d", direction: -1)
        precondition(q.ids == ["a", "b", "d", "c"])
        precondition(q.advance() == "d")
        precondition(q.rewind() == "b")
        q.remove("d")
        precondition(q.ids == ["a", "b", "c"])
        q.clearUpcoming()
        precondition(q.ids == ["b"] && q.nextID == nil)
        q.retain(availableIDs: Set(["x"]))
        precondition(q.ids.isEmpty && q.activeID == nil)
        precondition(LeonLyricsTiming.normalizedOffset(100) == 3)
        precondition(LeonLyricsTiming.normalizedOffset(-100) == -3)
        precondition(LeonLyricsTiming.normalizedOffset(0.16) == 0.2)
        precondition(LeonLyricsTiming.displayedTime(audioTime: 20, offset: 0.5) == 19.5)
        precondition(LeonLyricsTiming.displayedTime(audioTime: 20, offset: -0.5) == 20.5)
        precondition(LeonLyricsTiming.displayedTime(audioTime: 0, offset: 0.5) == -0.5)
        print("OK: coda, avanti, indietro, riordino, rimozione, offset e segno (19 verifiche)")
    }
}
