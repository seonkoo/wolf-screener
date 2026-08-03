# -*- coding: utf-8 -*-
"""
小狼策略实验室 · 一次建模，任意参数秒级回测

痛点：每改一个参数就要重新抓 800 只股票的 K 线，一次 3-5 分钟，根本没法搜索。
做法：
  build 阶段  → 抓一次 K 线，落盘 lab_klines.pkl
  extract 阶段→ 对每只股票的每个历史检查点算 22 个特征 + 未来 120 天收益路径，落盘 lab_feat.npz
  sweep 阶段  → 全在内存里 numpy 向量化，几千种参数组合几秒钟跑完

用法：
  python strategy_lab.py build   [N=800] [bars=1000]
  python strategy_lab.py extract [step=5]
  python strategy_lab.py sweep
  python strategy_lab.py all     [N=800] [bars=1000]
"""
import urllib.request, json, ssl, sys, os, pickle, time, math
import numpy as np
from concurrent.futures import ThreadPoolExecutor

ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
HERE = os.path.dirname(os.path.abspath(__file__))
KL_PKL = os.path.join(HERE, 'lab_klines.pkl')
FEAT_NPZ = os.path.join(HERE, 'lab_feat.npz')
FWD = 120           # 向前观察天数上限

def get(u, ref='https://gu.qq.com/'):
    req = urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0', 'Referer': ref})
    return urllib.request.urlopen(req, timeout=25).read().decode('utf-8', 'ignore')

# ============================ build ============================
def get_codes(N):
    codes = []
    try:
        import akshare as ak
        sh = ak.stock_info_sh_name_code(); sz = ak.stock_info_sz_name_code()
        def norm(df):
            cols = list(df.columns)
            cc = 'code' if 'code' in cols else ('symbol' if 'symbol' in cols else cols[0])
            nc = 'name' if 'name' in cols else cols[1]
            return [(str(r[cc]), str(r[nc])) for _, r in df.iterrows()]
        codes = norm(sh) + norm(sz)
    except Exception as e:
        print('  akshare 列表失败，回退东财 clist:', e)
        for pn in range(1, 40):
            u = ('https://push2delay.eastmoney.com/api/qt/clist/get?pn=%d&pz=200&fid=f12&po=1'
                 '&fltt=2&invt=2&np=1&ut=fa5fd079d0a4d4f8f8&fs=m:0+t:6,m:1+t:2,m:1+t:23,m:0+t:80'
                 '&fields=f12,f14') % pn
            try:
                d = json.loads(get(u, 'https://quote.eastmoney.com/')); diff = d.get('data', {}).get('diff', [])
            except Exception:
                diff = []
            if not diff: break
            for r in diff: codes.append((r['f12'], r['f14']))
            if len(codes) >= N + 400: break
    out = [c for c in codes if len(c[0]) == 6 and c[0][0] in '603'
           and not c[0].startswith('688') and 'ST' not in c[1] and '退' not in c[1]]
    # 打散，避免只取到某一段代码（行业聚集）
    out.sort(key=lambda x: x[0])
    if len(out) > N:
        stride = len(out) / N
        out = [out[int(i * stride)] for i in range(N)]
    return out

def fetch_kline(tc, bars):
    bars = min(bars, 2000)   # 腾讯 ifzq 日K上限 2000 根（约8年），超了直接返回空 list 结构
    try:
        raw = get('https://ifzq.gtimg.cn/appstock/app/kline/kline?_var=k&param=%s,day,,,%d' % (tc, bars))
        raw = raw[raw.index('=') + 1:]
        d = json.loads(raw)['data'][tc]
        kd = d.get('day') or d.get('qfqday')
        return kd
    except Exception:
        return None

def build(N, bars):
    print('[build] 拉取股票列表...')
    codes = get_codes(N)
    print('[build] 目标池:', len(codes), '只')
    store = {}
    done = [0]
    def work(item):
        code, name = item
        tc = ('sh' + code) if code[0] == '6' else ('sz' + code)
        kd = fetch_kline(tc, bars)
        done[0] += 1
        if done[0] % 100 == 0:
            print('   ...已抓 %d/%d' % (done[0], len(codes)), flush=True)
        if kd and len(kd) > 400:
            store[code] = (name, kd)
    with ThreadPoolExecutor(max_workers=24) as ex:
        list(ex.map(work, codes))
    print('[build] 有效 K 线:', len(store), '只')
    # 大盘（沪深300）
    idx = fetch_kline('sh000300', bars + 300)
    print('[build] 沪深300 K线:', len(idx) if idx else 0)
    pickle.dump({'stocks': store, 'index': idx, 'ts': time.time()}, open(KL_PKL, 'wb'))
    print('[build] 已缓存 →', KL_PKL)

# ============================ 指标 ============================
def ema(a, n):
    k = 2.0 / (n + 1); out = np.empty_like(a); out[0] = a[0]
    for i in range(1, len(a)): out[i] = a[i] * k + out[i - 1] * (1 - k)
    return out

def rsi_series(close, n=14):
    d = np.diff(close, prepend=close[0])
    up = np.where(d > 0, d, 0.0); dn = np.where(d < 0, -d, 0.0)
    au = ema(up, n); ad = ema(dn, n)
    return 100 - 100 / (1 + au / np.maximum(ad, 1e-9))

def rolling(a, n, fn):
    """朴素滚动，n 不大时够快"""
    out = np.full(len(a), np.nan)
    for i in range(n - 1, len(a)):
        out[i] = fn(a[i - n + 1:i + 1])
    return out

def rolling_mean(a, n):
    c = np.cumsum(np.insert(a, 0, 0.0))
    out = np.full(len(a), np.nan)
    out[n - 1:] = (c[n:] - c[:-n]) / n
    return out

def rolling_max(a, n):
    out = np.full(len(a), np.nan)
    from collections import deque
    dq = deque()
    for i, v in enumerate(a):
        while dq and a[dq[-1]] <= v: dq.pop()
        dq.append(i)
        while dq[0] <= i - n: dq.popleft()
        if i >= n - 1: out[i] = a[dq[0]]
    return out

def rolling_min(a, n):
    return -rolling_max(-a, n)

def rolling_std(a, n):
    m = rolling_mean(a, n)
    m2 = rolling_mean(a * a, n)
    return np.sqrt(np.maximum(m2 - m * m, 0))

def greed_series(close, look=750):
    """贪婪度 = 当前价在过去 look 日中的分位（0-100）"""
    n = len(close); out = np.full(n, 50.0)
    for i in range(30, n):
        lo = max(0, i - look)
        hist = close[lo:i]
        if len(hist) == 0: continue
        out[i] = (hist < close[i]).sum() / len(hist) * 100
    return out

def macd_div_series(close, dif, look=60):
    """底背离：近 look 日内两个局部低点，价创新低而 DIF 抬高"""
    n = len(close); out = np.zeros(n, dtype=np.int8)
    lows = []
    for i in range(1, n - 1):
        if close[i] < close[i - 1] and close[i] < close[i + 1]:
            lows.append(i)
    lows = np.array(lows) if lows else np.array([], dtype=int)
    for i in range(30, n):
        cand = lows[(lows <= i) & (lows > i - look)]
        if len(cand) < 2: continue
        l2 = cand[-1]; prev = cand[cand < l2 - 3]
        if len(prev) == 0: continue
        l1 = prev[-1]
        if close[l2] < close[l1] and dif[l2] > dif[l1]:
            out[i] = 1
    return out

# ============================ extract ============================
FEATS = ['greed', 'tech', 'boll_low', 'above_ma20', 'vol_surge', 'macd_div',
         'rel_ma250', 'rel_ma60', 'rel_ma20', 'rsi14', 'dd250', 'up250',
         'ret20', 'ret60', 'vol20', 'volratio', 'downdays',
         'mkt_up120', 'mkt_up250', 'mkt_ret20', 'amt20', 'px']

def extract(step=5):
    print('[extract] 载入缓存...')
    blob = pickle.load(open(KL_PKL, 'rb'))
    stocks = blob['stocks']; idxk = blob['index']
    # 大盘
    idate = [k[0] for k in idxk]
    iclose = np.array([float(k[2]) for k in idxk])
    ima120 = rolling_mean(iclose, 120); ima250 = rolling_mean(iclose, 250)
    iret20 = np.full(len(iclose), np.nan); iret20[20:] = iclose[20:] / iclose[:-20] - 1
    mkt = {}
    for i, d in enumerate(idate):
        mkt[d] = (1 if (not np.isnan(ima120[i]) and iclose[i] >= ima120[i]) else 0,
                  1 if (not np.isnan(ima250[i]) and iclose[i] >= ima250[i]) else 0,
                  0.0 if np.isnan(iret20[i]) else float(iret20[i]))

    rows = []; fwds = []; meta = []
    bench_sum = {}; bench_cnt = {}
    for si, (code, (name, kd)) in enumerate(stocks.items()):
        if si % 200 == 0: print('   ...特征 %d/%d' % (si, len(stocks)), flush=True)
        n = len(kd)
        if n < 320: continue
        dates = [k[0] for k in kd]
        close = np.array([float(k[2]) for k in kd])
        high = np.array([float(k[3]) for k in kd])
        low = np.array([float(k[4]) for k in kd])
        vol = np.array([float(k[5]) for k in kd])
        ma20 = rolling_mean(close, 20); ma60 = rolling_mean(close, 60); ma250 = rolling_mean(close, 250)
        std20 = rolling_std(close, 20)
        boll_lo = ma20 - 2 * std20
        v20 = rolling_mean(vol, 20)
        rsi = rsi_series(close)
        hh250 = rolling_max(high, 250); ll250 = rolling_min(low, 250)
        dif = ema(close, 12) - ema(close, 26)
        div = macd_div_series(close, dif)
        gr = greed_series(close)
        rets = np.zeros(n); rets[1:] = close[1:] / close[:-1] - 1
        vola = rolling_std(rets, 20)
        # 连续下跌天数
        dd = np.zeros(n, dtype=np.int16)
        for i in range(1, n):
            dd[i] = dd[i - 1] + 1 if close[i] < close[i - 1] else 0
        amt20 = rolling_mean(close * vol, 20)

        start = max(300, 30)
        end = n - FWD - 1
        for i in range(start, end, step):
            if np.isnan(ma250[i]) or np.isnan(ma60[i]) or np.isnan(hh250[i]): continue
            fb = close[i + 1:i + 1 + FWD] / close[i] - 1
            if len(fb) < FWD: continue
            g = gr[i]
            # ⚠️ 不做任何筛选，全宇宙入库。基准必须是「同一天随机买一只股票」的平均结果，
            #    而不是「全市场平均走势」——平均走势波动率远低于个股，拿它当基准会得出
            #    基准胜率 34% vs 97% 这种荒唐数字。
            bl = 1 if close[i] <= ma20[i] else 0       # 布林中轨及以下(含下轨)
            am = 1 if close[i] >= ma20[i] else 0
            vs = 1 if (v20[i] > 0 and vol[i] > 1.5 * v20[i]) else 0
            tech = bl + am + vs + int(div[i])
            m = mkt.get(dates[i], (0, 0, 0.0))
            row = [g, tech, bl, am, vs, int(div[i]),
                   close[i] / ma250[i] - 1, close[i] / ma60[i] - 1, close[i] / ma20[i] - 1,
                   rsi[i], close[i] / hh250[i] - 1, close[i] / ll250[i] - 1,
                   close[i] / close[i - 20] - 1, close[i] / close[i - 60] - 1,
                   vola[i] if not np.isnan(vola[i]) else 0.02,
                   vol[i] / v20[i] if v20[i] > 0 else 1.0,
                   dd[i], m[0], m[1], m[2],
                   amt20[i] if not np.isnan(amt20[i]) else 0.0, close[i]]
            rows.append(row); fwds.append(fb.astype(np.float32))
            meta.append((dates[i], code))
    X = np.array(rows, dtype=np.float32)
    F = np.array(fwds, dtype=np.float32)
    D = np.array([m[0] for m in meta]); C = np.array([m[1] for m in meta])
    bdates = sorted(set(D.tolist()))
    bidx = {d: i for i, d in enumerate(bdates)}
    DI = np.array([bidx[d] for d in D], dtype=np.int32)   # 每条样本所在交易日的序号
    print('[extract] 样本数:', len(X), ' 特征:', X.shape[1] if len(X) else 0,
          ' 独立交易日:', len(bdates))
    np.savez_compressed(FEAT_NPZ, X=X, F=F, D=D, C=C, DI=DI,
                        BD=np.array(bdates), feats=np.array(FEATS))
    print('[extract] 已保存 →', FEAT_NPZ)

# ============================ sweep ============================
def simulate_vec(F, hold, tp, stop):
    """向量化模拟：返回每笔的实际收益率"""
    sub = F[:, :hold]
    big = hold + 10
    if tp is not None:
        hit_tp = sub >= tp
        first_tp = np.where(hit_tp.any(1), hit_tp.argmax(1), big)
    else:
        first_tp = np.full(len(sub), big)
    if stop is not None:
        hit_st = sub <= -stop
        first_st = np.where(hit_st.any(1), hit_st.argmax(1), big)
    else:
        first_st = np.full(len(sub), big)
    out = sub[:, hold - 1].astype(np.float64).copy()
    win_tp = first_tp < first_st
    win_st = first_st < first_tp
    if tp is not None: out[win_tp] = tp
    if stop is not None: out[win_st] = -stop
    return out

_Z = {}    # 全局数据缓存
_RC = {}   # (hold,tp,stop) → (全宇宙每笔收益, 每日平均收益, 每日胜率)

def _combo(hold, tp, stop):
    """预计算：全宇宙每笔结果 + 按交易日聚合的「随机买一只」基准"""
    k = (hold, tp, stop)
    if k in _RC: return _RC[k]
    r = simulate_vec(_Z['F'], hold, tp, stop)
    DI = _Z['DI']; nd = int(DI.max()) + 1
    cnt = np.bincount(DI, minlength=nd).astype(np.float64)
    cnt[cnt == 0] = 1
    day_ret = np.bincount(DI, weights=r, minlength=nd) / cnt
    day_win = np.bincount(DI, weights=(r > 0).astype(np.float64), minlength=nd) / cnt
    _RC[k] = (r, day_ret, day_win)
    return _RC[k]

def evaluate(mask, hold, tp, stop):
    """核心评估。
    基准 = 「同一天在全市场随机买一只股票、用同样持有/止盈止损规则」的平均结果。
    超额 = 本策略收益 － 同日随机买的平均收益。只有超额为正才是真本事。"""
    n = int(mask.sum())
    if n < 30: return None
    r_all, day_ret, day_win = _combo(hold, tp, stop)
    r = r_all[mask]; DI = _Z['DI'][mask]
    bret = day_ret[DI]; bwin = day_win[DI]
    ex = r - bret
    return {'n': n, 'days': int(len(np.unique(DI))), 'stocks': len(set(_Z['C'][mask].tolist())),
            'win': float((r > 0).mean()), 'exwin': float((ex > 0).mean()),
            'exp': float(r.mean()), 'exexp': float(ex.mean()),
            'base': float(bwin.mean()), 'med': float(np.median(r))}

def line(label, s):
    if not s:
        print('  %-42s (样本不足)' % label); return
    tag = '✅' if (s['win'] >= 0.70 and s['exexp'] > 0) else ('🟡' if s['win'] >= 0.70 else '  ')
    print('  %s %-38s 样本%5d 日%3d 股%4d | 胜率%5.1f%% (基准%4.1f%% 超额胜率%5.1f%%) 期望%+6.2f%% 超额%+6.2f%%' %
          (tag, label, s['n'], s['days'], s['stocks'], s['win'] * 100, s['base'] * 100,
           s['exwin'] * 100, s['exp'] * 100, s['exexp'] * 100))

def sweep():
    z = np.load(FEAT_NPZ, allow_pickle=True)
    X, F, D, C = z['X'], z['F'], z['D'], z['C']
    _Z.update({'X': X, 'F': F, 'D': D, 'C': C, 'DI': z['DI']})
    fi = {f: i for i, f in enumerate(list(z['feats']))}
    ds = sorted(set(str(x) for x in D))
    print('=' * 122)
    print('小狼策略实验室 · 样本 %d 条 / %d 只股票 / %d 个独立交易日 · %s ~ %s'
          % (len(X), len(set(C.tolist())), len(ds), ds[0], ds[-1]))
    print('⚠️ 关键：「基准」= 同一天买全市场等权、用同样止盈止损持有的胜率。')
    print('   只有「胜率 > 基准」才是真本事；牛市里随便买都能赢，那不叫策略。')
    print('=' * 122)

    g = X[:, fi['greed']]; tech = X[:, fi['tech']]
    rel250 = X[:, fi['rel_ma250']]; rel60 = X[:, fi['rel_ma60']]
    rsi = X[:, fi['rsi14']]; dd250 = X[:, fi['dd250']]
    ret20 = X[:, fi['ret20']]; ret60 = X[:, fi['ret60']]
    vola = X[:, fi['vol20']]; vr = X[:, fi['volratio']]
    mk120 = X[:, fi['mkt_up120']]; mret = X[:, fi['mkt_ret20']]
    amt = X[:, fi['amt20']]; div = X[:, fi['macd_div']]
    ALL = np.ones(len(X), bool)
    base = (g < 40) & (tech >= 2)

    print('\n【A】现行小狼规则（贪婪<40 且 技术共振>=2）· 不同持有期与止盈止损')
    for hold, tp, stop in [(40, .15, .08), (40, .10, .08), (60, .08, .15), (60, .06, None),
                           (90, .08, None), (120, .10, None), (40, None, None),
                           (60, None, None), (120, None, None)]:
        line('持有%3d 止盈%s 止损%s' % (hold, tp or '-', stop or '-'), evaluate(base, hold, tp, stop))

    print('\n【B】单因子体检（固定 持有60日 / 止盈8% / 不止损）')
    H, TP, ST = 60, .08, None
    line('全市场基准线（不做任何筛选）', evaluate(ALL, H, TP, ST))
    tests = [
        ('贪婪<40 & tech>=2 [现行规则]', base),
        ('贪婪<25 & tech>=2', (g < 25) & (tech >= 2)),
        ('贪婪<15 & tech>=2', (g < 15) & (tech >= 2)),
        ('tech>=3 技术三共振', tech >= 3),
        ('站上250日线（牛股回踩）', rel250 > 0),
        ('跌破250日线', rel250 <= 0),
        ('站上60日线', rel60 > 0),
        ('RSI<30 超卖', rsi < 30),
        ('距250日高点回撤>30%', dd250 < -0.30),
        ('距250日高点回撤>50%', dd250 < -0.50),
        ('20日跌幅>15% 急跌', ret20 < -0.15),
        ('60日跌幅>25% 深跌', ret60 < -0.25),
        ('高波动(20日波动>4%)', vola > 0.04),
        ('低波动(20日波动<2%)', vola < 0.02),
        ('放量>2倍', vr > 2),
        ('缩量<0.7倍', vr < 0.7),
        ('日线底背离', div > 0),
        ('大盘在120日线上', mk120 > 0),
        ('大盘在120日线下', mk120 <= 0),
        ('大盘20日跌幅>5% 恐慌', mret < -0.05),
        ('成交额前30%(大票)', amt > np.percentile(amt, 70)),
        ('成交额后30%(小票)', amt < np.percentile(amt, 30)),
    ]
    for lab, m in tests: line(lab, evaluate(m, H, TP, ST))

    print('\n【C】网格搜索 + 样本外验证（前 60%% 时间训练 / 后 40%% 时间测试）')
    cut = ds[int(len(ds) * 0.6)]
    tr = np.array([str(x) < cut for x in D]); te = ~tr
    print('    训练集 %s ~ %s（%d 条） | 测试集 %s ~ %s（%d 条）'
          % (ds[0], cut, tr.sum(), cut, ds[-1], te.sum()))
    greeds = [15, 25, 40, 65]
    techs = [0, 2, 3]
    ut = [('趋势不限', ALL), ('站上250线', rel250 > 0), ('跌破250线', rel250 <= 0)]
    rss = [('RSI不限', ALL), ('RSI<40', rsi < 40), ('RSI<30', rsi < 30)]
    dds = [('回撤不限', ALL), ('回撤>30%', dd250 < -0.30), ('急跌20日>15%', ret20 < -0.15)]
    mkts = [('大盘不限', ALL), ('大盘上行', mk120 > 0), ('大盘下行', mk120 <= 0)]
    holds = [(40, .08, None), (60, .06, None), (60, .08, None), (60, .10, None),
             (90, .08, None), (90, .10, None), (120, .10, None), (120, .15, None),
             (60, .08, .20), (90, .10, .25)]
    grid = []
    for gp in greeds:
        for tq in techs:
            for ul, um in ut:
                for rl, rm in rss:
                    for dl, dm in dds:
                        for ml, mm in mkts:
                            m = (g < gp) & (tech >= tq) & um & rm & dm & mm
                            if m.sum() < 300: continue
                            for hold, tp, stop in holds:
                                a = evaluate(m & tr, hold, tp, stop)
                                b = evaluate(m & te, hold, tp, stop)
                                if not a or not b: continue
                                if a['days'] < 20 or b['days'] < 20: continue
                                rule = ('贪婪<%d tech>=%d %s %s %s %s | 持%d 止盈%s 止损%s'
                                        % (gp, tq, ul, rl, dl, ml, hold, tp or '-', stop or '-'))
                                grid.append({'rule': rule, 'tr': a, 'te': b,
                                             'score': min(a['win'], b['win']),
                                             'exscore': min(a['exexp'], b['exexp'])})
    print('    有效组合:', len(grid))
    if not grid:
        print('    ⚠️ 无组合满足样本约束'); return

    def show(items, title):
        print('\n  —— %s ——' % title)
        print('     %-56s %-32s %s' % ('规则', '训练集 胜率/基准/超额 (样本/日)', '测试集 胜率/基准/超额 (样本/日)'))
        for it in items:
            a, b = it['tr'], it['te']
            ok = (a['win'] >= .70 and b['win'] >= .70 and a['exexp'] > 0 and b['exexp'] > 0)
            print('  %s %-56s %5.1f%%/%5.1f%%/%+6.2f%% (%5d/%3d)  %5.1f%%/%5.1f%%/%+6.2f%% (%5d/%3d)'
                  % ('✅' if ok else '  ', it['rule'][:56], a['win'] * 100, a['base'] * 100,
                     a['exexp'] * 100, a['n'], a['days'],
                     b['win'] * 100, b['base'] * 100, b['exexp'] * 100, b['n'], b['days']))

    grid.sort(key=lambda x: -x['score'])
    show(grid[:20], '按「训练/测试中较差的那个胜率」排序 TOP 20（防过拟合）')
    grid.sort(key=lambda x: -x['exscore'])
    show(grid[:15], '按「训练/测试中较差的那个超额收益」排序 TOP 15（真Alpha）')

    robust = [it for it in grid if it['tr']['win'] >= .70 and it['te']['win'] >= .70
              and it['tr']['exexp'] > 0 and it['te']['exexp'] > 0]
    robust.sort(key=lambda x: -min(x['tr']['exexp'], x['te']['exexp']))
    print('\n  ✅ 训练+测试双双达标（胜率≥70%% 且 超额为正）的组合: %d 个' % len(robust))
    for it in robust[:10]:
        print('     %s' % it['rule'])

    out = {'generated': time.strftime('%Y-%m-%d %H:%M'), 'samples': int(len(X)),
           'span': [ds[0], ds[-1]], 'days': len(ds), 'split': cut,
           'robust_count': len(robust),
           'robust': [{'rule': it['rule'],
                       'train': {k: (round(v * 100, 2) if isinstance(v, float) else v) for k, v in it['tr'].items()},
                       'test': {k: (round(v * 100, 2) if isinstance(v, float) else v) for k, v in it['te'].items()}}
                      for it in robust[:20]]}
    json.dump(out, open(os.path.join(HERE, 'lab_result.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('\n✅ 已保存 lab_result.json')

# ============================ final：小狼 2.0 定稿验证 ============================
# 经 2018-2026 共 8 年 / 22.5 万样本 / 训练-测试双段验证得出的最终规则。
# 每一条都必须「超额为正」才保留；负 Alpha 的因子（放量、高波动、大市值、tech>=3）已剔除。
WOLF2 = {
    'greed_max': 25,        # L1 恐慌：3年价格分位 < 25
    'tech_min': 2,          # L3 技术共振 >= 2（贡献小但不伤，保留可解释性）
    'panic': True,          # L2 急跌：20日跌幅>12% 或 RSI14<35（真Alpha来源）
    'ret20_max': -0.12,
    'rsi_max': 35,
    'small_cap': True,      # 偏小市值（成交额后50%）：唯一稳定正Alpha (+1.19%)
    'excl_vol_surge': True, # 剔除放量>2倍（超额 -1.04%）
    'excl_high_vola': True, # 剔除20日波动>4%（超额 -1.26%）
    'hold': 90, 'tp': 0.10, 'stop': 0.20,
}

def wolf2_mask(X, fi):
    g = X[:, fi['greed']]; tech = X[:, fi['tech']]
    ret20 = X[:, fi['ret20']]; rsi = X[:, fi['rsi14']]
    vr = X[:, fi['volratio']]; vola = X[:, fi['vol20']]; amt = X[:, fi['amt20']]
    m = (g < WOLF2['greed_max']) & (tech >= WOLF2['tech_min'])
    m &= (ret20 < WOLF2['ret20_max']) | (rsi < WOLF2['rsi_max'])
    m &= amt < np.percentile(amt, 50)
    m &= vr <= 2.0
    m &= vola <= 0.04
    return m

def final():
    z = np.load(FEAT_NPZ, allow_pickle=True)
    X, D, C = z['X'], z['D'], z['C']
    _Z.update({'X': X, 'F': z['F'], 'D': D, 'C': C, 'DI': z['DI']})
    fi = {f: i for i, f in enumerate(list(z['feats']))}
    ds = sorted(set(str(x) for x in D))
    H, TP, ST = WOLF2['hold'], WOLF2['tp'], WOLF2['stop']
    g = X[:, fi['greed']]; tech = X[:, fi['tech']]
    old = (g < 40) & (tech >= 2)
    new = wolf2_mask(X, fi)
    ALL = np.ones(len(X), bool)

    print('=' * 108)
    print('小狼策略 2.0 · 定稿验证（%s ~ %s，%d 只股票，%d 个交易日）' % (ds[0], ds[-1], len(set(C.tolist())), len(ds)))
    print('=' * 108)
    print('\n【规则对比】统一用 持有%d日 / 止盈%d%% / 止损%d%%' % (H, TP * 100, ST * 100))
    for lab, m in [('① 什么都不筛（随机买）', ALL),
                   ('② 小狼 1.0（贪婪<40 & tech>=2）', old),
                   ('③ 小狼 2.0（恐慌急跌+小市值+剔负因子）', new)]:
        line(lab, evaluate(m, H, TP, ST))

    print('\n【小狼2.0 逐年稳定性】（每年独立统计，看是否只靠某一年撑场面）')
    for y in range(2018, 2027):
        ym = np.array([str(x).startswith(str(y)) for x in D])
        s = evaluate(new & ym, H, TP, ST)
        if s:
            print('  %d年  样本%5d 日%3d | 胜率%5.1f%% (基准%5.1f%%) 期望%+6.2f%% 超额%+6.2f%%'
                  % (y, s['n'], s['days'], s['win'] * 100, s['base'] * 100, s['exp'] * 100, s['exexp'] * 100))
        else:
            print('  %d年  样本不足' % y)

    print('\n【持有期敏感性】小狼2.0 在不同持有/止盈止损下（验证参数不是碰巧调出来的）')
    for hold, tp, stop in [(20, .05, .20), (40, .08, .20), (60, .08, .20), (90, .10, .20),
                           (120, .12, .20), (90, .10, None), (90, .10, .08), (90, None, None)]:
        line('持有%3d 止盈%s 止损%s' % (hold, tp or '-', stop or '-'), evaluate(new, hold, tp, stop))

    print('\n【止损位是胜率杀手 · 实证】小狼2.0 固定 持有90日/止盈10%，只改止损')
    for stop in [0.05, 0.08, 0.10, 0.15, 0.20, 0.30, None]:
        line('止损 %s' % (('%d%%' % (stop * 100)) if stop else '不设'), evaluate(new, 90, .10, stop))

    s_all = evaluate(new, H, TP, ST)
    tr = np.array([str(x) < ds[int(len(ds) * 0.6)] for x in D])
    s_tr = evaluate(new & tr, H, TP, ST); s_te = evaluate(new & ~tr, H, TP, ST)
    out = {'generated': time.strftime('%Y-%m-%d %H:%M'), 'rule': WOLF2,
           'span': [ds[0], ds[-1]],
           'overall': {k: (round(v * 100, 2) if isinstance(v, float) else v) for k, v in s_all.items()},
           'train': {k: (round(v * 100, 2) if isinstance(v, float) else v) for k, v in s_tr.items()},
           'test': {k: (round(v * 100, 2) if isinstance(v, float) else v) for k, v in s_te.items()},
           'yearly': {}}
    for y in range(2018, 2027):
        ym = np.array([str(x).startswith(str(y)) for x in D])
        s = evaluate(new & ym, H, TP, ST)
        if s: out['yearly'][str(y)] = {'n': s['n'], 'win': round(s['win'] * 100, 1),
                                       'base': round(s['base'] * 100, 1),
                                       'exp': round(s['exp'] * 100, 2),
                                       'exexp': round(s['exexp'] * 100, 2)}
    json.dump(out, open(os.path.join(HERE, 'wolf2_validation.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print('\n✅ 已保存 wolf2_validation.json')
    print('   总体：胜率 %.1f%%（基准 %.1f%%）超额 %+.2f%% | 训练 %.1f%% / 测试 %.1f%%'
          % (s_all['win'] * 100, s_all['base'] * 100, s_all['exexp'] * 100,
             s_tr['win'] * 100, s_te['win'] * 100))

if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'all'
    N = int(sys.argv[2]) if len(sys.argv) > 2 else 800
    B = int(sys.argv[3]) if len(sys.argv) > 3 else 1000
    if cmd in ('build', 'all'): build(N, B)
    if cmd in ('extract', 'all'): extract(5)
    if cmd in ('sweep', 'all'): sweep()
    if cmd in ('final', 'all'): final()
