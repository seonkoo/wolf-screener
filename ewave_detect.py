# -*- coding: utf-8 -*-
"""艾略特波浪 + 斐波那契 分析引擎 (日K)
==============================================
数据源: ifzq.gtimg.cn/appstock/app/kline/kline?param=code,day,,,N  (日K, 沙箱可达)
       day 行: [date, open, close, high, low, volume(手), ...]

流程:
  1) Zigzag 摆动检测(收盘价, 反向变动阈值) → 交替的 顶(H)/底(L) 转折点(含末段当前极值)
  2) 艾略特结构识别:
     - 推动浪: L0-H1-L2-H3-L4-H5 (五浪), 三铁律校验
        铁律1: 浪2 不回撤破浪1起点 (l2 > l0)
        铁律2: 浪3 不是最短推动段
        铁律3: 浪4 不与浪1重叠 (l4 > h1)
     - 调整浪: H0-La-Hb-Lc (A-B-C), B 不破 H0, C≈A 的 0.618~1.618 倍
     - 判定"当前处于什么浪" + 首选 + 备选
  3) 斐波那契测算:
     - 推动完成后的回调支撑: 整段(浪1起点-浪5高点)的 0.382/0.5/0.618/0.786
     - 调整结束后的反弹黄金分割(阻力): 自 C 低点反弹整段跌幅的 0.382/0.5/0.618
     - 延伸目标: 浪5 之后的 1.272/1.618/2.618
  4) 操作指引: 结合当前浪 → 支撑/阻力 → 低吸/减仓参考区 → 失效位

诚实边界: 自动数浪是启发式(千人千浪)。只给"首选 + 备选 + 特征证据 + 置信度"，不铁口直断。
"""
import json, ssl, urllib.request, math, sys

CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://gu.qq.com/'}

FIB_RETRACE = [0.382, 0.5, 0.618, 0.786]   # 回撤/反弹 位
FIB_EXTEND = [1.272, 1.618, 2.618]         # 延伸 位


def get(u, t=20):
    return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=t, context=CTX).read().decode('utf-8', 'ignore')


def fetch_daily(code, n=320):
    """返回 [{date, open, close, high, low, vol}] 最新在前"""
    url = "https://ifzq.gtimg.cn/appstock/app/kline/kline?_var=k&param=%s,day,,,%d" % (code, n)
    raw = get(url); raw = raw[raw.index('=') + 1:]
    node = json.loads(raw).get('data', {}).get(code, {})
    day = node.get('day') or node.get('qfqday') or []
    rows = []
    for r in day:
        if not r or len(r) < 6:
            continue
        try:
            rows.append({'date': r[0], 'open': float(r[1]), 'close': float(r[2]),
                         'high': float(r[3]), 'low': float(r[4]), 'vol': float(r[5])})
        except (ValueError, TypeError):
            continue
    return rows


def zigzag(closes, pct=0.05):
    """摆动点检测: 返回 [(idx, price, dir)] dir=+1 顶 / -1 底 (从旧到新, H/L 交替, 含末段极值)"""
    n = len(closes)
    if n < 12:
        return []
    pts = []
    trend = 0            # 0 未知 / 1 上行 / -1 下行
    hi = lo = closes[0]; hi_i = lo_i = 0
    for i in range(1, n):
        v = closes[i]
        if v > hi:
            hi, hi_i = v, i
        if v < lo:
            lo, lo_i = v, i
        if trend >= 0 and v < hi * (1 - pct):
            pts.append((hi_i, hi, 1)); trend = -1; lo, lo_i = v, i
        elif trend <= 0 and v > lo * (1 + pct):
            pts.append((lo_i, lo, -1)); trend = 1; hi, hi_i = v, i
    if not pts:
        return []
    # 末段极值补成最后一个摆动点(保证结构完整、可判当前浪)
    if trend == 1 and pts[-1][2] == -1:
        pts.append((hi_i, hi, 1))
    elif trend == -1 and pts[-1][2] == 1:
        pts.append((lo_i, lo, -1))
    return pts


def check_impulse(l0, h1, l2, h3, l4, h5):
    """五浪铁律校验: 返回 (ok, violations[])"""
    viol = []
    if l2 <= l0:
        viol.append('铁律1违规: 浪2低点 %.2f ≤ 浪1起点 %.2f (浪2 破了浪1起点)' % (l2, l0))
    legs = [abs(h1 - l0), abs(h3 - l2), abs(h5 - l4)]
    if legs[1] <= min(legs[0], legs[2]):
        viol.append('铁律2违规: 浪3(%.2f) 是最短推动段 (浪1=%.2f, 浪5=%.2f)' % (legs[1], legs[0], legs[2]))
    if l4 <= h1:
        viol.append('铁律3违规: 浪4低点 %.2f ≤ 浪1高点 %.2f (重叠)' % (l4, h1))
    ok = len(viol) == 0
    return ok, viol


def wave_metrics(l0, h1, l2, h3, l4, h5):
    """返回各浪百分比(相对起点) + 回撤比"""
    def p(a, b):
        return (a - b) / b * 100 if b else 0
    w1 = p(h1, l0)
    w2_retr = (h1 - l2) / (h1 - l0) * 100 if h1 != l0 else 0   # 浪2 回撤浪1 的比例
    w3 = p(h3, l2)
    w4_retr = (h3 - l4) / (h3 - l2) * 100 if h3 != l2 else 0   # 浪4 回撤浪3 的比例
    w5 = p(h5, l4)
    return w1, w2_retr, w3, w4_retr, w5


def fib_levels(lo, hi, ratios, tag):
    """在 lo..hi 区间生成回撤/反弹位 (lo<hi 为上行, 反之下行)"""
    span = hi - lo
    out = []
    for r in ratios:
        out.append({'r': r, 'price': hi - span * r, 'tag': tag})
    return out


def identify(closes):
    """识别当前波浪结构: 返回 dict"""
    pts = zigzag(closes)
    out = {'pts': pts, 'structure': None, 'phase': None, 'conf': 0.0,
           'evidence': [], 'rules': [], 'fib': None, 'primary': None, 'alt': None}
    if len(pts) < 5:
        out['phase'] = '数据不足'
        out['evidence'].append('摆动点不足（需≥5个转折点），无法可靠数浪；请拉长周期或换标的。')
        return out

    last_dir = pts[-1][2]
    cur = closes[-1]

    # ===== 尝试推动浪 L0-H1-L2-H3-L4-H5 (末段=最近6个摆动点的子集) =====
    imp_cands = []
    for i in range(max(0, len(pts) - 14), len(pts) - 5):
        if pts[i][2] != -1:
            continue
        seg = pts[i:i + 6]
        if len(seg) < 6:
            break
        l0, h1, l2, h3, l4, h5 = [p[1] for p in seg]
        ok, viol = check_impulse(l0, h1, l2, h3, l4, h5)
        w1, w2r, w3, w4r, w5 = wave_metrics(l0, h1, l2, h3, l4, h5)
        # 分数: 铁律全过 +3; 浪3 最长 +1.5; 浪2/浪4 回撤在合理(20%~80%)区间 +1
        score = (3 if ok else -4)
        if abs(h3 - l2) >= max(abs(h1 - l0), abs(h5 - l4)):
            score += 1.5
        if 15 <= w2r <= 85 and 15 <= w4r <= 85:
            score += 1
        imp_cands.append({'seg': seg, 'ok': ok, 'viol': viol, 'score': score,
                          'm': (w1, w2r, w3, w4r, w5), 'l0': l0, 'h1': h1, 'l2': l2, 'h3': h3, 'l4': l4, 'h5': h5})
    imp_cands.sort(key=lambda x: x['score'], reverse=True)

    # ===== 尝试调整浪 H0-La-Hb-Lc =====
    abc_cands = []
    for i in range(max(0, len(pts) - 10), len(pts) - 3):
        if pts[i][2] != 1:
            continue
        seg = pts[i:i + 4]
        if len(seg) < 4:
            break
        h0, la, hb, lc = [p[1] for p in seg]
        if hb > h0:                       # B 浪不能创新高
            continue
        A = h0 - la
        if A <= 0:
            continue
        C = hb - lc
        ratio = C / A
        ok = 0.5 <= ratio <= 1.8          # C ≈ A 的 0.5~1.8 倍为典型
        score = (2 if ok else -1)
        if 0.9 <= ratio <= 1.1:
            score += 1.5                  # C=A 最标准
        elif 0.6 <= ratio <= 0.85:
            score += 0.8                  # C=0.618A 常见
        abc_cands.append({'seg': seg, 'ok': ok, 'score': score, 'ratio': ratio,
                          'h0': h0, 'la': la, 'hb': hb, 'lc': lc, 'A': A, 'C': C})
    abc_cands.sort(key=lambda x: x['score'], reverse=True)

    # ===== 综合选首选 =====
    primary = None
    if imp_cands and (not abc_cands or imp_cands[0]['score'] >= abc_cands[0]['score']):
        c = imp_cands[0]
        l0, h1, l2, h3, l4, h5 = c['l0'], c['h1'], c['l2'], c['h3'], c['l4'], c['h5']
        w1, w2r, w3, w4r, w5 = c['m']
        structure = 'impulse'
        # 当前浪位判定
        if cur >= h5 * 0.995:
            phase = '推动浪·浪5 进行中/延伸'
        elif cur > l4:
            phase = '推动浪·浪5 进行中'
        elif cur > l2:
            phase = '推动浪完成, 进入调整 (A-B-C)'
        else:
            phase = '推动浪后深度调整'
        out['structure'] = structure
        out['phase'] = phase
        out['ok'] = c['ok']
        out['rules'] = c['viol']
        out['conf'] = min(0.9, 0.5 + (0.25 if c['ok'] else 0) + (0.1 if abs(h3 - l2) >= max(abs(h1 - l0), abs(h5 - l4)) else 0))
        out['evidence'].append('识别到五浪推动(首选): 浪1 %+.1f%% → 浪2回撤 %.0f%% → 浪3 %+.1f%% → 浪4回撤 %.0f%% → 浪5 %+.1f%%' % (w1, w2r, w3, w4r, w5))
        if c['viol']:
            out['evidence'].append('⚠️ 结构瑕疵: ' + '；'.join(c['viol']))
        # 斐波那契: 整段回调支撑 + 浪5延伸目标
        up = l0 < h5
        lo, hi = (l0, h5) if up else (h5, l0)
        fib = {}
        fib['retrace'] = fib_levels(lo, hi, FIB_RETRACE, '回调支撑')
        ext = abs(h5 - l4)
        fib['extend'] = [{'r': r, 'price': l4 + (h5 - l4) * r, 'tag': '浪5延伸'} for r in FIB_EXTEND]
        fib['base'] = {'lo': lo, 'hi': hi}
        out['fib'] = fib
        out['fib_verdict'] = ('整段(浪1起点 %.2f → 浪5高点 %.2f)回调支撑: 0.5≈%.2f / 0.618≈%.2f —— 回调到此区间是「低吸参考区」；'
                              '跌破浪2低点 %.2f 则推动结构失效。' % (l0, h5, fib['retrace'][1]['price'], fib['retrace'][2]['price'], l2))
        out['primary'] = {'type': 'impulse', 'l0': l0, 'h1': h1, 'l2': l2, 'h3': h3, 'l4': l4, 'h5': h5}
        if len(imp_cands) > 1:
            out['alt'] = {'type': 'impulse', 'note': '备选数法: 第2优选分浪(分数 %.1f)' % imp_cands[1]['score']}
    elif abc_cands:
        c = abc_cands[0]
        h0, la, hb, lc, A, C, ratio = c['h0'], c['la'], c['hb'], c['lc'], c['A'], c['C'], c['ratio']
        structure = 'abc'
        if cur <= lc * 1.005:
            phase = '调整浪·C浪 进行中/尾声'
        elif cur < hb:
            phase = '调整浪·C浪结束, 反弹中'      # 跌破C低点后展开反弹, 操作关注区
        else:
            phase = '调整浪·B浪 反弹'
        out['structure'] = structure
        out['phase'] = phase
        out['ok'] = c['ok']
        out['rules'] = [] if c['ok'] else ['C浪(%.2f) 与 A浪(%.2f) 比例 %.2f 偏离典型区间 0.5~1.8' % (C, A, ratio)]
        out['conf'] = min(0.85, 0.45 + (0.25 if c['ok'] else 0))
        out['evidence'].append('识别到 A-B-C 调整(首选): A浪 %+.1f%% → B浪反弹至 %.2f (回撤A %.0f%%) → C浪 %+.1f%% (A的%.2f倍)' %
                               ((la - h0) / h0 * 100, hb, (h0 - hb) / A * 100 if A else 0, (lc - hb) / hb * 100, ratio))
        # 斐波那契: C 目标(已隐含) + C 结束后反弹黄金分割(阻力)
        fib = {}
        fib['c_targets'] = [{'r': r, 'price': h0 - A * r, 'tag': 'C浪目标'} for r in [0.618, 1.0, 1.272, 1.618]]
        fib['rebound'] = fib_levels(lc, h0, FIB_RETRACE, '反弹阻力')   # 自 C 低点反弹整段跌幅
        out['fib'] = fib
        out['fib_verdict'] = ('C浪目标(按A浪幅度): 1.0倍≈%.2f / 1.272倍≈%.2f。若 C 已到 1.272~1.618 倍且出现止跌信号, '
                              '反弹第一目标看整段跌幅(A起点 %.2f → C低点 %.2f)的 0.382~0.5 黄金分割位 ≈ %.2f~%.2f。' %
                              (fib['c_targets'][1]['price'], fib['c_targets'][2]['price'], h0, lc,
                               fib['rebound'][0]['price'], fib['rebound'][1]['price']))
        out['primary'] = {'type': 'abc', 'h0': h0, 'la': la, 'hb': hb, 'lc': lc}
        if len(abc_cands) > 1:
            out['alt'] = {'type': 'abc', 'note': '备选数法: 第2优选分浪(分数 %.1f)' % abc_cands[1]['score']}
    else:
        out['phase'] = '结构不明'
        out['evidence'].append('近期摆动点不满足五浪或 ABC 标准结构，可能是复杂调整(平台/三角形)或数据区间不足。建议结合更大周期判断。')
        out['conf'] = 0.3
    return out


def analyze(code, n=320):
    rows = fetch_daily(code, n)
    if len(rows) < 30:
        return {'error': '日K数据不足', 'code': code}
    closes = [r['close'] for r in rows]
    res = identify(closes)
    res['code'] = code
    res['name'] = ''
    res['bars'] = rows[-90:]      # 仅返回最近90根供画图
    return res


def compact(r):
    """校验用精简结构(去掉 bars/pts 大数组)"""
    c = dict(r)
    c.pop('bars', None); c.pop('pts', None)
    if 'primary' in c and c['primary']:
        c['primary'] = {k: round(v, 3) if isinstance(v, (int, float)) else v for k, v in c['primary'].items()}
    if 'fib' in c and c['fib']:
        fib = c['fib']
        for k in ('retrace', 'extend', 'rebound', 'c_targets'):
            if k in fib:
                # 保留 price 原始精度, 由校验端统一 Math.round 到2位, 避免 Python 双舍入与 JS 不一致
                fib[k] = [{'r': round(x['r'], 3), 'price': x['price'],
                           'tag': x.get('tag', '')} for x in fib[k]]
    return c


def analyze_closes(code, closes):
    """直接用给定收盘价序列分析(校验用, 避免重复抓取导致数据不一致)"""
    res = identify(closes)
    res['code'] = code
    res['name'] = ''
    res['bars'] = []
    return res


if __name__ == '__main__':
    closes_file = None
    if '--closes-file' in sys.argv:
        i = sys.argv.index('--closes-file')
        closes_file = sys.argv[i + 1]
    if '--json' in sys.argv:
        code = [a for a in sys.argv[1:] if not a.startswith('-')][0]
        if closes_file:
            with open(closes_file, 'r', encoding='utf-8') as f:
                closes = json.load(f)
            print(json.dumps(compact(analyze_closes(code, closes)), ensure_ascii=False))
        else:
            print(json.dumps(compact(analyze(code, 300)), ensure_ascii=False))
    else:
        codes = sys.argv[1:] or ['sh600000', 'sz000001', 'sh601318', 'sz000858', 'sh600519', 'sz300750', 'sh601012', 'sz002594']
        for c in codes:
            try:
                r = analyze(c, 300)
                if 'error' in r:
                    print('%-10s ERR %s' % (c, r['error'])); continue
                print('%-10s 结构=%s | 相位=%s | 置信%.0f%% | %s' % (c, r['structure'], r['phase'], r['conf'] * 100, r['evidence'][0] if r['evidence'] else '-'))
                if r['fib']:
                    print('     → %s' % r['fib_verdict'])
            except Exception as e:
                print('%-10s EXC %s %s' % (c, type(e).__name__, e))
