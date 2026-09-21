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
    from .fonts import default_font_label, font_choices, resolve_font
except ImportError:                                       # 被当成顶层模块加载时
    import logofile as LF                                 # type: ignore[no-redef]
    import render as R                                    # type: ignore[no-redef]
    from fonts import default_font_label, font_choices, resolve_font  # type: ignore[no-redef]

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
        choices = ["（内置兜底字体·中文会显示为方块）"]
    try:
        default = default_font_label()
    except Exception:                                     # noqa: BLE001
        default = choices[0]
    return {
        "font": (choices, {
            "default": default,
            "tooltip": "中文字体。列表按「中文优先」排序（微软雅黑 / 黑体 / 宋体 / 楷体…）。\n"
                       "想用列表外的字体（手写体、商用字体），把下面 font_file 填成绝对路径即可，它会覆盖这里。\n"
                       "注意：黑体（simhei）没有 © 字形，用它会显示成方框 —— 含 © 的文字请用微软雅黑 / 宋体 / 楷体。",
        }),
        "font_file": ("STRING", {
            "default": "",
            "tooltip": "自定义字体文件绝对路径，例：D:/Fonts/思源黑体.otf\n"
                       "填写且文件存在时，忽略上面的字体下拉框。",
        }),
    }


# 面板上传的 logo 落成文件名，正式渲染时再读文件（不走 LoadImage 连线）
LOGO_FILE_WIDGET = {
    "logo_file": ("STRING", {
        "default": "",
        "tooltip": "logo 文件名（相对 ComfyUI 的 input 目录）。\n"
                   "在可视化面板里点「上传 Logo」会自动填这一项，通常不用手改；\n"
                   "也可以手动填一个已经放进 input 目录的文件，例：logo/kaero.png\n"
                   "注意：若 logo 输入口接了线，以连线的图为准，这里会被忽略。",
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
            "tooltip": "水印方式：\n"
                       "corner   固定贴四角之一（最不挡画面，日常首选）\n"
                       "center   画面正中，建议 opacity 压到 0.15~0.25\n"
                       "floating 在安全区内游走 / 周期跳位（防盗最强，观感最差）\n"
                       "tile     全画面平铺，最难裁掉抹除",
        }),
        "position": (R.POSITIONS, {
            "default": "bottom_right",
            "tooltip": "corner 模式贴哪个角。\n"
                       "右下角最不挡主体；若右下角有平台 UI 遮挡（点赞/分享按钮），改用左上角。",
        }),
        "text": ("STRING", {
            "default": "© 2026 kaero",
            "multiline": True,
            "tooltip": "水印文字，支持多行（直接回车换行）。",
        }),
        "opacity": ("FLOAT", {
            "default": 0.85, "min": 0.02, "max": 1.0, "step": 0.01,
            "tooltip": "不透明度。参考值：\n"
                       "四角固定 0.75~1.0（要看得清）\n"
                       "居中 / 平铺 0.12~0.22（再高就影响观赏）\n"
                       "浮动 0.25~0.45（太低会被压暗后抹掉）",
        }),
        "scale": ("FLOAT", {
            "default": 20.0, "min": 1.0, "max": 100.0, "step": 0.5,
            "tooltip": "水印宽度占画面宽度的百分比。换分辨率不用改，会自动等比换算。\n"
                       "文字水印 15~25 比较舒服；logo 水印 8~18。",
        }),
        "margin": ("INT", {
            "default": 32, "min": 0, "max": 600, "step": 1,
            "tooltip": "距画面边缘的安全边距（像素）。浮动 / 平铺同样受它约束，图章不会被切掉。\n"
                       "参考：736×992 用 24~40；1080p 用 36~64。",
        }),
        "use_text": ("BOOLEAN", {
            "default": True,
            "tooltip": "关掉可临时只留 logo，不必删掉文字内容。",
        }),
        "use_logo": ("BOOLEAN", {
            "default": False,
            "tooltip": "打开才会绘制 logo。\n"
                       "图片来源二选一：面板里「上传 Logo」（存成上面的 logo_file），\n"
                       "或者把 LoadImage 的 IMAGE 接到 logo 输入口（接线优先）。",
        }),
        "layout": (R.LAYOUTS, {
            "default": "vertical",
            "tooltip": "logo 与文字同时存在时的排布：vertical 上下排（logo 在上），horizontal 左右排（logo 在左）。",
        }),
        "color": ("STRING", {
            "default": "#FFFFFF",
            "tooltip": "文字颜色。支持 #RRGGBB / #RGB / r,g,b / 英文颜色名。",
        }),
        # ---- 样式组：先由 style 一键定调，想逐项手调就切到 manual ----
        "style": (R.STYLES, {
            "default": "soft",
            "tooltip": "水印样式预设 —— 一键换整套描边 / 投影参数：\n"
                       "soft           描边 + 投影，两者都淡（默认）\n"
                       "               明暗背景都读得清，又不像实心描边那样抢画面\n"
                       "plain          两个都关 —— 最不干扰画面，但亮背景上可能糊掉\n"
                       "outline        只留实心描边 —— 画面明暗变化剧烈时才需要\n"
                       "outline_shadow 描边 + 投影都拉满 —— 最清楚，同时也最显眼\n"
                       "manual         不用预设，完全按下面四个控件的数值来\n"
                       "注意：选预设时下面的描边/投影数值会被预设覆盖，要自己调就选 manual。",
        }),
        "use_stroke": ("BOOLEAN", {
            "default": True,
            "tooltip": "描边开关（仅 style=manual 生效，其余预设会接管）。\n"
                       "描边是沿文字外圈描的一圈边，在明暗变化大的镜头上比字本身还显眼 ——\n"
                       "觉得水印太重，优先降 stroke_opacity，而不是直接关掉。",
        }),
        "stroke_width": ("INT", {
            "default": 3, "min": 0, "max": 24, "step": 1,
            "tooltip": "描边粗细（像素）。只在描边打开时生效。画面明暗变化大时给 2~4 就够。",
        }),
        "stroke_color": ("STRING", {
            "default": "#000000",
            "tooltip": "描边颜色。",
        }),
        "stroke_opacity": ("FLOAT", {
            "default": 0.55, "min": 0.0, "max": 1.0, "step": 0.01,
            "tooltip": "描边自身的不透明度 —— 觉得描边太重就先降这个，比直接关掉更保留可读性。\n"
                       "1.0 = 实心黑边（最显眼）；0.5~0.6 = 柔和一圈（默认）；0 = 等于关掉描边。",
        }),
        "use_shadow": ("BOOLEAN", {
            "default": True,
            "tooltip": "投影开关（仅 style=manual 生效）。\n"
                       "投影把轮廓往外晕开一点：读得清，却不像描边那样在画面上糊一圈硬边。\n"
                       "⚠ 深色投影在夜景 / 黑幕上是隐形的，纯暗调画面请靠描边（或把 shadow_color 调亮）。",
        }),
        "shadow_color": ("STRING", {
            "default": "#000000",
            "tooltip": "投影颜色。纯暗调画面里深色投影看不见，可改成 #FFFFFF 之类亮色。",
        }),
        "shadow_opacity": ("FLOAT", {
            "default": 0.4, "min": 0.0, "max": 1.0, "step": 0.01,
            "tooltip": "投影自身的不透明度。0.3~0.5 是「看得见轮廓但不抢眼」的甜区。",
        }),
        "shadow_offset": ("INT", {
            "default": 5, "min": -80, "max": 80, "step": 1,
            "tooltip": "投影偏移（像素，向右下为正）。4~8 像自然投影；\n"
                       "0 则变成四周对称的柔和光晕，观感更轻，贴角时也不占边距。",
        }),
        "shadow_blur": ("INT", {
            "default": 8, "min": 0, "max": 100, "step": 1,
            "tooltip": "投影模糊半径（像素）。越大越柔。6~14 自然；0 = 硬边（等于把字复制一份）。",
        }),
        "angle": ("FLOAT", {
            "default": 0.0, "min": -180.0, "max": 180.0, "step": 0.5,
            "tooltip": "水印整体旋转角度。平铺时配 -20~-30 度最难对齐抹除。",
        }),
    }
    d.update(_font_widgets())
    d.update({
        "float_path": (R.FLOAT_PATHS, {
            "default": "diagonal",
            "tooltip": "floating 模式的活动轨迹：\n"
                       "diagonal / horizontal / vertical  匀速来回（三角波，端点不减速）\n"
                       "circle                            椭圆环路\n"
                       "random                            均匀随机跳位，防盗最强但位置会突变",
        }),
        "float_cycles": ("FLOAT", {
            "default": 1.0, "min": 0.1, "max": 200.0, "step": 0.1,
            "tooltip": "floating 模式：整段视频内来回走完的圈数。\n"
                       "1 = 整段走一个来回（很慢，适合长视频）；4~8 = 明显游走但仍看得清。\n"
                       "random 轨迹下含义变为「位置切换次数」，建议设成 2×视频秒数（约每 0.5 秒跳一次）。\n"
                       "单张图片上没有「走」这回事：位置由 seed 定死成一个点，每次跑都一样。",
        }),
        "seed": ("INT", {
            "default": 0, "min": 0, "max": 0xFFFFFFFF, "step": 1,
            "tooltip": "仅 random 轨迹使用，固定后每次生成的位置一致，便于复现。",
        }),
        "start_pct": ("FLOAT", {
            "default": 0.0, "min": 0.0, "max": 1.0, "step": 0.001,
            "tooltip": "水印出现的起始位置（占视频总长的比例）。0 = 片头就出现。\n"
                       "只对多帧序列有意义：单张图片整张算第 0 帧，这一项不影响它。",
        }),
        "end_pct": ("FLOAT", {
            "default": 1.0, "min": 0.0, "max": 1.0, "step": 0.001,
            "tooltip": "水印消失的位置（占总长比例）。1 = 一直留到片尾。\n"
                       "例：0.6 → 1.0 表示只在后 40% 出现。\n"
                       "只对多帧序列有意义：单张图片整张算第 0 帧，这一项不影响它。",
        }),
        "fade_frames": ("INT", {
            "default": 0, "min": 0, "max": 240, "step": 1,
            "tooltip": "出现 / 消失时的淡入淡出帧数，0 = 硬切。\n"
                       "只对多帧序列有意义：单张图片没有淡入淡出可做，这一项不影响它。",
        }),
        "tile_gap": ("INT", {
            "default": 90, "min": 0, "max": 1200, "step": 2,
            "tooltip": "tile 模式下水印之间的间距（像素）。",
        }),
    })
    return d


_LOGO_LINKS = {
    "logo": ("IMAGE", {
        "tooltip": "可选。带 alpha 通道的 PNG logo。接上后把 use_logo 打开才会生效。\n"
                   "透明度优先取 logo_mask；没接 mask 就用图片自带的 alpha 通道。",
    }),
    "logo_mask": ("MASK", {
        "tooltip": "可选。logo 的透明度遮罩，留空则用 logo 图片自带 alpha。\n"
                   "ComfyUI 的「加载图像」会把 PNG 透明通道单独输出成 MASK，直接接过来即可。",
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
        "tooltip": "可选。从外部接入文字（接上游拼字符串的节点，例如 String Function）。\n"
                   "接了线且内容非空 → **以连线为准**，面板里手填的文字自动让位；\n"
                   "断线、或上游传空字符串 → 回落到面板手填的文字。\n"
                   "典型用法：跑参数对比（侧视图 / 不同分辨率 / 不同 LoRA 强度 / 不同 seed）时，\n"
                   "把这一轮的参数拼成文字烧进画面，回看结果时一眼就知道是哪一套。\n"
                   "注意：它只吃「一段字符串」，节点不会替你填任何值 —— 要显示什么就在上游拼什么。",
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
    return "外部输入" if _ext_text(text_in) else "面板文字"


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
        _log(f"字体解析失败，改用内置兜底字体：{e}")
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
            _log(f"连线 logo 解析失败，改用 logo_file：{e}")

    name = (logo_file or "").strip()
    if name:
        try:
            rgba = LF.load_logo_rgba(name)
            if rgba is not None:
                return rgba
            _log(f"logo 文件读取失败（已忽略 logo）：{name}")
        except Exception as e:                            # noqa: BLE001
            _log(f"logo 文件读取异常（已忽略 logo）：{type(e).__name__}: {e}")
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
        _log(f"音频补静音失败，原样透传：{e}")
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
    DESCRIPTION = ("给逐帧图像打水印：四角固定 / 居中低透明 / 浮动 / 平铺。\n"
                   "视频流程：不绑定任何视频模型，H3、Wan、LTX、VHS 等 IMAGE 批次都能挂。\n"
                   "单张照片也直接用它 —— 一张图就是长度为 1 的批次，不必另开节点，"
                   "排版按这张图的宽高实时算。\n"
                   "批量处理一整包照片请交给专门的批处理工作流，本节点只管水印本身。\n"
                   "输出是新张量，不会改写上游数据。")

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
            _log(f"渲染失败，已原样透传（不中断工作流）：{type(e).__name__}: {e}")
            return (_to_tensor(np.asarray(arr, dtype=np.float32)),)

        if stamp.shape[0] > 2 and stamp.shape[1] > 2:
            _log(f"Overlay {mode}/{position} · {num_frames} 帧 · {w}×{h} · "
                 f"图章 {stamp.shape[1]}×{stamp.shape[0]} · 不透明度 {opacity} · "
                 f"{style}（描边{'开' if draw_stroke else '关'} / 投影{'开' if draw_shadow else '关'}）"
                 + (f" · 文字{_text_source(text_in)}" if use_text else ""))
        else:
            _log("Overlay 跳过：没有可绘制的内容（文字为空且未启用 logo）")
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
                "tooltip": "视频帧率，用来把「秒数」换算成帧数。\n"
                           "必须和最终合成视频的帧率一致，否则时长会不对（H3 常出 24fps）。",
            }),
            "where": (["head", "tail", "both"], {
                "default": "head",
                "tooltip": "head 只在片头加，tail 只在片尾加，both 两头都加（各占一份 seconds）。",
            }),
            "seconds": ("FLOAT", {
                "default": 2.0, "min": 0.1, "max": 60.0, "step": 0.1,
                "tooltip": "卡片时长（秒）。片尾版权声明 2 秒左右比较合适。",
            }),
            "text": ("STRING", {
                "default": "© 2026 kaero\n版权所有 · 禁止转载",
                "multiline": True,
                "tooltip": "卡片文字，支持多行。",
            }),
            "use_text": ("BOOLEAN", {"default": True, "tooltip": "关掉则只显示 logo。"}),
            "bg_color": ("STRING", {
                "default": "#000000",
                "tooltip": "卡片底色，默认纯黑。",
            }),
            "use_logo": ("BOOLEAN", {
                "default": False,
                "tooltip": "打开才会绘制 logo。图片来源同 Overlay：面板上传，或把 IMAGE 接到 logo 口。",
            }),
            "layout": (R.LAYOUTS, {
                "default": "vertical",
                "tooltip": "logo 与文字同时存在时的排布：vertical 上下排（logo 在上），horizontal 左右排（logo 在左）。",
            }),
            "logo_scale": ("FLOAT", {
                "default": 30.0, "min": 1.0, "max": 100.0, "step": 0.5,
                "tooltip": "logo 宽度占画面宽度的百分比。",
            }),
            "text_scale": ("FLOAT", {
                "default": 24.0, "min": 1.0, "max": 100.0, "step": 0.5,
                "tooltip": "文字宽度占画面宽度的百分比。中文片尾字幕 20~30 比较大气。",
            }),
            "text_color": ("STRING", {"default": "#FFFFFF", "tooltip": "卡片文字颜色。"}),
            "text_stroke_width": ("INT", {
                "default": 0, "min": 0, "max": 24, "step": 1,
                "tooltip": "文字描边粗细。底色不是纯黑时建议给 2~4 保证可读性。",
            }),
            "text_stroke_color": ("STRING", {"default": "#000000", "tooltip": "文字描边颜色。"}),
        }
        widgets.update(_font_widgets())
        widgets.update({
            "fade_frames": ("INT", {
                "default": 8, "min": 0, "max": 240, "step": 1,
                "tooltip": "卡片淡入淡出帧数。黑底卡片下视觉上就是文字/logo 渐显渐隐；0 = 硬切。",
            }),
            "pad_audio": ("BOOLEAN", {
                "default": True,
                "tooltip": "给音频补等长静音，保证加了片头后音画不错位。\n"
                           "接音乐轨时务必保持打开。",
            }),
        })
        links = dict(TEXT_IN_LINK)
        links.update(_LOGO_LINKS)
        links["audio"] = ("AUDIO", {
            "tooltip": "可选。视频音轨。接进来才会做静音补齐，并从这个端口原样输出。",
        })
        return {"required": _with_logo(widgets), "optional": links}

    RETURN_TYPES = ("IMAGE", "AUDIO")
    RETURN_NAMES = ("images", "audio")
    FUNCTION = "apply"
    CATEGORY = CATEGORY
    DESCRIPTION = ("在片段头尾插入黑幕版权卡片（文字 + logo），可选补齐音频静音以保证音画同步。"
                   "没接音频时音频输出为空。")

    def apply(self, images, fps=24.0, where="head", seconds=2.0,
              text="© 2026 kaero\n版权所有 · 禁止转载", use_text=True, bg_color="#000000",
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
            _log(f"卡片渲染失败，已原样透传（不中断工作流）：{type(e).__name__}: {e}")
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

        _log(f"Title {where} · 追加 {count * (2 if where == 'both' else 1)} 帧 · {w}×{h} @ {fps:g}fps "
             f"→ 总帧数 {out.shape[0]}"
             + ("（音频已补静音）" if audio is not None and pad_audio else "")
             + (f" · 文字{_text_source(text_in)}" if use_text else ""))
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
                    "tooltip": "片头 / 片尾黑幕版权卡片。off = 不加。",
                }),
                "title_seconds": ("FLOAT", {
                    "default": 2.0, "min": 0.1, "max": 60.0, "step": 0.1,
                    "tooltip": "卡片时长（秒）。帧率取自输入视频，自动换算帧数。",
                }),
                "title_text": ("STRING", {
                    "default": "",
                    "multiline": True,
                    "tooltip": "卡片文字。留空则复用上面的 text。",
                }),
                "title_bg_color": ("STRING", {
                    "default": "#000000",
                    "tooltip": "卡片底色。",
                }),
            })
            return {"required": _with_logo(widgets), "optional": dict(TEXT_IN_LINK, **_LOGO_LINKS)}

        RETURN_TYPES = ("VIDEO",)
        RETURN_NAMES = ("video",)
        FUNCTION = "apply"
        CATEGORY = CATEGORY
        DESCRIPTION = ("一步到位：对 VIDEO 做画面水印 + 片头片尾卡片，音频自动同步。"
                       "需要精细控制时，改用 Overlay + Title 两个节点串起来。")

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
                _log(f"渲染失败，已原样透传（不中断工作流）：{type(e).__name__}: {e}")
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
                    _log(f"卡片渲染失败，本节点只输出画面水印：{type(e).__name__}: {e}")
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

            _log(f"Video {mode}/{position} · {num_frames}→{out.shape[0]} 帧 · {w}×{h} @ {fps:g}fps"
                 f" · {style}（描边{'开' if draw_stroke else '关'} / 投影{'开' if draw_shadow else '关'}）"
                 + (f" · 卡片 {title_mode}" if title_mode != "off" else "")
                 + (f" · 文字{_text_source(text_in)}" if use_text else ""))

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
    "VideoMarkOverlay": "VideoMark Overlay（画面水印）",
    "VideoMarkTitle": "VideoMark Title（片头片尾版权页）",
}

if HAS_VIDEO_TYPE:
    NODE_CLASS_MAPPINGS["VideoMarkVideo"] = VideoMarkVideo
    NODE_DISPLAY_NAME_MAPPINGS["VideoMarkVideo"] = "VideoMark Video（视频一站式）"
else:
    print(f"[VideoMark] 未能导入 VIDEO 类型，已跳过 VideoMark Video 节点：{_VIDEO_IMPORT_ERROR}")
