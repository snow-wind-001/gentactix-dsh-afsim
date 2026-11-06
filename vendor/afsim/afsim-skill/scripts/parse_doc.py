"""
AFSIM-SKILL 文档解析脚本

支持解析 MD 和 PDF 文件中的 AFSIM 语法要点，
并按分类存入 refs/learn/ 对应文件。

使用方法：
    python scripts/parse_doc.py <文件路径> [--category <分类>]

分类选项：sensor, weapon, platform, mover, processor,
          script, radar, comm, other

示例：
    python scripts/parse_doc.py f:\\docs\\afsim_sensor.md
    python scripts/parse_doc.py f:\\docs\\afsim_sensor.pdf --category sensor
"""

import os
import sys
import re
import argparse
from datetime import date

try:
    import pdfplumber

    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

try:
    import pypdf

    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False


CATEGORIES = ["sensor", "weapon", "platform", "mover", "processor", "script", "radar", "comm", "other"]


def read_file(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".md":
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    elif ext == ".pdf":
        return extract_pdf(path)
    else:
        print(f"[WARN] 不支持的格式: {ext}，尝试作为文本读取")
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()


def extract_pdf(path: str) -> str:
    if HAS_PDFPLUMBER:
        try:
            import pdfplumber
            text_parts = []
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        text_parts.append(t)
            return "\n\n".join(text_parts)
        except Exception as e:
            print(f"[WARN] pdfplumber 解析失败: {e}")

    if HAS_PYPDF:
        try:
            import pypdf
            reader = pypdf.PdfReader(path)
            text_parts = []
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    text_parts.append(t)
            return "\n\n".join(text_parts)
        except Exception as e:
            print(f"[WARN] pypdf 解析失败: {e}")

    print("[ERROR] PDF 解析需要安装 pdfplumber: pip install pdfplumber")
    sys.exit(1)


def extract_code_blocks(text: str) -> list:
    pattern = re.compile(r"```(?:text|afsim)?(.*?)```", re.DOTALL)
    return [block.strip() for block in pattern.findall(text) if block.strip()]


def extract_headings(text: str) -> list:
    pattern = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
    return pattern.findall(text)


def parse_doc(content: str, source_path: str, category: str) -> str:
    today = date.today().isoformat()
    source_name = os.path.basename(source_path)

    blocks = extract_code_blocks(content)
    headings = extract_headings(content)

    output_lines = [
        "---",
        f"source: {source_name}",
        f"date: {today}",
        f"category: {category}",
        "---",
        "",
        f"## 来源: {source_name} ({category})",
        "",
        f"文档标题: {' / '.join(headings[:3]) if headings else '未知'}",
        "",
    ]

    for i, block in enumerate(blocks, 1):
        if len(block) < 20:
            continue
        output_lines.append(f"### 代码片段 {i}")
        output_lines.append("")
        output_lines.append("```text")
        output_lines.append(block)
        output_lines.append("```")
        output_lines.append("")

    return "\n".join(output_lines)


def save_learn_entry(content: str, category: str):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    skill_root = os.path.dirname(script_dir)
    learn_dir = os.path.join(skill_root, "refs", "learn")
    os.makedirs(learn_dir, exist_ok=True)

    dest_path = os.path.join(learn_dir, f"{category}.md")

    if os.path.exists(dest_path):
        with open(dest_path, "r", encoding="utf-8") as f:
            existing = f.read()
        separator = "\n\n---\n\n"
        content = existing.rstrip() + separator + content

    with open(dest_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"[OK] 内容已追加到: {dest_path}")


def main():
    parser = argparse.ArgumentParser(description="解析 AFSIM 文档")
    parser.add_argument("file", help="文档路径 (.md 或 .pdf)")
    parser.add_argument(
        "--category", "-c",
        choices=CATEGORIES,
        default="other",
        help=f"分类 ({', '.join(CATEGORIES)})"
    )
    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"[ERROR] 文件不存在: {args.file}")
        sys.exit(1)

    print(f"读取文件: {args.file}")
    content = read_file(args.file)

    if len(content) < 50:
        print("[ERROR] 文件内容太少，可能读取失败")
        sys.exit(1)

    print(f"提取到 {len(content)} 字符内容")
    print(f"分类: {args.category}")

    parsed = parse_doc(content, args.file, args.category)
    save_learn_entry(parsed, args.category)

    print("\n解析完成。请在 IDE 中查看 refs/learn/ 下的结果。")


if __name__ == "__main__":
    main()
