/* =====================================================================
 * comfyui-videomark — 可视化面板
 * =====================================================================
 *
 * 设计取舍（改这个文件前先看一遍）
 * ---------------------------------
 * 1. 面板只是「皮肤」：所有值仍然写回原来的 widget，节点的 INPUT_TYPES 一个没删。
 *    所以老工作流照常加载、API 提交照常、参数序列化照常 —— 面板坏掉最差也只是
 *    回到「手动填参数」，不会让存好的工作流失效。
 *
 * 2. 样式预设表从后端 /videomark/meta 取，前端不抄。
 *    抄一份的下场是「后端调了预设，面板滑块还摆在老位置」。
 *
 * 3. 这一版**没有内置预览**。预览只有两条路：自己在前端画一份（渲染逻辑
 *    实现两遍，早晚和出片不一致），或走一次后端渲染（拖滑块 130ms 防抖 +
 *    一张 PNG 往返，拖起来发涩）。而水印是「放上去就长期不变」的东西，
 *    看一次出片就知道了 —— 所以整条预览链路（前端预览区 + 后端预览接口）
 *    全部撤掉，面板只留 内容 / 样式 / 微调 / 进阶参数。
 *
 * 4. 滑块用「0 = 关闭」表达开关：不额外放 checkbox。
 *    描边滑块拉到底就是关掉描边，比「开关 + 数值」两个控件少一半歧义。
 *
 * 5. 每个数值都给两个入口：滑块粗调、数字框精调。而滑块的 min/max/step
 *    一律从后端 widget.options 取，模板里一个数都不写 —— 前端另抄一份边界，
 *    等于同时准备好「悄悄砍掉合法值」和「放进后端会拒的值」两种坏法。
 */

import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

/* ---------------------------------------------------------------------
 * i18n
 * ------------------------------------------------------------------- */

const DICT = {
  zh: {
    content: "内容",
    c_text: "只用文字",
    c_both: "文字 + Logo",
    c_logo: "只用 Logo",
    textPh: "版权文字，可回车换行",
    extIn: "已接外部文字（text_in）：以连线内容为准，手填的这段暂不生效",
    upload: "上传 Logo（PNG）",
    clear: "清除",
    noLogo: "未选 Logo",
    layout: "排布",
    l_vertical: "上下",
    l_horizontal: "左右",
    style: "水印样式",
    position: "贴角",
    tune: "微调",
    s_size: "大小",
    s_opacity: "透明度",
    s_stroke: "描边",
    s_shadow: "阴影",
    s_margin: "边距",
    s_gap: "平铺间距",
    s_angle: "旋转",
    f_path: "浮动轨迹",
    fp_diagonal: "对角",
    fp_horizontal: "水平",
    fp_vertical: "垂直",
    fp_circle: "绕圈",
    fp_random: "随机跳位",
    m_corner: "四角固定",
    m_center: "居中",
    m_floating: "浮动",
    m_tile: "平铺",
    pos_top_left: "左上",
    pos_top_right: "右上",
    pos_bottom_left: "左下",
    pos_bottom_right: "右下",
    adv: "进阶参数",
    a_font: "字体",
    a_color: "文字颜色",
    a_range: "出现区间",
    a_fade: "淡入淡出(帧)",
    a_seed: "随机种子",
    a_cycles: "浮动圈数",
    card: "片头 / 片尾版权页",
    cardOn: "启用",
    cardWhere: "加在哪",
    w_head: "片头",
    w_tail: "片尾",
    w_both: "两头都加",
    seconds: "时长(秒)",
    bg: "卡片底色",
    cardTextPh: "版权声明；留空则复用上面的文字",
    t_size: "文字大小",
    t_logoSize: "Logo 大小",
    t_stroke: "文字描边",
    t_fade: "淡入淡出(帧)",
    up_loading: "上传中…",
    up_failed: "上传失败",
    up_ok: "已上传",
    up_noname: "后端未返回文件名",
    fps: "帧率",
    pad: "自动补静音",
    off: "关闭",
    range: "取值范围",
    a_start: "开始",
    a_end: "结束",
  },
  en: {
    content: "Content",
    c_text: "Text only",
    c_both: "Text + Logo",
    c_logo: "Logo only",
    textPh: "Copyright text, Enter for a new line",
    extIn: "External text linked (text_in): the wired text wins, this field is ignored",
    upload: "Upload logo (PNG)",
    clear: "Clear",
    noLogo: "No logo",
    layout: "Layout",
    l_vertical: "Stacked",
    l_horizontal: "Inline",
    style: "Style",
    position: "Corner",
    tune: "Fine-tune",
    s_size: "Size",
    s_opacity: "Opacity",
    s_stroke: "Stroke",
    s_shadow: "Shadow",
    s_margin: "Margin",
    s_gap: "Tile gap",
    s_angle: "Rotate",
    f_path: "Float path",
    fp_diagonal: "Diagonal",
    fp_horizontal: "Horizontal",
    fp_vertical: "Vertical",
    fp_circle: "Circle",
    fp_random: "Random",
    m_corner: "Corners",
    m_center: "Center",
    m_floating: "Floating",
    m_tile: "Tiled",
    pos_top_left: "Top L",
    pos_top_right: "Top R",
    pos_bottom_left: "Bot L",
    pos_bottom_right: "Bot R",
    adv: "Advanced",
    a_font: "Font",
    a_color: "Text colour",
    a_range: "Visible range",
    a_fade: "Fade frames",
    a_seed: "Seed",
    a_cycles: "Float cycles",
    card: "Head / tail copyright card",
    cardOn: "Enable",
    cardWhere: "Placement",
    w_head: "Head",
    w_tail: "Tail",
    w_both: "Both",
    seconds: "Seconds",
    bg: "Card background",
    cardTextPh: "Copyright notice; blank = reuse the text above",
    t_size: "Text size",
    t_logoSize: "Logo size",
    t_stroke: "Text stroke",
    t_fade: "Fade frames",
    up_loading: "Uploading…",
    up_failed: "Upload failed",
    up_ok: "Uploaded",
    up_noname: "server returned no filename",
    fps: "FPS",
    pad: "Pad audio with silence",
    off: "Off",
    range: "range",
    a_start: "Start",
    a_end: "End",
  },
};

function detectLang() {
  let loc = "";
  try {
    const v = app?.ui?.settings?.getSettingValue?.("Comfy.Locale");
    if (v) loc = String(v);
  } catch (e) { /* 老版本前端没有这个设置项 */ }
  if (!loc) {
    try {
      const raw = localStorage.getItem("Comfy.Settings.Comfy.Locale");
      if (raw) loc = String(JSON.parse(raw));
    } catch (e) { /* 忽略 */ }
  }
  if (!loc && typeof navigator !== "undefined") loc = navigator.language || "";
  return String(loc).toLowerCase().startsWith("zh") ? "zh" : "en";
}

const LANG = detectLang();
const t = (k) => (DICT[LANG] && DICT[LANG][k]) || DICT.en[k] || k;

/* ---------------------------------------------------------------------
 * 样式卡片的示意图（内联 SVG，颜色走 currentColor 自动跟随主题）
 * ------------------------------------------------------------------- */

const svgWrap = (inner) =>
  `<svg viewBox="0 0 44 44" aria-hidden="true"><rect class="fr" x="2" y="2" width="40" height="40" rx="4"/>${inner}</svg>`;

const ICONS = {
  corner: svgWrap(`
    <rect class="mk" x="28" y="29" width="11" height="6" rx="1.5"/>`),
  center: svgWrap(`
    <rect class="mk" x="16" y="19" width="12" height="6" rx="1.5"/>`),
  floating: svgWrap(`
    <path class="tr" d="M10 33 L34 11"/>
    <rect class="mk dim" x="26" y="14" width="9" height="5" rx="1.5"/>
    <rect class="mk dim" x="18" y="22" width="9" height="5" rx="1.5"/>
    <rect class="mk" x="9" y="29" width="9" height="5" rx="1.5"/>`),
  tile: svgWrap(`
    <rect class="mk dim" x="7" y="7" width="9" height="5" rx="1.2"/>
    <rect class="mk dim" x="20" y="7" width="9" height="5" rx="1.2"/>
    <rect class="mk dim" x="33" y="7" width="9" height="5" rx="1.2"/>
    <rect class="mk dim" x="13" y="19" width="9" height="5" rx="1.2"/>
    <rect class="mk dim" x="26" y="19" width="9" height="5" rx="1.2"/>
    <rect class="mk dim" x="7" y="31" width="9" height="5" rx="1.2"/>
    <rect class="mk dim" x="20" y="31" width="9" height="5" rx="1.2"/>
    <rect class="mk dim" x="33" y="31" width="9" height="5" rx="1.2"/>`),
  title: svgWrap(`
    <rect class="blk" x="2" y="2" width="40" height="40" rx="4"/>
    <rect class="mk" x="13" y="19" width="18" height="3.5" rx="1.2"/>
    <rect class="mk dim" x="16" y="25" width="12" height="3" rx="1.2"/>`),
};

/* ---------------------------------------------------------------------
 * 节点参数清单（必须和后端 INPUT_TYPES 一一对应；
 * tools/uicheck.py 会做交叉校验，防止这里写错名字导致参数看不见）
 * ------------------------------------------------------------------- */

// 画面水印的通用参数：视频逐帧与单张图片共用同一套。
//
// ⚠ 这份名单的顺序不影响序列化，但**必须和后端 INPUT_TYPES 保持一致**：
//   后端把 logo_file 钉在末尾（_with_logo()），这里也就把它放末尾
//   （每个 SPECS 的最后一项），别让它回到中间 ——
//   两份顺序不一样时，下次「照着这边往后端加参数」就会把坑位错位重新埋回去。
const WM_WIDGETS = [
  "mode", "position", "text", "opacity", "scale", "margin", "use_text", "use_logo",
  "layout", "color", "style", "use_stroke", "stroke_width", "stroke_color",
  "stroke_opacity", "use_shadow", "shadow_color", "shadow_opacity", "shadow_offset",
  "shadow_blur", "angle", "font", "font_file", "float_path",
  "seed", "tile_gap",
];

// 时间轴相关的五个：首尾保留百分比、淡入淡出、浮动圈数。
// 名字里带 timeline 不代表「单张图用不了」—— 单张图整张算第 0 帧，
// start_pct / end_pct 的默认值（0 / 1）照样把它覆盖住，不会把水印算没。
const WM_TIMELINE = ["float_cycles", "start_pct", "end_pct", "fade_frames"];

const SPECS = {
  VideoMarkOverlay: {
    widgets: [...WM_WIDGETS, ...WM_TIMELINE, "logo_file"],
    modes: ["corner", "center", "floating", "tile"],
    title: false,
  },
  VideoMarkVideo: {
    widgets: [...WM_WIDGETS, ...WM_TIMELINE,
              "title_mode", "title_seconds", "title_text", "title_bg_color", "logo_file"],
    modes: ["corner", "center", "floating", "tile"],
    title: true,
  },
  VideoMarkTitle: {
    widgets: [
      "fps", "where", "seconds", "text", "use_text", "bg_color", "use_logo", "layout",
      "logo_scale", "text_scale", "text_color", "text_stroke_width", "text_stroke_color",
      "font", "font_file", "fade_frames", "pad_audio", "logo_file",
    ],
    cardOnly: true,
    title: true,
  },
};

/* ---------------------------------------------------------------------
 * CSS
 * ------------------------------------------------------------------- */

const CSS = `
.vmk {
  --vmk-fg: var(--fg-color, #ddd);
  --vmk-dim: var(--descrip-text, #999);
  --vmk-line: var(--border-color, #4e4e4e);
  --vmk-input: var(--comfy-input-bg, #222);
  --vmk-accent: var(--p-primary-color, #5b9bd5);
  width: 100%; height: 100%; overflow: hidden;
  font-size: 12px; color: var(--vmk-fg);
  box-sizing: border-box; padding: 0 2px 6px;
}
.vmk * { box-sizing: border-box; }
.vmk-inner { display: flex; flex-direction: column; gap: 8px; }

/* 瞬时提示位（目前只有「上传 logo」在用） */
.vmk-status {
  display: none; padding: 4px 8px; border-radius: 4px; font-size: 11px;
  background: var(--vmk-input); color: var(--vmk-dim); text-align: center;
}
.vmk-status.show { display: block; }
.vmk-status.err { color: #ffb4b4; }

/* 「外部文字已接管」提示条：text_in 是 forceInput 的连线口，不是控件，
   用户在手填框里看不到「值到底从哪来」，接上线就得明说手填的那段不作数了。 */
.vmk-ext {
  display: none; padding: 4px 7px; border-radius: 4px; font-size: 11px; line-height: 1.35;
  border: 1px dashed var(--vmk-accent); color: var(--vmk-accent);
}
.vmk-ext.show { display: block; }
textarea.vmk-text.over { opacity: .5; }

.vmk-sec { border: 1px solid var(--vmk-line); border-radius: 6px; overflow: hidden; }
.vmk-hd {
  display: flex; align-items: center; gap: 6px; padding: 5px 8px;
  background: var(--vmk-input); cursor: pointer; user-select: none; font-size: 11px;
  color: var(--vmk-dim);
}
.vmk-hd b { color: var(--vmk-fg); font-weight: 600; }
.vmk-hd .car { margin-left: auto; transition: transform .12s; }
.vmk-sec.closed .car { transform: rotate(-90deg); }
.vmk-bd { padding: 7px 8px 8px; display: flex; flex-direction: column; gap: 7px; }
.vmk-sec.closed .vmk-bd { display: none; }

.vmk-row { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.vmk-lbl { font-size: 11px; color: var(--vmk-dim); min-width: 44px; }

.vmk-seg { display: flex; gap: 4px; flex: 1; flex-wrap: wrap; }
.vmk-seg button {
  flex: 1 1 auto; min-width: 46px; padding: 4px 5px; border-radius: 4px; cursor: pointer;
  border: 1px solid var(--vmk-line); background: var(--vmk-input); color: var(--vmk-dim);
  font-size: 11px; white-space: nowrap;
}
.vmk-seg button.on { border-color: var(--vmk-accent); color: #fff; background: var(--vmk-accent); }

textarea.vmk-text {
  width: 100%; min-height: 46px; resize: vertical; padding: 5px 6px; border-radius: 4px;
  border: 1px solid var(--vmk-line); background: var(--vmk-input); color: var(--vmk-fg);
  font-size: 12px; font-family: inherit;
}

.vmk-cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: 5px; }
.vmk-cards.c5 { grid-template-columns: repeat(5, 1fr); }
.vmk-card {
  display: flex; flex-direction: column; align-items: center; gap: 3px; padding: 5px 2px;
  border-radius: 5px; cursor: pointer; border: 1px solid var(--vmk-line);
  background: var(--vmk-input); color: var(--vmk-dim); font-size: 10px; line-height: 1.15;
  text-align: center;
}
.vmk-card svg { width: 34px; height: 34px; }
.vmk-card.on { border-color: var(--vmk-accent); color: #fff; background: var(--vmk-accent); }
.vmk-card svg .fr { fill: none; stroke: currentColor; stroke-width: 1.4; opacity: .55; }
.vmk-card svg .tr { fill: none; stroke: currentColor; stroke-width: 1.2; opacity: .5; stroke-dasharray: 2.5 2.5; }
.vmk-card svg .mk { fill: currentColor; }
.vmk-card svg .mk.dim { opacity: .5; }
.vmk-card svg .blk { fill: currentColor; opacity: .3; }

.vmk-grid4 { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; flex: 1; }
.vmk-grid4 button {
  position: relative; height: 24px; border-radius: 4px; cursor: pointer;
  border: 1px solid var(--vmk-line); background: var(--vmk-input);
}
.vmk-grid4 button.on { border-color: var(--vmk-accent); background: var(--vmk-accent); }
.vmk-grid4 button::after {
  content: ""; position: absolute; width: 8px; height: 4px; border-radius: 1px;
  background: var(--vmk-dim);
}
.vmk-grid4 button.on::after { background: #fff; }
.vmk-grid4 button[data-v="top_left"]::after    { left: 4px;  top: 4px; }
.vmk-grid4 button[data-v="top_right"]::after   { right: 4px; top: 4px; }
.vmk-grid4 button[data-v="bottom_left"]::after { left: 4px;  bottom: 4px; }
.vmk-grid4 button[data-v="bottom_right"]::after{ right: 4px; bottom: 4px; }

.vmk-sl { display: flex; align-items: center; gap: 6px; }
.vmk-sl > span { min-width: 58px; font-size: 11px; color: var(--vmk-dim); }
.vmk-sl input[type=range] { flex: 1; min-width: 50px; accent-color: var(--vmk-accent); }

/* 数值框：滑块负责粗调，这里负责精确输入。
   宽度写死、不参与 flex，否则拖动滑块时整行会跟着值变宽变窄。
   min/max/step 一概不写在这里，由 applyBounds() 从后端声明灌进来。 */
.vmk-sl > .vmk-num {
  flex: none; width: 52px; height: 19px; padding: 0 4px;
  text-align: right; font-size: 11px; font-variant-numeric: tabular-nums;
  border-radius: 4px; border: 1px solid var(--vmk-line);
  background: var(--vmk-input); color: var(--vmk-fg);
  -moz-appearance: textfield; appearance: textfield;
}
.vmk-sl > .vmk-num::-webkit-outer-spin-button,
.vmk-sl > .vmk-num::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
.vmk-sl > .vmk-num:focus { outline: none; border-color: var(--vmk-accent); }
/* 还没被采纳的输入：越界、或敲到一半（"-"、"0."）。写进节点的永远只有合法值，
   所以红边不是在报错，是在说「这个数还没生效」 */
.vmk-sl > .vmk-num:invalid { border-color: #b06a6a; }
.vmk-sl > .vmk-u { font-size: 10px; font-style: normal; color: var(--vmk-dim); }

.vmk-logo { display: flex; align-items: center; gap: 6px; }
.vmk-btn {
  padding: 4px 8px; border-radius: 4px; cursor: pointer; font-size: 11px;
  border: 1px solid var(--vmk-line); background: var(--vmk-input); color: var(--vmk-fg);
}
.vmk-btn:hover { border-color: var(--vmk-accent); }
.vmk-thumb {
  width: 30px; height: 30px; border-radius: 4px; border: 1px solid var(--vmk-line);
  background: repeating-conic-gradient(#3a3a3a 0% 25%, #4a4a4a 0% 50%) 50% / 8px 8px;
  object-fit: contain; flex: none;
}
.vmk-name {
  flex: 1; font-size: 10px; color: var(--vmk-dim); overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap;
}
.vmk-warn { font-size: 10px; color: #e0a44a; }

`;

let cssDone = false;
function injectCSS() {
  if (cssDone) return;
  cssDone = true;
  const el = document.createElement("style");
  el.textContent = CSS;
  document.head.appendChild(el);
}

/* ---------------------------------------------------------------------
 * 后端元数据（样式预设表）—— 只拉一次，全局共享
 * ------------------------------------------------------------------- */

let metaPromise = null;

function metaReady() {
  if (!metaPromise) {
    metaPromise = (async () => {
      try {
        const res = await api.fetchApi("/videomark/meta");
        if (res.ok) return await res.json();
      } catch (e) { /* 接口没挂上：预设档就只是保持原值，滑块照常能用 */ }
      return null;
    })();
  }
  return metaPromise;
}

/* ---------------------------------------------------------------------
 * widget 读写
 * ------------------------------------------------------------------- */

function findWidget(node, name) {
  return (node.widgets || []).find((w) => w.name === name);
}
function wget(node, name) {
  const w = findWidget(node, name);
  return w ? w.value : undefined;
}
function wset(node, name, v) {
  const w = findWidget(node, name);
  if (!w) return false;
  w.value = v;
  return true;
}
function touch(node) {
  node.setDirtyCanvas?.(true, true);
  try { node.graph?.change?.(); } catch (e) { /* 忽略 */ }
}

// forceInput 的口（如 text_in）**不是 widget**，wget() 读不到它们 ——
// 「有没有接线」这件事只存在于 node.inputs 上。抽成顶层纯函数是为了让
// tools/jscheck.py 能直接测（写在 buildPanel 闭包里就测不到了）。
// 三种形态都要认：普通 input、被「转为输入」的 widget、以及压根没这个口。
function inputLinked(node, name) {
  for (const inp of (node && node.inputs) || []) {
    if (!inp) continue;
    if ((inp.name ?? inp.widget?.name) !== name) continue;
    const l = inp.link;
    // litegraph 里 link 是数字 id（未接 = null / -1 / 0），个别版本塞的是对象
    return typeof l === "number" ? l > 0 : Boolean(l);
  }
  return false;                                     // 节点上没有这个口 = 没接
}

/* ---------------------------------------------------------------------
 * 数值控件的边界与精度（纯函数，tools/jscheck.py 会直接测它们）
 * -------------------------------------------------------------------
 * 0.34.1 里「步长」和「落值吸附网格」是**两个不同字段**，别混：
 *
 *   options.step   = 声明的 step × 10 —— 拖拽灵敏度，别拿它当步长
 *   options.step2  = 声明的 step —— 真步长，箭头键一格走这么多
 *   options.round  = 10^-precision —— FLOAT 落值时按它四舍五入
 *
 * 面板要跟原生控件落在同一张网格上，所以 step 取 step2、吸附取 round。
 * ------------------------------------------------------------------- */

function stepOf(w) {
  const o = (w && w.options) || {};
  if (typeof o.step2 === "number" && o.step2 > 0) return o.step2;
  if (typeof o.precision === "number" && o.precision >= 0) return Math.pow(10, -o.precision);
  if (typeof o.step === "number" && o.step > 0) return o.step;
  return 1;
}

function gridOf(w) {
  const o = (w && w.options) || {};
  if (typeof o.round === "number" && o.round > 0) return o.round;
  if (typeof o.precision === "number" && o.precision >= 0) return Math.pow(10, -o.precision);
  return stepOf(w);
}

// 数字框里显示成什么。不要 toFixed(1) 那种粗糙收敛 —— 把 0.375 显示成 0.4，
// 人就再也对不上节点里到底存了什么。这里只收掉浮点尾巴（0.30000000000000004）。
function numText(v) {
  if (v === "" || v === null || v === undefined) return "";
  const n = Number(v);
  if (!Number.isFinite(n)) return "";
  return String(Number(n.toFixed(6)));
}

// 边敲边用：返回 null = 「此刻别写」。
// 敲到一半（"-"、"1."、空）写回去等于把用户正在敲的字擦掉；
// 越界先不写，等收口时再夹进范围 —— 这样节点上永远不留后端会拒的值。
function parseNum(raw, lo, hi) {
  const t = String(raw).trim();
  if (!t) return null;                       // Number("") === 0，这里必须先挡掉
  const v = Number(t);
  if (!Number.isFinite(v)) return null;
  if (Number.isFinite(lo) && v < lo) return null;
  if (Number.isFinite(hi) && v > hi) return null;
  return v;
}

// 收口（失焦 / 回车 / change）：夹进范围 + 吸附到网格。
// 输入不是数 → null，调用方保留原值（别把空框当成 0 写进去）。
function commitNum(raw, lo, hi, grid) {
  const t = String(raw).trim();
  if (!t) return null;                       // 空框不是 0（Number("") === 0），别把空框写成 0
  const v = Number(t);
  if (!Number.isFinite(v)) return null;
  let n = v;
  if (Number.isFinite(lo)) n = Math.max(lo, n);
  if (Number.isFinite(hi)) n = Math.min(hi, n);
  if (grid > 0) n = Number((Math.round(n / grid) * grid).toFixed(6));
  if (Number.isFinite(lo)) n = Math.max(lo, n);      // 吸附后再夹一次，别越过边界
  if (Number.isFinite(hi)) n = Math.min(hi, n);
  return n;
}

/* ---------------------------------------------------------------------
 * 老工作流的控件坑位迁移
 * ---------------------------------------------------------------------
 * ComfyUI 的工作流按「位置」存控件值（widgets_values 是个数组，不是字典）。
 * logo_file 是后加的参数，早期被插在 font_file 与 float_path 之间 ——
 * 于是「按那一版存下来的工作流」加载时，从该位置起所有控件的值整体右移一位，
 * 报出来的三条错长得完全不像同一件事：
 *
 *     float_path   输入值 1 不可用                   ← 其实是老的 float_cycles
 *     float_cycles 输入值 2261135997 高于最大值 200   ← 其实是老的 seed
 *     seed         输入值 randomize 无法转换为 INT     ← 其实是老的 control_after_generate
 *
 * 后端已经把 logo_file 挪到末尾（新存的工作流不会再有这个问题），
 * 这个函数负责把「已经错位存下来」的旧档就地还原：那个位置若装着一个
 * 该控件吃不下的值，就说明它是错位后的 logo_file，摘出来放回末尾即可。
 *
 * 判定条件刻意收得很紧 —— 只在「装不下」时才动手：
 *   · 正常排列：那个槽必然是 diagonal/horizontal/vertical/circle/random，命中即返回；
 *   · 更老的一版（压根没有 logo_file）：槽里是 float_path 的值，同样命中，返回；
 *   · 只有错位档会出现「下拉里没有这个值 / 数值型拿到字符串」。
 *
 * 但「装不下」只是嫌疑，不是证据 —— 历次增删参数叠加起来会产生**复合错位**，
 * 报错点散落在互不相邻的位置（实测见过 seed / start_pct / end_pct / tile_gap
 * 同时出错），而上面这套置换只能还原「整体右移一位」那一种。所以置换完必须
 * 再过一道全量校验：**只要还剩一个控件对不上，就一点都不许改**。
 * 宁可让它照原样报错（用户看得见、能删了重加），也不能把值搅乱之后被存进工作流。
 * ------------------------------------------------------------------- */

function valueFits(w, v) {
  if (!w || v === undefined) return true;                  // 没值 = 用默认，不算错位
  const vals = w.options && w.options.values;
  if (Array.isArray(vals)) return vals.some((x) => String(x) === String(v));
  const o = w.options || {};
  if (w.type === "toggle") return typeof v === "boolean";
  if (w.type === "number" || w.type === "slider") {
    if (typeof v !== "number" || !isFinite(v)) return false;
    if (typeof o.min === "number" && v < o.min - 1e-6) return false;
    if (typeof o.max === "number" && v > o.max + 1e-6) return false;
  }
  return true;                                             // 字符串型不判
}

/* 数一下「值对不上控件」的槽位有几个。0 = 完全对齐。 */
function countFlaws(ws, vals) {
  const n = Math.min(ws.length, vals.length);
  let flaws = 0;
  for (let i = 0; i < n; i++) {
    const w = ws[i];
    if (w && w.name !== "VideoMarkUI" && !valueFits(w, vals[i])) flaws++;
  }
  return flaws;
}

function migrateLegacyWidgets(node) {
  const vals = node && node.widgets_values;
  const ws = (node && node.widgets) || [];
  if (!Array.isArray(vals) || vals.length < 3) return false;

  const li = ws.findIndex((w) => w.name === "logo_file");
  const ni = ws.findIndex((w) => w.name === "font_file");
  // 没有 logo_file 的节点（不该有）或已经是「末尾」排列的，不用管
  if (li < 0 || ni < 0 || li <= ni + 1) return false;
  const bi = ni + 1;                                       // 老版本 logo_file 待过的位置
  if (bi >= vals.length || valueFits(ws[bi], vals[bi])) return false;

  // 错位：vals[bi] 是 logo_file 的值，bi+1..li 每个值都该往左挪一格
  const fixed = vals.slice(0, bi)
    .concat(vals.slice(bi + 1, li + 1), [vals[bi]], vals.slice(li + 1));

  // 写回前先整体验一遍：只有「所有控件都拿到对得上的值」才算还原成功。
  // 对不上就说明是复合错位（这套置换模型不适用），此时不动任何数据。
  const before = countFlaws(ws, vals);
  const after = countFlaws(ws, fixed);
  if (after > 0 || after >= before) {
    console.warn(
      "[videomark] 这个节点的控件值整体错位了，但不是「往后挪一位」那一种，" +
      "自动还原不安全，已放弃（原值保持不动）。\n" +
      "  请删除该节点后重新添加一次（参数重填后保存），或把工作流发我按真实数据修。\n" +
      "  错位槽位数：" + (after || before)
    );
    return false;
  }

  node.widgets_values = fixed;
  ws.forEach((w, i) => {
    if (i < fixed.length && w.name !== "VideoMarkUI") w.value = fixed[i];
  });
  console.log("[videomark] 老工作流控件排列已还原（logo_file 挪回末尾）");
  return true;
}

/* ---------------------------------------------------------------------
 * 面板构建
 * ------------------------------------------------------------------- */

const NODE_CHROME = 84;    // 标题栏 + 插槽占掉的高度，经验值；只为初始高度好看
const PANEL_W = 384;

function buildPanel(node, spec) {
  injectCSS();

  const isCard = !!spec.cardOnly;
  const hasTitle = !!spec.title;

  const root = document.createElement("div");
  root.className = "vmk";
  const inner = document.createElement("div");
  inner.className = "vmk-inner";
  root.appendChild(inner);

  /* ---------------- 内容 ---------------- */
  // 「外部文字已接管」提示条。和文字框挨着放 —— 它是「这个框里的值不作数」的注解，
  // 离远了就失去意义。text_in 没接线时它是隐藏的（.show 才显示）。
  const extBadge = `<div class="vmk-ext" data-ext="text">${t("extIn")}</div>`;

  const logoRow = `
    <div class="vmk-logo">
      <img class="vmk-thumb" alt="" />
      <span class="vmk-name">${t("noLogo")}</span>
      <button class="vmk-btn" data-act="upload">${t("upload")}</button>
      <button class="vmk-btn" data-act="clearlogo">${t("clear")}</button>
      <input type="file" accept="image/*" style="display:none" />
    </div>`;

  const contentBlock = isCard ? `
    <div class="vmk-sec" data-sec="content">
      <div class="vmk-hd"><b>${t("content")}</b><span class="car">▾</span></div>
      <div class="vmk-bd">
        <textarea class="vmk-text" data-f="text" placeholder="${t("cardTextPh")}"></textarea>
        ${extBadge}
        ${logoRow}
        <div class="vmk-row">
          <span class="vmk-lbl">${t("layout")}</span>
          <div class="vmk-seg" data-g="layout">
            <button data-v="vertical">${t("l_vertical")}</button>
            <button data-v="horizontal">${t("l_horizontal")}</button>
          </div>
        </div>
      </div>
    </div>` : `
    <div class="vmk-sec" data-sec="content">
      <div class="vmk-hd"><b>${t("content")}</b><span class="car">▾</span></div>
      <div class="vmk-bd">
        <div class="vmk-seg" data-g="content">
          <button data-v="text">${t("c_text")}</button>
          <button data-v="both">${t("c_both")}</button>
          <button data-v="logo">${t("c_logo")}</button>
        </div>
        <textarea class="vmk-text" data-f="text" placeholder="${t("textPh")}"></textarea>
        ${extBadge}
        ${logoRow}
        <div class="vmk-row">
          <span class="vmk-lbl">${t("layout")}</span>
          <div class="vmk-seg" data-g="layout">
            <button data-v="vertical">${t("l_vertical")}</button>
            <button data-v="horizontal">${t("l_horizontal")}</button>
          </div>
        </div>
      </div>
    </div>`;

  const styleBlock = isCard ? "" : `
    <div class="vmk-sec" data-sec="style">
      <div class="vmk-hd"><b>${t("style")}</b><span class="car">▾</span></div>
      <div class="vmk-bd">
        <div class="vmk-cards" data-g="mode">
          ${spec.modes.map((m) => `
            <div class="vmk-card" data-v="${m}">${ICONS[m] || ""}<span>${t("m_" + m)}</span></div>
          `).join("")}
        </div>
        <div class="vmk-row" data-only="corner">
          <span class="vmk-lbl">${t("position")}</span>
          <div class="vmk-grid4" data-g="position">
            <button data-v="top_left" title="${t("pos_top_left")}"></button>
            <button data-v="top_right" title="${t("pos_top_right")}"></button>
            <button data-v="bottom_left" title="${t("pos_bottom_left")}"></button>
            <button data-v="bottom_right" title="${t("pos_bottom_right")}"></button>
          </div>
        </div>
        <div class="vmk-row" data-only="floating">
          <span class="vmk-lbl">${t("f_path")}</span>
          <div class="vmk-seg" data-g="float_path">
            ${["diagonal", "horizontal", "vertical", "circle", "random"]
              .map((p) => `<button data-v="${p}">${t("fp_" + p)}</button>`).join("")}
          </div>
        </div>
      </div>
    </div>`;

  /* ---------------- 微调 ---------------- */
  // 一行微调：标签 + 滑块（粗调）+ 数字框（精调）+ 单位。
  // 这里**不写 min/max/step**，由 applyBounds() 从后端声明灌进来（见那里的注释）。
  // 面板上所有滑块都必须走这个函数生成 —— 手写 <input type="range"> 会绕过
  // 「配数字框」和「边界取后端」这两件事，那正是 uicheck 拦的东西。
  const sl = (key, label, unit, extra) => `
    <div class="vmk-sl" data-sl="${key}"${extra ? " " + extra : ""}>
      ${label ? `<span>${label}</span>` : ""}
      <input type="range">
      <input type="number" class="vmk-num" inputmode="decimal">
      ${unit ? `<i class="vmk-u">${unit}</i>` : ""}
    </div>`;

  const tuneBlock = isCard ? `
    <div class="vmk-sec" data-sec="tune">
      <div class="vmk-hd"><b>${t("tune")}</b><span class="car">▾</span></div>
      <div class="vmk-bd">
        ${sl("text_scale", t("t_size"), "%")}
        ${sl("logo_scale", t("t_logoSize"), "%")}
        ${sl("text_stroke_width", t("t_stroke"), "px")}
        ${sl("fade_frames", t("t_fade"), "f")}
      </div>
    </div>` : `
    <div class="vmk-sec" data-sec="tune">
      <div class="vmk-hd"><b>${t("tune")}</b><span class="car">▾</span></div>
      <div class="vmk-bd">
        ${sl("scale", t("s_size"), "%")}
        ${sl("opacity", t("s_opacity"), "")}
        ${sl("stroke_opacity", t("s_stroke"), "")}
        ${sl("shadow_opacity", t("s_shadow"), "")}
        ${sl("margin", t("s_margin"), "px")}
        ${sl("tile_gap", t("s_gap"), "px", 'data-only="tile"')}
        ${sl("angle", t("s_angle"), "°")}
      </div>
    </div>`;

  /* ---------------- 片头片尾 ---------------- */
  const cardBlock = (!hasTitle || isCard) ? "" : `
    <div class="vmk-sec" data-sec="card">
      <div class="vmk-hd"><b>${t("card")}</b><span class="car">▾</span></div>
      <div class="vmk-bd">
        <div class="vmk-seg" data-g="title_mode">
          <button data-v="off">${t("off")}</button>
          <button data-v="head">${t("w_head")}</button>
          <button data-v="tail">${t("w_tail")}</button>
          <button data-v="both">${t("w_both")}</button>
        </div>
        <textarea class="vmk-text" data-f="title_text" placeholder="${t("cardTextPh")}"></textarea>
        ${sl("title_seconds", t("seconds"), "s")}
      </div>
    </div>`;

  /* ---------------- 进阶 ---------------- */
  const advBody = isCard ? `
      <div class="vmk-row">
        <span class="vmk-lbl">${t("cardWhere")}</span>
        <div class="vmk-seg" data-g="where">
          <button data-v="head">${t("w_head")}</button>
          <button data-v="tail">${t("w_tail")}</button>
          <button data-v="both">${t("w_both")}</button>
        </div>
      </div>
      ${sl("seconds", t("seconds"), "s")}
      ${sl("fps", t("fps"), "")}
      <div class="vmk-row">
        <span class="vmk-lbl">${t("pad")}</span>
        <div class="vmk-seg" data-g="pad_audio">
          <button data-v="1">${t("cardOn")}</button><button data-v="0">${t("off")}</button>
        </div>
      </div>
  ` : `
      <div class="vmk-row">
        <span class="vmk-lbl">${t("a_font")}</span>
        <div class="vmk-seg" data-g="font_pick"></div>
      </div>
      <div class="vmk-row">
        <span class="vmk-lbl">${t("a_color")}</span>
        <div class="vmk-seg" data-g="color">
          <button data-v="#FFFFFF">白</button>
          <button data-v="#000000">黑</button>
          <button data-v="#FFD400">金</button>
          <button data-v="#FF5A5A">红</button>
        </div>
      </div>
      ${sl("float_cycles", t("a_cycles"), "")}
      ${sl("fade_frames", t("a_fade"), "f")}
      <div class="vmk-row">
        <span class="vmk-lbl">${t("a_range")}</span>
        ${sl("start_pct", null, "", `style="flex:1" title="${t("a_start")}"`)}
        ${sl("end_pct", null, "", `style="flex:1" title="${t("a_end")}"`)}
      </div>
  `;

  inner.insertAdjacentHTML("beforeend", `
    ${contentBlock}
    ${styleBlock}
    ${tuneBlock}
    ${cardBlock}
    <div class="vmk-sec closed" data-sec="adv">
      <div class="vmk-hd"><b>${t("adv")}</b><span class="car">▾</span></div>
      <div class="vmk-bd">${advBody}</div>
    </div>
    <div class="vmk-status"></div>
  `);

  /* ---------------- 挂到节点 ---------------- */

  if (typeof node.addDOMWidget !== "function") {
    console.warn("[videomark] 当前 ComfyUI 前端不支持 addDOMWidget，可视化面板已跳过");
    return;
  }
  // 前端给 DOM widget 的默认外边距是 10px，而画布叠加层的高度是
  // computedHeight - margin*2 —— 也就是可视高度比内容少 20px。
  // 面板根节点是 height:100% + overflow:hidden，少多少就切多少，
  // 关掉「节点 2.0（Vue Nodes）」走画布渲染时底部那截就是这么丢的。
  // 显式传 margin: 0，并把这个值记下来补进 measure()，两条腿一起站稳。
  let panelMargin = 10;                       // 先按前端的默认值算，读到真值再改
  const domW = node.addDOMWidget("VideoMarkUI", "VideoMarkUI", root, {
    hideOnZoom: false,
    serialize: false,
    margin: 0,
    getValue: () => "",
    setValue: () => {},
    getMinHeight: () => measure(),
  });
  if (domW) {
    panelMargin = typeof domW.margin === "number" ? domW.margin : 0;
    domW.computeSize = (width) => [width, measure()];
  }

  // 原生 widget 全部收起 —— 值照旧参与序列化，只是不再占界面
  for (const name of spec.widgets) {
    const w = findWidget(node, name);
    if (!w) continue;
    w.hidden = true;
    w.computeSize = () => [0, -4];
  }

  const $ = (sel) => inner.querySelector(sel);
  const $$ = (sel) => Array.from(inner.querySelectorAll(sel));

  /* ---------------- 边界取自后端声明 ----------------
   * 滑块的 min/max/step 一律从 widget.options 拿，模板里一个数都不写。
   * 写死过一份的代价是实打实的，而且都不报错、肉眼看不出来：
   *   · margin：模板写 0~200，后端其实是 0~600 —— 面板悄悄替用户砍掉了合法值，
   *     用户只会以为「这参数最多只能 200」；
   *   · opacity：模板写 0~1，后端是 0.02~1 —— 面板放进来的一段是后端会拒的，
   *     拖到底再跑就报「输入值低于最小值」。
   * 数字框的 title 顺带把范围写出来，省得靠试。 */
  function applyBounds() {
    for (const box of $$(".vmk-sl[data-sl]")) {
      const name = box.dataset.sl;
      const w = findWidget(node, name);
      const o = (w && w.options) || {};
      const has = (k) => typeof o[k] === "number";
      const rng = box.querySelector("input[type=range]");
      const num = box.querySelector(".vmk-num");
      if (!has("min") || !has("max")) {
        console.warn(`[videomark] 控件 ${name} 没拿到后端边界，滑块范围会退化成浏览器默认值`);
      }
      if (rng) {
        if (has("min")) rng.min = String(o.min);
        if (has("max")) rng.max = String(o.max);
        rng.step = String(stepOf(w));
      }
      if (num) {
        if (has("min")) num.min = String(o.min);
        if (has("max")) num.max = String(o.max);
        num.step = String(stepOf(w));
        if (has("min") && has("max")) num.title = `${t("range")} ${o.min} ~ ${o.max}`;
      }
    }
  }
  applyBounds();          // 必须在任何 bindSlider / paintSlider 之前

  function measure() {
    // + panelMargin*2：若某个版本无视 margin:0 仍按默认值扣，这里补回来，
    // 保证「叠加层可视高度 >= 内容高度」，宁可多几像素空白也不能切内容
    return Math.max(140, inner.offsetHeight + 6 + panelMargin * 2);
  }
  function syncHeight(fit) {
    const target = Math.ceil(measure() + NODE_CHROME);
    if (fit || node.size[1] < target - 2) node.size[1] = target;
    node.setDirtyCanvas?.(true, true);
  }

  /* ---------------- 状态提示 ---------------- */

  const status = $(".vmk-status");
  let statusTimer = null;

  function statusShow(msg, isErr) {
    clearTimeout(statusTimer);
    status.textContent = msg;
    status.className = "vmk-status show" + (isErr ? " err" : "");
    if (!isErr) statusTimer = setTimeout(statusHide, 2500);  // 成功提示自己消失
  }
  function statusHide() { status.className = "vmk-status"; }

  /* ---------------- 通用绑定 ---------------- */

  // 折叠
  $$(".vmk-sec .vmk-hd").forEach((hd) => {
    hd.addEventListener("click", () => {
      hd.parentElement.classList.toggle("closed");
      syncHeight(true);
    });
  });

  // 分段按钮组：data-g 对应 widget 名（或 UI 状态）
  function bindSeg(container, getter, setter) {
    if (!container) return;
    container.addEventListener("click", (ev) => {
      const btn = ev.target.closest("button[data-v]");
      if (!btn || !container.contains(btn)) return;
      ev.stopPropagation();
      setter(btn.dataset.v);
      paintSeg(container, getter());
      touch(node);
    });
  }
  function paintSeg(container, value) {
    // 面板按节点类型拼装，某种节点上不会有别的分组（正片节点没有"片头"、
    // 片头节点没有样式卡片），传进来 null 是常态，不能直接 querySelectorAll
    if (!container) return;
    container.querySelectorAll("button[data-v]").forEach((b) => {
      b.classList.toggle("on", String(b.dataset.v) === String(value));
    });
  }

  // 分段按钮组的选项直接取后端的 choices。
  // 前端另抄一份的下场是"后端加了选项、面板上却选不到"，而那种错没人会收到报错。
  function fillSegFromWidget(box, name, max) {
    if (!box) return;
    const w = findWidget(node, name);
    const vals = (w && w.options && w.options.values) || [];
    const list = max ? vals.slice(0, max) : vals;
    box.innerHTML = list.map((v) =>
      `<button data-v="${String(v).replace(/"/g, "&quot;")}">${
        String(v).slice(0, 10)}</button>`).join("");
  }

  /* 滑块 + 数字框：data-sl 对应 widget 名
   *
   * 两边都不是「真值」，真值永远在 widget 上，两边都只是它的显示。
   * 拖滑块 = 粗调，敲数字 = 精调（用户要的正是后者：用滑块凑到 0.85 很费劲，
   * 敲两个字符就完了）。
   *
   * 三条不能破的规矩：
   *   1. 敲的当下就生效（所见即所得），但**敲到一半和越界一律不写** ——
   *      "-"、"1."、""、超出 min/max 全都返回 null，节点上不留后端会拒的值；
   *   2. 吸附只发生在收口（失焦 / 回车 / change）。边敲边吸附会把用户正在
   *      输入的字改掉（敲 "0.375" 到第三位就被改成 0.38，后面没法接着敲）；
   *   3. 正在这个框里打字时，任何刷新都不许覆盖它 —— 刷新可能是别处触发的
   *      （上传 logo、切样式、折叠分组），覆盖等于把敲了一半的数字吃掉。
   */
  function bindSlider(name, apply) {
    const box = inner.querySelector(`.vmk-sl[data-sl="${name}"]`);
    if (!box) return null;
    const input = box.querySelector("input[type=range]");
    const num = box.querySelector(".vmk-num");
    const w = findWidget(node, name);
    const lo = () => parseFloat(input.min);
    const hi = () => parseFloat(input.max);

    input.addEventListener("input", () => {
      const v = parseFloat(input.value);
      if (num && document.activeElement !== num) num.value = numText(v);
      apply(v);
      touch(node);
    });

    if (num) {
      const commit = () => {
        const v = commitNum(num.value, lo(), hi(), w ? gridOf(w) : 0);
        const nv = v === null ? Number(wget(node, name)) : v;
        num.value = numText(nv);            // 空框 / 乱写 / 越界：收口一定回到合法值
        if (Number.isFinite(nv)) {
          input.value = String(nv);
          apply(nv);
          touch(node);
        }
      };
      num.addEventListener("input", () => {
        const v = parseNum(num.value, lo(), hi());
        if (v === null) return;             // 敲一半 / 越界：等收口，先不写
        input.value = String(v);
        apply(v);
        touch(node);
      });
      num.addEventListener("change", commit);
      num.addEventListener("blur", commit);
      num.addEventListener("keydown", (ev) => {
        ev.stopPropagation();               // 别让画布把按键当快捷键
        if (ev.key === "Enter") num.blur();  // 回车 = 收口
        else if (ev.key === "Escape") {      // Esc = 放弃这次输入，回到节点里的值
          num.value = numText(wget(node, name));
          num.blur();
        }
      });
    }
    return { box, input, num };
  }

  // 把节点里的值铺到滑块 + 数字框上
  function paintSlider(name, v) {
    const box = inner.querySelector(`.vmk-sl[data-sl="${name}"]`);
    if (!box) return;
    const input = box.querySelector("input[type=range]");
    const num = box.querySelector(".vmk-num");
    if (v === undefined || v === null || v === "") { box.style.display = "none"; return; }
    const n = Number(v);
    if (!Number.isFinite(n)) { box.style.display = "none"; return; }
    const c = Math.min(parseFloat(input.max), Math.max(parseFloat(input.min), n));
    input.value = String(c);
    if (num && document.activeElement !== num) num.value = numText(c);
  }

  /* ---------------- 具体控件 ---------------- */

  // 内容：文字 / 文字+logo / 只用 logo
  bindSeg($('[data-g="content"]'), () => contentMode(), (v) => {
    wset(node, "use_text", v !== "logo");
    wset(node, "use_logo", v !== "text");
  });
  function contentMode() {
    const ut = wget(node, "use_text") !== false;
    const ul = wget(node, "use_logo") === true;
    if (ut && ul) return "both";
    if (ul) return "logo";
    return "text";
  }

  const ta = $('[data-f="text"]');
  ta.value = String(wget(node, "text") ?? "");
  ta.addEventListener("input", () => { wset(node, "text", ta.value); touch(node); });

  const cardTa = $('[data-f="title_text"]');
  if (cardTa) {
    cardTa.value = String(wget(node, "title_text") ?? "");
    cardTa.addEventListener("input", () => { wset(node, "title_text", cardTa.value); touch(node); });
  }

  // 外部文字接管提示。手填的文字**不清空**（拔线后还要接着用），只是淡掉 + 挂提示条。
  // 判断依据是连线而不是控件值：text_in 是 forceInput 的口，压根不是 widget。
  function paintExt() {
    const on = inputLinked(node, "text_in");
    $(".vmk-ext")?.classList.toggle("show", on);
    ta?.classList.toggle("over", on);
  }

  bindSeg($('[data-g="layout"]'), () => wget(node, "layout"), (v) => wset(node, "layout", v));

  // logo 上传
  const thumb = $(".vmk-thumb");
  const logoName = $(".vmk-name");
  const fileInput = inner.querySelector('input[type=file]');
  const logoWarn = document.createElement("div");
  logoWarn.className = "vmk-warn";

  function paintLogo() {
    const name = String(wget(node, "logo_file") || "");
    const on = wget(node, "use_logo") === true;
    if (name) {
      logoName.textContent = name;
      const base = (globalThis.location?.origin || "") + (api.apiURL ? api.apiURL("/view") : "/view");
      thumb.src = `${base}?filename=${encodeURIComponent(name.split("/").pop())}&type=input&subfolder=${encodeURIComponent(name.includes("/") ? name.slice(0, name.lastIndexOf("/")) : "")}`;
      logoWarn.textContent = "";
    } else {
      logoName.textContent = t("noLogo");
      thumb.removeAttribute("src");
      logoWarn.textContent = on ? "⚠ " + t("noLogo") : "";
    }
    if (logoWarn.textContent && !logoWarn.parentElement) inner.querySelector(".vmk-logo")?.appendChild(logoWarn);
  }

  $('[data-act="upload"]')?.addEventListener("click", (ev) => { ev.stopPropagation(); fileInput.click(); });
  $('[data-act="clearlogo"]')?.addEventListener("click", (ev) => {
    ev.stopPropagation();
    wset(node, "logo_file", "");
    touch(node);
    refreshUI();
  });
  fileInput?.addEventListener("change", async () => {
    const f = fileInput.files && fileInput.files[0];
    fileInput.value = "";
    if (!f) return;
    statusShow(t("up_loading"), false);
    let data;
    try {
      if (typeof api.uploadImage === "function") {
        data = await api.uploadImage(f);
      } else {
        const body = new FormData();
        body.append("image", f);
        const res = await api.fetchApi("/upload/image", { method: "POST", body });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        data = await res.json();
      }
    } catch (e) {
      statusShow(`${t("up_failed")}: ${e?.message || e}`, true);
      return;
    }
    // 走到这里文件已经传上去了。下面这段即使界面出错，也绝不能报成"上传失败" ——
    // 曾经面板里的 TypeError 被这条 catch 捞走，让人以为文件没传上去
    const nm = data && data.name ? String(data.name) : "";
    if (!nm) { statusShow(`${t("up_failed")}: ${t("up_noname")}`, true); return; }
    const rel = data.subfolder ? `${data.subfolder}/${nm}` : nm;
    wset(node, "logo_file", rel);
    if (!wget(node, "use_logo")) wset(node, "use_logo", true);
    touch(node);
    refreshUI();
    statusShow(`${t("up_ok")} ${nm}`, false);
  });

  // 样式卡片（单选 mode）
  const cards = $('[data-g="mode"]');
  cards?.addEventListener("click", (ev) => {
    const c = ev.target.closest(".vmk-card[data-v]");
    if (!c) return;
    ev.stopPropagation();
    wset(node, "mode", c.dataset.v);
    touch(node);
    refreshUI();
  });

  bindSeg($('[data-g="position"]'), () => wget(node, "position"), (v) => wset(node, "position", v));
  bindSeg($('[data-g="float_path"]'), () => wget(node, "float_path"), (v) => wset(node, "float_path", v));
  bindSeg($('[data-g="title_mode"]'), () => wget(node, "title_mode"), (v) => wset(node, "title_mode", v));
  bindSeg($('[data-g="where"]'), () => wget(node, "where"), (v) => wset(node, "where", v));
  bindSeg($('[data-g="pad_audio"]'), () => (wget(node, "pad_audio") === false ? "0" : "1"),
    (v) => wset(node, "pad_audio", v === "1"));

  // 文字颜色快捷色
  bindSeg($('[data-g="color"]'), () => String(wget(node, "color") || "").toUpperCase(),
    (v) => wset(node, "color", v));

  // 字体下拉：直接用后端的 choices
  const fontBox = $('[data-g="font_pick"]');
  fillSegFromWidget(fontBox, "font", 24);
  bindSeg(fontBox, () => wget(node, "font"), (v) => wset(node, "font", v));

  // 微调滑块
  bindSlider("scale", (v) => wset(node, "scale", v));
  bindSlider("opacity", (v) => wset(node, "opacity", v));
  bindSlider("margin", (v) => wset(node, "margin", v));
  bindSlider("angle", (v) => wset(node, "angle", v));
  bindSlider("tile_gap", (v) => wset(node, "tile_gap", v));
  bindSlider("float_cycles", (v) => wset(node, "float_cycles", v));
  bindSlider("fade_frames", (v) => wset(node, "fade_frames", v));
  bindSlider("start_pct", (v) => wset(node, "start_pct", v));
  bindSlider("end_pct", (v) => wset(node, "end_pct", v));
  bindSlider("title_seconds", (v) => wset(node, "title_seconds", v));
  bindSlider("seconds", (v) => wset(node, "seconds", v));
  bindSlider("fps", (v) => wset(node, "fps", v));
  bindSlider("text_scale", (v) => wset(node, "text_scale", v));
  bindSlider("logo_scale", (v) => wset(node, "logo_scale", v));
  bindSlider("text_stroke_width", (v) => wset(node, "text_stroke_width", v));

  // 描边 / 阴影：0 就是关掉。用滑块值直接驱动开关，
  // 免得「开关 + 数值」两个控件互相打架（关掉再打开时数值还在不在？）
  bindSlider("stroke_opacity", (v) => {
    wset(node, "stroke_opacity", v);
    wset(node, "use_stroke", v > 0);
    wset(node, "style", "manual");                          // 动过滑块就脱离预设
  });
  bindSlider("shadow_opacity", (v) => {
    wset(node, "shadow_opacity", v);
    wset(node, "use_shadow", v > 0);
    wset(node, "style", "manual");
  });

  /* ---------------- 状态刷新 ---------------- */

  function applyContext() {
    const mode = String(wget(node, "mode") || "corner");
    $$("[data-only]").forEach((el) => {
      el.style.display = (el.dataset.only === mode) ? "" : "none";
    });
  }

  // 分组 -> 当前值。键就是模板里的 data-g。
  // 不要写成一串 $('[data-g="x"]') 再交给 paintSeg：面板是按节点类型拼的，
  // 某个分组在当前节点上可能压根不存在，null 会直接炸在 querySelectorAll 里。
  // 改成"扫面板上真实存在的分组、各自取值"，这类缺失就结构上不可能再出事。
  const GROUP_VALUE = {
    content: () => (isCard ? null : contentMode()),
    layout: () => wget(node, "layout"),
    position: () => wget(node, "position"),
    float_path: () => wget(node, "float_path"),
    title_mode: () => wget(node, "title_mode"),
    where: () => wget(node, "where"),
    pad_audio: () => (wget(node, "pad_audio") === false ? "0" : "1"),
    color: () => String(wget(node, "color") || "").toUpperCase(),
    font_pick: () => wget(node, "font"),
  };
  const warnedGroup = new Set();

  function paintAll() {
    for (const box of $$("[data-g]")) {
      const g = box.dataset.g;
      if (g === "mode") continue;                 // 样式卡片走下面的高亮逻辑
      const get = GROUP_VALUE[g];
      if (!get) {                                 // 模板加了分组但忘了配取值函数
        if (!warnedGroup.has(g)) {
          warnedGroup.add(g);
          console.warn(`[videomark] 分组 data-g="${g}" 没有取值函数，该控件不会高亮`);
        }
        continue;
      }
      paintSeg(box, get());
    }
    // 样式卡片高亮
    cards?.querySelectorAll(".vmk-card").forEach((c) => {
      c.classList.toggle("on", c.dataset.v === String(wget(node, "mode")));
    });
    // 滑块取值
    for (const name of [
      "scale", "opacity", "margin", "angle", "tile_gap", "float_cycles", "fade_frames",
      "start_pct", "end_pct", "stroke_opacity", "shadow_opacity", "title_seconds",
      "seconds", "fps", "text_scale", "logo_scale", "text_stroke_width",
    ]) {
      paintSlider(name, wget(node, name));
    }
    // 文字/logo 开关没打开时，对应滑块的参考价值下降，做淡处理
    const ut = isCard ? wget(node, "use_text") !== false : wget(node, "use_text") !== false;
    const dim = (n, off) => {
      const box = inner.querySelector(`.vmk-sl[data-sl="${n}"]`);
      if (box) box.style.opacity = off ? ".4" : "";
    };
    dim("scale", !ut && !wget(node, "use_logo"));
    dim("text_scale", !ut && !wget(node, "use_logo"));
    dim("text_stroke_width", !ut);
    paintExt();
    paintLogo();
    applyContext();
    syncHeight(true);
  }

  // 「节点值写好了」和「界面刷出来了」是两件事：刷新失败只记控制台，
  // 不能反过来把一次成功的操作报成失败
  function refreshUI() {
    try {
      paintLogo();
      paintAll();
    } catch (e) {
      console.error("[videomark] 界面刷新出错（节点参数不受影响）：", e);
    }
  }

  // 连线状态变了要重画提示条。text_in 不是控件，widget 那边不会有任何回调，
  // 所以只能挂 onConnectionsChange —— 接上、拔掉都得刷一次。
  const prevConn = node.onConnectionsChange;
  node.onConnectionsChange = function () {
    const r = prevConn?.apply(this, arguments);
    try {
      paintExt();
      syncHeight(true);
    } catch (e) {
      console.error("[videomark] 连线状态刷新出错（不影响出图）：", e);
    }
    return r;
  };

  /* ---------------- 预设 → 滑块 ---------------- */

  // 工作流里若还留着 soft/plain 这类预设档位，先把它对应的四个数值落到控件上，
  // 再切成 manual。渲染结果一模一样（数值就是从预设取的），但从此刻起滑块真的能调。
  (async () => {
    const raw = String(wget(node, "style") || "manual").toLowerCase();
    if (raw !== "manual") {
      const meta = await metaReady();
      const p = meta && meta.styles && meta.styles[raw];
      if (p) {
        wset(node, "use_stroke", p.use_stroke);
        wset(node, "use_shadow", p.use_shadow);
        wset(node, "stroke_opacity", p.stroke_opacity);
        wset(node, "shadow_opacity", p.shadow_opacity);
        wset(node, "style", "manual");
        touch(node);
      }
    }
    refreshUI();
  })();

  // 首次尺寸：DOM 还没进文档时量不到高度，等一帧再对一次
  requestAnimationFrame(() => {
    syncHeight(true);
    if (node.size[0] < PANEL_W) node.size[0] = PANEL_W;
  });

}

/* ---------------------------------------------------------------------
 * 注册
 * ------------------------------------------------------------------- */

function widgetsReady(node, spec) {
  // logo_file 是最后加进来的参数：拿不到它就说明 widgets 还没建好
  return !!findWidget(node, "logo_file") && spec.widgets.every((n) => !!findWidget(node, n) || n === "images");
}

app.registerExtension({
  name: "comfyui-videomark.ui",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    const spec = SPECS[nodeData?.name];
    if (!spec) return;

    const prev = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      const r = prev?.apply(this, arguments);
      const node = this;
      let tries = 0;
      const attempt = () => {
        // 值可能比 widget 晚一步就位，所以这里也兜一次（幂等，已迁移过会直接返回）
        migrateLegacyWidgets(node);
        if (widgetsReady(node, spec)) {
          try {
            buildPanel(node, spec);
          } catch (e) {
            console.error("[videomark] 面板构建失败，已回退到原生参数：", e);
          }
          return;
        }
        if (++tries < 25) setTimeout(attempt, 60);          // 最多等约 1.5 秒
      };
      attempt();
      return r;
    };

    // 工作流加载：configure() 先把 widgets_values 按位置铺到控件上，
    // 再回调 onConfigure —— 正是「错位已发生」的那个时刻，就地纠正。
    const prevCfg = nodeType.prototype.onConfigure;
    nodeType.prototype.onConfigure = function () {
      const r0 = prevCfg?.apply(this, arguments);
      try {
        if (migrateLegacyWidgets(this)) {
          // 迁移只在刷新前发生一次；面板还没建好时由 attempt() 读到修正后的值
          requestAnimationFrame(() => this.setDirtyCanvas?.(true, true));
        }
      } catch (e) {
        console.error("[videomark] 老工作流坑位迁移出错（不影响其它节点）：", e);
      }
      return r0;
    };
  },
});

console.log(`[VideoMark] 可视化面板已加载（${LANG}）`);
