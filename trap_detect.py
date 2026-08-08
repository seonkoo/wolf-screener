# -*- coding: utf-8 -*-
"""个股分时陷阱识别 + 量价关系解读 —— 分析引擎
========================================================
数据源(沙箱可达):
  - 分时: web.ifzq.gtimg.cn/appstock/app/minute/query?code=XXX  (仅最新交易日, &date 被忽略)
        每条 = "HHMM price 累计成交量(手) 累计成交额(元)"  (无均价字段, 自算 VWAP)
  - 日K: ifzq.gtimg.cn/appstock/app/kline/kline?param=XXX,day,,,12  (取昨收 + 前5日均量算量比)

两层判定(透明、可解释, 非黑箱):
  【第一层·陷阱判定】诱多 / 骗筹码 / 真实走强 / 真实走弱 / 震荡中性
    诱多(拉高诱多/诱多出货): 先拉(冲高) -> 量价背离 -> 回落 -> 收在均价线下方, 把追高者套在均价之上。
    骗筹码(洗盘震仓): 先跌(低开/盘中小杀) -> 长下影 -> 收回 -> 收在均价线上方, 把恐慌者洗下车后自己捡筹。
  【第二层·量价关系】放量上涨/缩量上涨/放量滞涨/放量下跌/缩量下跌/放量震荡 等, 并给交易含义
    量比 = 今日量 ÷ 前5日均量 (>1.5 放量, <0.7 缩量)
    量能方向 = 涨段量 ÷ (涨段量+跌段量) (>0.55 买盘主动, <0.45 卖盘主动)
  两层互相印证: 放量滞涨/缩量上涨 → 强化诱多; 缩量下跌/恐慌见底 → 强化骗筹码(洗盘)。

  注意: 单日分时无法证明「意图」(需结合趋势/消息/板块), 故本工具只给「嫌疑/特征 + 量价解读」, 不给定罪。
"""
import json, ssl, urllib.request, math
from datetime import datetime

CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://gu.qq.com/'}


def get(u, t=20):
    return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=t, context=CTX).read().decode('utf-8', 'ignore')


def fetch_minute(code):
    """返回 {date, name, rows:[{t, price, vol, amt}]}  t=距09:30的分钟数(0..240)"""
    url = "https://web.ifzq.gtimg.cn/appstock/app/minute/query?code=%s" % code
    j = json.loads(get(url))['data'][code]
    d = j['data']
    name = ''
    qt = j.get('qt', {}).get(code)
    if isinstance(qt, list) and len(qt) > 1:
        name = qt[1]
    rows = []
    for s in d['data']:
        parts = s.split()
        hhmm = parts[0]
        h = int(hhmm[:2]); m = int(hhmm[2:])
        # 距09:30分钟数 (午休11:30-13:00不连续, 用交易日分钟序号近似: 上午0..120, 下午121..240)
        if h < 12:
            t = (h - 9) * 60 + (m - 30)
        else:
            t = 120 + (h - 13) * 60 + m
        price = float(parts[1])
        vol = float(parts[2]) * 100          # 手 -> 股
        amt = float(parts[3])
        rows.append({'t': t, 'price': price, 'vol': vol, 'amt': amt})
    return {'date': d.get('date'), 'name': name, 'rows': rows}


def fetch_dayctx(code, target_date):
    """取 target_date 的昨收 + 当日量 + 前5日均量(均换算成股, 与分时口径一致)
    返回 {prev_close, today_vol, avg_prior_vol}
    """
    url = "https://ifzq.gtimg.cn/appstock/app/kline/kline?_var=k&param=%s,day,,,12" % code
    raw = get(url); raw = raw[raw.index('=') + 1:]
    node = json.loads(raw).get('data', {}).get(code, {})
    day = node.get('day') or node.get('qfqday') or []
    # day 行: [date, open, close, high, low, volume(手), ...]
    bars = [(r[0], float(r[2]), float(r[5])) for r in day if r]
    bars.sort(key=lambda x: x[0])
    if not bars:
        return {'prev_close': None, 'today_vol': None, 'avg_prior_vol': None}

    # 找 target_date 当日 bar (含回退: 取 <= target 的最后一根)
    today = None
    for b in bars:
        if b[0] <= target_date:
            today = b
    # 前5日(严格早于 today 的 date)
    prior = [b for b in bars if today and b[0] < today[0]]
    prior = prior[-5:]
    avg_prior_vol = (sum(b[2] for b in prior) / len(prior) * 100) if prior else None  # 手->股
    today_vol = today[2] * 100 if today else None                                    # 手->股
    # 昨收: today 之前一根收盘
    prev = prior[-1][1] if prior else (bars[0][1] if bars else None)
    return {'prev_close': prev, 'today_vol': today_vol, 'avg_prior_vol': avg_prior_vol}


def volprice_state(day_chg, vol_ratio, vol_bias, above_vwap, lower_shadow):
    """量价关系状态机: 返回 (state_label, impl_teach)"""
    up = day_chg > 0.005
    dn = day_chg < -0.005
    if vol_ratio is None:
        return ('量能未知', '无法取得近5日均量，量比暂不可计算。')
    if vol_ratio > 1.5:          # 放量
        if up:
            if vol_bias >= 0.55 and above_vwap:
                return ('放量上涨·量价齐升',
                        '上涨伴随买盘主动放量、价在均价线上方，属资金真实推动的走强/突破，可靠性较高。')
            if vol_bias < 0.45:
                return ('放量滞涨·高位派发',
                        '价在涨但量能偏向卖盘（量价背离/放量不涨），多为对倒拉高出货，是诱多的典型温床。')
            return ('放量上涨·分歧',
                    '上涨但多空分歧大（涨段跌段都在放量），需看收盘能否守住均价线确认方向。')
        if dn:
            if vol_bias < 0.45:
                if lower_shadow > 0.45:
                    return ('放量下跌·恐慌见底',
                            '低位放巨量杀跌后长下影收回，常是恐慌盘出尽（最后一跌），关注是否止跌企稳。')
                return ('放量下跌·抛压释放',
                        '卖盘主动放量下跌：若在高位=出货加速；若在低位长下影=恐慌见底信号。')
            return ('放量下跌·对倒',
                    '下跌中买盘也放量，可能是对倒制造恐慌（洗盘）或资金博弈，需结合位置判断。')
        return ('放量震荡·分歧加大', '平盘放量，多空分歧显著，方向待选，切勿追涨杀跌。')
    if vol_ratio < 0.7:          # 缩量
        if up:
            return ('缩量上涨·无量空涨',
                    '上涨却没量，动能不足/惜售，若已处高位需防回落（诱多前兆）。')
        if dn:
            return ('缩量下跌·洗盘阴跌',
                    '下跌缩量，抛压减轻，多为洗盘或阴跌，而非恐慌性杀跌。')
        return ('缩量横盘·观望', '量能萎缩横盘，资金观望，等待方向选择。')
    # 平量
    if up and above_vwap:
        return ('平量上涨·稳健', '温和放量上涨、价在均价线上，走势稳健健康。')
    if dn:
        return ('平量下跌·阴跌', '平量阴跌，趋势偏弱但无恐慌，多看少动。')
    return ('平量横盘', '多空均衡，方向不明。')


def analyze(code):
    md = fetch_minute(code)
    rows = md['rows']
    if not rows:
        return {'error': '无分时数据'}
    ctx = fetch_dayctx(code, md['date'])
    prev = ctx['prev_close']
    if not prev:
        return {'error': '无昨收'}

    prices = [r['price'] for r in rows]
    opens = prices[0]; close = prices[-1]
    high = max(prices); low = min(prices)
    high_i = prices.index(high); low_i = prices.index(low)

    # VWAP 序列
    vwap = []
    for r in rows:
        vwap.append(r['amt'] / r['vol'] if r['vol'] > 0 else r['price'])

    # 时间切分 (午休处理: 用 t 字段, 上午 t<=120, 下午 t>120)
    mid = next((i for i, r in enumerate(rows) if r['t'] > 120), len(rows))
    morning_vol = sum(r['vol'] for r in rows[:mid])
    afternoon_vol = sum(r['vol'] for r in rows[mid:])
    total_vol = morning_vol + afternoon_vol
    morning_share = morning_vol / total_vol if total_vol else 0
    # 尾盘30分钟
    n = len(rows)
    tail = rows[-30:] if n >= 30 else rows
    tail_vol = sum(r['vol'] for r in tail)
    tail_vol_share = tail_vol / total_vol if total_vol else 0
    tail_chg = (rows[-1]['price'] - rows[-30]['price']) / rows[-30]['price'] if n >= 30 and rows[-30]['price'] else 0

    gap = (opens - prev) / prev
    day_chg = (close - prev) / prev
    intraday_range = (high - low) / prev
    spike_up = (high - opens) / opens            # 相对开盘的冲高幅度
    dip_down = (low - opens) / opens             # 相对开盘的杀跌幅度(负值)
    fade_from_high = (high - close) / high       # 从最高点回落比例
    rebound_from_low = (close - low) / low       # 从最低点回收比例
    above_vwap_close = close > vwap[-1]
    vwap_close = vwap[-1]
    above_vwap_time = sum(1 for p, v in zip(prices, vwap) if p > v) / n
    lower_shadow = (close - low) / (high - low) if (high - low) > 0 else 0
    upper_shadow = (high - close) / (high - low) if (high - low) > 0 else 0

    # ---- 量能方向: 按分钟涨跌归集成交量 ----
    vol_up = vol_down = vol_flat = 0.0
    for i in range(1, n):
        dv = rows[i]['vol'] - rows[i - 1]['vol']
        if dv <= 0:
            continue
        if prices[i] > prices[i - 1]:
            vol_up += dv
        elif prices[i] < prices[i - 1]:
            vol_down += dv
        else:
            vol_flat += dv
    vol_bias = (vol_up / (vol_up + vol_down)) if (vol_up + vol_down) > 0 else 0.5

    # ---- 量比: 今日量 ÷ 前5日均量 ----
    vol_ratio = None
    if ctx['today_vol'] and ctx['avg_prior_vol']:
        vol_ratio = ctx['today_vol'] / ctx['avg_prior_vol']

    feats = dict(gap_pct=gap*100, day_chg_pct=day_chg*100, intraday_range_pct=intraday_range*100,
                 spike_up_pct=spike_up*100, dip_down_pct=dip_down*100,
                 fade_from_high_pct=fade_from_high*100, rebound_from_low_pct=rebound_from_low*100,
                 above_vwap=above_vwap_close, vwap_close=vwap_close, vwap_pos_time=above_vwap_time*100,
                 morning_vol_share=morning_share*100, tail_vol_share=tail_vol_share*100,
                 tail_chg_pct=tail_chg*100, lower_shadow=lower_shadow, upper_shadow=upper_shadow,
                 high_i=high_i, low_i=low_i, n=n, prev_close=prev, open=opens, close=close,
                 high=high, low=low, date=md['date'], name=md['name'],
                 vol_ratio=round(vol_ratio, 2) if vol_ratio else None, vol_bias=round(vol_bias, 3))

    # -------- 评分 (透明规则) --------
    evidence = []
    # 诱多: 冲高 + 回落 + 收在均价下
    lure = 0.0
    if spike_up > 0.012:
        lure += 1.0; evidence.append("盘中冲高 +%.1f%% (相对开盘)" % (spike_up*100))
    if fade_from_high > 0.5 and spike_up > 0.012:
        lure += 1.5; evidence.append("冲高后回落 %.0f%% 涨幅被吞 (高位追入者被套)" % (fade_from_high*100))
    elif fade_from_high > 0.35 and spike_up > 0.02:
        lure += 0.8; evidence.append("冲高后明显回落 %.0f%%" % (fade_from_high*100))
    if not above_vwap_close and spike_up > 0.012:
        lure += 1.2; evidence.append("收盘价 %.2f 低于均价线 %.2f (追高者多数套在均价之上)" % (close, vwap_close))
    if tail_chg > 0.008 and not above_vwap_close:
        lure += 0.6; evidence.append("尾盘急拉 +%.1f%% 但全天仍收弱 (粉饰收盘嫌疑)" % (tail_chg*100))
    if upper_shadow > 0.45 and spike_up > 0.015:
        lure += 0.6; evidence.append("长上影(上影占振幅 %.0f%%): 上方抛压重" % (upper_shadow*100))

    # 骗筹码: 低开/盘跌 + 收回 + 收在均价上
    shake = 0.0
    if gap < -0.008 or dip_down < -0.012:
        shake += 1.0; evidence.append("低开/盘中小幅杀跌 %.1f%% (制造恐慌)" % (min(gap, dip_down)*100))
    if rebound_from_low > 0.015 and (close > opens or above_vwap_close):
        shake += 1.5; evidence.append("从最低点回收 +%.1f%% 且收回开盘/均价之上 (恐慌盘被洗后收复)" % (rebound_from_low*100))
    if lower_shadow > 0.45 and (close > opens or above_vwap_close):
        shake += 0.8; evidence.append("长下影(下影占振幅 %.0f%%): 下方有承接、低点未确认" % (lower_shadow*100))
    if above_vwap_close and day_chg >= 0:
        shake += 0.6; evidence.append("收在均价线之上且日线不跌 (洗盘后资金收回)")

    # -------- 第二层: 量价关系 (互相印证) --------
    state, impl = volprice_state(day_chg, vol_ratio, vol_bias, above_vwap_close, lower_shadow)
    feats['volprice_state'] = state
    if vol_ratio is not None:
        vr_txt = "量比 %.2f" % vol_ratio
        if vol_ratio > 1.5:
            vr_txt += "(放量)"
        elif vol_ratio < 0.7:
            vr_txt += "(缩量)"
        else:
            vr_txt += "(平量)"
        evidence.append("%s | 量能方向: %s (涨段量占比%.0f%%)" %
                        (vr_txt, "买盘主动" if vol_bias >= 0.55 else ("卖盘主动" if vol_bias < 0.45 else "多空均衡"),
                         vol_bias*100))
    # 量价关系对陷阱判定的印证
    if state in ('放量滞涨·高位派发', '缩量上涨·无量空涨'):
        lure += 1.5; evidence.append("量价关系判定「%s」→ 强化诱多嫌疑" % state)
    elif state in ('放量下跌·恐慌见底', '缩量下跌·洗盘阴跌', '放量下跌·对倒'):
        shake += 1.2; evidence.append("量价关系判定「%s」→ 偏向洗盘/骗筹码" % state)

    # 日内形态 (易读标签)
    early = n * 0.3
    if high_i < early and close < opens:
        shape = '冲高回落'
    elif low_i < early and close > opens:
        shape = '下探回升(洗盘)'
    elif gap > 0.01 and close < opens:
        shape = '高开低走'
    elif gap < -0.01 and close > opens:
        shape = '低开高走'
    else:
        shape = '平开震荡'

    # 真实强弱
    genuine_up = day_chg > 0.01 and above_vwap_close and upper_shadow < 0.4 and spike_up <= 0.03
    genuine_down = day_chg < -0.01 and not above_vwap_close and lower_shadow < 0.4

    # 裁决
    if lure >= 2.5 and lure > shake:
        verdict = '诱多嫌疑'
        conf = min(0.95, 0.4 + lure / 8)
        teach = '表象强、收盘弱：拉高时用少量资金/对倒制造强势，把追涨者套在均价之上，随后派发。应对：不追高，等回踩均价线且放量确认再言。'
    elif shake >= 2.2 and shake > lure:
        verdict = '骗筹码嫌疑(洗盘吸筹)'
        conf = min(0.95, 0.4 + shake / 8)
        teach = '表象弱、收盘强：先低开/下杀制造恐慌逼你割肉，随后收回均价之上。对持筹者是偏多信号(洗盘结束)，而非真破位。应对：看收盘是否站回均价+不破前低。'
    elif genuine_up:
        verdict = '真实走强'
        conf = 0.7
        teach = '价量配合、全天在均价线上方、收盘近高位，属真实资金推动的走强。'
    elif genuine_down:
        verdict = '真实走弱'
        conf = 0.7
        teach = '全天在均价线下方、收盘近低位，属真实承压/派发，非洗盘。'
    else:
        verdict = '震荡中性'
        conf = 0.5
        teach = '多空拉锯、收盘贴近均价，无明确陷阱特征。'

    return {'code': code, 'verdict': verdict, 'confidence': round(conf, 2),
            'lure_score': round(lure, 2), 'shake_score': round(shake, 2), 'shape': shape,
            'volprice': {'state': state, 'impl': impl, 'vol_ratio': vol_ratio, 'vol_bias': round(vol_bias, 3)},
            'teach': teach, 'evidence': evidence, 'features': feats}


if __name__ == '__main__':
    import sys
    codes = sys.argv[1:] or ['sh600000', 'sz000001', 'sh601318', 'sz000858', 'sh600036', 'sh600519', 'sz300750', 'sh601012']
    for c in codes:
        try:
            r = analyze(c)
            if 'error' in r:
                print('%-10s ERR %s' % (c, r['error'])); continue
            f = r['features']
            vp = r['volprice']
            print('%-10s %s %s | 判=%s(%.0f%%) 诱多%.1f/骗筹%.1f | 量价=%s | 量比=%s 量向%.0f%%'
                  % (c, f['name'], f['date'], r['verdict'], r['confidence']*100, r['lure_score'], r['shake_score'],
                     vp['state'], vp['vol_ratio'], vp['vol_bias']*100))
            for e in r['evidence']:
                print('      ·', e)
        except Exception as e:
            print('%-10s EXC %s %s' % (c, type(e).__name__, e))
