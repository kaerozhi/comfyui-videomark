# -*- coding: utf-8 -*-
"""
comfyui-videomark 节点定义
==========================
三个节点：

  VideoMark Overlay  给图像批次打水印：四角固定 / 居中低透明 / 浮动 / 平铺
  VideoMark Title    片头 / 片尾黑幕卡片（版权声明 + logo），并可把音频补齐静音保持同步
  VideoMark Video    VIDEO → VIDEO 一站式：上面两件事一次做完

单张图片也走 Overlay：IMAGE 进 IMAGE 出，**一张图就是「批次长度为 1」**，
跟视频逐帧共用同一套水印参数（四角 / 居中 / 浮动 / 平铺都成立）。

「把一整包照片批量处理掉」不在这里做 —— 那是批处理工作流的活，
本包保持轻量，只负责把「水印本身」做对。

设计原则
--------
- 只依赖 torch + numpy + Pillow，不引入任何新 pip 依赖（Pillow 是 ComfyUI 自带）；
  渲染失败也不会抛异常中断出图，最差情况退化为「原样透传」；
- 只认 IMAGE 批次，不绑定任何视频模型 —— H3 / Wan / LTX / Hunyuan / VHS 都能挂；
- 需要走 VIDEO 类型时，内置的「获取视频元素 / 创建视频」即可桥接，
  VideoMark Video 节点也直接吃 VIDEO；
- 文字有两个来源：面板里手填（text / title_text）或从外部接进来（text_in）。
  连线且内容非空时**以连线为准**，规则与本包 logo 一致（连线 > logo_file）——
  跑参数对比测试时把这一轮的参数拼进画面，回看结果时一眼就知道是哪一套。

INPUT_TYPES 约定：控件参数一律放 required（ComfyUI 的通行做法），
只有「需要连线」的 logo / logo_mask / text_in / audio 放 optional。
其中 text_in 必须带 forceInput —— 它只长成一个连线口、不进控件表，
因此加它对老工作流的 widgets_values 一位都不影响（展开见 TEXT_IN_LINK 的注释）。
"""

from __future__ import annotations

from fractions import Fraction
from typing import Optional, Tuple

import numpy as np
import torch

try:
    from . import logofile as LF
    from . import render as R
    from .fonts import FALLBACK_LABEL, default_font_label, font_choices, resolve_font
except ImportError:                                       # 被当成顶层模块加载时
    import logofile as LF                                 # type: ignore[no-redef]
    import render as R                                    # type: ignore[no-redef]
    from fonts import FALLBACK_LABEL, default_font_label, font_choices, resolve_font  # type: ignore[no-redef]

CATEGORY = "VideoMark"

# ---------------------------------------------------------------------
# VIDEO 类型（可选能力，缺了也不影响 Overlay / Title 两个节点）
# ---------------------------------------------------------------------
VideoFromComponents = None
_VideoComponents = None
_VIDEO_IMPORT_ERROR = ""
try:
    from comfy_api.latest import InputImpl as _InputImpl, Types as _Types
    VideoFromComponents = _InputImpl.VideoFromComponents
    _VideoComponents = _Types.VideoComponents
except Exception as e:                                    # noqa: BLE001
    _VIDEO_IMPORT_ERROR = str(e)

HAS_VIDEO_TYPE = VideoFromComponents is not None and _VideoComponents is not None


# =====================================================================
# 输入参数表
# =====================================================================

def _log(msg: str) -> None:
    print(f"[VideoMark] {msg}")


def _font_widgets() -> dict:
    """字体相关控件。字体表在导入时算一次，避免每次排队都扫字体目录。"""
    try:
        choices = font_choices()
    except Exception:                                     # noqa: BLE001
        choices = [FALLBACK_LABEL]
    try:
        default = default_font_label()
    except Exception:                                     # noqa: BLE001
        default = choices[0]
    return {
        "font": (choices, {
            "default": default,
            "tooltip": "Font. Sorted CJK-first on Windows (Microsoft YaHei / SimHei / SimSun / KaiTi ...).\n"
                       "Fonts you drop into ComfyUI's input/fonts folder show up in this list too.\n"
                       "Note: SimHei has no glyph for © - it renders as a box. Use Microsoft YaHei / SimSun / KaiTi "
                       "for text containing ©.",
        }),
        "font_file": ("STRING", {
            "default": "",
            "tooltip": "Font file path relative to ComfyUI's input folder, e.g. fonts/MyFont.otf.\n"
                       "When set and the file exists it overrides the font list above.\n"
                       "Absolute paths and '..' are rejected.",
        }),
    }


# 面板上传的 logo 落成文件名，正式渲染时再读文件（不走 LoadImage 连线）
LOGO_FILE_WIDGET = {
    "logo_file": ("STRING", {
        "default": "",
        "tooltip": "Logo file name, relative to ComfyUI's input folder.\n"
                   "Clicking 'Upload logo' in the visual panel fills this in; you normally never edit it by hand.\n"
                   "You can also type the name of a file already placed in the input folder, e.g. logo/kaero.png.\n"
                   "Note: a linked IMAGE on the logo input always wins over this.",
    }),
}


def _with_logo(d: dict) -> dict:
    """把 logo_file 钉在控件表最后一位。**每个节点都必须用它收尾。**

    ComfyUI 的工作流按「位置」序列化控件值（widgets_values 是个数组，不是字典）。
    所以「往中间插一个新参数」这件事的代价是：所有老工作流在该位置之后的控件
    值都会整体右移一位，加载时报一串牛头不对马嘴的错 ——
    logo_file 当初插在 font_file 与 float_path 之间，用户拿到的就是：

        float_path  输入值 1 不可用                    （拿到老 float_cycles）
        float_cycles 输入值 2261135997 高于最大值 200   （拿到老 seed）
        seed        输入值 randomize 无法转换为 INT      （拿到老 control_after_generate）

    放在末尾，老工作流存的前 N 个值就能一一对上，多出来的槽位取默认值。
    新增参数时也请照这个规矩来：**只往末尾加，不改前面的顺序。**
    """
    if not d:
        return d
    d = dict(d)
    d.pop("logo_file", None)                 # 防呆：万一调用方已经塞过
    d.update(LOGO_FILE_WIDGET)
    return d


def _watermark_widgets() -> dict:
    """Overlay 与 Video 节点共用的水印参数，按「常用 → 进阶」排列。

    这套参数对视频逐帧和**单张图片**都成立：一张图就是「批次长度为 1」，
    排版按图宽等比算，四角 / 居中 / 浮动 / 平铺都照常工作。

    注意：这里**不含** logo_file —— 它由调用方用 _with_logo() 收尾，
    必须排在所有控件之后（老工作流的坑位兼容，见 _with_logo 的说明）。
    """
    d = {
        "mode": (R.MODES, {
            "default": "corner",
            "tooltip": "Watermark mode:\n"
                       "corner   fixed in one corner (least intrusive, best default)\n"
                       "center   dead centre - keep opacity around 0.15~0.25\n"
                       "floating wanders inside the safe area (hardest to crop out, worst to watch)\n"
                       "tile     repeated across the whole frame - hardest to remove in post",
        }),
        "position": (R.POSITIONS, {
            "default": "bottom_right",
            "tooltip": "Which corner to use in corner mode.\n"
                       "Bottom-right blocks the least; switch to top-left if the platform overlays its own UI "
                       "(like/share buttons) there.",
        }),
        "text": ("STRING", {
            "default": "© 2026 kaero",
            "multiline": True,
            "tooltip": "Watermark text. Multiple lines supported - just press Enter.",
        }),
        "opacity": ("FLOAT", {
            "default": 0.85, "min": 0.02, "max": 1.0, "step": 0.01,
            "tooltip": "Overall opacity. Reference values:\n"
                       "corner 0.75~1.0 (needs to stay legible)\n"
                       "centre / tile 0.12~0.22 (higher starts to hurt viewing)\n"
                       "floating 0.25~0.45 (too low gets erased after compression)",
        }),
        "scale": ("FLOAT", {
            "default": 20.0, "min": 1.0, "max": 100.0, "step": 0.5,
            "tooltip": "Watermark width as a percentage of the frame width. Resolution independent - you never retune it.\n"
                       "15~25 for text, 8~18 for a logo.",
        }),
        "margin": ("INT", {
            "default": 32, "min": 0, "max": 600, "step": 1,
            "tooltip": "Safe margin from the frame edge, in pixels. Floating and tiled stamps respect it too, "
                       "so nothing ever gets clipped.\n"
                       "24~40 for 736x992; 36~64 for 1080p.",
        }),
        "use_text": ("BOOLEAN", {
            "default": True,
            "tooltip": "Turn off to show the logo only without deleting the text.",
        }),
        "use_logo": ("BOOLEAN", {
            "default": False,
            "tooltip": "Master switch for drawing the logo.\n"
                       "Source is either the panel upload (stored as logo_file above)\n"
                       "or an IMAGE linked to the logo input - the link wins.",
        }),
        "layout": (R.LAYOUTS, {
            "default": "vertical",
            "tooltip": "How logo and text stack when both are present: vertical (logo on top) or horizontal (logo on the left).",
        }),
        "color": ("STRING", {
            "default": "#FFFFFF",
            "tooltip": "Text colour. Accepts #RRGGBB / #RGB / r,g,b / a colour name.",
        }),
        # ---- 样式组：先由 style 一键定调，想逐项手调就切到 manual ----
        "style": (R.STYLES, {
            "default": "soft",
            "tooltip": "Style preset - one click swaps the whole stroke / shadow set:\n"
                       "soft           both on but subtle (default)\n"
                       "               readable on light and dark footage, without grabbing attention\n"
                       "plain          both off - cleanest, but may vanish on bright backgrounds\n"
                       "outline        solid stroke only - only needed when contrast swings hard\n"
                       "outline_shadow both maxed - most legible, also most noticeable\n"
                       "manual         ignore presets, use the four controls below\n"
                       "Note: presets override the stroke / shadow values below - pick manual to tune them yourself.",
        }),
        "use_stroke": ("BOOLEAN", {
            "default": True,
            "tooltip": "Stroke switch (only read when style=manual; presets take over otherwise).\n"
                       "A stroke rings the glyphs and reads louder than the text itself on high-contrast shots -\n"
                       "if the watermark feels heavy, lower stroke_opacity before turning it off.",
        }),
        "stroke_width": ("INT", {
            "default": 3, "min": 0, "max": 24, "step": 1,
            "tooltip": "Stroke thickness in pixels. Only applies when the stroke is on. 2~4 is plenty.",
        }),
        "stroke_color": ("STRING", {
            "default": "#000000",
            "tooltip": "Stroke colour.",
        }),
        "stroke_opacity": ("FLOAT", {
            "default": 0.55, "min": 0.0, "max": 1.0, "step": 0.01,
            "tooltip": "Opacity of the stroke itself - lower this first when the watermark feels heavy; keeps more "
                       "legibility than switching it off.\n"
                       "1.0 = solid black outline (loudest); 0.5~0.6 = soft ring (default); 0 = same as off.",
        }),
        "use_shadow": ("BOOLEAN", {
            "default": True,
            "tooltip": "Shadow switch (only read when style=manual).\n"
                       "A shadow thickens the silhouette without the hard edge a stroke leaves -\n"
                       "⚠ a dark shadow is invisible on night / black footage - use a stroke there, or lighten shadow_color.",
        }),
        "shadow_color": ("STRING", {
            "default": "#000000",
            "tooltip": "Shadow colour. Dark shadows disappear on dark footage; use a light colour like #FFFFFF.",
        }),
        "shadow_opacity": ("FLOAT", {
            "default": 0.4, "min": 0.0, "max": 1.0, "step": 0.01,
            "tooltip": "Opacity of the shadow. 0.3~0.5 reads as 'visible outline, not in the way'.",
        }),
        "shadow_offset": ("INT", {
            "default": 5, "min": -80, "max": 80, "step": 1,
            "tooltip": "Shadow offset in pixels (positive = down-right). 4~8 looks natural;\n"
                       "0 turns it into a symmetrical soft glow - lighter, and costs no margin in a corner.",
        }),
        "shadow_blur": ("INT", {
            "default": 8, "min": 0, "max": 100, "step": 1,
            "tooltip": "Shadow blur radius in pixels. Bigger is softer. 6~14 is natural; 0 = a hard duplicate.",
        }),
        "angle": ("FLOAT", {
            "default": 0.0, "min": -180.0, "max": 180.0, "step": 0.5,
            "tooltip": "Rotate the whole watermark. For tiled marks, -20~-30 degrees is much harder to align and erase.",
        }),
    }
    d.update(_font_widgets())
    d.update({
        "float_path": (R.FLOAT_PATHS, {
            "default": "diagonal",
            "tooltip": "Path followed while floating:\n"
                       "diagonal / horizontal / vertical  constant back-and-forth (triangle wave)\n"
                       "circle                            elliptical loop\n"
                       "random                            uniform random jumps - strongest anti-theft, most jarring",
        }),
        "float_cycles": ("FLOAT", {
            "default": 1.0, "min": 0.1, "max": 200.0, "step": 0.1,
            "tooltip": "How many round trips across the whole clip.\n"
                       "1 = one very slow pass; 4~8 = clearly wandering but still readable.\n"
                       "For the random path this means 'number of position changes' - try 2x the clip length in seconds.\n"
                       "A single still has nothing to travel across: the seed pins it to one spot.",
        }),
        "seed": ("INT", {
            "default": 0, "min": 0, "max": 0xFFFFFFFF, "step": 1,
            "tooltip": "Used by the random float path only. Fix it to reproduce the same positions.",
        }),
        "start_pct": ("FLOAT", {
            "default": 0.0, "min": 0.0, "max": 1.0, "step": 0.001,
            "tooltip": "Where the watermark starts appearing, as a fraction of total length. 0 = from frame one.\n"
                       "Only meaningful for multi-frame sequences: a single still counts as frame 0.",
        }),
        "end_pct": ("FLOAT", {
            "default": 1.0, "min": 0.0, "max": 1.0, "step": 0.001,
            "tooltip": "Where it stops, as a fraction of total length. 1 = stays to the end.\n"
                       "e.g. 0.6 -> 1.0 shows it only in the last 40%.\n"
                       "Only meaningful for multi-frame sequences: a single still counts as frame 0.",
        }),
        "fade_frames": ("INT", {
            "default": 0, "min": 0, "max": 240, "step": 1,
            "tooltip": "Fade-in / fade-out length in frames. 0 = hard cut.\n"
                       "Only meaningful for multi-frame sequences: a single still has nothing to fade.",
        }),
        "tile_gap": ("INT", {
            "default": 90, "min": 0, "max": 1200, "step": 2,
            "tooltip": "Spacing between tiled watermarks, in pixels.",
        }),
    })
    return d


_LOGO_LINKS = {
    "logo": ("IMAGE", {
        "tooltip": "Optional. A PNG logo with an alpha channel. Only drawn when use_logo is on.\n"
                   "Transparency comes from logo_mask first; falls back to the PNG's own alpha.",
    }),
    "logo_mask": ("MASK", {
        "tooltip": "Optional. Transparency mask for the logo; falls back to the PNG's own alpha.\n"
                   "ComfyUI's Load Image outputs a PNG's transparency as a MASK - just wire it in.",
    }),
}


# 外部文字接入口。
#
# ⚠ forceInput 是必需的，不是修饰：带它的 STRING 只会长成一个**连线口**，
#   不会在控件表里占坑位 —— 所以加这个参数对老工作流的 widgets_values 一位都不动。
#   依据（前端产物 settingStore）：
#       let o = n.widgets.get(i.type); if (!o || t.forceInput) return;   // 不建 widget
#       addInputSocket(): 同一判断为假时才走 input 分支 → e.addInput(name, type, …)
#   反过来说：哪天有人把 forceInput 去掉，它立刻变成一个多出来的控件槽，
#   把之后所有控件值整体右移一位 —— 那正是 logo_file 当年踩过的坑。
#   tools/uicheck.py 的 is_widget_param() 认这条规则：forceInput 不算控件，
#   否则会误报「面板没接管这个参数」。
TEXT_IN_LINK = {
    "text_in": ("STRING", {
        "forceInput": True,
        "tooltip": "Optional. Feed the text in from another node (any node that builds a string).\n"
                   "When connected and non-empty the wired text wins - whatever you typed in the panel is ignored.\n"
                   "Disconnected, or an empty string upstream, falls back to the panel text.\n"
                   "Typical use: while comparing parameter variants (resolutions / LoRA strengths / seeds),\n"
                   "splice this run's parameters into the frame so you can tell at a glance which settings produced it.\n"
                   "Note: it takes one plain string - nothing is filled in for you, so build the text you want upstream.",
    }),
}


def _ext_text(text_in) -> str:
    """连线来的外部文字。没接（None）或只有空白 → 返回空串，表示「没有外部文字」。"""
    if text_in is None:
        return ""
    s = text_in if isinstance(text_in, str) else str(text_in)
    return s if s.strip() else ""


def _resolve_text(text, text_in) -> str:
    """
    最终用哪段文字：外部连线优先于面板手填。

    两条规则：
      1. 连线优先 —— 和 logo 一样（连线 > logo_file）。显式接进来的东西是用户
         当下要用的，控件里那份只是上一次留下的记录，不该反过来盖掉它。
      2. 空串按「没接」处理 —— 上游节点常常会输出空字符串（条件拼接没命中、
         文本被清空），这时回落到手填文字，比把水印整个变没要合理得多。

    这段逻辑单独成函数是为了能被 tools/selftest.py 直接测 —— 渲染那一步太重，
    拿它当测试入口会把「文字来源」这件事埋进像素断言里。
    """
    return _ext_text(text_in) or ("" if text is None else str(text))


def _text_source(text_in) -> str:
    """日志用的来源标记，让人一眼看出这段文字是接进来的还是手填的。"""
    return "external" if _ext_text(text_in) else "panel"


# =====================================================================
# 张量 ↔ numpy
# =====================================================================

def _to_np(t) -> Optional[np.ndarray]:
    if t is None:
        return None
    if isinstance(t, torch.Tensor):
        t = t.detach().cpu()
        if t.dtype == torch.float64:
            t = t.float()
        return t.numpy()
    return np.asarray(t)


def _first_image(a: Optional[np.ndarray]) -> Optional[np.ndarray]:
    """
    IMAGE 批次 [B,H,W,C] → 单张 [H,W,C]。

    注意区分维度：IMAGE 批次是 4 维，单张图是 3 维；
    MASK 批次是 3 维，单张遮罩是 2 维。搞混会把图切成一条一条的，
    所以这里按维度判断，两种形态都吃。
    """
    if a is None or a.size == 0:
        return None
    return a[0] if a.ndim == 4 else a


def _first_mask(a: Optional[np.ndarray]) -> Optional[np.ndarray]:
    """MASK 批次 [B,H,W] → 单张 [H,W]；已经是单张则原样返回。"""
    if a is None or a.size == 0:
        return None
    return a[0] if a.ndim == 3 else a


def _to_tensor(a: np.ndarray) -> torch.Tensor:
    return torch.from_numpy(np.ascontiguousarray(a, dtype=np.float32))


def _safe_font(font, font_file) -> Tuple[Optional[str], int]:
    try:
        return resolve_font(font or "", font_file or "")
    except Exception as e:                                # noqa: BLE001
        _log(f"font resolution failed, using the built-in fallback: {e}")
        return None, 0


def _build_logo(logo, logo_mask, logo_file: str = ""):
    """
    logo 的两个来源，优先级：连线的 IMAGE / MASK > 面板上传的文件名。

    「优先连线」是有意的：显式接一根线进来的图是用户当下要用的（可能是动态生成的），
    而 logo_file 只是面板上一次上传留下的记录，不该反过来盖掉连线。
    """
    arr = _first_image(_to_np(logo))
    if arr is not None:
        try:
            return R.logo_to_rgba(arr, _first_mask(_to_np(logo_mask)))
        except Exception as e:                            # noqa: BLE001
            _log(f"linked logo failed to parse, falling back to logo_file: {e}")

    name = (logo_file or "").strip()
    if name:
        try:
            rgba = LF.load_logo_rgba(name)
            if rgba is not None:
                return rgba
            _log(f"logo file could not be read (logo skipped): {name}")
        except Exception as e:                            # noqa: BLE001
            _log(f"logo file raised (logo skipped): {type(e).__name__}: {e}")
    return None


def _pad_audio(audio, head_sec: float = 0.0, tail_sec: float = 0.0):
    """
    给 AUDIO 补静音：{"waveform": [B,C,T], "sample_rate": int}。
    """
    try:
        if not isinstance(audio, dict) or (head_sec <= 0 and tail_sec <= 0):
            return audio
        wf = audio.get("waveform")
        sr = int(audio.get("sample_rate") or 0)
        if wf is None or sr <= 0:
            return audio
        if not isinstance(wf, torch.Tensor):
            wf = torch.as_tensor(wf)
        pieces = []
        if head_sec > 0:
            n = int(round(sr * head_sec))
            pieces.append(torch.zeros((wf.shape[0], wf.shape[1], n), dtype=wf.dtype, device=wf.device))
        pieces.append(wf)
        if tail_sec > 0:
            n = int(round(sr * tail_sec))
            pieces.append(torch.zeros((wf.shape[0], wf.shape[1], n), dtype=wf.dtype, device=wf.device))
        out = dict(audio)
        out["waveform"] = torch.cat(pieces, dim=-1)
        return out
    except Exception as e:                                # noqa: BLE001
        _log(f"audio padding failed, passing through unchanged: {e}")
        return audio


# =====================================================================
# 节点 1：VideoMark Overlay
# =====================================================================

class VideoMarkOverlay:
    """给图像批次（视频逐帧）打水印。"""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": _with_logo(dict({"images": ("IMAGE",)}, **_watermark_widgets())),
            # text_in 排在最前：它是最常用的外接口，长在 images 正下方最好找
            "optional": dict(TEXT_IN_LINK, **_LOGO_LINKS),
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "apply"
    CATEGORY = CATEGORY
    DESCRIPTION = ("Burn a watermark into a frame batch: fixed corner / low-opacity centre / floating / tiled.\n"
                   "Not tied to any video model - any IMAGE batch works (MiniMax H3, Wan, LTX, VHS...).\n"
                   "A single photo works too: one image is just a batch of length 1, laid out from its own "
                   "width and height.\n"
                   "Bulk-processing a folder is a job for a batch workflow; this node only draws the mark.\n"
                   "Returns a new tensor; upstream data is never modified.")

    def apply(self, images, mode="corner", position="bottom_right", text="© 2026 kaero",
              opacity=0.85, scale=20.0, margin=32, use_text=True, use_logo=False,
              layout="vertical", color="#FFFFFF",
              style="soft", use_stroke=True, stroke_width=3, stroke_color="#000000",
              stroke_opacity=0.55, use_shadow=True, shadow_color="#000000",
              shadow_opacity=0.4, shadow_offset=5, shadow_blur=8,
              angle=0.0, font=None, font_file="", float_path="diagonal", float_cycles=1.0,
              seed=0, start_pct=0.0, end_pct=1.0, fade_frames=0, tile_gap=90,
              logo_file="", logo=None, logo_mask=None, text_in=None):

        arr = _to_np(images)
        if arr is None or arr.size == 0:
            return (images,)
        if arr.ndim == 3:
            arr = arr[None, ...]
        num_frames, h, w = arr.shape[0], arr.shape[1], arr.shape[2]

        text = _resolve_text(text, text_in)                   # 连线优先，空串回落
        font_path, _ = _safe_font(font, font_file)
        logo_rgba = _build_logo(logo, logo_mask, logo_file) if use_logo else None
        draw_stroke, draw_shadow, so, sho = R.resolve_style(
            style, use_stroke, use_shadow,
            stroke_opacity=stroke_opacity, shadow_opacity=shadow_opacity)

        try:
            stamp = R.build_stamp(
                img_w=w, img_h=h, text=text, use_text=use_text, use_logo=use_logo,
                logo_rgba=logo_rgba, font_path=font_path, color=R.parse_color(color),
                use_stroke=draw_stroke, stroke_width=int(stroke_width),
                stroke_color=R.parse_color(stroke_color, (0, 0, 0)),
                stroke_opacity=so,
                use_shadow=draw_shadow, shadow_color=R.parse_color(shadow_color, (0, 0, 0)),
                shadow_opacity=sho,
                shadow_offset_x=int(shadow_offset), shadow_offset_y=int(shadow_offset),
                shadow_blur=float(shadow_blur),
                layout=layout, scale_pct=float(scale), angle=float(angle),
            )
            out = R.apply_watermark(
                arr, stamp, mode=mode, position=position, margin=int(margin),
                opacity=float(opacity), float_path=float_path, float_cycles=float(float_cycles),
                seed=int(seed), start_pct=float(start_pct), end_pct=float(end_pct),
                fade_frames=int(fade_frames), tile_gap=int(tile_gap),
            )
        except Exception as e:                            # noqa: BLE001
            _log(f"render failed, passing through unchanged (workflow not interrupted): {type(e).__name__}: {e}")
            return (_to_tensor(np.asarray(arr, dtype=np.float32)),)

        if stamp.shape[0] > 2 and stamp.shape[1] > 2:
            _log(f"Overlay {mode}/{position} · {num_frames} frames · {w}x{h} · "
                 f"stamp {stamp.shape[1]}x{stamp.shape[0]} · opacity {opacity} · "
                 f"{style}(stroke {'on' if draw_stroke else 'off'} / shadow {'on' if draw_shadow else 'off'})"
                 + (f" · text {_text_source(text_in)}" if use_text else ""))
        else:
            _log("Overlay skipped: nothing to draw (text empty and logo off)")
        return (_to_tensor(out),)


# =====================================================================
# 节点 2：VideoMark Title
# =====================================================================

class VideoMarkTitle:
    """片头 / 片尾黑幕卡片（版权声明 + logo），并可补齐音频静音。"""

    @classmethod
    def INPUT_TYPES(cls):
        widgets = {
            "images": ("IMAGE",),
            "fps": ("FLOAT", {
                "default": 24.0, "min": 1.0, "max": 240.0, "step": 1.0,
                "tooltip": "Frame rate, used to convert seconds into a frame count.\n"
                           "Must match the final clip's frame rate or the card length will be off (H3 usually outputs 24fps).",
            }),
            "where": (["head", "tail", "both"], {
                "default": "head",
                "tooltip": "head = only at the start, tail = only at the end, both = both ends (each gets a full card).",
            }),
            "seconds": ("FLOAT", {
                "default": 2.0, "min": 0.1, "max": 60.0, "step": 0.1,
                "tooltip": "Card duration in seconds. Around 2s works well for a copyright notice.",
            }),
            "text": ("STRING", {
                "default": "© 2026 kaero\nAll rights reserved",
                "multiline": True,
                "tooltip": "Card text. Multiple lines supported.",
            }),
            "use_text": ("BOOLEAN", {"default": True, "tooltip": "Turn off to show the logo only."}),
            "bg_color": ("STRING", {
                "default": "#000000",
                "tooltip": "Card background colour. Pure black by default.",
            }),
            "use_logo": ("BOOLEAN", {
                "default": False,
                "tooltip": "Master switch for drawing the logo. Same sources as Overlay: panel upload, or a linked IMAGE.",
            }),
            "layout": (R.LAYOUTS, {
                "default": "vertical",
                "tooltip": "How logo and text stack when both are present: vertical (logo on top) or horizontal (logo on the left).",
            }),
            "logo_scale": ("FLOAT", {
                "default": 30.0, "min": 1.0, "max": 100.0, "step": 0.5,
                "tooltip": "Logo width as a percentage of the frame width.",
            }),
            "text_scale": ("FLOAT", {
                "default": 24.0, "min": 1.0, "max": 100.0, "step": 0.5,
                "tooltip": "Text width as a percentage of the frame width. 20~30 reads well for a credit card.",
            }),
            "text_color": ("STRING", {"default": "#FFFFFF", "tooltip": "Card text colour."}),
            "text_stroke_width": ("INT", {
                "default": 0, "min": 0, "max": 24, "step": 1,
                "tooltip": "Text stroke thickness. Give it 2~4 when the background is not pure black.",
            }),
            "text_stroke_color": ("STRING", {"default": "#000000", "tooltip": "Card text stroke colour."}),
        }
        widgets.update(_font_widgets())
        widgets.update({
            "fade_frames": ("INT", {
                "default": 8, "min": 0, "max": 240, "step": 1,
                "tooltip": "Fade-in / fade-out length in frames. On a black card this reads as the text/logo fading; 0 = hard cut.",
            }),
            "pad_audio": ("BOOLEAN", {
                "default": True,
                "tooltip": "Pad the audio with matching silence so adding a head card does not desync A/V.\n"
                           "Keep this on whenever music is connected.",
            }),
        })
        links = dict(TEXT_IN_LINK)
        links.update(_LOGO_LINKS)
        links["audio"] = ("AUDIO", {
            "tooltip": "Optional. Video audio track. Only when connected does the node pad silence and pass it through.",
        })
        return {"required": _with_logo(widgets), "optional": links}

    RETURN_TYPES = ("IMAGE", "AUDIO")
    RETURN_NAMES = ("images", "audio")
    FUNCTION = "apply"
    CATEGORY = CATEGORY
    DESCRIPTION = ("Insert black copyright cards (text + logo) at the head and/or tail, optionally padding the\n"
                   "audio with matching silence so A/V stays in sync. "
                   "Audio output is empty when nothing is connected.")

    def apply(self, images, fps=24.0, where="head", seconds=2.0,
              text="© 2026 kaero\nAll rights reserved", use_text=True, bg_color="#000000",
              use_logo=False, layout="vertical", logo_scale=30.0, text_scale=24.0,
              text_color="#FFFFFF", text_stroke_width=0, text_stroke_color="#000000",
              font=None, font_file="", fade_frames=8, pad_audio=True,
              logo_file="", logo=None, logo_mask=None, audio=None, text_in=None):

        arr = _to_np(images)
        if arr is None or arr.size == 0:
            return (images, audio)
        if arr.ndim == 3:
            arr = arr[None, ...]
        h, w = arr.shape[1], arr.shape[2]

        text = _resolve_text(text, text_in)                   # 连线优先，空串回落
        count = max(1, int(round(float(seconds) * max(1.0, float(fps)))))
        font_path, _ = _safe_font(font, font_file)
        logo_rgba = _build_logo(logo, logo_mask, logo_file) if use_logo else None

        try:
            card = R.make_title_frames(
                img_w=w, img_h=h, count=count, bg_color=R.parse_color(bg_color, (0, 0, 0)),
                text=text, use_text=use_text, use_logo=use_logo, logo_rgba=logo_rgba,
                font_path=font_path, text_color=R.parse_color(text_color),
                text_stroke_width=int(text_stroke_width),
                text_stroke_color=R.parse_color(text_stroke_color, (0, 0, 0)),
                text_scale_pct=float(text_scale), logo_scale_pct=float(logo_scale),
                layout=layout, fade_frames=int(fade_frames),
            )
        except Exception as e:                            # noqa: BLE001
            _log(f"card render failed, passing through unchanged (workflow not interrupted): {type(e).__name__}: {e}")
            return (_to_tensor(np.asarray(arr, dtype=np.float32)), audio)

        head = where in ("head", "both")
        tail = where in ("tail", "both")
        blocks = ([card] if head else []) + [arr] + ([card] if tail else [])
        out = np.concatenate(blocks, axis=0) if len(blocks) > 1 else arr

        audio_out = audio
        if audio is not None and pad_audio and (head or tail):
            audio_out = _pad_audio(audio,
                                   head_sec=float(seconds) if head else 0.0,
                                   tail_sec=float(seconds) if tail else 0.0)

        _log(f"Title {where} · added {count * (2 if where == 'both' else 1)} frames · {w}x{h} @ {fps:g}fps "
             f"-> total {out.shape[0]} frames"
             + (" (audio padded)" if audio is not None and pad_audio else "")
             + (f" · text {_text_source(text_in)}" if use_text else ""))
        return (_to_tensor(out), audio_out)


# =====================================================================
# 节点 3：VideoMark Video（VIDEO → VIDEO）
# =====================================================================

if HAS_VIDEO_TYPE:
    class VideoMarkVideo:
        """VIDEO 进 VIDEO 出：一次搞定画面水印 + 片头片尾，音频自动处理。"""

        @classmethod
        def INPUT_TYPES(cls):
            widgets = dict({"video": ("VIDEO",)}, **_watermark_widgets())
            widgets.update({
                "title_mode": (["off", "head", "tail", "both"], {
                    "default": "off",
                    "tooltip": "Head / tail black copyright card. off = do not add one.",
                }),
                "title_seconds": ("FLOAT", {
                    "default": 2.0, "min": 0.1, "max": 60.0, "step": 0.1,
                    "tooltip": "Card duration in seconds. Frame rate comes from the input video.",
                }),
                "title_text": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": "Card text. Leave blank to reuse the watermark text above.",
                }),
                "title_bg_color": ("STRING", {
                    "default": "#000000",
                    "tooltip": "Card background colour.",
                }),
            })
            return {"required": _with_logo(widgets), "optional": dict(TEXT_IN_LINK, **_LOGO_LINKS)}

        RETURN_TYPES = ("VIDEO",)
        RETURN_NAMES = ("video",)
        FUNCTION = "apply"
        CATEGORY = CATEGORY
        DESCRIPTION = ("All-in-one: watermark + head/tail cards on a VIDEO, audio handled for you. "
                       "Use Overlay + Title when you want finer control.")

        def apply(self, video, mode="corner", position="bottom_right", text="© 2026 kaero",
                  opacity=0.85, scale=20.0, margin=32, use_text=True, use_logo=False,
                  layout="vertical", color="#FFFFFF",
                  style="soft", use_stroke=True, stroke_width=3, stroke_color="#000000",
                  stroke_opacity=0.55, use_shadow=True, shadow_color="#000000",
                  shadow_opacity=0.4, shadow_offset=5, shadow_blur=8,
                  angle=0.0, font=None, font_file="", float_path="diagonal",
                  float_cycles=1.0, seed=0, start_pct=0.0, end_pct=1.0,
                  fade_frames=0, tile_gap=90, title_mode="off", title_seconds=2.0,
                  title_text="", title_bg_color="#000000", logo_file="",
                  logo=None, logo_mask=None, text_in=None):

            comp = video.get_components()
            arr = _to_np(comp.images)
            if arr is None or arr.size == 0:
                return (video,)
            if arr.ndim == 3:
                arr = arr[None, ...]
            num_frames, h, w = arr.shape[0], arr.shape[1], arr.shape[2]
            fps = float(comp.frame_rate) if getattr(comp, "frame_rate", None) else 24.0

            text = _resolve_text(text, text_in)               # 连线优先，空串回落
            font_path, _ = _safe_font(font, font_file)
            logo_rgba = _build_logo(logo, logo_mask, logo_file) if use_logo else None
            draw_stroke, draw_shadow, so, sho = R.resolve_style(
                style, use_stroke, use_shadow,
                stroke_opacity=stroke_opacity, shadow_opacity=shadow_opacity)

            try:
                stamp = R.build_stamp(
                    img_w=w, img_h=h, text=text, use_text=use_text, use_logo=use_logo,
                    logo_rgba=logo_rgba, font_path=font_path, color=R.parse_color(color),
                    use_stroke=draw_stroke, stroke_width=int(stroke_width),
                    stroke_color=R.parse_color(stroke_color, (0, 0, 0)),
                    stroke_opacity=so,
                    use_shadow=draw_shadow, shadow_color=R.parse_color(shadow_color, (0, 0, 0)),
                    shadow_opacity=sho,
                    shadow_offset_x=int(shadow_offset), shadow_offset_y=int(shadow_offset),
                    shadow_blur=float(shadow_blur),
                    layout=layout, scale_pct=float(scale), angle=float(angle),
                )
                out = R.apply_watermark(
                    arr, stamp, mode=mode, position=position, margin=int(margin),
                    opacity=float(opacity), float_path=float_path,
                    float_cycles=float(float_cycles), seed=int(seed),
                    start_pct=float(start_pct), end_pct=float(end_pct),
                    fade_frames=int(fade_frames), tile_gap=int(tile_gap),
                )
            except Exception as e:                        # noqa: BLE001
                _log(f"render failed, passing through unchanged (workflow not interrupted): {type(e).__name__}: {e}")
                return (video,)

            audio_out = comp.audio
            added_title = 0
            if title_mode != "off":
                count = max(1, int(round(float(title_seconds) * fps)))
                try:
                    card = R.make_title_frames(
                        img_w=w, img_h=h, count=count,
                        bg_color=R.parse_color(title_bg_color, (0, 0, 0)),
                        # title_text 没填就跟着上面的 text 走 —— 于是外部接进来的文字
                        # 会自动覆盖到卡片上，用不着再接一根线
                        text=(title_text or text), use_text=use_text, use_logo=use_logo,
                        logo_rgba=logo_rgba, font_path=font_path,
                        text_color=R.parse_color(color),
                        # 卡片是黑底白字，对比度本来就够，不跟水印的描边样式走 ——
                        # 硬加描边只会让字整体变小，而黑描边在黑底上根本看不见。
                        text_stroke_width=0,
                        text_stroke_color=R.parse_color(stroke_color, (0, 0, 0)),
                        text_scale_pct=float(scale), logo_scale_pct=float(scale),
                        layout=layout,
                        fade_frames=int(fade_frames) if int(fade_frames) > 0 else 8,
                    )
                except Exception as e:                    # noqa: BLE001
                    _log(f"card render failed, this node outputs the watermark only: {type(e).__name__}: {e}")
                    card = None
                if card is not None and card.shape[0] > 0:
                    head = title_mode in ("head", "both")
                    tail = title_mode in ("tail", "both")
                    blocks = ([card] if head else []) + [out] + ([card] if tail else [])
                    out = np.concatenate(blocks, axis=0)
                    added_title = card.shape[0] * ((1 if head else 0) + (1 if tail else 0))
                    if audio_out is not None:
                        audio_out = _pad_audio(
                            audio_out,
                            head_sec=float(title_seconds) if head else 0.0,
                            tail_sec=float(title_seconds) if tail else 0.0,
                        )

            # 原始 alpha 与新帧数已不匹配，有插卡时直接丢掉，避免编码出问题
            alpha = getattr(comp, "alpha", None)
            if alpha is not None and (added_title > 0 or _is_empty(alpha)):
                alpha = None

            _log(f"Video {mode}/{position} · {num_frames}->{out.shape[0]} frames · {w}x{h} @ {fps:g}fps"
                 f" · {style}(stroke {'on' if draw_stroke else 'off'} / shadow {'on' if draw_shadow else 'off'})"
                 + (f" · card {title_mode}" if title_mode != "off" else "")
                 + (f" · text {_text_source(text_in)}" if use_text else ""))

            new_comp = _VideoComponents(
                images=_to_tensor(out),
                audio=audio_out,
                frame_rate=getattr(comp, "frame_rate", None) or Fraction(round(fps)),
                metadata=getattr(comp, "metadata", None),
                alpha=alpha,
            )
            bit_depth = _safe_call(video, "get_bit_depth", 8)
            color_space = _safe_call(video, "get_color_space", "sRGB")
            return (VideoFromComponents(new_comp, bit_depth=bit_depth, color_space=color_space),)


def _is_empty(t) -> bool:
    try:
        return not isinstance(t, torch.Tensor) or t.numel() == 0
    except Exception:                                     # noqa: BLE001
        return True


def _safe_call(obj, name: str, default):
    try:
        fn = getattr(obj, name, None)
        return fn() if callable(fn) else default
    except Exception:                                     # noqa: BLE001
        return default


# =====================================================================
# 注册
# =====================================================================

NODE_CLASS_MAPPINGS = {
    "VideoMarkOverlay": VideoMarkOverlay,
    "VideoMarkTitle": VideoMarkTitle,
}
NODE_DISPLAY_NAME_MAPPINGS = {
    "VideoMarkOverlay": "VideoMark Overlay",
    "VideoMarkTitle": "VideoMark Title",
}

if HAS_VIDEO_TYPE:
    NODE_CLASS_MAPPINGS["VideoMarkVideo"] = VideoMarkVideo
    NODE_DISPLAY_NAME_MAPPINGS["VideoMarkVideo"] = "VideoMark Video"
else:
    print(f"[VideoMark] VIDEO type unavailable, VideoMark Video node skipped: {_VIDEO_IMPORT_ERROR}")
