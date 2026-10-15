"""Bounded loopback HTTP tests. Fake keys and synthetic text only."""
import http.server
import json
import subprocess
import sys
import threading
import time

errors = []
requests = []


class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *_args):
        pass

    def do_POST(self):
        try:
            raw = self.rfile.read(int(self.headers.get('Content-Length', '0')))
            body = json.loads(raw)
            assert self.path == '/v1/chat/completions'
            assert self.headers.get('Authorization') == 'Bearer fake-polish-key'
            assert body['stream'] is True and body['model'] == 'synthetic-model'
            assert body['messages'][0]['role'] == 'system'
            sample = body['messages'][1]['content']
            prompt = body['messages'][0]['content']
            if sample == 'counts-only':
                assert 'User-confirmed' not in prompt and 'Personal vocabulary' not in prompt
                assert '用Midscene写测试' not in prompt
            else:
                assert "Midscene" in prompt
                if sample == '用Midjourney写测试':
                    assert 'User-confirmed' in prompt and '用Midscene写测试' in prompt
                else:
                    assert 'User-confirmed' not in prompt
            requests.append(sample)
            if sample == 'overlap':
                time.sleep(0.3)
            if sample == 'slow':
                time.sleep(6)
            if sample == 'error':
                self.send_response(401)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            if sample == 'redirect':
                self.send_response(307)
                self.send_header('Location', '/unexpected-redirect')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            lines = ['data: ' + json.dumps({'choices': [{'delta': {'content': '周四上线。'}}]}, ensure_ascii=False) + '\n\n']
            if sample != 'incomplete':
                lines += ['data: ' + json.dumps({'choices': [{'delta': {}, 'finish_reason': 'length' if sample == 'length' else 'stop'}]}) + '\n\n', 'data: [DONE]\n\n']
            data = ''.join(lines).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            for offset in range(0, len(data), 7):
                self.wfile.write(data[offset:offset + 7])
                self.wfile.flush()
                time.sleep(0.002)
        except (BrokenPipeError, ConnectionResetError):
            pass  # expected when cancellation or deadline closes the request
        except Exception as error:
            errors.append(type(error).__name__)


server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
server.daemon_threads = True
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
try:
    result = subprocess.run([sys.argv[1], f'http://127.0.0.1:{server.server_port}/v1'], timeout=28)
    if errors:
        raise SystemExit('FAIL: fixture ' + repr(errors))
    assert requests.count('success') == 4, requests
    assert requests.count('overlap') == 1, requests
    raise SystemExit(result.returncode)
finally:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)
