# -*- coding: utf-8 -*-
"""
把 auto_screen_result.json / blue_chip_result.json 的最新快照「烘焙」进两个 HTML：
  - 自动选股 Tab：写入 #autoMount 内的 <!--AUTOPICK_START/END--> 之间
  - 蓝筹低吸 Tab：写入 #blueMount 内的 <!--BLUECHIP_START/END--> 之间

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
FILES = ['wolf-screener3.0.html', 'wolf-mobile4.2.html']

A_START, A_END = '<!--AUTOPICK_START-->', '<!--AUTOPICK_END-->'
B_START, B_END = '<!--BLUECHIP_START-->', '<!--BLUECHIP_END-->'


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


def main():
    d = load(DATA)
    b = load(BLUE)
    if not d and not b:
        print('没有可用数据，退出')
        return
    auto_block = build_auto(d) if d else None
    blue_block = build_blue(b) if b else None
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
        if s != orig:
            open(p, 'w', encoding='utf-8').write(s)
            print('OK %-22s %s  (%d 字节)' % (fn, ' '.join(notes), len(s)))
        else:
            print('无变更', fn, ' '.join(notes))


if __name__ == '__main__':
    main()
