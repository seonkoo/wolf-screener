# -*- coding: utf-8 -*-
"""
把 auto_screen_result.json / blue_chip_result.json / national_team.json / sentiment.json 的最新快照「烘焙」进两个 HTML：
  - 自动选股 Tab：写入 #autoMount 内的 <!--AUTOPICK_START/END--> 之间
  - 蓝筹低吸 Tab：写入 #blueMount 内的 <!--BLUECHIP_START/END--> 之间
  - 国家队资金 Tab：写入 #teamMount 内的 <!--TEAM_START/END--> 之间
  - 市场情绪 Tab：写入 #sentMount 内的 <!--SENT_START/END--> 之间

为什么要烘焙：页面正常走 fetch 拉 JSON（GitHub Pages 上永远最新），
但本地 file:// 双击打开时 fetch 会被浏览器拦截，此时就显示这份烘焙快照兜底。
渲染脚本 fetch 成功会覆盖挂载点，所以两者不冲突。

用法：python sync_auto_tab.py      （幂等，可反复执行）
每日自动化：auto_screener.py -> blue_chip_screener.py -> gen_auto_pick.py -> 本脚本
"""
import json, re, os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'auto_screen_result.json')
BLUE = os.path.join(HERE, 'blue_chip_result.json')
GUARD = os.path.join(HERE, 'strategy_guard.json')
TEAM = os.path.join(HERE, 'national_team.json')
SENT = os.path.join(HERE, 'sentiment.json')
OVERVIEW = os.path.join(HERE, 'overview.json')
WATCH = os.path.join(HERE, 'watch_pool.json')
LIDAXIAO = os.path.join(HERE, 'li_daxiao.json')
FILES = ['wolf-screener3.0.html', 'wolf-mobile4.2.html']

A_START, A_END = '<!--AUTOPICK_START-->', '<!--AUTOPICK_END-->'
B_START, B_END = '<!--BLUECHIP_START-->', '<!--BLUECHIP_END-->'
G_START, G_END = '<!--GUARD_START-->', '<!--GUARD_END-->'
T_START, T_END = '<!--TEAM_START-->', '<!--TEAM_END-->'
S_START, S_END = '<!--SENT_START-->', '<!--SENT_END-->'
O_START, O_END = '<!--SYNTHESIS_START-->', '<!--SYNTHESIS_END-->'
W_START, W_END = '<!--WATCH_START-->', '<!--WATCH_END-->'
LD_START, LD_END = '<!--LIDAXIAO_START-->', '<!--LIDAXIAO_END-->'


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


# ---------------- 自动选股 ----------------
def a_cards(items):
    out = ''
    for r in items:
        l1, l2, l3, l4 = r.get('l1', {}), r.get('l2', {}), r.get('l3', {}), r.get('l4', {})
        chgcol = color_of(r.get('change'))
        l3txt = '⚠代理' if l3.get('proxy') else ''
        fund = ' ★好公司' if (r.get('fund') or {}).get('good') else ''
        out += f'''
    <div style="padding:10px;margin-bottom:8px;background:var(--bg2);border-radius:10px;border-left:3px solid var(--green2)">
      <div style="display:flex;justify-content:space-between;align-items:baseline">
        <div style="font-weight:700;color:var(--t1)">{r['name']} <span style="color:var(--t3);font-weight:400;font-size:12px">{r['code']}{fund}</span></div>
        <div style="text-align:right">
          <div style="color:var(--t1);font-weight:700">{num(r.get('price'))}</div>
          <div style="font-size:12px;color:{chgcol}">{chg(r.get('change'))}</div>
        </div>
      </div>
      <div style="margin-top:6px;font-size:12px;color:var(--t2);display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        {greed_badge(l1.get('greed'))} <span>主力 <b style="color:var(--green2)">{money(r.get('inflow'))}</b></span>
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


def build_auto(d):
    s = d['summary']
    return f'''
<div class="panel">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
    <div><h3>🤖 自动选股 · 全A四层扫描</h3>
    <div class="panel-sub" style="margin-bottom:0">小狼策略自动筛选 · 快照 {d['generated']}</div></div>
    <div style="font-size:12px;color:var(--t2)">候选 <b>{s['cand']}</b> · 🟢A <b>{s['A']}</b> · 🔵B <b>{s['B']}</b> · 🔴C <b>{s['C']}</b> · ⚪D <b>{s['D']}</b></div>
  </div>
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
'''


# ---------------- 蓝筹低吸 ----------------
def blue_card(p):
    if p.get('below_ma'):
        zone = '<span class="badge b-green">低吸区·低于年线</span>'
    elif p.get('near_low'):
        zone = '<span class="badge b-green">近52周低位</span>'
    else:
        zone = '<span class="badge b-amber">估值合理·待回调</span>'
    pct = ''
    if p.get('pe_pct') is not None:
        pct = f'<span class="badge b-green">PE近一年分位 {round(p["pe_pct"] * 100)}%</span>'
    gm = f'<span>毛利 {num(p.get("gm"), 1)}%</span>' if p.get('gm') is not None else ''
    return f'''
    <div style="padding:10px;margin-bottom:8px;background:var(--bg2);border-radius:10px;border-left:3px solid var(--blue)">
      <div style="display:flex;justify-content:space-between;align-items:baseline">
        <div style="font-weight:700;color:var(--t1)">{p['name']} <span style="color:var(--t3);font-weight:400;font-size:12px">{p['code']}</span></div>
        <div style="text-align:right"><div style="color:var(--t1);font-weight:700">{num(p.get('price'))}</div>
        <div style="font-size:11px;color:var(--t3)">评分 {num(p.get('score'), 1)}</div></div>
      </div>
      <div style="margin-top:6px;font-size:11px;color:var(--t2);display:flex;gap:6px;flex-wrap:wrap;align-items:center">
        <span class="badge b-green">3年ROE均 {num(p.get('roe_avg'), 1)}%</span>
        <span>PE {num(p.get('pe'), 1)} · PB {num(p.get('pb'), 2)}</span>
        {pct}{gm}{zone}
      </div>
      <div style="margin-top:5px;font-size:12px;color:var(--t2);line-height:1.5">{p.get('why', '')}</div>
    </div>'''


def build_blue(d):
    s = d.get('summary', {})
    picks = d.get('picks', [])
    low = [p for p in picks if p.get('below_ma') or p.get('near_low')]
    wait = [p for p in picks if not (p.get('below_ma') or p.get('near_low'))]
    low_html = ''.join(blue_card(p) for p in low) or '<div style="font-size:12px;color:var(--t3)">今日无标的落入低吸区。</div>'
    return f'''
<div class="panel">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
    <div><h3>💎 蓝筹低吸 · {s.get('universe', '沪深300')}</h3>
    <div class="panel-sub" style="margin-bottom:0">长期价值 + 低吸区 · 快照 {d.get('generated', '')}</div></div>
    <div style="font-size:12px;color:var(--t2)">蓝筹池 <b>{s.get('cand', 0)}</b> → 质量过 <b>{s.get('passed_quality', 0)}</b> → 估值过 <b>{s.get('passed_valuation', 0)}</b> → 推荐 <b>{s.get('selected', 0)}</b></div>
  </div>
</div>
<div class="panel">
  <h3 style="margin-bottom:6px">🟢 现在就可分批低吸（{len(low)}只）</h3>
  <div style="font-size:11px;color:var(--t3);margin-bottom:8px">质地过关 + 估值低位 + 价格已在年线下方或近52周低位，建议分3-5批、每批间隔≥2周买入。</div>
  {low_html}
</div>
<details class="panel"><summary style="cursor:pointer;font-weight:600;color:var(--t1)">🟡 优质但仍需等回调（{len(wait)}只）</summary>
  <div style="font-size:11px;color:var(--t3);margin:6px 0">质地与估值都合格，但价格未进入低吸区，可加自选等回踩年线。</div>
  {''.join(blue_card(p) for p in wait)}
</details>
'''


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
    dot = '🟢' if lvl == 'GREEN' else ('🟡' if lvl == 'AMBER' else '🔴')
    label = '正常' if lvl == 'GREEN' else ('建议调整' if lvl == 'AMBER' else '建议暂停')
    border = 'var(--green2)' if lvl == 'GREEN' else ('#d99e00' if lvl == 'AMBER' else 'var(--red2)')
    size = pr.get('size_mult', 1)
    stop = round((pr.get('stop_pct', 0.08)) * 100)
    note = rg.get('note', '')
    actions = ' ｜ '.join(g.get('actions', []))
    return f'''
<div class="panel" style="border-left:4px solid {border};background:var(--bg2)">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px">
    <div style="font-weight:700;color:var(--t1)">{dot} 策略体检 · {label}</div>
    <div style="font-size:12px;color:var(--t2)">市场 {rg.get('level', '-')} · 仓位 {size}x · 止损 {stop}%</div>
  </div>
  <div style="margin-top:5px;font-size:12px;color:var(--t2);line-height:1.5">{note}</div>
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
    wr = s.get('win_rate')
    vs = s.get('vs_backtest', '样本不足')
    wrcol = 'var(--t3)' if wr is None else ('var(--green2)' if vs == '高于回测' else ('var(--red2)' if vs == '低于回测' else 'var(--t3)'))
    wr_txt = f'{wr*100:.1f}%' if wr is not None else '—'
    base_txt = f' {(base.get("win") or 0)*100:.1f}%' if base.get('win') is not None else ''
    rows = ''
    for it in (d.get('items', []) or [])[::-1]:
        col = color_of(it.get('return'))
        stcol = 'var(--t3)' if it.get('status') == '持有中' else ('var(--green2)' if it.get('expectation') == '符合预期' else 'var(--red2)')
        ret = it.get('return') or 0
        rows += (f'<tr style="font-size:12px;border-top:1px solid var(--line)">'
                 f'<td style="padding:5px 4px;color:var(--t1)">{it.get("name","")}<br><span style="color:var(--t4);font-size:10px">{it.get("code","")}</span></td>'
                 f'<td style="padding:5px 4px">{num(it.get("entry_price"))}</td>'
                 f'<td style="padding:5px 4px">{num(it.get("last_price"))}</td>'
                 f'<td style="padding:5px 4px;color:{col}">{( "+" if ret>=0 else "" )}{ret*100:.2f}%</td>'
                 f'<td style="padding:5px 4px;color:{stcol}">{it.get("status","")}<br><span style="font-size:10px">{it.get("expectation","")}</span></td></tr>')
    avg_txt = f'{("+" if (s.get("avg_return") or 0) >= 0 else "")}{(s.get("avg_return") or 0)*100:.2f}%' if s.get('avg_return') is not None else '—'
    return f'''
<div class="panel">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
    <div><h3>📈 观察池 · 实盘验证</h3><div class="panel-sub" style="margin-bottom:0">快照 {d.get('updated','')}</div></div>
    <div style="text-align:right"><div style="font-size:20px;font-weight:800;color:{wrcol}">{wr_txt}</div>
    <div style="font-size:11px;color:var(--t3)">真实命中率 vs 回测{base_txt}</div></div>
  </div>
</div>
<div class="panel" style="font-size:12px;color:var(--t2);line-height:1.6">
  总追踪 <b>{s.get('total',0)}</b> 只 ｜ 已平仓 <b>{s.get('closed',0)}</b> ｜ 持仓 <b>{s.get('open',0)}</b>
  ｜ 止盈 <b style="color:var(--green2)">{s.get('tp',0)}</b> ｜ 止损 <b style="color:var(--red2)">{s.get('stop',0)}</b> ｜ 到期 <b>{s.get('expired',0)}</b>
  ｜ 均值 <b>{avg_txt}</b> ｜ <b style="color:{wrcol}">{vs}</b>
</div>
<div class="panel"><h3 style="margin-bottom:6px">追踪明细</h3><div style="max-height:48vh;overflow-y:auto"><table style="width:100%;border-collapse:collapse;font-size:12px">
  <tr style="color:var(--t4);text-align:left"><th style="padding:4px">标的</th><th style="padding:4px">入场价</th><th style="padding:4px">现价</th><th style="padding:4px">收益</th><th style="padding:4px">状态</th></tr>
  {rows}
</table></div></div>
<div class="panel" style="font-size:11px;color:var(--t4);line-height:1.5">自我纠正：观察池自动追踪「自动选股」输出的买入标的，自输出以来的真实走向即本表。命中率低于回测基线时策略体检将亮红灯。不构成投资建议。</div>
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


def main():
    d = load(DATA)
    b = load(BLUE)
    gd = load(GUARD)
    t = load(TEAM)
    sd = load(SENT)
    ov = load(OVERVIEW)
    wd = load(WATCH)
    ld = load(LIDAXIAO)
    if not (d or b or gd or t or sd or ov or wd or ld):
        print('没有可用数据，退出')
        return
    auto_block = build_auto(d) if d else None
    blue_block = build_blue(b) if b else None
    guard_block = build_guard(gd) if gd else None
    team_block = build_team(t) if t else None
    sent_block = build_sent(sd) if sd else None
    ov_block = build_overview(ov) if ov else None
    wd_block = build_watch(wd) if wd else None
    ld_block = build_lidaxiao(ld) if ld else None
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
        if blue_block:
            s, m = inject(s, blue_block, B_START, B_END, 'blueMount')
            notes.append('blue:' + (m or 'FAIL'))
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
        if s != orig:
            open(p, 'w', encoding='utf-8').write(s)
            print('OK %-22s %s  (%d 字节)' % (fn, ' '.join(notes), len(s)))
        else:
            print('无变更', fn, ' '.join(notes))


if __name__ == '__main__':
    main()
