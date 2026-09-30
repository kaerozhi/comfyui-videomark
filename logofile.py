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

安全约定（v1.4.3 起）
---------------------
``logo_file`` 同样是**用户可控**的 widget —— 任何工作流都能往里塞任意字符串。
所以它一律只按「ComfyUI input 目录内的相对路径」解析：绝对路径 / 盘符 / UNC、
含 ``..`` 的路径一律拒绝，realpath + commonpath 校验必须落在 input 目录内。

判定本身在 :mod:`pathguard`（``font_file`` 走的是同一套），**不再依赖
``folder_paths`` 的校验**：那层围栏是较新版本才补上的，而 ``get_full_path``
只靠 ``os.path.relpath`` 的归一化副作用 —— 把安全语义外包给宿主，等于随
ComfyUI 版本升降级而变，这正是这里要避免的。

不依赖 ComfyUI（拿不到 ``folder_paths`` 时一律返回 None），可独立测试。
"""

from __future__ import annotations

from typing import Optional

import numpy as np

try:                       # 包内相对导入（ComfyUI 加载时）
    from . import pathguard  # type: ignore[import-not-found]
except ImportError:        # 独立运行 / 自测时按平铺模块导入
    import pathguard

# ComfyUI 的注解写法是**后缀**加一个空格：`logo.png [input]`。
# 面板不使用它（面板只写纯相对名），但手工搭的工作流可能带，收下并归一化。
_ANNOTATION_SUFFIX = "[input]"


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
    把面板给的文件名解析成实际存在的绝对路径；解析不出来（含越界）返回 None。

    接受：``logo.png`` / ``sub/logo.png`` / ``logo.png [input]``（相对 input 目录）
    拒绝：绝对路径、盘符、UNC、含 ``..`` 的路径，以及 realpath 后落在 input 之外
          的一切路径（符号链接 / 目录联接同样拦下）。
    """
    name = (name or "").strip().strip('"').strip("'").replace("\\", "/")
    if name.endswith(_ANNOTATION_SUFFIX):
        name = name[: -len(_ANNOTATION_SUFFIX)].strip()
    if not name:
        return None
    base = input_dir()
    if not base:
        return None
    return pathguard.inside(base, name)


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
