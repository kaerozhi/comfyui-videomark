# -*- coding: utf-8 -*-
"""
可视化面板一致性检查（静态，不需要开 ComfyUI）
==============================================
面板最容易出的两类错，都很难靠肉眼发现：

  1. 后端加了个参数，忘了在面板上给它位置 —— 用户在那个节点上就永远改不到它，
     而且节点上原生 widget 已经被隐藏了，等于这个参数直接消失；
  2. 面板写了个后端不存在的参数名（改名、拼错）—— 静默失败，
     拖滑块看起来有反应，实际什么都没写进去；
  3. 面板分组（data-g）与取值表（GROUP_VALUE）对不上 —— 会直接抛 TypeError，
     而且异常抛在别处（上传 logo、切样式）时会被误报成那个操作失败；
  4. 控件顺序被动过（新参数插在中间）—— 老工作流按位置取值会整体错位，
     报出来的错跟真正的原因长得完全不像；
  5. 滑块没走 sl() 生成 —— 会同时丢掉「配数字框」和「边界取自后端声明」两件事，
     而两件事丢了都不报错，只是面板悄悄砍掉合法值 / 放进非法值。

这个脚本把 web/videomark.js 里的 SPECS 与 nodes.py 的 INPUT_TYPES 对一遍，
顺带检查 i18n 字典的中英文键是否对称、t() 用到的键是否都有翻译。

跑法（在包目录下）：

    python tools/uicheck.py
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from typing import Any, Dict, List, Set

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_PATH = os.path.join(PKG, "web", "videomark.js")

# 这些类型要走连线，面板不接管
LINK_TYPES = {"IMAGE", "MASK", "AUDIO", "VIDEO", "LATENT"}


def load_nodes_module():
    root = os.path.dirname(PKG)
    comfy = os.path.dirname(root)
    for p in (comfy, PKG):
        if p not in sys.path:
            sys.path.insert(0, p)
    init = os.path.join(PKG, "__init__.py")
    spec = importlib.util.spec_from_file_location("videomark_pkg_check", init,
                                                  submodule_search_locations=[PKG])
    mod = importlib.util.module_from_spec(spec)
    sys.modules["videomark_pkg_check"] = mod
    spec.loader.exec_module(mod)
    return mod


def is_widget_param(pdef: Any) -> bool:
    """True = 面板应该给它一个控件；False = 连线型，不用管。

    forceInput / socketless / hidden 的输入**不是 widget**：前端 settingStore 里
    那段判断是 `let o = n.widgets.get(i.type); if (!o || t.forceInput) return;`
    —— 命中就直接返回，不建控件。既然不建控件，它就不占 widgets_values 的槽位，
    面板当然也不用给位置。

    漏掉这条的后果（本文件真踩过）：给节点加一个「外部文字输入」口，
    检查立刻报「控件型参数面板没有接管：text_in」，看着像面板漏了一项，
    其实那个参数压根不该出现在面板上 —— 而照它去补，就会往 SPECS 里塞一个
    根本不存在的控件名，接着又触发「面板引用了后端不存在的参数」。
    """
    if not isinstance(pdef, (list, tuple)) or not pdef:
        return False
    opt = pdef[1] if len(pdef) > 1 and isinstance(pdef[1], dict) else {}
    if any(opt.get(k) for k in ("forceInput", "socketless", "hidden")):
        return False
    t = pdef[0]
    if isinstance(t, list):
        return True                                     # COMBO 下拉
    if isinstance(t, str):
        return t.upper() not in LINK_TYPES
    return False


def node_params(module) -> Dict[str, Dict[str, bool]]:
    """{节点名: {参数名: 是否需要面板控件}}"""
    out: Dict[str, Dict[str, bool]] = {}
    for name, cls in module.NODE_CLASS_MAPPINGS.items():
        try:
            it = cls.INPUT_TYPES()
        except Exception:                                  # noqa: BLE001
            continue
        params: Dict[str, bool] = {}
        for bucket in ("required", "optional"):
            for pname, pdef in (it.get(bucket) or {}).items():
                params[pname] = is_widget_param(pdef)
        out[name] = params
    return out


# ---------------------------------------------------------------------
# 解析 JS
# ---------------------------------------------------------------------

def loads_js_array(text: str) -> List[str]:
    """
    解析 JS 的字符串数组字面量。

    JS 允许尾逗号、JSON 不允许，所以先去掉 `,]` 再交给 json ——
    否则每加一行参数就会在这里炸一次，而且报错信息完全看不出是尾逗号的问题。
    """
    t = text.strip()
    if not t.startswith("["):
        return []
    t = re.sub(r",(\s*)\]", r"\1]", t)
    try:
        return json.loads(t)
    except json.JSONDecodeError as e:
        raise SystemExit(f"解析 JS 数组失败：{e}\n原文：{t[:200]}")


def _array_span(text: str, start: int) -> int:
    """
    从 text[start] == "[" 开始，返回与之配对的 "]" 的下标（找不到返回 -1）。

    为什么不用正则找数组结尾：早先写成 `\\[[\\s\\S]*?\\n\\]`（"以换行+右括号结尾"），
    结果只要有一个数组写成单行（`const X = ["a", "b"];`），
    引擎就会一路找到**下一个**数组的结尾去，把两个数组的内容串成一个。
    症状很隐蔽：解析出来数量不对，还以为是展开语法没支持。
    参数名的数组里不会有嵌套方括号、也不会有转义引号，所以数括号深度就够了。
    """
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                return i
    return -1


def resolve_array(expr: str, table: Dict[str, List[str]]) -> List[str]:
    """
    解析一个数组表达式：["a","b"] / NAME / [...NAME, ...OTHER, "x"] 都认。

    以前只支持 [...WM_WIDGETS, "x"] 这一种写法，靠字符串替换实现 ——
    于是面板的参数清单没办法拆成「通用 / 时间轴 / 节点独有」几组，
    一拆就解析不了，只能整份复制粘贴（而复制粘贴的名单迟早会漂）。
    现在按出现顺序逐个取「字符串字面量」或「展开项」，分组可以随便组合。

    这里刻意不处理转义引号：这些数组里放的是参数名，不会有这种内容，
    为它写一个正规的字符串扫描器只会让这里更容易出错。
    """
    expr = expr.strip()
    if not expr.startswith("["):
        return list(table.get(expr, []))
    body = expr[1:expr.rindex("]")]
    out: List[str] = []
    for m in re.finditer(r'"([^"]*)"|\'([^\']*)\'|\.\.\.\s*([A-Za-z_][A-Za-z0-9_]*)', body):
        if m.group(1) is not None:
            out.append(m.group(1))
        elif m.group(2) is not None:
            out.append(m.group(2))
        else:
            out.extend(table.get(m.group(3), []))
    return out


def js_arrays(js: str) -> Dict[str, List[str]]:
    """收集 `const NAME = [ ... ];` 形式的顶层数组常量，允许它们互相展开。"""
    raw: Dict[str, str] = {}
    for m in re.finditer(r"const\s+([A-Z][A-Z0-9_]*)\s*=\s*\[", js):
        open_i = m.end() - 1
        close_i = _array_span(js, open_i)
        if close_i > 0:
            raw[m.group(1)] = js[open_i:close_i + 1]

    table: Dict[str, List[str]] = {}
    for _ in range(3):                    # 迭代几轮即可解决「引用了后面才定义的数组」
        for name, expr in raw.items():
            table[name] = resolve_array(expr, table)
    return table


def parse_specs(js: str) -> Dict[str, List[str]]:
    js = strip_js_comments(js)
    table = js_arrays(js)

    m = re.search(r"const\s+SPECS\s*=\s*\{([\s\S]*?)\n\};", js)
    if not m:
        raise SystemExit("找不到 SPECS 定义，检查 web/videomark.js 的结构")
    block = m.group(1)

    specs: Dict[str, List[str]] = {}
    parts = re.split(r"\n  (VideoMark\w+):\s*\{", block)
    for i in range(1, len(parts), 2):
        node_name, body = parts[i], parts[i + 1]
        wm = re.search(r"widgets\s*:\s*(\[|[A-Za-z_][A-Za-z0-9_]*)", body)
        if not wm:
            continue
        if wm.group(1) == "[":
            open_i = wm.end() - 1
            close_i = _array_span(body, open_i)
            expr = body[open_i:close_i + 1] if close_i > 0 else ""
        else:
            expr = wm.group(1)
        specs[node_name] = resolve_array(expr, table)
    return specs

def js_string_literals(js: str) -> Set[str]:
    return set(re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"', js))


def check_i18n(js: str) -> List[str]:
    problems: List[str] = []
    langs = {}
    for lang in ("zh", "en"):
        m = re.search(rf"\n  {lang}:\s*\{{([\s\S]*?)\n  \}},", js)
        if not m:
            problems.append(f"找不到 i18n 的 {lang} 段")
            continue
        langs[lang] = set(re.findall(r"^\s{4}([A-Za-z0-9_]+):", m.group(1), re.M))
    if len(langs) == 2:
        only_zh = sorted(langs["zh"] - langs["en"])
        only_en = sorted(langs["en"] - langs["zh"])
        if only_zh:
            problems.append(f"i18n：{langs['zh'] and 'zh'} 有、en 缺的键：{', '.join(only_zh)}")
        if only_en:
            problems.append(f"i18n：en 有、zh 缺的键：{', '.join(only_en)}")

    used = set(re.findall(r"(?<![A-Za-z0-9_.])t\(\s*[\"']([A-Za-z0-9_]+)[\"']\s*\)", js))
    # 用模板拼出来的键（t("m_" + m)、t("fp_" + fp)）正则抓不到，单独展开。
    # ⚠ 展开必须挂在 if 里面：早先这里漏了 if（还多写了一句无意义的 values.extend(values)），
    #   导致不管 JS 里有没有拼接都无条件把表里所有键塞进 used —— 于是「删掉某组字典项」
    #   会立刻假报警。表里也只该留真正在用拼接的前缀，其余（pos_/l_/s_/c_）都是字面量。
    for prefix, values in (
        ("m_", ["corner", "center", "floating", "tile"]),
        ("fp_", ["diagonal", "horizontal", "vertical", "circle", "random"]),
        ("pos_", ["top_left", "top_right", "bottom_left", "bottom_right"]),
        ("l_", ["vertical", "horizontal"]),
        ("s_", ["size", "opacity", "stroke", "shadow", "margin", "gap", "angle"]),
        ("c_", ["text", "both", "logo"]),
    ):
        if f'"{prefix}" +' in js or f"'{prefix}' +" in js:
            used |= {prefix + v for v in values}
    all_keys = set()
    for s in langs.values():
        all_keys |= s
    missing = sorted(k for k in used if k not in all_keys)
    if missing:
        problems.append(f"i18n：代码里用到但字典里没有的键：{', '.join(missing)}")
    return problems


def strip_js_comments(js: str) -> str:
    """
    去掉注释再分析。

    注释里很自然会出现被检查的字样（本文件刚吃过两次亏）：
    `$('[data-g="x"]')` 这种举例会被当成真的分组 x，
    `paintSeg` 的注释里写了一句「不能直接 querySelectorAll」又把 null 保护的判定带偏。
    这个 JS 里没有字符串形式的 `//`（已确认），逐行截断是安全的。
    """
    js = re.sub(r"/\*[\s\S]*?\*/", "", js)
    return "\n".join(line.split("//")[0] for line in js.splitlines())


def check_groups(js: str) -> List[str]:
    """
    面板分组（data-g）↔ 取值表（GROUP_VALUE）必须一一对应。

    早先 paintAll() 是「逐个 $('[data-g="x"]') 再交给 paintSeg」，可面板是按节点
    类型拼出来的：正片节点没有「片头」分组、片头节点没有样式卡片，取不到就是 null，
    paintSeg 里一句 null.querySelectorAll 直接抛 TypeError。更坑的是上传 logo 时
    这个异常被上传的 try 捞走，界面报「上传失败」，其实文件早就传上去了。

    现在 paintAll 改成扫面板上真实存在的分组再取值，缺失在结构上不可能再出事；
    这个检查守着剩下的一半：模板加了新分组、却忘了在 GROUP_VALUE 里配取值函数
    （症状是那个控件永远不高亮，肉眼很难发现）。
    """
    problems: List[str] = []
    js = strip_js_comments(js)

    tpl = set(re.findall(r'data-g="([a-z_]+)"', js))

    m = re.search(r"const\s+GROUP_VALUE\s*=\s*\{([\s\S]*?)\n  \};", js)
    if not m:
        problems.append("找不到 GROUP_VALUE：paintAll 是不是又改回逐个取分组的老写法了？")
        return problems
    table = set(re.findall(r"^\s{4}([a-z_]+)\s*:\s*\(\)", m.group(1), re.M))

    no_getter = sorted(tpl - table - {"mode"})     # mode 是样式卡片，单独高亮
    if no_getter:
        problems.append(f"面板里有分组没配取值函数，这些控件不会高亮：{', '.join(no_getter)}")
    unused = sorted(table - tpl)
    if unused:
        problems.append(f"取值函数里的分组在模板里不存在（名字写错？）：{', '.join(unused)}")

    if not re.search(r"for\s*\(const\s+\w+\s+of\s+\$\$\('\[data-g\]'\)\)", js) \
            and not re.search(r'for\s*\(const\s+\w+\s+of\s+\$\$\("\[data-g\]"\)\)', js):
        problems.append('paintAll 没有用 $$("[data-g]") 扫分组，可能又退回到逐个取 null 的写法')

    if re.search(r"""paintSeg\(\s*\$\('\[data-g""", js):
        problems.append("仍有 paintSeg($('[data-g=...]')) 裸调用：分组不存在时会抛 TypeError")

    i = js.find("function paintSeg(")
    if i < 0:
        problems.append("找不到 paintSeg 定义")
    elif "if (!container) return" not in js[i:i + 500].split("querySelectorAll")[0]:
        problems.append("paintSeg 缺 null 保护（分组不是每种节点都有，null 是常态）")

    return problems


def check_widget_order(params: Dict[str, Dict[str, bool]]) -> List[str]:
    """
    logo_file 必须在每个节点控件表的**最后一位**。

    这条规矩不是洁癖：ComfyUI 的工作流把控件值按「位置」存成数组
    （widgets_values），往中间插一个新参数 = 老工作流在该位置之后的控件
    值全部右移一位，加载时报一串看起来毫不相干的错。真事：

        float_path   输入值 1 不可用
        float_cycles 输入值 2261135997 高于最大值 200
        seed         输入值 randomize 无法转换为 INT

    三条错分别对应「老 float_cycles / 老 seed / 老 control_after_generate」，
    根因只是 logo_file 当初被插在了 font_file 与 float_path 之间。

    后端靠 _with_logo() 收尾来保证顺序，这个检查守着它不被后来者破坏
    （把 logo_file 写回 _watermark_widgets 里就属于破坏）。
    """
    problems: List[str] = []
    for node_name, pmap in params.items():
        widgets = [p for p in pmap if pmap[p]]          # dict 保序：required → optional
        if "logo_file" not in widgets:
            continue
        if widgets[-1] != "logo_file":
            tail = widgets[widgets.index("logo_file") + 1:]
            problems.append(
                f"{node_name}：logo_file 不在控件表末尾（后面还有 {', '.join(tail)}）——"
                f"老工作流会整体错位一位；请用 _with_logo() 收尾，别插在中间")
    return problems


def check_link_inputs(module) -> List[str]:
    """
    forceInput 的口必须是 optional。

    forceInput 是**连线口**：放 required 就变成「必填」—— 老工作流没接它，
    validate_prompt 直接报缺输入，等于把一个「想接才接」的功能变成升级即坏。
    这条很容易在复制粘贴加参数时写错（required 那段更好找），所以静态守着。
    """
    problems: List[str] = []
    for node_name, cls in module.NODE_CLASS_MAPPINGS.items():
        try:
            it = cls.INPUT_TYPES()
        except Exception:                               # noqa: BLE001
            continue
        for bucket in ("required", "optional"):
            for pname, pdef in (it.get(bucket) or {}).items():
                opt = pdef[1] if (isinstance(pdef, (list, tuple)) and len(pdef) > 1
                                  and isinstance(pdef[1], dict)) else {}
                if opt.get("forceInput") and bucket != "optional":
                    problems.append(
                        f"{node_name}.{pname} 带 forceInput 却写在 required 里："
                        f"它会变成必填连线口，没接线的工作流直接报「缺输入」")
    return problems


def check_slider_panel(js: str) -> List[str]:
    """
    面板上的滑块必须**全部**由 `sl()` 生成，且 `sl()` 里不写边界。

    这条不是洁癖，是一根滑块上挂着三件必须同时成立的事：

      1. 配一个可直接输入数字的框 —— 光靠滑块拖不出 0.85 这种值；
      2. min/max/step 由 `applyBounds()` 从后端 widget.options 灌进来
         （真事：模板里 margin 写过 0~200，后端其实允许 600，面板悄悄替用户
         砍掉了合法值；opacity 又写过 0~1，后端是 0.02~1，面板放进来的那段
         后端会直接拒）；
      3. 顺序无关的细节 —— 数字框 width 写死，跟着值的位数变宽变窄会很难看。

    手写一个 `<input type="range">` 就会把 1、2 两条一起绕过去，而且绕过之后
    没有任何报错，只有用户偶尔觉得「这参数怎么拖不到那么高」。
    所以这里守的结构不变量是：**全文件只允许 sl() 模板里出现一个 range**。
    """
    problems: List[str] = []
    code = strip_js_comments(js)

    n_range = code.count('<input type="range"')
    if n_range != 1:
        problems.append(
            f"面板里有 {n_range} 处 <input type=\"range\">（应只有 sl() 模板里那一个）："
            "手写滑块会绕过「配数字框」和「边界取自后端」两件事，请改用 sl()")

    m = re.search(r"const sl = \(([^)]*)\) => `([\s\S]*?)`;", code)
    if not m:
        problems.append("找不到 sl() 模板：面板结构变了？")
    else:
        args, tpl = m.group(1), m.group(2)
        if "vmk-num" not in tpl:
            problems.append("sl() 模板里没有 .vmk-num：每根滑块都要配一个可直接输入数字的框")
        if "data-sl=\"${key}\"" not in tpl:
            problems.append("sl() 模板里的 data-sl 不对（应当是 data-sl=\"${key}\"）")
        # 两种写法都要拦：写死数字（min="0"）和写成插值（min="${min}"）
        if re.search(r'(?:^|\s)(min|max|step)\s*=\s*["\'{]', tpl):
            problems.append("sl() 模板里又出现 min/max/step 属性了："
                            "边界只能从后端声明取（applyBounds），别在前端另抄一份")
        if not re.search(r"class=\"vmk-num\"", tpl):
            problems.append('数字框的 class 不是 "vmk-num"：CSS 与 bindSlider 都按这个名字找')

    # applyBounds 得存在、且真被调用（定义 1 次 + 调用 1 次）
    if code.count("applyBounds") < 2:
        problems.append("applyBounds() 没定义或没被调用：滑块的 min/max/step 就不会同步后端声明了")

    # 面板里出现过的滑块名，后端必须声明了 min/max/step（applyBounds 才灌得进去）
    return problems


# ---------------------------------------------------------------------

def check_version_consistency() -> List[str]:
    """包内各处版本号必须一致。

    pyproject 与 __init__ 曾经各自走一路（pyproject 1.3.2 / __init__ 1.2.0），
    于是「面板/管理器/启动日志」报出的版本各不相同，排查时很容易被带偏 ——
    尤其是"到底哪个包在生效"这类判断。版本号是给人看的，只允许有一个。
    """
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    seen: Dict[str, str] = {}

    init_py = os.path.join(root, "__init__.py")
    if os.path.isfile(init_py):
        m = re.search(r'^__version__\s*=\s*"([^"]+)"', open(init_py, encoding="utf-8").read(), re.M)
        if m:
            seen["__init__.py"] = m.group(1)
        else:
            seen["__init__.py"] = "<缺失>"

    pyproject = os.path.join(root, "pyproject.toml")
    if os.path.isfile(pyproject):
        m = re.search(r'^version\s*=\s*"([^"]+)"', open(pyproject, encoding="utf-8").read(), re.M)
        if m:
            seen["pyproject.toml"] = m.group(1)
        else:
            seen["pyproject.toml"] = "<缺失>"

    if len(set(seen.values())) > 1:
        return ["版本号不一致：" + "、".join(f"{k}={v}" for k, v in seen.items())]
    return []


def main() -> int:
    if not os.path.isfile(JS_PATH):
        print(f"找不到 {JS_PATH}")
        return 1
    js = open(JS_PATH, encoding="utf-8").read()

    module = load_nodes_module()
    params = node_params(module)
    specs = parse_specs(js)

    print(f"后端节点：{', '.join(params)}")
    print(f"面板覆盖：{', '.join(f'{k}({len(v)})' for k, v in specs.items())}")

    problems: List[str] = []

    for node_name, covered in specs.items():
        if node_name not in params:
            problems.append(f"{node_name}：面板里有这个节点，但后端 NODE_CLASS_MAPPINGS 没有")
            continue
        backend = params[node_name]
        cset = set(covered)

        unknown = sorted(cset - set(backend))
        if unknown:
            problems.append(f"{node_name}：面板引用了后端不存在的参数（改名/拼错？）："
                            f"{', '.join(unknown)}")

        needs = {p for p, is_w in backend.items() if is_w}
        missed = sorted(needs - cset)
        if missed:
            problems.append(f"{node_name}：以下控件型参数面板没有接管，用户将无法修改："
                            f"{', '.join(missed)}")

        extra_link = sorted(p for p in (cset & set(backend)) if not backend[p])
        if extra_link:
            print(f"  · {node_name}：面板列了连线型参数（无害，只是多余）：{', '.join(extra_link)}")

    # wset / wget / bindSlider / data-sl 用到的名字必须被面板覆盖
    used = set(re.findall(r"w(?:set|get)\(node,\s*\"([^\"]+)\"", js))
    used |= set(re.findall(r"bindSlider\(\s*\"([^\"]+)\"", js))
    used |= {v for v in re.findall(r'data-sl="([^"]+)"', js) if "$" not in v}
    used |= {v for v in re.findall(r'data-t="([^"]+)"', js) if "$" not in v}
    all_covered = {p for v in specs.values() for p in v}
    orphan = sorted(used - all_covered)
    if orphan:
        problems.append(f"面板代码写入了没被 SPECS 覆盖的参数：{', '.join(orphan)}")

    problems += check_i18n(js)
    problems += check_groups(js)
    problems += check_widget_order(params)
    problems += check_link_inputs(module)
    problems += check_slider_panel(js)
    problems += check_version_consistency()

    if problems:
        print("\n发现问题：")
        for p in problems:
            print(f"  ✗ {p}")
        return 1

    total = sum(len(v) for v in specs.values())
    print(f"\n✓ 面板与后端一致：{len(specs)} 个节点、{total} 个参数位，无缺项、无笔误。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
