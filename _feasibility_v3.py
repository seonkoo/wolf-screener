# -*- coding: utf-8 -*-
"""可行性验证 v3 —— 5年完整牛熊周期

v2 教训: 320根日K(15个月)且以下跌为主, 所有"低位买入"都跑输, 无法分辨
         "策略真无效" 还是 "样本窗口刚好是熊市"。
v3 改进: 拉 1200 根日K (2021-08 ~ 2026-08, 含 21牛尾/22熊/23震荡/24-26),
         regime 用「指数近20日涨跌幅」(当期可知, 无未来函数)。

核心命题(用户): 贪婪<35 且开始有资金流入 → 强烈提醒。
反命题:         贪婪<35 但无资金流入 → 无人问津。
"""
import json, os, math, random, ssl, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
COST = 0.0025
NBARS = 1200
KC = os.path.join(HERE, '_bt_klines_long.json')


def get(url, timeout=20):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                  timeout=timeout, context=CTX).read().decode('utf-8', 'ignore')


def fnum(x, d=0.0):
    try:
        v = float(x)
        return d if v != v else v
    except (TypeError, ValueError):
        return d


def fetch_kline(code, n=NBARS, is_index=False):
    tcode = code if is_index else (('sh' if code[0] in '69' else 'sz') + code)
    varn = 'k' + str(random.randint(0, 999999))
    url = 'https://ifzq.gtimg.cn/appstock/app/kline/kline?_var=%s&param=%s,day,,,%d' % (varn, tcode, n)
    for _ in range(2):
        try:
            raw = get(url); raw = raw[raw.index('=') + 1:]
            data = json.loads(raw)
            if not isinstance(data, dict):
                return []
            kd = (data.get('data') or {}).get(tcode, {})
            kl = kd.get('day') or kd.get('qfqday')
            if not kl:
                return []
            return [[k[0], float(k[1]), float(k[2]), float(k[3]), float(k[4]),
                     float(k[5]) if len(k) > 5 else 0.0] for k in kl]
        except Exception:
            time.sleep(0.15)
    return []


def fetch_universe():
    out, seen = [], set()
    for pn in range(1, 61):
        url = ('https://push2delay.eastmoney.com/api/qt/clist/get?pn=%d&pz=100&po=1&np=1&fltt=2&invt=2'
               '&fid=f3&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&fields=f12,f14,f20' % pn)
        try:
            d = json.loads(get(url)).get('data') or {}
        except Exception:
            break
        diff = d.get('diff') or []
        if not diff:
            break
        for it in diff:
            c, n = str(it.get('f12') or ''), str(it.get('f14') or '')
            if len(c) != 6 or not n or c in seen or 'ST' in n.upper() or '退' in n:
                continue
            seen.add(c); out.append((c, n, fnum(it.get('f20'))))
        if len(diff) < 100:
            break
    return out


def greed_at(closes, i):
    if i < 30:
        return None
    look = min(i, 750)
    hist = closes[i - look:i]
    return sum(1 for c in hist if c < closes[i]) / len(hist) * 100.0 if hist else None


def mfi_at(kl, i, period=14):
    if i < period + 1:
        return None
    pos = neg = 0.0
    for j in range(i - period + 1, i + 1):
        tp = (kl[j][3] + kl[j][4] + kl[j][2]) / 3.0
        tp0 = (kl[j - 1][3] + kl[j - 1][4] + kl[j - 1][2]) / 3.0
        mf = tp * kl[j][5]
        if tp > tp0:
            pos += mf
        elif tp < tp0:
            neg += mf
    if neg == 0:
        return 100.0 if pos > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + pos / neg)


def vr_at(kl, i, n=20):
    if i < n:
        return None
    ma = sum(kl[j][5] for j in range(i - n, i)) / n
    return kl[i][5] / ma if ma > 0 else None


def obv_at(kl, i, n=5):
    if i < n + 1:
        return None
    obv = 0.0; seq = []
    for j in range(i - n, i + 1):
        if kl[j][2] > kl[j - 1][2]:
            obv += kl[j][5]
        elif kl[j][2] < kl[j - 1][2]:
            obv -= kl[j][5]
        seq.append(obv)
    return seq[-1] - seq[0]


def stat(rs):
    if not rs:
        return None
    n = len(rs); avg = sum(rs) / n
    win = sum(1 for r in rs if r > 0) / n
    sd = math.sqrt(sum((r - avg) ** 2 for r in rs) / n) if n > 1 else 0.0
    return {'n': n, 'win': win, 'avg': avg, 'se': sd / math.sqrt(n) if n else 0}


def show(title, groups, base_key):
    print('\n### %s' % title)
    print('%-18s %7s %8s %9s %10s %8s' % ('组别', '样本', '胜率', '均收', '超额', '标准误'))
    print('-' * 66)
    base = stat(groups.get(base_key, []))
    res = {}
    for k, v in groups.items():
        st = stat(v)
        if not st:
            print('%-18s   无样本' % k); continue
        ex = (st['avg'] - base['avg']) * 100 if base else 0.0
        res[k] = dict(st, excess=ex)
        print('%-18s %7d %7.1f%% %8.2f%% %9.2f%% %7.2f%%'
              % (k, st['n'], st['win'] * 100, st['avg'] * 100, ex, st['se'] * 100))
    return res


def main():
    random.seed(7)
    cache = {}
    if os.path.exists(KC):
        try:
            cache = json.load(open(KC, encoding='utf-8'))
        except Exception:
            cache = {}
    if len(cache) < 250:
        uni = [u for u in fetch_universe() if u[2] > 0]
        print('全A %d 只' % len(uni))
        uni.sort(key=lambda x: -x[2])
        big, mid, small = uni[:600], uni[600:1800], uni[1800:]
        pick = (random.sample(big, min(90, len(big))) +
                random.sample(mid, min(120, len(mid))) +
                random.sample(small, min(90, len(small))))
        todo = [p[0] for p in pick if p[0] not in cache]
        print('拉取 %d 只 × %d根日K...' % (len(todo), NBARS))
        with ThreadPoolExecutor(max_workers=10) as ex:
            for i, (c, kl) in enumerate(zip(todo, ex.map(lambda c: fetch_kline(c), todo))):
                if kl and len(kl) > 400:
                    cache[c] = kl
                if (i + 1) % 50 == 0:
                    print('  ...%d/%d' % (i + 1, len(todo)))
        json.dump(cache, open(KC, 'w', encoding='utf-8'))
    print('K线就绪 %d 只, 长度中位 %d' %
          (len(cache), sorted(len(v) for v in cache.values())[len(cache) // 2]))

    idx = fetch_kline('sh000300', NBARS, is_index=True)
    print('沪深300 %d 根: %s ~ %s' % (len(idx), idx[0][0], idx[-1][0]))
    ic = [k[2] for k in idx]
    regime_of = {}
    for i, k in enumerate(idx):
        if i < 20:
            regime_of[k[0]] = 'na'; continue
        chg = (ic[i] - ic[i - 20]) / ic[i - 20] * 100
        regime_of[k[0]] = 'down' if chg < -3 else ('up' if chg > 3 else 'side')
    from collections import Counter
    print('regime分布:', dict(Counter(regime_of.values())))

    recs = []
    for code, kl in cache.items():
        if len(kl) < 300:
            continue
        closes = [k[2] for k in kl]
        for i in range(60, len(kl) - 41, 5):
            entry = closes[i]
            if entry <= 0:
                continue
            g = greed_at(closes, i)
            if g is None:
                continue
            mfi = mfi_at(kl, i); mfi_p = mfi_at(kl, i - 1)
            vr = vr_at(kl, i); ob = obv_at(kl, i)
            recs.append({'greed': g,
                         'mfi': bool(mfi is not None and mfi_p is not None and mfi > mfi_p and mfi > 30),
                         'vr': bool(vr is not None and vr > 1.3),
                         'obv': bool(ob is not None and ob > 0),
                         'r10': (closes[i + 10] - entry) / entry - COST,
                         'r20': (closes[i + 20] - entry) / entry - COST,
                         'r40': (closes[i + 40] - entry) / entry - COST,
                         'regime': regime_of.get(kl[i][0], 'na')})
    for r in recs:
        r['flow'] = (int(r['mfi']) + int(r['vr']) + int(r['obv'])) >= 2
    print('总检查点 %d' % len(recs))

    out = {}
    # 1) 全样本
    out['all'] = show('全样本 5年 (持有20日)', {
        'S0全样本': [r['r20'] for r in recs],
        'G0贪婪<35': [r['r20'] for r in recs if r['greed'] < 35],
        'G1低+资金(≥2)': [r['r20'] for r in recs if r['greed'] < 35 and r['flow']],
        'G2低-无资金': [r['r20'] for r in recs if r['greed'] < 35 and not r['flow']],
        'G1低+MFI单': [r['r20'] for r in recs if r['greed'] < 35 and r['mfi']],
        'G2低-无MFI': [r['r20'] for r in recs if r['greed'] < 35 and not r['mfi']],
    }, 'S0全样本')

    # 2) 分 regime
    for rg in ['down', 'side', 'up']:
        sub = [r for r in recs if r['regime'] == rg]
        if len(sub) < 300:
            continue
        out['regime_' + rg] = show('regime=%s (持有20日)' % rg, {
            'S0': [r['r20'] for r in sub],
            'G0贪婪<35': [r['r20'] for r in sub if r['greed'] < 35],
            'G1低+资金': [r['r20'] for r in sub if r['greed'] < 35 and r['flow']],
            'G2低-无资金': [r['r20'] for r in sub if r['greed'] < 35 and not r['flow']],
            'G1低+MFI': [r['r20'] for r in sub if r['greed'] < 35 and r['mfi']],
        }, 'S0')

    # 3) 阈值
    g = {'S0': [r['r20'] for r in recs]}
    for th in [20, 25, 30, 35, 45]:
        g['低%d+资金' % th] = [r['r20'] for r in recs if r['greed'] < th and r['flow']]
    out['threshold'] = show('贪婪阈值敏感性', g, 'S0')

    # 4) 持有期
    for hz in ['r10', 'r20', 'r40']:
        out['hold_' + hz] = show('持有期 %s' % hz, {
            'S0': [r[hz] for r in recs],
            'G1低+资金': [r[hz] for r in recs if r['greed'] < 35 and r['flow']],
            'G2低-无资金': [r[hz] for r in recs if r['greed'] < 35 and not r['flow']],
        }, 'S0')

    json.dump({'generated': time.strftime('%Y-%m-%d %H:%M'), 'n': len(recs),
               'stocks': len(cache), 'result': out},
              open(os.path.join(HERE, '_feasibility_v3.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('\n已写入 _feasibility_v3.json')


if __name__ == '__main__':
    main()
