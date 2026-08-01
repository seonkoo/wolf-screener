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
}
global.document = {
  readyState: 'complete',
  getElementById: el,
  addEventListener: (ev, fn) => fn(),
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
  ['autoMount', 'blueMount'].forEach((id) => {
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
  // 抽样输出蓝筹第一张卡的纯文本
  const t = el('blueMount').innerHTML.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').slice(0, 320);
  console.log('   蓝筹片段:', t);
  process.exit(bad ? 1 : 0);
}, 400);
