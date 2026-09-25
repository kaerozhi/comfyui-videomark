# -*- coding: utf-8 -*-
"""
comfyui-videomark 字体解析
==========================
职责：
  1. 给出字体下拉框的候选列表 —— 系统字体（中文优先）+ 用户投放在 input/fonts 的字体；
  2. 把下拉框标签 / 自定义字体路径解析成 (字体文件路径, 字体索引)；
  3. 找不到任何可用字体时给出兜底（Pillow 内置位图字体，中文会变方块，会打印警告）。


安全约定（v1.4.2 起）
---------------------
``font_file`` 是**用户可控**的 widget —— 任何工作流都能往里塞任意字符串。
所以它一律只按「ComfyUI input 目录内的相对路径」解析：

  * 绝对路径 / 盘符 / UNC 开头  → 拒绝
  * 含 ``..`` 段的路径          → 拒绝
  * 拼出来的路径先 realpath，再用 ``commonpath`` 校验必须落在 input 目录内
    （realpath 会解开符号链接，软链同样逃不出去）

这样一来，这个参数再也不能当成「读任意文件」的入口。
想用自己的字体，把文件丢进 ``ComfyUI/input/fonts/`` —— 它会自动出现在下拉框里，
不用再手填路径。


不依赖 ComfyUI（``folder_paths`` 拿不到时退化为「只有系统字体」），可独立测试。
"""

from __future__ import annotations

import os
import re
import sys
from typing import Dict, List, Optional, Tuple

from PIL import ImageFont

# ---------------------------------------------------------------------
# 候选字体（按优先级排序）。值里的文件名在 Windows 上是大小写不敏感的，
# 所以这里写什么都行，存在即命中。
#
# 标签一律用英文：本包以英文为源语言，静态文案的中文由 locales/zh 覆盖，
# 但「下拉框的选项文本」是运行时值，locale 覆盖不到，所以在这里就得是英文。
# ---------------------------------------------------------------------
FONT_CANDIDATES: List[Tuple[str, str]] = [
    # —— 中文（简体）——
    ("Microsoft YaHei", "msyh.ttc"),
    ("Microsoft YaHei Bold", "msyhbd.ttc"),
    ("Microsoft YaHei Light", "msyhl.ttc"),
    ("SimHei", "simhei.ttf"),
    ("SimSun", "simsun.ttc"),
    ("DengXian", "Deng.ttf"),
    ("DengXian Bold", "Dengb.ttf"),
    ("KaiTi", "simkai.ttf"),
    ("FangSong", "simfang.ttf"),
    ("STKaiti", "STKAITI.TTF"),
    ("STFangsong", "STFANGSO.TTF"),
    ("STXihei", "STXIHEI.TTF"),
    # —— 中文（繁体 / 港台常用）——
    ("MingLiU", "mingliu.ttc"),
    ("DFKai-SB", "kaiu.ttf"),
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

# 认得出的字体扩展名
_FONT_EXTS = (".ttf", ".ttc", ".otf")

# 用户自定义字体的投放目录：ComfyUI input 下的这个子目录
USER_FONT_SUBDIR = "fonts"

# 兜底扫描时，哪些关键字大概率是符号字体 / 图标字体，排除掉免得下拉框被塞满
_SCAN_BLOCKLIST = (
    "symbol", "wingding", "webding", "marlett", "segmdl2", "seguiemj",
    "seguisym", "holomdl2", "emoji", "mdlicons", "freeserif", "bssym",
)

FALLBACK_LABEL = "(built-in fallback font - CJK glyphs render as boxes)"

# 测试 / 宿主注入用；None = 正常去问 folder_paths
_INPUT_DIR_OVERRIDE: Optional[str] = None


# ---------------------------------------------------------------------
# input 目录（自定义字体的合法边界）
# ---------------------------------------------------------------------

def input_directory() -> Optional[str]:
    """ComfyUI 的 input 目录。独立运行 / 测试时拿不到，返回 None。"""
    if _INPUT_DIR_OVERRIDE:
        return _INPUT_DIR_OVERRIDE
    try:
        import folder_paths  # type: ignore
    except Exception:
        return None
    try:
        d = folder_paths.get_input_directory()
    except Exception:
        return None
    return d or None


def user_font_dir() -> Optional[str]:
    """``input/fonts`` —— 用户投放自定义字体的地方。目录不存在返回 None。"""
    base = input_directory()
    if not base:
        return None
    d = os.path.join(base, USER_FONT_SUBDIR)
    return d if os.path.isdir(d) else None


def _inside(base: str, rel: str) -> Optional[str]:
    """把 ``rel`` 解析成 base 之内的真实文件路径；越界一律返回 None。"""
    parts = [p for p in re.split(r"[\\/]+", rel) if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    base_real = os.path.realpath(base)
    cand = os.path.realpath(os.path.join(base_real, *parts))
    try:
        if os.path.commonpath([cand, base_real]) != base_real:
            return None
    except ValueError:                      # 不同盘符，commonpath 会抛
        return None
    return cand if os.path.isfile(cand) else None


def custom_font_path(font_file: str) -> Optional[str]:
    """
    把 ``font_file`` 解析成 input 目录内的字体文件路径。

    接受：``fonts/my.ttf``、``fonts\\my.ttf``（相对 input 目录）
    拒绝：绝对路径（``D:/x.ttf``、``\\\\host\\share``、``/usr/x.ttf``）、
          含 ``..`` 的路径、以及 realpath 后落在 input 之外的一切路径。
    """
    name = (font_file or "").strip().strip('"').strip("'")
    if not name:
        return None
    # 绝对路径 / 盘符 / UNC —— 注意 POSIX 上 isabs("D:/x") 为假，所以 splitdrive 也得查
    if os.path.isabs(name) or os.path.splitdrive(name)[0] or name[0] in ("\\", "/"):
        return None
    if any(p == ".." for p in re.split(r"[\\/]+", name)):
        return None
    base = input_directory()
    if not base:
        return None
    return _inside(base, name)


# ---------------------------------------------------------------------
# 下拉框候选
# ---------------------------------------------------------------------

def font_search_dirs() -> List[str]:
    """返回本机字体目录（系统级 + 用户级）。

    注意：这里**刻意不读取环境变量**。Comfy Registry 的安全扫描
    （yara 规则 ``$env_read2`` / T1574.007 Environment Variable Hijacking）
    会把「读环境变量」的调用判为 ``python_environment_manipulation`` ——
    哪怕只是用来定位系统目录，也会把整个版本标成 Flagged。
    （此说明刻意不写出该调用的原文：yara 是纯文本匹配，注释一样会命中。）
    等价写法：
      * 系统字体固定在 ``C:\\Windows\\Fonts``（Windows 装在非 C 盘属罕见场景）
      * 用户级字体在 ``%USERPROFILE%\\AppData\\Local``，用 ``expanduser("~")`` 取
    返回前统一经 ``os.path.isdir`` 过滤，所以多给一个不存在的目录是安全的。
    """
    dirs: List[str] = []
    dirs.append(os.path.join(r"C:\Windows", "Fonts"))
    local = os.path.join(os.path.expanduser("~"), "AppData", "Local")
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


def _scan_user_fonts() -> Dict[str, str]:
    """扫描 ``input/fonts``（含子目录），标签取相对路径去掉扩展名。"""
    base = user_font_dir()
    found: Dict[str, str] = {}
    if not base:
        return found
    for root, _dirs, files in os.walk(base):
        for fn in sorted(files):
            if not fn.lower().endswith(_FONT_EXTS):
                continue
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, base).replace("\\", "/")
            found.setdefault(os.path.splitext(rel)[0], full)
    return found


def discover_fonts() -> Dict[str, str]:
    """
    返回 {下拉框显示名: 字体绝对路径}。

    顺序：系统候选表 → 用户投放（input/fonts）→ 万一两者皆空才做目录兜底扫描。
    用户字体排在系统候选之后，这样默认字体不会被随手丢进来的字体顶掉。
    """
    found: Dict[str, str] = {}
    for label, filename in FONT_CANDIDATES:
        p = _lookup_in_dirs(filename)
        if p:
            found[label] = p

    for label, p in _scan_user_fonts().items():
        found.setdefault(label, p)

    if found:
        return found

    # 兜底：扫描系统字体目录，排除明显的符号字体
    for d in font_search_dirs():
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for name in names:
            if not name.lower().endswith(_FONT_EXTS):
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

    - font_file 解析成功 → 优先用它（只能是 input 目录内的相对路径，见模块顶部的安全约定）；
    - 否则查下拉表；
    - 都拿不到 → (None, 0)，调用方需走兜底字体。
    """
    custom = custom_font_path(font_file)
    if custom:
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
