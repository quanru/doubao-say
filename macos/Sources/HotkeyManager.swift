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
    func configure(_ settings: MacSettings) {
        resetGesture(); shortcut = settings.shortcut
        gesture.holdSeconds = Double(settings.holdMilliseconds) / 1000
        gesture.doubleSeconds = Double(settings.doubleMilliseconds) / 1000
        gesture.doubleEnter = settings.doubleEnter
    }
    func start() {
        guard eventTap == nil else { return }
        let mask = (1 << CGEventType.keyDown.rawValue) | (1 << CGEventType.keyUp.rawValue) | (1 << CGEventType.flagsChanged.rawValue)
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
    func setEscapeHandlingEnabled(_ enabled: Bool, recording: Bool = false) { active = enabled; self.recording = recording }
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
        if code == 53 && type == .keyDown && (active || shortcutDown || gesture.isPending) { resetGesture(); onHotkeyEvent?(.cancel); return nil }
        if shortcut.keyCode == 63 && recording && type == .keyDown && code != 63 { onHotkeyEvent?(.stop); return Unmanaged.passUnretained(event) }
        let now = ProcessInfo.processInfo.systemUptime
        let modifierShortcut = Self.modifierBit(shortcut.keyCode)
        let down = modifierShortcut != 0 ? (type == .flagsChanged && code == shortcut.keyCode && mods & modifierShortcut != 0) : type == .keyDown
        if down && code == shortcut.keyCode && (mods & ~modifierShortcut) == shortcut.modifiers {
            shortcutDown = true; emit(gesture.down(at: now)); return modifierShortcut == 0 ? nil : Unmanaged.passUnretained(event)
        }
        if shortcutDown && ((type == .keyUp && code == shortcut.keyCode) || (type == .flagsChanged && (mods & shortcut.modifiers != shortcut.modifiers || (modifierShortcut != 0 && mods & modifierShortcut == 0)))) {
            shortcutDown = false; emit(gesture.up(at: now)); return type == .keyUp ? nil : Unmanaged.passUnretained(event)
        }
        return Unmanaged.passUnretained(event)
    }
}
