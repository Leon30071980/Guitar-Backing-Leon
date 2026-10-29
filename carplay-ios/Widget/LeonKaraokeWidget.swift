import ActivityKit
import SwiftUI
import WidgetKit

struct LeonKaraokeView: View {
    let context: ActivityViewContext<LeonKaraokeAttributes>
    @Environment(\.activityFamily) private var activityFamily

    var body: some View {
        let small = activityFamily == .small
        TimelineView(.periodic(from: .now, by: 1)) { timeline in
            let phrase = LeonLiveClock.line(at: timeline.date, state: context.state)
            VStack(spacing: 0) {
                Text(phrase.isEmpty ? "♪ PAUSA MUSICALE" : phrase.uppercased())
                    .font(.system(size: small ? 27 : 27, weight: .heavy, design: .rounded))
                    .foregroundStyle(.white)
                    .multilineTextAlignment(.center)
                    .lineLimit(small ? 2 : 3)
                    .minimumScaleFactor(0.50)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                    .accessibilityLabel(phrase)
            }
            .padding(small ? 5 : 10)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color.black)
            .activityBackgroundTint(.black)
            .activitySystemActionForegroundColor(.white)
        }
    }
}

struct LeonKaraokeWidget: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: LeonKaraokeAttributes.self) { context in
            LeonKaraokeView(context: context)
        } dynamicIsland: { context in
            DynamicIsland {
                DynamicIslandExpandedRegion(.center) {
                    Text(LeonLiveClock.line(at: .now, state: context.state))
                        .font(.headline)
                        .multilineTextAlignment(.center)
                }
            } compactLeading: {
                Image(systemName: "music.mic").foregroundStyle(.yellow)
            } compactTrailing: {
                Text(context.state.phraseFallback).lineLimit(1)
            } minimal: {
                Image(systemName: "music.mic").foregroundStyle(.yellow)
            }
        }
        .supplementalActivityFamilies([.small])
    }
}

@main
struct LeonKaraokeWidgetBundle: WidgetBundle {
    var body: some Widget { LeonKaraokeWidget() }
}
