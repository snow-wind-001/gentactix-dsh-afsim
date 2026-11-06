#!/usr/bin/env python3
"""Linux compatibility entry for upstream AFSIM_MCP's executable-path setting."""
from launch import run_mission
import sys


if __name__ == '__main__':
    raise SystemExit(run_mission(sys.argv[1:]))
