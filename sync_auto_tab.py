# -*- coding: utf-8 -*-
"""
把 auto_screen_result.json / national_team.json / sentiment.json / li_daxiao.json / sector_flow.json 等的最新快照「烘焙」进两个 HTML：
  - 自动选股 Tab：写入 #autoMount 内的 <!--AUTOPICK_START/END--> 之间
  - 国家队资金 Tab：写入 #teamMount 内的 <!--TEAM_START/END--> 之间
  - 市场情绪 Tab：写入 #sentMount 内的 <!--SENT_START/END--> 之间
  - 李大霄/板块资金等：写入对应挂载点
注：原「蓝筹低吸」独立 Tab 已删除（回测显示跌破年线低吸无超额）；蓝筹低值发现仍由 li_daxiao.json 承载。

为什么要烘焙：页面正常走 fetch 拉 JSON（GitHub Pages 上永远最新），
但本地 file:// 双击打开时 fetch 会被浏览器拦截，此时就显示这份烘焙快照兜底。
渲染脚本 fetch 成功会覆盖挂载点，所以两者不冲突。

用法：python sync_auto_tab.py      （幂等，可反复执行）
每日自动化：auto_screener.py -> blue_chip_screener.py -> gen_auto_pick.py -> 本脚本
"""
import json, re, os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'auto_screen_result.json')
GUARD = os.path.join(HERE, 'strategy_guard.json')
TEAM = os.path.join(HERE, 'national_team.json')
SENT = os.path.join(HERE, 'sentiment.json')
OVERVIEW = os.path.join(HERE, 'overview.json')
WATCH = os.path.join(HERE, 'watch_pool.json')
LIDAXIAO = os.path.join(HERE, 'li_daxiao.json')
SECTOR = os.path.join(HERE, 'sector_flow.json')
FILES = ['wolf-screener3.0.html', 'wolf-mobile4.2.html']

A_START, A_END = '<!--AUTOPICK_START-->', '<!--AUTOPICK_END-->'
G_START, G_END = '<!--GUARD_START-->', '<!--GUARD_END-->'
T_START, T_END = '<!--TEAM_START-->', '<!--TEAM_END-->'
S_START, S_END = '<!--SENT_START-->', '<!--SENT_END-->'
O_START, O_END = '<!--SYNTHESIS_START-->', '<!--SYNTHESIS_END-->'
W_START, W_END = '<!--WATCH_START-->', '<!--WATCH_END-->'
LD_START, LD_END = '<!--LIDAXIAO_START-->', '<!--LIDAXIAO_END-->'
SE_START, SE_END = '<!--SECTORFLOW_START-->', '<!--SECTORFLOW_END-->'
TT_START, TT_END = '<!--TRADETIME_START-->', '<!--TRADETIME_END-->'
TB_START, TB_END = '<!--TTBANNER_START-->', '<!--TTBANNER_END-->'
ET_START, ET_END = '<!--ETFTIME_START-->', '<!--ETFTIME_END-->'
ETF_DATA = os.path.join(HERE, 'etf_result.json')


def esc(x):
    if x is None:
        return ''
    return str(x).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def dim_badge_py(label, st):
    if st == 'pass':
        return f'<span class="badge b-green">{esc(label)} ✓达标</span>'
    if st == 'fail':
        return f'<span class="badge b-red">{esc(label)} ✗未达标</span>'
    if st == 'watch':
        return f'<span class="badge b-amber">{esc(label)} ⏳观望</span>'
    return f'<span class="badge" style="background:var(--bg3);color:var(--t3)">{esc(label)} —待确认</span>'


def ld_bar(name, cur, pct_all, sub, unit=''):
    p = pct_all if (pct_all is not None) else 50
    p = max(0, min(100, p))
    col = 'var(--green2)' if p < 25 else ('#7cb342' if p < 50 else ('#d99e00' if p < 75 else 'var(--red2)'))
    return f'''<div style="margin:8px 0">
  <div style="display:flex;justify-content:space-between;font-size:12px">
    <span style="color:var(--t1);font-weight:600">{esc(name)}</span>
    <span style="color:var(--t1)">{num(cur)}{unit} <span style="color:var(--t3);font-size:11px">{esc(sub)}</span></span></div>
  <div style="height:10px;background:linear-gradient(90deg,var(--green2),#d99e00,var(--red2));border-radius:5px;position:relative;margin-top:4px">
    <div style="position:absolute;top:-3px;left:calc({p}% - 3px);width:6px;height:16px;background:#fff;border:2px solid var(--t1);border-radius:3px"></div></div>
</div>'''


def ld_card_py(b):
    low = b.get('low')
    pct = b.get('pe_pct_hist') if b.get('pe_pct_hist') is not None else (
        b.get('pe_pct_1y') if b.get('pe_pct_1y') is not None else (b.get('cheap_score') if b.get('cheap_score') is not None else None))
    pct_txt = '—' if pct is None else f'{round(pct)}%'
    pct_label = '历史分位' if b.get('pe_pct_hist') is not None else ('近1年分位' if b.get('pe_pct_1y') is not None else '横截面')
    border = 'var(--green2)' if low else 'var(--line)'
    low_badge = ' <span class="badge b-green">🟢低值</span>' if low else ''
    pcol = 'var(--green2)' if low else 'var(--t2)'
    return f'''<div style="padding:8px 10px;margin-bottom:6px;background:var(--bg2);border-radius:8px;border-left:3px solid {border}">
  <div style="display:flex;justify-content:space-between;align-items:baseline">
    <div style="font-weight:600;color:var(--t1)">{esc(b.get('name', ''))} <span style="color:var(--t3);font-weight:400;font-size:11px">{esc(b.get('code', ''))}</span>{low_badge}</div>
    <div style="font-size:12px;color:var(--t2)">PE {num(b.get('pe'))} · PB {num(b.get('pb'))}</div></div>
  <div style="margin-top:3px;font-size:11px;color:var(--t3)">{pct_label} <b style="color:{pcol}">{pct_txt}</b>{' · 降级数据' if b.get('src') == 'fallback' else ''}</div>
</div>'''


def load(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def money(v):
    y = (v or 0) / 1e8
    return ('+' if y >= 0 else '') + f'{y:.2f}亿'


def chg(v):
    v = v or 0
    return ('+' if v >= 0 else '') + f'{v:.2f}%'


def color_of(v):
    return 'var(--red2)' if (v or 0) >= 0 else 'var(--green2)'  # A股红涨绿跌


def num(v, n=2):
    try:
        return f'{float(v):.{n}f}'
    except Exception:
        return '-'


def greed_badge(g):
    if g is None:
        return '<span class="badge b-amber">—</span>'
    if g < 35:
        c, t = 'b-green', '恐慌低位'
    elif g > 65:
        c, t = 'b-red', '贪婪过热'
    else:
        c, t = 'b-amber', '中性'
    return f'<span class="badge {c}">{t} {g:.1f}%</span>'


def layer_pill(label, st):
    c = 'b-green' if st == 'pass' else ('b-red' if st == 'fail' else 'b-amber')
    t = '✓通过' if st == 'pass' else ('✗未过' if st == 'fail' else '⏳观望')
    return f'<span class="badge {c}">{label} {t}</span>'


def tier_tag(r):
    m = {'M': ('#1e88e5', '🚀强势顺势'), 'E': ('#ff7043', '🔥早期突破'), 'A': ('var(--green2)', '🟢低位低吸'),
         'B': ('#d99e00', '🔵观察'), 'C': ('var(--red2)', '🔴过热禁止'), 'D': ('#888', '⚪观望')}
    col, txt = m.get(r.get('template'), ('#d99e00', '?'))
    return f'<span style="font-size:11px;padding:1px 6px;border-radius:6px;background:{col}22;color:{col};border:1px solid {col}55">{txt}</span>'


def sector_chip(r):
    sec = r.get('sector')
    if not sec:
        return ''
    col = 'var(--red2)' if r.get('sector_hot') else '#888'
    # sector_net 单位已是「亿元」，勿再除 1e8
    net = r.get('sector_net') or 0
    hot = (f' 🔥+{net:.0f}亿' + (f'/第{r["sector_rank"]}' if r.get('sector_rank') else '')) if (r.get('sector_hot') and net) else (' 🔥热点' if r.get('sector_hot') else '')
    return f'<span style="font-size:11px;padding:1px 6px;border-radius:6px;background:{col}18;color:{col};border:1px solid {col}55">板块:{esc(sec)}{hot}</span>'


def dark_chip(r):
    dp = r.get('darkpool')
    if dp is None or dp <= 0:
        return ''
    return f'<span style="font-size:11px;padding:1px 6px;border-radius:6px;background:#7b3fa022;color:#7b3fa0;border:1px solid #7b3fa055">暗盘+{num(dp,1)}亿</span>'


def leader_chip(r):
    if r.get('is_leader') and r.get('industry_rank'):
        return f'<span style="font-size:11px;padding:1px 6px;border-radius:6px;background:#d4a01722;color:#b8860b;border:1px solid #d4a01755">🏆龙头(行业第{r["industry_rank"]}/{r["industry_count"]})</span>'
    return ''


# ---------------- 自动选股 ----------------
def a_cards(items):
    out = ''
    for r in (items or []):
        l1, l2, l3, l4 = r.get('l1', {}), r.get('l2', {}), r.get('l3', {}), r.get('l4', {})
        chgcol = color_of(r.get('change'))
        l3txt = '⚠代理' if l3.get('proxy') else ''
        fund = ' ★好公司' if (r.get('fund') or {}).get('good') else ''
        border = 'var(--blue)' if r.get('template') == 'M' else ('#ff7043' if r.get('template') == 'E' else 'var(--green2)')
        out += f'''
    <div style="padding:10px;margin-bottom:8px;background:var(--bg2);border-radius:10px;border-left:3px solid {border}">
      <div style="display:flex;justify-content:space-between;align-items:baseline">
        <div style="font-weight:700;color:var(--t1)">{r['name']} <span style="color:var(--t3);font-weight:400;font-size:12px">{r['code']}{fund}</span></div>
        <div style="text-align:right">
          <div style="color:var(--t1);font-weight:700">{num(r.get('price'))}</div>
          <div style="font-size:12px;color:{chgcol}">{chg(r.get('change'))}</div>
        </div>
      </div>
      <div style="margin-top:6px;font-size:12px;color:var(--t2);display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        {tier_tag(r)} {greed_badge(l1.get('greed'))} <span>主力 <b style="color:var(--green2)">{money(r.get('inflow'))}</b></span> {sector_chip(r)} {dark_chip(r)} {leader_chip(r)}
      </div>
      <div style="margin-top:5px;font-size:11px;color:var(--t3);display:flex;gap:5px;flex-wrap:wrap">
        {layer_pill('①情绪', l1.get('status'))}
        {layer_pill('②浪型', l2.get('status'))}
        {layer_pill('③技术' + l3txt, l3.get('status'))}
        {layer_pill('④资金', l4.get('status'))}
      </div>
      <div style="margin-top:5px;font-size:11px;color:var(--t3)">止损 <b>{num(r.get('stop'), 3)}</b> · 目标 <b>{num(r.get('target'), 3)}</b></div>
      <div style="margin-top:4px;font-size:12px;color:var(--t2);line-height:1.5">{r.get('suggestion', '')}</div>
    </div>'''
    return out


def compact_table(items):
    h = '<div style="max-height:52vh;overflow-y:auto"><table style="width:100%;border-collapse:collapse">'
    h += ('<tr style="color:var(--t4);font-size:11px;text-align:left"><th style="padding:4px">名称</th>'
          '<th style="padding:4px">价</th><th style="padding:4px">涨跌</th>'
          '<th style="padding:4px">贪婪</th><th style="padding:4px">判定</th></tr>')
    for r in items:
        col = color_of(r.get('change'))
        g = (r.get('l1') or {}).get('greed')
        h += (f'<tr style="font-size:12px;border-top:1px solid var(--line)">'
              f'<td style="padding:5px 4px;color:var(--t1)">{r["name"]}<br><span style="color:var(--t4);font-size:10px">{r["code"]}</span></td>'
              f'<td style="padding:5px 4px;color:var(--t1)">{num(r.get("price"))}</td>'
              f'<td style="padding:5px 4px;color:{col}">{chg(r.get("change"))}</td>'
              f'<td style="padding:5px 4px">{num(g, 1) if g is not None else "-"}%</td>'
              f'<td style="padding:5px 4px;color:var(--t3)">{r.get("template", "")}</td></tr>')
    return h + '</table></div>'


def build_backtest_bake():
    """读取 backtest_winrate.json（backtest_screener.py 生成）烘焙多策略×多持有期对比表；缺失则留空。"""
    try:
        b = json.load(open('backtest_winrate.json', encoding='utf-8'))
    except Exception:
        return ''
    mx = b.get('matrix') or {}
    strs = list(mx.keys())
    if not strs:
        return ''
    pa = b.get('params') or {}
    h = '<div class="panel"><h3 style="margin-bottom:6px">📊 多策略回测对比（持股 10/20/30/40 日 · 胜率%/均值%）</h3>'
    h += (f'<div class="panel-sub" style="margin-bottom:6px">{esc(pa.get("range",""))} · 股票池{pa.get("pool",0)}只 · '
          f'检查点{pa.get("checkpoints",0)}个 · 止损{round((pa.get("stop") or .08)*100)}%/止盈{round((pa.get("tp") or .15)*100)}%（先触发先执行）</div>')
    h += ('<table style="width:100%;border-collapse:collapse;font-size:12px">'
          '<tr style="color:var(--t4)"><th style="padding:4px;text-align:left">策略</th><th style="padding:4px">样本</th>'
          '<th style="padding:4px">10日</th><th style="padding:4px">20日</th>'
          '<th style="padding:4px">30日</th><th style="padding:4px">40日</th></tr>')
    for sname in strs:
        row = mx[sname]; cells = ''; nn = 0; best_h = None; best_v = -9
        for hd in (10, 20, 30, 40):
            c = row.get(str(hd)) or row.get(hd) or {}     # JSON 反序列化后键是字符串，两种都兜住
            if c.get('n'):
                nn = c['n']
                if (c.get('avg') or -9) > best_v:
                    best_v = c.get('avg') or -9; best_h = hd
        for hd in (10, 20, 30, 40):
            c = row.get(str(hd)) or row.get(hd) or {}
            if c.get('n'):
                avg = (c.get('avg') or 0) * 100
                hi = ';background:rgba(212,160,23,.14);border-radius:4px' if hd == best_h else ''
                cells += (f'<td style="padding:4px;text-align:center;color:var(--t2){hi}">胜{c.get("win",0):.1f}%<br>'
                          f'<span style="color:{color_of(avg)}">{"+" if avg>=0 else ""}{avg:.2f}%</span></td>')
            else:
                cells += '<td style="padding:4px;text-align:center;color:var(--t4)">—</td>'
        h += (f'<tr style="border-top:1px solid var(--line)"><td style="padding:4px;color:var(--t1)">{esc(sname)}</td>'
              f'<td style="padding:4px;text-align:center;color:var(--t4)">{nn}</td>{cells}</tr>')
    h += '</table>'
    vd = b.get('verdict') or []
    if vd:
        h += '<div style="margin-top:8px;font-size:12px;color:var(--t2);line-height:1.7">'
        for v in vd:
            ex = v.get('excess') or 0
            h += (f'<div>{"✅" if v.get("edge") else "⚠️"} <b>{esc(v.get("strategy",""))}</b>：最优持有 '
                  f'<b>{v.get("best_hold")}日</b>，胜率 {v.get("win",0):.1f}%、均值 {(v.get("avg") or 0)*100:.2f}%，'
                  f'相对纯持有基线 {"超额 +" if ex>0 else "落后 "}{ex*100:.2f}%'
                  f'{"（有 Alpha）" if v.get("edge") else "（无显著 Alpha，慎用）"}</div>')
        h += '</div>'
    if b.get('note'):
        h += f'<div style="margin-top:6px;font-size:11px;color:var(--t4);line-height:1.5">⚠️ {esc(b["note"])}</div>'
    h += '</div>'
    return h


def wait_list(arr):
    """资金主线龙头但当前不可买（过热/未共振）：登记 + 明确回踩条件，不追高。"""
    arr = arr or []
    if not arr: return ''
    rows = ''.join(
        f'<div style="border-top:1px solid var(--line);padding:6px 2px;font-size:12px">'
        f'<b style="color:var(--t1)">{esc(r.get("name",""))}</b> '
        f'<span style="color:var(--t4);font-size:10px">{esc(r.get("code",""))}</span> '
        f'<span style="color:{color_of(r.get("change",0))}">{chg(r.get("change"))}</span>'
        f'<div style="color:var(--t3);line-height:1.5;margin-top:2px">{esc(r.get("watch_note",""))}</div></div>'
        for r in arr)
    return ('<details style="margin-top:8px"><summary style="cursor:pointer;font-size:12px;color:var(--t3)">'
            f'⏸ 资金主线龙头 · 当前不可买（过热/未共振，{len(arr)}只，点开看回踩条件）</summary>{rows}</details>')

def build_auto(d):
    s = d['summary']
    leaders = d.get('leaders', [])
    bt = build_backtest_bake()
    wl = wait_list(d.get('leaders_wait', []))
    return f'''
<div class="panel">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
    <div><h3>🤖 自动选股 · 全A四层扫描</h3>
    <div class="panel-sub" style="margin-bottom:0">小狼策略自动筛选 · 快照 {d['generated']}</div></div>
    <div style="font-size:12px;color:var(--t2)">候选 <b>{s['cand']}</b> · 🚀M <b>{s.get('M',0)}</b> · 🔥E <b>{s.get('E',0)}</b> · 🏆龙头 <b>{s.get('leaders',0)}</b> · 🟢A <b>{s['A']}</b> · 🔵B <b>{s['B']}</b> · 🔴C <b>{s['C']}</b> · ⚪D <b>{s['D']}</b></div>
  </div>
</div>
<div class="panel" style="border-left:3px solid #d4a017">
  <h3 style="margin-bottom:6px">🏆 热点板块龙头（板块资金净流入 + 行业龙头 + 顺势时机 三重确认 · {s.get('leaders',0)}只）</h3>
  {a_cards(leaders) if leaders else '<div style="font-size:12px;color:var(--t3)">今日无三重确认标的（资金主线板块内暂无龙头出现买点），不硬凑。</div>'}
  {wl}
</div>
<div class="panel">
  <h3 style="margin-bottom:6px">🚀 M · 强势顺势（右侧·跟主力，捕捉上涨阶段 · {s.get('M',0)}只）</h3>
  {a_cards(d.get('M', []))}
</div>
<div class="panel" style="border-left:3px solid #ff7043">
  <h3 style="margin-bottom:6px">🔥 E · 热点早期突破（板块资金主线+个股放量长阳，小仓试错跟随 · {s.get('E',0)}只）</h3>
  {a_cards(d.get('E', [])) if d.get('E') else '<div style="font-size:12px;color:var(--t3)">今日无热点早期突破标的（板块资金主线内暂无放量长阳个股越过1亿净流入门槛）。</div>'}
</div>
<div class="panel">
  <h3 style="margin-bottom:6px">🟢 A · 建议低吸（四层全过 {s['A']}只）</h3>
  {a_cards(d['A'])}
</div>
<details class="panel"><summary style="cursor:pointer;font-weight:600;color:var(--t1)">🔵 B · 观察（{s['B']}只）</summary>
{compact_table(d['B'])}
</details>
<details class="panel"><summary style="cursor:pointer;font-weight:600;color:var(--t1)">🔴 C · 禁止（{s['C']}只）</summary>
{compact_table(d['C'])}
</details>
<details class="panel"><summary style="cursor:pointer;font-weight:600;color:var(--t1)">⚪ D · 观望（{s['D']}只）</summary>
{compact_table(d['D'])}
</details>
{bt}
'''




# ---------------- 板块资金 · 买卖策略导向 ----------------
def _sector_group(title, arr, col):
    if not arr:
        return ''
    chips = ''.join(
        '<span style="font-size:11px;padding:2px 8px;border-radius:14px;border:1px solid %s;color:%s">%s <span style="opacity:.7">%s亿</span></span>'
        % (col, col, esc(s.get('name', '')), num(s.get('net5'), 1)) for s in arr)
    return ('<div style="margin-top:8px"><div style="font-size:12px;font-weight:700;color:%s">%s（%d）</div>'
            '<div style="display:flex;flex-wrap:wrap;gap:5px;margin-top:4px">%s</div></div>' % (col, title, len(arr), chips))


def build_sector_flow(d):
    if not d:
        return ''
    secs = d.get('sectors', [])
    def by_state(st):
        return sorted([s for s in secs if s.get('state') == st], key=lambda s: -(s.get('net5') or 0))
    inflow = by_state('持续流入')[:8]
    backflow = by_state('短线回流')[:6]
    pullback = by_state('短期回调')[:6]
    outflow = by_state('持续流出')[:8]
    m = d.get('market', {})
    h = ('<div class="panel" style="border-left:4px solid var(--blue);background:var(--bg2)">'
         '<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">'
         '<div><h3>🧭 板块资金 · 买卖策略导向</h3><div class="panel-sub" style="margin-bottom:0">生成于 %s</div></div>'
         '<div style="font-size:12px;color:var(--t2)">↑流入板块 <b>%s</b> · ↓流出 <b>%s</b> · 广度 <b>%s%%</b></div></div>'
         % (esc(d.get('generated', '')), m.get('up_sectors', 0), m.get('down_sectors', 0), m.get('breadth', 0)))
    h += ('<div style="margin-top:6px;font-size:12px;color:var(--t2)">📌 策略：优先「持续流入」板块做多/持有；「短线回流」做波段；'
          '「短期回调」等企稳；「持续流出」回避。市场整体：%s</div>' % esc(m.get('verdict', '')))
    h += _sector_group('🟢 持续流入（可买/持有）', inflow, 'var(--green2)')
    h += _sector_group('🔵 短线回流（波段做T）', backflow, '#1e88e5')
    h += _sector_group('⚪ 短期回调（等企稳）', pullback, 'var(--t3)')
    h += _sector_group('🔴 持续流出（回避）', outflow, 'var(--red2)')
    h += '</div>'
    return h


# ---------------- 注入 ----------------
def inject(s, block, start_tag, end_tag, mount_id):
    """把 block 写进 start_tag / end_tag 之间；标记缺失时自动在挂载点内建立标记。"""
    if start_tag in s and end_tag in s:
        i = s.index(start_tag)
        j = s.index(end_tag) + len(end_tag)
        return s[:i] + start_tag + block + end_tag + s[j:], 'refresh'
    mount = '<div id="%s">' % mount_id
    k = s.find(mount)
    if k >= 0:  # 有挂载点但没标记：清掉挂载点原内容（loading），重建标记
        depth, i = 1, k + len(mount)
        while i < len(s) and depth > 0:  # 简易匹配挂载 div 的闭合
            if s.startswith('<div', i):
                depth += 1
            elif s.startswith('</div>', i):
                depth -= 1
                if depth == 0:
                    break
            i += 1
        if depth == 0:
            return s[:k + len(mount)] + start_tag + block + end_tag + s[i:], 'rebuild-marker'
    return s, None


def build_guard(g):
    lvl = g.get('risk_level', 'GREEN')
    rg = g.get('regime', {}) or {}
    pr = g.get('position_rule', {}) or {}
    v = g.get('volume', {}) or {}
    dot = '🟢' if lvl == 'GREEN' else ('🟡' if lvl == 'AMBER' else '🔴')
    label = '正常' if lvl == 'GREEN' else ('建议调整' if lvl == 'AMBER' else '建议暂停')
    border = 'var(--green2)' if lvl == 'GREEN' else ('#d99e00' if lvl == 'AMBER' else 'var(--red2)')
    size = pr.get('size_mult', 1)
    stop = round((pr.get('stop_pct', 0.08)) * 100)
    note = rg.get('note', '')
    actions = ' ｜ '.join(g.get('actions', []))

    # 大盘量能行（与在线 loadGuard 文案/结构保持一致）
    vol_html = ''
    if v.get('ok'):
        vl = v.get('level', 'GREEN')
        vcol = 'var(--green2)' if vl == 'GREEN' else ('#d99e00' if vl == 'AMBER' else 'var(--red2)')
        fv = v.get('favor', 'none')
        fav = ('<span style="margin-left:6px;font-size:11px;color:var(--red2)">🚀 更利于M档顺势</span>' if fv == 'M'
               else ('<span style="margin-left:6px;font-size:11px;color:var(--green2)">🟢 更利于A档低吸</span>' if fv == 'A' else ''))
        cv = v.get('chg') or 0
        ccol = 'var(--red2)' if cv >= 0 else 'var(--green2)'
        amt = (' ｜ 两市 %.2f 万亿' % (v['amount_yi'] / 1e4)) if v.get('amount_yi') else ''
        intr = ' ｜ 盘中折算' if v.get('intraday') else ''
        vol_html = (
            f'<div style="margin-top:6px;padding:6px 8px;border-radius:6px;background:var(--bg1);border-left:3px solid {vcol}">'
            f'<div style="font-size:12px;color:var(--t1)">📊 大盘量能 · <b style="color:{vcol}">{v.get("verdict", "")}</b>'
            f'<span style="font-size:11px;color:var(--t3)"> ｜ 量比 {round((v.get("ratio20") or 0) * 100)}%{amt}'
            f' ｜ 上证 <span style="color:{ccol}">{"+" if cv >= 0 else ""}{cv:.2f}%</span>{intr}</span>{fav}</div>'
            f'<div style="margin-top:3px;font-size:11px;color:var(--t2);line-height:1.5">操作：{v.get("action", "")}</div>'
            f'<div style="margin-top:2px;font-size:11px;color:var(--t3);line-height:1.5">风险：{v.get("risk", "")}</div>'
            f'</div>')

    return f'''
<div class="panel" style="border-left:4px solid {border};background:var(--bg2)">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px">
    <div style="font-weight:700;color:var(--t1)">{dot} 策略体检 · {label}</div>
    <div style="font-size:12px;color:var(--t2)">市场 {rg.get('level', '-')} · 仓位 {size}x · 止损 {stop}%</div>
  </div>
  <div style="margin-top:5px;font-size:12px;color:var(--t2);line-height:1.5">{note}</div>
  {vol_html}
  <div style="margin-top:5px;font-size:11px;color:var(--t3)">{actions}</div>
</div>
'''


def build_team(d):
    rg = d.get('regime', {}) or {}
    c = d.get('conclusion', {}) or {}
    etfs = d.get('etfs', [])
    att = c.get('attitude', '-')
    att_color = 'var(--green2)' if '进场' in att else ('var(--red2)' if '离场' in att else 'var(--t3)')
    rows = ''
    for e in etfs:
        tcol = 'var(--red2)' if e.get('trend') == '上行' else ('var(--green2)' if e.get('trend') == '下行' else 'var(--t3)')
        sh = num(e.get('shares_now_亿份'), 1) if e.get('shares_now_亿份') is not None else '-'
        rows += (f'<tr style="border-top:1px solid var(--line)">'
                 f'<td style="padding:5px 4px;color:var(--t1)">{e["name"]}<br><span style="color:var(--t4);font-size:10px">{e.get("role","")}</span></td>'
                 f'<td style="padding:5px 4px">{num(e.get("turnover_5d"),1)}</td>'
                 f'<td style="padding:5px 4px">{num(e.get("turnover_20d"),1)}</td>'
                 f'<td style="padding:5px 4px">{num(e.get("turnover_60d"),1)}</td>'
                 f'<td style="padding:5px 4px;color:{tcol}">{e.get("trend","")}<br><span style="font-size:10px;color:var(--t3)">{e.get("short_term","")}</span></td>'
                 f'<td style="padding:5px 4px">{sh}</td></tr>')
    v = d.get('validation', {})
    return f'''
<div class="panel">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
    <div><h3>🏛️ 国家队资金走向</h3>
    <div class="panel-sub" style="margin-bottom:0">快照 {d.get('generated','')} · 沪深300 {rg.get('state','-')}</div></div>
    <div style="font-weight:700;color:{att_color}">大资金：{att}</div>
  </div>
</div>
<div class="panel" style="font-size:12px;color:var(--t2);line-height:1.6">{c.get('summary','')}</div>
<div class="panel">
  <h3 style="margin-bottom:6px">宽基ETF 成交活跃度（估算成交额·亿元）</h3>
  <div style="max-height:46vh;overflow-y:auto"><table style="width:100%;border-collapse:collapse;font-size:12px">
    <tr style="color:var(--t4);text-align:left"><th style="padding:4px">ETF</th><th style="padding:4px">5日</th><th style="padding:4px">20日</th><th style="padding:4px">60日</th><th style="padding:4px">趋势</th><th style="padding:4px">份额(亿)</th></tr>
    {rows}
  </table></div>
</div>
<div class="panel" style="font-size:11px;color:var(--t3);line-height:1.5">✔ 验证：政策底由宽基ETF托市(True)；高位撤离(True,2026开年降温式调仓)。{v.get('note','')}</div>
<div class="panel" style="font-size:11px;color:var(--t4);line-height:1.5">⚠ {d.get('caveat','')}</div>
'''


def build_sent(d):
    idx = d.get('index', 50)
    zone = d.get('zone', '中性')
    adv = d.get('advice', '')
    comp = d.get('components', {}) or {}
    bar_color = 'var(--green2)' if idx < 35 else ('var(--red2)' if idx > 65 else '#d99e00')
    fs = d.get('forums_status', {}) or {}
    fs_lines = '<br>'.join(f'· {k}：{v}' for k, v in fs.items())
    v = d.get('validation', {})
    return f'''
<div class="panel">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
    <div><h3>🌡️ 市场情绪指数</h3>
    <div class="panel-sub" style="margin-bottom:0">恐惧贪婪 0-100 · 反向指标 · 快照 {d.get('generated','')}</div></div>
    <div style="font-weight:700;color:var(--t1)">{num(idx,0)} · {zone}</div>
  </div>
</div>
<div class="panel">
  <div style="height:14px;background:linear-gradient(90deg,var(--green2),#d99e00,var(--red2));border-radius:7px;position:relative;margin:8px 0 4px">
    <div style="position:absolute;top:-4px;left:calc({idx}% - 3px);width:6px;height:22px;background:#fff;border:2px solid var(--t1);border-radius:3px"></div>
  </div>
  <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--t4)"><span>冰点(逆向买)</span><span>中性</span><span>狂热(逆向卖)</span></div>
  <div style="margin-top:8px;font-size:13px;color:{bar_color};font-weight:600">{adv}</div>
</div>
<div class="panel" style="font-size:12px;color:var(--t2)">数据构成：微博舆情NLP <b>{num(comp.get("weibo_sentiment"),0)}</b> ｜ 市场代理 <b>{num(comp.get("market_proxy"),0)}</b> ｜ 合成 <b>{num(idx,0)}</b><br><span style="color:var(--t3);font-size:11px">来源：{d.get("source_detail","")}</span></div>
<details class="panel"><summary style="cursor:pointer;font-weight:600;color:var(--t1)">论坛接入状态</summary>
  <div style="font-size:11px;color:var(--t3);margin-top:6px;line-height:1.6">{fs_lines}</div>
</details>
<div class="panel" style="font-size:11px;color:var(--t3);line-height:1.5">✔ 验证：散户情绪作反向指标有效——回测极度悲观买入胜率68.1%、极度乐观卖出68.6%。{v.get('note','')}</div>
<div class="panel" style="font-size:11px;color:var(--t4);line-height:1.5">⚠ {d.get('caveat','')}</div>
'''


def build_overview(d):
    sc = d.get('score', 50)
    vcol = 'var(--green2)' if sc >= 70 else ('#3a9b3a' if sc >= 50 else ('#d99e00' if sc >= 30 else 'var(--red2)'))
    dot = '🟢' if d.get('risk_level') == 'GREEN' else ('🟡' if d.get('risk_level') == 'AMBER' else '🔴')
    comp = d.get('components', {}) or {}
    rows = ''
    for k, label in [('sentiment', '情绪'), ('national_team', '国家队'), ('regime', '市场状态'), ('watch_pool', '实盘验证'), ('auto_A', '选股信号')]:
        v = comp.get(k)
        if not v:
            continue
        val = v.get('count', '') and f'{v["count"]}只A信号' or v.get('zone') or v.get('attitude') or v.get('vs_backtest') or ''
        cont = v.get('贡献', 0) or 0
        ccol = 'var(--green2)' if cont > 0 else ('var(--red2)' if cont < 0 else 'var(--t3)')
        rows += f'· {label}：{val} <b style="color:{ccol}">{"+" if cont >= 0 else ""}{cont}</b><br>'
    return f'''
<div class="panel" style="border-left:4px solid {vcol};background:var(--bg2)">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
    <div><h3>🧭 综合研判总览</h3><div class="panel-sub" style="margin-bottom:0">快照 {d.get('generated','')}</div></div>
    <div style="text-align:right"><div style="font-size:30px;font-weight:800;color:{vcol}">{num(sc,0)}</div><div style="font-size:12px;color:var(--t3)">机会分 0-100</div></div>
  </div>
  <div style="margin-top:6px;font-weight:700;color:var(--t1);font-size:15px">{d.get('verdict','')}</div>
  <div style="margin-top:4px;font-size:12px;color:var(--t2);line-height:1.5">{d.get('action','')}</div>
  <div style="margin-top:4px;font-size:11px;color:var(--t3)">{dot} 风险等级 {d.get('risk_level','')} ｜ {d.get('sentence','')}</div>
</div>
<div class="panel"><h3 style="margin-bottom:6px">各维度贡献</h3><div style="font-size:12px;color:var(--t2);line-height:1.9">{rows}</div></div>
<div class="panel" style="font-size:11px;color:var(--t4);line-height:1.5">{d.get('caveat','')}</div>
'''


def build_watch(d):
    s = d.get('stats', {}) or {}
    base = d.get('baseline', {}) or {}
    items = d.get('items', []) or []
    pm = s.get('pool_max', 10); hd = s.get('hold_days', 10); exd = s.get('exit_days', 11)
    wr = s.get('win_rate')
    vs = s.get('vs_backtest', '样本不足')
    wrcol = 'var(--t3)' if wr is None else ('var(--green2)' if vs == '高于回测' else ('var(--red2)' if vs == '低于回测' else 'var(--t3)'))
    wr_txt = f'{wr*100:.1f}%' if wr is not None else '—'
    base_txt = f' {(base.get("win") or 0)*100:.1f}%' if base.get('win') is not None else ''
    avg_txt = f'{("+" if (s.get("avg_return") or 0) >= 0 else "")}{(s.get("avg_return") or 0)*100:.2f}%' if s.get('avg_return') is not None else '—'
    pick_txt = (f'今日已选 {esc(s.get("last_pick_name",""))}' if s.get('today_picked')
                else '今日未选（已满格/无候选）')
    # 分档对比(已清出样本)：M(强势顺势) vs A(低位低吸)，保留之前策略、相互对比盈亏
    def _fmt_tier(t):
        st = (s.get('by_tier') or {}).get(t) or {}
        if not st.get('n'): return '样本不足'
        return '命中率%.1f%% / 均值%+.2f%% (n=%d)' % (st['win_rate'] * 100, st['avg_return'] * 100, st['n'])
    tier_html = ('<div class="panel" style="font-size:12px;color:var(--t2);line-height:1.6">'
                 '🏁 <b>策略对比(已清出样本)</b> ｜ 🚀M强势顺势：' + _fmt_tier('M')
                 + ' ｜ 🔥E早期突破：' + _fmt_tier('E')
                 + ' ｜ 🟢A低位低吸：' + _fmt_tier('A') + '</div>')

    def arow(it):
        col = color_of(it.get('return'))
        nm = esc(it.get('name', '')); cd = esc(it.get('code', ''))
        ret = it.get('return') or 0
        hdd = it.get('hold_days', 0)
        day = f'第{min(hdd, hd)}/{hd}日'
        note = esc(it.get('expectation', '') or '')
        return ('<tr style="font-size:12px;border-top:1px solid var(--line)">'
                f'<td style="padding:5px 4px;color:var(--t1)">{nm}<br><span style="color:var(--t4);font-size:10px">{cd}</span></td>'
                f'<td style="padding:5px 4px;color:var(--t3)">{esc(it.get("entry_date",""))}</td>'
                f'<td style="padding:5px 4px;color:var(--t3)">{day}</td>'
                f'<td style="padding:5px 4px">{num(it.get("entry_price"))}</td>'
                f'<td style="padding:5px 4px">{num(it.get("last_price"))}</td>'
                f'<td style="padding:5px 4px;color:{col}">{chg(ret*100)}</td>'
                f'<td style="padding:5px 4px;color:var(--t3)">持有中<br><span style="font-size:10px">{note}</span></td></tr>')

    def erow(it):
        col = color_of(it.get('return'))
        nm = esc(it.get('name', '')); cd = esc(it.get('code', ''))
        exr = it.get('exit_return') or 0
        ret = it.get('return') or 0
        diff = ret - exr
        excol = color_of(exr); dcol = color_of(diff)
        return ('<tr style="font-size:12px;border-top:1px solid var(--line)">'
                f'<td style="padding:5px 4px;color:var(--t1)">{nm}<br><span style="color:var(--t4);font-size:10px">{cd}</span></td>'
                f'<td style="padding:5px 4px;color:var(--t3)">{esc(it.get("entry_date",""))}</td>'
                f'<td style="padding:5px 4px;color:var(--t3)">{esc(it.get("exit_date",""))}</td>'
                f'<td style="padding:5px 4px;color:{excol}">{chg(exr*100)}</td>'
                f'<td style="padding:5px 4px;color:{col}">{chg(ret*100)}</td>'
                f'<td style="padding:5px 4px;color:{dcol}">{("+" if diff>=0 else "")}{diff*100:.2f}%</td></tr>')

    active = [it for it in items if it.get('status') == '持有中']
    exited = [it for it in items if it.get('status') not in ('持有中', '已移除')]
    rows_a = ''.join(arow(it) for it in reversed(active)) or '<tr><td colspan="7" style="padding:12px;color:var(--t3);text-align:center">暂无持仓中标的</td></tr>'
    rows_e = ''.join(erow(it) for it in reversed(exited)) or '<tr><td colspan="6" style="padding:12px;color:var(--t3);text-align:center">暂无已清出标的</td></tr>'
    return f'''
<div class="panel">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
    <div><h3>🎯 动态观察池 · 滚动{pm}格</h3><div class="panel-sub" style="margin-bottom:0">快照 {esc(d.get('updated',''))}</div></div>
    <div style="text-align:right"><div style="font-size:20px;font-weight:800;color:{wrcol}">{wr_txt}</div>
    <div style="font-size:11px;color:var(--t3)">清出命中率 vs 回测{base_txt}</div></div>
  </div>
</div>
<div class="panel" style="font-size:12px;color:var(--t2);line-height:1.6">
  持仓 <b>{s.get('active',0)}</b>/{pm} ｜ 已清出 <b>{s.get('cleared',0)}</b> ｜ {pick_txt}
  ｜ 均值 <b>{avg_txt}</b> ｜ <b style="color:{wrcol}">{esc(vs)}</b>
</div>
{tier_html}
<div class="panel" style="font-size:11px;color:var(--t3);line-height:1.5">
  📌 规则：每天入选「策略盈利率最高」的 <b>1 只</b>，持有 <b>{hd}</b> 日、第 <b>{exd}</b> 日清出，始终保持 {pm} 只·<b>一进一出</b>。清出后<b>仍追踪现价</b>，可对比「按纪律出场」与「一直持有」的差距。
</div>
<div class="panel"><h3 style="margin-bottom:6px">🔵 持仓中（动态池 · 一进一出）</h3>
  <div style="max-height:38vh;overflow-y:auto"><table style="width:100%;border-collapse:collapse;font-size:12px">
  <tr style="color:var(--t4);text-align:left"><th style="padding:4px">标的</th><th style="padding:4px">入选日</th><th style="padding:4px">持有</th><th style="padding:4px">入场价</th><th style="padding:4px">现价</th><th style="padding:4px">至今收益</th><th style="padding:4px">状态</th></tr>
  {rows_a}
  </table></div></div>
<div class="panel"><h3 style="margin-bottom:6px">⚪ 已清出 · 仍追踪后续</h3>
  <div style="max-height:38vh;overflow-y:auto"><table style="width:100%;border-collapse:collapse;font-size:12px">
  <tr style="color:var(--t4);text-align:left"><th style="padding:4px">标的</th><th style="padding:4px">入选日</th><th style="padding:4px">清出日</th><th style="padding:4px">结算收益</th><th style="padding:4px">至今累计</th><th style="padding:4px">若持有差额</th></tr>
  {rows_e}
  </table></div></div>
<div class="panel" style="font-size:11px;color:var(--t4);line-height:1.5">自我纠正：动态池用「满持有期清出」做干净的实验——命中率以<b>清出时结算收益</b>为基准。清出标的之后仍每天更新现价，故「至今累计」与「结算收益」的差额可见（绿=一直拿着更赚，红=早出场更对）。不构成投资建议。</div>
'''


# ---------------- 李大霄底部研判 ----------------
def build_lidaxiao(d):
    s = d.get('sz50', {}) or {}
    v = d.get('verdict', {}) or {}
    blues = d.get('bluechips', []) or []
    dims = d.get('dims', {}) or {}
    tier = s.get('tier') or '未知'
    tier_color = 'var(--green2)' if tier == '极致底部' else ('#d99e00' if tier == '温和底部' else 'var(--t3)')
    # 数据来源角标（防止静默降级被误当实时）
    src = d.get('source') or s.get('source') or 'realtime'
    src_map = {'realtime': ('实时 · akshare', 'var(--green2)'),
               'cache_hit': ('缓存(6h内)', 'var(--green2)'),
               'cache_fallback': ('缓存降级 · 数据源不可达', '#d99e00'),
               'empty': ('无数据', 'var(--red2)')}
    src_label, src_color = src_map.get(src, ('实时', 'var(--green2)'))
    src_badge = f'<span style="font-size:11px;color:{src_color};border:1px solid {src_color};border-radius:6px;padding:1px 6px">来源：{src_label}</span>'
    gen = d.get('generated', '-')
    h = ''
    h += f'''<div class="panel" style="border-left:4px solid {tier_color};background:var(--bg2)">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
    <div><h3>📉 李大霄底部研判 · 综合结论</h3><div class="panel-sub" style="margin-bottom:0">上证50估值温度计 · 数据截至 {esc(s.get('asof', '-'))} · 生成于 {esc(gen)} {src_badge}</div></div>
    <div style="text-align:right"><div style="font-size:22px;font-weight:800;color:{tier_color}">{esc(tier)}</div>
    <div style="font-size:12px;color:var(--t3)">上证50 静态PE {num(s.get('pe'))}</div></div></div>
  <div style="margin-top:6px;font-size:13px;color:var(--t1);font-weight:600">{esc(v.get('level', ''))}</div>
  <div style="margin-top:4px;font-size:12px;color:var(--t2);line-height:1.5">{esc(v.get('action', ''))}</div>
  <div style="margin-top:4px;font-size:11px;color:var(--t3)">蓝筹低值 {v.get('blue_low_count', 0)}/{v.get('blue_total', 0)} 只处历史/近期低位</div></div>'''
    h += '<div class="panel"><h3 style="margin-bottom:6px">📊 上证50 估值温度计（对比历年 PE/PB）</h3>'
    h += ld_bar('静态PE', s.get('pe'), s.get('pe_pct_all'), f"全历史{num(s.get('pe_pct_all'))}% / 近5年{num(s.get('pe_pct_5y'))}%", '倍')
    h += ld_bar('市净率PB', s.get('pb'), s.get('pb_pct_all'), f"全历史{num(s.get('pb_pct_all'))}% / 近5年{num(s.get('pb_pct_5y'))}%")
    h += f'<div style="font-size:11px;color:var(--t4);margin-top:6px">分位越低=越便宜。参考区间：PE {num(s.get("pe_min"))}~{num(s.get("pe_max"))}（中位{num(s.get("pe_med"))}）；李大霄三档：≤8.5极致 / 8.5~10温和 / &gt;10接近底部。</div></div>'
    h += f'<div class="panel"><h3 style="margin-bottom:6px">💎 蓝筹低值发现（{len(blues)}只，按便宜度排序）</h3>'
    h += '<div style="font-size:11px;color:var(--t3);margin-bottom:6px">标注🟢低值的蓝筹处历史/近期估值低位，可重点纳入观察池。' + (
        '（个股历史接口限流，暂以1年分位+横截面替代）' if (blues and blues[0].get('src') == 'fallback') else '') + '</div>'
    h += ''.join(ld_card_py(b) for b in blues)
    h += '</div>'
    # 估值温度历史回测验证（诚实标注温度是否真含中期赔率信息）
    bt = d.get('backtest') or {}
    if bt.get('available'):
        bcol = 'var(--green2)' if bt.get('verified') else '#d99e00'
        h += '<div class="panel"><h3 style="margin-bottom:6px">🔬 估值温度历史回测验证</h3>'
        h += '<div style="font-size:12px;color:var(--t2);line-height:1.7">'
        h += f'样本 {num(bt.get("sample_n"))} 个交易日；其中 PE分位&lt;{num(bt.get("cheap_pct_threshold"))}% 的「便宜区」{num(bt.get("cheap_n"))} 个观测。<br>'
        h += f'之后60日中位收益：便宜区 <b>{num(bt.get("cheap_med60"))}%</b> vs 全样本 <b>{num(bt.get("all_med60"))}%</b>；'
        h += f'之后120日：便宜区 <b>{num(bt.get("cheap_med120"))}%</b> vs 全样本 <b>{num(bt.get("all_med120"))}%</b>。<br>'
        h += f'<span style="color:{bcol};font-weight:600">结论：{esc(bt.get("verdict"))}</span></div></div>'
    else:
        h += f'<div class="panel"><h3 style="margin-bottom:6px">🔬 估值温度历史回测验证</h3><div style="font-size:12px;color:var(--t3)">{esc(bt.get("note", "暂不可用"))}</div></div>'
    h += '<div class="panel"><h3 style="margin-bottom:6px">五维研判（量化修订版）</h3><div style="font-size:12px;color:var(--t2);line-height:1.9">'
    for k, dm in dims.items():
        h += dim_badge_py(k, dm.get('status')) + f' <span style="color:var(--t3)">{esc(dm.get("text", ""))}</span><br>'
    h += '</div></div>'
    return h


# ---------------- 交易时机（主入口）----------------
def tt_card_py(r, tag=''):
    tp = r.get('trade_plan') or {}
    oc = 'var(--green2)' if tp.get('open') == 'open' else ('#d99e00' if tp.get('open') == 'watch' else 'var(--red2)')
    olab = '✅ 可开仓' if tp.get('open') == 'open' else ('⏳ 等/小仓' if tp.get('open') == 'watch' else '⛔ 禁止')
    conv = tp.get('conviction', 0)
    ccol = 'var(--green2)' if conv >= 70 else ('#1e88e5' if conv >= 45 else ('#d99e00' if conv >= 20 else 'var(--t3)'))
    sp = (tp.get('stop_pct') or 0) * 100
    tp2 = (tp.get('target_pct') or 0) * 100
    side = tp.get('side', 'left')
    wave = tp.get('wave') or {}
    is_ld = bool(tp.get('lidaxiao_pick'))
    l1 = r.get('l1', {}) or {}; l2 = r.get('l2', {}) or {}; l3 = r.get('l3', {}) or {}; l4 = r.get('l4', {}) or {}
    wolf2 = (r.get('wolf2') or {}).get('pass')
    mac = (' ｜ ' + esc(tp['macro_note'])) if tp.get('macro_note') else ''
    tag_badge = f'<span class="badge" style="border:1px solid var(--t3);color:var(--t3)">{tag}</span>' if tag else ''
    side_badge = ('<span class="badge" style="border:1px solid var(--green2);color:var(--green2)">右侧顺势·买强</span>'
                 if side == 'right' else '<span class="badge" style="border:1px solid #d99e00;color:#d99e00">左侧低吸·买跌</span>')
    ld_badge = '<span class="badge" style="border:1px solid var(--blue);color:var(--blue)">李大霄·蓝筹</span>' if is_ld else ''
    wave_line = f'<div style="margin-top:4px;font-size:12px;color:var(--t2)">🌊 {esc(wave.get("label", "—"))}：{esc(wave.get("op", ""))}</div>' if wave.get('label') else ''
    rationale = tp.get('rationale', '')
    rat_html = f'<div style="margin-top:5px;font-size:12px;color:var(--t2);line-height:1.5;background:var(--bg3);padding:6px;border-radius:8px">📝 买入理由：{esc(rationale)}</div>' if rationale else ''
    return f'''
    <div data-side="{side}" style="padding:10px;margin-bottom:8px;background:var(--bg2);border-radius:10px;border-left:3px solid {oc}">
      <div style="display:flex;justify-content:space-between;align-items:baseline">
        <div style="font-weight:700;color:var(--t1)">{esc(r.get('name',''))} <span style="color:var(--t3);font-weight:400;font-size:12px">{esc(r.get('code',''))}</span></div>
        <div style="text-align:right"><div style="color:var(--t1);font-weight:700">{num(r.get('price'))}</div><div style="font-size:12px;color:{color_of(r.get('change'))}">{chg(r.get('change'))}</div></div>
      </div>
      <div style="margin-top:6px;font-size:12px;display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        <span class="badge" style="border:1px solid {oc};color:{oc}">{olab}</span>
        <span style="color:var(--t2)">📍 {esc(tp.get('buy_trigger',''))}</span>
        <span style="font-size:11px;color:{ccol}">确定性 {conv}</span>
        {side_badge}{ld_badge}{tag_badge}
      </div>
      <div style="margin-top:5px;font-size:12px;color:var(--t2)">持股 <b>{tp.get('hold_days','-')}</b> 日 · 止损 <b style="color:var(--red2)">{num(tp.get('stop_price'),3)}</b> ({sp:.0f}%) · 止盈 <b style="color:var(--green2)">{num(tp.get('target_price'),3)}</b> (+{tp2:.0f}%)</div>
      {wave_line}
      {rat_html}
      <div style="margin-top:4px;font-size:11px;color:var(--t3)">{esc(tp.get('open_reason',''))}{mac}</div>
      <div style="margin-top:4px;font-size:11px;color:var(--t3);display:flex;gap:5px;flex-wrap:wrap">
        {layer_pill('①情绪', l1.get('status'))} {layer_pill('②浪型', l2.get('status'))} {layer_pill('③技术', l3.get('status'))} {layer_pill('④资金', l4.get('status'))}{'<span class="badge b-green">★小狼2.0</span>' if wolf2 else ''}
      </div>
      <div style="margin-top:4px;font-size:12px;color:var(--t2);line-height:1.5">{esc(r.get('suggestion',''))}</div>
    </div>'''


def build_tradetime(d):
    if not d:
        return ''
    picks = []
    for r in (d.get('A', []) + d.get('B', [])):
        if r.get('trade_plan'):
            picks.append(r)
    picks.sort(key=lambda r: -(r['trade_plan'].get('conviction', 0)))
    actionable = [r for r in picks if r['trade_plan'].get('open') != 'no']
    if not actionable:
        return '<div class="panel" style="font-size:12px;color:var(--t3)">当前无可操作个股（大市环境或个股信号均未触发开仓）。可切「🤖 自动选股」看全部候选。</div>'
    h = f'<div class="panel" style="font-size:11px;color:var(--t3)">按确定性排序的可操作个股（开仓+观望共 {len(actionable)} 只）。非投资建议。</div>'
    h += ''.join(tt_card_py(r) for r in actionable)
    return h


def build_etftime(d):
    """ETF/LOF 交易时机快照（结构同 build_tradetime，复用 tt_card_py）。"""
    if not d:
        return ''
    picks = []
    for r in (d.get('A', []) + d.get('B', [])):
        if r.get('trade_plan'):
            picks.append(r)
    picks.sort(key=lambda r: -(r['trade_plan'].get('conviction', 0)))
    actionable = [r for r in picks if r['trade_plan'].get('open') != 'no']
    if not actionable:
        return '<div class="panel" style="font-size:12px;color:var(--t3)">当前无操作信号 ETF。可观察 B 类（观望/小仓）标的，等信号共振。非投资建议。</div>'
    h = f'<div class="panel" style="font-size:11px;color:var(--t3)">按确定性排序的可操作 ETF（开仓+观望共 {len(actionable)} 只）。非投资建议。</div>'
    h += ''.join(tt_card_py(r, 'ETF') for r in actionable)
    return h


def build_tt_banner(d, ld, sent):
    m = (d or {}).get('market', {}) or {}
    tier = ((ld or {}).get('sz50', {}) or {}).get('tier', '-')
    pe = ((ld or {}).get('sz50', {}) or {}).get('pe')
    sidx = (sent or {}).get('index')
    szone = (sent or {}).get('zone', '')
    mtrend = m.get('trend', 'na')
    mtrend_txt = '🟢 大盘上行' if mtrend == 'up' else ('🔴 大盘下行(恐慌区)' if mtrend == 'down' else '🟡 大盘震荡')
    pe_txt = f'（PE {num(pe)}）' if pe is not None else ''
    sidx_txt = num(sidx, 0) if sidx is not None else '-'
    dev_txt = f'（年线偏离 {num(m.get("dev_pct"))}%）' if m.get('dev_pct') is not None else ''
    return f'''<div class="panel" style="border-left:4px solid var(--blue);background:var(--bg2)">
  <div style="font-weight:700;color:var(--t1)">⏱️ 交易时机 · 大市环境</div>
  <div style="font-size:12px;color:var(--t2);margin-top:4px;line-height:1.6">李大霄温度 <b>{esc(tier)}</b>{pe_txt} ｜ 情绪 <b>{sidx_txt}</b> {esc(szone)}
   ｜ {mtrend_txt}{dev_txt}</div>
  <div style="font-size:11px;color:var(--t3);margin-top:4px">开仓「总开关」：底部区域优先配置【优质蓝筹】(李大霄体系)，劣质股抄底=接飞刀；趋势向上强势股可【右侧顺势】跟随。下方可按「左侧低吸 / 右侧顺势」筛选。</div>
</div>'''


def main():
    d = load(DATA)
    ed = load(ETF_DATA)
    gd = load(GUARD)
    t = load(TEAM)
    sd = load(SENT)
    ov = load(OVERVIEW)
    wd = load(WATCH)
    ld = load(LIDAXIAO)
    se = load(SECTOR)
    if not (d or gd or t or sd or ov or wd or ld or se):
        print('没有可用数据，退出')
        return
    auto_block = build_auto(d) if d else None
    guard_block = build_guard(gd) if gd else None
    team_block = build_team(t) if t else None
    sent_block = build_sent(sd) if sd else None
    ov_block = build_overview(ov) if ov else None
    wd_block = build_watch(wd) if wd else None
    ld_block = build_lidaxiao(ld) if ld else None
    sector_block = build_sector_flow(se) if se else None
    banner_block = build_tt_banner(d, ld, sd) if d else None
    tt_block = build_tradetime(d) if d else None
    etf_block = build_etftime(ed) if ed else None
    for fn in FILES:
        p = os.path.join(HERE, fn)
        if not os.path.exists(p):
            print('SKIP (missing)', fn)
            continue
        s = open(p, encoding='utf-8').read()
        orig = s
        notes = []
        if auto_block:
            s, m = inject(s, auto_block, A_START, A_END, 'autoMount')
            notes.append('auto:' + (m or 'FAIL'))
        if guard_block:
            s, m = inject(s, guard_block, G_START, G_END, 'guardMount')
            notes.append('guard:' + (m or 'FAIL'))
        if team_block:
            s, m = inject(s, team_block, T_START, T_END, 'teamMount')
            notes.append('team:' + (m or 'FAIL'))
        if sent_block:
            s, m = inject(s, sent_block, S_START, S_END, 'sentMount')
            notes.append('sent:' + (m or 'FAIL'))
        if ov_block:
            s, m = inject(s, ov_block, O_START, O_END, 'synthesisMount')
            notes.append('synthesis:' + (m or 'FAIL'))
        if wd_block:
            s, m = inject(s, wd_block, W_START, W_END, 'watchMount')
            notes.append('watch:' + (m or 'FAIL'))
        if ld_block:
            s, m = inject(s, ld_block, LD_START, LD_END, 'ldMount')
            notes.append('lidaxiao:' + (m or 'FAIL'))
        if sector_block:
            s, m = inject(s, sector_block, SE_START, SE_END, 'sectorMount')
            notes.append('sector:' + (m or 'FAIL'))
        if banner_block:
            s, m = inject(s, banner_block, TB_START, TB_END, 'ttBanner')
            notes.append('ttbanner:' + (m or 'FAIL'))
        if tt_block:
            s, m = inject(s, tt_block, TT_START, TT_END, 'ttMount')
            notes.append('tradetime:' + (m or 'FAIL'))
        if etf_block:
            s, m = inject(s, etf_block, ET_START, ET_END, 'etfMount')
            notes.append('etftime:' + (m or 'FAIL'))
        if s != orig:
            open(p, 'w', encoding='utf-8').write(s)
            print('OK %-22s %s  (%d 字节)' % (fn, ' '.join(notes), len(s)))
        else:
            print('无变更', fn, ' '.join(notes))


if __name__ == '__main__':
    main()
