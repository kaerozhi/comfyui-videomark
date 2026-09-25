# -*- coding: utf-8 -*-
"""
comfyui-videomark 离线自测
==========================
不启动 ComfyUI，直接跑渲染核心 + 节点类，产出样张 PNG 供肉眼核对。

用法：
    python tools\\selftest.py

产出目录：包根目录下的 preview/
"""

from __future__ import annotations

import os
import sys
import traceback
from fractions import Fraction

import numpy as np
from PIL import Image

PKG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMFY_DIR = r"D:\AI\ComfyUI"
OUT_DIR = os.path.join(PKG_DIR, "preview")

sys.path.insert(0, COMFY_DIR)          # 让 comfy_api 能被导入
sys.path.insert(0, PKG_DIR)

import render as R                                                    # noqa: E402
import fonts as F                                                     # noqa: E402

PASS, FAIL = [], []


def check(name, fn):
    try:
        fn()
        PASS.append(name)
        print(f"  [OK]   {name}")
    except Exception as e:                                            # noqa: BLE001
        FAIL.append((name, traceback.format_exc()))
        print(f"  [FAIL] {name}: {type(e).__name__}: {e}")


# =====================================================================
# 造测试素材
# =====================================================================

def make_frame(w: int, h: int, seed: int = 0, dark: bool = False) -> np.ndarray:
    """造一张有明暗层次的假画面，方便看清水印。"""
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    base = (yy / max(1, h - 1)) * 0.55 + (xx / max(1, w - 1)) * 0.35
    img = np.stack([base * 0.95, base * 0.7 + 0.15, base * 0.5 + 0.3], axis=2)
    if dark:
        img *= 0.28
    # 几个圆形色块，模拟画面主体
    rng = np.random.default_rng(seed)
    for _ in range(5):
        cx, cy = rng.uniform(0, w), rng.uniform(0, h)
        r = rng.uniform(0.05, 0.16) * min(w, h)
        m = ((xx - cx) ** 2 + (yy - cy) ** 2) <= r * r
        col = rng.uniform(0.15, 0.95, size=3).astype(np.float32)
        img[m] = img[m] * 0.35 + col * 0.65
    return np.clip(img, 0, 1).astype(np.float32)


def make_logo(size: int = 256) -> np.ndarray:
    """造一个带 alpha 的圆形 logo（RGBA float32）。"""
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    c = (size - 1) / 2.0
    r = ((xx - c) ** 2 + (yy - c) ** 2) ** 0.5
    alpha = np.clip((size * 0.47 - r) / (size * 0.03), 0, 1)
    img = np.zeros((size, size, 4), dtype=np.float32)
    inner = np.clip((size * 0.40 - r) / (size * 0.04), 0, 1)
    img[:, :, 0] = 1.0 - inner * 0.85
    img[:, :, 1] = 0.86 - inner * 0.6
    img[:, :, 2] = 0.35 + inner * 0.55
    img[:, :, 3] = alpha
    return img


def save_png(arr: np.ndarray, name: str) -> str:
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, name)
    a = np.clip(np.asarray(arr, dtype=np.float32), 0, 1)
    if a.shape[2] == 4:
        Image.fromarray((a * 255).astype(np.uint8), mode="RGBA").save(path)
    else:
        Image.fromarray((a * 255).astype(np.uint8), mode="RGB").save(path)
    return path


def stamp_with_style(style: str, **kw) -> np.ndarray:
    """
    按节点里的某个样式预设渲染图章。

    样张必须走这条路径 —— 否则样张展示的样式和用户实际拿到的默认值会脱节，
    「默认太重，样张里却看不出来」这类问题就是这么漏掉的。
    """
    us, ush, so, sho = R.resolve_style(style, True, True, 0.55, 0.4)
    kw.setdefault("stroke_width", 3)
    kw.setdefault("shadow_offset_x", 5)
    kw.setdefault("shadow_offset_y", 5)
    kw.setdefault("shadow_blur", 8)
    return R.build_stamp(use_stroke=us, stroke_opacity=so,
                         use_shadow=ush, shadow_opacity=sho, **kw)


def row(images, gap=6) -> np.ndarray:
    """横向拼图（高度需一致）。"""
    images = [np.asarray(i, np.float32) for i in images]
    h = max(i.shape[0] for i in images)
    out_w = sum(i.shape[1] for i in images) + gap * (len(images) - 1)
    out = np.zeros((h, out_w, 3), np.float32)
    x = 0
    for i in images:
        out[: i.shape[0], x:x + i.shape[1]] = i[:, :, :3]
        x += i.shape[1] + gap
    return out


def col(images, gap=6) -> np.ndarray:
    images = [np.asarray(i, np.float32) for i in images]
    w = max(i.shape[1] for i in images)
    out_h = sum(i.shape[0] for i in images) + gap * (len(images) - 1)
    out = np.zeros((out_h, w, 3), np.float32)
    y = 0
    for i in images:
        out[y:y + i.shape[0], : i.shape[1]] = i[:, :, :3]
        y += i.shape[0] + gap
    return out


def label_bar(text: str, w: int, h: int = 34) -> np.ndarray:
    """给样张加个中文标题条。"""
    img = Image.new("RGB", (w, h), (24, 24, 28))
    from PIL import ImageDraw
    d = ImageDraw.Draw(img)
    d.text((10, h // 2), text, font=F.load_font(_FONT_PATH, 20), fill=(240, 240, 240), anchor="lm")
    return np.asarray(img).astype(np.float32) / 255.0


def crop_zoom(img: np.ndarray, x: int, y: int, w: int, h: int, zoom: float = 3.0) -> np.ndarray:
    """
    裁一小块再放大。

    样式类样张必须这么做：整帧缩到一行里，描边和投影的差别根本看不出来，
    只有把水印那块放大三五倍，才能核对轮廓晕开的程度。
    """
    a = np.asarray(img, dtype=np.float32)
    x, y = max(0, int(x)), max(0, int(y))
    patch = a[y:y + int(h), x:x + int(w), :3]
    if patch.size == 0:
        return np.zeros((2, 2, 3), np.float32)
    im = Image.fromarray((np.clip(patch, 0, 1) * 255).astype(np.uint8), mode="RGB")
    im = im.resize((max(1, int(im.width * zoom)), max(1, int(im.height * zoom))), Image.LANCZOS)
    return np.asarray(im).astype(np.float32) / 255.0


W, H = 854, 480          # 用横屏，接近视频比例
_FONT_PATH = None


# =====================================================================
# 测试项
# =====================================================================

def t_fonts():
    table = F.get_font_table()
    assert table, "一个字体都没找到"
    print(f"         字体候选命中 {len(table)} 个，默认：{F.default_font_label()}")
    p, i = F.resolve_font(F.default_font_label(), "")
    assert p and os.path.isfile(p), f"解析出的字体文件不存在：{p}"


def t_stamp_text():
    s = R.build_stamp(img_w=W, img_h=H, text="© 2026 kaero", scale_pct=20,
                      color=(255, 255, 255), stroke_width=2)
    assert s.shape[2] == 4 and s.shape[0] > 4 and s.shape[1] > 4, s.shape
    assert s[:, :, 3].max() > 0.5, "图章完全透明"
    want = W * 0.20
    assert abs(s.shape[1] - want) < want * 0.06, f"宽度没对齐 target：{s.shape[1]} vs {want}"


def t_stamp_multiline():
    one = R.build_stamp(img_w=W, img_h=H, text="© 2026 kaero", scale_pct=20)
    two = R.build_stamp(img_w=W, img_h=H, text="© 2026 kaero\n禁止转载", scale_pct=20)
    assert two.shape[0] > one.shape[0], "多行没有变高"


def t_stamp_logo():
    logo = make_logo()
    s = R.build_stamp(img_w=W, img_h=H, use_text=False, use_logo=True, logo_rgba=logo,
                      scale_pct=15)
    target = W * 0.15
    assert s.shape[2] == 4 and s[:, :, 3].max() > 0.5
    # 源图自带的透明边会被裁掉，所以带内边距的 logo 会略窄于 target，这是预期行为
    assert target * 0.85 <= s.shape[1] <= target * 1.02, f"{s.shape[1]} vs {target}"


def t_stamp_logo_and_text():
    logo = make_logo()
    v = R.build_stamp(img_w=W, img_h=H, text="© kaero", use_logo=True, logo_rgba=logo,
                      scale_pct=18, layout="vertical")
    h = R.build_stamp(img_w=W, img_h=H, text="© kaero", use_logo=True, logo_rgba=logo,
                      scale_pct=18, layout="horizontal")
    assert v.shape[0] > h.shape[0], "竖排应该比横排高"
    assert h.shape[1] > v.shape[1], "横排应该比竖排宽"


def t_rotate():
    a = R.build_stamp(img_w=W, img_h=H, text="© 2026 kaero", scale_pct=20)
    b = R.build_stamp(img_w=W, img_h=H, text="© 2026 kaero", scale_pct=20, angle=-25)
    assert b.shape[0] > a.shape[0], "旋转后高度应变大"


def t_positions():
    kw = dict(num_frames=8, img_w=W, img_h=H, stamp_w=200, stamp_h=60, margin=32)
    assert R.frame_positions(mode="corner", position="top_left", **kw)[0] == (32, 32)
    assert R.frame_positions(mode="corner", position="bottom_right", **kw)[0] == (W - 200 - 32, H - 60 - 32)
    cx, cy = R.frame_positions(mode="center", position="center", **kw)[0]
    assert abs(cx - (W - 200) // 2) <= 1 and abs(cy - (H - 60) // 2) <= 1
    fl = R.frame_positions(mode="floating", position="bottom_right", float_path="diagonal",
                           float_cycles=3, seed=0, **kw)
    assert len(set(fl)) >= 4, f"对角线轨迹位置太单一：{fl}"
    for x, y in fl:
        assert 32 <= x <= W - 200 - 32 and 32 <= y <= H - 60 - 32, f"越界：{x},{y}"


def t_watermark_shapes():
    frames = np.stack([make_frame(W, H, i) for i in range(6)])
    stamp = R.build_stamp(img_w=W, img_h=H, text="© 2026 kaero", scale_pct=20)
    out = R.apply_watermark(frames, stamp, mode="corner", position="bottom_right",
                            margin=32, opacity=0.85)
    assert out.shape == frames.shape
    assert not np.allclose(out, frames), "完全没画上去"
    assert np.allclose(frames[0, 0, 0], out[0, 0, 0]), "左上角不该被改动"


def t_watermark_passthrough():
    """空文字 + 不启用 logo → 图章为空 → 原样返回，不应该崩。"""
    frames = np.stack([make_frame(W, H, i) for i in range(3)])
    stamp = R.build_stamp(img_w=W, img_h=H, text="", use_text=True, use_logo=False)
    out = R.apply_watermark(frames, stamp, mode="corner")
    assert out.shape == frames.shape and np.allclose(out, frames)


def t_range_and_fade():
    frames = np.zeros((10, 64, 128, 3), np.float32) + 0.5
    stamp = R.build_stamp(img_w=128, img_h=64, text="IN", scale_pct=30)
    out = R.apply_watermark(frames, stamp, mode="center", margin=8, opacity=1.0,
                            start_pct=0.5, end_pct=1.0, fade_frames=2)
    assert np.allclose(out[0], frames[0]), "前半段不该有水印"
    assert not np.allclose(out[9], frames[9]), "后半段应该有水印"


def t_tile_covers():
    frames = np.zeros((1, H, W, 3), np.float32) + 0.5
    stamp = R.build_stamp(img_w=W, img_h=H, text="© kaero", scale_pct=12)
    out = R.apply_watermark(frames, stamp, mode="tile", tile_gap=60, opacity=0.5)
    ink = np.abs(out[0] - frames[0]).sum(axis=2) > 1e-3
    # 平铺应该覆盖画面的每一块区域：四角都要有内容
    quads = [ink[: H // 2, : W // 2].any(), ink[: H // 2, W // 2:].any(),
             ink[H // 2:, : W // 2].any(), ink[H // 2:, W // 2:].any()]
    assert all(quads), f"平铺没有覆盖全部四个象限：{quads}"


def t_title():
    card = R.make_title_frames(img_w=W, img_h=H, count=4, bg_color=(0, 0, 0),
                               text="© 2026 kaero\n版权所有 · 禁止转载", text_scale_pct=24,
                               fade_frames=2)
    assert card.shape == (4, H, W, 3), card.shape
    assert card[0].mean() <= card[3].mean() + 1e-6, "淡入方向不对"
    assert card[:, :2, :, :].max() < 0.02, "边缘应该还是黑底"


def t_silence():
    s = R.make_silence(44100, 2.0, 2)
    assert s.shape == (1, 2, 88200), s.shape


def t_node_overlay():
    import torch
    import nodes as N
    node = N.VideoMarkOverlay()
    frames = np.stack([make_frame(W, H, i) for i in range(4)])
    t = torch.from_numpy(frames)
    (out,), = (node.apply(t, mode="corner", position="bottom_right", text="© 2026 kaero",
                          opacity=0.8, scale=20, margin=32),)
    assert out.shape == t.shape and out.dtype == torch.float32
    assert not torch.allclose(out, t)
    (same,), = (node.apply(t, text="", use_text=False, use_logo=False),)
    assert torch.allclose(same, t), "无内容时应原样返回"


def t_node_overlay_logo():
    """两种形态都要能吃：ComfyUI 传的是批次（4D/3D），但单张（3D/2D）也得认。"""
    import torch
    import nodes as N
    node = N.VideoMarkOverlay()
    t = torch.from_numpy(np.stack([make_frame(W, H, 1)]))
    single = torch.from_numpy(make_logo())                       # [H,W,4]
    batched = torch.from_numpy(make_logo()[None, ...])           # [1,H,W,4]
    mask_single = torch.from_numpy(np.ascontiguousarray(make_logo()[:, :, 3]))       # [H,W]
    mask_batched = torch.from_numpy(np.ascontiguousarray(make_logo()[:, :, 3][None]))  # [1,H,W]

    for name, lg, mk in (("单张 logo + 单张 mask", single, mask_single),
                         ("批次 logo + 批次 mask", batched, mask_batched),
                         ("批次 logo + 单张 mask", batched, mask_single)):
        (out,), = (node.apply(t, mode="corner", use_logo=True, logo=lg, logo_mask=mk,
                              use_text=True, text="© 2026 kaero", opacity=0.9),)
        assert out.shape == t.shape, (name, out.shape)
        assert not torch.allclose(out, t), f"{name}: 没画上去"

    # 图章必须是方形量级——若把单张图误当批次剥维，会渲染出一条细长条
    import render as R2
    lg = R2.logo_to_rgba(make_logo(), None)
    stamp = R2.build_stamp(img_w=W, img_h=H, use_text=False, use_logo=True,
                           logo_rgba=lg, scale_pct=15)
    ratio = stamp.shape[0] / stamp.shape[1]
    assert 0.8 <= ratio <= 1.25, f"方形 logo 渲染出了长条：{stamp.shape}"


def t_node_overlay_still():
    """单张照片这条路：真文件 → 照 Load Image 的方式解码 → Overlay → 存回磁盘。

    这是主用法（批量处理交给专门的批处理工作流，本包只负责把一张图打对）。
    三条必须守住的性质：
      1. 单张图（批次长度 1）一定会被打上；
      2. 时间轴参数动不了它 —— start_pct / end_pct 在 num_frames=1 时两端都是第 0 帧，
         所以就算拖到 0.5 也不会把水印算没（tooltip 里就是这么承诺的）；
      3. 输出形状 / 类型不变，可以直接接 Save Image。
    """
    import shutil
    import tempfile
    import torch
    import nodes as N

    node = N.VideoMarkOverlay()
    tmp = tempfile.mkdtemp(prefix="videomark_still_")
    try:
        for w, h, tag in ((1200, 800, "landscape"), (800, 1200, "portrait")):
            src = os.path.join(tmp, f"{tag}.jpg")
            Image.fromarray((np.clip(make_frame(w, h, seed=w), 0, 1) * 255).astype(np.uint8)
                            ).save(src, quality=95)
            back = np.asarray(Image.open(src).convert("RGB"), dtype=np.float32) / 255.0
            assert back.shape == (h, w, 3), (tag, back.shape)

            t = torch.from_numpy(back[None, ...])            # [1,H,W,3]，与 Load Image 一致
            (out,), = (node.apply(t, mode="corner", position="bottom_right",
                                  text="© 2026 kaero", opacity=0.85, scale=20, margin=32),)
            assert out.shape == t.shape and out.dtype == torch.float32, \
                (tag, tuple(out.shape), out.dtype)
            assert not torch.allclose(out, t), f"{tag}: 单张照片没被打上水印"

            # 水印该在右下角，左上角一个像素都不该动
            diff = (out[0] - t[0]).abs().sum(dim=2).numpy()
            br = float(diff[int(h * 0.7):, int(w * 0.6):].max())
            tl = float(diff[:int(h * 0.3), :int(w * 0.4)].max())
            assert br > 0.05, f"{tag}: 右下角没有水印（最大差值 {br}）"
            assert tl < 1e-6, f"{tag}: 左上角不该被动过（最大差值 {tl}）"

            # 时间轴参数对单张图无效：极端值也不许把水印藏掉
            (out2,), = (node.apply(t, mode="corner", text="© 2026 kaero", opacity=0.85,
                                   start_pct=0.5, end_pct=1.0, fade_frames=12),)
            assert not torch.allclose(out2, t), f"{tag}: 时间轴参数把单张图的水印藏掉了"

            # 其余三种方式在单张图上同样成立
            for mode in ("tile", "center", "floating"):
                (m,), = (node.apply(t, mode=mode, text="© 2026 kaero", opacity=0.5),)
                assert not torch.allclose(m, t), f"{tag}/{mode}: 没画上去"

            # 存回磁盘（模拟 Save Image 的输入），确认不是「只在内存里好看」
            dst = os.path.join(tmp, f"wm_{tag}.jpg")
            Image.fromarray((out[0].clamp(0, 1).numpy() * 255).astype(np.uint8)).save(dst, quality=95)
            chk = np.asarray(Image.open(dst).convert("RGB"), dtype=np.float32) / 255.0
            assert float(np.abs(chk - back).mean()) > 1e-4, f"{tag}: 存盘后与输入图无差别"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def t_node_title():
    import torch
    import nodes as N
    node = N.VideoMarkTitle()
    t = torch.from_numpy(np.stack([make_frame(W, H, i) for i in range(5)]))
    wf = torch.zeros(1, 2, 44100)
    audio = {"waveform": wf, "sample_rate": 44100}
    (out, a2), = (node.apply(t, fps=24.0, where="both", seconds=2.0,
                            text="© 2026 kaero", pad_audio=True, audio=audio),)
    assert out.shape[0] == 5 + 48 * 2, out.shape
    assert a2["waveform"].shape[-1] == 44100 + int(44100 * 4), a2["waveform"].shape
    assert a2["sample_rate"] == 44100
    (out2, a3), = (node.apply(t, fps=24.0, where="head", seconds=1.0, pad_audio=False,
                             audio=audio),)
    assert out2.shape[0] == 5 + 24 and a3["waveform"].shape[-1] == 44100


def t_node_video():
    import torch
    import nodes as N
    if not N.HAS_VIDEO_TYPE:
        raise RuntimeError("VIDEO 类型不可用，跳过")
    from comfy_api.latest import Types
    src = torch.from_numpy(np.stack([make_frame(W, H, i) for i in range(24)]))
    comp = Types.VideoComponents(
        images=src,
        audio={"waveform": torch.zeros(1, 2, 48000), "sample_rate": 48000},
        frame_rate=Fraction(24),
    )
    video = N.VideoFromComponents(comp, bit_depth=8, color_space="sRGB")
    node = N.VideoMarkVideo()
    (out_video,) = node.apply(video, mode="corner", position="bottom_right",
                              text="© 2026 kaero", opacity=0.8, scale=20, margin=32,
                              title_mode="head", title_seconds=1.0, seed=0)
    gc = out_video.get_components()
    assert gc.images.shape[0] == 24 + 24, gc.images.shape
    assert gc.images.shape[1:] == src.shape[1:], gc.images.shape
    assert abs(float(gc.frame_rate) - 24.0) < 1e-6
    assert gc.audio is not None and gc.audio["waveform"].shape[-1] == 48000 + 48000
    assert not torch.allclose(gc.images[30], src[6]), "画面水印没生效"


def t_input_types():
    import nodes as N
    for cls in (N.VideoMarkOverlay, N.VideoMarkTitle, getattr(N, "VideoMarkVideo", None)):
        if cls is None:
            continue
        spec = cls.INPUT_TYPES()
        for bucket in ("required", "optional"):
            for key, val in spec.get(bucket, {}).items():
                assert isinstance(val, (tuple, list)) and len(val) >= 1, f"{cls.__name__}.{key} 格式不对"
                t = val[0]
                assert isinstance(t, (str, list)), f"{cls.__name__}.{key} 类型声明不对：{t}"
                if isinstance(t, list):
                    assert t, f"{cls.__name__}.{key} 下拉列表为空"
                    if len(val) > 1 and isinstance(val[1], dict) and "default" in val[1]:
                        assert val[1]["default"] in t, f"{cls.__name__}.{key} 默认值不在选项里"
        print(f"         {cls.__name__}: required {len(spec.get('required', {}))} 项 / "
              f"optional {len(spec.get('optional', {}))} 项，FUNCTION={cls.FUNCTION}")


# ---------------------------------------------------------------------
# 控件槽位冻结表 —— 老工作流兼容的「契约」，不是随便能改的清单
# ---------------------------------------------------------------------
# ComfyUI 的工作流按**位置**存控件值（widgets_values 是数组，不是字典）。
# 所以这份顺序 == 用户手里所有老工作流的兼容契约：
#   · 新增参数只能**追加到末尾**（老工作流存的前 N 个值一一对上，多出来的槽取默认值）；
#   · 往中间插一个，后面所有值整体右移一格，加载时报一串牛头不对马嘴的错
#     （logo_file 当年就这么坏过一次：float_path 拿到旧 float_cycles…）；
#   · **唯一能随便插的加法是 forceInput / socketless / hidden 的连线口** ——
#     它们不生成 widget，也就不占槽位（text_in 正是这一类）。
# 改这张表之前，先确认自己不是在把老工作流弄坏。
FROZEN_WIDGETS = {
    "VideoMarkOverlay": (
        "mode", "position", "text", "opacity", "scale", "margin",
        "use_text", "use_logo", "layout", "color", "style", "use_stroke",
        "stroke_width", "stroke_color", "stroke_opacity", "use_shadow", "shadow_color",
        "shadow_opacity", "shadow_offset", "shadow_blur", "angle", "font", "font_file",
        "float_path", "float_cycles", "seed", "seed.__control_after_generate",
        "start_pct", "end_pct", "fade_frames", "tile_gap", "logo_file",
    ),
    "VideoMarkTitle": (
        "fps", "where", "seconds", "text", "use_text", "bg_color",
        "use_logo", "layout", "logo_scale", "text_scale", "text_color", "text_stroke_width",
        "text_stroke_color", "font", "font_file", "fade_frames", "pad_audio", "logo_file",
    ),
    "VideoMarkVideo": (
        "mode", "position", "text", "opacity", "scale", "margin",
        "use_text", "use_logo", "layout", "color", "style", "use_stroke",
        "stroke_width", "stroke_color", "stroke_opacity", "use_shadow", "shadow_color",
        "shadow_opacity", "shadow_offset", "shadow_blur", "angle", "font", "font_file",
        "float_path", "float_cycles", "seed", "seed.__control_after_generate",
        "start_pct", "end_pct", "fade_frames", "tile_gap", "title_mode", "title_seconds",
        "title_text", "title_bg_color", "logo_file",
    ),
}

# 本包声明里出现过的连线类型。声明里若新增别的连线类型（CLIP/VAE…），
# 这里的槽位复刻会多算一格而报警 —— 宁可误报，也不要用「少算一格」把它放过。
_LINK_TYPES = {"IMAGE", "MASK", "AUDIO", "VIDEO", "LATENT"}


def _widget_slots(cls):
    """复刻前端会为这个节点建出哪些控件槽（含 seed 后面的 control_after_generate）。"""
    it = cls.INPUT_TYPES()
    out = []
    for bucket in ("required", "optional"):
        for name, val in (it.get(bucket) or {}).items():
            opt = val[1] if len(val) > 1 and isinstance(val[1], dict) else {}
            if any(opt.get(k) for k in ("forceInput", "socketless", "hidden")):
                continue                                  # 只长连线口，不占槽位
            typ = val[0]
            if not isinstance(typ, list) and (not isinstance(typ, str)
                                              or typ.upper() in _LINK_TYPES):
                continue
            out.append(name)
            if isinstance(typ, str) and typ == "INT" and name in ("seed", "noise_seed"):
                out.append(name + ".__control_after_generate")
    return out


def t_widget_slots_frozen():
    import nodes as N
    for name, expect in FROZEN_WIDGETS.items():
        cls = N.NODE_CLASS_MAPPINGS.get(name)
        assert cls is not None, f"{name} 不见了"
        got = _widget_slots(cls)
        assert got == list(expect), (
            f"{name} 的控件槽位变了 —— 老工作流会整体错位。\n"
            f"      现在：{got}\n      期望：{list(expect)}\n"
            "      新增参数请追加到末尾；只有 forceInput 的连线口才不占槽位。")
        # 顺带钉住这条：连线口绝不能被算成控件
        for bucket in ("required", "optional"):
            for pname, val in (cls.INPUT_TYPES().get(bucket) or {}).items():
                opt = val[1] if len(val) > 1 and isinstance(val[1], dict) else {}
                if opt.get("forceInput"):
                    assert pname not in got, f"{name}.{pname} 带 forceInput 却占了控件槽位"


def t_text_in():
    """外部文字接入：连线优先、空串回落、并且真的画到画面上。"""
    import torch
    import nodes as N

    # ---- 规则层：_resolve_text 的真值表 ----
    assert N._resolve_text("面板", "外部") == "外部"
    assert N._resolve_text("面板", "") == "面板"          # 上游传空串 = 没接
    assert N._resolve_text("面板", None) == "面板"
    assert N._resolve_text("面板", "   ") == "面板"        # 只有空白也算没接
    assert N._resolve_text("面板", 123) == "123"          # 非字符串也收
    assert N._resolve_text("", "外部") == "外部"
    assert N._resolve_text("面板", "") == "面板"
    assert N._text_source("外部") == "external"
    assert N._text_source("") == "panel"
    assert N._text_source(None) == "panel"

    # ---- 声明层：三个节点都要有，且必须是 forceInput（否则会占控件槽位） ----
    for cls in (N.VideoMarkOverlay, N.VideoMarkTitle, getattr(N, "VideoMarkVideo", None)):
        if cls is None:
            continue
        opt = (cls.INPUT_TYPES().get("optional") or {})
        assert "text_in" in opt, f"{cls.__name__} 没有 text_in 外接口"
        assert opt["text_in"][1].get("forceInput") is True, \
            f"{cls.__name__}.text_in 缺 forceInput —— 它会变成一个多出来的控件槽，把老工作流顶错位"

    # ---- 行为层：真调节点，画到画面上 ----
    node = N.VideoMarkOverlay()
    frames = np.stack([make_frame(W, H, i) for i in range(2)])
    t = torch.from_numpy(frames)

    def run(**kw):
        (out,) = node.apply(t, mode="corner", opacity=0.9, scale=20, **kw)
        return out

    panel = run(text="PANEL-TEXT")
    ext = run(text="PANEL-TEXT", text_in="EXTERNAL-TEXT")
    assert not torch.allclose(panel, ext), "接了外部文字，画面却没变 —— 外部输入没生效"
    # 断线 / 空串 → 与纯手填完全一致（这样才能说「不接线不影响老用法」）
    assert torch.allclose(run(text="PANEL-TEXT", text_in=""), panel), "空串没回落到手填文字"
    assert torch.allclose(run(text="PANEL-TEXT", text_in=None), panel)
    # 关掉文字开关时，外部输入也不该硬画上去
    off = run(text="PANEL-TEXT", text_in="EXTERNAL-TEXT", use_text=False)
    assert torch.allclose(off, run(text="PANEL-TEXT", use_text=False)), "关掉 use_text 后外部文字仍在画"


def t_style_switches():
    """样式预设 / 描边开关 / 投影开关 / 描边自身透明度。"""
    # 预设接管全部四项（开关 + 两个强度）
    assert R.resolve_style("soft", False, False) == (True, True, 0.55, 0.40)
    assert R.resolve_style("plain", True, True) == (False, False, 0.0, 0.0)
    assert R.resolve_style("outline", False, False) == (True, False, 1.0, 0.0)
    assert R.resolve_style("outline_shadow", False, False) == (True, True, 1.0, 0.6)
    # manual（以及任何未知值）听控件的，且大小写 / 空格不敏感
    assert R.resolve_style("manual", True, False, 0.7, 0.2) == (True, False, 0.7, 0.2)
    assert R.resolve_style(" MANUAL ", False, True, 0.25, 0.9) == (False, True, 0.25, 0.9)
    assert R.resolve_style("", True, True, 0.3, 0.35) == (True, True, 0.3, 0.35)

    # 关掉描边后，stroke_width 不该再影响渲染结果（尺寸必须完全一致）
    off12 = R.build_stamp(img_w=W, img_h=H, text="© kaero", scale_pct=20,
                          use_stroke=False, stroke_width=12, use_shadow=False)
    off0 = R.build_stamp(img_w=W, img_h=H, text="© kaero", scale_pct=20,
                         use_stroke=False, stroke_width=0, use_shadow=False)
    assert off12.shape == off0.shape, \
        f"关掉描边后 stroke_width 仍影响尺寸：{off12.shape} vs {off0.shape}"

    # 投影要向外扩出占位，否则贴角时影子会被 margin 切掉
    shadowed = R.build_stamp(img_w=W, img_h=H, text="© kaero", scale_pct=20, use_shadow=True,
                             shadow_blur=8, shadow_opacity=0.5,
                             shadow_offset_x=6, shadow_offset_y=6)
    assert shadowed.shape[0] > off0.shape[0] and shadowed.shape[1] > off0.shape[1], \
        f"投影没有扩出边距：{shadowed.shape} vs {off0.shape}"
    assert float(shadowed[..., 3].max()) <= 1.0

    # 投影关掉时必须和原来一模一样（不能被"顺手"加上）
    nope = R.build_stamp(img_w=W, img_h=H, text="© kaero", scale_pct=20, use_shadow=False,
                         shadow_blur=8, shadow_opacity=0.9)
    assert nope.shape == off0.shape, "use_shadow=False 时仍被加了投影"

    # 描边透明度：alpha 总量随透明度单调递增
    totals = []
    for so in (0.0, 0.35, 0.7, 1.0):
        t = R.render_text_rgba("© kaero", _FONT_PATH, 180, (255, 255, 255), 4, (0, 0, 0),
                               stroke_opacity=so)
        totals.append(float(t[..., 3].sum()))
    assert totals == sorted(totals) and totals[0] < totals[-1], f"描边透明度没生效：{totals}"
    # 0 应当只剩文字本体：比「完全不带描边的渲染」略小是正常的 ——
    # 描边宽度也算进「图章宽度 = 画面宽 X%」的预算里，字号会被等比缩小；
    # 但绝不能比它大（大了就说明描边还在）。
    only_text = R.render_text_rgba("© kaero", _FONT_PATH, 180, (255, 255, 255), 0, (0, 0, 0))
    ref = float(only_text[..., 3].sum())
    assert totals[0] < ref, f"stroke_opacity=0 时描边没有消失：{totals[0]} vs {ref}"
    assert totals[0] > ref * 0.7, f"stroke_opacity=0 时文字本体被一并抹掉了：{totals[0]} vs {ref}"
    print(f"         描边 alpha 总量梯度 {[round(v) for v in totals]}（纯文字 {round(ref)}）")


# =====================================================================
# 出样张
# =====================================================================

def make_samples():
    os.makedirs(OUT_DIR, exist_ok=True)
    frame = make_frame(W, H, 7)
    frame_dark = make_frame(W, H, 3, dark=True)
    logo = make_logo()

    # ---- 00 素材 ----
    save_png(make_logo(), "00_logo_sample.png")

    # ---- 01 四角（用节点默认样式 soft）----
    panels = []
    for p in R.POSITIONS:
        s = stamp_with_style("soft", img_w=W, img_h=H, text="© 2026 kaero\n禁止转载",
                             scale_pct=18, color=(255, 255, 255))
        out = R.apply_watermark(frame[None], s, mode="corner", position=p, margin=32, opacity=0.9)
        panels.append(col([label_bar(f"mode=corner   position={p}   margin=32   （soft 默认样式）", W),
                           out[0]]))
    save_png(col(panels), "01_corner.png")

    # ---- 02 居中低透明 ----
    panels = [label_bar("mode=center  opacity=0.20   （soft 默认样式）", W)]
    s = stamp_with_style("soft", img_w=W, img_h=H, text="© 2026 kaero", scale_pct=34,
                         color=(255, 255, 255))
    out = R.apply_watermark(frame[None], s, mode="center", margin=32, opacity=0.20)
    panels.append(out[0])
    save_png(col(panels), "02_center_lowopacity.png")

    # ---- 03 浮动轨迹（每格是同一段视频里不同帧）----
    for path, cycles in (("diagonal", 4), ("horizontal", 4), ("vertical", 4),
                         ("circle", 3), ("random", 6)):
        s = R.build_stamp(img_w=W, img_h=H, text="© 2026 kaero", scale_pct=16,
                          color=(255, 255, 255), angle=-12,
                          use_shadow=True, shadow_blur=8, shadow_opacity=0.5,
                          shadow_offset_x=4, shadow_offset_y=4)
        frames = np.stack([frame] * 6)
        out = R.apply_watermark(frames, s, mode="floating", float_path=path,
                                float_cycles=cycles, opacity=0.55, margin=32, seed=1)
        save_png(col([label_bar(f"mode=floating  float_path={path}  （同一段视频的 6 帧）", W)] + list(out)),
                 f"03_floating_{path}.png")

    # ---- 04 平铺（平铺用 plain：画面本来就被铺满，再加影子只会更脏）----
    panels = [label_bar("mode=tile  gap=70  angle=-25  opacity=0.18  （plain 样式）", W)]
    s = R.build_stamp(img_w=W, img_h=H, text="© 2026 kaero", scale_pct=14,
                      color=(255, 255, 255), angle=-25, use_shadow=False)
    out = R.apply_watermark(frame[None], s, mode="tile", tile_gap=70, opacity=0.18)
    panels.append(out[0])
    save_png(col(panels), "04_tile.png")

    # ---- 05 logo + 文字（深浅底各一份）----
    s = stamp_with_style("soft", img_w=W, img_h=H, text="王 者 出 品", use_logo=True,
                         logo_rgba=logo, scale_pct=16, layout="horizontal",
                         color=(255, 255, 255))
    a = R.apply_watermark(frame[None], s, mode="corner", position="bottom_right",
                          margin=32, opacity=0.9)[0]
    b = R.apply_watermark(frame_dark[None], s, mode="corner", position="bottom_right",
                          margin=32, opacity=0.9)[0]
    save_png(col([label_bar("mode=corner  横排 logo+文字  上：亮底  下：暗底", W), a, b]),
             "05_logo_combo.png")

    # ---- 06 片头片尾卡片 ----
    cards = [label_bar("mode=title  2 秒黑幕版权页  缓入缓出 8 帧", W)]
    cards.append(R.make_title_frames(img_w=W, img_h=H, count=1, text="© 2026 kaero\n版权所有 · 禁止转载",
                                     use_logo=True, logo_rgba=logo, layout="vertical",
                                     logo_scale_pct=14, text_scale_pct=22, fade_frames=0)[0])
    save_png(col(cards), "06_title_card.png")

    # ---- 07 完整时间轴 ----
    body = np.stack([make_frame(W, H, i) for i in range(20)])
    s = stamp_with_style("soft", img_w=W, img_h=H, text="© 2026 kaero", scale_pct=18,
                         color=(255, 255, 255))
    body = R.apply_watermark(body, s, mode="corner", position="bottom_right",
                             margin=32, opacity=0.9)
    head = R.make_title_frames(img_w=W, img_h=H, count=4, text="© 2026 kaero\n版权所有 · 禁止转载",
                               use_logo=True, logo_rgba=logo, layout="vertical",
                               logo_scale_pct=14, text_scale_pct=22, fade_frames=2)
    tail = R.make_title_frames(img_w=W, img_h=H, count=4, text="© 2026 kaero",
                               use_logo=True, logo_rgba=logo, layout="horizontal",
                               logo_scale_pct=8, text_scale_pct=14, fade_frames=2)
    seq = np.concatenate([head[1:2], head[3:4], body[0:1], body[10:11], tail[0:1], tail[3:4]], axis=0)
    save_png(col([label_bar("完整时间轴：片头卡片 → 正片（带角标）→ 片尾卡片", W)] + list(seq)),
             "07_timeline.png")

    # ---- 08 文字细节（放大看字形 / 描边 / 行距 / 多字体）----
    panels = []
    table = F.get_font_table()
    picked = [k for k in ("微软雅黑", "黑体", "宋体", "华文楷体", "Arial") if k in table]
    picked = (picked + list(table.keys()))[:4]
    for name in picked:
        fp, _i = F.resolve_font(name, "")
        s = R.build_stamp(img_w=W, img_h=H, text="© 2026 kaero\n禁 止 转 载", font_path=fp,
                          scale_pct=40, color=(255, 255, 255), stroke_width=4)
        out = R.apply_watermark(frame_dark[None], s, mode="center", margin=32, opacity=0.95)[0]
        panels.append(col([label_bar(f"字体：{name}   scale=40  stroke=4（放大看细节）", W), out]))
    save_png(col(panels), "08_text_detail.png")

    # ---- 09 样式对比：右下角局部放大，否则缩到一行里根本看不出描边和投影的差别 ----
    combos = [
        ("01 soft  描边+投影，都淡（默认）", (True, True, 0.55, 0.40)),
        ("02 plain 都不加（最轻）", (False, False, 0.0, 0.0)),
        ("03 outline 只留实心描边", (True, False, 1.0, 0.0)),
        ("04 outline_shadow 全拉满（最重）", (True, True, 1.0, 0.6)),
    ]
    CW, CH, ZOOM = 300, 150, 2.2
    for tag, dark, fname in (("亮底（浅色镜头）", False, "09_style_compare.png"),
                             ("暗底（夜景 / 黑幕）", True, "09b_style_compare_dark.png")):
        base = make_frame(W, H, 3, dark=dark)
        cells = []
        for label, (us, ush, so, sho) in combos:
            s = R.build_stamp(img_w=W, img_h=H, text="© 2026 kaero", scale_pct=18,
                              color=(255, 255, 255),
                              use_stroke=us, stroke_width=3, stroke_opacity=so,
                              use_shadow=ush, shadow_color=(0, 0, 0), shadow_opacity=sho,
                              shadow_offset_x=5, shadow_offset_y=5, shadow_blur=8)
            o = R.apply_watermark(base[None], s, mode="corner", position="bottom_right",
                                  margin=32, opacity=0.9)[0]
            cells.append(col([label_bar(label, int(CW * ZOOM), 28),
                              crop_zoom(o, W - CW, H - CH, CW, CH, ZOOM)]))
        save_png(col([label_bar(f"样式对比 · {tag} · 右下角局部放大 {ZOOM}×", W)] + [row(cells, 6)]),
                 fname)

    # ---- 10 描边自身透明度梯度（觉得描边太重时先调这个，比直接关掉更保留可读性）----
    for tag, dark, fname in (("亮底", False, "10_stroke_opacity.png"),
                             ("暗底", True, "10b_stroke_opacity_dark.png")):
        base = make_frame(W, H, 3, dark=dark)
        cells = []
        for so in (0.0, 0.3, 0.6, 1.0):
            s = R.build_stamp(img_w=W, img_h=H, text="© 2026 kaero", scale_pct=18,
                              color=(255, 255, 255),
                              use_stroke=True, stroke_width=3, stroke_opacity=so,
                              use_shadow=False)
            o = R.apply_watermark(base[None], s, mode="corner", position="bottom_right",
                                  margin=32, opacity=0.9)[0]
            cells.append(col([label_bar(f"stroke_opacity={so}", int(CW * ZOOM), 28),
                              crop_zoom(o, W - CW, H - CH, CW, CH, ZOOM)]))
        save_png(col([label_bar(f"描边粗细固定 3px · {tag} · 局部放大 {ZOOM}×（其余参数完全一致）", W)]
                     + [row(cells, 6)]), fname)

    return sorted(os.listdir(OUT_DIR))


# =====================================================================
# 入口
# =====================================================================

def main():
    global _FONT_PATH
    print("=" * 66)
    print("comfyui-videomark 离线自测")
    print("=" * 66)
    _FONT_PATH, _ = F.resolve_font(F.default_font_label(), "")

    print("\n[1] 字体")
    check("字体发现与解析", t_fonts)

    print("\n[2] 渲染核心")
    check("文字图章（宽度自动适配）", t_stamp_text)
    check("多行文字", t_stamp_multiline)
    check("logo 图章", t_stamp_logo)
    check("logo + 文字 组合排布", t_stamp_logo_and_text)
    check("旋转", t_rotate)
    check("样式开关（预设/描边/投影/透明度）", t_style_switches)
    check("位置计算（含边界约束）", t_positions)
    check("水印合成", t_watermark_shapes)
    check("空内容原样透传", t_watermark_passthrough)
    check("显示区间 + 淡入淡出", t_range_and_fade)
    check("平铺覆盖四个象限", t_tile_covers)
    check("片头片尾卡片", t_title)
    check("静音生成", t_silence)

    print("\n[3] 节点（用假张量直接调）")
    check("Overlay 节点", t_node_overlay)
    check("Overlay 节点 + logo/mask", t_node_overlay_logo)
    check("单张照片（真文件 → Overlay → 存盘）", t_node_overlay_still)
    check("Title 节点（含音频补静音）", t_node_title)
    check("Video 节点（VIDEO → VIDEO）", t_node_video)
    check("外部文字接入（连线优先 / 空串回落）", t_text_in)
    check("INPUT_TYPES 合法性", t_input_types)
    check("控件槽位冻结表（老工作流兼容契约）", t_widget_slots_frozen)

    print("\n[4] 出样张")
    try:
        files = make_samples()
        print(f"       已写入 {OUT_DIR}")
        for f in files:
            print(f"         - {f}")
    except Exception as e:                                            # noqa: BLE001
        FAIL.append(("样张生成", traceback.format_exc()))
        print(f"  [FAIL] 样张生成: {type(e).__name__}: {e}")

    print("\n" + "=" * 66)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    for name, tb in FAIL:
        print(f"\n--- {name} ---\n{tb}")
    print("=" * 66)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
