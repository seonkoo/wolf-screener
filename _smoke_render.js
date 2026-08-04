// 渲染冒烟测试：模拟 DOM + fetch，用真实 JSON 跑一遍页面注入脚本
const fs = require('fs');
const arg2 = process.argv[2];
const isHtml = arg2 && arg2.endsWith('.html');
let src;
if (isHtml) {
  // CI 模式：直接从 HTML 抽取渲染脚本，无需先 extract
  const html = fs.readFileSync(arg2, 'utf8');
  const m = html.match(/<!--WOLF_RENDER_JS_START-->\s*<script>([\s\S]*?)<\/script>\s*<!--WOLF_RENDER_JS_END-->/);
  if (!m) { console.error('❌ 找不到 WOLF_RENDER_JS 标记'); process.exit(2); }
  src = m[1];
} else {
  src = fs.readFileSync(arg2, 'utf8');
}

const OFFLINE = process.argv[3] === 'offline';
const htmlFile = isHtml ? arg2 : process.argv[4];

const els = {};
function el(id) {
  if (!els[id]) els[id] = { id, innerHTML: '', insertAdjacentHTML(pos, h) { this.innerHTML = h + this.innerHTML; } };
  return els[id];
}
// 离线模式：把 HTML 里烘焙的快照预填进挂载点，模拟 file:// 打开
if (OFFLINE && htmlFile) {
  const html = fs.readFileSync(htmlFile, 'utf8');
  const grab = (a, b) => { const m = html.match(new RegExp('<!--' + a + '-->([\\s\\S]*?)<!--' + b + '-->')); return m ? m[1] : ''; };
  if (html.includes('id="autoMount"')) el('autoMount').innerHTML = grab('AUTOPICK_START', 'AUTOPICK_END');
  if (html.includes('id="ldMount"')) el('ldMount').innerHTML = grab('LIDAXIAO_START', 'LIDAXIAO_END');
  if (html.includes('id="ttBanner"')) el('ttBanner').innerHTML = grab('TTBANNER_START', 'TTBANNER_END');
  if (html.includes('id="ttMount"')) el('ttMount').innerHTML = grab('TRADETIME_START', 'TRADETIME_END');
  if (html.includes('id="etfMount"')) el('etfMount').innerHTML = grab('ETFTIME_START', 'ETFTIME_END');
}
global.window = global;
const SAMPLE_K = (function () {
  // ~176 根合成日K：5浪上行 + A-B-C 调整，每段反转幅度 5%~15%（贴合真实指数拐点尺度），供波浪识别器跑通
  var bars = [], price = 3000, d = new Date(2024, 0, 1);
  var phases = [0.10, -0.05, 0.16, -0.06, 0.10, -0.12, 0.07, -0.15];
  var nPer = 22;
  for (var p = 0; p < phases.length; p++) {
    var magPct = phases[p];
    var start = price, end = price * (1 + magPct), step = (end - start) / nPer;
    for (var i = 0; i < nPer; i++) {
      var base = start + step * i;
      var close = base + Math.sin(i * 1.7 + p) * price * 0.004;
      var open = base - Math.sin(i * 0.9) * price * 0.003;
      var high = Math.max(open, close) + price * 0.005;
      var low = Math.min(open, close) - price * 0.005;
      var ds = d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2);
      bars.push([ds, open.toFixed(2), close.toFixed(2), high.toFixed(2), low.toFixed(2), (800000 + Math.floor(Math.abs(Math.sin(i + p) * 400000)))]);
      d.setDate(d.getDate() + 1);
    }
    price = end;
  }
  return bars;
})();
global.document = {
  readyState: 'complete',
  getElementById: el,
  addEventListener: (ev, fn) => fn(),
  body: { appendChild() {} },
  createElement(tag) {
    if (tag === 'script') {
      return {
        _src: '', onload: null, onerror: null,
        set src(v) {
          this._src = v;
          var m = v.match(/_var=([^&]+)/), vm = v.match(/param=([^,&]+)/);
          var name = m ? m[1] : 'ewVar', ts = vm ? vm[1] : 'sh000001';
          var payload = { data: {} }; payload.data[ts] = { day: SAMPLE_K };
          global[name] = payload;
          var self = this;
          setTimeout(() => { if (self.onload) self.onload(); }, 0);
        },
        get src() { return this._src; },
        remove() {},
      };
    }
    return { style: {}, appendChild() {}, remove() {}, setAttribute() {} };
  },
};
global.fetch = (u) => OFFLINE
  ? Promise.reject(new TypeError('Failed to fetch'))   // file:// 下浏览器的真实表现
  : Promise.resolve({
      ok: fs.existsSync(u), status: fs.existsSync(u) ? 200 : 404,
      json: () => Promise.resolve(JSON.parse(fs.readFileSync(u, 'utf8'))),
    });

eval(src);

setTimeout(() => {
  let bad = 0;
  const html = (htmlFile && fs.existsSync(htmlFile)) ? fs.readFileSync(htmlFile, 'utf8') : '';
  const mountIds = html ? [...html.matchAll(/id="([\w]+Mount)"/g)].map(m => m[1]) : ['autoMount', 'ldMount', 'ewMount'];
  // 离线模式只校验「已烘焙快照」的挂载点（模拟 file:// 打开的兜底路径）；在线模式校验全部挂载点
  // ttBanner 不是 *Mount 命名，单独纳入校验（在线渲染 + 离线快照兜底）
  const ttBannerId = (html.includes('id="ttBanner"')) ? ['ttBanner'] : [];
  const checkIds = OFFLINE
    ? mountIds.filter(id => ['autoMount', 'ldMount', 'ttMount', 'etfMount'].includes(id)).concat(ttBannerId)
    : mountIds.concat(ttBannerId);
  // 各挂载点最小长度：大内容区(列表)要求 ≥500，避免「渲染失败但无报错」漏过；
  // 小头部(如 ttBanner/etfMount 仅有环境描述或"无信号"提示时常态 <500 字)降低阈值，避免误判。
  const MIN_LEN = { ttBanner: 100, etfMount: 50 };
  checkIds.forEach((id) => {
    const h = el(id).innerHTML;
    const issues = [];
    if (/undefined/.test(h)) issues.push('undefined');
    if (/NaN/.test(h)) issues.push('NaN');
    if (/\[object Object\]/.test(h)) issues.push('[object Object]');
    if (h.length < (MIN_LEN[id] || 500)) issues.push('内容过短(可能渲染失败)');
    const open = (h.match(/<div\b/g) || []).length, close = (h.match(/<\/div>/g) || []).length;
    if (open !== close) issues.push(`div不平衡 ${open}/${close}`);
    if (issues.length) bad++;
    console.log(`${id}: ${h.length} 字符, div ${open}/${close}, ${issues.length ? '❌ ' + issues.join(', ') : '✅ 正常'}`);
    const m = h.match(/<h3>([^<]*)<\/h3>/);
    if (m) console.log('   标题:', m[1]);
  });
  // 艾略特波浪操作建议校验（仅在线模式，依赖 K线 mock 渲染）
  if (!OFFLINE && mountIds.includes('ewMount')) {
    const ea = el('ewAdvise').innerHTML;
    const eaOk = /操作参考/.test(ea) && ea.length > 50;
    console.log('ewAdvise:', ea.length, '字符', eaOk ? '✅ 含操作建议' : '❌ 无建议');
    if (!eaOk) bad++;
  }
  process.exit(bad ? 1 : 0);
}, 600);
