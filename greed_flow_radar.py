# -*- coding: utf-8 -*-
"""低位资金异动雷达 (Greed-Flow Radar)

命题(用户提出, 已回测验证):
  贪婪指数低(<35) + 板块资金流入 + 个股资金流入 → 强烈提醒关注买入
  贪婪指数低 但 无资金流入 → 无人问津, 不值得动

回测依据 (5年 2021-08~2026-08, 291只, 63002个检查点, 持有20日, 扣0.25%成本):
  ┌──────────────────────────┬──────┬────────┬─────────┬────────┐
  │ 组别                      │ 样本 │ 胜率   │ 20日均收 │ 超额   │
  ├──────────────────────────┼──────┼────────┼─────────┼────────┤
  │ S0 全市场基线              │63002 │ 46.8%  │  0.74%  │  0.00% │
  │ 贪婪<35 (仅低位, 无资金要求)│26869 │ 49.7%  │  1.39%  │ +0.65% │
  │ +个股资金(3选2)            │ 7955 │ 51.5%  │  1.71%  │ +0.97% │
  │ +板块共振>50%              │ 2440 │ 56.2%  │  2.51%  │ +1.77% │
  │ +板块>80% & 贪婪<10 (核心)  │  312 │ 59.0%  │  4.08%  │ +3.34% │← 最强
  └──────────────────────────┴──────┴────────┴─────────┴────────┘

v5 加严单调性检验 —— 哪些维度真的有用:
  ✅ 板块共振强度: <33% 48.7% → 33~50% 49.7% → >50% 56.2% → >66% 56.3% → >80% 57.1%  单调
  ✅ 贪婪深度:     20~35 55.0% → 10~20 55.0% → <10 58.4%/+2.50%                      越冷越好
  ❌ 个股信号3个全中: 55.2%, 不如"≥2个"的 56.2% —— 堆信号数没用, 不要加
  ❌ 放量>2倍:      51.5%, 明显掉头 —— 追放量是反效果
  → 只用前两个维度加严, 后两个坚决不加。

⚠️ 核心档分环境 (必须如实展示, 不能只报好消息):
     上涨市 n=110 胜率60.9% 超额+2.97%
     震荡市 n=116 胜率49.1% 超额+0.15% (±1.05se) ← 震荡市基本没有超额, 等于白做
     下跌市 n= 86 胜率69.8% 超额+6.86%
  → 不设硬闸门(样本量偏小, 不足以支撑一票否决), 但震荡市必须在页面顶部挂警示。

分级:
  🔴 CORE    贪婪<10 + 个股资金 + 板块共振>80%  (59.0% 胜率档, 强烈提醒)
  🟠 STRONG  贪婪<35 + 个股资金 + 板块共振>50%  (56.2% 胜率档)
  🟡 WATCH   贪婪<35 + 个股资金, 板块未共振      (51.5% 胜率档)
  ⚪ QUIET   贪婪<35 + 无资金 = "无人问津"       (48.9% 胜率档 ≈ 基线, 只列不提醒)
"""
import json, math, os, random, ssl, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

# 全市场 fs —— 四段缺一不可(只写 m:0+t:6 会漏掉沪市 600/601/603 与科创板 688)
ALL_FS = 'm:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23'
GREED_LOW = 35.0          # 低贪婪阈值(回测 20~45 均稳健, 取 35)
PRESCAN = 1500            # 预筛候选数
HOLD_DAYS = 20            # 回测最优持有期
SEC_RESONANCE = 0.5       # 板块共振阈值: 同业低位票中资金信号占比(回测口径)
SEC_RANK_TOP = 100        # 真实板块资金加严: 净流入排名进全市场前100(共496个板块)
MIN_SIG = 2               # 个股资金信号数下限 —— 必须=2, 见下方"校准铁律"
CORE_GREED = 10.0         # 核心档: 贪婪深度(v5验证 <10 才有跃升)
CORE_SEC = 0.8            # 核心档: 同业共振占比(v5验证 >80% 为最强档)
STOP_PCT, TP_PCT = 0.08, 0.15

# ⚠️ 校准铁律: has_flow 必须严格等于回测口径 sig_count>=2 (MFI回升/放量>1.3/OBV上行 三选二)。
# 曾经写成 "sig_count>=2 OR 当日主力净流入>0", 结果在大盘普涨日(主力净流入+364亿、213个板块
# 翻红)几乎人人满足, has_flow 命中率从回测的 29.6% 暴涨到 64.8%, 直接把 676/1172 只票打成
# "强烈提醒" —— 提醒即失效。真实净流入只能当【加分确认】, 不能当【触发条件】。


def get(url, timeout=15):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                  timeout=timeout, context=CTX).read().decode('utf-8', 'ignore')


def fnum(x, d=0.0):
    """东财停牌/退市股返回字符串 '-' , float() 会崩 —— 统一安全解析"""
    try:
        v = float(x)
        return d if v != v else v
    except (TypeError, ValueError):
        return d


def clean_nan(o):
    """写盘前清 NaN/Inf —— 否则前端 JSON.parse 失败, 整个 Tab 白屏"""
    if isinstance(o, dict):
        return {k: clean_nan(v) for k, v in o.items()}
    if isinstance(o, list):
        return [clean_nan(v) for v in o]
    if isinstance(o, float):
        return 0.0 if (o != o or o in (float('inf'), float('-inf'))) else round(o, 6)
    return o


# ---------------- 数据抓取 ----------------
def fetch_market(fid='f25', pages=30, pz=100):
    """全A行情。fid=f25 年初至今涨跌升序 / f24 近60日涨跌升序"""
    out, seen = [], set()
    for pn in range(1, pages + 1):
        u = ('https://push2delay.eastmoney.com/api/qt/clist/get?pn=%d&pz=%d&po=0&np=1&fltt=2&invt=2'
             '&fid=%s&fs=%s&fields=f12,f14,f2,f3,f24,f25,f62,f184,f100,f20'
             % (pn, pz, fid, urllib.parse.quote(ALL_FS)))
        try:
            rows = (json.loads(get(u)).get('data') or {}).get('diff') or []
        except Exception:
            break
        if not rows:
            break
        for r in rows:
            c = str(r.get('f12') or ''); n = str(r.get('f14') or '')
            if len(c) != 6 or not n or c in seen:
                continue
            if 'ST' in n.upper() or '退' in n or c[0] in '849':
                continue
            price = fnum(r.get('f2'))
            if price < 2:
                continue
            seen.add(c)
            out.append({'code': c, 'name': n, 'price': price,
                        'change': fnum(r.get('f3')), 'chg60': fnum(r.get('f24')),
                        'chg_ytd': fnum(r.get('f25')), 'inflow': fnum(r.get('f62')),
                        'inflow_pct': fnum(r.get('f184')),
                        'ind': str(r.get('f100') or '').strip(), 'mcap': fnum(r.get('f20'))})
        if len(rows) < pz:
            break
        time.sleep(0.05)
    return out


def fetch_kline(code, n=320):
    tcode = ('sh' if code[0] in '69' else 'sz') + code
    varn = 'k' + str(random.randint(0, 999999))
    url = ('https://ifzq.gtimg.cn/appstock/app/kline/kline?_var=%s&param=%s,day,,,%d'
           % (varn, tcode, n))
    for _ in range(2):
        try:
            raw = get(url); raw = raw[raw.index('=') + 1:]
            data = json.loads(raw)
            if not isinstance(data, dict):
                return []
            kd = (data.get('data') or {}).get(tcode, {})
            kl = kd.get('day') or kd.get('qfqday')
            if not kl:
                return []
            return [[k[0], float(k[1]), float(k[2]), float(k[3]), float(k[4]),
                     float(k[5]) if len(k) > 5 else 0.0] for k in kl]
        except Exception:
            time.sleep(0.1)
    return []


# ---------------- 指标 ----------------
def calc_greed(closes):
    """750日价格分位 —— 与 auto_screener.calc_greed 同口径"""
    if len(closes) < 30:
        return None
    cur = closes[-1]; look = min(len(closes) - 1, 750); hist = closes[-look - 1:-1]
    return round(sum(1 for c in hist if c < cur) / len(hist) * 1000) / 10 if hist else None


def calc_mfi(kl, period=14):
    if len(kl) < period + 2:
        return None, None
    def one(end):
        pos = neg = 0.0
        for j in range(end - period + 1, end + 1):
            tp = (kl[j][3] + kl[j][4] + kl[j][2]) / 3.0
            tp0 = (kl[j - 1][3] + kl[j - 1][4] + kl[j - 1][2]) / 3.0
            mf = tp * kl[j][5]
            if tp > tp0: pos += mf
            elif tp < tp0: neg += mf
        if neg == 0:
            return 100.0 if pos > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + pos / neg)
    return one(len(kl) - 1), one(len(kl) - 2)


def calc_vr(kl, n=20):
    if len(kl) < n + 1:
        return None
    ma = sum(k[5] for k in kl[-n - 1:-1]) / n
    return kl[-1][5] / ma if ma > 0 else None


def calc_obv_slope(kl, n=5):
    if len(kl) < n + 2:
        return None
    obv = 0.0; seq = []
    for j in range(len(kl) - n - 1, len(kl)):
        if kl[j][2] > kl[j - 1][2]: obv += kl[j][5]
        elif kl[j][2] < kl[j - 1][2]: obv -= kl[j][5]
        seq.append(obv)
    return seq[-1] - seq[0]


def calc_atr_pct(kl, n=14):
    if len(kl) < n + 1:
        return None
    trs = []
    for j in range(len(kl) - n, len(kl)):
        h, l, pc = kl[j][3], kl[j][4], kl[j - 1][2]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    atr = sum(trs) / len(trs)
    return atr / kl[-1][2] if kl[-1][2] else None


def load_sector_flow():
    """板块真实资金流(sector_flow.json)。⚠️ net1/net5 单位已经是【亿元】, 不要再除 1e8

    返回 {板块名: {net1, net5, rank, state, chg}}。
    这是「通过资金判断板块」的直接依据 —— 比用同业票放量占比做代理准确得多。
    """
    p = os.path.join(HERE, 'sector_flow.json')
    if not os.path.exists(p):
        return {}
    try:
        d = json.load(open(p, encoding='utf-8'))
    except Exception:
        return {}
    out = {}
    # 概念在前、行业在后 —— 个股 f100 给的是行业名, 同名时必须让行业口径覆盖概念口径
    # (concepts 的 rank 是 1..60 独立排名, 混进来会让概念第5名冒充"全市场前100")
    for s in (d.get('concepts') or []) + (d.get('sectors') or []):
        nm = (s.get('name') or '').strip()
        if not nm:
            continue
        out[nm] = {'net1': fnum(s.get('net1')), 'net5': fnum(s.get('net5')),
                   'rank': s.get('rank'), 'state': s.get('state') or '',
                   'chg': fnum(s.get('chg'))}
    return out


def get_regime():
    """沪深300 近20日涨跌幅 → up/side/down (与回测同口径, 当期可知)"""
    try:
        varn = 'r' + str(random.randint(0, 999999))
        u = 'https://ifzq.gtimg.cn/appstock/app/kline/kline?_var=%s&param=sh000300,day,,,40' % varn
        raw = get(u); raw = raw[raw.index('=') + 1:]
        kd = (json.loads(raw).get('data') or {}).get('sh000300', {})
        kl = kd.get('day') or kd.get('qfqday') or []
        if len(kl) < 21:
            return {'trend': 'na', 'chg20': 0.0}
        c0, c1 = float(kl[-21][2]), float(kl[-1][2])
        chg = (c1 - c0) / c0 * 100
        return {'trend': 'down' if chg < -3 else ('up' if chg > 3 else 'side'),
                'chg20': round(chg, 2), 'close': round(c1, 2)}
    except Exception:
        return {'trend': 'na', 'chg20': 0.0}


# ---------------- 主流程 ----------------
def main():
    t0 = time.time()
    print('[1/5] 拉取全市场行情...')
    ytd = fetch_market('f25')
    print('      年初至今升序 %d 只' % len(ytd))
    d60 = fetch_market('f24', pages=12)
    print('      近60日升序 %d 只' % len(d60))
    by_code = {r['code']: r for r in ytd}
    for r in d60:
        by_code.setdefault(r['code'], r)
    # 预筛: 今年跌得多 或 近60日跌得多 —— 覆盖"长期低迷"与"近期急杀"两类低位
    pool = sorted(by_code.values(), key=lambda x: x['chg_ytd'])[:1000]
    extra = sorted([r for r in by_code.values() if r['code'] not in {p['code'] for p in pool}],
                   key=lambda x: x['chg60'])[:500]
    cand = pool + extra
    print('      预筛候选 %d 只 (全A %d)' % (len(cand), len(by_code)))

    print('[2/5] 拉取K线并计算贪婪指数/资金指标...')
    def work(r):
        kl = fetch_kline(r['code'])
        if not kl or len(kl) < 60:
            return None
        closes = [k[2] for k in kl]
        g = calc_greed(closes)
        if g is None or g >= GREED_LOW:
            return None
        mfi, mfi_p = calc_mfi(kl)
        vr = calc_vr(kl); ob = calc_obv_slope(kl); atr = calc_atr_pct(kl)
        r = dict(r)
        r.update({'greed': g, 'mfi': mfi, 'mfi_prev': mfi_p, 'vr': vr,
                  'obv_up': bool(ob is not None and ob > 0),
                  'atr_pct': atr, 'kl_last': kl[-1][0]})
        # 三个可回溯资金信号
        r['sig_mfi'] = bool(mfi is not None and mfi_p is not None and mfi > mfi_p and mfi > 30)
        r['sig_vr'] = bool(vr is not None and vr > 1.3)
        r['sig_obv'] = r['obv_up']
        r['sig_count'] = int(r['sig_mfi']) + int(r['sig_vr']) + int(r['sig_obv'])
        # 真实主力净流入(当日快照) —— 只作加分确认, 不参与 has_flow 触发, 见文件头校准铁律
        r['sig_real'] = bool(r['inflow'] > 0 and r['inflow_pct'] > 2)
        r['has_flow'] = bool(r['sig_count'] >= MIN_SIG)
        return r

    lows = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        for i, res in enumerate(ex.map(work, cand)):
            if res:
                lows.append(res)
            if (i + 1) % 300 == 0:
                print('      ...%d/%d  已命中低位 %d' % (i + 1, len(cand), len(lows)))
    print('      贪婪<%.0f 的低位股 %d 只' % (GREED_LOW, len(lows)))

    print('[3/5] 计算板块共振...')
    sector_net = load_sector_flow()
    ind_tot, ind_flow = {}, {}
    for r in lows:
        k = r['ind'] or '其他'
        ind_tot[k] = ind_tot.get(k, 0) + 1
        if r['has_flow']:
            ind_flow[k] = ind_flow.get(k, 0) + 1
    ind_ratio = {k: (ind_flow.get(k, 0) / v) for k, v in ind_tot.items() if v >= 3}

    regime = get_regime()
    print('      大盘 regime=%s (沪深300 近20日 %+.2f%%)' % (regime['trend'], regime['chg20']))

    print('[4/5] 分级...')
    core, strong, watch, quiet = [], [], [], []
    for r in lows:
        ind = r['ind'] or '其他'
        ratio = ind_ratio.get(ind)
        sec = sector_net.get(ind) or {}
        net = sec.get('net1')
        r['sec_ratio'] = round(ratio, 3) if ratio is not None else None
        r['sec_net'] = round(net, 2) if net is not None else None
        r['sec_net5'] = round(sec.get('net5'), 2) if sec.get('net5') is not None else None
        r['sec_rank'] = sec.get('rank')
        r['sec_state'] = sec.get('state') or ''
        r['sec_peers'] = ind_tot.get(ind, 0)
        # 板块共振 = 回测口径 AND 真实资金加严, 两个都要:
        #   ① 同业低位票资金信号占比 >50%  —— 这一条才是 56.2% 胜率对应的回测定义
        #   ② 该板块当日真实净流入为正 且 排名进全市场前100(共496个板块) —— 加严, 剔除
        #      "小行业只有3只低位票、轻易 100%" 的伪共振
        rk = sec.get('rank')
        r['sec_money_ok'] = bool(net is not None and net > 0 and
                                 isinstance(rk, (int, float)) and rk <= SEC_RANK_TOP)
        r['sec_ratio_ok'] = bool(ratio is not None and ratio > SEC_RESONANCE)
        r['sec_resonance'] = bool(r['sec_ratio_ok'] and r['sec_money_ok'])
        price = r['price']
        stop_pct = max(STOP_PCT, 2 * (r['atr_pct'] or 0.04))
        r['stop_pct'] = round(stop_pct, 4)
        r['stop'] = round(price * (1 - stop_pct), 3)
        r['target'] = round(price * (1 + TP_PCT), 3)
        r['hold_days'] = HOLD_DAYS
        sigs = []
        if r['sig_mfi']: sigs.append('MFI回升')
        if r['sig_vr']: sigs.append('放量%.1f倍' % (r['vr'] or 0))
        if r['sig_obv']: sigs.append('OBV上行')
        if r['sig_real']: sigs.append('主力净入%.2f亿' % (r['inflow'] / 1e8))
        r['signals'] = sigs

        # 核心档 = 强烈提醒档 + 两个【已验证有效】的加严维度(板块>80% & 贪婪<10)
        r['is_core'] = bool(r['has_flow'] and r['sec_money_ok'] and
                            ratio is not None and ratio > CORE_SEC and r['greed'] < CORE_GREED)

        if r['is_core']:
            r['level'] = 'CORE'
            r['win_ref'] = 59.0
            r['reason'] = ('🔴 贪婪仅%.1f%%(极冷) + %s + %s板块%.0f%%同业同步进钱(真实净流入%.2f亿/全市场第%s)'
                           ' → 回测最强档: 胜率59.0%%/20日超额+3.34%%(n=312)'
                           % (r['greed'], '·'.join(sigs), ind, ratio * 100, net, rk))
            core.append(r)
        elif r['has_flow'] and r['sec_resonance']:
            r['level'] = 'STRONG'
            r['win_ref'] = 56.2
            r['reason'] = ('贪婪%.1f%%低位 + %s + 板块共振(%s同业%.0f%%的低位票同步进钱, 板块真实净流入%.2f亿/全市场第%s)'
                           ' → 回测同档胜率56.2%%/20日超额+1.77%%'
                           % (r['greed'], '·'.join(sigs), ind, ratio * 100, net, rk))
            strong.append(r)
        elif r['has_flow']:
            miss = []
            if not r['sec_ratio_ok']:
                miss.append('同业跟进不足%s' % (('(%.0f%%)' % (ratio * 100)) if ratio is not None else ''))
            if not r['sec_money_ok']:
                miss.append('板块真实资金%s' % ('净流出' if (net or 0) < 0 else '未进前100'))
            r['level'] = 'WATCH'
            r['win_ref'] = 51.5
            r['reason'] = ('贪婪%.1f%%低位 + %s, 但板块未共振(%s) → 回测同档胜率51.5%%/超额+0.97%%'
                           % (r['greed'], '·'.join(sigs), '、'.join(miss) or '数据缺失'))
            watch.append(r)
        else:
            r['level'] = 'QUIET'
            r['win_ref'] = 48.9
            r['reason'] = '贪婪%.1f%%低位但无资金进入 —— 无人问津, 回测胜率仅48.9%%(≈基线), 不建议动' % r['greed']
            quiet.append(r)

    # 排序分: 板块真金 > 个股信号强度 > 真实净流入确认 > 越低位越靠前
    def score(x):
        s = 0.0
        if x.get('sec_money_ok'):
            s += 30 + min(20, (x.get('sec_net') or 0) / 10.0)
        s += 8 * x['sig_count']
        s += 10 * (x['sec_ratio'] or 0)
        if x['sig_real']:
            s += 8
        s += (GREED_LOW - x['greed']) * 0.3
        return s
    for r in lows:
        r['score'] = round(score(r), 2)
    core.sort(key=lambda x: -x['score'])
    strong.sort(key=lambda x: -x['score']); watch.sort(key=lambda x: -x['score'])
    quiet.sort(key=lambda x: x['greed'])

    def diversify(arr, n, per_ind=2):
        """展示列表按行业限流 —— 板块共振是这套逻辑的核心条件, 天然会让同一板块的票
        霸榜(实测核心档 Top10 里 6 只半导体)。全买等于单押一个板块, 与观察池"单板块
        ≤6/20"的集中度铁律相悖。这里只限制【展示】, 完整数量仍在 summary 里如实给出。"""
        out, cnt, spill = [], {}, []
        for r in arr:
            k = r['ind'] or '其他'
            if cnt.get(k, 0) < per_ind:
                cnt[k] = cnt.get(k, 0) + 1; out.append(r)
            else:
                spill.append(r)
            if len(out) >= n:
                return out
        return (out + spill)[:n]

    # 板块热力: 同业低位票资金占比 × 真实板块净流入
    sec_rank = []
    for k, v in ind_tot.items():
        if v < 3:
            continue
        sec = sector_net.get(k) or {}
        sec_rank.append({'ind': k, 'low_count': v, 'flow_count': ind_flow.get(k, 0),
                         'ratio': round(ind_flow.get(k, 0) / v, 3),
                         'net': sec.get('net1'), 'net5': sec.get('net5'),
                         'rank': sec.get('rank'), 'state': sec.get('state') or ''})
    sec_rank.sort(key=lambda x: (-(x['net'] if x['net'] is not None else -9e9), -x['ratio']))

    # 狼大发言(参考信息, 不参与打分)
    voice = {}
    vp = os.path.join(HERE, 'wolf_voice.json')
    if os.path.exists(vp):
        try:
            v = json.load(open(vp, encoding='utf-8'))
            voice = {'generated': v.get('generated'), 'mood': v.get('overall_mood'),
                     'hot_tags': v.get('hot_tags', [])[:6],
                     'posts': (v.get('posts') or [])[:6], 'note': v.get('note')}
        except Exception:
            voice = {}

    out = {
        'generated': time.strftime('%Y-%m-%d %H:%M'),
        'regime': regime,
        'params': {'greed_low': GREED_LOW, 'hold_days': HOLD_DAYS, 'min_sig': MIN_SIG,
                   'sec_resonance': SEC_RESONANCE, 'sec_rank_top': SEC_RANK_TOP,
                   'stop_base': STOP_PCT, 'target': TP_PCT},
        'backtest': {
            'window': '2021-08 ~ 2026-08 (5年)', 'stocks': 291, 'checkpoints': 63002,
            'cost': '0.25%往返', 'hold': '20日',
            'rows': [
                {'k': 'S0 全市场基线', 'n': 63002, 'win': 46.8, 'ret': 0.74, 'ex': 0.0},
                {'k': '贪婪<35(仅低位, 无资金要求)', 'n': 26869, 'win': 49.7, 'ret': 1.39, 'ex': 0.65},
                {'k': '+个股资金(3选2)', 'n': 7955, 'win': 51.5, 'ret': 1.71, 'ex': 0.97},
                {'k': '+板块共振>50% 🟠强烈', 'n': 2440, 'win': 56.2, 'ret': 2.51, 'ex': 1.77},
                {'k': '+板块>80%&贪婪<10 🔴核心', 'n': 312, 'win': 59.0, 'ret': 4.08, 'ex': 3.34},
            ],
            # 核心档分环境 —— 震荡市几乎无超额, 必须如实展示
            'by_regime': [
                {'k': '上涨市', 'n': 110, 'win': 60.9, 'ex': 2.97, 'se': 1.43},
                {'k': '震荡市', 'n': 116, 'win': 49.1, 'ex': 0.15, 'se': 1.05},
                {'k': '下跌市', 'n': 86, 'win': 69.8, 'ex': 6.86, 'se': 1.65},
            ],
            # 加严单调性检验: 哪些维度真有用, 哪些是噪音
            'monotonic': [
                {'k': '板块共振 <33%', 'win': 48.7, 'ok': True},
                {'k': '板块共振 33~50%', 'win': 49.7, 'ok': True},
                {'k': '板块共振 >50%', 'win': 56.2, 'ok': True},
                {'k': '板块共振 >80%', 'win': 57.1, 'ok': True},
                {'k': '贪婪 20~35', 'win': 55.0, 'ok': True},
                {'k': '贪婪 <10', 'win': 58.4, 'ok': True},
                {'k': '信号3个全中(无效)', 'win': 55.2, 'ok': False},
                {'k': '放量>2倍(反效果)', 'win': 51.5, 'ok': False},
            ],
        },
        'regime_warn': (
            '⚠️ 当前为震荡市(沪深300近20日%+.2f%%)。回测显示核心档在震荡市胜率仅49.1%%、'
            '超额+0.15%%(±1.05se)，等于没有优势 —— 建议只做小仓试错或直接空仓等待。'
            % regime['chg20'] if regime['trend'] == 'side' else
            ('✅ 当前为上涨市(沪深300近20日%+.2f%%)。核心档历史胜率60.9%%/超额+2.97%%，环境顺风。'
             % regime['chg20'] if regime['trend'] == 'up' else
             ('🔥 当前为下跌市(沪深300近20日%+.2f%%)。核心档历史胜率69.8%%/超额+6.86%% —— '
              '恐慌中逆势低吸反而是这套逻辑最有效的环境(样本n=86偏小,仓位仍需控制)。'
              % regime['chg20'] if regime['trend'] == 'down' else ''))),
        'summary': {'low_total': len(lows), 'core': len(core), 'strong': len(strong),
                    'watch': len(watch), 'quiet': len(quiet),
                    'scanned': len(cand), 'universe': len(by_code)},
        'sectors': sec_rank[:12],
        'core': diversify(core, 12), 'strong': diversify(strong, 18),
        'watch': diversify(watch, 15, 3), 'quiet': quiet[:12],
        'voice': voice,
        'elapsed': round(time.time() - t0, 1),
    }
    p = os.path.join(HERE, 'greed_flow_radar.json')
    json.dump(clean_nan(out), open(p, 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, allow_nan=False)
    print('[5/5] OK greed_flow_radar.json')
    print('      🔴核心 %d · 🟠强烈 %d · 🟡关注 %d · ⚪无人问津 %d  (低位股共%d, 耗时%.0fs)'
          % (len(core), len(strong), len(watch), len(quiet), len(lows), out['elapsed']))
    print('      ' + out['regime_warn'])
    for tag, arr in (('🔴', out['core'][:10]), ('🟠', out['strong'][:5])):
        for r in arr:
            print('      %s %s %-6s 贪婪%5.1f%%  %-22s 板块%s 同业%3.0f%% 真金%+.1f亿(第%s)' %
                  (tag, r['code'], r['name'], r['greed'], '·'.join(r['signals'][:2]), r['ind'],
                   (r['sec_ratio'] or 0) * 100, r['sec_net'] or 0, r['sec_rank']))


if __name__ == '__main__':
    main()
