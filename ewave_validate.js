// ewave_validate.js — 双引擎校验: 抽取 HTML 内 JS 引擎 + 跑 Python 引擎, 同源数据比对一致
// 用法: node ewave_validate.js sh601318 sz000858 sh600000
const fs = require('fs');
const path = require('path');
const https = require('https');
const { spawnSync } = require('child_process');
const os = require('os');

const PY = 'C:\\Users\\seon\\.workbuddy\\binaries\\python\\versions\\3.13.12\\python.exe';
const HTML = path.join(__dirname, 'ewave-detector.html');

// 1) 抽取 HTML 内纯逻辑引擎
const html = fs.readFileSync(HTML, 'utf8');
const a = html.indexOf('var FIB_RETRACE');
const b = html.indexOf('/* ===== 数据获取');
if (a < 0 || b < 0) { console.error('FAIL: 无法在 HTML 中定位 JS 引擎'); process.exit(1); }
const engineSrc = html.slice(a, b);
const fn = new Function('window', engineSrc + '\n;return {zigzag,checkImpulse,waveMetrics,fibLevels,identify,guidance};');
const JS = fn({});

// 2) 单次抓取数据, 同时喂给两端, 杜绝两次抓取不一致
function fetchDaily(code) {
  return new Promise((resolve, reject) => {
    const url = `https://ifzq.gtimg.cn/appstock/app/kline/kline?_var=k&param=${code},day,,,320`;
    https.get(url, res => {
      let d = ''; res.on('data', c => d += c); res.on('end', () => {
        try {
          const rb = d.slice(d.indexOf('=') + 1);
          const j = JSON.parse(rb);
          const node = (j.data && j.data[code]) || {};
          const day = node.day || node.qfqday || [];
          const closes = day.filter(r => r && r.length >= 6).map(r => +r[2]);
          resolve(closes);
        } catch (e) { reject(e); }
      });
    }).on('error', reject);
  });
}
function round(obj, n = 2) {
  if (Array.isArray(obj)) return obj.map(x => round(x, n));
  if (typeof obj === 'number') return Math.round(obj * 10 ** n) / 10 ** n;
  if (obj && typeof obj === 'object') { const o = {}; for (const k in obj) o[k] = round(obj[k], n); return o; }
  return obj;
}

(async () => {
  const codes = process.argv.slice(2).length ? process.argv.slice(2) : ['sh601318', 'sz000858', 'sh600000'];
  const tmp = path.join(os.tmpdir(), '_ew_closes.json');
  let allOk = true;
  for (const code of codes) {
    const closes = await fetchDaily(code);
    if (!closes || closes.length < 30) { console.error(code, 'NO DATA'); allOk = false; continue; }
    fs.writeFileSync(tmp, JSON.stringify(closes));
    const jsRes = JS.identify(closes);
    const pyRaw = spawnSync(PY, ['ewave_detect.py', '--json', '--closes-file', tmp, code], { encoding: 'utf8' });
    if (pyRaw.status !== 0) { console.error(code, 'PYTHON ERR', pyRaw.stderr); allOk = false; continue; }
    const pyRes = JSON.parse(pyRaw.stdout.trim());

    const jsStruct = jsRes.structure, pyStruct = pyRes.structure;
    const jsPhase = jsRes.phase, pyPhase = pyRes.phase;
    const jsFib = jsRes.fib ? Object.fromEntries(Object.entries(jsRes.fib).map(([k, v]) => [k, round(v)])) : null;
    const pyFib = pyRes.fib ? Object.fromEntries(Object.entries(pyRes.fib).map(([k, v]) => [k, round(v)])) : null;
    const jsPrim = jsRes.primary ? round(jsRes.primary) : null;
    const pyPrim = pyRes.primary ? round(pyRes.primary) : null;
    const jsG = round(JS.guidance(closes, jsRes));
    const pyG = round(pyRes.guidance);

    const structOk = jsStruct === pyStruct;
    const phaseOk = jsPhase === pyPhase;
    const fibOk = JSON.stringify(jsFib) === JSON.stringify(pyFib);
    const primOk = JSON.stringify(jsPrim) === JSON.stringify(pyPrim);
    const gdOk = JSON.stringify(jsG) === JSON.stringify(pyG);
    const ok = structOk && phaseOk && fibOk && primOk && gdOk;
    if (!ok) allOk = false;
    console.log(`${ok ? 'OK ' : 'XX '} ${code}  结构=${jsStruct}/${pyStruct} 相位="${jsPhase}"=="${pyPhase}"?${phaseOk} fib同?${fibOk} prim同?${primOk} guidance同?${gdOk}`);
    if (!fibOk) { console.log('   JS :', JSON.stringify(jsFib)); console.log('   PY :', JSON.stringify(pyFib)); }
    if (!gdOk) { console.log('   JS.gd :', JSON.stringify(jsG)); console.log('   PY.gd :', JSON.stringify(pyG)); }
  }
  console.log(allOk ? '\nALL OK — 双引擎一致' : '\nMISMATCH — 见上');
  process.exit(allOk ? 0 : 1);
})();
