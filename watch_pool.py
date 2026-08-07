# -*- coding: utf-8 -*-
"""
watch_pool.py — 观察池 / 自我纠正账本

作用：把自动选股「建议买入(A类)」名单里输出的标的，自动纳入观察池，
      并在之后每一次运行时追踪「自输出以来的走向」，判断是否「符合预期」。
      这是把「纸面回测」闭环成「实盘验证」的自我纠正机制。

逻辑（滚动动态池 · 一进一出）：
  1) 追踪：每天更新所有在池标的的现价/至今累计收益/持有天数。
     达到第 EXIT_DAYS(11) 天即自动「清出」，记录清出时收益(exit_return)为结算点；
     清出后【仍持续更新现价】，以便对比「按纪律出场」与「一直持有」的差距。
  2) 每日入选：每天(按日期去重)从 auto_screen_result.json 的 A 名单里挑
     「策略排序最靠前的 1 只」(wolf2强化/好公司优先 → 目标盈利率高 → 贪婪更低=更低位)，
     且仅当活跃格 < POOL_MAX(10) 时才补入；写入 last_pick_date 防同日重复选。
     ── 稳态：始终保持 10 只在场，每天约 1 只满 11 天清出、1 只新入选，一进一出。
  3) 聚合：以「已清出」标的的结算收益为命中基准，统计真实胜率/均值，
     与回测基线(胜率65.5% / 均值+5.9%)对比，输出 vs_backtest。

持久化：写入 watch_pool.json。云端工作流 git commit+push，故跨日累积；本地在磁盘累积。

依赖：仅 urllib + json（腾讯K线可沙箱取）。
"""
import json, time, os, math, urllib.request, ssl

HERE = os.path.dirname(os.path.abspath(__file__))
POOL = os.path.join(HERE, 'watch_pool.json')
AUTO = os.path.join(HERE, 'auto_screen_result.json')

CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
HDR = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://quote.eastmoney.com/'}

TP = 0.15      # 止盈阈值（仅作信息性标注：持有期间是否触止盈）
STOP = -0.08   # 止损阈值（仅作信息性标注：持有期间是否触止损）
# 2026-08-07 依多持有期网格回测校准：10 日是最差持有期(胜52.9%/均+1.47%)，20 日才是峰值
# (胜61.5%/均+4.11%)。原来第 11 天结算 = 一直在策略最弱的点上量它，必然长期"低于回测"。
# 改为 20 日持有 / 第 21 天结算；池格同步扩到 20，维持"每日 1 进 1 出"的稳态。
POOL_MAX = 20      # 动态池格数：始终保持最多 20 只在场（=每日1只 × 20日持有）
HOLD_DAYS = 20     # 计划持有天数（回测最优）
EXIT_DAYS = 21     # 达到该持有天数即清出（第 21 天出局）→ 维持一进一出
BASE_WIN = 0.615   # 回测基线胜率（S1 小狼逆向 · 20日持有 · n=174）
BASE_AVG = 0.0411  # 回测基线均值（同上）

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

def pick_daily(items, auto, today, meta):
    """每天(按日期去重)从 M(强势顺势) + E(热点早期突破) + A(低位低吸) 名单挑「策略排序最靠前的 1 只」补入动态池。
    同时纳入三档，使观察池能自然积累 M vs E vs A 的真实盈亏，供「不同策略相互对比」之用。
    仅当活跃格 < POOL_MAX 才补；返回入选的 item 或 None。"""
    if meta.get('last_pick_date') == today:
        return None  # 今天已经选过，防同日重复选
    active_codes = {it['code'] for it in items if it.get('status') == '持有中'}
    if len(active_codes) >= POOL_MAX:
        return None  # 满格，等清出腾位
    cands = []
    for tier in ('M', 'E', 'A'):
        for r in auto.get(tier, []):
            code = str(r.get('code', ''))
            if not code or code in active_codes:
                continue
            cands.append((r, tier))
    if not cands:
        return None
    # 排序：wolf2强化 > 档位(M优先于A) > 好公司 > 确定性conviction高
    def sc(x):
        r, tier = x
        tp = r.get('trade_plan') or {}
        conv = tp.get('conviction', 0) or 0
        w2 = 0 if (r.get('wolf2') or {}).get('pass') else 1
        good = 0 if (r.get('fund') or {}).get('good', False) else 1
        tier_rank = {'M': 0, 'E': 1, 'A': 2}.get(tier, 1)
        return (w2, tier_rank, good, -conv)
    cands.sort(key=sc)
    r, tier = cands[0]
    code = str(r.get('code', ''))
    try:
        price = float(r.get('price') or 0)
    except Exception:
        price = 0.0
    tp = (r.get('trade_plan') or {})
    item = {
        'code': code, 'name': str(r.get('name', '')), 'template': tier,
        'entry_date': today, 'entry_price': price,
        'last_date': '', 'last_price': None, 'return': None,
        'hold_days': 0, 'status': '持有中', 'expectation': '待观察',
        'plan_exit_days': EXIT_DAYS,   # 冻结入池时的结算期，日后调参不追溯污染样本
        'is_leader': bool(r.get('is_leader')), 'sector': str(r.get('sector', '')),
        'target_pct': (tp.get('target_pct', 0) or 0),
        'side': (tp.get('side', '') or ''),
        'note': '',
    }
    items.append(item)
    return item

def track(items):
    """更新所有在池标的的现价/至今累计收益/持有天数。
    持有中标的达到第 EXIT_DAYS(11) 天即自动「清出」，记录 exit_return(结算点收益)；
    清出后【仍持续更新现价】，以便对比「按纪律出场」与「一直持有」的差距。"""
    updated = 0
    now = time.time()
    for it in items:
        if it.get('status') == '已移除':
            continue
        cur, dt = fetch_last_close(it['code'])
        if cur is None:
            continue
        it['last_price'] = cur
        it['last_date'] = dt or time.strftime('%Y-%m-%d')
        ep = it.get('entry_price') or 0
        if ep > 0:
            it['return'] = round(cur / ep - 1, 4)   # 至今累计收益
        try:
            d0 = time.mktime(time.strptime(it['entry_date'], '%Y-%m-%d'))
            it['hold_days'] = max(0, int((now - d0) / 86400))
        except Exception:
            it['hold_days'] = 0
        ret = it.get('return')
        if it.get('status') == '持有中':
            # 每条记录带自己的结算期：改全局常量不会追溯改写在途样本（老样本仍按入池时的 11 天结算）
            exit_at = it.get('plan_exit_days') or EXIT_DAYS
            if it['hold_days'] >= exit_at:
                # 时间到期清出：以当前收益为结算点（动态池的「出场」=满持有期）
                it['exit_date'] = it['last_date']; it['exit_return'] = ret
                it['exit_at_days'] = exit_at
                it['status'] = '已清出'; it['expectation'] = '已清出'
            else:
                # 信息性标注（不提前出场，保持一进一出节奏）
                if ret is None:
                    it['expectation'] = '待观察'
                elif ret >= TP:
                    it['expectation'] = '达标·触止盈'
                elif ret <= STOP:
                    it['expectation'] = '破位·触止损'
                elif ret > 0:
                    it['expectation'] = '偏符合'
                else:
                    it['expectation'] = '偏不符'
        # 已清出的仍持续更新「至今累计」，不重复结算
        updated += 1
    return updated

def aggregate(items, meta):
    live = [it for it in items if it.get('status') != '已移除']
    active = [it for it in live if it.get('status') == '持有中']
    cleared = [it for it in live if it.get('status') == '已清出']   # 已清出 = 结算完毕，命中基准
    n = len(live); na = len(active); nc = len(cleared)
    # 命中率/均值以「清出时结算收益」(exit_return) 为基准，不受后续追踪干扰
    wins = sum(1 for it in cleared if (it.get('exit_return') or 0) > 0)
    win_rate = (wins / nc) if nc else None
    rets = [it.get('exit_return') for it in cleared
            if isinstance(it.get('exit_return'), (int, float))]
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
    # 分档对比：M(强势顺势) vs A(低位低吸) —— 保留之前策略、相互对比盈亏
    def _tier_stats(sub):
        n2 = len(sub)
        if not n2:
            return {'n': 0, 'win_rate': None, 'avg_return': None}
        w = sum(1 for it in sub if (it.get('exit_return') or 0) > 0)
        rr = [it['exit_return'] for it in sub if isinstance(it.get('exit_return'), (int, float))]
        return {'n': n2, 'win_rate': round(w / n2, 3),
                'avg_return': round(sum(rr) / len(rr), 4) if rr else None}
    m_sub = [it for it in cleared if (it.get('template') or 'A') == 'M']
    e_sub = [it for it in cleared if (it.get('template') or 'A') == 'E']
    a_sub = [it for it in cleared if (it.get('template') or 'A') == 'A']
    by_tier = {'M': _tier_stats(m_sub), 'E': _tier_stats(e_sub), 'A': _tier_stats(a_sub)}
    return {
        'total': n, 'active': na, 'cleared': nc, 'win': wins,
        'win_rate': round(win_rate, 3) if win_rate is not None else None,
        'avg_return': round(avg_ret, 4) if avg_ret is not None else None,
        'vs_backtest': vs,
        'by_tier': by_tier,
        'pool_max': POOL_MAX, 'hold_days': HOLD_DAYS, 'exit_days': EXIT_DAYS,
        'today_picked': bool(meta.get('today_picked')),
        'last_pick_date': meta.get('last_pick_date', ''),
        'last_pick_name': meta.get('last_pick_name', ''),
    }

def main():
    log('开始更新动态观察池 ...')
    pool = load_pool()
    items = pool.get('items', [])
    today = time.strftime('%Y-%m-%d')
    meta = {
        'last_pick_date': pool.get('last_pick_date', ''),
        'last_pick_code': pool.get('last_pick_code', ''),
        'last_pick_name': pool.get('last_pick_name', ''),
        'today_picked': False,
    }

    # 1) 先追踪：更新现价/至今收益，并在满 11 天时清出
    updated = track(items)
    log('追踪更新:', updated, '只')

    # 2) 每日一只入选（日期去重 + 满格不补）
    if os.path.exists(AUTO):
        auto = json.load(open(AUTO, encoding='utf-8'))
        picked = pick_daily(items, auto, today, meta)
        if picked:
            tgt = (picked.get('target_pct') or 0) * 100
            log('今日入选: %s %s ｜ 策略目标盈利率 %.1f%%' % (picked['name'], picked['code'], tgt))
            meta['today_picked'] = True
            meta['last_pick_date'] = today
            meta['last_pick_code'] = picked['code']
            meta['last_pick_name'] = picked['name']
        else:
            log('今日无新入选（已满格 / 无候选 / 已选过）')
    else:
        log('未找到 auto_screen_result.json，跳过入选')

    stats = aggregate(items, meta)
    act = stats['active']; clr = stats['cleared']
    log('聚合: 在场 %d/%d ｜ 已清出 %d | 命中率 %s | 均值 %s | %s' % (
        act, stats['pool_max'], clr,
        ('%.1f%%' % (stats['win_rate'] * 100)) if stats['win_rate'] is not None else '—',
        ('%+.2f%%' % (stats['avg_return'] * 100)) if stats['avg_return'] is not None else '—',
        stats['vs_backtest']))

    out = {
        'updated': time.strftime('%Y-%m-%d %H:%M'),
        'baseline': {'win': BASE_WIN, 'avg': BASE_AVG},
        'stats': stats,
        'items': items[-300:],
        'last_pick_date': meta['last_pick_date'],
        'last_pick_code': meta['last_pick_code'],
        'last_pick_name': meta['last_pick_name'],
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
