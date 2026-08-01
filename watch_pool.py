# -*- coding: utf-8 -*-
"""
watch_pool.py — 观察池 / 自我纠正账本

作用：把自动选股「建议买入(A类)」名单里输出的标的，自动纳入观察池，
      并在之后每一次运行时追踪「自输出以来的走向」，判断是否「符合预期」。
      这是把「纸面回测」闭环成「实盘验证」的自我纠正机制。

逻辑：
  1) 摄入：读 auto_screen_result.json 的 A 名单，把尚未在观察的新标的
     记入账本（入场日 = 信号生成日，入场价 = 信号时价格）。
  2) 追踪：对每个「持有中」标的，取最新收盘价算收益率，
     按 止盈15% / 止损8% / 持有满40日 结算状态，并给「符合/不符/待观察」结论。
  3) 聚合：统计真实命中率、平均收益，与回测基线(胜率65.5% / 均值+5.9%)对比，
     输出 vs_backtest（高于/接近/低于回测）。

持久化：写入 watch_pool.json（账本即视图）。云端工作流会 git commit+push，
        故跨日累积；本地自动化在磁盘累积。

依赖：仅 urllib + json（腾讯K线可沙箱取）。
"""
import json, time, os, math, urllib.request, ssl

HERE = os.path.dirname(os.path.abspath(__file__))
POOL = os.path.join(HERE, 'watch_pool.json')
AUTO = os.path.join(HERE, 'auto_screen_result.json')

CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
HDR = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://quote.eastmoney.com/'}

TP = 0.15      # 止盈阈值（与 auto_screener 一致）
STOP = -0.08   # 止损阈值
HOLD_MAX = 40  # 最长持有日（与回测持有期一致）
BASE_WIN = 0.655   # 回测基线胜率
BASE_AVG = 0.059   # 回测基线均值

def log(*a):
    print('[观察池]', *a); sys.stdout.flush()

import sys

def fetch_last_close(code):
    tcode = ('sh' if code[0] in '69' else 'sz') + code
    url = 'https://ifzq.gtimg.cn/appstock/app/kline/kline?_var=k&param=%s,day,,,12' % tcode
    for _ in range(3):
        try:
            raw = urllib.request.urlopen(urllib.request.Request(url, headers=HDR), timeout=20).read().decode('utf-8', 'ignore')
            raw = raw[raw.index('=') + 1:]
            d = json.loads(raw)
            kd = d.get('data', {}).get(tcode, {}).get('day') or d.get('data', {}).get(tcode, {}).get('qfqday')
            if kd:
                return float(kd[-1][2]), kd[-1][0]
        except Exception as e:
            time.sleep(0.15); last_e = e
    log('  现价获取失败:', code, last_e if 'last_e' in dir() else '')
    return None, None

def load_pool():
    try:
        return json.load(open(POOL, encoding='utf-8'))
    except Exception:
        return {'items': [], 'updated': ''}

def ingest(items, auto):
    """把 auto 的 A 名单里尚未在观察的新标的入账。返回新增数。"""
    opened = {it['code'] for it in items if it.get('status') == '持有中'}
    gen = auto.get('generated', '')[:10]
    added = 0
    for r in auto.get('A', []):
        code = str(r.get('code', ''))
        if not code:
            continue
        if code in opened:
            continue  # 已有一个未平仓的观察
        try:
            price = float(r.get('price') or 0)
        except Exception:
            price = 0.0
        items.append({
            'code': code, 'name': str(r.get('name', '')),
            'entry_date': gen, 'entry_price': price,
            'last_date': '', 'last_price': None, 'return': None,
            'hold_days': 0, 'status': '持有中', 'expectation': '待观察',
        })
        opened.add(code)
        added += 1
    return added

def track(items):
    """更新所有持有中标的的现价/收益/状态。返回更新数。"""
    updated = 0
    for it in items:
        if it.get('status') != '持有中':
            continue
        cur, dt = fetch_last_close(it['code'])
        if cur is None:
            continue
        it['last_price'] = cur
        it['last_date'] = dt or time.strftime('%Y-%m-%d')
        ep = it.get('entry_price') or 0
        if ep > 0:
            it['return'] = round(cur / ep - 1, 4)
        try:
            d0 = time.mktime(time.strptime(it['entry_date'], '%Y-%m-%d'))
            it['hold_days'] = max(0, int((time.time() - d0) / 86400))
        except Exception:
            it['hold_days'] = 0
        ret = it.get('return')
        if ret is None:
            continue
        if ret >= TP:
            it['status'] = '止盈达标'; it['expectation'] = '符合预期'
        elif ret <= STOP:
            it['status'] = '触止损'; it['expectation'] = '不符预期'
        elif it['hold_days'] >= HOLD_MAX:
            it['status'] = '持有到期'; it['expectation'] = '符合预期' if ret > 0 else '不符预期'
        else:
            it['status'] = '持有中'; it['expectation'] = '偏符合' if ret > 0 else '待观察'
        updated += 1
    return updated

def aggregate(items):
    closed = [it for it in items if it.get('status') != '持有中']
    n = len(items); nc = len(closed); no = n - nc
    tp = sum(1 for it in closed if it['status'] == '止盈达标')
    st = sum(1 for it in closed if it['status'] == '触止损')
    ex = sum(1 for it in closed if it['status'] == '持有到期')
    wins = sum(1 for it in closed if it.get('expectation') == '符合预期')
    win_rate = (wins / nc) if nc else None
    rets = [it['return'] for it in closed if isinstance(it.get('return'), (int, float))]
    avg_ret = (sum(rets) / len(rets)) if rets else None
    if win_rate is not None:
        if win_rate > BASE_WIN + 0.03:
            vs = '高于回测'
        elif win_rate < BASE_WIN - 0.03:
            vs = '低于回测'
        else:
            vs = '接近回测'
    else:
        vs = '样本不足'
    return {
        'total': n, 'closed': nc, 'open': no,
        'tp': tp, 'stop': st, 'expired': ex,
        'win': wins,
        'win_rate': round(win_rate, 3) if win_rate is not None else None,
        'avg_return': round(avg_ret, 4) if avg_ret is not None else None,
        'vs_backtest': vs,
    }

def main():
    log('开始更新观察池 ...')
    pool = load_pool()
    items = pool.get('items', [])
    before = len(items)

    if os.path.exists(AUTO):
        auto = json.load(open(AUTO, encoding='utf-8'))
        added = ingest(items, auto)
        log('摄入新标的:', added, '只')
    else:
        log('未找到 auto_screen_result.json，跳过摄入')

    updated = track(items)
    log('追踪更新持仓标的:', updated, '只')
    stats = aggregate(items)
    log('聚合: 总 %d / 已平仓 %d / 持仓 %d | 命中率 %s | 均值 %s | %s' % (
        stats['total'], stats['closed'], stats['open'],
        ('%.1f%%' % (stats['win_rate'] * 100)) if stats['win_rate'] is not None else '—',
        ('%+.2f%%' % (stats['avg_return'] * 100)) if stats['avg_return'] is not None else '—',
        stats['vs_backtest']))

    out = {
        'updated': time.strftime('%Y-%m-%d %H:%M'),
        'baseline': {'win': BASE_WIN, 'avg': BASE_AVG},
        'stats': stats,
        'items': items[-80:],   # 视图最多保留最近80条，账本持久在文件
    }
    # NaN 清洗
    def clean(o):
        if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list): return [clean(v) for v in o]
        if isinstance(o, float) and (math.isnan(o) or math.isinf(o)): return None
        return o
    out = clean(out)
    json.dump(out, open(POOL, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, allow_nan=False)
    log('已写入 watch_pool.json（账本%d条，视图展示%d条）' % (len(items), len(out['items'])))

if __name__ == '__main__':
    main()
