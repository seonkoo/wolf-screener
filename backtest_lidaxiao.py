# -*- coding: utf-8 -*-
"""
李大霄估值温度的「历史有效性」回测
==================================================================
验证核心命题：当上证50 PE 处于历史低位（分位低）时，之后 60/120 个交易日
的中证50（用上证50指数收盘代理）收益，是否显著优于全样本中位收益？

若显著更优 → 温度低确实含有「中期赔率」信息（历史验证）；
若没有 → 诚实标注「历史未显著验证」，避免把框架当信号。

输出写入 li_daxiao.json 的 backtest 字段（由 sync_auto_tab 烘焙进页面）。
全程 try/except 兜底：任何失败只写 {available:false}，不影响主模块部署。
==================================================================
"""
import json, os, time
import urllib.request
from datetime import datetime, timedelta
import akshare as ak
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
PE_CACHE = os.path.join(HERE, 'sz50_pe_history.json')
CLOSE_CACHE = os.path.join(HERE, 'sz50_close_history.json')
OUT = os.path.join(HERE, 'li_daxiao.json')
CACHE_SEC = 24 * 3600
CHEAP_PCT = 25  # PE 历史分位 < 25% 视为「便宜区」


def log(*a):
    print('[backtest_lidaxiao]', *a)


def load_pe():
    if not os.path.exists(PE_CACHE):
        return {}
    try:
        d = json.load(open(PE_CACHE, encoding='utf-8'))
        return {r['date']: r['v'] for r in d.get('rows', []) if r.get('v') is not None}
    except Exception as e:
        log('load_pe 失败', e)
        return {}


def load_close():
    """取上证50指数(000016)日收盘，带 24h 缓存。返回 {date: close}。
    优先 akshare（生产 Actions 环境可达）；失败则用腾讯 ifzq 分页拉全历史（沙箱可达）。"""
    if os.path.exists(CLOSE_CACHE):
        try:
            d = json.load(open(CLOSE_CACHE, encoding='utf-8'))
            if time.time() - d.get('ts', 0) < CACHE_SEC:
                return d['rows']
        except Exception:
            pass
    rows = {}
    # 1) akshare（生产环境）
    try:
        ed = time.strftime('%Y%m%d')
        df = ak.index_zh_a_hist(symbol='000016', period='daily',
                                 start_date='20050101', end_date=ed)
        rows = {str(r[0]): float(r[1]) for r in df[['日期', '收盘']].itertuples(index=False, name=None)}
        if rows:
            json.dump({'ts': time.time(), 'rows': rows}, open(CLOSE_CACHE, 'w', encoding='utf-8'))
            log('akshare 上证50收盘 %d 条' % len(rows))
            return rows
    except Exception as e:
        log('akshare 收盘失败，回退腾讯: %s' % e)
    # 2) 腾讯 ifzq 分页（沙箱/限流环境），每页最多 1024 根，向前翻页直到 2005
    try:
        bars = []
        end = None
        for _ in range(12):  # 最多 ~12*1024 ≈ 30 年
            param = 'sh000016,day,,' + (end + ',' if end else ',') + '1024'
            url = 'https://ifzq.gtimg.cn/appstock/app/kline/kline?param=' + param
            raw = urllib.request.urlopen(url, timeout=25).read().decode('utf-8')
            d = json.loads(raw)
            data = d.get('data')
            kl = []
            if isinstance(data, dict):
                v = data.get('sh000016', {})
                kl = v.get('day') or v.get('qfqday') or []
            if not kl:
                break
            chunk = [[r[0], float(r[2])] for r in kl]
            bars = chunk + bars
            first = kl[0][0]
            if first <= '2005-01-01' or len(chunk) < 1024:
                break
            end = (datetime.strptime(first, '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d')
        rows = {b[0]: b[1] for b in bars}
        if rows:
            json.dump({'ts': time.time(), 'rows': rows}, open(CLOSE_CACHE, 'w', encoding='utf-8'))
            log('腾讯 上证50收盘 %d 条' % len(rows))
            return rows
    except Exception as e:
        log('腾讯 收盘失败: %s' % e)
    return {}


def main():
    t0 = time.time()
    try:
        pe = load_pe()
        close = load_close()
        if not pe or not close:
            raise RuntimeError('PE或收盘数据缺失')
        # 按日期对齐（交集）
        dates = sorted(set(pe) & set(close))
        if len(dates) < 400:
            raise RuntimeError('对齐样本不足(%d)' % len(dates))
        pe_arr = np.array([pe[d] for d in dates], dtype=float)
        close_arr = np.array([close[d] for d in dates], dtype=float)
        n = len(dates)
        cheap60, all60, cheap120, all120 = [], [], [], []
        win_cheap, win_all = 0, 0  # 正收益占比
        for t in range(n):
            if t + 120 >= n:
                break
            win = pe_arr[max(0, t - 1260): t + 1]
            if len(win) < 60:
                continue
            pct = float(np.mean(win < pe_arr[t]) * 100)
            r60 = close_arr[t + 60] / close_arr[t] - 1
            r120 = close_arr[t + 120] / close_arr[t] - 1
            all60.append(r60); all120.append(r120)
            if r60 > 0:
                win_all += 1
            if pct < CHEAP_PCT:
                cheap60.append(r60); cheap120.append(r120)
                if r60 > 0:
                    win_cheap += 1
        if not all60:
            raise RuntimeError('无可用观测')
        med = lambda x: float(np.median(x)) if x else None
        cheap_n = len(cheap60)
        c60, a60 = med(cheap60), med(all60)
        c120, a120 = med(cheap120), med(all120)
        # 判定：便宜区中位收益显著高于全样本（60日 > +2pct 且 120日 > +3pct 视为验证）
        verified = (c60 is not None and c60 > (a60 or 0) + 0.02 and
                    c120 is not None and c120 > (a120 or 0) + 0.03)
        weak = (c60 is not None and a60 is not None and c60 < a60)
        if verified:
            verdict = '历史验证：低估值(PE分位<%d%%)后，中期收益显著优于全样本，温度确有中期赔率信息' % CHEAP_PCT
        elif weak:
            verdict = '历史未验证：低估值后中期收益反而弱于全样本，温度仅作「下行空间收敛」参考，勿当买入信号'
        else:
            verdict = '历史中性：低估值后收益与全样本差异有限，温度作为辅助参考'
        bt = {
            'available': True,
            'cheap_pct_threshold': CHEAP_PCT,
            'sample_n': len(all60),
            'cheap_n': cheap_n,
            'cheap_med60': round(c60 * 100, 2) if c60 is not None else None,
            'all_med60': round(a60 * 100, 2) if a60 is not None else None,
            'cheap_med120': round(c120 * 100, 2) if c120 is not None else None,
            'all_med120': round(a120 * 100, 2) if a120 is not None else None,
            'cheap_win_rate60': round(win_cheap / cheap_n * 100, 1) if cheap_n else None,
            'all_win_rate60': round(win_all / len(all60) * 100, 1) if all60 else None,
            'verdict': verdict,
            'verified': verified,
        }
        log('完成：sample=%d cheap=%d | 60d 中位 便宜%.1f%% vs 全样%.1f%% | 120d 便宜%.1f%% vs 全样%.1f%%'
            % (len(all60), cheap_n, (c60 or 0) * 100, (a60 or 0) * 100, (c120 or 0) * 100, (a120 or 0) * 100))
    except Exception as e:
        log('FATAL', e)
        bt = {'available': False, 'note': '回测数据获取失败，暂不可验证：%s' % e}

    # 写回 li_daxiao.json（不破坏主模块已有字段）
    try:
        d = json.load(open(OUT, encoding='utf-8')) if os.path.exists(OUT) else {}
        d['backtest'] = bt
        with open(OUT, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, allow_nan=False, indent=1)
        log('write backtest ->', OUT, '%.1fs' % (time.time() - t0))
    except Exception as e:
        log('写回失败', e)


if __name__ == '__main__':
    main()
