# -*- coding: utf-8 -*-
"""
变异测试：证明「外部文字接入」这三道防线真的会响。
==================================================

绿的自检只说明现有代码没问题，不说明检查有效 —— 正则写错、锚点没命中、
早退分支挡在前面，它都会安静地放过 bug。所以这里故意把代码改坏，
要求检查**必须**报出来，然后逐字节还原。

三组：
  A. 去掉 forceInput         → 它变成控件槽；uicheck 必须报「面板没接管」
                              （这条同时证明 is_widget_param 的 forceInput 补丁是必需的）
  B. 把 forceInput 放 required → 它变成必填连线口；check_link_inputs 必须报
  C. 往控件表中间插一个参数   → 老工作流错位；selftest 的冻结表必须报

⚠ 它**真的会改写 nodes.py**（改完立刻从内存还原，并逐字节校验 sha256）。
所以：不要和别的检查并行跑，也**不要**加进 check_all.py 的默认步骤 ——
它验的是「防线本身有没有效」，跑一次就够，不是每次改代码都要跑的东西。

跑法（在包目录下）：

    python tools/guardcheck.py
"""

from __future__ import annotations

import io
import os
import subprocess
import sys

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NODES = os.path.join(PKG, "nodes.py")
PY = sys.executable

ORIGINAL = io.open(NODES, encoding="utf-8").read()      # 先进内存，绝不重读
import hashlib                                          # noqa: E402
BEFORE = hashlib.sha256(ORIGINAL.encode("utf-8")).hexdigest()

FAILS = []


def run(script, needle):
    """跑一个自检脚本，看输出里有没有 needle。返回 (命中, 输出尾)。"""
    r = subprocess.run([PY, os.path.join(PKG, "tools", script)], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", cwd=PKG, timeout=600)
    out = (r.stdout or "") + (r.stderr or "")
    return needle in out, r.returncode, out


def mutate(pairs, script, needle, label):
    """按 pairs 改文件 → 跑检查 → 还原（从内存写回）→ 逐字节校验。"""
    src = ORIGINAL
    for a, b in pairs:
        assert src.count(a) == 1, f"{label}: 锚点命中 {src.count(a)} 次，不是 1 次，拒绝改"
        src = src.replace(a, b)
    with io.open(NODES, "w", encoding="utf-8", newline="\n") as f:
        f.write(src)
    try:
        hit, code, out = run(script, needle)
    finally:
        with io.open(NODES, "w", encoding="utf-8", newline="\n") as f:
            f.write(ORIGINAL)                            # 从内存还原，不重读文件
    now = hashlib.sha256(io.open(NODES, "rb").read()).hexdigest()
    assert now == BEFORE, f"{label}: 还原后哈希不一致！{now[:12]} != {BEFORE[:12]}"
    print(f"  {'✓' if hit else '✗'} {label}")
    print(f"      检查{'报出来了' if hit else '没报（防线无效）'}：{needle}")
    for ln in out.splitlines():
        if "✗" in ln or "→" in ln:
            print(f"      | {ln.strip()[:150]}")
    if not hit:
        FAILS.append(label)


print("变异测试：外部文字接入的三道防线")
print("=" * 72)

mutate([
    ('        "forceInput": True,\n', ""),
], "uicheck.py", "控件型参数面板没有接管",
    "A. 去掉 forceInput → 面板接管检查必须报（证明 is_widget_param 那个补丁是必需的）")

mutate([
    ('dict({"images": ("IMAGE",)}, **_watermark_widgets())',
     'dict({"images": ("IMAGE",), "zz_probe": ("STRING", {"forceInput": True})},'
     ' **_watermark_widgets())'),
], "uicheck.py", "却写在 required 里",
    "B. forceInput 的口放进 required → 连线口检查必须报")

mutate([
    ('"required": _with_logo(dict({"images": ("IMAGE",)}, **_watermark_widgets())),\n'
     '            # text_in 排在最前',
     '"required": _with_logo(dict({"images": ("IMAGE",), "zz_sneak": ("STRING",'
     ' {"default": "x"})}, **_watermark_widgets())),\n'
     '            # text_in 排在最前'),
], "selftest.py", "控件槽位变了",
    "C. 往控件表中间插一个参数 → 冻结表必须报（老工作流会整体错位）")

print()
print("=" * 72)
print("还原校验：nodes.py sha256 = %s（改前改后一致）" % BEFORE[:16])
if FAILS:
    print(f"✗ {len(FAILS)} 道防线没响：{FAILS}")
    sys.exit(1)
print("✓ 三道防线全部会响，且目标文件逐字节无损。")
