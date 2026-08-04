# -*- coding: utf-8 -*-
"""
ETF/LOF 买入卖出时机扫描器
============================
复用 auto_screener 的「技术底层」(自建贪婪指数 / MACD / 布林 / 底背离 / 小狼2.0 / 大盘门控 / trade_plan / 宏观调制)，
针对 ETF 做三点适配：
  1) 正确的 secid / K线 市场映射 (510300→sh, 159915→sz, 588000→sh …)
  2) 跳过「好公司」基本面过滤 (ETF 非个股，无 ROE/现金流可言)
  3) L4 主力资金流尽力而为 (场内 ETF 有资金流，缺失不影响主线)
输出 etf_result.json：{generated, A/B/C/D:[{code,name,price,change,trade_plan,rationale,...}]}
交易时机 Tab 的「ETF 分区」直接读取本文件产物。
"""
import json, time, random, os, sys, math
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import auto_screener as A

# ---------- ETF/LOF 精选池（流动性好、代表性）----------
# 宽基 + 行业/主题 + 商品/跨境；均为交易所上市、腾讯 K线 直取可用
ETF_UNIVERSE = [
    # 宽基
    ('510300', '沪深300ETF'), ('510500', '中证500ETF'), ('159915', '创业板ETF'),
    ('588000', '科创50ETF'), ('512100', '中证1000ETF'), ('159901', '深证100ETF'),
    # 行业 / 主题
    ('512660', '军工ETF'), ('512010', '医药ETF'), ('512760', '半导体ETF'),
    ('515030', '新能源ETF'), ('512690', '酒ETF'), ('159928', '消费ETF'),
    ('515790', '光伏ETF'), ('516970', '基建50ETF'), ('512800', '银行ETF'),
    ('512880', '证券ETF'), ('516110', '汽车ETF'), ('159995', '芯片ETF'),
    ('561300', '国泰中证全指ETF'), ('516160', '新能源ETF基金'),
    # 商品 / 跨境 / 其他
    ('518880', '黄金ETF'), ('513100', '纳指ETF'), ('513180', '恒生科技ETF'),
    ('513500', '标普500ETF'), ('159920', '恒生ETF'), ('511380', '可转债ETF'),
    ('159980', '有色ETF'), ('159981', '能源化工ETF'),
]


def etf_secid(code):
    return ('1.' if code[0] in '569' else '0.') + code


def etf_kline(code, period='day'):
    tcode = ('sh' if code[0] in '569' else 'sz') + code
    varn = 'k' + code + '_' + str(random.randint(0, 999999))
    if period == 'min15':
        url = 'https://ifzq.gtimg.cn/appstock/app/kline/mkline?_var=%s&param=%s,min15,,,320' % (varn, tcode)
    else:
        url = 'https://ifzq.gtimg.cn/appstock/app/kline/kline?_var=%s&param=%s,day,,,320' % (varn, tcode)
    for _ in range(3):
        try:
            raw = A.get(url); raw = raw[raw.index('=') + 1:]
            d = json.loads(raw); kd = d.get('data', {}).get(tcode, {})
            kl = kd.get('m15') if period == 'min15' else (kd.get('day') or kd.get('qfqday'))
            if not kl:
                return []
            return [{'date': k[0], 'open': float(k[1]), 'close': float(k[2]), 'high': float(k[3]),
                     'low': float(k[4]), 'volume': float(k[5]) if len(k) > 5 else 0} for k in kl]
        except Exception:
            time.sleep(0.15)
    return []


def scan_etf(code, name):
    """逐 ETF 跑四层+小狼2.0，收敛成 trade_plan（与 run_screening 同构，去掉 L0 基本面）。"""
    res = {'code': code, 'name': name, 'price': 0, 'change': 0, 'inflow': 0, 'asset_type': 'ETF',
           'template': '', 'suggestion': '',
           'stop': 0, 'target': 0,
           'l1': {}, 'l2': {}, 'l3': {}, 'l4': {}, 'flows': [], 'market': A.get_market_regime(), 'wolf2': {}}
    kd = etf_kline(code, 'day')
    if not kd or len(kd) < 30:
        res['l1'] = {'status': 'wait', 'greed': 0.0, 'detail': 'K线数据不足'}
        res['template'] = 'D'; res['suggestion'] = 'K线数据不足'
        res['l2'] = {'status': 'wait', 'detail': 'K线不足'}
        res['l3'] = {'status': 'wait', 'detail': 'K线不足'}
        res['l4'] = {'status': 'wait', 'detail': '资金流不足'}
        return res
    day_closes = [k['close'] for k in kd]
    res['price'] = round(day_closes[-1], 3)
    res['change'] = round((day_closes[-1] / day_closes[-2] - 1) * 100, 2) if len(day_closes) >= 2 else 0
    # 基础止损/止盈（按价格推算；wolf2 / A 分支会覆盖为更宽参数）
    res['stop'] = round(res['price'] * (1 - A.STOP_PCT), 3)
    res['target'] = round(res['price'] * (1 + A.TP_PCT), 3)
    # —— Layer 1 贪婪指数 ——
    greed = A.calc_greed(day_closes)
    if greed < A.GREED_PASS:
        l1 = ('pass', greed, '低位/恐慌区间，入观察池')
    elif greed > 65:
        l1 = ('fail', greed, '贪婪过热，禁止开仓')
    else:
        l1 = ('neutral', greed, '中性区间，观望')
    res['l1'] = {'status': l1[0], 'greed': greed, 'detail': '自建贪婪指数 %.1f%% → %s' % (greed, l1[1])}
    # —— Layer 2 MACD ——
    md = A.calc_macd(day_closes)
    if md:
        cr = A.check_macd_cross(md['dif'], md['dea'])
        if cr in ('golden', 'above'):
            res['l2'] = {'status': 'pass', 'detail': '日线MACD金叉/DIF在DEA上方，存在反弹窗口'}
        else:
            gs = A.check_macd_green_shorten(md['macd'])
            if gs:
                res['l2'] = {'status': 'wait', 'detail': '日线MACD零轴下方绿柱缩短，酝酿反弹'}
            else:
                res['l2'] = {'status': 'fail', 'detail': '日线MACD死叉且绿柱未缩短，持续下行风险高'}
    else:
        res['l2'] = {'status': 'wait', 'detail': 'K线不足，无法判断浪型'}
    # —— Layer 3 日线代理共振（扫描环境无15min，与个股一致）——
    tech = 0; sig = []
    b = A.calc_bollinger(day_closes)
    if b and b['position'] in ('下轨支撑', '中轨附近'):
        tech += 1; sig.append('布林' + b['position'])
    ma20 = sum(day_closes[-20:]) / 20
    if day_closes[-1] >= ma20:
        tech += 1; sig.append('站上MA20')
    lastvol = kd[-1]['volume']; avgvol = sum(k['volume'] for k in kd[-20:]) / 20
    if avgvol > 0 and lastvol > 1.5 * avgvol:
        tech += 1; sig.append('放量×%.1f' % (lastvol / avgvol))
    if md and A.check_macd_divergence(day_closes, md['dif']):
        tech += 1; sig.append('日线底背离')
    l3status = 'pass' if tech >= 2 else ('wait' if tech >= 1 else 'fail')
    res['l3'] = {'status': l3status, 'detail': '日线代理共振: ' + (' / '.join(sig) if sig else '无信号'), 'tech': tech}
    # —— 小狼 2.0（ETF 无小市值，small=False）——
    res['wolf2'] = A.wolf2_layer(kd, greed, tech, False)
    # —— Layer 4 主力资金流（场内 ETF 尽力而为）——
    flows = A.fetch_fund_flow(etf_secid(code))
    res['flows'] = flows
    l4status = 'wait'; l4detail = '资金流数据不足'
    if flows:
        recent = flows[-3:]; allout = all(f['main'] < 0 for f in recent)
        slowing = allout and abs(recent[-1]['main']) < abs(recent[0]['main'])
        last = recent[-1]; lastin = last['main'] > 0; amt = last['main'] / 1e8
        if lastin:
            l4status, l4detail = 'pass', '最近一日主力净流入 %.2f亿' % amt
        elif slowing:
            l4status, l4detail = 'wait', '近3日持续流出但幅度收窄'
        elif allout:
            l4status, l4detail = 'fail', '近3日主力持续净流出'
        else:
            l4status, l4detail = 'neutral', '资金流向不明朗'
    res['l4'] = {'status': l4status, 'detail': l4detail}
    # —— Layer 5 右侧(趋势跟随) + 波浪阶段 ——（与左侧低吸并列，让顺势买入被识别）
    res['l5'] = A.right_side(day_closes, kd, md)
    res['wave'] = A.wave_stage(day_closes)
    # —— 好公司过滤：ETF 不适用 ——
    res['fund'] = {'good': True, 'detail': 'ETF非个股，跳过好公司过滤'}
    # —— Template ——
    w2 = res['wolf2'].get('pass')
    if w2:
        res['template'] = 'A'
        res['stop'] = round(res['price'] * (1 - A.WOLF2_STOP), 3)
        res['target'] = round(res['price'] * (1 + A.WOLF2_TP), 3)
        w = res['wolf2']
        res['suggestion'] = ('【ETF·小狼2.0】低位恐慌+技术底背离，命中：%s。分批低吸，持有约%d日，'
                             '止损%d%%目标%d%%，反弹即走。') % (
            ' / '.join(w.get('reasons', [])) or '多因子共振', A.WOLF2_HOLD, int(A.WOLF2_STOP * 100), int(A.WOLF2_TP * 100))
    elif l1[0] == 'fail':
        res['template'] = 'C'; res['suggestion'] = '贪婪过热，禁止新开仓。'
    elif res['l2']['status'] == 'fail':
        res['template'] = 'D'; res['suggestion'] = '主跌阶段，观望，规避下跌风险。'
    elif l1[0] == 'pass' and l3status == 'pass':
        res['template'] = 'A'
        res['suggestion'] = 'ETF低位+技术共振：分批低吸，持有约%d日做均值回归，止损%d%%目标%d%%。' % (
            A.HOLD_DAYS, int(A.STOP_PCT * 100), int(A.TP_PCT * 100))
    else:
        res['template'] = 'B'; res['suggestion'] = '纳入观察池，等待信号共振，暂不入场。'
    gated, gnote = A.regime_gate(res['template'], res['market'])
    if gated != res['template']:
        res['template'] = gated; res['suggestion'] = gnote
    elif gnote:
        res['suggestion'] = res['suggestion'].rstrip('。') + '。' + gnote
    res['trade_plan'] = A.base_trade_plan(res)
    return res


def clean_nan(o):
    if isinstance(o, dict):
        return {k: clean_nan(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean_nan(v) for v in o]
    if isinstance(o, float):
        if math.isnan(o) or math.isinf(o):
            return None
    return o


def main():
    print('=== ETF/LOF 交易时机扫描 (共 %d 只) ===' % len(ETF_UNIVERSE))
    results = []
    # 串行扫描（ETF 量小，串行更稳；腾讯接口限频已内置重试）
    for code, name in ETF_UNIVERSE:
        try:
            r = scan_etf(code, name)
            results.append(r)
            print('  %s %s -> %s conv=%s' % (code, name, r['template'], r['trade_plan'].get('conviction')))
        except Exception as e:
            print('  %s %s 异常: %s' % (code, name, e))
    # 分类
    out = {'A': [], 'B': [], 'C': [], 'D': []}
    for r in results:
        out.setdefault(r['template'], 'D')
        out[r['template']].append(r)
    # 宏观调制（李大霄温度 + 情绪）per-pick 开仓总开关
    ld, sd = A.load_macro_best_effort()
    if ld or sd:
        qset = A.load_quality_set()
        for r in results:
            r['lidaxiao_pick'] = r['code'] in qset
            A.apply_macro(r, ld, sd)
    # 排序（确定性降序）
    for k in out:
        out[k].sort(key=lambda r: -(r.get('trade_plan', {}).get('conviction', 0)))
    payload = {
        'generated': time.strftime('%Y-%m-%d %H:%M'),
        'count': len(results),
        'A': out.get('A', []), 'B': out.get('B', []), 'C': out.get('C', []), 'D': out.get('D', []),
    }
    payload = clean_nan(payload)
    with open(os.path.join(HERE, 'etf_result.json'), 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, allow_nan=False, indent=1)
    print('=== etf_result.json 已生成: A=%d B=%d C=%d D=%d ===' % (
        len(out['A']), len(out['B']), len(out['C']), len(out['D'])))


if __name__ == '__main__':
    main()
