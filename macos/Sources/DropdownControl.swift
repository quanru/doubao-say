import SwiftUI
import AppKit

struct DropdownChoice: Identifiable {
    let id: String
    let title: String
    var destructive = false
}

/// An application-drawn dropdown shared by settings selectors and action menus.
struct DropdownControl: View {
    let label: String
    let title: String
    let identifier: String
    let choices: [DropdownChoice]
    var selectedID: String?
    var compact = false
    var disabled = false
    let select: (String) -> Void
    @State private var presented = false

    var body: some View {
        Button { presented.toggle() } label: {
            HStack(spacing: 8) {
                if compact { Image(systemName: "ellipsis").frame(width: 18) }
                else {
                    Text(title).lineLimit(1).truncationMode(.middle)
                    Spacer(minLength: 12)
                    Image(systemName: "chevron.down").font(.caption.weight(.semibold))
                }
            }
            .padding(.horizontal, 10).padding(.vertical, 7)
            .background(RoundedRectangle(cornerRadius: 6).fill(Color(nsColor: .controlBackgroundColor)))
            .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.secondary.opacity(0.3)))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain).disabled(disabled || choices.isEmpty)
        .accessibilityLabel(label).accessibilityValue(compact ? "" : title)
        .accessibilityIdentifier(identifier).help(compact ? label : title)
        .popover(isPresented: $presented, arrowEdge: .bottom) {
            DropdownList(choices: choices, selectedID: selectedID, identifier: identifier) { value in
                presented = false
                if let value = value { select(value) }
            }
        }
        .onChange(of: disabled) { if $0 { presented = false } }
    }
}

private struct DropdownList: View {
    let choices: [DropdownChoice]
    let selectedID: String?
    let identifier: String
    let finish: (String?) -> Void
    @State private var highlighted: String?
    @State private var keyMonitor: Any?

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                VStack(spacing: 2) {
                    ForEach(choices) { choice in
                        Button { finish(choice.id) } label: {
                            HStack(spacing: 8) {
                                Image(systemName: "checkmark").opacity(choice.id == selectedID ? 1 : 0)
                                    .frame(width: 14)
                                Text(choice.title).lineLimit(1)
                                Spacer(minLength: 8)
                            }
                            .foregroundColor(choice.destructive ? .red : .primary)
                            .padding(.horizontal, 10).frame(height: 30)
                            .background(RoundedRectangle(cornerRadius: 4)
                                .fill(highlighted == choice.id ? Color.accentColor.opacity(0.18) : .clear))
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain).id(choice.id)
                        .accessibilityIdentifier(identifier + "." + choice.id)
                        .accessibilityLabel(choice.title)
                        .accessibilityValue(choice.id == selectedID ? L("Selected", "已选") : "")
                        .onHover { if $0 { highlighted = choice.id } }
                    }
                }.padding(6)
            }
            .frame(width: 280, height: CGFloat(min(choices.count, 8) * 32 + 10))
            .onChange(of: highlighted) { if let value = $0 { proxy.scrollTo(value) } }
        }
        .onAppear {
            highlighted = choices.contains { $0.id == selectedID } ? selectedID : choices.first?.id
            keyMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
                guard let window = event.window, NSApp.windows.contains(where: { $0 === window }),
                      event.modifierFlags.intersection([.command, .control, .option]).isEmpty else { return event }
                switch event.keyCode {
                case 125: move(1)
                case 126: move(-1)
                case 115: highlighted = choices.first?.id
                case 119: highlighted = choices.last?.id
                case 36, 49, 76: if let value = highlighted { finish(value) }
                case 53: finish(nil)
                case 48: finish(nil); return event
                default: return event
                }
                return nil
            }
        }
        .onDisappear {
            if let monitor = keyMonitor { NSEvent.removeMonitor(monitor) }
            keyMonitor = nil
        }
    }

    private func move(_ offset: Int) {
        guard !choices.isEmpty else { return }
        let index = choices.firstIndex { $0.id == highlighted } ?? 0
        highlighted = choices[max(0, min(choices.count - 1, index + offset))].id
    }
}
