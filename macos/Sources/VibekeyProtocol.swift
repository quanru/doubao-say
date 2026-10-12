import Foundation

/// AU05 wire format ported from trigger/au05.py. These are vendor protocol constants.
enum VibekeyProtocol {
    static let key: [UInt32] = [0xCAA5BACA, 0xBC2A8A6D, 0xCA5A9EBA, 0x9BB88BCA]
    static let authXor: [UInt32] = [0x20141107, 0xC138BF6D, 0xA8AB23C7, 0x73165329, 0x30629139, 0xD9F4E04C, 0xEC8C35BF, 0x64101856, 0x47201988, 0x98211053, 0xF0D4ECA9, 0x82991136, 0x09153583, 0x16141925, 0xBF8A7CED, 0x54557049]
    static func word(_ bytes: [UInt8], _ offset: Int) -> UInt32 {
        (0..<4).reduce(0) { $0 | UInt32(bytes[offset + $1]) << ($1 * 8) }
    }
    static func bytes(_ value: UInt32) -> [UInt8] { (0..<4).map { UInt8(truncatingIfNeeded: value >> ($0 * 8)) } }
    static func block(_ bytes: [UInt8], decode: Bool) -> [UInt8] {
        var v0 = word(bytes, 0), v1 = word(bytes, 4), sum: UInt32 = decode ? 0xC6EF3720 : 0
        let delta: UInt32 = 0x9E3779B9
        for _ in 0..<32 {
            if decode {
                v1 = v1 &- (((v0 << 4) &+ key[2]) ^ (v0 &+ sum) ^ ((v0 >> 5) &+ key[3]))
                v0 = v0 &- (((v1 << 4) &+ key[0]) ^ (v1 &+ sum) ^ ((v1 >> 5) &+ key[1]))
                sum = sum &- delta
            } else {
                sum = sum &+ delta
                v0 = v0 &+ (((v1 << 4) &+ key[0]) ^ (v1 &+ sum) ^ ((v1 >> 5) &+ key[1]))
                v1 = v1 &+ (((v0 << 4) &+ key[2]) ^ (v0 &+ sum) ^ ((v0 >> 5) &+ key[3]))
            }
        }
        return self.bytes(v0) + self.bytes(v1)
    }
    static func encode(_ value: [UInt8]) -> Data {
        let padded = Array(value.prefix(64)) + [UInt8](repeating: 0, count: max(0, 64 - value.count))
        let encoded = stride(from: 0, to: 64, by: 8).flatMap { block(Array(padded[$0..<$0 + 8]), decode: false) }
        return Data([0x55] + Array(encoded.prefix(63)))
    }
    static func decode(_ report: Data) -> [UInt8] {
        var bytes = [UInt8](report)
        if bytes.first == 0x55 { bytes.removeFirst() }
        let complete = bytes.count / 8 * 8
        return stride(from: 0, to: complete, by: 8).flatMap { block(Array(bytes[$0..<$0 + 8]), decode: true) } + Array(bytes[complete...])
    }
    static func auth(_ code: UInt32) -> Data { encode([0x06, 0x02, 0x05, 0x01, UInt8(code & 15)] + bytes(code)) }
    static func authenticated(_ bytes: [UInt8], code: UInt32) -> Bool {
        guard bytes.count >= 9, Array(bytes.prefix(4)) == [6, 2, 5, 17], Int(bytes[4]) < authXor.count else { return false }
        return word(bytes, 5) ^ authXor[Int(bytes[4])] == code
    }
    static func action(_ bytes: [UInt8]) -> (String, Bool)? {
        guard bytes.count >= 5 else { return nil }
        if bytes[0] & 31 == 11 && bytes[1] == 16 {
            let code = bytes[2], status = bytes[3]
            guard status <= 1 else { return nil }
            if code == 0x72 || code == 0x73 { return status == 1 ? (code == 0x72 ? "clockwise" : "counterclockwise", true) : nil }
            if let name = [UInt8(0x6E): "press", 0x6F: "record", 0x70: "enter", 0x71: "cancel"][code] { return (name, status == 1) }
        } else if bytes[1] == 0x12, bytes[3] <= 1, let name = [UInt8(0): "record", 1: "enter", 2: "cancel"][bytes[4]] { return (name, bytes[3] == 1) }
        return nil
    }
}
