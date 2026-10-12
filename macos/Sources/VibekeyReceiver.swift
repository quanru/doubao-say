import Foundation
import IOKit.hid

/// Opens only the matching vendor interface; ordinary keyboards remain owned by macOS.
final class VibekeyReceiver {
    var onAction: ((String, Bool) -> Void)?
    var onStatus: ((Bool) -> Void)?
    private var manager: IOHIDManager?
    private var device: IOHIDDevice?
    private let report = UnsafeMutablePointer<UInt8>.allocate(capacity: 64)
    private var heartbeat: Timer?
    private var code: UInt32 = 0
    private var authenticated = false
    private var pressed = Set<String>()
    deinit { report.deallocate() }
    func start() {
        guard manager == nil else { return }
        let manager = IOHIDManagerCreate(kCFAllocatorDefault, IOOptionBits(kIOHIDOptionsTypeNone))
        self.manager = manager
        IOHIDManagerSetDeviceMatching(manager, [kIOHIDVendorIDKey: 0xFFF1, kIOHIDProductIDKey: 0x00DD] as CFDictionary)
        let context = Unmanaged.passUnretained(self).toOpaque()
        IOHIDManagerRegisterDeviceMatchingCallback(manager, { context, _, _, device in
            guard let context = context else { return }
            Unmanaged<VibekeyReceiver>.fromOpaque(context).takeUnretainedValue().attach(device)
        }, context)
        IOHIDManagerRegisterDeviceRemovalCallback(manager, { context, _, _, device in
            guard let context = context else { return }
            let receiver = Unmanaged<VibekeyReceiver>.fromOpaque(context).takeUnretainedValue()
            if receiver.device == device { receiver.detach() }
        }, context)
        IOHIDManagerScheduleWithRunLoop(manager, CFRunLoopGetMain(), CFRunLoopMode.commonModes.rawValue)
        if IOHIDManagerOpen(manager, IOOptionBits(kIOHIDOptionsTypeNone)) != kIOReturnSuccess { onStatus?(false) }
        heartbeat = Timer(timeInterval: 0.8, repeats: true) { [weak self] _ in
            guard let self = self else { return }
            if self.device != nil { self.ping() }
            else if let manager = self.manager, let devices = IOHIDManagerCopyDevices(manager) as? Set<IOHIDDevice> {
                for device in devices { self.attach(device) }
            }
        }
        RunLoop.main.add(heartbeat!, forMode: .common)
    }
    private func attach(_ candidate: IOHIDDevice) {
        guard device == nil, let descriptor = IOHIDDeviceGetProperty(candidate, kIOHIDReportDescriptorKey as CFString) as? Data,
              descriptor.starts(with: [0x06, 0xFC, 0xFF, 0x09, 0x01, 0xA1, 0x01, 0x09, 0x02, 0x85, 0x55]),
              IOHIDDeviceOpen(candidate, IOOptionBits(kIOHIDOptionsTypeNone)) == kIOReturnSuccess else { return }
        device = candidate; code = UInt32.random(in: .min ... .max); authenticated = false
        IOHIDDeviceRegisterInputReportCallback(candidate, report, 64, { context, result, _, _, reportID, bytes, length in
            guard let context = context, result == kIOReturnSuccess, length > 0, length <= 64 else { return }
            let receiver = Unmanaged<VibekeyReceiver>.fromOpaque(context).takeUnretainedValue()
            var data = Data(bytes: bytes, count: length)
            if reportID == 0x55 && data.first != 0x55 { data.insert(0x55, at: 0) }
            receiver.receive(data)
        }, Unmanaged.passUnretained(self).toOpaque())
        IOHIDDeviceScheduleWithRunLoop(candidate, CFRunLoopGetMain(), CFRunLoopMode.commonModes.rawValue)
        ping()
    }
    private func write(_ data: Data) {
        guard let device = device else { return }
        let result = data.withUnsafeBytes { raw in
            IOHIDDeviceSetReport(device, kIOHIDReportTypeOutput, 0x55, raw.bindMemory(to: UInt8.self).baseAddress!, data.count)
        }
        if result != kIOReturnSuccess { detach() }
    }
    private func ping() {
        if !authenticated { write(VibekeyProtocol.auth(code)) }
        write(VibekeyProtocol.encode([6, 1, 0x23, 0, 1]))
    }
    private func receive(_ data: Data) {
        let decoded = VibekeyProtocol.decode(data)
        if VibekeyProtocol.authenticated(decoded, code: code) { authenticated = true; onStatus?(true); return }
        guard authenticated, let (name, down) = VibekeyProtocol.action(decoded) else { return }
        if name == "clockwise" || name == "counterclockwise" { onAction?(name, true); return }
        if down { if !pressed.insert(name).inserted { return } }
        else { if pressed.remove(name) == nil { return } }
        onAction?(name, down)
    }
    private func detach() {
        if let device = device {
            IOHIDDeviceRegisterInputReportCallback(device, report, 64, nil, nil)
            IOHIDDeviceUnscheduleFromRunLoop(device, CFRunLoopGetMain(), CFRunLoopMode.commonModes.rawValue)
            IOHIDDeviceClose(device, IOOptionBits(kIOHIDOptionsTypeNone))
        }
        device = nil; authenticated = false
        for name in pressed { onAction?(name, false) }; pressed.removeAll(); onStatus?(false)
    }
    func stop() {
        heartbeat?.invalidate(); heartbeat = nil
        detach()
        if let manager = manager {
            IOHIDManagerRegisterDeviceMatchingCallback(manager, nil, nil)
            IOHIDManagerRegisterDeviceRemovalCallback(manager, nil, nil)
            IOHIDManagerUnscheduleFromRunLoop(manager, CFRunLoopGetMain(), CFRunLoopMode.commonModes.rawValue)
            IOHIDManagerClose(manager, IOOptionBits(kIOHIDOptionsTypeNone))
        }
        manager = nil
    }
}
