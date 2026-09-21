# -*- coding: utf-8 -*-
"""
生成 locales/<lang>/nodeDefs.json
=================================
ComfyUI 的节点界面文案（显示名 / 参数名 / 提示）是靠 `locales/<locale>/nodeDefs.json`
覆盖的，`INPUT_TYPES` 里的键名本身没法做多语言。

既然中文 tooltip 已经写在 nodes.py 里了，就别再手抄一份到 JSON ——
那个抄本迟早会和代码跑偏。这里直接从 `INPUT_TYPES()` 抽结构：

    中文：节点名 / 参数名 从下面的表取，tooltip 直接复用 nodes.py 里的现成中文
    英文：节点名 / 参数名 / tooltip 都从下面的表取

跑法（在包目录下）：

    python tools/gen_locales.py

它会打印「哪些参数没有英文 tooltip」，方便补齐。缺参数名时按参数名原样输出并报警。
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from typing import Any, Dict, List

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(PKG, "locales")

LANGS = ["zh", "en"]

# ---------------------------------------------------------------------
# 节点级文案
# ---------------------------------------------------------------------

NODE_LABELS: Dict[str, Dict[str, Dict[str, str]]] = {
    "zh": {
        "VideoMarkOverlay": {
            "display_name": "视频水印 · 画面（VideoMark Overlay）",
            "description": "给逐帧图像打水印：四角固定 / 居中低透明 / 浮动 / 平铺。"
                           "视频流程：不绑定任何视频模型，H3、Wan、LTX、VHS 等 IMAGE 批次都能挂。"
                           "单张照片也直接用它 —— 一张图就是长度为 1 的批次，"
                           "按这张图的宽高实时排版，不用另开节点。"
                           "输出是新张量，不会改写上游数据。",
        },
        "VideoMarkTitle": {
            "display_name": "视频水印 · 片头片尾版权页（VideoMark Title）",
            "description": "在片段头尾插入黑幕版权卡片（文字 + logo），"
                           "可选补齐等长静音以保证音画同步。没接音频时音频输出为空。",
        },
        "VideoMarkVideo": {
            "display_name": "视频水印 · 一站式（VideoMark Video）",
            "description": "一步到位：对 VIDEO 做画面水印 + 片头片尾卡片，音频自动同步。"
                           "需要精细控制时，改用 Overlay + Title 两个节点串起来。",
        },
    },
    "en": {
        "VideoMarkOverlay": {
            "display_name": "VideoMark Overlay",
            "description": "Burn a watermark into every frame — or into a single still photo: "
                           "fixed corner / low-opacity centre / floating / tiled. Not tied to any "
                           "video model; works with any IMAGE batch (MiniMax H3, Wan, LTX, VHS, "
                           "AnimateDiff...). A single image is just a batch of length 1 and gets "
                           "laid out from its own width and height. "
                           "Returns a new tensor; upstream data is never modified.",
        },
        "VideoMarkTitle": {
            "display_name": "VideoMark Title",
            "description": "Insert black copyright cards (text + logo) at the head and/or tail, "
                           "optionally padding the audio with matching silence so A/V stays in sync. "
                           "Audio output is empty when nothing is connected.",
        },
        "VideoMarkVideo": {
            "display_name": "VideoMark Video",
            "description": "All-in-one: watermark + head/tail cards on a VIDEO, audio handled for you. "
                           "Use Overlay + Title when you want finer control.",
        },
    },
}

# ---------------------------------------------------------------------
# 参数显示名
# ---------------------------------------------------------------------

LABELS: Dict[str, Dict[str, str]] = {
    "zh": {
        "images": "图像",
        "video": "视频",
        "audio": "音频",
        "logo": "Logo 图（连线）",
        "logo_mask": "Logo 遮罩",
        "logo_file": "Logo 文件",
        "mode": "水印方式",
        "position": "贴哪个角",
        "text": "水印文字",
        "text_in": "外部文字（连线）",
        "opacity": "不透明度",
        "scale": "宽度占比",
        "margin": "安全边距",
        "use_text": "显示文字",
        "use_logo": "显示 Logo",
        "layout": "图文排布",
        "color": "文字颜色",
        "style": "样式预设",
        "use_stroke": "描边开关",
        "stroke_width": "描边粗细",
        "stroke_color": "描边颜色",
        "stroke_opacity": "描边浓度",
        "use_shadow": "投影开关",
        "shadow_color": "投影颜色",
        "shadow_opacity": "投影浓度",
        "shadow_offset": "投影偏移",
        "shadow_blur": "投影模糊",
        "angle": "旋转角度",
        "font": "字体",
        "font_file": "字体文件",
        "float_path": "浮动轨迹",
        "float_cycles": "浮动圈数",
        "seed": "随机种子",
        "start_pct": "出现位置",
        "end_pct": "消失位置",
        "fade_frames": "淡入淡出帧数",
        "tile_gap": "平铺间距",
        "fps": "帧率",
        "where": "加在哪",
        "seconds": "卡片时长(秒)",
        "bg_color": "卡片底色",
        "logo_scale": "Logo 宽度占比",
        "text_scale": "文字宽度占比",
        "text_color": "卡片文字颜色",
        "text_stroke_width": "卡片文字描边",
        "text_stroke_color": "卡片描边颜色",
        "pad_audio": "补齐静音",
        "title_mode": "片头片尾卡片",
        "title_seconds": "卡片时长(秒)",
        "title_text": "卡片文字",
        "title_bg_color": "卡片底色",
    },
    "en": {
        "images": "Images",
        "video": "Video",
        "audio": "Audio",
        "logo": "Logo (link)",
        "logo_mask": "Logo mask",
        "logo_file": "Logo file",
        "mode": "Mode",
        "position": "Corner",
        "text": "Text",
        "text_in": "External text (link)",
        "opacity": "Opacity",
        "scale": "Width %",
        "margin": "Margin",
        "use_text": "Show text",
        "use_logo": "Show logo",
        "layout": "Layout",
        "color": "Text colour",
        "style": "Style preset",
        "use_stroke": "Stroke",
        "stroke_width": "Stroke width",
        "stroke_color": "Stroke colour",
        "stroke_opacity": "Stroke strength",
        "use_shadow": "Shadow",
        "shadow_color": "Shadow colour",
        "shadow_opacity": "Shadow strength",
        "shadow_offset": "Shadow offset",
        "shadow_blur": "Shadow blur",
        "angle": "Rotate",
        "font": "Font",
        "font_file": "Font file",
        "float_path": "Float path",
        "float_cycles": "Float cycles",
        "seed": "Seed",
        "start_pct": "Appear at",
        "end_pct": "Disappear at",
        "fade_frames": "Fade frames",
        "tile_gap": "Tile gap",
        "fps": "FPS",
        "where": "Placement",
        "seconds": "Seconds",
        "bg_color": "Card colour",
        "logo_scale": "Logo width %",
        "text_scale": "Text width %",
        "text_color": "Card text colour",
        "text_stroke_width": "Card text stroke",
        "text_stroke_color": "Card stroke colour",
        "pad_audio": "Pad silence",
        "title_mode": "Title card",
        "title_seconds": "Card seconds",
        "title_text": "Card text",
        "title_bg_color": "Card colour",
    },
}

# ---------------------------------------------------------------------
# 英文 tooltip（中文 tooltip 直接取 nodes.py 里的，不重复维护）
# ---------------------------------------------------------------------

TIPS_EN: Dict[str, str] = {
    "images": "Frame batch to watermark. Any IMAGE output works; the node never modifies it in place.",
    "video": "VIDEO to process. Frame rate is read from the video itself.",
    "audio": "Optional. Only needed so the node can pad matching silence and pass the track through "
             "when a head/tail card is added.",
    "logo": "Optional. A PNG logo with an alpha channel. Takes priority over the uploaded logo file.",
    "logo_mask": "Optional. Transparency mask for the logo; falls back to the PNG's own alpha.",
    "logo_file": "Logo file name relative to ComfyUI's input folder. The visual panel fills this in "
                 "automatically when you click 'Upload logo'. A linked logo input always wins over this.",
    "mode": "corner   fixed in one corner (least intrusive, best default)\n"
            "center   dead centre — keep opacity around 0.15~0.25\n"
            "floating wanders inside the safe area (hardest to crop out, worst to watch)\n"
            "tile     repeated across the whole frame — hardest to remove in post",
    "position": "Which corner to use in corner mode. Bottom-right blocks the least; switch to top-left "
                "if the platform overlays its own UI (like/share buttons) there.",
    "text": "Watermark text. Supports multiple lines — just press Enter.",
    "text_in": "Optional. Feed the text in from another node (any node that builds a string).\n"
               "When connected and non-empty the wired text wins — whatever you typed in the panel "
               "is ignored. Disconnected, or an empty string upstream, falls back to the panel text.\n"
               "Typical use: while comparing parameter variants (side view / resolutions / LoRA "
               "strengths / seeds), splice this run's parameters into the frame so you can tell at a "
               "glance which settings produced which result.\n"
               "Note: it takes one plain string — nothing is filled in for you, so build exactly the "
               "text you want upstream.",
    "opacity": "Overall opacity. Reference values:\n"
               "corner 0.75~1.0 / centre 0.12~0.22 / floating 0.25~0.45 / tile 0.10~0.20",
    "scale": "Watermark width as a percentage of the frame width. Resolution independent — "
             "you never have to retune it. 15~25 for text, 8~18 for a logo.",
    "margin": "Safe margin from the frame edge, in pixels. Floating and tiled stamps respect it too, "
              "so nothing ever gets clipped. 24~40 for 736x992; 36~64 for 1080p.",
    "use_text": "Turn off to show the logo only without deleting the text.",
    "use_logo": "Master switch for drawing the logo. Source is either the panel upload (logo_file) "
                "or a linked IMAGE on the logo input — the link wins.",
    "layout": "How logo and text stack when both are present: vertical (logo on top) or "
              "horizontal (logo on the left).",
    "color": "Text colour. Accepts #RRGGBB / #RGB / r,g,b / a colour name.",
    "style": "One-click preset for stroke + shadow:\n"
             "soft            both on but subtle (default) — readable on light and dark footage\n"
             "plain           both off — cleanest, but may vanish on bright backgrounds\n"
             "outline         solid stroke only — for footage with extreme contrast swings\n"
             "outline_shadow  both maxed — most legible, also most noticeable\n"
             "manual          ignore presets and use the four controls below",
    "use_stroke": "Stroke switch. Only read when style=manual; presets override it.\n"
                  "A stroke is the single biggest reason a watermark feels 'too heavy' — "
                  "lower stroke_opacity before turning it off.",
    "stroke_width": "Stroke thickness in pixels. Only applies when the stroke is on. 2~4 is plenty.",
    "stroke_color": "Stroke colour.",
    "stroke_opacity": "Opacity of the stroke itself. Lower this first when the watermark feels heavy — "
                      "it keeps the legibility while losing the hard black outline. 0 = no stroke.",
    "use_shadow": "Shadow switch. Only read when style=manual.\n"
                  "A shadow thickens the silhouette without the hard edge a stroke leaves — "
                  "but a dark shadow is invisible on night footage.",
    "shadow_color": "Shadow colour. Dark shadows disappear on dark footage; use a light colour there.",
    "shadow_opacity": "Opacity of the shadow. 0.3~0.5 reads as 'visible outline, not in the way'. "
                      "0 = no shadow.",
    "shadow_offset": "Shadow offset in pixels (positive = down-right). 4~8 looks natural; "
                     "0 turns it into a symmetrical soft glow, which is lighter and costs no margin.",
    "shadow_blur": "Shadow blur radius in pixels. Bigger is softer. 6~14 is natural; 0 = a hard duplicate.",
    "angle": "Rotate the whole watermark. For tiled marks, -20~-30 is much harder to align and erase.",
    "font": "Font. The list is sorted Chinese-first on Windows. To use a font outside the list, "
            "put its absolute path in font_file below — that overrides this.",
    "font_file": "Absolute path to a font file, e.g. D:/Fonts/Inter.otf. Overrides the font list above.",
    "float_path": "Path followed while floating:\n"
                  "diagonal / horizontal / vertical  constant back-and-forth (triangle wave)\n"
                  "circle                            elliptical loop\n"
                  "random                            uniform random jumps — strongest anti-theft, "
                  "most jarring to watch",
    "float_cycles": "How many round trips across the whole clip. 1 = one very slow pass; "
                    "4~8 = clearly wandering but still readable. For the random path this means "
                    "'number of position changes' — try 2x the clip length in seconds. "
                    "A single still has nothing to travel across: the seed pins it to one spot.",
    "seed": "Used by the random float path only. Fix it to reproduce the same positions.",
    "start_pct": "Where the watermark starts appearing, as a fraction of total length. "
                 "0 = from frame one. Only meaningful for multi-frame sequences: a single still "
                 "counts as frame 0, so this never hides it.",
    "end_pct": "Where it stops, as a fraction of total length. 1 = stays to the end. "
               "0.6 → 1.0 shows it only in the last 40%. Only meaningful for multi-frame sequences: "
               "a single still counts as frame 0, so this never hides it.",
    "fade_frames": "Fade-in / fade-out length in frames. 0 = hard cut. A single still has nothing "
                   "to fade, so this does not affect it.",
    "tile_gap": "Spacing between tiled watermarks, in pixels.",
    "fps": "Frame rate, used to convert seconds into a frame count. Must match the final clip's "
           "frame rate or the card length will be off (MiniMax H3 usually outputs 24fps).",
    "where": "head = only at the start, tail = only at the end, both = both ends "
             "(each gets a full card of `seconds`).",
    "seconds": "Card duration in seconds. Around 2s works well for a copyright notice.",
    "bg_color": "Card background colour. Pure black by default.",
    "logo_scale": "Logo width as a percentage of the frame width.",
    "text_scale": "Text width as a percentage of the frame width. 20~30 reads well for a credit card.",
    "text_color": "Card text colour.",
    "text_stroke_width": "Text stroke thickness. Give it 2~4 when the background is not pure black.",
    "text_stroke_color": "Card text stroke colour.",
    "pad_audio": "Pad the audio with matching silence so adding a head card does not desync A/V. "
                 "Keep this on whenever music is connected.",
    "title_mode": "Head / tail black copyright card. off = do not add one.",
    "title_seconds": "Card duration in seconds. Frame rate comes from the input video.",
    "title_text": "Card text. Leave blank to reuse the watermark text above.",
    "title_bg_color": "Card background colour.",
}


# ---------------------------------------------------------------------
# 采集 INPUT_TYPES
# ---------------------------------------------------------------------

def load_nodes_module():
    """按 ComfyUI 的方式把包 import 进来（和 tools/loadcheck.py 同一套做法）。"""
    root = os.path.dirname(PKG)                       # .../custom_nodes
    comfy = os.path.dirname(root)                     # .../ComfyUI
    for p in (comfy, PKG):
        if p not in sys.path:
            sys.path.insert(0, p)
    init = os.path.join(PKG, "__init__.py")
    spec = importlib.util.spec_from_file_location("videomark_pkg", init,
                                                  submodule_search_locations=[PKG])
    mod = importlib.util.module_from_spec(spec)
    sys.modules["videomark_pkg"] = mod
    spec.loader.exec_module(mod)
    return mod


def collect(module) -> Dict[str, Any]:
    """{节点名: {inputs: {参数名: 中文tooltip}, outputs: [输出名...]}}"""
    out: Dict[str, Any] = {}
    for name, cls in module.NODE_CLASS_MAPPINGS.items():
        try:
            it = cls.INPUT_TYPES()
        except Exception as e:                              # noqa: BLE001
            print(f"  ! {name}: INPUT_TYPES() 失败：{e}")
            continue
        inputs: Dict[str, str] = {}
        for bucket in ("required", "optional"):
            for pname, pdef in (it.get(bucket) or {}).items():
                tip = ""
                if isinstance(pdef, (list, tuple)) and len(pdef) > 1 and isinstance(pdef[1], dict):
                    tip = str(pdef[1].get("tooltip") or "")
                inputs[pname] = tip
        outs: List[str] = []
        rn = getattr(cls, "RETURN_NAMES", None) or getattr(cls, "RETURN_TYPES", ())
        outs = [str(x) for x in rn]
        out[name] = {"inputs": inputs, "outputs": outs}
    return out


def build(lang: str, structure: Dict[str, Any]) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    missing_labels: List[str] = []
    missing_tips: List[str] = []

    for node_name, info in structure.items():
        label = NODE_LABELS.get(lang, {}).get(node_name, {})
        entry: Dict[str, Any] = {
            "display_name": label.get("display_name", node_name),
        }
        if label.get("description"):
            entry["description"] = label["description"]

        inputs: Dict[str, Any] = {}
        for pname, zh_tip in info["inputs"].items():
            nm = LABELS.get(lang, {}).get(pname)
            if not nm:
                missing_labels.append(f"{node_name}.{pname}")
                nm = pname
            item: Dict[str, Any] = {"name": nm}
            if lang == "zh":
                if zh_tip:
                    item["tooltip"] = zh_tip
            else:
                tip = TIPS_EN.get(pname)
                if tip:
                    item["tooltip"] = tip
                elif zh_tip:
                    missing_tips.append(f"{node_name}.{pname}")
                    item["tooltip"] = zh_tip          # 宁可显示中文，也别空着
            inputs[pname] = item
        entry["inputs"] = inputs

        outputs: Dict[str, Any] = {}
        for i, oname in enumerate(info["outputs"]):
            key = str(i)
            nm = LABELS.get(lang, {}).get(oname)
            if not nm:
                missing_labels.append(f"{node_name}.out:{oname}")
                nm = oname
            outputs[key] = {"name": nm}
        entry["outputs"] = outputs
        data[node_name] = entry

    # 输出后端没有、但表里写了的展示名（多半是笔误）
    used = {p for info in structure.values() for p in info["inputs"]}
    used |= {o for info in structure.values() for o in info["outputs"]}
    stray = sorted(set(LABELS.get(lang, {})) - used)

    return {"data": data, "missing_labels": sorted(set(missing_labels)),
            "missing_tips": sorted(set(missing_tips)), "stray": stray}


def main() -> int:
    print(f"包目录：{PKG}")
    module = load_nodes_module()
    structure = collect(module)
    print(f"采集到 {len(structure)} 个节点：" +
          ", ".join(f"{k}({len(v['inputs'])} 参数)" for k, v in structure.items()))

    failed = False
    for lang in LANGS:
        res = build(lang, structure)
        d = os.path.join(OUT, lang)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "nodeDefs.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(res["data"], f, ensure_ascii=False, indent=2)
            f.write("\n")
        size = os.path.getsize(path)
        print(f"\n[{lang}] 写入 {os.path.relpath(path, PKG)}（{size} 字节，"
              f"{len(res['data'])} 节点）")
        if res["missing_labels"]:
            failed = True
            print(f"  ! 缺显示名（已退回参数名）：{', '.join(res['missing_labels'])}")
        if res["missing_tips"]:
            print(f"  · 缺英文 tooltip（暂用中文顶替）：{', '.join(res['missing_tips'])}")
        if res["stray"]:
            print(f"  · 表里有多余条目（后端没有这些参数）：{', '.join(res['stray'])}")

    if failed:
        print("\n有参数缺显示名，请补 LABELS 后重跑。")
        return 1
    print("\n完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
