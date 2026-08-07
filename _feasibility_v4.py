# -*- coding: utf-8 -*-
"""可行性验证 v4 —— 板块资金共振维度

用户命题的完整形态是三段式:
  贪婪指数低  +  板块资金流入  +  个股资金流入  → 强烈提醒

v3 已验证「个股资金流入」维度(全样本超额 +0.79%, up环境 +1.58%)。
v4 补验「板块共振」: 同行业当日有 ≥X% 的票同时出现资金流入信号 = 板块级资金流入代理
(真实板块净流入无法回溯, 用同业放量占比替代)。
"""
import json, os, math, ssl, urllib.request, random
from collections import defaultdict, Counter

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


def show(title, g, bk):
    print('\n### %s' % title)
    print('%-22s %7s %8s %9s %10s' % ('组别', '样本', '胜率', '均收', '超额'))
    print('-' * 62)
    b = stat(g.get(bk, []))
    for k, v in g.items():
        st = stat(v)
        if not st or st['n'] < 30:
            print('%-22s %7s  样本不足' % (k, st['n'] if st else 0)); continue
        print('%-22s %7d %7.1f%% %8.2f%% %9.2f%%'
              % (k, st['n'], st['win'] * 100, st['avg'] * 100, (st['avg'] - b['avg']) * 100))


def main():
    cache = json.load(open(os.path.join(HERE, '_bt_klines_long.json'), encoding='utf-8'))
    imap = (json.load(open(os.path.join(HERE, 'industry_map.json'), encoding='utf-8')) or {}).get('map', {})
    ind_of = {c: (imap.get(c) or {}).get('ind', '') for c in cache}
    covered = sum(1 for c in cache if ind_of.get(c))
    print('K线 %d 只, 有行业标签 %d 只' % (len(cache), covered))
    print('行业分布 top8:', Counter(v for v in ind_of.values() if v).most_common(8))

    idx = fetch_index()
    ic = [k[1] for k in idx]          # fetch_index 返回 [date, close]
    regime_of = {}
    for i, k in enumerate(idx):
        if i < 20:
            regime_of[k[0]] = 'na'; continue
        chg = (ic[i] - ic[i - 20]) / ic[i - 20] * 100
        regime_of[k[0]] = 'down' if chg < -3 else ('up' if chg > 3 else 'side')

    # 第一遍: 逐票逐日算信号, 按 (日期, 行业) 汇总
    per = []               # 每条记录
    day_ind_tot = defaultdict(int)
    day_ind_flow = defaultdict(int)
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
            flow = (int(sm) + int(sv) + int(so)) >= 2
            d = kl[i][0]
            if ind:
                day_ind_tot[(d, ind)] += 1
                if flow:
                    day_ind_flow[(d, ind)] += 1
            per.append({'d': d, 'ind': ind, 'greed': g, 'flow': flow,
                        'r20': (cl[i + 20] - e) / e - COST,
                        'regime': regime_of.get(d, 'na')})
    print('检查点 %d' % len(per))

    # 第二遍: 附板块共振比例
    for r in per:
        k = (r['d'], r['ind'])
        tot = day_ind_tot.get(k, 0)
        r['sec_ratio'] = (day_ind_flow.get(k, 0) / tot) if tot >= 3 else None

    base = [r['r20'] for r in per]
    lo = [r for r in per if r['greed'] < 35]
    g = {
        'S0全样本': base,
        'G0贪婪<35': [r['r20'] for r in lo],
        'G1个股资金': [r['r20'] for r in lo if r['flow']],
        'G1+板块共振>50%': [r['r20'] for r in lo if r['flow'] and r['sec_ratio'] is not None and r['sec_ratio'] > 0.5],
        'G1+板块共振>33%': [r['r20'] for r in lo if r['flow'] and r['sec_ratio'] is not None and r['sec_ratio'] > 0.33],
        'G1但板块冷<20%': [r['r20'] for r in lo if r['flow'] and r['sec_ratio'] is not None and r['sec_ratio'] < 0.2],
        '仅板块热无个股': [r['r20'] for r in lo if (not r['flow']) and r['sec_ratio'] is not None and r['sec_ratio'] > 0.5],
    }
    show('板块共振维度 (贪婪<35, 持有20日, 全环境)', g, 'S0全样本')

    for rg in ['up', 'side', 'down']:
        sub = [r for r in lo if r['regime'] == rg]
        b2 = [r['r20'] for r in per if r['regime'] == rg]
        if len(sub) < 200: continue
        g2 = {
            'S0': b2,
            'G1个股资金': [r['r20'] for r in sub if r['flow']],
            'G1+板块>50%': [r['r20'] for r in sub if r['flow'] and r['sec_ratio'] is not None and r['sec_ratio'] > 0.5],
            'G1板块冷<20%': [r['r20'] for r in sub if r['flow'] and r['sec_ratio'] is not None and r['sec_ratio'] < 0.2],
        }
        show('regime=%s 板块共振' % rg, g2, 'S0')


if __name__ == '__main__':
    main()
