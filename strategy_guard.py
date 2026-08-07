# -*- coding: utf-8 -*-
"""
小狼策略 · 纠错 / 体检机制 (Error-Correction & Health Monitor)
================================================================
目标：在"信号已经产生"之后，再上一道纠错闸门——判断当下到底该不该按信号出手、
      出多少、止损该不该收紧。三层：

  L0 逻辑自检   : 读 opt_result.json，核对当前参数是否落在回测安全区；
                 并明确提示"本策略为均值回归型，回测期相对全市场等权持有为负超额，
                 属风险控制型而非 Alpha 增强型"——防止牛市跑输指数时被误判为失效。

  L1 市场状态   : 取沪深300日K线，用 现价 vs MA200 + MA60斜率 + MA60/MA200 死叉
                 判定 牛 / 震荡 / 弱 / 熊 → 给出仓位系数 size_mult 与 动态止损 stop_pct。
                 （回测证明：均值回归在动量/牛市中跑输，在震荡中最优，在熊市落刀风险高）

  L2 实盘回检   : 若提供 trade_log.json（用户记录真实买卖），滚动最近 N 笔计算胜率/均值，
                 与回测基线(胜率65.5% / 均值+5.9%)比对；偏离超阈 → RED，建议暂停新开仓。
                 （闭环：让"预期盈利率"从纸面回测变成可被实盘证伪/纠偏的数字）

输出：strategy_guard.json（网页横幅消费）+ 中文诊断打印。
用法：python strategy_guard.py
依赖：仅标准库 urllib/json/math（云端无 akshare 也能跑）。
"""
import urllib.request, json, ssl, math, sys, time, os

CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
HDR = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://quote.eastmoney.com/'}

# 当前实跑参数（须与 auto_screener.py 顶部一致）
GREED_PASS = 40
HOLD_DAYS = 40
STOP_PCT = 0.08
TP_PCT = 0.15

# 回测基线（来自 opt_result.json，V3 最优变体）
BASE_WIN = 0.655
BASE_AVG = 0.059
BASE_EXCESS = -0.026   # 相对全市场等权持有的负超额
BASE_N = 1524

def log(*a): print('[体检]', *a); sys.stdout.flush()


def fetch_index_kline(code='sh000300', n=320):
    """返回 [[date, close, volume], ...]。
    腾讯日K字段为 [日期, 开, 收, 高, 低, 成交量(手)]，其中成交量已实测与
    qt.gtimg.cn 实时字段[36]完全一致。保留 r[1]=close 的既有取值方式不变。"""
    url = 'https://ifzq.gtimg.cn/appstock/app/kline/kline?_var=k&param=%s,day,,,%d' % (code, n)
    last_e = None
    for _ in range(3):
        try:
            raw = urllib.request.urlopen(urllib.request.Request(url, headers=HDR), timeout=20).read().decode('utf-8', 'ignore')
            raw = raw[raw.index('=') + 1:]
            d = json.loads(raw)
            inner = d.get('data', {}).get(code, {})
            kd = inner.get('day') or inner.get('qfqday') if isinstance(inner, dict) else None
            if kd:
                out = []
                for k in kd:
                    try:
                        vol = float(k[5]) if len(k) > 5 else 0.0
                    except Exception:
                        vol = 0.0
                    out.append([k[0], float(k[2]), vol])
                return out
        except Exception as e:
            time.sleep(0.2); last_e = e
    log('指数K线获取失败:', last_e)
    return []


def regime_from_kline(kd):
    """返回市场状态 dict: level/size_mult/stop_pct/note + 指标。"""
    if not kd or len(kd) < 200:
        return {'level': 'UNKNOWN', 'size_mult': 0.7, 'stop_pct': 0.08,
                'note': '指数K线不足，无法判定状态，保守按弱势处理(仓位0.7x/止损8%)',
                'close': None, 'ma60': None, 'ma200': None, 'ma60_slope': None}
    closes = [r[1] for r in kd]
    L = len(closes)
    def ma(p, end=L):
        return sum(closes[end - p:end]) / p
    close = closes[-1]; ma20 = ma(20); ma60 = ma(60); ma200 = ma(200)
    ma60_prev = ma(60, L - 20)
    slope = (ma60 - ma60_prev) / ma60_prev if ma60_prev else 0.0
    if close > ma60 and ma60 > ma200 and slope > 0.01:
        lvl, size, stop = 'BULL', 0.5, 0.08
        note = '市场上行趋势(价在MA60上、MA60>MA200、MA60斜率为正)：本均值回归策略在动量市中跑输指数是回测已证实的预期，建议仅以0.5x小仓博反弹，主力应配指数/趋势品种。'
    elif close < ma60 and ma60 < ma200:
        lvl, size, stop = 'BEAR', 0.6, 0.06
        note = '市场下行趋势(MA60下穿MA200死叉)：恐慌低吸逻辑有效但"接落刀"风险高，止损收紧至6%、仓位0.6x，严控单笔且优先好公司。'
    elif close < ma200:
        lvl, size, stop = 'WEAK', 0.7, 0.07
        note = '价格低于年线(长期弱势但无死叉)：落刀风险中等，仓位0.7x、止损7%，只做技术共振最强的A信号。'
    else:
        lvl, size, stop = 'RANGE', 1.0, 0.08
        note = '区间震荡：均值回归逻辑最适宜的环境，仓位1.0x、止损8%，可正常按信号出手。'
    return {'level': lvl, 'size_mult': size, 'stop_pct': stop, 'note': note,
            'close': round(close, 2), 'ma60': round(ma60, 2), 'ma200': round(ma200, 2),
            'ma60_slope': round(slope, 4)}


# ======================= L1b 大盘量能（缩量 / 放量） =======================
# A股日内成交量呈 U 型分布（开盘、尾盘放量，午间清淡）。本脚本在 CI 里于
# 08:30 / 10:30 / 14:00 运行，盘中拿到的"当日成交量"只是截至当刻的累计值；
# 若直接与 20 日"全天"均量比较，必然被误判成「地量」。故按经验累计占比曲线
# 把盘中量折算为全天预估量后再比较。
INTRADAY_CURVE = [
    (9 * 60 + 30, 0.00), (10 * 60, 0.20), (10 * 60 + 30, 0.31),
    (11 * 60, 0.40), (11 * 60 + 30, 0.48), (13 * 60, 0.48),
    (13 * 60 + 30, 0.57), (14 * 60, 0.66), (14 * 60 + 30, 0.77),
    (15 * 60, 1.00),
]

# 量比(当日量 / 20日均量)阈值 —— 由沪深两市近 300 个交易日实测分位数校准：
#   P02≈0.77  P05≈0.81  P10≈0.85  P25≈0.93  P50≈0.99
#   P75≈1.08  P90≈1.18  P95≈1.26  P98≈1.36   (区间最小0.74 / 最大1.65)
# ⚠️ 大盘指数的量能波动远小于个股，不可套用个股"放量=1.5倍"的经验值：
#    实测 320 日内量比最大仅 1.65，若把天量设为 1.6、地量设为 0.7，
#    则「天量下跌→RED」与「地量」两条分支几乎永远不会触发，风控形同虚设。
# 若市场活跃度发生结构性变化，重算分位数并按 P10/P25/P75/P90/P98 重新校准。
VR_HUGE = 1.35   # 天量   ~P98
VR_HIGH = 1.18   # 放量   ~P90
VR_MILD = 1.08   # 温和放量 ~P75
VR_FLAT = 0.93   # 平量下沿 ~P25
VR_LOW = 0.85    # 缩量下沿 ~P10（更低即地量）


def intraday_ratio(now_min):
    """截至当日 now_min 分钟，预计已成交的全天占比 0~1（分段线性插值）。"""
    if now_min <= INTRADAY_CURVE[0][0]:
        return 0.0
    if now_min >= 15 * 60:
        return 1.0
    for i in range(1, len(INTRADAY_CURVE)):
        t0, r0 = INTRADAY_CURVE[i - 1]
        t1, r1 = INTRADAY_CURVE[i]
        if now_min <= t1:
            if t1 == t0:
                return r1
            return r0 + (r1 - r0) * (now_min - t0) / float(t1 - t0)
    return 1.0


def fetch_market_amount():
    """两市当日成交额合计(亿元)，仅用于展示直观数字（判定仍用成交量）。"""
    try:
        url = 'https://qt.gtimg.cn/q=sh000001,sz399001'
        raw = urllib.request.urlopen(urllib.request.Request(url, headers=HDR), timeout=15).read().decode('gbk', 'ignore')
        tot = 0.0
        for line in raw.strip().split('\n'):
            if '=' not in line:
                continue
            p = line.split('=', 1)[1].strip().strip(';').strip('"').split('~')
            if len(p) > 37:
                try:
                    tot += float(p[37] or 0)   # 成交额，单位万元
                except Exception:
                    pass
        return round(tot / 1e4, 0) if tot > 0 else None   # 万元 → 亿元
    except Exception:
        return None


def volume_check():
    """大盘量能体检：沪深两市成交量 → 缩量/放量 → 结合价格方向判定量价关系，
    输出「操作建议 + 风险提示 + 仓位微调 + 当前更适合 M(顺势) 还是 A(低吸)」。

    口径说明：腾讯日K只给成交量(手)不给成交额，而指数层面价格变化缓慢，
    成交量的相对变化已足以刻画量能强弱，故判定用量、展示用额。
    """
    out = {'ok': False, 'state': '未知', 'verdict': '未知',
           'level': 'GREEN', 'size_adj': 1.0, 'favor': 'none',
           'action': '', 'risk': '', 'trend': '',
           'ratio20': None, 'ratio5': None, 'chg': None,
           'intraday': False, 'amount_yi': None,
           'note': '未能获取大盘成交量，本次跳过量能维度。'}

    sh = fetch_index_kline('sh000001', 90)
    sz = fetch_index_kline('sz399001', 90)
    if not sh or len(sh) < 26:
        return out

    # 按日期对齐合并两市成交量（深市取不到时降级为仅沪市，相对比较依然成立）
    szmap = {r[0]: r[2] for r in sz}
    cmap = {r[0]: r[1] for r in sh}
    dates, vols = [], []
    for r in sh:
        v = (r[2] or 0) + (szmap.get(r[0], 0) or 0)
        if v > 0:
            dates.append(r[0]); vols.append(v)
    if len(vols) < 26:
        return out

    # —— 盘中折算 ——
    intraday = False
    lt = time.localtime()
    today_str = time.strftime('%Y-%m-%d', lt)
    if dates[-1] == today_str:
        rr = intraday_ratio(lt.tm_hour * 60 + lt.tm_min)
        if rr >= 0.999:
            pass                      # 已收盘，当日量完整
        elif rr > 0.05:
            vols[-1] = vols[-1] / rr  # 折算成全天预估量
            intraday = True
        else:
            dates = dates[:-1]; vols = vols[:-1]   # 开盘前/集合竞价，样本不可信
            if len(vols) < 26:
                return out

    closes = [cmap.get(d) for d in dates]
    today = vols[-1]
    hist = vols[:-1]                                   # 均量不含当日，避免自我污染
    ma5 = sum(hist[-5:]) / 5.0
    ma20 = sum(hist[-20:]) / 20.0
    if ma20 <= 0:
        return out
    ratio20 = today / ma20
    ratio5 = today / ma5 if ma5 > 0 else ratio20

    # 量能中期方向（含当日折算值）
    m5a = sum(vols[-5:]) / 5.0
    m20a = sum(vols[-20:]) / 20.0
    tr = (m5a / m20a) if m20a > 0 else 1.0
    trend = '量能持续放大' if tr >= 1.15 else ('量能持续萎缩' if tr <= 0.85 else '量能平稳')

    # 价格方向（上证）
    chg = 0.0
    if len(closes) >= 2 and closes[-1] and closes[-2]:
        chg = (closes[-1] / closes[-2] - 1) * 100

    if ratio20 >= VR_HUGE:
        state = '天量'
    elif ratio20 >= VR_HIGH:
        state = '放量'
    elif ratio20 >= VR_MILD:
        state = '温和放量'
    elif ratio20 >= VR_FLAT:
        state = '平量'
    elif ratio20 >= VR_LOW:
        state = '缩量'
    else:
        state = '地量'

    up, down = chg > 0.3, chg < -0.3

    if state == '天量':
        if up:
            verdict, level, size_adj, favor = '天量大涨', 'AMBER', 0.8, 'none'
            action = '不追高：M档顺势持仓收紧止盈、分批兑现，暂缓新开A档低吸。'
            risk = '天量常对应短期情绪顶（见量见顶），冲高回落概率上升。'
        elif down:
            verdict, level, size_adj, favor = '天量下跌', 'RED', 0.5, 'none'
            action = '暂停新开仓，存量按纪律止损，等待缩量企稳。'
            risk = '恐慌性抛售、资金加速出逃，此时低吸接落刀风险极高。'
        else:
            verdict, level, size_adj, favor = '天量滞涨', 'AMBER', 0.7, 'none'
            action = '放量不涨多为高位派发，减仓观望，不新开仓。'
            risk = '多空分歧剧烈，滞涨往往是变盘前兆。'
    elif state == '放量':
        if up:
            verdict, level, size_adj, favor = '量价齐升', 'GREEN', 1.10, 'M'
            action = '资金真实进场，M档(强势顺势)环境最佳，可正常乃至略加仓顺势；A档低吸机会相应减少。'
            risk = '低。但需盯住是否升级为天量，天量后应转防守。'
        elif down:
            verdict, level, size_adj, favor = '放量下跌', 'AMBER', 0.6, 'none'
            action = '减半或暂停新开仓，等缩量企稳再考虑低吸。'
            risk = '放量杀跌说明抛压真实且集中，左侧低吸易接落刀。'
        else:
            verdict, level, size_adj, favor = '放量滞涨', 'AMBER', 0.8, 'none'
            action = '量增价平，方向未明，观望为主、不新开仓。'
            risk = '资金进出激烈而价格无进展，需防向下变盘。'
    elif state == '温和放量':
        if up:
            verdict, level, size_adj, favor = '温和放量上涨', 'GREEN', 1.05, 'M'
            action = '量能温和配合上涨，M档顺势可按信号出手；但强度尚未到全面进攻，仓位不宜过满。'
            risk = '低。若后续量能跟不上，易转为缩量背离而回落。'
        elif down:
            verdict, level, size_adj, favor = '温和放量下跌', 'AMBER', 0.85, 'none'
            action = '量增价跌、抛压略占上风，暂缓新开仓，观察能否缩量企稳。'
            risk = '中。需防演变为放量杀跌。'
        else:
            verdict, level, size_adj, favor = '温和放量滞涨', 'GREEN', 0.95, 'none'
            action = '量能小幅活跃但价格无进展，按既定信号正常操作即可。'
            risk = '低。'
    elif state == '平量':
        verdict, level, size_adj, favor = '量能平稳', 'GREEN', 1.0, 'none'
        action = '量能无异常，按既定信号与仓位纪律正常出手。'
        risk = '低。'
    elif state == '缩量':
        if up:
            verdict, level, size_adj, favor = '缩量上涨', 'AMBER', 0.8, 'none'
            action = '量价背离，不追高；等放量确认再顺势，M档新开仓从严。'
            risk = '无量反弹持续性存疑，易冲高回落。'
        elif down:
            verdict, level, size_adj, favor = '缩量下跌', 'GREEN', 1.0, 'A'
            action = '抛压趋于衰竭，A档(低位低吸)环境转好，可小仓分批；反转仍需放量确认。'
            risk = '中低。但缩量阴跌可能延续，切勿一次重仓。'
        else:
            verdict, level, size_adj, favor = '缩量横盘', 'GREEN', 0.9, 'A'
            action = '窄幅缩量整理，可按A档信号小仓低吸，等待方向选择。'
            risk = '中低。方向未明，控制单笔仓位。'
    else:
        verdict, level, size_adj, favor = '地量', 'AMBER', 0.8, 'A'
        action = '成交萎缩至冰点，轻仓观望；地量之后常有变盘，等放量确认方向再出手。'
        risk = '流动性偏枯竭，个股易无量阴跌，卖出时滑点变大。'

    amt = fetch_market_amount()
    amt_txt = ('两市成交约%.0f亿' % amt) if amt else ''
    intr_txt = '（盘中按日内量能曲线折算为全天预估）' if intraday else ''
    note = '%s：当日量为20日均量的%.0f%%%s，%s。%s%s' % (
        verdict, ratio20 * 100, ('、5日均量的%.0f%%' % (ratio5 * 100)) if ratio5 else '',
        trend, (amt_txt + '。') if amt_txt else '', intr_txt)

    out.update({'ok': True, 'state': state, 'verdict': verdict, 'level': level,
                'size_adj': size_adj, 'favor': favor, 'action': action, 'risk': risk,
                'trend': trend, 'ratio20': round(ratio20, 3), 'ratio5': round(ratio5, 3),
                'chg': round(chg, 2), 'intraday': intraday, 'amount_yi': amt,
                'note': note})
    return out


def logic_check():
    """读 opt_result.json 做逻辑自检。"""
    out = {'params_ok': True, 'warn': '', 'backtest': {}}
    # 参数安全区核对
    params_ok = (GREED_PASS in (35, 40, 45) and HOLD_DAYS in (20, 40, 60)
                 and abs(STOP_PCT - 0.08) < 1e-6 and abs(TP_PCT - 0.15) < 1e-6)
    out['params_ok'] = params_ok
    # 回测基线
    try:
        d = json.load(open('opt_result.json', encoding='utf-8'))
        v = d['variants'].get('V3止损8止盈15@40') or d['variants'].get('V5g40止损8止盈15@40')
        if v:
            out['backtest'] = {'win': round(v['win'], 4), 'avg': round(v['avg'], 4),
                               'med': round(v['med'], 4), 'excess': round(v['excess'], 4),
                               'stop_r': round(v.get('stop_r', 0), 4), 'tp_r': round(v.get('tp_r', 0), 4)}
        neg = [k for k, vv in d['variants'].items() if vv['excess'] < 0]
        out['warn'] = ('回测 %d/%d 个变体相对「全市场等权持有」超额为负(最优约 %.1f%%)，'
                       '说明本策略属风险控制/均值回归型而非 Alpha 增强型；'
                       '牛市跑输指数属预期内，不应误判为策略失效。' % (len(neg), len(d['variants']), min(vv['excess'] for vv in d['variants'].values()) * 100))
    except Exception as e:
        out['warn'] = '未找到 opt_result.json(%s)，无法核对回测基线，按参数默认自检。' % e
    return out


def live_check(baseline_win=BASE_WIN, baseline_avg=BASE_AVG, window=20):
    """L2 实盘回检。优先读 watch_pool.json（自动追踪的真实命中率，无需手填），
    样本不足时回退 trade_log.json（手动记录）。两者皆无则 N/A。"""
    # 1) 优先：观察池（自我纠正闭环的数据源）
    wp = 'watch_pool.json'
    if os.path.exists(wp):
        try:
            d = json.load(open(wp, encoding='utf-8'))
            s = d.get('stats', {})
            wr = s.get('win_rate'); av = s.get('avg_return'); closed = s.get('closed', 0)
            if closed and wr is not None:
                if wr < 0.45 or (av or 0) < 0:
                    status, action = 'RED', '观察池真实命中率严重低于回测基线，疑似策略失效或市场状态切换，建议暂停新开仓、收缩存量仓位并复盘。'
                elif wr < baseline_win - 0.10 or (av or 0) < baseline_avg * 0.5:
                    status, action = 'AMBER', '观察池真实命中率偏弱于回测基线，建议减半新开仓、收紧止损至6%，观察下一周期。'
                else:
                    status, action = 'GREEN', '观察池真实命中率与回测基线基本吻合，维持既定参数。'
                return {'has_data': True, 'source': '观察池(自动追踪%d笔)' % closed, 'status': status,
                        'window': closed, 'rolling_win': wr, 'rolling_avg': av,
                        'baseline_win': baseline_win, 'baseline_avg': baseline_avg, 'note': action}
            # 样本不足：继续往下走 trade_log
        except Exception:
            pass
    # 2) 回退：手动实盘记录
    path = 'trade_log.json'
    if not os.path.exists(path):
        return {'has_data': False, 'status': 'N/A',
                'note': '暂无实盘记录（观察池样本也不足）。观察池会随每日扫描自动累积，'
                        '建议先看观察池的「实盘验证」Tab，或按 trade_log.json 格式补记真实买卖。'}
    try:
        recs = json.load(open(path, encoding='utf-8'))
        if not isinstance(recs, list) or not recs:
            return {'has_data': False, 'status': 'N/A', 'note': 'trade_log.json 为空。'}
        recent = recs[-window:]
        pnls = [float(r.get('pnl', 0)) for r in recent if 'pnl' in r]
        if not pnls:
            return {'has_data': True, 'status': 'N/A', 'note': '近期记录缺少 pnl 字段。'}
        win = sum(1 for x in pnls if x > 0) / len(pnls)
        avg = sum(pnls) / len(pnls)
        # 偏离判定
        if win < 0.45 or avg < 0:
            status, action = 'RED', '实盘滚动胜率/收益严重低于回测基线，疑似策略失效或市场状态切换，建议暂停新开仓、收缩存量仓位并复盘。'
        elif win < baseline_win - 0.10 or avg < baseline_avg * 0.5:
            status, action = 'AMBER', '实盘偏弱于回测基线，建议减半新开仓、收紧止损至6%，观察下一周期。'
        else:
            status, action = 'GREEN', '实盘与回测基线基本吻合，维持既定参数。'
        return {'has_data': True, 'status': status, 'window': len(pnls),
                'rolling_win': round(win, 4), 'rolling_avg': round(avg, 4),
                'baseline_win': baseline_win, 'baseline_avg': baseline_avg, 'note': action}
    except Exception as e:
        return {'has_data': False, 'status': 'N/A', 'note': '读取 trade_log.json 失败: %s' % e}


def main():
    log('=== 小狼策略 · 体检/纠错 ===')
    lc = logic_check()
    kd = fetch_index_kline()
    rg = regime_from_kline(kd)
    vol = volume_check()
    lv = live_check()

    # 风险等级聚合
    risk = 'GREEN'
    reasons = []
    if not lc['params_ok']:
        risk = 'RED'; reasons.append('参数已偏离回测安全区')
    if lv.get('status') == 'RED':
        risk = 'RED'; reasons.append('实盘回检触发RED')
    elif lv.get('status') == 'AMBER':
        risk = 'AMBER' if risk != 'RED' else risk; reasons.append('实盘偏弱')
    if rg['level'] in ('BULL', 'BEAR', 'WEAK') and risk == 'GREEN':
        risk = 'AMBER'; reasons.append('市场状态=%s，需调整仓位/止损' % rg['level'])
    # 大盘量能：天量下跌直接触发RED；其余异常量价关系升为AMBER
    if vol.get('ok'):
        if vol['level'] == 'RED':
            risk = 'RED'; reasons.append('大盘量能异常(%s)' % vol['verdict'])
        elif vol['level'] == 'AMBER':
            if risk == 'GREEN':
                risk = 'AMBER'
            reasons.append('大盘量能预警(%s)' % vol['verdict'])

    # 仓位系数 = 市场状态基准 × 量能微调（夹在 0.3~1.2）
    size_mult = rg['size_mult']
    if vol.get('ok'):
        size_mult = max(0.3, min(1.2, round(rg['size_mult'] * vol['size_adj'], 2)))

    actions = []
    actions.append('仓位系数 %.2fx（市场状态：%s%s）' % (
        size_mult, rg['level'],
        ' × 量能%s%.1f' % (vol['verdict'], vol['size_adj']) if vol.get('ok') and abs(vol['size_adj'] - 1.0) > 1e-9 else ''))
    actions.append('动态止损 %.0f%%（原8%%）' % (rg['stop_pct'] * 100))
    if vol.get('ok'):
        actions.append('📊 量能：%s' % vol['action'])
        if vol['favor'] == 'M':
            actions.append('🚀 当前量能环境更利于 M档(强势顺势)')
        elif vol['favor'] == 'A':
            actions.append('🟢 当前量能环境更利于 A档(低位低吸)')
    if risk == 'RED':
        actions.append('⛔ 暂停新开仓，复盘信号与近期市场状态')
    elif risk == 'AMBER':
        actions.append('⚠️ 减半新开仓，仅做共振最强的信号')
    else:
        actions.append('✅ 可正常按信号出手')

    diagnosis = ('逻辑自检：%s\n市场状态：%s —— %s\n大盘量能：%s\n实盘回检：%s' %
                 ('参数安全区OK' if lc['params_ok'] else '参数偏离!',
                  rg['level'], rg['note'],
                  ('%s ｜ 操作：%s ｜ 风险：%s' % (vol['note'], vol['action'], vol['risk'])) if vol.get('ok') else vol['note'],
                  (lv['note'] if lv.get('has_data') else '暂无实盘记录，仅逻辑+状态自检')))

    out = {
        'generated': time.strftime('%Y-%m-%d %H:%M'),
        'risk_level': risk,
        'risk_reasons': reasons,
        'regime': rg,
        'volume': vol,
        'logic_check': lc,
        'live': lv,
        'position_rule': {
            'max_positions': 6,
            'single_cap': 0.20,
            'size_mult': size_mult,
            'base_size_mult': rg['size_mult'],
            'vol_size_adj': vol.get('size_adj', 1.0),
            'stop_pct': rg['stop_pct'],
            'tp_pct': TP_PCT,
        },
        'diagnosis': diagnosis,
        'actions': actions,
    }
    json.dump(out, open('strategy_guard.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1, allow_nan=False)
    # 打印诊断
    print('\n────────── 策略体检报告 ──────────')
    print('风险等级 :', {'GREEN': '🟢 绿(正常)', 'AMBER': '🟡 黄(调整)', 'RED': '🔴 红(暂停)'}[risk])
    if reasons: print('触发原因 :', '; '.join(reasons))
    print('市场状态 :', rg['level'], '(close %.2f / MA200 %.2f / MA60斜率 %s)' % (rg['close'] or 0, rg['ma200'] or 0, rg['ma60_slope']))
    if vol.get('ok'):
        print('大盘量能 : %s(%s) 量比20日 %.0f%% %s' % (
            vol['verdict'], vol['state'], vol['ratio20'] * 100,
            '[盘中折算]' if vol['intraday'] else ''))
        print('   操作   :', vol['action'])
        print('   风险   :', vol['risk'])
        if vol['favor'] != 'none':
            print('   适配   :', 'M档(强势顺势)' if vol['favor'] == 'M' else 'A档(低位低吸)')
    else:
        print('大盘量能 : 获取失败，跳过')
    print('仓位系数 :', size_mult, 'x   动态止损:', '%.0f%%' % (rg['stop_pct'] * 100))
    if lc['backtest']:
        b = lc['backtest']
        print('回测基线 : 胜率%.1f%% 均值%+4.1f%% 中位%+4.1f%% 超额%+4.1f%%' % (b['win'] * 100, b['avg'] * 100, b['med'] * 100, b['excess'] * 100))
    print('逻辑警示 :', lc['warn'])
    if lv.get('has_data'):
        print('实盘回检 : 滚动胜率%.1f%% 均值%+4.1f%% → %s' % (lv['rolling_win'] * 100, lv['rolling_avg'] * 100, lv['status']))
    print('建议动作 :')
    for a in actions: print('   •', a)
    print('──────────────────────────────────')
    print('✅ 已保存 strategy_guard.json')


if __name__ == '__main__':
    main()
