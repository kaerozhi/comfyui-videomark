# -*- coding: utf-8 -*-
"""
按「前端会传什么」真跑一遍节点 —— 契约层 + logo 行为的回归。

为什么要有这一关（漏网经过）：
    给每个节点加 logo_file 控件时，INPUT_TYPES 声明了，但 Overlay / Video 两个
    apply() 的形参表漏了一格。6 关自检全绿，用户一跑图片就挂：
        TypeError: VideoMarkOverlay.apply() got an unexpected keyword argument 'logo_file'

    漏在哪：
      · promptcheck 只调 execution.validate_prompt()，那是**纯声明校验**，
        从不碰 apply() 的签名；
      · selftest 调 apply 全是手写参数，天然覆盖不到「多出来的那个键」。
    所以这里做两件事：① 把 INPUT_TYPES 声明的键**全量**当关键字参数灌进 apply()，
    等价于前端攒 prompt；② 验 logo 的四种来源/降级行为。

用法：python tools\\callcheck.py
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile

COMFY_DIR = r"D:\AI\ComfyUI"
PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, COMFY_DIR)
sys.path.insert(0, PKG_DIR)

import numpy as np                                            # noqa: E402
import torch                                                  # noqa: E402

FAILS: list = []


def check(cond, msg: str) -> None:
    print(("  ✓ " if cond else "  ✗ ") + msg)
    if not cond:
        FAILS.append(msg)


def load():
    spec = importlib.util.spec_from_file_location(
        "vmk_callcheck", os.path.join(PKG_DIR, "__init__.py"),
        submodule_search_locations=[PKG_DIR])
    m = importlib.util.module_from_spec(spec)
    sys.modules["vmk_callcheck"] = m
    spec.loader.exec_module(m)
    return m


def prompt_inputs(cls, links: bool = False) -> dict:
    """
    攒出「前端提交的 inputs」。

    links=False 模拟**没接任何线**：ComfyUI 前端只为 widget 填值，optional 的
    连线口不接线就不会出现在 inputs 里 —— 正是用户那次出错的形状。
    """
    kw = {}
    it = cls.INPUT_TYPES()
    for bucket in ("required", "optional"):
        if bucket == "optional" and not links:
            continue
        for k, v in it.get(bucket, {}).items():
            t, opt = v[0], (v[1] if len(v) > 1 else {})
            if isinstance(t, list):
                kw[k] = t[0]
            elif t == "IMAGE":
                kw[k] = torch.zeros(1, 8, 8, 3)
            elif t in ("MASK", "AUDIO", "VIDEO"):
                kw[k] = None
            elif t == "STRING":
                kw[k] = opt.get("default", "")
            elif t in ("INT", "FLOAT"):
                kw[k] = opt.get("default", 0)
            elif t == "BOOLEAN":
                kw[k] = opt.get("default", False)
    return kw


def main() -> int:
    m = load()
    import folder_paths
    from PIL import Image

    tmp = tempfile.mkdtemp(prefix="vmk_callcheck_")
    # 把 ComfyUI 的 input 目录临时指到临时目录，别动用户真实的 input。
    # 0.34.1 里 input 不在 folder_names_and_paths（那是模型目录的），走的是模块级
    # input_directory，get_annotated_filepath() 就靠它兜底 —— 换掉这一个函数即可。
    orig_input_dir = folder_paths.get_input_directory
    folder_paths.get_input_directory = lambda: tmp

    try:
        # 带透明通道的 logo：不透明的红方块在左半边，右半边全透明
        lg = np.zeros((40, 40, 4), dtype=np.uint8)
        lg[:, :20, 0] = 255
        lg[:, :20, 3] = 255
        Image.fromarray(lg, "RGBA").save(os.path.join(tmp, "cc_logo.png"))

        def run_overlay(**over):
            cls = m.NODE_CLASS_MAPPINGS["VideoMarkOverlay"]
            kw = prompt_inputs(cls, links=False)
            kw["images"] = torch.zeros(1, 200, 300, 3)         # 300×200 的图
            kw.update(over)                                    # 给了 logo 就等于接线了
            out = cls().apply(**kw)[0]
            return out[0].cpu().numpy() if hasattr(out, "cpu") else np.asarray(out)[0]

        print("[1] 未接任何线，把 widget 值全量灌进 apply()（用户崩在这一步）")
        for name in ("VideoMarkOverlay", "VideoMarkTitle"):
            cls = m.NODE_CLASS_MAPPINGS[name]
            kw = prompt_inputs(cls, links=False)
            if "images" in kw:
                kw["images"] = torch.zeros(1, 8, 8, 3)
            try:
                cls().apply(**kw)
                check(True, f"{name}.apply(**{len(kw)} 个 widget 参数) 没抛 TypeError")
            except TypeError as e:
                check(False, f"{name}.apply() 抛了 TypeError：{e}")
            except Exception as e:                             # noqa: BLE001
                check(False, f"{name}.apply() 抛了别的异常：{type(e).__name__}: {e}")

        common = dict(use_text=True, text="© kaero", layout="horizontal")

        print("[2] 只文字（基线）")
        base = run_overlay(**common, use_logo=False, logo_file="")
        check(base.max() > 0.5, "右下角真的画上了白字")

        print("[3] 文字 + 面板上传的 logo（logo_file 必须真的生效）")
        with_logo = run_overlay(**common, use_logo=True, logo_file="cc_logo.png")
        check(float(np.abs(with_logo - base).sum()) > 0,
              "加了 logo_file 之后画面变了 —— logo 确实被用上")
        red = int(((with_logo[..., 0] > 0.6) & (with_logo[..., 1] < 0.4)).sum())
        check(red > 0, f"画面上出现 {red} 个红色像素 —— 正是 logo 的颜色")

        print("[4] logo_file 指向不存在的文件 → 降级成纯文字，不崩")
        ghost = run_overlay(**common, use_logo=True, logo_file="没有这个文件.png")
        check(float(np.abs(ghost - base).sum()) < 1e-6, "与基线一致：读不到 logo 就只画文字")

        print("[5] 连线 logo 优先于 logo_file")
        linked = run_overlay(**common, use_logo=True, logo_file="cc_logo.png",
                             logo=torch.zeros(1, 40, 40, 3))
        check(float(np.abs(linked - with_logo).sum()) > 0,
              "连线的是黑图，结果与只有文件时不同 → 连线优先")

        print("[6] use_logo=False 时 logo_file 不该干扰画面")
        off = run_overlay(**common, use_logo=False, logo_file="cc_logo.png")
        check(float(np.abs(off - base).sum()) < 1e-6, "关掉 logo 开关后与基线一致")

        print("[7] 外部文字接入（text_in）")
        for name, cls in m.NODE_CLASS_MAPPINGS.items():
            opt = (cls.INPUT_TYPES().get("optional") or {})
            check("text_in" in opt and opt["text_in"][1].get("forceInput") is True,
                  f"{name}.text_in 存在且带 forceInput（只长连线口，不占控件槽位）")

        # 空串 = 没接：断线、上游没拼出东西，都不该影响原有用法
        same_as_base = run_overlay(**common, text_in="")
        check(float(np.abs(same_as_base - base).sum()) < 1e-6,
              "text_in 传空串时与纯手填逐像素一致 —— 老用法不受影响")

        ext = run_overlay(**common, text_in="EXTERNAL-LABEL")
        check(float(np.abs(ext - base).sum()) > 0, "接了外部文字后画面变了 —— 外部输入确实生效")

        # 与「手填同一段字」逐像素一致 → 证明外部文字走的是同一条渲染路径，
        # 不是另开一条分支（另开分支迟早和正式渲染不一致）
        bare = {k: v for k, v in common.items() if k not in ("text", "use_text")}
        typed = run_overlay(**bare, text="EXTERNAL-LABEL", text_in="")
        check(float(np.abs(ext - typed).sum()) < 1e-6,
              "外部文字与手填同一段字渲染结果逐像素一致（同一条渲染路径）")

        # use_text=False 时外部文字也不该硬画上去
        check(float(np.abs(run_overlay(**bare, use_text=False, text_in="EXTERNAL-LABEL")
                           - run_overlay(**bare, use_text=False)).sum()) < 1e-6,
              "关掉 use_text 后外部文字也不画")
    finally:
        folder_paths.get_input_directory = orig_input_dir
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    if FAILS:
        print(f"✗ {len(FAILS)} 项未通过")
        return 1
    print("✓ 按前端调用方式真跑节点：全通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
