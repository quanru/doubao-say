"""Seed ASR binary framing used by Volcengine's official WebSocket API."""

from __future__ import annotations

from dataclasses import dataclass
import gzip
import json
import struct


CLIENT_FULL_REQUEST = 0x1
CLIENT_AUDIO_REQUEST = 0x2
SERVER_FULL_RESPONSE = 0x9
SERVER_ERROR_RESPONSE = 0xF

POSITIVE_SEQUENCE = 0x1
NEGATIVE_SEQUENCE = 0x3
JSON_SERIALIZATION = 0x1
GZIP_COMPRESSION = 0x1


class ProtocolError(ValueError):
    pass


@dataclass(frozen=True)
class SeedResponse:
    code: int = 0
    sequence: int = 0
    is_last: bool = False
    message: dict | None = None


def _header(message_type: int, flags: int, serialization: int, compression: int) -> bytes:
    return bytes((0x11, (message_type << 4) | flags,
                  (serialization << 4) | compression, 0x00))


def full_request(sequence: int = 1) -> bytes:
    payload = {
        "user": {"uid": "doubao-say"},
        "audio": {
            "format": "pcm", "codec": "raw", "rate": 16000,
            "bits": 16, "channel": 1,
        },
        "request": {
            "model_name": "bigmodel", "enable_itn": True,
            "enable_punc": True, "enable_ddc": False,
            "enable_nonstream": True,
            "show_utterances": False,
        },
    }
    compressed = gzip.compress(json.dumps(payload, separators=(",", ":")).encode())
    return (_header(CLIENT_FULL_REQUEST, POSITIVE_SEQUENCE,
                    JSON_SERIALIZATION, GZIP_COMPRESSION)
            + struct.pack(">iI", sequence, len(compressed)) + compressed)


def audio_request(sequence: int, audio: bytes, *, last: bool = False) -> bytes:
    if sequence <= 0:
        raise ValueError("Sequence must be positive")
    compressed = gzip.compress(bytes(audio))
    wire_sequence = -sequence if last else sequence
    flags = NEGATIVE_SEQUENCE if last else POSITIVE_SEQUENCE
    return (_header(CLIENT_AUDIO_REQUEST, flags, 0, GZIP_COMPRESSION)
            + struct.pack(">iI", wire_sequence, len(compressed)) + compressed)


def parse_response(data: bytes) -> SeedResponse:
    if not isinstance(data, bytes) or len(data) < 4:
        raise ProtocolError("Seed response header is incomplete")
    header_words = data[0] & 0x0F
    if data[0] >> 4 != 1 or header_words < 1:
        raise ProtocolError("Unsupported Seed protocol header")
    offset = header_words * 4
    if len(data) < offset:
        raise ProtocolError("Seed response header is truncated")
    message_type = data[1] >> 4
    flags = data[1] & 0x0F
    serialization = data[2] >> 4
    compression = data[2] & 0x0F
    sequence = 0
    if flags & 0x1:
        if len(data) < offset + 4:
            raise ProtocolError("Seed response sequence is truncated")
        sequence = struct.unpack(">i", data[offset:offset + 4])[0]
        offset += 4
    if flags & 0x4:
        if len(data) < offset + 4:
            raise ProtocolError("Seed response event is truncated")
        offset += 4
    code = 0
    if message_type == SERVER_FULL_RESPONSE:
        if len(data) < offset + 4:
            raise ProtocolError("Seed response size is truncated")
        size = struct.unpack(">I", data[offset:offset + 4])[0]
        offset += 4
    elif message_type == SERVER_ERROR_RESPONSE:
        if len(data) < offset + 8:
            raise ProtocolError("Seed error response is truncated")
        code, size = struct.unpack(">iI", data[offset:offset + 8])
        offset += 8
    else:
        raise ProtocolError("Unsupported Seed response type")
    if size > 2**20 or len(data) - offset != size:
        raise ProtocolError("Seed response payload size is invalid")
    payload = data[offset:]
    if compression == GZIP_COMPRESSION and payload:
        try:
            payload = gzip.decompress(payload)
        except (OSError, EOFError) as error:
            raise ProtocolError("Seed response compression is invalid") from error
    message = None
    if payload:
        if serialization != JSON_SERIALIZATION:
            raise ProtocolError("Unsupported Seed response serialization")
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeError, ValueError) as error:
            raise ProtocolError("Seed response JSON is invalid") from error
        if not isinstance(decoded, dict):
            raise ProtocolError("Seed response JSON must be an object")
        message = decoded
    return SeedResponse(code=code, sequence=sequence,
                        is_last=bool(flags & 0x2), message=message)


def result_text(message: dict | None) -> str:
    if not isinstance(message, dict):
        return ""
    result = message.get("result")
    if isinstance(result, dict) and isinstance(result.get("text"), str):
        return result["text"].strip()
    # Some compatible/legacy responses wrap result objects in a list.
    if isinstance(result, list):
        for item in reversed(result):
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                return item["text"].strip()
    return ""
