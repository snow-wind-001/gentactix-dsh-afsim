"""
AFSIM-SKILL 安装向导

使用方法：
    python scripts/install.py

检查环境并引导用户完成安装。
"""

import sys
import os
import shutil

try:
    import readline  # noqa: F401
except ImportError:
    pass


def print_banner():
    banner = r"""
 +------------------------------------------------------+
 |                                                      |
 |   A F S I M - S K I L L                             |
 |   ===================================                |
 |                                                      |
"""
    print(banner)


def print_status(ok: bool, msg: str):
    status = "  [OK]" if ok else "  [FAIL]"
    print(f"  {status}  {msg}")


def check_python():
    version = sys.version_info
    print(f"\nPython 版本: {version.major}.{version.minor}.{version.micro}")
    if version.major >= 3 and version.minor >= 8:
        print_status(True, "Python 版本满足要求")
        return True
    else:
        print_status(False, "需要 Python 3.8+")
        return False


def check_ide():
    print("\n检查 IDE 环境:")
    ide_found = []

    # 检查 Cursor
    cursor_path = os.path.join(os.environ.get("APPDATA", ""), "Cursor")
    if os.path.exists(cursor_path):
        print_status(True, "检测到 Cursor IDE")
        ide_found.append("Cursor")

    # 检查 Trae
    trae_path = os.path.join(os.environ.get("APPDATA", ""), "Trae")
    if os.path.exists(trae_path):
        print_status(True, "检测到 Trae IDE")
        ide_found.append("Trae")

    if not ide_found:
        print_status(False, "未检测到支持的 IDE")
        return False
    return True


def check_skill_dir():
    print("\n检查 Skill 目录:")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    skill_root = os.path.dirname(script_dir)
    skl_path = os.path.join(skill_root, "SKILL.md")

    if os.path.exists(skl_path):
        print_status(True, f"SKILL.md 存在于: {skl_path}")
        return True
    else:
        print_status(False, "未找到 SKILL.md")
        return False


def print_done():
    done = r"""
 +------------------------------------------------------+
 |                                                      |
 |   ALL SYSTEM STATUS : NOMINAL                        |
 |   SKILL DIRECTORY    : READY                        |
 |   IDE COMPATIBILITY  : READY                        |
 |                                                      |
 |   Next: Open this directory in Cursor/Trae           |
 |   Then start chatting with /afsim                   |
 |                                                      |
 +------------------------------------------------------+
"""
    print(done)


def main():
    print_banner()
    print("检查系统环境...\n")

    checks = [
        ("Python 版本", check_python),
        ("IDE 环境", check_ide),
        ("Skill 目录", check_skill_dir),
    ]

    all_ok = True
    for name, fn in checks:
        if not fn():
            all_ok = False

    if all_ok:
        print_done()
    else:
        print("\n  部分检查未通过，请解决上述问题后重试。")
        print("  如有问题，请参考 README.md 或联系海空兵棋。\n")

    input("\n按 Enter 退出...")


if __name__ == "__main__":
    main()
