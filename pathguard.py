# -*- coding: utf-8 -*-
"""
comfyui-videomark 路径围栏
==========================
本包有两个「用户可控的文件路径」入口，一并由这里收口：

  * ``font_file`` —— 自定义字体文件
  * ``logo_file`` —— 面板上传的 logo 图

两者都是 widget 值：**任何工作流都能往里塞任意字符串**。所以一律只按
「ComfyUI input 目录内的相对路径」解析，越界直接拒绝：

  * 绝对路径 / 盘符 / UNC 开头（``C:/x``、``\\\\host\\share``、``/usr/x``）→ 拒绝
  * 含 ``..`` 段的路径                                                   → 拒绝
  * 拼出来的路径先 ``realpath``，再用 ``commonpath`` 校验必须落在 base 之内
    → 符号链接与 NTFS 目录联接（junction）同样逃不出去

为什么自己判、不信任 ``folder_paths``
-------------------------------------
``folder_paths.get_annotated_filepath`` 的越界校验是**较新版本**才加进去的；
``get_full_path`` 则只依赖 ``os.path.relpath`` 的归一化副作用（跨平台行为微妙）。
把判定放在本包内，行为在任何 ComfyUI 版本上一致，也不会随宿主实现变动而失效。
换句话说：围栏不能外包给外部库，否则「升级 / 降级宿主」就等于「换了一套安全语义」。

不依赖 ComfyUI，可独立测试。
"""

from __future__ import annotations

import os
import re
from typing import List, Optional

_SEP_RE = re.compile(r"[\\/]+")


def is_absolute(name: str) -> bool:
    """绝对路径 / 带盘符 / 以分隔符开头（含 UNC）都算绝对。"""
    if not name:
        return False
    if os.path.isabs(name):
        return True
    # POSIX 上 isabs("D:/x") 为假，所以盘符要单独看
    if os.path.splitdrive(name)[0]:
        return True
    return name[0] in ("\\", "/")


def segments(name: str) -> List[str]:
    """按两种分隔符切分，丢掉空段与 ``.``；``..`` 原样保留，交给调用方判断。"""
    return [p for p in _SEP_RE.split(name) if p not in ("", ".")]


def has_parent_segment(name: str) -> bool:
    """路径里是否含 ``..`` 段（两种分隔符都算）。"""
    return any(p == ".." for p in segments(name))


def inside(base: str, rel: str) -> Optional[str]:
    """
    把 ``rel`` 解析成 ``base`` 之内的真实文件路径；越界或不存在的文件返回 None。

    这是本包唯一的路径准入点 —— 两个 widget 入口都走它。
    """
    if is_absolute(rel) or has_parent_segment(rel):
        return None
    parts = segments(rel)
    if not parts:
        return None

    base_real = os.path.realpath(base)
    # realpath 会解开符号链接 / 目录联接，所以软链指向外面时这里就露馅了
    cand = os.path.realpath(os.path.join(base_real, *parts))
    try:
        if os.path.commonpath([cand, base_real]) != base_real:
            return None
    except ValueError:
        # 不同盘符时 commonpath 会抛 ValueError；内嵌空字节也会走到这里
        return None
    return cand if os.path.isfile(cand) else None
