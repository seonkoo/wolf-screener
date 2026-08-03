# -*- coding: utf-8 -*-
"""
板块资金流向 · 每日生成 sector_flow.json

用途：给「艾略特波浪操作结论」和「综合研判」提供板块层面的资金方向，
      让买卖建议不只看个股浪型和大盘，还看"钱往哪个板块流"。

输出结构：
{
  "generated": "...",
  "market": {"main_net": 全市场主力净额(亿), "up_sectors": 净流入板块数, "down_sectors": ...,
             "breadth": 净流入板块占比, "verdict": "资金整体流入/流出/分歧"},
  "sectors": [{code,name,chg,net1(亿),net5(亿),ratio,state,rank}],
  "top_in": [...8], "top_out": [...8],
  "names": ["电力设备", ...]   # 供前端个股行业名模糊匹配
}
state: 持续流入 / 短线回流 / 短期回调 / 持续流出
"""
import urllib.request, json, time, os, math

HERE = os.path.dirname(os.path.abspath(__file__))
HDRS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://quote.eastmoney.com/'}


def get(u, timeout=25):
    return urllib.request.urlopen(urllib.request.Request(u, headers=HDRS), timeout=timeout).read().decode('utf-8', 'ignore')


def clean_nan(o):
    """写盘铁律：JSON 里绝不能出现 NaN/Infinity，否则浏览器 JSON.parse 直接炸"""
    if isinstance(o, dict):
        return {k: clean_nan(v) for k, v in o.items()}
    if isinstance(o, list):
        return [clean_nan(v) for v in o]
    if isinstance(o, float):
        return None if (math.isnan(o) or math.isinf(o)) else round(o, 4)
    return o


def fetch_boards(fs='m:90+t:2', maxn=600):
    """行业板块(m:90 t:2) / 概念板块(m:90 t:3) 资金流排行
    ⚠️ 东财单页最多返回 100 条（pz>100 无效），必须翻页，否则只拿到净流入TOP100、
       全是正数，会误判成「全市场资金100%流入」。"""
    out = []
    for pn in range(1, maxn // 100 + 2):
        u = ('https://push2delay.eastmoney.com/api/qt/clist/get?pn=%d&pz=100&po=1&np=1&fltt=2&invt=2'
             '&fid=f62&fs=%s&fields=f12,f14,f2,f3,f62,f184,f164,f165,f166,f167'
             % (pn, urllib.parse.quote(fs, safe='')))
        try:
            d = json.loads(get(u))
            diff = d.get('data', {}).get('diff', []) or []
        except Exception as e:
            print('  [warn] 板块拉取失败 %s pn=%d: %s' % (fs, pn, e))
            break
        if not diff:
            break
        out += diff
        if len(out) >= (d.get('data', {}).get('total') or 0):
            break
    return out


import urllib.parse  # noqa: E402  (fetch_boards 里用到)


def build_sectors(diff):
    out = []
    for r in diff:
        try:
            net1 = float(r.get('f62') or 0) / 1e8          # 今日主力净额（亿）
            net5 = float(r.get('f164') or 0) / 1e8         # 5日主力净额（亿）
            ratio = float(r.get('f184') or 0)              # 今日主力净占比 %
            chg = float(r.get('f3') or 0)
        except Exception:
            continue
        if net1 > 0 and net5 > 0:
            state = '持续流入'
        elif net1 > 0 and net5 <= 0:
            state = '短线回流'
        elif net1 <= 0 and net5 > 0:
            state = '短期回调'
        else:
            state = '持续流出'
        out.append({'code': r.get('f12'), 'name': r.get('f14'), 'chg': round(chg, 2),
                    'net1': round(net1, 2), 'net5': round(net5, 2),
                    'ratio': round(ratio, 2), 'state': state})
    out.sort(key=lambda x: -x['net1'])
    for i, s in enumerate(out):
        s['rank'] = i + 1
    return out


def main():
    print('[1] 拉取行业板块资金流...')
    ind = build_sectors(fetch_boards('m:90+t:2'))
    print('    行业板块:', len(ind))
    print('[2] 拉取概念板块资金流...')
    con = build_sectors(fetch_boards('m:90+t:3'))
    print('    概念板块:', len(con))

    # 大盘整体资金：板块加总会重复计算（电子/半导体/数字芯片设计是嵌套多级），
    # 必须用沪深两市口径。akshare 优先，失败回退东财指数资金流。
    print('[3] 拉取沪深两市整体资金流...')
    total = None; net5 = None; ratio = None
    try:
        import akshare as ak
        df = ak.stock_market_fund_flow()
        col = [c for c in df.columns if '主力净流入-净额' in c][0]
        rcol = [c for c in df.columns if '主力净流入-净占比' in c][0]
        total = float(df[col].iloc[-1]) / 1e8
        ratio = float(df[rcol].iloc[-1])
        net5 = float(df[col].iloc[-5:].sum()) / 1e8
    except Exception as e:
        print('  [warn] akshare 大盘资金流失败，回退东财:', e)
        try:
            u = ('https://push2delay.eastmoney.com/api/qt/ulist.np/get?fltt=2'
                 '&secids=1.000001,0.399001&fields=f12,f14,f62,f184')
            d = json.loads(get(u))['data']['diff']
            total = sum(float(r['f62']) for r in d) / 1e8
            ratio = sum(float(r['f184']) for r in d) / max(len(d), 1)
        except Exception as e2:
            print('  [warn] 东财也失败:', e2)

    ups = sum(1 for s in ind if s['net1'] > 0)
    n = max(len(ind), 1)
    breadth = ups / n
    t = total if total is not None else 0.0
    if t > 100 and breadth > 0.5:
        verdict, tone = '资金整体流入（进攻窗口，可提高仓位）', 'in'
    elif t < -100 and breadth < 0.4:
        verdict, tone = '资金整体流出（防守为主，控制仓位）', 'out'
    else:
        verdict, tone = '资金分歧（结构性行情，选对板块才有肉）', 'mix'

    out = {
        'generated': time.strftime('%Y-%m-%d %H:%M'),
        'market': {'main_net': round(total, 1) if total is not None else None,
                   'main_net5': round(net5, 1) if net5 is not None else None,
                   'main_ratio': round(ratio, 2) if ratio is not None else None,
                   'up_sectors': ups, 'down_sectors': n - ups,
                   'breadth': round(breadth * 100, 1),
                   'verdict': verdict, 'tone': tone},
        'sectors': ind,
        'concepts': con[:60],
        'top_in': ind[:8],
        'top_out': ind[-8:][::-1],
        'names': [s['name'] for s in ind],
    }
    json.dump(clean_nan(out), open(os.path.join(HERE, 'sector_flow.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, allow_nan=False)
    print('[4] 沪深两市主力净额 %s亿（5日 %s亿）| 净流入板块 %d/%d (%.0f%%) → %s'
          % ('%.1f' % total if total is not None else 'n/a',
             '%.1f' % net5 if net5 is not None else 'n/a',
             ups, n, breadth * 100, verdict))
    print('    资金流入 TOP5:', ' / '.join('%s(%+.1f亿)' % (s['name'], s['net1']) for s in ind[:5]))
    print('    资金流出 TOP5:', ' / '.join('%s(%+.1f亿)' % (s['name'], s['net1']) for s in ind[-5:][::-1]))
    print('✅ 已保存 sector_flow.json')


if __name__ == '__main__':
    main()
