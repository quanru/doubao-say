"""Loopback WebSocket fixture; no microphone, credentials or external network."""
import base64
import hashlib
import json
import socket
import struct
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
            request = b''
            while b'\r\n\r\n' not in request:
                chunk = conn.recv(4096)
                if not chunk:
                    raise RuntimeError('EOF during handshake')
                request += chunk
            headers = {key.lower(): value for key, value in (line.split(': ', 1) for line in request.decode().split('\r\n')[1:] if ': ' in line)}
            key = headers['sec-websocket-key']
            accept = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest())
            conn.sendall(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: ' + accept + b'\r\n\r\n')
            audio = []

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

            while len(audio) < 2:
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
                opcode = first & 15
                if opcode == 9:
                    send(10, data)
                elif opcode == 2:
                    audio.append(data)
            assert audio == [bytes([1, 2, 3, 4]), bytes(6400)], [len(x) for x in audio]
            send(1, json.dumps({'event': 'result', 'result': {'Text': 'synthetic result'}}).encode())
            send(1, b'{"event":"finish"}')
    except Exception as error:
        errors.append(str(error))
    finally:
        listener.close()


thread = threading.Thread(target=serve, daemon=True)
thread.start()
result = subprocess.run([sys.argv[1], f'ws://127.0.0.1:{port}/asr'], timeout=12)
thread.join(timeout=10)
if errors or thread.is_alive():
    raise SystemExit(f'FAIL: {errors or "fixture did not exit"}')
if result.returncode:
    raise SystemExit(result.returncode)

for status in (401, 403, 500):
    class Rejection(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            self.send_response(status)
            self.send_header('Content-Length', '0')
            self.end_headers()

    server = ThreadingHTTPServer(('127.0.0.1', 0), Rejection)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        subprocess.run([sys.argv[1], f'ws://127.0.0.1:{server.server_port}/asr',
                        'auth' if status in (401, 403) else 'generic'], timeout=12, check=True)
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=2)
