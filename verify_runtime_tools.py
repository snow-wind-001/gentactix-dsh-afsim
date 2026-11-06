"""Native DSH tool-surface policy regressions (no model/API dependency)."""
import subprocess
import json
import http.client
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


class RuntimeToolTests(unittest.TestCase):
    def test_chinese_tool_rejection_is_utf8_json_and_next_request_still_works(self):
        from http.server import ThreadingHTTPServer
        from backend import runtime_bridge as bridge
        server=ThreadingHTTPServer(('127.0.0.1',0),bridge._Handler)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3)
        def dispatch(context,payload):
            if payload['args'].get('offset'):
                raise ValueError('状态变化翻页必须沿用第一页的view_version版本与查询范围')
            return {'ok':True,'context':context}
        try:
            with patch.object(bridge,'_token','qa-only-token'),patch.object(bridge,'_dispatcher',dispatch),patch.dict(bridge._contexts,{'qa':{'read_only':True}}):
                headers={'Authorization':'Bearer qa-only-token','Content-Type':'application/json'}
                for args,status in (({'offset':16},400),({'offset':0},200)):
                    connection.request('POST','/tool',json.dumps({'session_id':'qa','args':args}),headers)
                    reply=connection.getresponse();body=json.loads(reply.read().decode('utf-8'))
                    self.assertEqual(reply.status,status)
                    self.assertIn('application/json',reply.getheader('Content-Type'))
                    if status==400:self.assertIn('view_version',body['error'])
                    else:self.assertEqual(body,{'ok':True,'context':{'read_only':True}})
                self.assertEqual(bridge._contexts['qa'],{'read_only':True})
        finally:
            connection.close();server.shutdown();server.server_close();worker.join(timeout=3)

    def run_node(self, script):
        root = Path(__file__).resolve().parent
        value = subprocess.run(['node', script], cwd=root,
                               text=True, capture_output=True, timeout=20)
        self.assertEqual(value.returncode, 0, value.stdout + value.stderr)

    def test_agent_scoped_tool_visibility(self):
        self.run_node('tools/qa/runtime_tool_visibility.mjs')

    def test_plugin_first_request_and_reconfiguration(self):
        self.run_node('tools/qa/runtime_policy_lifecycle.mjs')


if __name__ == '__main__':
    unittest.main()
