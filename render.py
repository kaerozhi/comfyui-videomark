# -*- coding: utf-8 -*-
"""
comfyui-videomark 渲染核心
==========================
纯 numpy + Pillow 实现，**不依赖 torch / ComfyUI**，方便离线自测（见 tools/selftest.py）。

数据约定
--------
- 帧批次：float32 的 np.ndarray，形状 [B, H, W, 3]（也容忍 4 通道），取值 0..1；
- 图章（stamp）：float32 的 np.ndarray，形状 [h, w, 4]，RGB 已预乘好、A 为 0..1。
  图章只在批处理开始时渲染一次，之后每帧只做一次局部 alpha 合成，帧数再多也不掉速。

四种水印模式（对应节点里的 mode）
--------------------------------
  corner   固定贴在四角之一，按 margin 留出安全边距；
  center   画面正中，通常配低透明度（0.15~0.25）；
  floating 在安全区内缓慢游走 / 周期跳变，最防盗；
  tile     全画面平铺并倾斜，最难裁掉 / 抹除。
"""

from __future__ import annotations

import math
import random
from typing import List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

try:                                              # 作为包被 ComfyUI 加载时
    from .fonts import load_font, default_font_label, resolve_font
except ImportError:                               # 直接当脚本跑（离线自测）
    from fonts import load_font, default_font_label, resolve_font  # type: ignore[no-redef]


_DEFAULT_FONT_PATH: list = []


def default_font_path() -> Optional[str]:
    """
    全局默认中文字体。调用方没指定字体时用它兜底。

    没有这层兜底的话，font_path=None 会一路掉到 Pillow 内置位图字体上，
    中文直接渲染成方块 —— 这种坑不该让调用方去踩。
    """
    if not _DEFAULT_FONT_PATH:
        path = None
        try:
            path, _ = resolve_font(default_font_label(), "")
        except Exception:                          # noqa: BLE001
            path = None
        _DEFAULT_FONT_PATH.append(path)
    return _DEFAULT_FONT_PATH[0]

# =====================================================================
# 常量
# =====================================================================

MODES = ["corner", "center", "floating", "tile"]
POSITIONS = ["top_left", "top_right", "bottom_left", "bottom_right"]
FLOAT_PATHS = ["diagonal", "horizontal", "vertical", "circle", "random"]
LAYOUTS = ["vertical", "horizontal"]

# 样式预设：(描边开关, 投影开关, 描边不透明度, 投影不透明度)
#   预设是「一键整套参数」，连强度一起定 —— 否则换风格只是换了个开关，
#   用户还得自己猜该配多少透明度。想逐项手调就把 style 切成 manual。
#
#   注意：深色投影在夜景 / 黑幕上是隐形的，所以默认那档不能只靠投影，
#   描边也必须留着（靠 stroke_opacity 压淡，而不是关掉）。
STYLES = ["soft", "plain", "outline", "outline_shadow", "manual"]
_STYLE_PRESETS: dict[str, Tuple[bool, bool, float, float]] = {
    "soft":           (True,  True,  0.55, 0.40),   # 默认：都开但都淡 —— 明暗背景都可读，又不抢画面
    "plain":          (False, False, 0.00, 0.00),   # 纯净：什么都不加，最不干扰画面
    "outline":        (True,  False, 1.00, 0.00),   # 硬描边：画面明暗变化剧烈时用
    "outline_shadow": (True,  True,  1.00, 0.60),   # 描边 + 投影：最强，几乎任何背景都看得清
}


def resolve_style(style: str, use_stroke: bool, use_shadow: bool,
                  stroke_opacity: float = 1.0,
                  shadow_opacity: float = 0.5) -> Tuple[bool, bool, float, float]:
    """
    把「样式预设」和「四个显式控件」合成最终参数。

    返回 (描边开关, 投影开关, 描边不透明度, 投影不透明度)。

    预设接管全部四项，manual（或任何未知值）则完全听控件的 ——
    这样"一键换风格"和"逐项微调"不会互相打架，manual 是唯一读控件的档位。
    """
    key = str(style or "").strip().lower()
    if key in _STYLE_PRESETS:
        return _STYLE_PRESETS[key]
    return bool(use_stroke), bool(use_shadow), float(stroke_opacity), float(shadow_opacity)


def style_presets() -> dict:
    """
    预设表的公开读取口（给前端 meta 接口用）。

    存在的意义：可视化面板需要知道「每个预设对应哪四个数值」，好把滑块摆到正确位置。
    如果让前端自己抄一份表，后端改预设时前端就会悄悄跑偏 —— 上一轮已经吃过一次
    「样张和默认值脱节」的亏，这次直接从后端喂过去。
    """
    return {
        k: {"use_stroke": bool(v[0]), "use_shadow": bool(v[1]),
            "stroke_opacity": float(v[2]), "shadow_opacity": float(v[3])}
        for k, v in _STYLE_PRESETS.items()
    }

# 四角 / 正中对齐系数：(水平比例, 垂直比例)
_ANCHORS: dict[str, Tuple[float, float]] = {
    "top_left": (0.0, 0.0),
    "top_right": (1.0, 0.0),
    "bottom_left": (0.0, 1.0),
    "bottom_right": (1.0, 1.0),
    "center": (0.5, 0.5),
}

_NAMED_COLORS = {
    "black": (0, 0, 0),
    "white": (255, 255, 255),
    "red": (255, 0, 0),
    "green": (0, 128, 0),
    "lime": (0, 255, 0),
    "blue": (0, 0, 255),
    "gray": (128, 128, 128),
    "grey": (128, 128, 128),
    "silver": (192, 192, 192),
    "yellow": (255, 255, 0),
    "cyan": (0, 255, 255),
    "aqua": (0, 255, 255),
    "magenta": (255, 0, 255),
    "fuchsia": (255, 0, 255),
    "orange": (255, 165, 0),
    "purple": (128, 0, 128),
}


# =====================================================================
# 颜色
# =====================================================================

def parse_color(value, default: Tuple[int, int, int] = (255, 255, 255)) -> Tuple[int, int, int]:
    """
    支持 "#RRGGBB" / "#RGB" / "RRGGBB" / "r,g,b" / 颜色名 / 三元组。
    解析不出来就回退 default，不抛异常（水印节点不该因为写错颜色而中断整个工作流）。
    """
    if isinstance(value, (tuple, list)) and len(value) >= 3:
        return tuple(int(max(0, min(255, v))) for v in value[:3])  # type: ignore[return-value]
    if not isinstance(value, str):
        return default
    s = value.strip()
    if not s:
        return default
    low = s.lower()
    if low in _NAMED_COLORS:
        return _NAMED_COLORS[low]
    if "," in s:
        parts = [p.strip() for p in s.split(",")]
        if len(parts) >= 3:
            try:
                return tuple(int(max(0, min(255, float(p)))) for p in parts[:3])  # type: ignore[return-value]
            except ValueError:
                return default
    h = s[1:] if s.startswith("#") else s
    if len(h) == 3 and all(c in "0123456789abcdefABCDEF" for c in h):
        return tuple(int(c * 2, 16) for c in h)  # type: ignore[return-value]
    if len(h) == 6 and all(c in "0123456789abcdefABCDEF" for c in h):
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    return default


# =====================================================================
# 基础工具
# =====================================================================

def _triangle(phase: float) -> float:
    """三角波：把 phase 循环映射到 0→1→0，用于「匀速来回」的运动，端点不减速。"""
    p = phase % 1.0
    return 1.0 - abs(2.0 * p - 1.0)


def _to_float01(arr: np.ndarray) -> np.ndarray:
    a = np.asarray(arr)
    if a.dtype == np.uint8:
        return a.astype(np.float32) / 255.0
    a = a.astype(np.float32, copy=False)
    if a.size and float(a.max()) > 1.5:      # 0..255 的浮点图
        a = a / 255.0
    return a


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else (hi if v > hi else v)


# =====================================================================
# logo → RGBA 数组
# =====================================================================

def logo_to_rgba(logo: np.ndarray, mask: Optional[np.ndarray] = None) -> np.ndarray:
    """
    把 logo 图像转成 float32 [h, w, 4]（0..1）。

    alpha 的取值优先级：
      1) 显式传入的 mask（单通道，ComfyUI 的 LoadImage 会把 PNG 透明通道作为 MASK 输出）；
      2) logo 自带第 4 通道（RGBA）；
      3) 都没有 → 完全不透明。
    """
    arr = _to_float01(logo)
    if arr.ndim == 2:
        arr = arr[:, :, None]
    h, w = arr.shape[0], arr.shape[1]
    rgb = arr[:, :, :3]
    if rgb.shape[2] == 1:                       # 灰度图
        rgb = np.repeat(rgb, 3, axis=2)

    alpha = None
    if mask is not None:
        m = _to_float01(mask)
        if m.ndim == 3:
            m = m[:, :, 0]
        if m.shape[:2] != (h, w):
            m = np.asarray(
                Image.fromarray((np.clip(m, 0, 1) * 255).astype(np.uint8)).resize((w, h), Image.LANCZOS)
            ).astype(np.float32) / 255.0
        alpha = m
    elif arr.shape[2] >= 4:
        alpha = arr[:, :, 3]

    if alpha is None:
        alpha = np.ones((h, w), dtype=np.float32)

    out = np.empty((h, w, 4), dtype=np.float32)
    out[:, :, :3] = np.clip(rgb, 0.0, 1.0)
    out[:, :, 3] = np.clip(alpha, 0.0, 1.0)
    return out


# =====================================================================
# 文字 / 图章渲染
# =====================================================================

def _text_size(text: str, font: ImageFont.FreeTypeFont, spacing: int, stroke_width: int
               ) -> Tuple[int, int, Tuple[float, float, float, float]]:
    """测量多行文字的包围盒，返回 (w, h, bbox)。"""
    probe = Image.new("RGBA", (4, 4))
    draw = ImageDraw.Draw(probe)
    try:
        bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=spacing,
                                       stroke_width=stroke_width)
    except AttributeError:                       # 极老版本 Pillow
        bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    w = max(1, int(math.ceil(bbox[2] - bbox[0])))
    h = max(1, int(math.ceil(bbox[3] - bbox[1])))
    return w, h, bbox


def render_text_rgba(text: str, font_path: Optional[str], target_w: int, color: Tuple[int, int, int],
                     stroke_width: int = 0, stroke_color: Tuple[int, int, int] = (0, 0, 0),
                     spacing_ratio: float = 0.30, font_index: int = 0,
                     max_size: int = 4000, stroke_opacity: float = 1.0) -> np.ndarray:
    """
    把文字渲染成 RGBA，**自动把字号缩放到指定的目标宽度**（不用用户去猜字号）。

    做法：先用 100px 试探一次，按实测宽度等比推出字号，再用实际字号复测微调，
    这样「水印宽度 = 画面宽度的 X%」是准的，换分辨率也不用改参数。

    spacing_ratio：行距 = 字号 × 该比例。必须随字号缩放 —— 固定像素的行距
    在字号被放大后会让两行挤在一起。

    stroke_opacity：描边自身的不透明度。描边是实心一圈，满不透明时非常显眼；
    压到 0.5~0.7 既保留「把字从杂背景里托出来」的作用，又不会在画面上糊一圈黑。
    实现上描边与文字分两层渲染，只给描边层降 alpha，文字本身保持满不透明。
    """
    text = text if text else ""
    if not text.strip():
        return np.zeros((1, 1, 4), dtype=np.float32)

    font_path = font_path or default_font_path()      # 别掉到无中文的内置位图字体上

    def _spacing(size: int) -> int:
        return max(1, int(round(size * float(spacing_ratio))))

    size = 100
    font = load_font(font_path, size, font_index)
    w, _, _ = _text_size(text, font, _spacing(size), stroke_width)
    if w > 0:
        size = int(round(size * float(target_w) / float(w)))
    # 复测一次，修正 hinting 带来的非线性
    for _ in range(2):
        size = max(4, min(max_size, size))
        font = load_font(font_path, size, font_index)
        w, _, _ = _text_size(text, font, _spacing(size), stroke_width)
        if w <= 0 or abs(w - target_w) <= max(1, target_w * 0.02):
            break
        size = int(round(size * float(target_w) / float(w)))
    size = max(4, min(max_size, size))
    font = load_font(font_path, size, font_index)
    spacing = _spacing(size)

    tw, th, bbox = _text_size(text, font, spacing, stroke_width)
    sw = max(0, int(stroke_width))
    pad = sw + 4
    canvas = (tw + pad * 2, th + pad * 2)
    origin = (pad - bbox[0], pad - bbox[1])
    fill_rgba = (int(color[0]), int(color[1]), int(color[2]), 255)
    stroke_rgba = (int(stroke_color[0]), int(stroke_color[1]), int(stroke_color[2]), 255)
    so = float(_clamp(stroke_opacity, 0.0, 1.0))

    def _flat() -> Image.Image:
        img = Image.new("RGBA", canvas, (0, 0, 0, 0))
        ImageDraw.Draw(img).multiline_text(origin, text, font=font, fill=fill_rgba,
                                           spacing=spacing, align="center")
        return img

    if sw <= 0:
        return _to_float01(np.asarray(_flat()))

    if so >= 0.999:                                   # 常规满不透明描边，一次画完
        img = Image.new("RGBA", canvas, (0, 0, 0, 0))
        ImageDraw.Draw(img).multiline_text(
            origin, text, font=font, fill=fill_rgba, spacing=spacing, align="center",
            stroke_width=sw, stroke_fill=stroke_rgba)
        return _to_float01(np.asarray(img))

    # 半透明描边：描边层单独降 alpha，再把文字原样压回去（文字不能被削弱）
    under = Image.new("RGBA", canvas, (0, 0, 0, 0))
    if so > 0.0:
        ImageDraw.Draw(under).multiline_text(
            origin, text, font=font, fill=(0, 0, 0, 0), spacing=spacing, align="center",
            stroke_width=sw, stroke_fill=stroke_rgba)
        a = np.asarray(under.getchannel("A"), dtype=np.float32) * so
        under.putalpha(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), mode="L"))
    return _to_float01(np.asarray(Image.alpha_composite(under, _flat())))


def resize_rgba(stamp: np.ndarray, target_w: int) -> np.ndarray:
    """等比缩放图章到指定宽度（LANCZOS 会作用到 alpha，边缘依然平滑）。"""
    h, w = stamp.shape[:2]
    target_w = max(1, int(target_w))
    if w <= 0 or target_w == w:
        return stamp
    target_h = max(1, int(round(h * target_w / float(w))))
    img = Image.fromarray((np.clip(stamp, 0, 1) * 255).astype(np.uint8), mode="RGBA")
    img = img.resize((target_w, target_h), Image.LANCZOS)
    return _to_float01(np.asarray(img))


def rotate_stamp(stamp: np.ndarray, angle: float) -> np.ndarray:
    """旋转图章（expand=True 保证不被裁切）。"""
    if abs(float(angle)) < 0.01:
        return stamp
    img = Image.fromarray((np.clip(stamp, 0, 1) * 255).astype(np.uint8), mode="RGBA")
    img = img.rotate(float(angle), expand=True, resample=Image.BICUBIC)
    return _to_float01(np.asarray(img))


def trim_rgba(stamp: np.ndarray, threshold: float = 1.0 / 255.0) -> np.ndarray:
    """
    裁掉四周完全透明的边。

    为什么必须做：渲染文字/旋转时会留出透明的安全边，如果不清掉，
    「水印宽度 = 画面宽度 X%」和「margin = N 像素」都会带上这几像素的暗账，
    贴边位置看起来就会比设定的更靠里。裁掉后两个参数都是精确的。
    """
    if stamp.ndim != 3 or stamp.shape[2] != 4 or stamp.size == 0:
        return stamp
    a = stamp[:, :, 3]
    rows = np.where(a.max(axis=1) > threshold)[0]
    cols = np.where(a.max(axis=0) > threshold)[0]
    if rows.size == 0 or cols.size == 0:            # 整张全透明，保持原样
        return stamp
    y0, y1 = int(rows[0]), int(rows[-1]) + 1
    x0, x1 = int(cols[0]), int(cols[-1]) + 1
    if (y0, y1, x0, x1) == (0, stamp.shape[0], 0, stamp.shape[1]):
        return stamp
    return np.ascontiguousarray(stamp[y0:y1, x0:x1])


def add_shadow(stamp: np.ndarray, *, color: Tuple[int, int, int] = (0, 0, 0),
               offset_x: int = 5, offset_y: int = 5, blur: float = 8.0,
               opacity: float = 0.5) -> np.ndarray:
    """
    给图章加柔和投影：取 alpha 剪影 → 高斯模糊 → 垫在图章底下。

    为什么投影比描边好：描边是沿字形外围描一圈**实心**的边，
    在明暗变化大的镜头上，那一圈黑边会比字本身还显眼；
    投影只是把轮廓往外晕开一点点，暗背景上照样分得出边界，
    却不会在画面上留下硬邦邦的黑圈 —— 这就是「降低可见度但保住可读性」的正解。

    返回扩展边距后的新图章（投影本身也会占位，贴边位置照样由 margin 精确约束）。
    """
    if stamp.ndim != 3 or stamp.shape[2] != 4 or stamp.size == 0:
        return stamp
    op = float(_clamp(opacity, 0.0, 1.0))
    bl = max(0.0, float(blur))
    ox, oy = int(offset_x), int(offset_y)
    if op <= 0.0 or (bl <= 0.0 and ox == 0 and oy == 0):
        return stamp

    h, w = stamp.shape[:2]
    pad = int(math.ceil(bl * 3.0)) + 2
    mx = pad + abs(ox)
    my = pad + abs(oy)
    size = (w + mx * 2, h + my * 2)

    src = Image.fromarray((np.clip(stamp, 0, 1) * 255).astype(np.uint8), mode="RGBA")

    # 剪影层：把 alpha 平移到「原图 + 偏移」的位置再模糊
    silhouette = Image.new("L", size, 0)
    silhouette.paste(src.getchannel("A"), (mx + ox, my + oy))
    silhouette = silhouette.filter(ImageFilter.GaussianBlur(bl))
    if op < 0.999:
        a = np.asarray(silhouette, dtype=np.float32) * op
        silhouette = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), mode="L")

    shadow = Image.new("RGBA", size, (int(color[0]), int(color[1]), int(color[2]), 0))
    shadow.putalpha(silhouette)

    top = Image.new("RGBA", size, (0, 0, 0, 0))
    top.paste(src, (mx, my))
    return _to_float01(np.asarray(Image.alpha_composite(shadow, top)))


def hstack_rgba(blocks: Sequence[np.ndarray], gap: int = 0) -> np.ndarray:
    """水平拼接若干 RGBA 图块（垂直居中）。"""
    blocks = [b for b in blocks if b is not None and b.size]
    if not blocks:
        return np.zeros((1, 1, 4), dtype=np.float32)
    h = max(b.shape[0] for b in blocks)
    w = sum(b.shape[1] for b in blocks) + gap * (len(blocks) - 1)
    out = np.zeros((h, w, 4), dtype=np.float32)
    x = 0
    for b in blocks:
        y = (h - b.shape[0]) // 2
        out[y:y + b.shape[0], x:x + b.shape[1]] = b
        x += b.shape[1] + gap
    return out


def vstack_rgba(blocks: Sequence[np.ndarray], gap: int = 0) -> np.ndarray:
    """垂直拼接若干 RGBA 图块（水平居中）。"""
    blocks = [b for b in blocks if b is not None and b.size]
    if not blocks:
        return np.zeros((1, 1, 4), dtype=np.float32)
    w = max(b.shape[1] for b in blocks)
    h = sum(b.shape[0] for b in blocks) + gap * (len(blocks) - 1)
    out = np.zeros((h, w, 4), dtype=np.float32)
    y = 0
    for b in blocks:
        x = (w - b.shape[1]) // 2
        out[y:y + b.shape[0], x:x + b.shape[1]] = b
        y += b.shape[0] + gap
    return out


def build_stamp(
    *,
    img_w: int,
    img_h: int,
    text: str = "",
    use_text: bool = True,
    use_logo: bool = False,
    logo_rgba: Optional[np.ndarray] = None,
    font_path: Optional[str] = None,
    font_index: int = 0,
    color: Tuple[int, int, int] = (255, 255, 255),
    stroke_width: int = 0,
    stroke_color: Tuple[int, int, int] = (0, 0, 0),
    stroke_opacity: float = 1.0,
    use_stroke: bool = True,
    use_shadow: bool = False,
    shadow_color: Tuple[int, int, int] = (0, 0, 0),
    shadow_offset_x: int = 5,
    shadow_offset_y: int = 5,
    shadow_blur: float = 8.0,
    shadow_opacity: float = 0.5,
    layout: str = "vertical",
    gap: Optional[int] = None,
    scale_pct: float = 20.0,
    angle: float = 0.0,
    max_stamp_px: Optional[int] = None,
) -> np.ndarray:
    """
    渲染水印图章（RGBA float32，尚未乘透明度）。

    scale_pct：图章宽度占画面宽度的百分比。
      - 只有文字：文字宽度 = scale_pct% 画面宽；
      - 只有 logo：logo 宽度 = scale_pct% 画面宽；
      - 两者都要：竖排时各占 scale_pct%（取较宽者决定整体宽度），
                  横排时各占一半，拼起来整体宽度仍约等于 scale_pct%。

    use_stroke / use_shadow：样式开关。库这一层不预设风格，默认「给什么就画什么」
    （use_stroke=True 时 stroke_width>0 才生效），预设与默认值由节点层决定。

    返回形状 (h, w, 4)，alpha 已为 0..1（含投影扩出的边）。
    """
    text = text or ""
    want_text = bool(use_text) and bool(text.strip())
    want_logo = bool(use_logo) and logo_rgba is not None and logo_rgba.size > 0
    if not want_text and not want_logo:
        return np.zeros((1, 1, 4), dtype=np.float32)

    # 关掉描边时按 0 参与测量，这样「图章宽度 = 画面宽 X%」才是准的
    sw = max(0, int(stroke_width)) if use_stroke else 0

    target_w = max(4.0, float(img_w) * float(scale_pct) / 100.0)
    if max_stamp_px:
        target_w = min(target_w, float(max_stamp_px))
    if gap is None:
        gap = max(4, int(round(img_w * 0.012)))

    blocks: List[Tuple[str, np.ndarray]] = []
    if want_text and want_logo:
        if layout == "horizontal":
            half = target_w * 0.5
            blocks.append(("logo", resize_rgba(logo_rgba, half)))
            blocks.append(("text", render_text_rgba(text, font_path, int(half), color,
                                                    sw, stroke_color, font_index=font_index,
                                                    stroke_opacity=stroke_opacity)))
        else:
            blocks.append(("logo", resize_rgba(logo_rgba, target_w)))
            blocks.append(("text", render_text_rgba(text, font_path, int(target_w), color,
                                                    sw, stroke_color, font_index=font_index,
                                                    stroke_opacity=stroke_opacity)))
        stamp = vstack_rgba([b for _, b in blocks], gap) if layout == "vertical" \
            else hstack_rgba([b for _, b in blocks], gap)
    elif want_logo:
        stamp = resize_rgba(logo_rgba, target_w)
    else:
        stamp = render_text_rgba(text, font_path, int(target_w), color,
                                 sw, stroke_color, font_index=font_index,
                                 stroke_opacity=stroke_opacity)

    stamp = rotate_stamp(stamp, angle)
    if use_shadow:
        # 投影加在旋转之后：光源相对画面固定，影子不会跟着歪掉的水印一起转
        stamp = add_shadow(stamp, color=shadow_color, offset_x=shadow_offset_x,
                           offset_y=shadow_offset_y, blur=shadow_blur, opacity=shadow_opacity)
    return trim_rgba(stamp)


# =====================================================================
# 位置计算
# =====================================================================

def frame_positions(
    *,
    num_frames: int,
    img_w: int,
    img_h: int,
    stamp_w: int,
    stamp_h: int,
    mode: str,
    position: str,
    margin: int,
    float_path: str = "diagonal",
    float_cycles: float = 1.0,
    seed: int = 0,
) -> List[Tuple[int, int]]:
    """
    返回每一帧的图章左上角坐标列表，长度 = num_frames。

    安全区：画面内缩 margin 像素后剩下的矩形，图章始终完整落在其中，
    所以浮动 / 平铺都不会出现半个水印被切掉的情况。
    """
    num_frames = max(1, int(num_frames))
    span_x = max(0, img_w - stamp_w - 2 * int(margin))
    span_y = max(0, img_h - stamp_h - 2 * int(margin))
    m = int(margin)

    if mode == "tile":
        return [(0, 0)] * num_frames

    if mode == "floating":
        cycles = max(0.05, float(float_cycles))
        span = max(1, num_frames - 1)

        if float_path == "random":
            segs = max(1, int(round(cycles)))
            rng = random.Random(int(seed))
            pts = [(rng.random(), rng.random()) for _ in range(segs)]
            out: List[Tuple[int, int]] = []
            for i in range(num_frames):
                seg = min(segs - 1, (i * segs) // num_frames)
                fx, fy = pts[seg]
                out.append((int(round(m + span_x * fx)), int(round(m + span_y * fy))))
            return out

        out = []
        for i in range(num_frames):
            phase = (i / span) * cycles if num_frames > 1 else 0.0
            if float_path == "horizontal":
                fx, fy = _triangle(phase), 0.5
            elif float_path == "vertical":
                fx, fy = 0.5, _triangle(phase)
            elif float_path == "circle":
                a = 2.0 * math.pi * phase - math.pi / 2.0
                fx, fy = 0.5 + 0.45 * math.cos(a), 0.5 + 0.45 * math.sin(a)
            else:  # diagonal
                fx, fy = _triangle(phase), _triangle(phase + 0.3)
            out.append((int(round(m + span_x * fx)), int(round(m + span_y * fy))))
        return out

    # corner / center：固定位置
    ax, ay = _ANCHORS.get(position if mode == "corner" else "center", (1.0, 1.0))
    x = int(round(m + span_x * ax))
    y = int(round(m + span_y * ay))
    return [(x, y)] * num_frames


def tile_layer(stamp: np.ndarray, img_w: int, img_h: int, gap: int) -> np.ndarray:
    """
    把图章铺满整幅画面，返回与画面同尺寸的 RGBA 图层。
    超出画布的图章由调用方在合成时自动裁掉。
    """
    sh, sw = stamp.shape[:2]
    gap = max(0, int(gap))
    layer = np.zeros((img_h, img_w, 4), dtype=np.float32)
    if sw <= 0 or sh <= 0:
        return layer
    step_x = sw + gap
    step_y = sh + gap
    y = gap
    while y < img_h:
        x = gap
        while x < img_w:
            x0, y0 = max(0, x), max(0, y)
            x1, y1 = min(img_w, x + sw), min(img_h, y + sh)
            if x1 > x0 and y1 > y0:
                sx0, sy0 = x0 - x, y0 - y
                layer[y0:y1, x0:x1] = stamp[sy0:sy0 + (y1 - y0), sx0:sx0 + (x1 - x0)]
            x += step_x
        y += step_y
    return layer


# =====================================================================
# 合成
# =====================================================================

def composite(frame: np.ndarray, stamp: np.ndarray, x: int, y: int, alpha_scale: float = 1.0) -> None:
    """
    把 RGBA 图章按 alpha 合成到 frame（原地修改）。
    只处理图章覆盖的那一小块，所以哪怕上万帧也不会拖慢流程。
    """
    if alpha_scale <= 0.0:
        return
    fh, fw = frame.shape[0], frame.shape[1]
    sh, sw = stamp.shape[:2]
    x0, y0 = max(0, int(x)), max(0, int(y))
    x1, y1 = min(fw, int(x) + sw), min(fh, int(y) + sh)
    if x1 <= x0 or y1 <= y0:
        return
    sx0, sy0 = x0 - int(x), y0 - int(y)
    a = stamp[sy0:sy0 + (y1 - y0), sx0:sx0 + (x1 - x0), 3:4]
    if alpha_scale != 1.0:
        a = a * alpha_scale
    c = stamp[sy0:sy0 + (y1 - y0), sx0:sx0 + (x1 - x0), :3]
    region = frame[y0:y1, x0:x1, :3]
    region *= (1.0 - a)
    region += c * a


def _visibility(i: int, num_frames: int, start_pct: float, end_pct: float,
                fade_frames: int) -> float:
    """第 i 帧水印的透明度系数（0 表示不画）。"""
    if num_frames <= 0:
        return 0.0
    lo = int(round(_clamp(start_pct, 0.0, 1.0) * (num_frames - 1)))
    hi = int(round(_clamp(end_pct, 0.0, 1.0) * (num_frames - 1)))
    if hi < lo:
        lo, hi = hi, lo
    if i < lo or i > hi:
        return 0.0
    k = 1.0
    if fade_frames > 0:
        ff = max(1, min(int(fade_frames), max(1, (hi - lo + 1) // 2)))
        k = min(1.0, (i - lo + 1) / ff, (hi - i + 1) / ff)
    return float(_clamp(k, 0.0, 1.0))


def apply_watermark(
    frames: np.ndarray,
    stamp: np.ndarray,
    *,
    mode: str = "corner",
    position: str = "bottom_right",
    margin: int = 32,
    opacity: float = 0.85,
    float_path: str = "diagonal",
    float_cycles: float = 1.0,
    seed: int = 0,
    start_pct: float = 0.0,
    end_pct: float = 1.0,
    fade_frames: int = 0,
    tile_gap: int = 80,
    copy: bool = True,
) -> np.ndarray:
    """
    给整段帧批次打上水印。frames: [B,H,W,3] float32 0..1（可带 4 通道，只改前 3 个）。
    返回同形状数组。
    """
    src = np.asarray(frames)
    if src.ndim == 3:
        src = src[None, ...]
    if copy:
        out = np.array(src, dtype=np.float32, copy=True)
    else:
        out = src
    num_frames, img_h, img_w = out.shape[0], out.shape[1], out.shape[2]

    stamp = np.asarray(stamp, dtype=np.float32)
    if stamp.ndim != 3 or stamp.shape[2] != 4 or stamp.shape[0] < 2 or stamp.shape[1] < 2:
        return out                                   # 图章为空 → 原样返回
    if opacity <= 0.0:
        return out

    sh, sw = stamp.shape[:2]

    if mode == "tile":
        layer = tile_layer(stamp, img_w, img_h, tile_gap)
        for i in range(num_frames):
            k = _visibility(i, num_frames, start_pct, end_pct, fade_frames)
            if k <= 0:
                continue
            composite(out[i], layer, 0, 0, opacity * k)
        return out

    positions = frame_positions(
        num_frames=num_frames, img_w=img_w, img_h=img_h,
        stamp_w=sw, stamp_h=sh, mode=mode, position=position,
        margin=int(margin), float_path=float_path,
        float_cycles=float_cycles, seed=seed,
    )
    for i in range(num_frames):
        k = _visibility(i, num_frames, start_pct, end_pct, fade_frames)
        if k <= 0:
            continue
        x, y = positions[i]
        composite(out[i], stamp, x, y, opacity * k)
    return out


# =====================================================================
# 片头 / 片尾黑幕卡片
# =====================================================================

def make_title_frames(
    *,
    img_w: int,
    img_h: int,
    count: int,
    bg_color: Tuple[int, int, int] = (0, 0, 0),
    text: str = "",
    use_text: bool = True,
    use_logo: bool = False,
    logo_rgba: Optional[np.ndarray] = None,
    font_path: Optional[str] = None,
    font_index: int = 0,
    text_color: Tuple[int, int, int] = (255, 255, 255),
    text_stroke_width: int = 0,
    text_stroke_color: Tuple[int, int, int] = (0, 0, 0),
    text_scale_pct: float = 24.0,
    logo_scale_pct: float = 30.0,
    layout: str = "vertical",
    gap: Optional[int] = None,
    fade_frames: int = 6,
) -> np.ndarray:
    """
    生成片头/片尾卡片帧：[count, H, W, 3] float32 0..1。

    fade_frames：从纯黑渐显 / 渐隐到卡片的帧数。黑底卡片下，视觉上就是文字/logo 淡入淡出；
              非黑底则会呈现「由黑转亮」的转场，也算合理。
    """
    count = max(0, int(count))
    if count == 0 or img_w <= 0 or img_h <= 0:
        return np.zeros((0, img_h, img_w, 3), dtype=np.float32)

    base = np.zeros((img_h, img_w, 3), dtype=np.float32)
    base[:, :] = np.array(bg_color, dtype=np.float32) / 255.0

    card = np.array(base, copy=True)

    # 卡片内容单独渲染一次
    if gap is None:
        gap = max(4, int(round(img_w * 0.015)))
    text_img = None
    if use_text and (text or "").strip():
        text_img = render_text_rgba(text, font_path, int(img_w * text_scale_pct / 100.0),
                                    text_color, text_stroke_width, text_stroke_color,
                                    font_index=font_index)
    logo_img = None
    if use_logo and logo_rgba is not None and logo_rgba.size > 0:
        logo_img = resize_rgba(logo_rgba, int(img_w * logo_scale_pct / 100.0))

    if text_img is not None and logo_img is not None:
        stamp = vstack_rgba([logo_img, text_img], gap) if layout == "vertical" \
            else hstack_rgba([logo_img, text_img], gap)
    elif logo_img is not None:
        stamp = logo_img
    elif text_img is not None:
        stamp = text_img
    else:
        stamp = None

    if stamp is not None:
        sh, sw = stamp.shape[:2]
        if sw > img_w:                                  # 超宽时再收一点，防止出画
            stamp = resize_rgba(stamp, img_w - 8)
            sh, sw = stamp.shape[:2]
        x = (img_w - sw) // 2
        y = (img_h - sh) // 2
        composite(card, stamp, x, y, 1.0)

    frames = np.repeat(card[None, ...], count, axis=0)

    if fade_frames > 0:
        ff = max(1, min(int(fade_frames), max(1, count // 2)))
        ramp = np.ones((count, 1, 1, 1), dtype=np.float32)
        for i in range(count):
            ramp[i, 0, 0, 0] = min(1.0, (i + 0.5) / ff, (count - i - 0.5) / ff)
        frames = frames * ramp
    return frames


def make_silence(sample_rate: int, seconds: float, channels: int,
                 batch: int = 1) -> np.ndarray:
    """生成静音波形 [batch, channels, samples]（numpy，float32）。"""
    n = max(0, int(round(float(sample_rate) * max(0.0, float(seconds)))))
    return np.zeros((batch, max(1, int(channels)), n), dtype=np.float32)
