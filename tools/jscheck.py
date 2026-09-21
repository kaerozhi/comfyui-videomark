# -*- coding: utf-8 -*-
"""
前端脚本检查（语法 + 老工作流坑位迁移的行为测试）
================================================

`uicheck.py` 只看参数名对不对，看不出 JS 本身能不能跑。而这个文件里有两类
错是**只在浏览器里才炸**的：

  1. 语法错（Python 里字符串隐式拼接写顺手了，到 JS 就是 SyntaxError）——
     整个面板直接不加载，节点上光秃秃一片，控制台里一条红字；
  2. 迁移逻辑写歪（认错人 → 把正常参数改掉，或该迁的没迁）——
     比语法错更坏，因为它是静默的。

做法：把前端那两行 import 桩掉、导出要测的函数，在 node 里直接跑一遍。
找不到 node 就跳过（返回 0），不让没装 node 的机器卡在自检上。

跑法（在包目录下）：

    python tools/jscheck.py
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile

PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_PATH = os.path.join(PKG, "web", "videomark.js")

# node 可能的落点：环境变量 → PATH → 本机常见的几处
NODE_CANDIDATES = [
    os.environ.get("VIDEOMARK_NODE", ""),
    shutil.which("node") or "",
    r"C:\Program Files\nodejs\node.exe",
    os.path.expanduser(r"~\AppData\Roaming\npm\node.exe"),
    r"C:\nvm4w\nodejs\node.exe",
    "/usr/bin/node",
    "/usr/local/bin/node",
]

IMPORTS = """import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";"""

STUBS = """const app = { ui: { settings: { getSettingValue: () => "zh" } }, registerExtension: () => {} };
const api = { fetchApi: async () => ({ ok: false }) };"""

# 行为测试：把「值怎么铺到控件上」这件事按 ComfyUI 的做法（按位置）模拟一遍。
TEST_JS = r"""
import { migrateLegacyWidgets, valueFits, numText, parseNum, commitNum,
         stepOf, gridOf, inputLinked } from "./vmk_module.mjs";

const TYPES = {
  float_path: { type: "combo", options: { values: ["diagonal", "horizontal", "vertical", "circle", "random"] } },
  float_cycles: { type: "number", options: { min: 0.1, max: 200 } },
  seed: { type: "number", options: { min: 0, max: 4294967295 } },
  fade_frames: { type: "number", options: { min: 0, max: 240 } },
  pad_audio: { type: "toggle" },
};

function mkNode(names) {
  return {
    widgets: names.map((n) => {
      const t = TYPES[n] || {};
      return { name: n, type: t.type || "text", options: t.options || {} };
    }),
    widgets_values: [],
    setDirtyCanvas() {},
  };
}

const OVERLAY = ["mode", "font_file", "float_path", "float_cycles", "seed", "tile_gap", "logo_file"];
const CARD    = ["mode", "font_file", "fade_frames", "pad_audio", "logo_file"];

const CASES = [
  ["新排列：logo_file 本就在末尾，不许动",
   OVERLAY,
   ["corner", "", "diagonal", 1, 2261135997, 90, "logo/x.png"],
   false, null],

  ["更老的一版（压根没有 logo_file），不许动",
   OVERLAY,
   ["corner", "", "diagonal", 1, 2261135997, 90],
   false, null],

  ["错位档（logo_file 夹在 font_file 后面）要还原",
   OVERLAY,
   ["corner", "", "logo/x.png", "diagonal", 1, 2261135997, 90],
   true, ["corner", "", "diagonal", 1, 2261135997, 90, "logo/x.png"]],

  ["错位档但 logo 没上传（空串）同样要还原",
   OVERLAY,
   ["corner", "", "", "diagonal", 1, 2261135997, 90],
   true, ["corner", "", "diagonal", 1, 2261135997, 90, ""]],

  ["片头节点的错位档（后面跟的是数值型）也要认出来",
   CARD,
   ["corner", "", "logo/x.png", 8, true],
   true, ["corner", "", 8, true, "logo/x.png"]],

  ["片头节点的新排列不许动",
   CARD,
   ["corner", "", 8, true, "logo/x.png"],
   false, null],

  // 复合错位：历次增删参数叠加后，报错点会散落在互不相邻的位置，
  // 「整体右移一位」这套置换还原不了。这时必须一点都别改 ——
  // 改错了会被用户顺手存回工作流，把参数永久搅乱（比报错更糟）。
  ["复合错位（置换后仍对不上）：宁可不修，也不许写坏",
   OVERLAY,
   ["corner", "", 90, "nope", 1, 2261135997, 5],
   false, null],
];

let bad = 0;
for (const [name, names, vals, want, expect] of CASES) {
  const node = mkNode(names);
  node.widgets_values = vals.slice();
  node.widgets.forEach((w, i) => { if (i < vals.length) w.value = vals[i]; });

  let changed;
  try {
    changed = migrateLegacyWidgets(node);
  } catch (e) {
    console.log(`  ✗ ${name}：抛异常 ${e}`);
    bad++; continue;
  }

  const errs = [];
  if (changed !== want) errs.push(`期望${want ? "迁移" : "不动"}，实际${changed ? "迁移了" : "没动"}`);
  // 「不动」必须是真的不动：迁移函数一旦写回 widgets_values，用户顺手保存就会固化错值
  if (!want && JSON.stringify(node.widgets_values) !== JSON.stringify(vals)) {
    errs.push(`判定为不动，却改写了 widgets_values：${JSON.stringify(node.widgets_values)}`);
  }
  if (expect) {
    const got = JSON.stringify(node.widgets_values);
    if (got !== JSON.stringify(expect)) errs.push(`排列不对\n      期望 ${JSON.stringify(expect)}\n      实际 ${got}`);
    const mapped = node.widgets.map((w) => w.value);
    if (JSON.stringify(mapped) !== JSON.stringify(expect)) errs.push(`控件的值没跟着更新：${JSON.stringify(mapped)}`);
  }

  if (errs.length) { console.log(`  ✗ ${name}：${errs.join("；")}`); bad++; }
  else console.log(`  ✓ ${name}：${changed ? "已还原" : "保持原样"}`);
}

/* ---------------------------------------------------------------------
 * 数字框：精度与吸附
 * -------------------------------------------------------------------
 * 这几条守的是「面板上的数字框与 ComfyUI 原生控件落在同一张网格上」：
 *   · 显示不许把用户敲的精度抹掉（0.375 显示成 0.4 就再也对不上了）；
 *   · 边敲边写只写「完整且合法」的值，越界与半成品一律等收口；
 *   · 收口才夹范围 + 吸附网格，且吸附后要再夹一次（不然会越界）。
 * ------------------------------------------------------------------- */
const NUM = [];
let numTotal = 0;
const eq = (name, got, want) => {
  numTotal++;
  if (!Object.is(got, want)) NUM.push(`${name}：期望 ${JSON.stringify(want)}，实际 ${JSON.stringify(got)}`);
};

eq("numText(0.375) 不许四舍五入成 0.4", numText(0.375), "0.375");
eq("numText(0.1+0.2) 收浮点尾巴", numText(0.1 + 0.2), "0.3");
eq("numText(0)", numText(0), "0");
eq("numText('')", numText(""), "");
eq("numText(null)", numText(null), "");
eq("numText(NaN)", numText(NaN), "");

eq("parseNum 合法值照收", parseNum("0.375", 0, 1), 0.375);
eq("parseNum 高于上限先不写", parseNum("1.5", 0, 1), null);
eq("parseNum 低于下限先不写", parseNum("0", 0.02, 1), null);
eq("parseNum('-') 敲一半", parseNum("-", 0, 1), null);
eq("parseNum('1.') 已经是个数", parseNum("1.", 0, 10), 1);
eq("parseNum('') 空框（Number('')===0，必须挡掉）", parseNum("", 0, 1), null);
eq("parseNum(' ') 空格", parseNum(" ", 0, 1), null);
eq("parseNum('abc')", parseNum("abc", 0, 1), null);

eq("commitNum 高于上限夹回来", commitNum("1.5", 0, 1, 0.01), 1);
eq("commitNum 低于下限夹上来", commitNum("-3", 0, 1, 0.01), 0);
eq("commitNum 吸附到网格", commitNum("0.375", 0, 1, 0.01), 0.38);
eq("commitNum grid=0 不吸附", commitNum("0.375", 0, 1, 0), 0.375);
eq("commitNum 吸附到 0.5 网格", commitNum("12.34", 1, 100, 0.5), 12.5);
eq("commitNum 空框交给调用方", commitNum("", 0, 1, 0.01), null);
eq("commitNum 吸附后仍要落在下限内", commitNum("0.001", 0.02, 1, 0.01), 0.02);

eq("stepOf 优先 step2（options.step 是 step*10，不是步长）",
   stepOf({ options: { step: 0.1, step2: 0.01, precision: 2 } }), 0.01);
eq("stepOf 没有 step2 时退到 precision", stepOf({ options: { step: 5, precision: 2 } }), 0.01);
eq("stepOf 什么都没有时兜底 1", stepOf(undefined), 1);
eq("gridOf 用 round", gridOf({ options: { round: 0.1, step2: 0.5, precision: 1 } }), 0.1);
eq("gridOf 没有 round 时退到 precision", gridOf({ options: { step2: 0.5, precision: 1 } }), 0.1);

if (NUM.length) { NUM.forEach((m) => console.log(`  ✗ ${m}`)); bad++; }
else console.log(`  ✓ 数字框：${numTotal} 条（显示精度 / 边敲 / 收口吸附 / 步长）全过`);

// valueFits 的边界：别把「范围内的数值」「合法下拉项」判成错位
const fp = TYPES.float_path;
if (!valueFits({ ...fp }, "diagonal")) { console.log("  ✗ valueFits：合法的下拉项被判成错位"); bad++; }
if (valueFits({ ...fp }, "nope")) { console.log("  ✗ valueFits：非法下拉项没被认出来"); bad++; }
if (valueFits({ type: "number", options: { min: 0, max: 200 } }, 500)) { console.log("  ✗ valueFits：超上限的数值没被认出来"); bad++; }
if (valueFits({ type: "toggle" }, 8)) { console.log("  ✗ valueFits：布尔位拿到数字没被认出来"); bad++; }
if (!valueFits({ type: "number", options: { min: 0, max: 200 } }, undefined)) { console.log("  ✗ valueFits：缺值应该算「没得比」，不该拦"); bad++; }

// inputLinked：text_in 是 forceInput 的口，不是 widget，只能从 node.inputs 上读连线。
// 判错的后果是「接了线但面板不说」，比报错更隐蔽 —— 用户会以为参数没生效，
// 回头去改一个根本不起作用的文字框。
const LINKED = [
  ["接上线（link 是数字 id）", { inputs: [{ name: "text_in", link: 3 }] }, true],
  ["没接（link=null）", { inputs: [{ name: "text_in", link: null }] }, false],
  ["没接（link=-1，老写法）", { inputs: [{ name: "text_in", link: -1 }] }, false],
  ["没接（link=0）", { inputs: [{ name: "text_in", link: 0 }] }, false],
  ["没有 link 字段", { inputs: [{ name: "text_in" }] }, false],
  ["被「转为输入」的 widget 形态（name 在 widget 上）",
   { inputs: [{ widget: { name: "text_in" }, link: 5 }] }, true],
  ["同名的是别的口，不算数", { inputs: [{ name: "logo", link: 7 }] }, false],
  ["节点还没有 inputs", {}, false],
  ["inputs 里有空洞（undefined）", { inputs: [undefined, { name: "text_in", link: 9 }] }, true],
];
let linkBad = 0;
for (const [label, node, want] of LINKED) {
  const got = inputLinked(node, "text_in");
  if (got !== want) { console.log(`  ✗ inputLinked ${label}：期望 ${want}，实际 ${got}`); linkBad++; }
}
if (linkBad) bad++;
else console.log(`  ✓ 连线状态判定：${LINKED.length} 条（接上 / 拔掉 / 各种未接形态）全过`);

console.log(bad ? `MIGRATION_FAIL ${bad}` : "MIGRATION_OK");
process.exit(bad ? 1 : 0);
"""


def find_node() -> str:
    for p in NODE_CANDIDATES:
        if p and os.path.isfile(p):
            return p
    return ""


def run(node: str, args, **kw):
    return subprocess.run([node] + list(args), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", **kw)


def main() -> int:
    node = find_node()
    if not node:
        print("没找到 node，跳过前端脚本检查（装了 node 再跑就能查语法与迁移逻辑）")
        return 0
    print(f"node：{node}")

    if not os.path.isfile(JS_PATH):
        print(f"找不到 {JS_PATH}")
        return 1
    src = open(JS_PATH, encoding="utf-8").read()

    problems = []
    with tempfile.TemporaryDirectory(prefix="vmk_js_") as d:
        # ---- 1. 语法 ----
        raw = os.path.join(d, "raw.js")
        with open(raw, "w", encoding="utf-8", newline="\n") as f:
            f.write(src)
        r = run(node, ["--check", raw])
        if r.returncode != 0:
            problems.append("语法错误：\n" + (r.stderr or r.stdout).strip())
        print("语法检查：" + ("✗ 有语法错" if problems else "✓ 通过"))

        # ---- 2. 坑位迁移行为 ----
        if IMPORTS not in src:
            problems.append("找不到前端 import 那两行，测试桩没法打（文件结构变了？）")
        else:
            body = src.replace(IMPORTS, "").rstrip() + \
                "\nexport { migrateLegacyWidgets, valueFits," \
                " numText, parseNum, commitNum, stepOf, gridOf, inputLinked };\n"
            with open(os.path.join(d, "vmk_module.mjs"), "w", encoding="utf-8", newline="\n") as f:
                f.write(STUBS + "\n" + body)
            with open(os.path.join(d, "vmk_test.mjs"), "w", encoding="utf-8", newline="\n") as f:
                f.write(TEST_JS)
            r = run(node, [os.path.join(d, "vmk_test.mjs")], cwd=d)
            out = ((r.stdout or "") + (r.stderr or "")).strip()
            print("坑位迁移行为：")
            for ln in out.splitlines():
                print("  " + ln)
            if r.returncode != 0 or "MIGRATION_FAIL" in out:
                problems.append("坑位迁移的行为测试没全过（见上面输出）")

    if problems:
        print("\n发现问题：")
        for p in problems:
            print(f"  ✗ {p}")
        return 1
    print("\n✓ 前端脚本：语法通过、坑位迁移行为符合预期。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
