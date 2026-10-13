"""Official-provider wire acceptance against a loopback fixture, never vendor services."""
import base64
import gzip
import hashlib
import json
import socket
import struct
import subprocess
import sys
import threading


def check(provider, raw=False):
    errors = []
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(1)
    listener.settimeout(10)
    port = listener.getsockname()[1]

    def serve():
        try:
            with listener.accept()[0] as conn:
                conn.settimeout(8)

                def read(n):
                    data = b''
                    while len(data) < n:
                        chunk = conn.recv(n - len(data))
                        if not chunk:
                            raise RuntimeError('unexpected EOF')
                        data += chunk
                    return data

                def send(opcode, data):
                    header = bytes([0x80 | opcode, len(data)]) if len(data) < 126 else bytes([0x80 | opcode, 126]) + struct.pack('!H', len(data))
                    conn.sendall(header + data)

                def receive():
                    first, second = read(2)
                    size = second & 127
                    if size == 126:
                        size = struct.unpack('!H', read(2))[0]
                    elif size == 127:
                        size = struct.unpack('!Q', read(8))[0]
                    mask = read(4) if second & 128 else b''
                    data = read(size)
                    if mask:
                        data = bytes(x ^ mask[i % 4] for i, x in enumerate(data))
                    if first & 15 == 9:
                        send(10, data)
                        return receive()
                    return first & 15, data

                request = b''
                while b'\r\n\r\n' not in request:
                    request += read(1)
                headers = {key.lower(): value for key, value in (line.split(': ', 1) for line in request.decode().split('\r\n')[1:] if ': ' in line)}
                if provider == 'volcengine':
                    assert headers['x-api-key'] == 'fake-asr-key'
                    assert headers['x-api-resource-id'] == 'volc.seedasr.sauc.duration'
                else:
                    assert headers['authorization'] == 'Token fake-asr-key'
                accept = base64.b64encode(hashlib.sha1((headers['sec-websocket-key'] + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest())
                conn.sendall(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ' + accept + b'\r\n\r\n')
                if provider == 'volcengine':
                    opcode, data = receive()
                    assert opcode == 2 and data[:4] == bytes([0x11, 0x11, 0x11, 0])
                    body = json.loads(gzip.decompress(data[12:]))
                    assert body['audio']['rate'] == 16000 and body['request']['enable_punc'] is True
                    if raw:
                        assert 'corpus' not in body['request']
                    else:
                        assert json.loads(body['request']['corpus']['context']) == {'hotwords': [{'word': 'Midscene'}, {'word': 'Vibelet'}]}
                    payload = gzip.compress(b'{}')
                    send(2, bytes([0x11, 0x91, 0x11, 0]) + struct.pack('!iI', 1, len(payload)) + payload)
                    opcode, data = receive()
                    assert opcode == 2 and data[:4] == bytes([0x11, 0x23, 1, 0])
                    assert struct.unpack('!i', data[4:8])[0] == -2
                    assert gzip.decompress(data[12:]) == bytes([1, 2, 3, 4])
                    payload = gzip.compress(b'{"result":{"text":"synthetic result"}}')
                    send(2, bytes([0x11, 0x93, 0x11, 0]) + struct.pack('!iI', -2, len(payload)) + payload)
                else:
                    opcode, data = receive()
                    assert opcode == 2 and data == bytes([1, 2, 3, 4])
                    opcode, data = receive()
                    assert opcode == 1 and json.loads(data)['type'] == 'Finalize'
                    for transcript, final, finalize in [('Wrong', False, False), ('First', True, False), ('second', False, False), ('second', True, True)]:
                        send(1, json.dumps({'type': 'Results', 'is_final': final, 'from_finalize': finalize, 'channel': {'alternatives': [{'transcript': transcript}]}}).encode())
        except Exception as error:
            errors.append(type(error).__name__)
        finally:
            listener.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    result = subprocess.run([sys.argv[1], f'ws://127.0.0.1:{port}/asr', provider] + (['raw'] if raw else []), timeout=12)
    thread.join(timeout=10)
    if errors or thread.is_alive():
        raise SystemExit('FAIL: ' + repr(errors or ['fixture did not exit']))
    if result.returncode:
        raise SystemExit(result.returncode)


for provider in ['volcengine', 'deepgram']:
    check(provider)

check('volcengine', raw=True)
