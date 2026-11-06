import SwiftUI

/// Offset delle parole, indipendente dal volume e dalla temporizzazione MP3.
/// I pulsanti hanno una superficie di tocco >= 52 pt, il cursore 46 pt.
struct LeonOffsetControl: View {
    let value: Double
    let onChange: (Double) -> Void

    private let thumb: CGFloat = 46
    private let minimum = -3.0
    private let maximum = 3.0

    private var progress: CGFloat {
        CGFloat((LeonLyricsTiming.normalizedOffset(value) - minimum) / (maximum - minimum))
    }

    private func update(_ x: CGFloat, width: CGFloat) {
        let available = max(1, width - thumb)
        let fraction = min(1, max(0, (x - thumb / 2) / available))
        let offset = minimum + Double(fraction) * (maximum - minimum)
        onChange(LeonLyricsTiming.normalizedOffset(offset))
    }

    private func adjust(_ amount: Double) {
        onChange(LeonLyricsTiming.normalizedOffset(value + amount))
    }

    var body: some View {
        VStack(spacing: 10) {
            GeometryReader { geometry in
                let width = max(thumb, geometry.size.width)
                let x = thumb / 2 + progress * (width - thumb)
                ZStack(alignment: .leading) {
                    Capsule().fill(Color.secondary.opacity(0.20))
                        .frame(height: 14).padding(.horizontal, thumb / 2)
                    Capsule().fill(Color.accentColor.opacity(0.28))
                        .frame(width: max(0, x - thumb / 2), height: 14)
                        .offset(x: thumb / 2)
                    Capsule().fill(Color.secondary.opacity(0.55))
                        .frame(width: 2, height: 22)
                        .position(x: width / 2, y: 34)
                    Circle().fill(Color.accentColor)
                        .overlay(Circle().strokeBorder(.white.opacity(0.8), lineWidth: 3))
                        .frame(width: thumb, height: thumb)
                        .shadow(radius: 2)
                        .position(x: x, y: 34)
                }
                .frame(width: width, height: 68)
                .contentShape(Rectangle())
                .gesture(DragGesture(minimumDistance: 0).onChanged { gesture in
                    update(gesture.location.x, width: width)
                })
            }
            .frame(height: 68)
            .accessibilityElement()
            .accessibilityLabel("Regolazione offset karaoke")
            .accessibilityValue(String(format: "%+.1f secondi", value))
            .accessibilityAdjustableAction { direction in
                switch direction {
                case .increment: adjust(0.1)
                case .decrement: adjust(-0.1)
                @unknown default: break
                }
            }

            HStack(spacing: 8) {
                offsetButton("−0,5", amount: -0.5)
                offsetButton("−0,1", amount: -0.1)
                Button { onChange(0) } label: {
                    Text("Azzera")
                        .frame(maxWidth: .infinity, minHeight: 52)
                        .contentShape(Rectangle())
                }
                    .buttonStyle(.bordered)
                    .accessibilityLabel("Azzera ritardo karaoke")
                offsetButton("+0,1", amount: 0.1)
                offsetButton("+0,5", amount: 0.5)
            }
            .font(.callout.bold())
        }
    }

    private func offsetButton(_ label: String, amount: Double) -> some View {
        Button { adjust(amount) } label: {
            Text(label)
                .frame(maxWidth: .infinity, minHeight: 52)
                .contentShape(Rectangle())
        }
            .buttonStyle(.borderedProminent)
            .accessibilityLabel(amount > 0
                ? "Ritarda parole di \(abs(amount)) secondi"
                : "Anticipa parole di \(abs(amount)) secondi")
    }
}
