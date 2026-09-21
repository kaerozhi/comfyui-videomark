# -*- coding: utf-8 -*-
"""
用 ComfyUI 自己的后端校验器验一遍节点声明。
重点确认：
  1. optional 的 logo / logo_mask / audio 不接线时，校验能通过；
  2. INPUT_TYPES 声明的每个参数，apply() 的形参表都收得下（见 check_signature）。

用法：python tools\\promptcheck.py
"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys

PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMFY_DIR = r"D:\AI\ComfyUI"
sys.path.insert(0, COMFY_DIR)
sys.path.insert(0, PKG_DIR)


def load():
    spec = importlib.util.spec_from_file_location(
        "vmk_promptcheck", os.path.join(PKG_DIR, "__init__.py"),
        submodule_search_locations=[PKG_DIR])
    m = importlib.util.module_from_spec(spec)
    sys.modules["vmk_promptcheck"] = m
    spec.loader.exec_module(m)
    return m


def defaults(cls):
    d = {}
    for bucket in ("required", "optional"):
        for k, v in cls.INPUT_TYPES().get(bucket, {}).items():
            t = v[0]
            if isinstance(t, list):
                d[k] = t[0]
            elif t in ("IMAGE", "MASK", "AUDIO", "VIDEO"):
                d[k] = None
            elif t == "STRING":
                d[k] = v[1].get("default", "")
            elif t in ("INT", "FLOAT"):
                d[k] = v[1].get("default", 0)
            elif t == "BOOLEAN":
                d[k] = v[1].get("default", False)
    return d


def check_signature(m) -> list:
    """
    声明了就必须收得下：INPUT_TYPES 的键 ⊆ apply() 的形参名。

    ComfyUI 执行节点是 `f(**inputs)`，inputs 的键**完全来自**
    INPUT_TYPES 的 required + optional。声明里多一个、签名里少一个，
    运行到那一步就抛 TypeError，而且报错位置在 execution.py，看着像框架的错。

    validate_prompt() 查不出这类问题 —— 它只读声明，不读函数签名。
    真事：logo_file 声明过、两个节点的 apply() 漏收，6 关自检全绿，用户一跑就挂。
    """
    import inspect

    problems = []
    for name, cls in m.NODE_CLASS_MAPPINGS.items():
        it = cls.INPUT_TYPES()
        declared = []
        for bucket in ("required", "optional"):
            declared += list(it.get(bucket, {}).keys())
        fn = getattr(cls, getattr(cls, "FUNCTION", "apply"), None)
        if fn is None:
            problems.append(f"{name}: INPUT_TYPES 有声明，但找不到 FUNCTION 指向的方法")
            continue
        sig = inspect.signature(fn)
        if any(p.kind == p.VAR_KEYWORD for p in sig.parameters.values()):
            continue                                   # **kwargs 兜底，怎么都收得下
        missing = [d for d in declared if d not in sig.parameters]
        if missing:
            problems.append(
                f"{name}: INPUT_TYPES 声明了 {', '.join(missing)}，"
                f"但 {getattr(cls, 'FUNCTION', 'apply')}() 的形参表里没有 —— "
                f"跑起来会抛 TypeError: ... got an unexpected keyword argument")
    return problems


async def main() -> int:
    import torch
    import execution
    import nodes as comfy_nodes

    m = load()

    # 先做静态契约检查（不需要 ComfyUI 执行器就能判，失败也没必要往下跑）
    problems = check_signature(m)
    for p in problems:
        print(f"  [FAIL] {p}")
    if problems:
        print("\n参数契约不通过：声明与 apply() 签名对不上，先修这个。")
        return 1
    print(f"  [OK]   参数契约：{len(m.NODE_CLASS_MAPPINGS)} 个节点，"
          f"声明的参数 apply() 全部收得下")

    comfy_nodes.NODE_CLASS_MAPPINGS.update(m.NODE_CLASS_MAPPINGS)

    # 造一个只吐 IMAGE 的替身节点，避免依赖具体版本里内置节点叫什么名
    class _FakeImage:
        @classmethod
        def INPUT_TYPES(cls):
            return {"required": {}}

        RETURN_TYPES = ("IMAGE",)
        FUNCTION = "run"
        CATEGORY = "dev"

        def run(self):
            return (torch.zeros(1, 8, 8, 3),)

    comfy_nodes.NODE_CLASS_MAPPINGS["VMFakeImage"] = _FakeImage

    # 还需要一个输出节点，否则 ComfyUI 会以「Prompt has no outputs」拒绝
    class _FakeSave:
        @classmethod
        def INPUT_TYPES(cls):
            return {"required": {"images": ("IMAGE",)}}

        RETURN_TYPES = ()
        OUTPUT_NODE = True
        FUNCTION = "run"
        CATEGORY = "dev"

        def run(self, images):
            return {}

    comfy_nodes.NODE_CLASS_MAPPINGS["VMFakeSave"] = _FakeSave

    cases = [
        ("VideoMarkOverlay", ["logo", "logo_mask"]),
        ("VideoMarkTitle", ["logo", "logo_mask", "audio"]),
    ]
    ok_all = True
    for name, drop in cases:
        cls = m.NODE_CLASS_MAPPINGS[name]
        inputs = defaults(cls)
        for k in drop:
            inputs.pop(k, None)                 # 模拟「这些口没接线」
        ins = {k: v for k, v in inputs.items() if v is not None}
        ins["images"] = ["2", 0]
        prompt = {
            "1": {"class_type": name, "inputs": ins},
            "2": {"class_type": "VMFakeImage", "inputs": {}},
            "3": {"class_type": "VMFakeSave", "inputs": {"images": ["1", 0]}},
        }
        # 第三个参数必须传 None：传空列表会被判定成「没有任何输出节点」
        res = await execution.validate_prompt("selftest", prompt, None)
        good = res[0]
        err = res[1] if not good else None
        ok_all = ok_all and good
        print(f"  {'[OK]  ' if good else '[FAIL]'} {name}（未接 {'/'.join(drop)}）: valid={good}")
        if not good:
            print(f"         {err}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
