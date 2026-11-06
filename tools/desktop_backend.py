"""Frozen desktop backend entry point; binds only to loopback."""
import multiprocessing
import os
import sys
from pathlib import Path


if __name__ == '__main__':
    multiprocessing.freeze_support()
    if '--afsim-mcp' in sys.argv:
        import runpy
        from tools.afsim.launch import layout, prepare_mcp, PROJECT
        paths = layout(Path(os.environ.get('GENTACTIX_PROJECT_ROOT', PROJECT)))
        environment = prepare_mcp(paths)
        os.environ.clear(); os.environ.update(environment)
        # The upstream source transport falls back to top-level `tools` imports.
        # Release our launcher namespace before loading that isolated server.
        for name in list(sys.modules):
            if name == 'tools' or name.startswith('tools.'):
                sys.modules.pop(name)
        sys.argv = [str(paths['mcp'])]
        runpy.run_path(str(paths['mcp']), run_name='__main__')
        raise SystemExit(0)
    if '--afsim-mission-proxy' in sys.argv:
        from tools.afsim.launch import layout, run_mission, PROJECT
        paths = layout(Path(os.environ.get('GENTACTIX_PROJECT_ROOT', PROJECT)))
        raise SystemExit(run_mission(sys.argv[2:], paths=paths))
    import uvicorn
    from backend.main import app
    uvicorn.run(app, host='127.0.0.1', port=int(os.environ.get('GENTACTIX_PORT', '8700')))
