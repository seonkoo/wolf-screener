# -*- coding: utf-8 -*-
"""
将 auto_screen_result.json 的扫描快照注入两个 HTML 的「🤖 自动选股」Tab。
用法：python sync_auto_tab.py
每日自动化会调用：auto_screener.py 重跑 -> gen_auto_pick.py 生成结果页 -> 本脚本同步入库。
"""
import json, re, os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'auto_screen_result.json')
FILES = ['wolf-screener3.0.html', 'wolf-mobile4.2.html']

def load():
    with open(DATA, encoding='utf-8') as f:
        return json.load(f)

def money(v):
    y = v / 1e8
    return ('+' if y >= 0 else '') + f'{y:.2f}亿'

def chg(v):
    return ('+' if v >= 0 else '') + f'{v:.2f}%'

def greed_badge(g):
    if g < 35:
        c, t = 'b-green', '恐慌低位'
    elif g > 65:
        c, t = 'b-red', '贪婪过热'
    else:
        c, t = 'b-amber', '中性'
    return f'<span class="badge {c}">{t} {g:.1f}%</span>'

def layer_pill(label, st):
    c = 'b-green' if st == 'pass' else ('b-red' if st == 'fail' else 'b-amber')
    return f'<span class="badge {c}">{label}</span>'

def color_of(v):
    return 'var(--red2)' if v >= 0 else 'var(--green2)'  # A股红涨绿跌

def a_cards(items):
    out = ''
    for r in items:
        l1, l2, l3, l4 = r['l1'], r['l2'], r['l3'], r['l4']
        chgcol = color_of(r['change'])
        l3txt = '⚠代理' if l3.get('proxy') else '✓'
        out += f'''
    <div style="padding:10px;margin-bottom:8px;background:var(--bg2);border-radius:10px;border-left:3px solid var(--green2)">
      <div style="display:flex;justify-content:space-between;align-items:baseline">
        <div style="font-weight:700;color:var(--t1)">{r['name']} <span style="color:var(--t3);font-weight:400;font-size:12px">{r['code']}</span></div>
        <div style="text-align:right">
          <div style="color:var(--t1);font-weight:700">{r['price']:.2f}</div>
          <div style="font-size:12px;color:{chgcol}">{chg(r['change'])}</div>
        </div>
      </div>
      <div style="margin-top:6px;font-size:12px;color:var(--t2);display:flex;gap:8px;flex-wrap:wrap;align-items:center">
        {greed_badge(r['l1']['greed'])} <span>主力 <b style="color:var(--green2)">{money(r['inflow'])}</b></span>
      </div>
      <div style="margin-top:5px;font-size:11px;color:var(--t3);display:flex;gap:5px;flex-wrap:wrap">
        {layer_pill('①情绪', l1['status'])}
        {layer_pill('②浪型', l2['status'])}
        {layer_pill('③技术' + l3txt, l3['status'])}
        {layer_pill('④资金', l4['status'])}
      </div>
      <div style="margin-top:5px;font-size:11px;color:var(--t3)">止损 <b>{r['stop']:.2f}</b> · 目标 <b>{r['target']:.2f}</b></div>
      <div style="margin-top:4px;font-size:12px;color:var(--t2);line-height:1.5">{r['suggestion']}</div>
    </div>'''
    return out

def compact_table(items):
    h = '<div style="max-height:52vh;overflow-y:auto"><table style="width:100%;border-collapse:collapse">'
    h += '<tr style="color:var(--t4);font-size:11px;text-align:left"><th style="padding:4px">名称</th><th style="padding:4px">价</th><th style="padding:4px">涨跌</th><th style="padding:4px">贪婪</th><th style="padding:4px">判定</th></tr>'
    for r in items:
        col = color_of(r['change'])
        h += (f'<tr style="font-size:12px;border-top:1px solid var(--line)">'
              f'<td style="padding:5px 4px;color:var(--t1)">{r["name"]}<br><span style="color:var(--t4);font-size:10px">{r["code"]}</span></td>'
              f'<td style="padding:5px 4px;color:var(--t1)">{r["price"]:.2f}</td>'
              f'<td style="padding:5px 4px;color:{col}">{chg(r["change"])}</td>'
              f'<td style="padding:5px 4px">{r["l1"].get("greed",0):.1f}%</td>'
              f'<td style="padding:5px 4px;color:var(--t3)">{r["template"]} {r["l4"].get("flow","")}</td></tr>')
    h += '</table></div>'
    return h

def build_block(d):
    s = d['summary']
    return f'''
<div class="panel">
  <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
    <div><h3>🤖 自动选股 · 全A四层扫描</h3>
    <div class="panel-sub" style="margin-bottom:0">小狼策略自动筛选 · 生成于 {d['generated']}</div></div>
    <div style="font-size:12px;color:var(--t2)">候选 <b>{s['cand']}</b> · 🟢A <b>{s['A']}</b> · 🔵B <b>{s['B']}</b> · 🔴C <b>{s['C']}</b> · ⚪D <b>{s['D']}</b></div>
  </div>
  <div style="margin-top:8px;font-size:11px;color:var(--t3)">⚠️ 波段反弹信号，非投资建议；止损6% / 目标10%。第3层技术共振在扫描环境用「日线代理」（沙箱取不到15min K线），在手机网页端切到本Tab后，建议用「🎯 选股雷达」用真实15min MACD复核。</div>
</div>
<div class="panel">
  <h3 style="margin-bottom:6px">🟢 A · 建议低吸（四层全过 {s['A']}只）</h3>
  {a_cards(d['A'])}
</div>
<div class="panel">
  <details><summary style="cursor:pointer;font-weight:600;color:var(--t1)">🔵 B · 观察（{s['B']}只）</summary>
  {compact_table(d['B'])}
  </details>
</div>
<div class="panel">
  <details><summary style="cursor:pointer;font-weight:600;color:var(--t1)">🔴 C · 禁止（{s['C']}只）</summary>
  {compact_table(d['C'])}
  </details>
</div>
<div class="panel">
  <details><summary style="cursor:pointer;font-weight:600;color:var(--t1)">⚪ D · 观望（{s['D']}只）</summary>
  {compact_table(d['D'])}
  </details>
</div>
'''

def main():
    d = load()
    block = build_block(d)
    for fn in FILES:
        p = os.path.join(HERE, fn)
        if not os.path.exists(p):
            print('SKIP (missing)', fn)
            continue
        s = open(p, encoding='utf-8').read()
        if '<!--AUTOPICK_BLOCK-->' not in s:
            print('WARN no placeholder in', fn, '(already injected or structure changed)')
            continue
        s = s.replace('<!--AUTOPICK_BLOCK-->', block, 1)
        open(p, 'w', encoding='utf-8').write(s)
        print('OK injected ->', fn)

if __name__ == '__main__':
    main()
