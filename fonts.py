# -*- coding: utf-8 -*-
"""
comfyui-videomark 字体解析
==========================
职责：
  1. 扫描系统字体目录，挑出「中文优先」的候选字体，供节点下拉框使用；
  2. 把下拉框的友好名 / 用户自定义路径解析成 (字体文件路径, 字体索引)；
  3. 找不到任何可用字体时给出兜底（Pillow 内置位图字体，中文会变方块，会打印警告）。

不依赖 ComfyUI，可独立测试。
"""

from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional, Tuple

from PIL import ImageFont

# ---------------------------------------------------------------------
# 候选字体（按优先级排序）。值里的文件名在 Windows 上是大小写不敏感的，
# 所以这里写什么都行，存在即命中。
# ---------------------------------------------------------------------
FONT_CANDIDATES: List[Tuple[str, str]] = [
    # —— 中文（简体）——
    ("微软雅黑", "msyh.ttc"),
    ("微软雅黑 粗体", "msyhbd.ttc"),
    ("微软雅黑 细体", "msyhl.ttc"),
    ("黑体", "simhei.ttf"),
    ("宋体", "simsun.ttc"),
    ("等线", "Deng.ttf"),
    ("等线 粗体", "Dengb.ttf"),
    ("楷体", "simkai.ttf"),
    ("仿宋", "simfang.ttf"),
    ("华文楷体", "STKAITI.TTF"),
    ("华文仿宋", "STFANGSO.TTF"),
    ("华文细黑", "STXIHEI.TTF"),
    # —— 中文（繁体 / 港台常用）——
    ("新细明体", "mingliu.ttc"),
    ("标楷体", "kaiu.ttf"),
    # —— 西文，做 logo / 片尾字幕常用 ——
    ("Arial", "arial.ttf"),
    ("Arial Bold", "arialbd.ttf"),
    ("Impact", "impact.ttf"),
    ("Times New Roman", "times.ttf"),
    ("Georgia", "georgia.ttf"),
    ("Verdana", "verdana.ttf"),
    ("Tahoma", "tahoma.ttf"),
    ("Consolas", "consola.ttf"),
    ("Courier New", "cour.ttf"),
]

# 兜底扫描时，哪些关键字大概率是符号字体 / 图标字体，排除掉免得下拉框被塞满
_SCAN_BLOCKLIST = (
    "symbol", "wingding", "webding", "marlett", "segmdl2", "seguiemj",
    "seguisym", "holomdl2", "emoji", "mdlicons", "freeserif", "bssym",
)

FALLBACK_LABEL = "（内置兜底字体·中文会显示为方块）"


def font_search_dirs() -> List[str]:
    """返回本机字体目录（系统级 + 用户级）。"""
    dirs: List[str] = []
    windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows"
    dirs.append(os.path.join(windir, "Fonts"))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        dirs.append(os.path.join(local, "Microsoft", "Windows", "Fonts"))
    # 非 Windows（理论上用不到，留着做兼容）
    if sys.platform == "darwin":
        dirs += ["/System/Library/Fonts", "/Library/Fonts", os.path.expanduser("~/Library/Fonts")]
    elif sys.platform.startswith("linux"):
        dirs += ["/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts")]
    return [d for d in dirs if os.path.isdir(d)]


def _lookup_in_dirs(filename: str) -> Optional[str]:
    """在字体目录中按文件名找字体（Windows 文件系统大小写不敏感，直接 exists 即可）。"""
    for d in font_search_dirs():
        p = os.path.join(d, filename)
        if os.path.isfile(p):
            return p
    # 部分系统文件名大小写敏感，做一次不区分大小写的兜底遍历
    low = filename.lower()
    for d in font_search_dirs():
        try:
            for name in os.listdir(d):
                if name.lower() == low:
                    return os.path.join(d, name)
        except OSError:
            continue
    return None


def discover_fonts() -> Dict[str, str]:
    """
    返回 {下拉框显示名: 字体绝对路径}。
    优先命中 FONT_CANDIDATES；如果一个都没命中，则兜底扫描目录（最多 40 个）。
    """
    found: Dict[str, str] = {}
    for label, filename in FONT_CANDIDATES:
        p = _lookup_in_dirs(filename)
        if p:
            found[label] = p
    if found:
        return found

    # 兜底：扫描目录，排除明显的符号字体
    exts = (".ttf", ".ttc", ".otf")
    for d in font_search_dirs():
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for name in names:
            if not name.lower().endswith(exts):
                continue
            if any(bad in name.lower() for bad in _SCAN_BLOCKLIST):
                continue
            label = os.path.splitext(name)[0]
            if label in found:
                continue
            found[label] = os.path.join(d, name)
            if len(found) >= 40:
                return found
    return found


# 模块级缓存：ComfyUI 启动时算一次即可
_FONT_TABLE: Optional[Dict[str, str]] = None


def get_font_table() -> Dict[str, str]:
    global _FONT_TABLE
    if _FONT_TABLE is None:
        _FONT_TABLE = discover_fonts()
    return _FONT_TABLE


def default_font_label() -> str:
    """下拉框默认选项：第一个可用字体（候选表已按中文优先排序）。"""
    table = get_font_table()
    if table:
        return next(iter(table))
    return FALLBACK_LABEL


def font_choices() -> List[str]:
    """下拉框选项列表（永远至少有一项，保证默认值合法）。"""
    table = get_font_table()
    if not table:
        return [FALLBACK_LABEL]
    return list(table.keys())


def resolve_font(font_label: str, font_file: str = "", font_index: int = 0
                 ) -> Tuple[Optional[str], int]:
    """
    把用户选择解析成 (字体路径, 索引)。

    - font_file 非空且文件存在 → 优先用它（允许用户填任意字体绝对路径，比如自己的手写体）；
    - 否则查下拉表；
    - 都拿不到 → (None, 0)，调用方需走兜底字体。
    """
    custom = (font_file or "").strip().strip('"').strip("'")
    if custom:
        custom = os.path.expandvars(os.path.expanduser(custom))
        if os.path.isfile(custom):
            return custom, int(font_index)
    table = get_font_table()
    path = table.get(font_label or "")
    if path:
        return path, int(font_index)
    if table:
        # 传了个不认识的标签，退回第一个可用字体，别让用户白跑一趟
        return next(iter(table.values())), int(font_index)
    return None, int(font_index)


def load_font(path: Optional[str], size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    """加载字体；失败或没有字体时返回 Pillow 内置字体（中文会变方块）。"""
    size = max(4, int(size))
    if path:
        try:
            return ImageFont.truetype(path, size, index=int(index), layout_engine=ImageFont.Layout.BASIC)
        except Exception:
            try:
                return ImageFont.truetype(path, size, index=int(index))
            except Exception:
                pass
    return load_default_font(size)


def load_default_font(size: int) -> ImageFont.ImageFont:
    """Pillow 内置字体，新版支持 size 参数；旧版只能拿到固定小字号。"""
    try:
        return ImageFont.load_default(size=max(4, int(size)))
    except TypeError:
        return ImageFont.load_default()
