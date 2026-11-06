#!/usr/bin/env python3
"""Liveness of the web/API pair; not model or AFSIM acceptance."""
import json
import urllib.request

with urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=5) as response:
    result = json.load(response)
    if response.status != 200 or result.get('status') != 'ok':
        raise SystemExit(1)
