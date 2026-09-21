# -*- coding: utf-8 -*-
"""
comfyui-videomark 加载自检
==========================
完全复刻 ComfyUI 的 custom_node 加载方式（importlib + submodule_search_locations），
确认 __init__.py 能被正确执行、节点能注册、且不与已有节点重名。

用法：
    python tools\\loadcheck.py
"""

from __future__ import annotations

import importlib.util
import os
import sys

PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMFY_DIR = r"D:\AI\ComfyUI"
PKG_NAME = os.path.basename(PKG_DIR)

sys.path.insert(0, COMFY_DIR)

# 收集已有节点名，检查重名
EXISTING = set()
CUSTOM_NODES = os.path.join(COMFY_DIR, "custom_nodes")
for entry in sorted(os.listdir(CUSTOM_NODES)):
    d = os.path.join(CUSTOM_NODES, entry)
    if entry == PKG_NAME or not os.path.isdir(d):
        continue
    for probe in ("nodes.py", "__init__.py"):
        p = os.path.join(d, probe)
        if not os.path.isfile(p):
            continue
        try:
            text = open(p, encoding="utf-8", errors="ignore").read()
        except OSError:
            continue
        import re
        for m in re.finditer(r"^\s*\"([A-Za-z][A-Za-z0-9_]{2,})\"\s*:", text, re.MULTILINE):
            EXISTING.add(m.group(1))


def main() -> int:
    print("=" * 66)
    print(f"按 ComfyUI 方式加载：{PKG_DIR}")
    print("=" * 66)

    spec = importlib.util.spec_from_file_location(
        "comfyui_videomark_init",
        os.path.join(PKG_DIR, "__init__.py"),
        submodule_search_locations=[PKG_DIR],
    )
    if spec is None or spec.loader is None:
        print("[FAIL] 无法为 __init__.py 建立加载器")
        return 1

    module = importlib.util.module_from_spec(spec)
    sys.modules["comfyui_videomark_init"] = module
    spec.loader.exec_module(module)

    classes = getattr(module, "NODE_CLASS_MAPPINGS", None)
    display = getattr(module, "NODE_DISPLAY_NAME_MAPPINGS", None)
    version = getattr(module, "__version__", "?")

    if not classes:
        print("[FAIL] NODE_CLASS_MAPPINGS 为空或缺失")
        return 1
    if not display:
        print("[FAIL] NODE_DISPLAY_NAME_MAPPINGS 为空或缺失")
        return 1

    print(f"\n版本 {version}，注册 {len(classes)} 个节点：")
    ok = True
    for key, cls in classes.items():
        name = display.get(key, "(缺显示名)")
        has = all(hasattr(cls, a) for a in
                  ("INPUT_TYPES", "RETURN_TYPES", "FUNCTION", "CATEGORY"))
        func_ok = hasattr(cls, getattr(cls, "FUNCTION", ""))
        spec_ok = True
        try:
            cls.INPUT_TYPES()
        except Exception as e:                                        # noqa: BLE001
            spec_ok = False
            print(f"  [FAIL] {key}: INPUT_TYPES() 抛错 {type(e).__name__}: {e}")
        clash = key in EXISTING
        flag = "[OK]" if (has and func_ok and spec_ok and not clash) else "[FAIL]"
        if flag == "[FAIL]":
            ok = False
        print(f"  {flag} {key}")
        print(f"        显示名 {name}")
        print(f"        分类 {cls.CATEGORY} | 返回 {cls.RETURN_TYPES} | FUNCTION={cls.FUNCTION}")
        if not has:
            print("        缺属性：INPUT_TYPES / RETURN_TYPES / FUNCTION / CATEGORY 之一")
        if not func_ok:
            print(f"        类上没有 {cls.FUNCTION} 方法")
        if clash:
            print("        ⚠ 与 custom_nodes 里已有节点重名，会被后者覆盖")

    if hasattr(module, "WEB_DIRECTORY"):
        wd = module.WEB_DIRECTORY
        p = os.path.join(PKG_DIR, wd)
        print(f"\n前端扩展目录 {wd} → {'存在' if os.path.isdir(p) else '不存在'}")

    # 面板接口：/videomark/meta 是现在唯一的后端接口。它是「预设档 → 滑块该摆在哪」
    # 的唯一数据源（前端不抄一份），坏了不会报错，只会让滑块静默跑偏 —— 所以在这里钉一下。
    api = sys.modules.get("comfyui_videomark_init.webapi")
    if api is None:
        print("\n[FAIL] 面板接口模块 webapi 未能导入（面板预设档会失效）")
        ok = False
    else:
        try:
            meta = api.build_meta()
        except Exception as e:                                        # noqa: BLE001
            print(f"\n[FAIL] webapi.build_meta() 抛错 {type(e).__name__}: {e}")
            ok = False
        else:
            need = {"modes", "positions", "float_paths", "layouts", "styles"}
            miss = sorted(need - set(meta))
            fields = {"use_stroke", "use_shadow", "stroke_opacity", "shadow_opacity"}
            bad = [k for k, v in meta.get("styles", {}).items() if set(v) != fields]
            print(f"\n面板接口 build_meta()：{len(meta)} 个键，"
                  f"{len(meta.get('styles', {}))} 条样式预设")
            if miss:
                print(f"  [FAIL] 缺键：{', '.join(miss)}")
                ok = False
            if bad:
                print(f"  [FAIL] 预设字段不全（应含 {len(fields)} 项）：{', '.join(bad)}")
                ok = False
            if not miss and not bad:
                print("  [OK] 键与预设字段齐全")

    print("\n" + "=" * 66)
    print("加载自检通过" if ok else "加载自检失败")
    print("=" * 66)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
