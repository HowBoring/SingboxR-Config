#!/usr/bin/env python3
"""Build distributable configuration targets from the modular source tree."""
from __future__ import annotations
import argparse
from pathlib import Path
import subprocess
import sys

import manage as m

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", choices=["windows"])
    parser.add_argument("--template", action="store_true", help="允许 Provider/API 占位符，生成可审阅模板")
    parser.add_argument("--output", help="输出路径")
    parser.add_argument("--check", action="store_true", help="生成后调用目标 reF1nd 内核执行 check")
    parser.add_argument("--core", help="reF1nd sing-box 可执行文件路径")
    parser.add_argument("--keep-seed-paths", action="store_true", help="保留 initial_path；导入 Windows 前必须改成目标机器可访问的路径")
    args = parser.parse_args()
    if args.target == "windows":
        output = m.write_windows_profile(template=args.template, output=args.output, keep_seed_paths=args.keep_seed_paths)
        if args.check:
            if args.template:
                raise m.ConfigError("含占位符的模板不能执行原生 check；请先填写 Provider 并 init。")
            exe = m.core_path(args.core)
            return subprocess.call([exe, "check", "-c", str(output)], cwd=m.ROOT)
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main() or 0)
    except m.ConfigError as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        sys.exit(2)
