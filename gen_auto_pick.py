# -*- coding: utf-8 -*-
"""读取 auto_screen_result.json，生成自包含的移动端「今日自动选股」页面 auto_pick.html"""
import json, html

D = json.load(open('auto_screen_result.json', encoding='utf-8'))
gen = D.get('generated', '')
s = D.get('summary', {})
A = D.get('A', []); B = D.get('B', []); C = D.get('C', []); DD = D.get('D', [])

def st_badge(st):
    if st == 'pass': return '<span style="color:#52c41a;font-weight:700">✓通过</span>'
    if st == 'fail': return '<span style="color:#ff4d4f;font-weight:700">✗未过</span>'
    return '<span style="color:#fa8c16">⏳观望</span>'

def l1txt(r):
    g = r['l1'].get('greed')
    return '%.1f%%' % g

cards_a = ''
for r in A:
    g = r['l1']['greed']; inflow = r.get('inflow', 0) / 1e8
    cards_a += '''
    <div style="background:#121a2b;border:1px solid #2b3a52;border-left:3px solid #52c41a;border-radius:12px;padding:12px;margin-bottom:10px">
      <div style="display:flex;justify-content:space-between;align-items:baseline">
        <div style="font-size:16px;font-weight:800;color:#edf3ff">%(name)s <span style="font-size:12px;color:#93a4bb">%(code)s</span></div>
        <div style="font-size:13px;color:#edf3ff">%(price).2f <span style="color:%(cc)s">%(chg).2f%%</span></div>
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin:8px 0;font-size:11px">
        <span style="background:rgba(82,196,26,.15);color:#69db7c;padding:2px 8px;border-radius:6px">贪婪 %(g).1f%% 恐慌低位</span>
        <span style="background:rgba(74,158,255,.15);color:#93c5fd;padding:2px 8px;border-radius:6px">主力净流入 %(inflow).2f亿</span>
      </div>
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;font-size:11px;margin-bottom:6px">
        <div>1️⃣情绪 %(l1)s</div><div>2️⃣浪型 %(l2)s</div><div>3️⃣技术 %(l3)s</div><div>4️⃣资金 %(l4)s</div>
      </div>
      <div style="font-size:12px;color:#b2bfd3;line-height:1.6">%(sug)s</div>
      <div style="font-size:11px;color:#72839c;margin-top:4px">止损 %(stop)s · 目标 %(target)s</div>
    </div>''' % {
        'name': html.escape(r['name']), 'code': r['code'], 'price': r['price'],
        'cc': '#ff4d4f' if r['change'] >= 0 else '#52c41a', 'chg': r['change'],
        'g': g, 'inflow': inflow,
        'l1': st_badge(r['l1']['status']), 'l2': st_badge(r['l2']['status']),
        'l3': st_badge(r['l3']['status']), 'l4': st_badge(r['l4']['status']),
        'sug': html.escape(r['suggestion']), 'stop': r.get('stop'), 'target': r.get('target')
    }

rows_b = ''
for r in B[:40]:
    g = r['l1']['greed']; inflow = r.get('inflow', 0) / 1e8
    rows_b += '<tr><td>%(code)s</td><td>%(name)s</td><td class="c">%(g).1f%%</td><td class="c">%(inflow).2f亿</td><td class="c">%(l1)s %(l2)s</td></tr>' % {
        'code': r['code'], 'name': html.escape(r['name']), 'g': g, 'inflow': inflow,
        'l1': st_badge(r['l1']['status']), 'l2': st_badge(r['l2']['status'])
    }

HTML = '''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>小狼雷达 · 今日自动选股</title></head>
<body style="margin:0;background:#0a0e17;color:#edf3ff;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;padding:12px">
<div style="font-size:20px;font-weight:800;margin:6px 0">🤖 小狼雷达 · 今日自动选股</div>
<div style="font-size:12px;color:#72839c;margin-bottom:4px">生成时间 %(gen)s · 全自动扫描全A股，四层标准同 wolf-screener</div>
<div style="font-size:12px;color:#72839c;margin-bottom:10px">候选 %(cand)d 只 → A建议买入 <b style="color:#52c41a">%(a)d</b> · B观察 %(b)d · C禁止 %(c)d · D观望 %(d)d</div>
<div style="font-size:12px;color:#fdba74;line-height:1.6;background:rgba(250,140,22,.08);border:1px solid rgba(250,140,22,.3);border-radius:8px;padding:8px;margin-bottom:12px">
⚠️ 扫描环境取不到15分钟K线，第3层"技术共振"用日线代理(布林/MA20/放量/底背离)。网页端(wolf-screener3.0.html)以真实15min复核可得严格结论，第1/2/4层完全一致。本结果仅为波段信号参考，非投资建议。
</div>
<div style="font-size:15px;font-weight:700;color:#69db7c;margin:10px 0 8px">🟢 A 建议低吸（恐慌低位 + 技术共振 + 资金回流）</div>
%(cards_a)s
<div style="font-size:15px;font-weight:700;color:#fdba74;margin:14px 0 8px">🟡 B 纳入观察池（缺15min确认，等共振）</div>
<table style="width:100%%;border-collapse:collapse;font-size:12px"><thead><tr style="color:#b2bfd3;text-align:left">
<th>代码</th><th>名称</th><th class="c">贪婪</th><th class="c">净流入</th><th class="c">层1/层2</th></tr></thead>
<tbody>%(rows_b)s</tbody></table>
<div style="font-size:11px;color:#72839c;margin-top:16px;line-height:1.7">
数据：东方财富(列表/资金流) + 腾讯(K线)。脚本 auto_screener.py 可任意重跑；本页为 %(gen)s 的快照。
</div>
</body></html>''' % {
    'gen': gen, 'cand': s.get('cand', 0), 'a': s.get('A', 0), 'b': s.get('B', 0),
    'c': s.get('C', 0), 'd': s.get('D', 0), 'cards_a': cards_a, 'rows_b': rows_b
}

open('auto_pick.html', 'w', encoding='utf-8').write(HTML)
print('auto_pick.html 生成完成，A候选 %d 只' % len(A))
