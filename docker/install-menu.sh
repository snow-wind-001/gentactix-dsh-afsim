#!/usr/bin/env bash
set -euo pipefail
package_dir="$(cd -- "$(dirname -- "$0")" && pwd)"
applications_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$applications_dir"
python3 - "$package_dir" "$applications_dir" <<'PYTHON'
from pathlib import Path
import sys
package=Path(sys.argv[1]);dest=Path(sys.argv[2])/'gentactix-docker.desktop'
def quoted(s):return '"'+str(s).replace('\\','\\\\').replace('"','\\"').replace('`','\\`').replace('$','\\$')+'"'
dest.write_text('[Desktop Entry]\nType=Application\nName=GenTactix 教学推演（Docker）\nComment=启动本机 GenTactix 教学容器\nExec='+quoted(package/'start.sh')+'\nIcon='+str(package/'gentactix.png')+'\nTerminal=true\nCategories=Education;Science;\n')
dest.chmod(0o755)
print(dest)
PYTHON
