"""Keyless compatibility probe using the installed SDK and real native plugin.

Only a loopback model fixture is used. Runtime homes and journals are retained
under --out; user credentials, configuration and battles are never loaded.
This checks transport/lifecycle compatibility, not real model quality.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version
import json
import os
from pathlib import Path
import threading
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--resume-parent', help='Restore a parent produced by an earlier SDK in the same --out home')
    args = parser.parse_args()
    root = args.out.resolve()
    root.mkdir(parents=True, exist_ok=True)
    requests = []
    waiting = threading.Event()
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['content-length'])))
            requests.append(body)
            # DSH may append a runtime-context user block after the prompt.
            # Match this fixture's actual instruction, never that context block.
            text = ''
            for message in reversed(body['messages']):
                if message['role'] != 'user':
                    continue
                content = message['content']
                content = ''.join(b.get('text', '') for b in content) if isinstance(content, list) else content
                if 'SDK_' in content:
                    text = content
                    break
            self.send_response(200)
            self.send_header('content-type', 'text/event-stream')
            self.end_headers()

            def send(delta, finish=None):
                value = {'id': 'keyless-upgrade', 'object': 'chat.completion.chunk', 'created': 0,
                         'model': 'sdk-upgrade-fixture',
                         'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}
                self.wfile.write(('data: ' + json.dumps(value) + '\n\n').encode())
                self.wfile.flush()

            try:
                send({'role': 'assistant'})
                if 'SDK_CANCEL' in text:
                    waiting.set()
                    release.wait(30)
                answer = 'RESUME_OK' if 'SDK_RESUME' in text else 'FORK_OK' if 'SDK_FORK' in text else 'FIRST_OK'
                send({'content': answer})
                send({}, 'stop')
                self.wfile.write(b'data: [DONE]\n\n')
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    for key, suffix in [('DSH_HOME', 'dsh-home'), ('DSH_WORKSPACE', 'workspace'),
                        ('SESSION_DIR', 'battles'), ('TRACE_DIR', 'traces'),
                        ('ROLE_INDEX', 'roles.json'), ('LLM_CONFIG', 'llm.enc'),
                        ('VAULT_KEY_FILE', 'vault.key')]:
        os.environ['GENTACTIX_' + key] = str(root / suffix)
    os.environ.update(GENTACTIX_LLM_BASE_URL=f'http://127.0.0.1:{server.server_port}/v1',
                      GENTACTIX_LLM_API_KEY='keyless-local-fixture', GENTACTIX_LLM_MODEL='sdk-upgrade-fixture',
                      GENTACTIX_NATIVE_RUNTIME='1')
    from backend import harness_engine as h
    result = {'passed': False, 'actual_model': False, 'actual_native_runtime': True,
              'sdk': version('deepseek-harness-sdk'), 'runtime': version('deepseek-harness-runtime-bin')}
    try:
        observer = h.RunObserver('SDK lifecycle fixture')
        if args.resume_parent:
            restored=h.get_harness().resume_session(args.resume_parent)
            assert not requests, 'Restoration must not issue a model request'
            first=restored.run('SDK_RESUME',on_notification=observer.on_notification)
            observer.record_result(first)
            assert first.final_response=='RESUME_OK'
            assert 'SDK_FIRST' in json.dumps(requests[-1]['messages'])
            assert 'FIRST_OK' in json.dumps(requests[-1]['messages'])
            result['restored_prior_sdk_parent']=True
        else:
            first = h._run_brain('SDK_FIRST', None, observer=observer)
            assert first.final_response == 'FIRST_OK'
        result['parent_session_id']=first.session_id
        parent = observer.runs[-1]
        fork = h.fork_run(parent, 'SDK_FORK', h.RunObserver('SDK branch fixture'))
        assert fork.final_response == 'FORK_OK'
        assert fork.session_id != first.session_id
        assert 'SDK_FIRST' in json.dumps(requests[-1]['messages'])
        assert 'FIRST_OK' in json.dumps(requests[-1]['messages'])
        result['fork_exact_prefix'] = True
        h.close_harness()
        before = len(requests)
        resumed = h.get_harness().resume_session(first.session_id)
        assert len(requests) == before, 'Resume must not send model input'
        response = resumed.run('SDK_RESUME')
        assert response.session_id == first.session_id and response.final_response == 'RESUME_OK'
        assert 'SDK_FIRST' in json.dumps(requests[-1]['messages'])
        assert 'FIRST_OK' in json.dumps(requests[-1]['messages'])
        assert 'SDK_FORK' not in json.dumps(requests[-1]['messages']), 'Branch polluted parent history'
        result['restart_resume_preserved_history'] = True
        observer = h.RunObserver('SDK cancellation fixture')
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(h._run_brain, 'SDK_CANCEL', None, observer=observer)
            assert waiting.wait(20), 'No active model transport'
            started = time.monotonic()
            receipt = h.cancel_observer(observer)
            assert any(r.get('ok') for r in receipt), receipt
            try:
                future.result(timeout=10)
            except h.HarnessRunError:
                pass
            else:
                raise AssertionError('Cancelled output was accepted')
            finally:
                release.set()
            result['cancel_seconds'] = round(time.monotonic() - started, 3)
        result.update(passed=True, native_cancel_acknowledged=True, cancelled_output_rejected=True,
                      model_requests=len(requests))
    finally:
        release.set()
        h.close_harness()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        (root / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
