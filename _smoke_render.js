// 渲染冒烟测试：模拟 DOM + fetch，用真实 JSON 跑一遍页面注入脚本
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');

const OFFLINE = process.argv[3] === 'offline';
const htmlFile = process.argv[4];

const els = {};
function el(id) {
  if (!els[id]) els[id] = { id, innerHTML: '', insertAdjacentHTML(pos, h) { this.innerHTML = h + this.innerHTML; } };
  return els[id];
}
// 离线模式：把 HTML 里烘焙的快照预填进挂载点，模拟 file:// 打开
if (OFFLINE && htmlFile) {
  const html = fs.readFileSync(htmlFile, 'utf8');
  const grab = (a, b) => { const m = html.match(new RegExp('<!--' + a + '-->([\\s\\S]*?)<!--' + b + '-->')); return m ? m[1] : ''; };
  el('autoMount').innerHTML = grab('AUTOPICK_START', 'AUTOPICK_END');
  el('blueMount').innerHTML = grab('BLUECHIP_START', 'BLUECHIP_END');
  el('ldMount').innerHTML = grab('LIDAXIAO_START', 'LIDAXIAO_END');
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
  ['autoMount', 'blueMount', 'ldMount', 'ewMount'].forEach((id) => {
    const h = el(id).innerHTML;
    const issues = [];
    if (/undefined/.test(h)) issues.push('undefined');
    if (/NaN/.test(h)) issues.push('NaN');
    if (/\[object Object\]/.test(h)) issues.push('[object Object]');
    if (h.length < 500) issues.push('内容过短(可能渲染失败)');
    const open = (h.match(/<div\b/g) || []).length, close = (h.match(/<\/div>/g) || []).length;
    if (open !== close) issues.push(`div不平衡 ${open}/${close}`);
    if (issues.length) bad++;
    console.log(`${id}: ${h.length} 字符, div ${open}/${close}, ${issues.length ? '❌ ' + issues.join(', ') : '✅ 正常'}`);
    const m = h.match(/<h3>([^<]*)<\/h3>/);
    if (m) console.log('   标题:', m[1]);
  });
  // 艾略特波浪操作建议校验
  const ea = el('ewAdvise').innerHTML;
  const eaOk = /操作参考/.test(ea) && ea.length > 50;
  console.log('ewAdvise:', ea.length, '字符', eaOk ? '✅ 含操作建议' : '❌ 无建议');
  if (!eaOk) bad++;
  // 抽样输出蓝筹第一张卡的纯文本
  const t = el('blueMount').innerHTML.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').slice(0, 320);
  console.log('   蓝筹片段:', t);
  process.exit(bad ? 1 : 0);
}, 600);
