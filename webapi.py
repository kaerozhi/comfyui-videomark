# -*- coding: utf-8 -*-
"""
面板用的后端接口
================
只有一个 `/videomark/meta`：把样式预设表和各组枚举喂给前端面板。

**为什么要走接口、不让前端抄一份**：一个预设是「四个数值」的打包
（use_stroke / use_shadow / stroke_opacity / shadow_opacity）。前端要是揣着
一份老副本，后端调了预设之后，滑块就会摆在和出片效果不一致的位置上 ——
上一轮已经吃过一次「样张与默认值脱节」的亏。

**这里曾经还有一个 `/videomark/preview`**（面板里的实时预览），已随预览区一起撤掉。
理由：水印是放上去就长期不变的东西，看一次出片就知道效果，不值得为它维护一条
「拖滑块 → 130ms 防抖 → 后端渲染 PNG → 回传」的链路；那条链路还额外带来了一次
缓存被原地改写的 bug。
"""

from __future__ import annotations

from typing import Any, Dict

from . import render as R


def build_meta() -> Dict[str, Any]:
    """面板需要的元数据。全部取自后端，前端不抄。"""
    return {
        "modes": list(R.MODES),
        "positions": list(R.POSITIONS),
        "float_paths": list(R.FLOAT_PATHS),
        "layouts": list(R.LAYOUTS),
        "styles": R.style_presets(),
    }


def register_routes() -> bool:
    """
    把接口挂到 ComfyUI 的 aiohttp 上，返回是否挂上。

    必须在 `PromptServer.instance` 已经存在时调用 —— ComfyUI 是先建好 PromptServer
    再加载 custom_nodes 的，所以在 `__init__.py` 里调最合适。拿不到 server 就跳过：
    面板的预设档会退化成「保持原值」，节点本身照常工作。
    """
    try:
        from aiohttp import web
        from server import PromptServer
    except Exception as e:                                  # noqa: BLE001
        print(f"[VideoMark] 未注册面板接口（{type(e).__name__}: {e}）；节点功能不受影响")
        return False

    server = getattr(PromptServer, "instance", None)
    routes = getattr(server, "routes", None)
    if routes is None:
        print("[VideoMark] 未注册面板接口（PromptServer 尚未就绪）；节点功能不受影响")
        return False

    @routes.get("/videomark/meta")
    async def videomark_meta(request):                      # noqa: ANN001
        return web.json_response(build_meta(),
                                 headers={"Cache-Control": "no-store"})

    return True
