# -*- coding: utf-8 -*-
"""可行性验证 v5 —— 加严是否真的更强 (为"核心提醒"档找依据)

v4 已确认三段式命题成立: 贪婪<35 + 个股资金 + 板块共振 = 56.2%胜率/+1.77%超额。
但线上跑出来符合该档的有 277 只 —— 对"强烈提醒"来说太多, 提醒即失效。

v5 要回答的唯一问题: 在 56.2% 这档之上再加严, 收益是单调上升还是掉头?
  · 个股信号 2个 vs 3个全中
  · 板块共振 >50% vs >66% vs >80%
  · 贪婪深度 <15 vs 15~35
只有加严后确实更强, "核心提醒"才有依据; 否则就老实按综合分取 TopN, 不编新档位。
"""
import json, os, math, ssl, urllib.request, random
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = {'User-Agent': 'Mozilla/5.0'}
COST = 0.0025


def get(u, t=20):
    return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=t,
                                  context=CTX).read().decode('utf-8', 'ignore')


def fetch_index(n=1200):
    varn = 'k' + str(random.randint(0, 999999))
    url = 'https://ifzq.gtimg.cn/appstock/app/kline/kline?_var=%s&param=sh000300,day,,,%d' % (varn, n)
    raw = get(url); raw = raw[raw.index('=') + 1:]
    kd = (json.loads(raw).get('data') or {}).get('sh000300', {})
    return [[k[0], float(k[2])] for k in (kd.get('day') or kd.get('qfqday') or [])]


def greed_at(cl, i):
    if i < 30:
        return None
    look = min(i, 750); h = cl[i - look:i]
    return sum(1 for c in h if c < cl[i]) / len(h) * 100.0 if h else None


def mfi_at(kl, i, p=14):
    if i < p + 1:
        return None
    pos = neg = 0.0
    for j in range(i - p + 1, i + 1):
        tp = (kl[j][3] + kl[j][4] + kl[j][2]) / 3.0
        tp0 = (kl[j - 1][3] + kl[j - 1][4] + kl[j - 1][2]) / 3.0
        mf = tp * kl[j][5]
        if tp > tp0: pos += mf
        elif tp < tp0: neg += mf
    return 100.0 - 100.0 / (1.0 + pos / neg) if neg else (100.0 if pos else 50.0)


def vr_at(kl, i, n=20):
    if i < n: return None
    ma = sum(kl[j][5] for j in range(i - n, i)) / n
    return kl[i][5] / ma if ma > 0 else None


def obv_at(kl, i, n=5):
    if i < n + 1: return None
    o = 0.0; s = []
    for j in range(i - n, i + 1):
        if kl[j][2] > kl[j - 1][2]: o += kl[j][5]
        elif kl[j][2] < kl[j - 1][2]: o -= kl[j][5]
        s.append(o)
    return s[-1] - s[0]


def stat(rs):
    if not rs: return None
    n = len(rs); a = sum(rs) / n
    w = sum(1 for r in rs if r > 0) / n
    sd = math.sqrt(sum((r - a) ** 2 for r in rs) / n) if n > 1 else 0
    return {'n': n, 'win': w, 'avg': a, 'se': sd / math.sqrt(n) if n else 0}


def show(title, g, base):
    print('\n### %s' % title)
    print('%-26s %7s %8s %9s %10s %9s' % ('组别', '样本', '胜率', '均收', '超额', '±1se'))
    print('-' * 74)
    b = stat(base)
    for k, v in g.items():
        st = stat(v)
        if not st or st['n'] < 40:
            print('%-26s %7s  样本不足' % (k, st['n'] if st else 0)); continue
        print('%-26s %7d %7.1f%% %8.2f%% %9.2f%% %8.2f%%'
              % (k, st['n'], st['win'] * 100, st['avg'] * 100,
                 (st['avg'] - b['avg']) * 100, st['se'] * 100))


def main():
    cache = json.load(open(os.path.join(HERE, '_bt_klines_long.json'), encoding='utf-8'))
    imap = (json.load(open(os.path.join(HERE, 'industry_map.json'), encoding='utf-8')) or {}).get('map', {})
    ind_of = {c: (imap.get(c) or {}).get('ind', '') for c in cache}

    idx = fetch_index()
    ic = [k[1] for k in idx]
    regime_of = {}
    for i, k in enumerate(idx):
        if i < 20:
            regime_of[k[0]] = 'na'; continue
        chg = (ic[i] - ic[i - 20]) / ic[i - 20] * 100
        regime_of[k[0]] = 'down' if chg < -3 else ('up' if chg > 3 else 'side')

    per = []
    day_ind_tot = defaultdict(int); day_ind_flow = defaultdict(int)
    for code, kl in cache.items():
        if len(kl) < 300:
            continue
        cl = [k[2] for k in kl]
        ind = ind_of.get(code, '')
        for i in range(60, len(kl) - 21, 5):
            e = cl[i]
            if e <= 0: continue
            g = greed_at(cl, i)
            if g is None: continue
            mfi = mfi_at(kl, i); mfp = mfi_at(kl, i - 1)
            vr = vr_at(kl, i); ob = obv_at(kl, i)
            sm = bool(mfi and mfp and mfi > mfp and mfi > 30)
            sv = bool(vr and vr > 1.3)
            so = bool(ob and ob > 0)
            sc = int(sm) + int(sv) + int(so)
            d = kl[i][0]
            if ind:
                day_ind_tot[(d, ind)] += 1
                if sc >= 2:
                    day_ind_flow[(d, ind)] += 1
            per.append({'d': d, 'ind': ind, 'greed': g, 'sc': sc, 'vr': vr or 0,
                        'r20': (cl[i + 20] - e) / e - COST,
                        'regime': regime_of.get(d, 'na')})
    for r in per:
        k = (r['d'], r['ind']); tot = day_ind_tot.get(k, 0)
        r['sr'] = (day_ind_flow.get(k, 0) / tot) if tot >= 3 else None
    print('检查点 %d' % len(per))

    base = [r['r20'] for r in per]
    lo = [r for r in per if r['greed'] < 35]

    # ① 个股信号数是否单调
    show('① 个股资金信号数 (贪婪<35)', {
        '0个信号': [r['r20'] for r in lo if r['sc'] == 0],
        '1个信号': [r['r20'] for r in lo if r['sc'] == 1],
        '2个信号': [r['r20'] for r in lo if r['sc'] == 2],
        '3个全中': [r['r20'] for r in lo if r['sc'] == 3],
    }, base)

    # ② 板块共振强度是否单调
    f = [r for r in lo if r['sc'] >= 2]
    show('② 板块共振强度 (贪婪<35 + 个股资金≥2)', {
        '板块<33%': [r['r20'] for r in f if r['sr'] is not None and r['sr'] < 0.33],
        '板块33~50%': [r['r20'] for r in f if r['sr'] is not None and 0.33 <= r['sr'] <= 0.5],
        '板块>50%': [r['r20'] for r in f if r['sr'] is not None and r['sr'] > 0.5],
        '板块>66%': [r['r20'] for r in f if r['sr'] is not None and r['sr'] > 0.66],
        '板块>80%': [r['r20'] for r in f if r['sr'] is not None and r['sr'] > 0.8],
    }, base)

    # ③ 贪婪深度
    fs = [r for r in f if r['sr'] is not None and r['sr'] > 0.5]
    show('③ 贪婪深度 (个股资金≥2 + 板块>50%)', {
        '贪婪<10 极冷': [r['r20'] for r in fs if r['greed'] < 10],
        '贪婪10~20': [r['r20'] for r in fs if 10 <= r['greed'] < 20],
        '贪婪20~35': [r['r20'] for r in fs if 20 <= r['greed'] < 35],
    }, base)

    # ④ 叠加加严 —— 核心提醒档候选
    show('④ 核心提醒档候选 (逐层加严)', {
        'A 资金≥2+板块>50%': [r['r20'] for r in fs],
        'B A且3个全中': [r['r20'] for r in fs if r['sc'] == 3],
        'C A且板块>66%': [r['r20'] for r in f if r['sr'] is not None and r['sr'] > 0.66],
        'D 3全中+板块>66%': [r['r20'] for r in f if r['sc'] == 3 and r['sr'] is not None and r['sr'] > 0.66],
        'E D且贪婪<20': [r['r20'] for r in f if r['sc'] == 3 and r['sr'] is not None and r['sr'] > 0.66 and r['greed'] < 20],
        'F D且放量>2倍': [r['r20'] for r in f if r['sc'] == 3 and r['sr'] is not None and r['sr'] > 0.66 and r['vr'] > 2],
    }, base)

    # ⑤ 只保留【真正有效】的两个加严维度: 板块共振强度 + 贪婪深度
    #    (①③④已证: 信号数3全中、放量倍数 都不是有效加严维度, 不要往里堆)
    def sub(gmax, srmin):
        return [r['r20'] for r in f
                if r['greed'] < gmax and r['sr'] is not None and r['sr'] > srmin]
    show('⑤ 有效维度组合 (资金≥2 打底)', {
        '板块>80%': sub(35, 0.8),
        '板块>80% + 贪婪<20': sub(20, 0.8),
        '板块>80% + 贪婪<10': sub(10, 0.8),
        '板块>66% + 贪婪<10': sub(10, 0.66),
        '板块>50% + 贪婪<10': sub(10, 0.5),
    }, base)

    # ⑥ 核心档在三种大盘环境下是否都站得住 (不能只在牛市有效)
    core = [r for r in f if r['greed'] < 10 and r['sr'] is not None and r['sr'] > 0.8]
    for rg in ['up', 'side', 'down']:
        b2 = [r['r20'] for r in per if r['regime'] == rg]
        show('⑥ regime=%s' % rg, {
            'S0基线': b2,
            '核心档(板块>80%+贪婪<10)': [r['r20'] for r in core if r['regime'] == rg],
        }, b2)


if __name__ == '__main__':
    main()
