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
    # code 已是完整腾讯代码(如 sh000300 / sz399001)，直接用于 URL 与返回字典键
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
                return [[k[0], float(k[2])] for k in kd]
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

    actions = []
    actions.append('仓位系数 %.1fx（市场状态：%s）' % (rg['size_mult'], rg['level']))
    actions.append('动态止损 %.0f%%（原8%%）' % (rg['stop_pct'] * 100))
    if risk == 'RED':
        actions.append('⛔ 暂停新开仓，复盘信号与近期市场状态')
    elif risk == 'AMBER':
        actions.append('⚠️ 减半新开仓，仅做共振最强的A信号')
    else:
        actions.append('✅ 可正常按信号出手')

    diagnosis = ('逻辑自检：%s\n市场状态：%s —— %s\n实盘回检：%s' %
                 ('参数安全区OK' if lc['params_ok'] else '参数偏离!',
                  rg['level'], rg['note'],
                  (lv['note'] if lv.get('has_data') else '暂无实盘记录，仅逻辑+状态自检')))

    out = {
        'generated': time.strftime('%Y-%m-%d %H:%M'),
        'risk_level': risk,
        'risk_reasons': reasons,
        'regime': rg,
        'logic_check': lc,
        'live': lv,
        'position_rule': {
            'max_positions': 6,
            'single_cap': 0.20,
            'size_mult': rg['size_mult'],
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
    print('仓位系数 :', rg['size_mult'], 'x   动态止损:', '%.0f%%' % (rg['stop_pct'] * 100))
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
