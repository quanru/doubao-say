import Foundation
import zlib

enum SeedProtocol {
    struct Response {
        var code: Int = 0
        var sequence: Int32 = 0
        var last = false
        var text = ""
    }
    enum Failure: Error { case invalid }
    static func gzip(_ data: Data, decompress: Bool = false) throws -> Data {
        var stream = z_stream()
        let status = decompress
            ? inflateInit2_(&stream, 31, ZLIB_VERSION, Int32(MemoryLayout<z_stream>.size))
            : deflateInit2_(&stream, Z_DEFAULT_COMPRESSION, Z_DEFLATED, 31, 8, Z_DEFAULT_STRATEGY, ZLIB_VERSION, Int32(MemoryLayout<z_stream>.size))
        guard status == Z_OK else { throw Failure.invalid }
        defer { if decompress { inflateEnd(&stream) } else { deflateEnd(&stream) } }
        return try data.withUnsafeBytes { input in
            stream.next_in = UnsafeMutablePointer(mutating: input.bindMemory(to: Bytef.self).baseAddress)
            stream.avail_in = uInt(data.count)
            var result = Data()
            var code: Int32 = Z_OK
            repeat {
                var buffer = [UInt8](repeating: 0, count: 16_384)
                let written = buffer.withUnsafeMutableBytes { output -> Int in
                    stream.next_out = output.bindMemory(to: Bytef.self).baseAddress
                    stream.avail_out = uInt(output.count)
                    code = decompress ? inflate(&stream, Z_NO_FLUSH) : deflate(&stream, Z_FINISH)
                    return output.count - Int(stream.avail_out)
                }
                guard code == Z_OK || code == Z_STREAM_END, result.count + written <= 1_048_576 else { throw Failure.invalid }
                result.append(contentsOf: buffer.prefix(written))
            } while code != Z_STREAM_END
            guard stream.avail_in == 0 else { throw Failure.invalid }
            return result
        }
    }
    static func integer(_ value: Int32) -> Data {
        var big = value.bigEndian
        return withUnsafeBytes(of: &big) { Data($0) }
    }
    static func frame(type: UInt8, sequence: Int32, json: Bool, payload: Data, last: Bool = false) throws -> Data {
        let bytes = try gzip(payload)
        return Data([0x11, (type << 4) | (last ? 3 : 1), (json ? 0x10 : 0) | 1, 0])
            + integer(last ? -sequence : sequence) + integer(Int32(bytes.count)) + bytes
    }
    static func initial(hotwords: [String] = []) throws -> Data {
        var request: [String: Any] = ["model_name": "bigmodel", "enable_itn": true, "enable_punc": true, "enable_ddc": false, "show_utterances": false]
        if let context = try PersonalCorrections.hotwordContext(hotwords) { request["corpus"] = ["context": context] }
        let body: [String: Any] = ["user": ["uid": "doubao-say"],
            "audio": ["format": "pcm", "codec": "raw", "rate": 16000, "bits": 16, "channel": 1],
            "request": request]
        return try frame(type: 1, sequence: 1, json: true, payload: JSONSerialization.data(withJSONObject: body))
    }
    static func parse(_ data: Data) throws -> Response {
        let bytes = [UInt8](data)
        guard bytes.count >= 4, bytes[0] >> 4 == 1, bytes[0] & 15 >= 1 else { throw Failure.invalid }
        var offset = Int(bytes[0] & 15) * 4
        guard bytes.count >= offset, [0, 1].contains(bytes[2] & 15) else { throw Failure.invalid }
        func number() throws -> Int32 {
            guard offset + 4 <= bytes.count else { throw Failure.invalid }
            let value = bytes[offset..<offset + 4].reduce(UInt32(0)) { ($0 << 8) | UInt32($1) }
            offset += 4
            return Int32(bitPattern: value)
        }
        var response = Response(last: bytes[1] & 2 != 0)
        if bytes[1] & 1 != 0 { response.sequence = try number() }
        if bytes[1] & 4 != 0 { _ = try number() }
        let type = bytes[1] >> 4
        guard type == 9 || type == 15 else { throw Failure.invalid }
        if type == 15 { response.code = Int(try number()) }
        let size = Int(try number())
        guard size >= 0, size <= 1_048_576, bytes.count - offset == size else { throw Failure.invalid }
        var payload = Data(bytes[offset...])
        if !payload.isEmpty && bytes[2] & 15 == 1 { payload = try gzip(payload, decompress: true) }
        if !payload.isEmpty {
            guard bytes[2] >> 4 == 1, let json = try JSONSerialization.jsonObject(with: payload) as? [String: Any] else { throw Failure.invalid }
            if let result = json["result"] as? [String: Any] { response.text = result["text"] as? String ?? "" }
            else if let results = json["result"] as? [[String: Any]] { response.text = results.reversed().compactMap { $0["text"] as? String }.first ?? "" }
        }
        return response
    }
}
