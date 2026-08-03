# -*- coding: utf-8 -*-
"""
李大霄历史底部研判体系模块
==================================================================
融合 2015 婴儿底 / 2019 年 2440 大底 / 2022 年 3000 点 三套经典标准，
适配 2026 全面注册制环境做量化修订，输出：

  1) 上证50 估值温度计（PE/PB 当前值 + 历年分位）
     —— 对应「通过对比历年 PE/PB 判断入市时机」
  2) 蓝筹低值发现（蓝筹股当前 PE/PB 在其自身历史中的分位，标注历史低位）
     —— 对应「发现蓝筹股的低值，判断买入蓝筹股的时机」
  3) 五维研判 + 综合结论（估值维度自动算，其余维度给人工确认位）

输出 li_daxiao.json（带 NaN 清洗，allow_nan=False，供前端 fetch 渲染）。

数据源：
  - 上证50 指数级 PE/PB 历史：akshare stock_index_pe_lg / stock_index_pb_lg（沙箱可达）
  - 蓝筹个股历史 PE/PB：akshare stock_zh_valuation_baidu（云端 Actions 可达；沙箱偶发限流，
    失败则降级为「蓝筹 JSON 的 1 年分位 pe_pct + 横截面便宜度」）
==================================================================
"""
import json, os, time, math
import akshare as ak
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SZ50_PE_CACHE = os.path.join(HERE, 'sz50_pe_history.json')
SZ50_PB_CACHE = os.path.join(HERE, 'sz50_pb_history.json')
BLUECHIP_CACHE = os.path.join(HERE, 'bluechip_hist_cache.json')
BLUE = os.path.join(HERE, 'blue_chip_result.json')
OUT = os.path.join(HERE, 'li_daxiao.json')
CACHE_SEC = 6 * 3600

# 李大霄 2026 修订三档估值锚（基于上证50 静态PE）
TIER_EXTREME, TIER_MILD, TIER_NEAR = 8.5, 10.0, 10.0  # PE<=8.5 极致 / 8.5~10 温和 / >10 接近底部


def log(*a):
    print('[li_daxiao]', *a)


def clean_nan(obj):
    """递归把 NaN / Infinity 换成 None，避免 json.dump 写出浏览器解析不了的 NaN。"""
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: clean_nan(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [clean_nan(v) for v in obj]
    return obj


def pct_of(vals, cur):
    """当前值 cur 在 vals 历史中的分位（0~100，越低越便宜）。"""
    s = [v for v in vals if v is not None and not (isinstance(v, float) and math.isnan(v)) and v > 0]
    if not s or cur is None:
        return None
    return float(np.mean(np.array(s) < cur) * 100)


def fetch_index(symbol, kind):
    """取上证50 指数级 PE 或 PB 全历史；带 6h 缓存。返回 (rows, ts, src)。
    src ∈ {'realtime' 实时拉取, 'cache_fallback' 拉取失败回退过期缓存, 'empty' 无数据}。"""
    cache = SZ50_PE_CACHE if kind == 'pe' else SZ50_PB_CACHE
    if os.path.exists(cache):
        try:
            d = json.load(open(cache, encoding='utf-8'))
            if time.time() - d.get('ts', 0) < CACHE_SEC:
                return d['rows'], d['ts'], 'cache_hit'
        except Exception:
            pass
    try:
        if kind == 'pe':
            df = ak.stock_index_pe_lg(symbol=symbol)
            col = '静态市盈率'
        else:
            df = ak.stock_index_pb_lg(symbol=symbol)
            col = '市净率'
        rows = [{'date': str(r[0]), 'v': (float(r[1]) if r[1] is not None else None)}
                for r in df[['日期', col]].itertuples(index=False, name=None)]
        json.dump({'ts': time.time(), 'rows': rows}, open(cache, 'w', encoding='utf-8'))
        return rows, time.time(), 'realtime'
    except Exception as e:
        # 拉取失败：尽量用过期缓存兜底，避免整体崩溃导致 li_daxiao.json 缺失
        if os.path.exists(cache):
            try:
                d = json.load(open(cache, encoding='utf-8'))
                log('fetch_index 失败(%s)，用本地缓存兜底: %s' % (e, cache))
                return d['rows'], d.get('ts', 0), 'cache_fallback'
            except Exception:
                pass
        log('fetch_index 失败(%s)，无缓存可兜底，返回空' % e)
        return [], 0, 'empty'



def get_sz50():
    pe_rows, _, pe_src = fetch_index('上证50', 'pe')
    pb_rows, _, pb_src = fetch_index('上证50', 'pb')
    src = 'cache_fallback' if ('cache_fallback' in (pe_src, pb_src)) else (
        'empty' if ('empty' in (pe_src, pb_src)) else 'realtime')
    pe_vals = [r['v'] for r in pe_rows if r['v'] is not None]
    pb_vals = [r['v'] for r in pb_rows if r['v'] is not None]
    cur_pe = pe_vals[-1] if pe_vals else None
    cur_pb = pb_vals[-1] if pb_vals else None
    # 近5年 / 近10年 窗口（约 252*N 交易日）
    pe5 = pe_vals[-252 * 5:] if len(pe_vals) >= 252 * 5 else pe_vals
    pe10 = pe_vals[-252 * 10:] if len(pe_vals) >= 252 * 10 else pe_vals
    pb5 = pb_vals[-252 * 5:] if len(pb_vals) >= 252 * 5 else pb_vals
    pb10 = pb_vals[-252 * 10:] if len(pb_vals) >= 252 * 10 else pb_vals
    # 档位（基于 PE）
    if cur_pe is None:
        tier = '未知'
    elif cur_pe <= TIER_EXTREME:
        tier = '极致底部'
    elif cur_pe <= TIER_MILD:
        tier = '温和底部'
    else:
        tier = '接近底部'
    return {
        'pe': round(cur_pe, 2) if cur_pe is not None else None,
        'pb': round(cur_pb, 2) if cur_pb is not None else None,
        'pe_pct_all': round(pct_of(pe_vals, cur_pe), 1) if cur_pe is not None else None,
        'pe_pct_5y': round(pct_of(pe5, cur_pe), 1) if cur_pe is not None else None,
        'pe_pct_10y': round(pct_of(pe10, cur_pe), 1) if cur_pe is not None else None,
        'pb_pct_all': round(pct_of(pb_vals, cur_pb), 1) if cur_pb is not None else None,
        'pb_pct_5y': round(pct_of(pb5, cur_pb), 1) if cur_pb is not None else None,
        'pe_min': round(min(pe_vals), 2) if pe_vals else None,
        'pe_max': round(max(pe_vals), 2) if pe_vals else None,
        'pe_med': round(float(np.median(pe_vals)), 2) if pe_vals else None,
        'pb_min': round(min(pb_vals), 2) if pb_vals else None,
        'pb_med': round(float(np.median(pb_vals)), 2) if pb_vals else None,
        'tier': tier,
        'tier_pe': round(cur_pe, 2) if cur_pe is not None else None,
        'asof': pe_rows[-1]['date'] if pe_rows else None,
        'source': src,
    }


def get_bluechip_hist(code, indicator):
    """取单只股票历史估值分位；失败返回 None（调用方降级）。"""
    try:
        df = ak.stock_zh_valuation_baidu(symbol='sh' + code if code.startswith('6') else 'sz' + code,
                                         indicator=indicator)
        if df is None or len(df) == 0:
            return None
        vals = df.iloc[:, 1].dropna().astype(float).tolist()
        cur = vals[-1]
        return {'cur': float(cur), 'pct': pct_of(vals, cur), 'n': len(vals)}
    except Exception:
        return None


def load_bluehist_cache():
    if os.path.exists(BLUECHIP_CACHE):
        try:
            return json.load(open(BLUECHIP_CACHE, encoding='utf-8'))
        except Exception:
            pass
    return {}


def get_bluechips():
    """蓝筹低值发现：对蓝筹 JSON 每只算 PE/PB 历史分位；失败降级为 1年分位 + 横截面。"""
    if not os.path.exists(BLUE):
        return []
    d = json.load(open(BLUE, encoding='utf-8'))
    picks = d.get('picks', [])
    cache = load_bluehist_cache()
    out = []
    for p in picks:
        code = p.get('code')
        name = p.get('name')
        pe = p.get('pe')
        pb = p.get('pb')
        pe_pct_1y = p.get('pe_pct')  # 已有 1 年分位
        # 尝试拉个股历史
        ch = cache.get(code, {})
        need_refresh = (time.time() - ch.get('ts', 0) > CACHE_SEC)
        if need_refresh:
            pe_h = get_bluechip_hist(code, 'pe')
            pb_h = get_bluechip_hist(code, 'pb')
            ch = {'ts': time.time(),
                  'pe_pct': pe_h['pct'] if pe_h else None,
                  'pb_pct': pb_h['pct'] if pb_h else None,
                  'src': 'hist' if (pe_h or pb_h) else 'fallback'}
            cache[code] = ch
        pe_pct_hist = ch.get('pe_pct')
        pb_pct_hist = ch.get('pb_pct')
        src = ch.get('src', 'fallback')
        # 综合「低值」判定：个股历史分位 < 25%，或 1年分位 < 0.30
        low = False
        cheap_score = None
        if pe_pct_hist is not None:
            cheap_score = pe_pct_hist
            low = pe_pct_hist < 25
        elif pe_pct_1y is not None:
            cheap_score = pe_pct_1y * 100
            low = pe_pct_1y < 0.30
        out.append({
            'code': code, 'name': name, 'pe': pe, 'pb': pb,
            'pe_pct_hist': round(pe_pct_hist, 1) if pe_pct_hist is not None else None,
            'pb_pct_hist': round(pb_pct_hist, 1) if pb_pct_hist is not None else None,
            'pe_pct_1y': round(pe_pct_1y * 100, 1) if pe_pct_1y is not None else None,
            'low': low, 'cheap_score': cheap_score, 'src': src,
        })
    # 横截面兜底：若全部无历史分位，用 PE 在列表内排序作为便宜度
    if all(b['cheap_score'] is None for b in out) and out:
        pes = [b['pe'] for b in out if b['pe']]
        if pes:
            lo, hi = min(pes), max(pes)
            for b in out:
                if b['pe']:
                    b['cheap_score'] = round((b['pe'] - lo) / (hi - lo) * 100, 1) if hi > lo else 50.0
                    b['low'] = b['cheap_score'] < 30
                    b['src'] = 'cross'
    out.sort(key=lambda b: (b['cheap_score'] if b['cheap_score'] is not None else 999))
    json.dump(cache, open(BLUECHIP_CACHE, 'w', encoding='utf-8'))
    return out


def judge(sz50, blues):
    """五维研判 + 综合结论。估值维度自动；其余给人工确认位。"""
    tier = sz50.get('tier')
    pe = sz50.get('pe')
    # 估值维度
    if tier == '极致底部':
        val_status, val_text = 'pass', '上证50 PE≤8.5，处极致底部区间'
    elif tier == '温和底部':
        val_status, val_text = 'pass', '上证50 PE 8.5~10，处温和底部区间'
    elif tier == '接近底部':
        val_status, val_text = 'watch', '上证50 PE>10，仅处接近底部区间，估值未达极致'
    else:
        val_status, val_text = 'unknown', '估值数据不可用'
    low_count = sum(1 for b in blues if b.get('low'))
    # 其余四维度（数据源不可达，留人工确认位）
    dims = {
        '估值': {'status': val_status, 'text': val_text, 'auto': True},
        '杠杆': {'status': 'unknown', 'text': '两融余额数据源不可达，需结合两融数据人工确认'},
        '资金': {'status': 'unknown', 'text': '外资/险资/产业资本增持回购力度，需结合公开数据人工确认'},
        '供给': {'status': 'unknown', 'text': 'IPO 节奏与解禁规模，需结合发行安排人工确认'},
        '政策': {'status': 'unknown', 'text': '货币宽松与活跃资本市场政策，需结合最新政策人工确认'},
    }
    # 综合结论
    if tier == '极致底部' and low_count >= 3:
        level, action = '中长期底部', '可扩大优质标的观察池，分批布局；优先低估值、稳定盈利龙头'
    elif tier in ('极致底部', '温和底部'):
        level, action = '临近底部', '可轻仓试错、严格选股；仅限优质龙头，禁止题材垃圾股'
    else:
        level, action = '谨慎 / 控制仓位', '优先控仓，仅优质龙头可小幅分批；禁止一次性满仓，防二次下探'
    verdict = {
        'level': level, 'action': action,
        'blue_low_count': low_count, 'blue_total': len(blues),
        'tier': tier, 'pe': pe,
    }
    return dims, verdict


def main():
    t0 = time.time()
    try:
        sz50 = get_sz50()
        log('上证50:', sz50.get('pe'), 'PE 全历史分位', sz50.get('pe_pct_all'), '% 档位', sz50.get('tier'))
        blues = get_bluechips()
        log('蓝筹低值扫描 %d 只，历史低位 %d 只' % (len(blues), sum(1 for b in blues if b.get('low'))))
        dims, verdict = judge(sz50, blues)
        out = clean_nan({
            'generated': time.strftime('%Y-%m-%d %H:%M'),
            'source': sz50.get('source', 'realtime'),
            'sz50': sz50,
            'bluechips': blues,
            'dims': dims,
            'verdict': verdict,
        })
        with open(OUT, 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, allow_nan=False, indent=1)
        log('write', OUT, '%.1fs' % (time.time() - t0))
    except Exception as e:
        # 兜底：无论如何都写一份最小可用 JSON，保证前端/同步不崩、li_daxiao.json 不缺失
        log('FATAL:', e)
        fb = clean_nan({
            'generated': time.strftime('%Y-%m-%d %H:%M'),
            'error': str(e),
            'sz50': {'tier': '未知', 'pe': None, 'asof': None},
            'bluechips': [],
            'dims': {'估值': {'status': 'unknown', 'text': '数据暂不可达，请稍后重试'}},
            'verdict': {'level': '数据暂不可达', 'action': '李大霄模块数据获取失败，请稍后查看',
                        'blue_low_count': 0, 'blue_total': 0, 'tier': '未知', 'pe': None},
        })
        with open(OUT, 'w', encoding='utf-8') as f:
            json.dump(fb, f, ensure_ascii=False, allow_nan=False, indent=1)
        log('write fallback', OUT, '%.1fs' % (time.time() - t0))


if __name__ == '__main__':
    main()
