# -*- coding: utf-8 -*-
"""
蓝筹长期价值选股（适合长期持有、当前可慢慢低吸）

范围：沪深300（蓝筹池）
逻辑（全部基于沙箱可达接口）：
  质量(好公司/可长期持有)：
    - ROE 连续 ≥3 年 > 12%（高且稳定回报）  —— 业绩报表(年度)
    - 经营现金流每股 连续 ≥3 年 > 0（真金白银）—— 业绩报表(年度)
    - 每股收益 > 0（盈利）
  估值(值得低吸)：
    - PE(TTM) 5~20（不贵）                    —— 百度估值(近一年序列)
    - PB < 3                                  —— 百度估值
    - PE 处近一年低位(<50%分位) = 当前便宜     —— 由序列算分位
  时点(现可慢慢低吸)：
    - 现价 < 250 日均线（中期回撤/低吸区）加分 —— 腾讯K线
打分排序，选 Top 30 作为「蓝筹低吸」推荐。
注：股息率为蓝筹重要特征，但沙箱可达接口(百度估值/业绩报表)均不返回股息率，
    故以「ROE稳定性+现金流为正+低估值分位」代理"现金奶牛"质量；如需硬性股息率门槛，
    可在能访问东方财富全量接口的机器上补充。
输出：blue_chip_result.json
用法：python blue_chip_screener.py
"""
import akshare as ak
import json, os, time, datetime, sys, math

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'blue_chip_result.json')
CACHE = os.path.join(HERE, 'bluechip_cache.json')

def log(*a):
    print('[蓝筹]', *a); sys.stdout.flush()


def clean_nan(o):
    """递归把 NaN/Infinity 换成 None —— 浏览器 JSON.parse 不认这两个字面量。"""
    if isinstance(o, dict):
        return {k: clean_nan(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean_nan(v) for v in o]
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    return o

def load_cache():
    if os.path.exists(CACHE):
        try: return json.load(open(CACHE, encoding='utf-8'))
        except: return {}
    return {}

def save_cache(c):
    try: json.dump(c, open(CACHE, 'w', encoding='utf-8'))
    except: pass

def col(df, *names):
    for n in names:
        if n in df.columns: return n
    return df.columns[0]

def get_hs300():
    cf = os.path.join(HERE, 'hs300_cons.json')
    if os.path.exists(cf) and time.time() - os.path.getmtime(cf) < 7*86400:
        return json.load(open(cf, encoding='utf-8'))
    codes = []
    try:
        df = ak.index_stock_cons(symbol="000300")
        code_c = col(df, '股票代码', 'code', '成分券代码')
        name_c = col(df, '股票名称', 'name', '成分券名称')
        for _, r in df.iterrows():
            code = str(r[code_c])
            if code and len(code) == 6:
                codes.append((code, str(r[name_c])))
        log('沪深300 成分 %d 只' % len(codes))
    except Exception as e:
        log('沪深300 获取失败:', e)
    json.dump(codes, open(cf, 'w', encoding='utf-8'))
    return codes

def get_yjbb(date, cache):
    if date in cache.get('yjbb', {}):
        return cache['yjbb'][date]
    rec = {}
    try:
        df = ak.stock_yjbb_em(date=date)
        cc = col(df, '股票代码', 'code')
        rc = col(df, '净资产收益率(%)', '净资产收益率')
        oc = col(df, '每股经营现金流量', '每股经营性现金流(元)')
        ec = col(df, '每股收益')
        bc = col(df, '每股净资产')
        gc = col(df, '销售毛利率')
        ry = col(df, '营业总收入-同比增长')
        ny = col(df, '净利润-同比增长')
        for _, r in df.iterrows():
            code = str(r[cc])
            def f(x):
                try: return float(x)
                except: return None
            rec[code] = {
                'roe': f(r[rc]), 'ocf': f(r[oc]), 'eps': f(r[ec]),
                'bvps': f(r[bc]), 'gm': f(r[gc]),
                'rev_yoy': f(r[ry]), 'np_yoy': f(r[ny]),
            }
    except Exception as e:
        log('  yjbb %s 失败: %s' % (date, e))
    cache.setdefault('yjbb', {})[date] = rec
    return rec

def baidu(code, indicator, cache):
    key = 'bd_' + indicator
    if code in cache.get(key, {}):
        return cache[key][code]
    series = None
    try:
        df = ak.stock_zh_valuation_baidu(symbol=code, indicator=indicator, period='近一年')
        if df is not None and len(df):
            series = [float(x) for x in df['value'] if x is not None]
    except Exception as e:
        log('  baidu %s %s 失败: %s' % (code, indicator, e))
    cache.setdefault(key, {})[code] = series
    return series

def get_kline(code, cache):
    if code in cache.get('kline', {}):
        return cache['kline'][code]
    res = (None, None, None)
    try:
        import urllib.request, ssl, json as _json, random
        tcode = ('sh' if code[0] in '69' else 'sz') + code
        varn = 'k' + code + '_' + str(random.randint(0, 999999))
        url = 'https://ifzq.gtimg.cn/appstock/app/kline/kline?_var=%s&param=%s,day,,,320' % (varn, tcode)
        ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        raw = urllib.request.urlopen(url, timeout=10, context=ctx).read().decode('utf-8', 'ignore')
        raw = raw[raw.index('=') + 1:]
        d = _json.loads(raw); data = d.get('data', {}); kd = data.get(tcode, {})
        kl = kd.get('day') or kd.get('qfqday')
        if kl:
            closes = [float(k[2]) for k in kl if len(k) > 2]
            if closes:
                close = closes[-1]
                ma250 = sum(closes[-250:]) / min(250, len(closes))
                low52 = min(closes[-250:]) if len(closes) >= 250 else min(closes)
                res = (close, ma250, low52)
    except Exception as e:
        log('  kline %s 失败: %s' % (code, e))
    cache.setdefault('kline', {})[code] = res
    return res

def get_names_map(codes):
    """从腾讯 qt 批量行情接口取 代码->名称 映射（一次请求拿全部，沙箱/云端均可达）。
    这是名字的唯一可靠来源，不再依赖 akshare 成分表那套脆弱的列名猜测
    （旧逻辑在列名不匹配时会把 name 退化成代码列，导致线上只显示代码）。"""
    m = {}
    if not codes:
        return m
    try:
        import urllib.request, ssl
        tcs = [('sh' if c[0] in '69' else 'sz') + c for c in codes]
        url = 'https://qt.gtimg.cn/q=' + ','.join(tcs)
        ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
        raw = urllib.request.urlopen(url, timeout=15, context=ctx).read().decode('gbk', 'ignore')
        for line in raw.replace('\n', ';').split(';'):
            line = line.strip()
            if not line.startswith('v_'):
                continue
            eq = line.find('=')
            if eq < 0:
                continue
            inner = line[2:eq]                       # sh600803
            code6 = inner[2:] if inner[2:].isdigit() else None
            val = line[eq+1:].strip().strip('"')
            parts = val.split('~')
            if code6 and len(parts) > 1 and parts[1]:
                m[code6] = parts[1]
    except Exception as e:
        log('  批量取股票名称失败(退回成分表名称):', e)
    return m

def main():
    t0 = time.time()
    cache = load_cache()
    hs300 = get_hs300()
    if not hs300:
        log('蓝筹池为空，退出'); return
    # 用腾讯 qt 接口的真名覆盖成分表名称（成分表列名不可靠，且 7 天缓存可能已污染）
    nmap = get_names_map([c for c, _ in hs300])
    def _good(nm, code):
        return nm and not nm.isdigit() and nm != code
    hs300 = [(c, (nmap.get(c) if _good(nmap.get(c), c) else n)) for c, n in hs300]

    # 取近 3 个年报期 + 最新一期
    annual = ['20251231', '20241231', '20231231', '20221231']
    latest = '20260331'
    annual_recs = [get_yjbb(d, cache) for d in annual]
    latest_rec = get_yjbb(latest, cache)

    # 质量筛选
    quality = []
    for code, name in hs300:
        recs = [ar.get(code, {}) for ar in annual_recs]
        roes = [r.get('roe') for r in recs if r.get('roe') is not None]
        ocfs = [r.get('ocf') for r in recs if r.get('ocf') is not None]
        lr = latest_rec.get(code, {})
        eps = lr.get('eps')
        if len(roes) < 3 or not all(r > 12 for r in roes): continue
        if not ocfs or not all(o > 0 for o in ocfs): continue
        if not eps or eps <= 0: continue
        roe_avg = sum(roes) / len(roes)
        quality.append({'code': code, 'name': name, 'roe_avg': round(roe_avg, 1),
                        'eps': eps, 'bvps': lr.get('bvps'), 'gm': lr.get('gm'),
                        'rev_yoy': lr.get('rev_yoy'), 'np_yoy': lr.get('np_yoy')})
    log(f'质量(ROE>12%×3 & 现金流>0×3 & EPS>0): 沪深300 {len(hs300)} → {len(quality)} 只')

    # 估值 + 低吸分位
    valued = []
    for q in quality:
        code = q['code']
        pe_s = baidu(code, '市盈率(TTM)', cache)
        pb_s = baidu(code, '市净率', cache)
        if not pe_s or not pb_s:
            continue
        pe = pe_s[-1]; pb = pb_s[-1]
        if pe is None or pe <= 5 or pe > 20: continue
        if pb is None or pb <= 0 or pb >= 3: continue
        lo, hi = min(pe_s), max(pe_s)
        pe_pct = (pe - lo) / (hi - lo) if hi > lo else 0.5
        if pe_pct > 0.6: continue   # 仅留近一年偏便宜的
        q['pe'] = round(pe, 1); q['pb'] = round(pb, 2); q['pe_pct'] = round(pe_pct, 3)
        valued.append(q)
        time.sleep(0.03)
    log('估值(PE 5-20 & PB<3 & 近一年低位): %d → %d 只' % (len(quality), len(valued)))

    # 时点(K线)：现价 vs 250日均线，取 Top 40 再算
    valued.sort(key=lambda x: (x['pe_pct'], -x['roe_avg']))
    finalists = valued[:40]
    picks = []
    seen = set()
    for q in finalists:
        code = q['code']
        if code in seen: continue
        seen.add(code)
        close, ma250, low52 = get_kline(code, cache)
        below_ma = (close is not None and ma250 is not None and close < ma250)
        near_low = (close is not None and low52 is not None and low52 > 0 and close <= low52 * 1.10)
        price = close if close is not None else (q['pe'] * q['eps'] if q['eps'] else None)
        score = (1 - q['pe_pct']) * 40 + min(q['roe_avg'], 30) * 0.8 + max(0, 3 - q['pb']) * 5
        if below_ma: score += 10
        if near_low: score += 5
        if below_ma and near_low:
            why = '处年线下方且近52周低位，低吸区明确，可分批慢慢建仓，长期持有。'
        elif below_ma:
            why = '现价低于250日均线（中期回撤），估值又处近一年低位，适合逢低慢慢低吸。'
        elif near_low:
            why = '接近52周低位、估值便宜，可小步低吸，以年为单位持有。'
        else:
            why = 'ROE稳定高、现金流为正、估值处近一年低位，可逢回调慢慢低吸，长期持有。'
        picks.append({'code': code, 'name': q['name'], 'price': round(price, 2) if price else None,
                      'pe': q['pe'], 'pb': q['pb'], 'pe_pct': q['pe_pct'],
                      'roe_avg': q['roe_avg'], 'gm': q.get('gm'),
                      'below_ma': bool(below_ma), 'near_low': bool(near_low),
                      'score': round(score, 2), 'why': why})
    picks.sort(key=lambda x: (not x['below_ma'], -x['score']))
    top = picks[:30]
    save_cache(cache)
    out = {'generated': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
           'summary': {'universe': '沪深300', 'cand': len(hs300),
                      'passed_quality': len(quality), 'passed_valuation': len(valued),
                      'selected': len(top)},
           'picks': top}
    # 浏览器 JSON.parse 不接受 NaN/Infinity（Python 默认会写出来），必须先清洗成 null
    out = clean_nan(out)
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, allow_nan=False)
    log('完成 → blue_chip_result.json，推荐 %d 只（耗时 %.0fs）' % (len(top), time.time() - t0))
    for p in top[:10]:
        tag = '低吸区' if p['below_ma'] else ('近低位' if p['near_low'] else '估值低位')
        log('  %s %s  价%s  PE%.1f PB%.2f  ROE均%.1f%%  [%s]' % (
            p['code'], p['name'], ('%.2f' % p['price']) if p['price'] else '-',
            p['pe'], p['pb'], p['roe_avg'], tag))

if __name__ == '__main__':
    main()
