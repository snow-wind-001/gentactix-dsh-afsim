"""Actual native DSH adapter against a local SSE fixture, no paid model calls."""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main():
    root = Path('.cache/qa/model-policy-medium-2026-10-29/wire').resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.environ['GENTACTIX_DSH_HOME'] = str(root / 'dsh-home')
    os.environ['GENTACTIX_DSH_WORKSPACE'] = str(root / 'workspace')
    os.environ['GENTACTIX_LLM_CONFIG'] = str(root / 'nonexistent.enc')
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append({'path': self.path, 'effort': body.get('reasoning_effort'),
                             'cap': body.get('max_tokens'), 'model': body['model']})
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            payload = {'id': 'qa', 'object': 'chat.completion.chunk', 'created': 1,
                       'model': body['model'], 'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': 'OK'}, 'finish_reason': None}]}
            self.wfile.write(('data: '+json.dumps(payload)+'\n\n').encode())
            payload['choices'] = [{'index': 0, 'delta': {}, 'finish_reason': 'stop'}]
            self.wfile.write(('data: '+json.dumps(payload)+'\n\ndata: [DONE]\n\n').encode())
            self.wfile.flush()

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    from backend import harness_engine as h
    h.LLM_BASE_URL = f'http://127.0.0.1:{server.server_port}/v1'
    h.LLM_MODEL = 'fixture-qwen'
    h.LLM_API_KEY = 'fixture-only'
    h.LLM_MAX_TOKENS = 65536
    h.CONTEXT_WINDOW = 262144
    h.ROLE_POLICIES = {}
    try:
        for effort in ('low', 'medium', 'high', 'xhigh', None):
            h.ROLE_POLICIES['chat'] = {'reasoning_effort': effort, 'max_tokens': 65536}
            result = h._run_brain('Reply OK.', None, role='chat')
            assert result.final_response.strip() == 'OK'
            assert requests[-1] == {'path': '/v1/chat/completions', 'effort': effort, 'cap': 65536, 'model': 'fixture-qwen'}, requests[-1]
        report = {'passed': True, 'native_dsh': True, 'live_model': False, 'requests': requests}
        (root/'result.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report))
    finally:
        h.close_harness()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == '__main__':
    main()
