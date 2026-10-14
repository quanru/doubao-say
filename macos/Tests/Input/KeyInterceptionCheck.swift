import AppKit

@main struct KeyInterceptionCheck {
    static func key(_ code: UInt16, _ down: Bool, flags: CGEventFlags = []) -> CGEvent {
        let event = CGEvent(keyboardEventSource: nil, virtualKey: code, keyDown: down)!
        event.flags = flags
        return event
    }
    static func main() {
        for shortcut in [Shortcut(keyCode: 49, modifiers: 3), Shortcut(keyCode: 63, modifiers: 0)] {
            for code: UInt16 in [0, 36, 53, 49, 48, 51, 123, 122] {
                let manager = HotkeyManager()
                var settings = MacSettings(); settings.shortcut = shortcut
                manager.configure(settings)
                var stops = 0, other = 0
                manager.onHotkeyEvent = { if case .stop = $0 { stops += 1 } else { other += 1 } }
                manager.setEscapeHandlingEnabled(true, recording: true)
                precondition(manager.handle(.keyDown, key(code, true)) == nil)
                precondition(manager.handle(.keyDown, key(code, true)) == nil, "Held-key repeat must be swallowed")
                precondition(stops == 1 && other == 0, "Every recording key must stop, never cancel or send Enter")
                manager.setEscapeHandlingEnabled(false)
                precondition(manager.handle(.keyUp, key(code, false)) == nil, "Release must remain swallowed after delivery")
                precondition(manager.handle(.keyDown, key(0, true)) != nil, "Ordinary typing must resume when idle")
            }
        }
        let trigger = HotkeyManager()
        var triggerSettings = MacSettings(); triggerSettings.shortcut = Shortcut(keyCode: 63, modifiers: 0)
        triggerSettings.doubleEnter = false; trigger.configure(triggerSettings)
        var triggerStops = 0
        trigger.onHotkeyEvent = { if case .stop = $0 { triggerStops += 1 } }
        precondition(trigger.handle(.flagsChanged, key(63, true, flags: .maskSecondaryFn)) == nil,
                     "The voice trigger must not reach the system's original Fn action")
        trigger.setEscapeHandlingEnabled(true, recording: true)
        precondition(trigger.handle(.keyDown, key(0, true, flags: .maskSecondaryFn)) == nil && triggerStops == 1)
        trigger.setEscapeHandlingEnabled(false)
        precondition(trigger.handle(.flagsChanged, key(63, false)) == nil && triggerStops == 1,
                     "Releasing the original trigger after finishing must not perform its system action or restart recording")
        precondition(trigger.handle(.keyUp, key(0, false)) == nil)
        let manager = HotkeyManager()
        var stops = 0
        manager.onHotkeyEvent = { if case .stop = $0 { stops += 1 } else { preconditionFailure("Unexpected gesture") } }
        for modifier: UInt16 in [55, 59, 58, 56, 63] {
            let flags = HotkeyManager.flags([UInt16(55): 4, 59: 1, 58: 2, 56: 8, 63: 16][modifier]!)
            manager.setEscapeHandlingEnabled(true, recording: true)
            let before = stops
            precondition(manager.handle(.flagsChanged, key(modifier, true, flags: flags)) == nil)
            precondition(manager.handle(.keyDown, key(8, true, flags: flags)) == nil)
            precondition(stops == before + 1, "A shortcut chord must produce one stop")
            manager.setEscapeHandlingEnabled(false)
            precondition(manager.handle(.flagsChanged, key(modifier, false)) == nil)
            precondition(manager.handle(.keyUp, key(8, false)) == nil)
            precondition(manager.handle(.keyDown, key(0, true)) != nil)
        }
        manager.setEscapeHandlingEnabled(false)
        precondition(manager.handle(.flagsChanged, key(59, true, flags: CGEventFlags(rawValue: CGEventFlags.maskControl.rawValue | 0x1))) != nil)
        manager.setEscapeHandlingEnabled(true, recording: true)
        precondition(manager.handle(.flagsChanged, key(62, true, flags: CGEventFlags(rawValue: CGEventFlags.maskControl.rawValue | 0x2001))) == nil)
        manager.setEscapeHandlingEnabled(false)
        precondition(manager.handle(.flagsChanged, key(59, false, flags: CGEventFlags(rawValue: CGEventFlags.maskControl.rawValue | 0x2000))) != nil,
                     "The original trigger modifier release must not become a new blocked press")
        precondition(manager.handle(.flagsChanged, key(62, false)) == nil)
        precondition(manager.handle(.keyDown, key(0, true)) != nil, "Both modifier sides must drain without leaving keyboard interception stuck")
        manager.setEscapeHandlingEnabled(true, interceptKeys: true)
        precondition(manager.handle(.keyDown, key(53, true)) == nil, "Finishing input must not cancel on Escape")
        manager.setEscapeHandlingEnabled(false)
        precondition(manager.handle(.keyUp, key(53, false)) == nil)
        manager.setEscapeHandlingEnabled(true, recording: true)
        let synthetic = key(9, true, flags: .maskCommand)
        synthetic.setIntegerValueField(.eventSourceUserData, value: HotkeyManager.syntheticMarker)
        let before = stops
        precondition(manager.handle(.keyDown, synthetic) != nil && stops == before, "Our output must bypass interception")
        manager.setEscapeHandlingEnabled(false)
        manager.setEscapeHandlingEnabled(true)
        var cancelled = false
        manager.onHotkeyEvent = { if case .cancel = $0 { cancelled = true } }
        precondition(manager.handle(.keyDown, key(53, true)) == nil && cancelled, "Escape still dismisses kept text outside input")
        manager.onHotkeyEvent = { if case .stop = $0 { stops += 1 } else { preconditionFailure("Unexpected media gesture") } }
        manager.setEscapeHandlingEnabled(true, recording: true)
        let mediaDown = NSEvent.otherEvent(with: .systemDefined, location: .zero, modifierFlags: [], timestamp: 0,
                                          windowNumber: 0, context: nil, subtype: 8, data1: 0x0a00, data2: 0)!.cgEvent!
        let mediaUp = NSEvent.otherEvent(with: .systemDefined, location: .zero, modifierFlags: [], timestamp: 0,
                                        windowNumber: 0, context: nil, subtype: 8, data1: 0x0b00, data2: 0)!.cgEvent!
        let mediaBefore = stops
        precondition(manager.handle(mediaDown.type, mediaDown) == nil && stops == mediaBefore + 1)
        manager.setEscapeHandlingEnabled(false)
        precondition(manager.handle(mediaUp.type, mediaUp) == nil)
        precondition(manager.handle(mediaDown.type, mediaDown) != nil, "Media keys must resume when idle")
        print("PASS: recording keys, Escape/Enter, modifiers, shortcut chords, media keys, repeats, post-delivery releases and synthetic-output bypass; no event tap or real key posting")
    }
}
