# -*- coding: utf-8 -*-
"""
logo 文件读取
=============
可视化面板上传的 PNG logo 会落到 ComfyUI 的 input 目录，节点只记文件名
（`logo_file`），真正渲染时再由这里把文件读成 RGBA 数组。

为什么不走 `LoadImage` 节点连线？
  - 面板里「上传 logo」应该一步到位，不该要求用户再拖一个 LoadImage 手动连线；
  - 连线入口仍然保留（`logo` / `logo_mask`），显式接线时优先用连线的图，
    这样需要做动态 logo（比如跟着模型输出变）的流程也不受限。

安全：只允许解析进 ComfyUI input 目录下的路径。
`folder_paths.get_annotated_filepath` 与 `get_full_path` 自带越界校验，
所以外部传 `../../windows/system32/...` 是读不到的。
"""

from __future__ import annotations

import os
from typing import Optional

import numpy as np


def input_dir() -> Optional[str]:
    """ComfyUI 的 input 目录；离线（没有 folder_paths）时返回 None。"""
    try:
        import folder_paths
        getter = getattr(folder_paths, "get_input_directory", None)
        if callable(getter):
            return getter()
    except Exception:                                          # noqa: BLE001
        pass
    return None


def resolve_path(name: str) -> Optional[str]:
    """
    把面板给的文件名解析成实际存在的绝对路径；解析不出来返回 None。

    三种写法都接受：`logo.png` / `sub/logo.png` / `[input]logo.png`。
    """
    name = (name or "").strip().replace("\\", "/")
    if not name:
        return None
    # 面板只应传相对名；挡掉绝对路径与非 input 前缀，少一层风险
    if os.path.isabs(name):
        return _offline_abs(name)
    if name.startswith("[") and not name.startswith("[input]"):
        return None

    try:
        import folder_paths
    except Exception:                                          # noqa: BLE001
        return _offline_relative(name)

    try:
        p = folder_paths.get_annotated_filepath(name)
        if p and os.path.isfile(p):
            return p
    except Exception:                                          # noqa: BLE001
        pass
    try:
        p = folder_paths.get_full_path("input", name)
        if p and os.path.isfile(p):
            return p
    except Exception:                                          # noqa: BLE001
        pass
    return None


def _offline_abs(name: str) -> Optional[str]:
    """没有 ComfyUI 时（离线自测）才允许绝对路径，方便跑脚本验证。"""
    try:
        import folder_paths  # noqa: F401
        return None                                        # 有 ComfyUI 就不放行
    except Exception:                                      # noqa: BLE001
        return name if os.path.isfile(name) else None


def _offline_relative(name: str) -> Optional[str]:
    p = os.path.abspath(name)
    return p if os.path.isfile(p) else None


def load_logo_rgba(name: str) -> Optional[np.ndarray]:
    """
    读成 float32 RGBA（0..1）。读不到返回 None，由调用方决定降级方式。

    PNG 自带的 alpha 会被完整保留 —— 这正是用户要的「带 alpha 通道的 png logo」。
    非 RGBA 的图（JPG 等）补成不透明，不会报错。
    """
    path = resolve_path(name)
    if not path:
        return None
    try:
        from PIL import Image
        with Image.open(path) as im:
            rgba = im.convert("RGBA")
            arr = np.asarray(rgba, dtype=np.uint8).astype(np.float32) / 255.0
    except Exception:                                          # noqa: BLE001
        return None
    if arr.ndim != 3 or arr.shape[2] != 4 or arr.shape[0] < 2 or arr.shape[1] < 2:
        return None
    return arr
