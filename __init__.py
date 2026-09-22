# -*- coding: utf-8 -*-
"""
comfyui-videomark
=================
视频水印自定义节点：四角固定 / 居中低透明 / 浮动 / 平铺 / 片头片尾版权页。

节点：
  VideoMark Overlay  画面水印（IMAGE 批次进出）
  VideoMark Title    片头片尾黑幕版权页（IMAGE + AUDIO）
  VideoMark Video    VIDEO → VIDEO 一站式

界面：
  - 节点内置可视化面板（web/videomark.js）——文字/logo 上传、图形化选水印样式、
    描边/阴影/透明度/字号的微调滑块、进阶参数折叠区；
  - 面板只是「皮肤」，所有值仍写回原生 widget，老工作流照常加载与提交；
  - 面板不内置预览（撤掉的理由写在 webapi.py 顶部），水印效果看出片即可。

文字来源（v1.4.0）
  - 面板手填（text / title_text）或从外部接进来（text_in，forceInput 的连线口）；
  - 连线且内容非空时**以连线为准**，规则与本包 logo 一致（连线 > logo_file）；
  - text_in 不带控件，所以加它对老工作流的 widgets_values 一位都不影响。
"""

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

__version__ = "1.4.1"

# ComfyUI 会自动把该目录下的 .js 当作前端扩展加载
WEB_DIRECTORY = "./web"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]


def _register_web_api() -> None:
    """
    挂面板接口（/videomark/meta）。

    失败不影响节点本身：面板的样式预设档会退化成「保持原值」，参数照常能填、
    工作流照常能跑。
    """
    try:
        from . import webapi
        if webapi.register_routes():
            print("[VideoMark] 面板接口已就绪：/videomark/meta")
    except Exception as e:                                  # noqa: BLE001
        print(f"[VideoMark] 面板接口注册失败（节点不受影响）：{type(e).__name__}: {e}")


_register_web_api()
