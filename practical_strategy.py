# -*- coding: utf-8 -*-
"""
实战策略(最高指引 v2) · practical_strategy.py

四大支柱(用户定稿, 2026-08-08):
1. 艾略特波浪阶段研判 -> 操作指引 + 概率(务实阶段引擎, 不精确数浪)
2. 资金判断板块(行业板块资金流) + 板块内最强个股(东财板块成分股接口直连 BK 代码, 按主力净流入取前 N)
3. 入手可行性 + 仓位 + 止盈止损(ATR动态 + 斐波那契回踩区 + 风险预算)
4. 全程概率优先: 只输出 R:R>=1.5 且 概率>=阈值 的候选, 按综合分排序

旧 M/E/A/B/C/D 多档体系已降级为"阅读信息", 本模块是新的选股主引擎。
依赖: sector_flow.json(由 sector_flow.py 生成) 须先于本脚本存在。
"""
import os, json, time, math, urllib.request, urllib.parse
import auto_screener as A   # 复用已验证底层: fetch_kline/calc_atr/wave_stage/calc_rsi/load_industry_map/build_leaders/load_sector_flow

HERE = os.path.dirname(os.path.abspath(__file__))

# ---- 参数 ----
HOT_SECTOR_N   = 8     # 取资金流入最强的 N 个行业板块
PER_SECTOR_TOP = 5     # 每个热点板块经成分股接口直连, 取净流入最强前 N 只(绕开行业名匹配)
MIN_PROB       = 0.45  # 概率优先: 低于此概率不进可操作面板
MIN_RR         = 1.5   # 风险报酬比门槛
CAPITAL_RISK   = 0.02  # 单名最大可亏资本比例(风险预算)
POS_CAP        = 0.35  # 单名仓位上限
STOP_PCT      = A.STOP_PCT   # 0.08

# 波浪阶段 -> 持有期 / 基础概率 / 基础仓位 / 目标收益
WAVE_HOLD  = {'imp3':60,'corr':20,'v':15,'side':20,'down':0,'na':0}
WAVE_PROB  = {'imp3':0.62,'corr':0.58,'v':0.45,'side':0.50,'down':0.30,'na':0.45}
WAVE_POS   = {'imp3':0.30,'corr':0.20,'side':0.12,'v':0.10,'down':0.0,'na':0.10}
WAVE_TP    = {'imp3':0.20,'corr':0.12,'side':0.10,'v':0.10,'down':0.0,'na':0.10}


def clean_nan(o):
    if isinstance(o, dict):  return {k: clean_nan(v) for k, v in o.items()}
    if isinstance(o, list):  return [clean_nan(v) for v in o]
    if isinstance(o, float): return None if (math.isnan(o) or math.isinf(o)) else round(o, 4)
    return o


def load_json(p):
    try:
        return json.load(open(os.path.join(HERE, p), encoding='utf-8'))
    except Exception:
        return None


def name_of(code):
    """轻量解析个股名称(腾讯 qt), 用于补充热点板块市值龙头的显示名。"""
    try:
        pre = 'sh' if code[0] in '69' else 'sz'
        s = A.get('https://qt.gtimg.cn/q=%s%s' % (pre, code))
        parts = s.split('~')
        return parts[1] if len(parts) > 1 and parts[1] else code
    except Exception:
        return code


EM_HDRS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://quote.eastmoney.com/'}


def em_get(u, timeout=25):
    return urllib.request.urlopen(urllib.request.Request(u, headers=EM_HDRS), timeout=timeout).read().decode('utf-8', 'ignore')


def fetch_board_members(board_code, topn=PER_SECTOR_TOP):
    """东财板块成分股接口: 直连板块 BK 代码(fs=b:BKxxxx), 按主力净流入(f62)取前 topn 只。
    彻底绕开之前『个股行业名 ↔ 板块资金名』的脆弱子串匹配 —— 板块成员精确到只, 不再漏健康趋势票。"""
    def fnum(x, d=0.0):
        try:
            return float(x)
        except Exception:
            return d
    u = ('https://push2delay.eastmoney.com/api/qt/clist/get?pn=1&pz=500&po=1&np=1&fltt=2&invt=2'
         '&fid=f62&fs=b:%s&fields=f12,f14,f2,f3,f62,f184'
         % urllib.parse.quote(str(board_code), safe=''))
    try:
        d = json.loads(em_get(u))
        diff = (d.get('data', {}) or {}).get('diff', []) or []
    except Exception as e:
        print('  [warn] 板块 %s 成分股拉取失败: %s' % (board_code, e))
        return []
    if not diff:
        return []
    rows = []
    for r in diff:
        inflow = fnum(r.get('f62'), 0.0) / 1e8
        rows.append({'code': r.get('f12'), 'name': r.get('f14'),
                     'price': fnum(r.get('f2'), 0.0), 'change': fnum(r.get('f3'), 0.0),
                     'inflow': round(inflow, 3), 'net_ratio': fnum(r.get('f184'), 0.0)})
    rows.sort(key=lambda x: -x['inflow'])
    return rows[:topn]


def wave_profile(closes, kd):
    """在 wave_stage 基础上补: 概率 + 斐波那契回踩区。"""
    w = A.wave_stage(closes)
    key = w['key']
    window = closes[-60:]
    hi, lo = max(window), min(window)
    rng = hi - lo
    fib = {
        'swing_hi': round(hi, 3), 'swing_lo': round(lo, 3),
        'retrace_0.382': round(hi - rng * 0.382, 3),
        'retrace_0.5':   round(hi - rng * 0.5, 3),
        'retrace_0.618': round(hi - rng * 0.618, 3),
    }
    return {'key': key, 'label': w['label'], 'op': w['op'],
            'prob': WAVE_PROB.get(key, 0.45),
            'hold_days': w.get('hold', A.HOLD_DAYS), 'fib': fib}


def strength_detail(kd, closes):
    n = len(closes); c = closes[-1]
    ma20 = sum(closes[-20:]) / 20
    ma60 = sum(closes[-60:]) / 60 if n >= 60 else ma20
    ret5  = c / closes[-6]  - 1 if n >= 6  else 0
    ret20 = c / closes[-21] - 1 if n >= 21 else 0
    rsi = A.calc_rsi(closes, 14) or 50
    vols = [k['volume'] for k in kd[-20:]]
    av = sum(vols) / len(vols) if vols else 0
    vratio = (kd[-1]['volume'] / av) if av > 0 else 1
    trend = 1 if (c > ma20 and ma20 >= ma60) else (0 if c > ma20 else -1)
    return {'ret5': round(ret5, 4), 'ret20': round(ret20, 4), 'rsi': round(rsi, 1),
            'vratio': round(vratio, 2), 'ma20': round(ma20, 3),
            'ma60': round(ma60, 3), 'trend': trend, 'price': c}


def entry_zone(wave_key, closes, atr_pct, ma20):
    c = closes[-1]
    if wave_key == 'imp3':                       # 主升浪: 回踩 MA20 加仓区
        lo = round(ma20 * (1 - 0.6 * atr_pct), 3)
        hi = round(ma20 * (1 + 0.4 * atr_pct), 3)
        note = '主升浪回踩 MA20 加仓区, 不追高'
    elif wave_key == 'corr':                     # 调整浪: 斐波那契 0.382~0.618 低吸区
        window = closes[-60:]; hi, lo = max(window), min(window); rng = hi - lo
        lo = round(hi - rng * 0.618, 3)
        hi = round(hi - rng * 0.382, 3)
        note = '调整浪斐波那契回踩低吸区(0.382~0.618)'
    else:                                        # 震荡/末升: 现价附近小仓
        lo = round(c * (1 - 0.03), 3)
        hi = round(c * (1 + 0.01), 3)
        note = '现价附近, 轻仓试探'
    return {'low': lo, 'high': hi, 'note': note}


def composite_prob(wave_key, sector_net, st, is_leader):
    p = WAVE_PROB.get(wave_key, 0.45)
    if sector_net >= 50:   p += 0.06
    elif sector_net >= 15: p += 0.03
    if st['ret20'] > 0.15 and st['trend'] == 1: p += 0.04
    if is_leader: p += 0.03
    return round(min(max(p, 0.35), 0.72), 3)


def build_candidate(c, kd, sector_net, is_leader):
    closes = [k['close'] for k in kd]
    c['atr_pct'] = round(A.calc_atr(kd) or 0.03, 4)
    wave = wave_profile(closes, kd)
    c['wave'] = wave
    c['sector_net'] = sector_net
    c['is_leader'] = is_leader
    if wave['key'] == 'down':
        c['status'] = 'skip'; c['reason'] = '下跌浪(C/大A)回避, 不抄底'
        return c
    st = strength_detail(kd, closes)
    c['strength'] = st
    atr_pct = c['atr_pct']
    # —— 止损/止盈均随 ATR 缩放, 锁住 R:R>=1.5(概率优先: 负期望一律不碰) ——
    k = wave['key']
    if k == 'imp3':
        stop_pct = max(STOP_PCT, 2.0 * atr_pct); tp_pct = max(WAVE_TP['imp3'], 3.0 * atr_pct)
    elif k == 'corr':
        stop_pct = max(STOP_PCT, 2.0 * atr_pct); tp_pct = max(WAVE_TP['corr'], 3.0 * atr_pct)
    elif k == 'side':
        stop_pct = max(0.05, 1.0 * atr_pct);     tp_pct = max(WAVE_TP['side'], 1.5 * atr_pct)
    elif k == 'v':
        stop_pct = max(0.06, 1.5 * atr_pct);     tp_pct = max(WAVE_TP['v'], 2.0 * atr_pct)
    else:
        stop_pct = STOP_PCT; tp_pct = WAVE_TP['na']
    entry = st['price']
    stop_price = round(entry * (1 - stop_pct), 3)
    target_price = round(entry * (1 + tp_pct), 3)
    rr = tp_pct / stop_pct if stop_pct > 0 else 0
    # —— 仓位: 波浪基础 × 板块强度, 再受风险预算与上限约束 ——
    base = WAVE_POS.get(wave['key'], 0.10)
    sec_scale = 1.2 if sector_net >= 50 else (1.0 if sector_net >= 15 else 0.8)
    pos = base * sec_scale
    pos = min(pos, CAPITAL_RISK / stop_pct, POS_CAP)   # 风险预算封顶
    pos = round(pos, 3)
    prob = composite_prob(wave['key'], sector_net, st, is_leader)
    zone = entry_zone(wave['key'], closes, atr_pct, st['ma20'])
    score = round(prob * rr * (1 + min(sector_net, 100) / 200), 4)
    c.update({
        'entry_zone': zone, 'entry': entry, 'price': entry,
        'stop_pct': round(stop_pct, 4), 'stop': stop_price,
        'target_pct': round(tp_pct, 4), 'target': target_price,
        'rr': round(rr, 2), 'position_pct': pos,
        'hold_days': wave['hold_days'], 'prob': prob, 'score': score,
    })
    # —— 概率优先过滤 ——
    if wave['key'] == 'v':
        c['status'] = 'observe'; c['reason'] = '末升浪(5): 分批止盈不追高, 仅观察'
    elif prob < MIN_PROB or rr < MIN_RR or pos < 0.02:
        c['status'] = 'observe'
        c['reason'] = '概率%.0f%%/盈亏比%.1f/仓位%.0f%% 未达门槛' % (prob * 100, rr, pos * 100)
    else:
        c['status'] = 'action'
    c['rationale'] = ('%s | 板块[%s]净流入%+.0f亿 | 20日涨%.0f%% RSI%.0f 量比%.1f | 概率%.0f%% 盈亏比%.1f | '
                      '仓位%.0f%% 止损%.0f%% 目标%.0f%% 持有%d日'
                      % (wave['label'], c['sector'], sector_net, st['ret20'] * 100, st['rsi'],
                         st['vratio'], prob * 100, rr, pos * 100, stop_pct * 100, tp_pct * 100,
                         wave['hold_days']))
    return c


def main():
    t0 = time.time()
    print('=' * 64)
    print('实战策略(波浪阶段 + 资金板块 + 仓位/止损) 开始')
    print('=' * 64)
    sf = load_json('sector_flow.json')
    if not sf:
        print('  [error] 找不到 sector_flow.json, 请先运行 sector_flow.py'); return
    sectors = sf.get('sectors', [])
    hot = [s for s in sectors if s.get('net1', 0) > 0 and s.get('state') in ('持续流入', '短线回流')]
    hot.sort(key=lambda x: -x.get('net1', 0))
    hot = hot[:HOT_SECTOR_N]
    hot_names = {s['name'] for s in hot}
    print('[P1] 热点板块 %d 个: %s' % (len(hot), ' / '.join('%s(%+.0f亿)' % (s['name'], s['net1']) for s in hot)))

    print('[P2] 逐热点板块拉取成分股(东财板块成分股接口, 直连 BK 代码绕开行业名匹配)...')
    cands, seen = [], set()
    for s in hot:
        members = fetch_board_members(s['code'], PER_SECTOR_TOP)
        for m in members:
            code = m['code']
            if not code or code in seen:
                continue
            seen.add(code)
            cands.append({'code': code, 'name': m['name'], 'price': m['price'],
                          'change': m['change'], 'inflow': m['inflow'], 'sector': s['name']})
    print('[P3] 板块∩资金 候选 %d 只 (覆盖 %d 个热点板块)' % (len(cands), len(hot)))

    print('[P4] 行业龙头集(用于 is_leader 概率加成, 可选)...')
    leaders = {}
    try:
        leaders = A.build_leaders(A.load_industry_map())
    except Exception as e:
        print('  [warn] 龙头集载入失败(不影响主流程):', e)

    # 每板块取净流入最强若干截断(去重后边界保护)
    by_sec = {}
    for c in cands:
        by_sec.setdefault(c['sector'], []).append(c)
    trimmed = []
    for s, lst in by_sec.items():
        lst.sort(key=lambda x: -(x.get('inflow', 0)))
        trimmed += lst[:PER_SECTOR_TOP]
    cands = trimmed
    print('     截断后 %d 只 (每板块≤%d)' % (len(cands), PER_SECTOR_TOP))

    # 逐只拉K线 -> 波浪 + ATR + 强度 + 仓位
    results = []
    for c in cands:
        kd = A.fetch_kline(c['code'])
        if not kd or len(kd) < 60:
            continue
        sn = next((s['net1'] for s in hot if s['name'] == c['sector']), 0)
        is_lead = bool(leaders.get(c['code'], {}).get('is_leader'))
        results.append(build_candidate(c, kd, sn, is_lead))
        time.sleep(0.02)

    actions = [r for r in results if r.get('status') == 'action']
    observes = [r for r in results if r.get('status') in ('observe', 'skip')]
    actions.sort(key=lambda x: -x.get('score', 0))
    observes.sort(key=lambda x: -x.get('score', 0))

    picked = {s: [r['code'] for r in actions if r['sector'] == s] for s in hot_names}
    out = {
        'generated': time.strftime('%Y-%m-%d %H:%M'),
        'source_note': '最高指引v2: 波浪阶段引擎(不精确数浪) + 资金判板块∩主力净流入最强个股 + ATR/斐波那契止损止盈 + 概率优先(R:R≥%.1f, 概率≥%.0f%%)。旧M/E/A/B/C/D仅作阅读信息。'
                       % (MIN_RR, MIN_PROB * 100),
        'params': {'hot_sector_n': HOT_SECTOR_N, 'per_sector_top': PER_SECTOR_TOP,
                   'min_prob': MIN_PROB, 'min_rr': MIN_RR, 'capital_risk': CAPITAL_RISK, 'pos_cap': POS_CAP},
        'market': sf.get('market', {}),
        'hot_sectors': [{'name': s['name'], 'net1': s['net1'], 'net5': s.get('net5'),
                         'state': s['state'], 'rank': s.get('rank'), 'picked': picked.get(s['name'], [])}
                        for s in hot],
        'candidates': actions,   # 可操作
        'observe': observes,     # 观察/回避
        'summary': {
            'hot_sectors': len(hot), 'candidates_total': len(results),
            'action': len(actions), 'observe': len(observes),
            'avg_prob': round(sum(r['prob'] for r in actions) / len(actions), 3) if actions else 0,
            'avg_rr': round(sum(r['rr'] for r in actions) / len(actions), 2) if actions else 0,
            'top_sector': max(hot, key=lambda s: s['net1'])['name'] if hot else None,
        },
    }
    json.dump(clean_nan(out), open(os.path.join(HERE, 'practical_strategy.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, allow_nan=False)
    print('\n✅ 已保存 practical_strategy.json  (可操作 %d / 观察 %d, 用时 %.0fs)'
          % (len(actions), len(observes), time.time() - t0))
    if actions:
        print('--- 可操作候选(按综合分) ---')
        for r in actions[:10]:
            print('  %s %s [%s] 概率%.0f%% R:R%.1f 仓位%.0f%% 止损%.0f%% 目标%.0f%% %s'
                  % (r['code'], r['name'], r['sector'], r['prob'] * 100, r['rr'],
                     r['position_pct'] * 100, r['stop_pct'] * 100, r['target_pct'] * 100, r['wave']['label']))


if __name__ == '__main__':
    main()
