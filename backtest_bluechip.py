# -*- coding: utf-8 -*-
"""
蓝筹低吸 · 历史胜率回测

回答用户的疑问：「蓝筹低吸名单每天都在变，我怎么回测胜率？」
答案：名单变不影响回测。回测做的是「把规则在历史上每一天重放一遍」——
      历史上每一天，凡是当天符合低吸条件的蓝筹股，都当作买入一次，
      持有 N 天后结算，统计赚钱比例。名单每天变，恰恰是每天都产生新样本。

规则（对齐 blue_chip_screener.py 的「时机」层）：
    universe : 沪深300 成分股
    低吸条件 : 现价 < 250日均线（中期回撤）   [可选叠加] 价格处近250日分位 < 40%（低位）
    持有     : 60 / 120 / 250 个交易日
    基准     : ①同日在沪深300里随机买一只（同样持有规则） ②沪深300指数本身

⚠️ 已知偏差：用的是「当前」沪深300成分，含幸存者偏差（退市/被剔除的股票不在内），
   真实胜率会略低于本结果。已在输出中标注。

用法：python backtest_bluechip.py [bars=2000] [step=5]
"""
import json, os, sys, time, math
import numpy as np
from concurrent.futures import ThreadPoolExecutor
import strategy_lab as L

HERE = os.path.dirname(os.path.abspath(__file__))
FWD = 250


def clean_nan(o):
    if isinstance(o, dict): return {k: clean_nan(v) for k, v in o.items()}
    if isinstance(o, list): return [clean_nan(v) for v in o]
    if isinstance(o, float): return None if (math.isnan(o) or math.isinf(o)) else round(o, 4)
    return o


def load_hs300():
    p = os.path.join(HERE, 'hs300_cons.json')
    codes = []
    if os.path.exists(p):
        try:
            for row in json.load(open(p, encoding='utf-8')):
                c = row[0] if isinstance(row, (list, tuple)) else row
                if isinstance(c, str) and len(c) == 6: codes.append(c)
        except Exception:
            pass
    if len(codes) < 100:
        try:
            import akshare as ak
            df = ak.index_stock_cons(symbol='000300')
            for c in df.iloc[:, 0].astype(str):
                if len(c) == 6: codes.append(c)
        except Exception as e:
            print('  [warn] 成分股获取失败:', e)
    return sorted(set(codes))


def main():
    bars = int(sys.argv[1]) if len(sys.argv) > 1 else 2000
    step = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    codes = load_hs300()
    print('[1] 沪深300 成分:', len(codes), '只')

    store = {}
    def work(code):
        tc = ('sh' + code) if code[0] == '6' else ('sz' + code)
        kd = L.fetch_kline(tc, bars)
        if kd and len(kd) > 600: store[code] = kd
    with ThreadPoolExecutor(max_workers=24) as ex:
        list(ex.map(work, codes))
    print('[2] 有效K线:', len(store), '只')
    idx = L.fetch_kline('sh000300', bars)
    ic = {k[0]: float(k[2]) for k in idx} if idx else {}
    idates = [k[0] for k in idx] if idx else []
    ipos = {d: i for i, d in enumerate(idates)}
    iclose = np.array([float(k[2]) for k in idx]) if idx else np.array([])

    rows = []   # (dateIdx, code, below_ma, pct250, fwd[FWD])
    dates_all = []
    for code, kd in store.items():
        n = len(kd)
        close = np.array([float(k[2]) for k in kd])
        dts = [k[0] for k in kd]
        ma250 = L.rolling_mean(close, 250)
        lo250 = L.rolling_min(close, 250); hi250 = L.rolling_max(close, 250)
        for i in range(300, n - FWD - 1, step):
            if np.isnan(ma250[i]) or np.isnan(lo250[i]): continue
            rng = hi250[i] - lo250[i]
            pct = (close[i] - lo250[i]) / rng if rng > 0 else 0.5
            f = close[i + 1:i + 1 + FWD] / close[i] - 1
            if len(f) < FWD: continue
            rows.append((dts[i], code, 1 if close[i] < ma250[i] else 0, pct, f.astype(np.float32)))
    print('[3] 全宇宙样本:', len(rows))
    D = np.array([r[0] for r in rows]); C = np.array([r[1] for r in rows])
    BM = np.array([r[2] for r in rows], dtype=np.int8)
    PC = np.array([r[3] for r in rows], dtype=np.float32)
    F = np.array([r[4] for r in rows], dtype=np.float32)
    bd = sorted(set(D.tolist())); bi = {d: i for i, d in enumerate(bd)}
    DI = np.array([bi[d] for d in D], dtype=np.int32)
    print('    独立交易日:', len(bd), '区间', bd[0], '~', bd[-1])

    L._Z.update({'F': F, 'D': D, 'C': C, 'DI': DI})
    L._RC.clear()

    # 沪深300 指数自身同规则基准
    def index_ret(hold, tp, stop):
        outs = []
        for d in bd:
            i = ipos.get(d)
            if i is None or i + hold >= len(iclose): continue
            path = iclose[i + 1:i + 1 + hold] / iclose[i] - 1
            r = path[-1]
            if tp is not None and (path >= tp).any(): r = tp
            elif stop is not None and (path <= -stop).any(): r = -stop
            outs.append(r)
        return (np.mean([1 if o > 0 else 0 for o in outs]) if outs else 0,
                np.mean(outs) if outs else 0)

    print('\n' + '=' * 112)
    print('蓝筹低吸回测 · 沪深300成分 · %s ~ %s · %d 只 / %d 个独立交易日' % (bd[0], bd[-1], len(store), len(bd)))
    print('基准 = 同一天在沪深300里随机买一只（同样持有规则）。超额为正才说明「低吸择时」有效。')
    print('=' * 112)

    ALL = np.ones(len(F), bool)
    scen = [
        ('不择时（随便哪天买）', ALL),
        ('现价<250日均线 [现行低吸]', BM == 1),
        ('现价>250日均线（追高对照）', BM == 0),
        ('价格处近250日分位<40%', PC < 0.40),
        ('价格处近250日分位<20% 深跌', PC < 0.20),
        ('<250日线 且 分位<40% [强化低吸]', (BM == 1) & (PC < 0.40)),
        ('<250日线 且 分位<20% [极端低吸]', (BM == 1) & (PC < 0.20)),
    ]
    result = {}
    for hold, tp, stop in [(60, None, None), (120, None, None), (250, None, None),
                           (120, .15, None), (250, .20, None)]:
        iw, ir = index_ret(hold, tp, stop)
        print('\n── 持有 %d 个交易日（约%d个月）｜止盈%s ── 沪深300指数同期：胜率%.1f%% 均值%+.2f%%'
              % (hold, round(hold / 21), tp or '不设', iw * 100, ir * 100))
        for lab, m in scen:
            s = L.evaluate(m, hold, tp, stop)
            if not s:
                print('   %-34s 样本不足' % lab); continue
            tag = '✅' if (s['win'] >= .70 and s['exexp'] > 0) else ('🟡' if s['win'] >= .70 else '  ')
            print('   %s %-32s 样本%6d 日%4d 股%3d | 胜率%5.1f%% (随机买基准%5.1f%%) 均值%+6.2f%% 超额%+6.2f%%'
                  % (tag, lab, s['n'], s['days'], s['stocks'], s['win'] * 100,
                     s['base'] * 100, s['exp'] * 100, s['exexp'] * 100))
            result['%s|%d|%s' % (lab, hold, tp or '-')] = {
                'win': round(s['win'] * 100, 1), 'base': round(s['base'] * 100, 1),
                'exp': round(s['exp'] * 100, 2), 'exexp': round(s['exexp'] * 100, 2),
                'n': s['n'], 'days': s['days'], 'index_win': round(iw * 100, 1)}

    out = {'generated': time.strftime('%Y-%m-%d %H:%M'),
           'span': [bd[0], bd[-1]], 'stocks': len(store), 'days': len(bd),
           'samples': int(len(F)),
           'note': '沪深300当前成分，含幸存者偏差；基准为同日随机买一只沪深300成分股',
           'result': result}
    json.dump(clean_nan(out), open(os.path.join(HERE, 'bluechip_backtest.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, allow_nan=False)
    print('\n✅ 已保存 bluechip_backtest.json')


if __name__ == '__main__':
    main()
