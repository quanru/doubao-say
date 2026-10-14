import AppKit

/// macOS event tap implements configurable shortcuts, including modifier-only keys.
final class HotkeyManager {
    enum HotkeyEvent { case start, stop, cancel, enter, prime, discard }
    static let syntheticMarker: Int64 = 0x44534253
    var onHotkeyEvent: ((HotkeyEvent) -> Void)?
    private var eventTap: CFMachPort?
    private var source: CFRunLoopSource?
    private var permissionTimer: Timer?
    private var gestureTimer: Timer?
    private var active = false
    private var recording = false
    private var interceptingInput = false
    private var blockedKeys = Set<UInt16>()
    private var blockedModifiers = Set<UInt16>()
    private var withheldTriggerModifiers = Set<UInt16>()
    private var shortcut = Shortcut()
    private var gesture = ShortcutGesture()
    private var shortcutDown = false
    private var capture: ((Shortcut?) -> Void)?
    private var modifierCandidate: Shortcut?
    private var captureExpiry: DispatchWorkItem?
    var available: Bool { eventTap != nil }
    var label: String { shortcut.label }
    static func flags(_ value: Int) -> CGEventFlags {
        var flags = CGEventFlags()
        for (bit, flag) in [(1, CGEventFlags.maskControl), (2, .maskAlternate), (4, .maskCommand), (8, .maskShift), (16, .maskSecondaryFn)] where value & bit != 0 { flags.insert(flag) }
        return flags
    }
    static func modifiers(_ flags: CGEventFlags) -> Int {
        [(1, CGEventFlags.maskControl), (2, .maskAlternate), (4, .maskCommand), (8, .maskShift), (16, .maskSecondaryFn)]
            .reduce(0) { $0 | (flags.contains($1.1) ? $1.0 : 0) }
    }
    private static func canonical(_ code: UInt16) -> UInt16 {
        [UInt16(62): UInt16(59), 61: 58, 54: 55, 60: 56][code] ?? code
    }
    private static func modifierBit(_ code: UInt16) -> Int {
        [UInt16(59): 1, 58: 2, 55: 4, 56: 8, 63: 16][canonical(code)] ?? 0
    }
    private static func modifierPressed(_ code: UInt16, flags: CGEventFlags) -> Bool {
        // IOLLEvent.h device masks distinguish releasing one side while the other is held.
        let masks: [UInt16: (UInt64, UInt64)] = [59: (0x1, 0x2001), 62: (0x2000, 0x2001),
            56: (0x2, 0x6), 60: (0x4, 0x6), 55: (0x8, 0x18), 54: (0x10, 0x18),
            58: (0x20, 0x60), 61: (0x40, 0x60)]
        if let (device, pair) = masks[code], flags.rawValue & pair != 0 { return flags.rawValue & device != 0 }
        return modifiers(flags) & modifierBit(code) != 0
    }
    func configure(_ settings: MacSettings) {
        resetGesture(); shortcut = settings.shortcut
        gesture.holdSeconds = Double(settings.holdMilliseconds) / 1000
        gesture.doubleSeconds = Double(settings.doubleMilliseconds) / 1000
        gesture.doubleEnter = settings.doubleEnter
    }
    func start() {
        guard eventTap == nil else { return }
        // Type 14 carries AppKit system-defined media-key events.
        let mask = (1 << CGEventType.keyDown.rawValue) | (1 << CGEventType.keyUp.rawValue) | (1 << CGEventType.flagsChanged.rawValue) | (1 << 14)
        guard let tap = CGEvent.tapCreate(tap: .cgSessionEventTap, place: .headInsertEventTap,
            options: .defaultTap, eventsOfInterest: CGEventMask(mask), callback: { _, type, event, info in
                guard let info = info else { return Unmanaged.passUnretained(event) }
                return Unmanaged<HotkeyManager>.fromOpaque(info).takeUnretainedValue().handle(type, event)
            }, userInfo: Unmanaged.passUnretained(self).toOpaque()) else { return }
        eventTap = tap; source = CFMachPortCreateRunLoopSource(kCFAllocatorDefault, tap, 0)
        CFRunLoopAddSource(CFRunLoopGetMain(), source, .commonModes); CGEvent.tapEnable(tap: tap, enable: true)
        gestureTimer = Timer(timeInterval: 0.02, repeats: true) { [weak self] _ in
            guard let self = self else { return }
            self.emit(self.gesture.tick(at: ProcessInfo.processInfo.systemUptime))
        }
        RunLoop.main.add(gestureTimer!, forMode: .common)
    }
    func requestPermission() {
        _ = AXIsProcessTrustedWithOptions([kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary)
        start(); permissionTimer?.invalidate()
        permissionTimer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] timer in
            self?.start(); if self?.available == true { timer.invalidate() }
        }
    }
    func stop() {
        permissionTimer?.invalidate(); permissionTimer = nil; gestureTimer?.invalidate(); gestureTimer = nil
        finishCapture(nil)
        if let tap = eventTap { CGEvent.tapEnable(tap: tap, enable: false); CFMachPortInvalidate(tap) }
        if let source = source { CFRunLoopRemoveSource(CFRunLoopGetMain(), source, .commonModes) }
        eventTap = nil; source = nil; resetGesture()
        blockedKeys.removeAll(); blockedModifiers.removeAll(); withheldTriggerModifiers.removeAll(); interceptingInput = false
    }
    func captureShortcut(_ completion: @escaping (Shortcut?) -> Void) {
        guard available, !active else { completion(nil); return }
        finishCapture(nil); resetGesture(); capture = completion; modifierCandidate = nil
        let expiry = DispatchWorkItem { [weak self] in self?.finishCapture(nil) }
        captureExpiry = expiry; DispatchQueue.main.asyncAfter(deadline: .now() + 20, execute: expiry)
    }
    func cancelCapture() { finishCapture(nil) }
    private func finishCapture(_ value: Shortcut?) {
        captureExpiry?.cancel(); captureExpiry = nil; modifierCandidate = nil
        let completion = capture; capture = nil
        if let completion = completion { DispatchQueue.main.async { completion(value) } }
    }
    func setEscapeHandlingEnabled(_ enabled: Bool, recording: Bool = false, interceptKeys: Bool? = nil) {
        active = enabled; self.recording = recording
        interceptingInput = interceptKeys ?? recording
        // Keep swallowed keys until their releases, even after delivery finishes.
    }
    func stopFromAuxiliaryKey() {
        gesture.reset(); shortcutDown = false
        onHotkeyEvent?(.stop)
    }
    func auxiliaryRecord(_ pressed: Bool) {
        let now = ProcessInfo.processInfo.systemUptime
        emit(pressed ? gesture.down(at: now) : gesture.up(at: now))
    }
    private func resetGesture() { gesture.reset(); shortcutDown = false; onHotkeyEvent?(.discard) }
    private func emit(_ actions: [ShortcutGesture.Action]) {
        for action in actions {
            switch action {
            case .prime: onHotkeyEvent?(.prime)
            case .discard: onHotkeyEvent?(.discard)
            case .start: onHotkeyEvent?(.start)
            case .stop: onHotkeyEvent?(.stop)
            case .toggle: onHotkeyEvent?(recording ? .stop : .start)
            case .enter: onHotkeyEvent?(.enter)
            }
        }
    }
    func handle(_ type: CGEventType, _ event: CGEvent) -> Unmanaged<CGEvent>? {
        if event.getIntegerValueField(.eventSourceUserData) == Self.syntheticMarker { return Unmanaged.passUnretained(event) }
        if type == .tapDisabledByTimeout || type == .tapDisabledByUserInput {
            if let tap = eventTap { CGEvent.tapEnable(tap: tap, enable: true) }
            blockedKeys.removeAll(); blockedModifiers.removeAll(); withheldTriggerModifiers.removeAll()
            resetGesture(); return Unmanaged.passUnretained(event)
        }
        let code = Self.canonical(UInt16(event.getIntegerValueField(.keyboardEventKeycode)))
        let mods = Self.modifiers(event.flags)
        let bit = Self.modifierBit(code)
        if capture != nil {
            if type == .keyDown {
                if code == 53 { finishCapture(nil) } else { finishCapture(Shortcut(keyCode: code, modifiers: mods)) }
                return nil
            }
            if type == .flagsChanged, bit != 0 {
                if mods & bit != 0 { modifierCandidate = Shortcut(keyCode: code, modifiers: mods & ~bit) }
                else if let candidate = modifierCandidate { finishCapture(candidate) }
            }
            return Unmanaged.passUnretained(event)
        }
        let physicalCode = UInt16(event.getIntegerValueField(.keyboardEventKeycode))
        let modifierPressed = type == .flagsChanged && Self.modifierPressed(physicalCode, flags: event.flags)
        if type == .flagsChanged && !modifierPressed, withheldTriggerModifiers.remove(physicalCode) != nil {
            if shortcutDown { shortcutDown = false; emit(gesture.up(at: ProcessInfo.processInfo.systemUptime)) }
            return nil
        }
        if type == .keyUp, blockedKeys.remove(physicalCode) != nil { return nil }
        if type == .flagsChanged && !modifierPressed, blockedModifiers.remove(physicalCode) != nil { return nil }
        let draining = !blockedKeys.isEmpty || !blockedModifiers.isEmpty
        if type.rawValue == 14, let media = NSEvent(cgEvent: event), media.subtype.rawValue == 8 {
            let mediaCode = UInt16(0x8000 | ((media.data1 >> 16) & 0x7fff))
            let keyState = (media.data1 >> 8) & 0xff
            if keyState == 0x0b, blockedKeys.remove(mediaCode) != nil { return nil }
            if keyState == 0x0a && (interceptingInput || draining) {
                let firstPress = blockedKeys.insert(mediaCode).inserted
                if interceptingInput && firstPress && !draining { stopFromAuxiliaryKey() }
                return nil
            }
            return Unmanaged.passUnretained(event)
        }
        if (type == .keyDown || modifierPressed || (type == .flagsChanged && code == 57)) && (interceptingInput || draining) {
            let firstPress: Bool
            if modifierPressed { firstPress = blockedModifiers.insert(physicalCode).inserted }
            else if type == .keyDown { firstPress = blockedKeys.insert(physicalCode).inserted }
            else { firstPress = true }
            if interceptingInput && firstPress && !draining { stopFromAuxiliaryKey() }
            return nil
        }
        if code == 53 && type == .keyDown && (active || shortcutDown || gesture.isPending) { resetGesture(); onHotkeyEvent?(.cancel); return nil }
        let now = ProcessInfo.processInfo.systemUptime
        let modifierShortcut = Self.modifierBit(shortcut.keyCode)
        let down = modifierShortcut != 0 ? (type == .flagsChanged && code == shortcut.keyCode && mods & modifierShortcut != 0) : type == .keyDown
        if down && code == shortcut.keyCode && (mods & ~modifierShortcut) == shortcut.modifiers {
            if modifierShortcut != 0 { withheldTriggerModifiers.insert(physicalCode) }
            shortcutDown = true; emit(gesture.down(at: now)); return nil
        }
        if shortcutDown && ((type == .keyUp && code == shortcut.keyCode) || (type == .flagsChanged && (mods & shortcut.modifiers != shortcut.modifiers || (modifierShortcut != 0 && mods & modifierShortcut == 0)))) {
            shortcutDown = false; emit(gesture.up(at: now)); return type == .keyUp ? nil : Unmanaged.passUnretained(event)
        }
        return Unmanaged.passUnretained(event)
    }
}
