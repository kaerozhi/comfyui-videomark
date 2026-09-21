# -*- coding: utf-8 -*-
"""
一键自检（不开 ComfyUI）
========================
按顺序跑完这个包的全部离线检查，汇总结果。

    python tools/check_all.py

改完代码（尤其是 prompt 逻辑、面板参数、语言包）之后跑一遍，
比重启 ComfyUI 一个个点快得多。

顺序是有讲究的：先跑最便宜的静态检查，出错时能立刻定位，
省得等了半天才在最后一步发现前面就写错了。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

TOOLS = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

STEPS = [
    ("渲染核心 + 节点逻辑", "selftest.py", 600),
    ("面板与后端参数一致性", "uicheck.py", 300),
    ("前端脚本语法 + 坑位迁移", "jscheck.py", 300),
    ("语言包生成 / 校验", "gen_locales.py", 300),
    ("按 ComfyUI 方式加载注册", "loadcheck.py", 300),
    ("ComfyUI 后端 prompt 校验", "promptcheck.py", 600),
    ("按前端调用方式真跑节点", "callcheck.py", 600),
]


def main() -> int:
    print("=" * 70)
    print("comfyui-videomark 离线自检")
    print("=" * 70)
    results = []
    for title, script, timeout in STEPS:
        path = os.path.join(TOOLS, script)
        if not os.path.isfile(path):
            results.append((title, script, None, "找不到脚本"))
            continue
        print(f"\n>>> {title}（{script}）")
        t0 = time.time()
        try:
            proc = subprocess.run([PY, path], cwd=os.path.dirname(TOOLS),
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired:
            results.append((title, script, False, f"超时（>{timeout}s）"))
            print(f"    [TIMEOUT] 超过 {timeout}s")
            continue
        dt = time.time() - t0
        tail = [ln for ln in (proc.stdout or "").strip().splitlines() if ln.strip()]
        for ln in tail[-4:]:
            print("    " + ln)
        if proc.returncode != 0 and (proc.stderr or "").strip():
            for ln in proc.stderr.strip().splitlines()[-6:]:
                print("    ! " + ln)
        results.append((title, script, proc.returncode == 0, f"{dt:.1f}s"))

    print("\n" + "=" * 70)
    bad = 0
    for title, script, ok, note in results:
        if ok is None:
            print(f"  [SKIP] {title:28s} {note}")
            bad += 1
        elif ok:
            print(f"  [ OK ] {title:28s} {note}")
        else:
            print(f"  [FAIL] {title:28s} {note}")
            bad += 1
    print("=" * 70)
    print("全部通过。" if bad == 0 else f"有 {bad} 项没过，往上翻看输出。")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
