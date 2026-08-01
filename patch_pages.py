# -*- coding: utf-8 -*-
"""
改造 wolf-mobile4.2.html 与 wolf-screener3.0.html：
  1) 增加「💎 蓝筹低吸」tab 按钮
  2) 自动选股 pane 改为运行时 fetch auto_screen_result.json 渲染（替换写死示例）
  3) 新增 pane-bluechip，fetch blue_chip_result.json 渲染
  4) 在 </body> 前注入共享渲染脚本
用法：python patch_pages.py
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = ['wolf-mobile4.2.html', 'wolf-screener3.0.html']

# ---- 自动选股 pane 新内容（fetch 渲染）----
AUTO_PANE = '''<section class="pane" id="pane-auto">
  <div class="panel" style="font-size:11px;color:var(--t3);line-height:1.5">⚠️ 波段反弹信号，非投资建议；止损8%% / 目标15%%。第3层技术共振在扫描环境用「日线代理」（沙箱取不到15min K线），切到本Tab后用「🎯 选股雷达」以真实15min MACD复核。</div>
  <div id="autoMount"><div class="panel"><div class="loading"><div class="spinner"></div><div style="margin-top:8px">正在加载自动选股数据…</div></div></div></div>
</section>'''

# ---- 蓝筹低吸 pane 新内容 ----
BLUE_PANE = '''<section class="pane" id="pane-bluechip">
  <div class="panel" style="font-size:11px;color:var(--t3);line-height:1.5">💎 蓝筹价值 + 低吸区：适合长期持有，当前可分批慢慢低吸，以年为单位，忽略短期波动。非投资建议。</div>
  <div id="blueMount"><div class="panel"><div class="loading"><div class="spinner"></div><div style="margin-top:8px">正在加载蓝筹低吸数据…</div></div></div></div>
</section>'''

BLUE_TAB_BTN = '  <button class="tab" data-tab="bluechip">💎 蓝筹低吸</button>\n'

# ---- 共享渲染脚本 ----
SCRIPT = r'''
<script>
(function(){
  function esc(s){ return (s==null?'':String(s)).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
  function colorOf(v){ return v>=0 ? 'var(--red2)' : 'var(--green2)'; }
  function chg(v){ return (v>=0?'+':'') + (v!=null? v.toFixed(2):'0.00') + '%'; }
  function money(v){ var y=(v||0)/1e8; return (y>=0?'+':'') + y.toFixed(2)+'亿'; }
  function greedBadge(g){
    if(g==null) return '<span class="badge b-amber">—</span>';
    var c,t; if(g<35){c='b-green';t='恐慌低位';} else if(g>65){c='b-red';t='贪婪过热';} else {c='b-amber';t='中性';}
    return '<span class="badge '+c+'">'+t+' '+g.toFixed(1)+'%</span>';
  }
  function pill(label,st){
    var c = st=='pass'?'b-green':(st=='fail'?'b-red':'b-amber');
    var t = st=='pass'?'✓通过':(st=='fail'?'✗未过':'⏳观望');
    return '<span class="badge '+c+'">'+label+' '+t+'</span>';
  }
  function autoCard(r){
    var l1=r.l1||{}, l2=r.l2||{}, l3=r.l3||{}, l4=r.l4||{};
    var cc=colorOf(r.change||0);
    var l3t = l3.proxy? '⚠代理':'';
    var fund = r.fund && r.fund.good ? ' ★好公司' : '';
    return '<div style="padding:10px;margin-bottom:8px;background:var(--bg2);border-radius:10px;border-left:3px solid var(--green2)">'
      + '<div style="display:flex;justify-content:space-between;align-items:baseline">'
      + '<div style="font-weight:700;color:var(--t1)">'+esc(r.name)+' <span style="color:var(--t3);font-weight:400;font-size:12px">'+esc(r.code)+fund+'</span></div>'
      + '<div style="text-align:right"><div style="color:var(--t1);font-weight:700">'+(r.price!=null?r.price.toFixed(2):'-')+'</div>'
      + '<div style="font-size:12px;color:'+cc+'">'+chg(r.change)+'</div></div></div>'
      + '<div style="margin-top:6px;font-size:12px;color:var(--t2);display:flex;gap:8px;flex-wrap:wrap;align-items:center">'
      + greedBadge(l1.greed) + ' <span>主力 <b style="color:var(--green2)">'+money(r.inflow)+'</b></span></div>'
      + '<div style="margin-top:5px;font-size:11px;color:var(--t3);display:flex;gap:5px;flex-wrap:wrap">'
      + pill('①情绪',l1.status) + pill('②浪型',l2.status) + pill('③技术'+l3t,l3.status) + pill('④资金',l4.status) + '</div>'
      + '<div style="margin-top:5px;font-size:11px;color:var(--t3)">止损 <b>'+(r.stop!=null?r.stop.toFixed(3):'-')+'</b> · 目标 <b>'+(r.target!=null?r.target.toFixed(3):'-')+'</b></div>'
      + '<div style="margin-top:4px;font-size:12px;color:var(--t2);line-height:1.5">'+esc(r.suggestion)+'</div></div>';
  }
  function autoRow(r){
    var col=colorOf(r.change||0);
    return '<tr style="font-size:12px;border-top:1px solid var(--line)">'
      + '<td style="padding:5px 4px;color:var(--t1)">'+esc(r.name)+'<br><span style="color:var(--t4);font-size:10px">'+esc(r.code)+'</span></td>'
      + '<td style="padding:5px 4px;color:var(--t1)">'+(r.price!=null?r.price.toFixed(2):'-')+'</td>'
      + '<td style="padding:5px 4px;color:'+col+'">'+chg(r.change)+'</td>'
      + '<td style="padding:5px 4px">'+(r.l1&&r.l1.greed!=null?r.l1.greed.toFixed(1)+'%':'-')+'</td>'
      + '<td style="padding:5px 4px;color:var(--t3)">'+(r.template||'')+'</td></tr>';
  }
  function autoTable(items){
    var h='<div style="max-height:52vh;overflow-y:auto"><table style="width:100%;border-collapse:collapse">';
    h+='<tr style="color:var(--t4);font-size:11px;text-align:left"><th style="padding:4px">名称</th><th style="padding:4px">价</th><th style="padding:4px">涨跌</th><th style="padding:4px">贪婪</th><th style="padding:4px">判定</th></tr>';
    (items||[]).forEach(function(r){ h+=autoRow(r); });
    return h+'</table></div>';
  }
  function blueCard(p){
    var zone = p.below_ma ? '<span class="badge b-green">低吸区·低于年线</span>' : (p.near_low?'<span class="badge b-green">近52周低位</span>':'<span class="badge b-amber">估值合理</span>');
    return '<div style="padding:10px;margin-bottom:8px;background:var(--bg2);border-radius:10px;border-left:3px solid var(--blue)">'
      + '<div style="display:flex;justify-content:space-between;align-items:baseline">'
      + '<div style="font-weight:700;color:var(--t1)">'+esc(p.name)+' <span style="color:var(--t3);font-weight:400;font-size:12px">'+esc(p.code)+'</span></div>'
      + '<div style="text-align:right"><div style="color:var(--t1);font-weight:700">'+(p.price!=null?p.price.toFixed(2):'-')+'</div></div></div>'
      + '<div style="margin-top:6px;font-size:11px;color:var(--t2);display:flex;gap:6px;flex-wrap:wrap;align-items:center">'
      + '<span class="badge b-green">ROE均 '+p.roe_avg+'%</span>'
      + '<span class="badge b-amber">股息 '+p.div_yield+'%</span>'
      + '<span>PE '+p.pe+' / PB '+p.pb+'</span>'
      + zone + '</div>'
      + '<div style="margin-top:5px;font-size:12px;color:var(--t2);line-height:1.5">'+esc(p.why)+'</div></div>';
  }
  function loadJSON(u){ return fetch(u,{cache:'no-store'}).then(function(r){ if(!r.ok) throw new Error(u+' '+r.status); return r.json(); }); }
  function errBox(id,msg){ var el=document.getElementById(id); if(el) el.innerHTML='<div class="panel" style="font-size:12px;color:var(--t3)">'+msg+'</div>'; }
  function loadAuto(){
    loadJSON('auto_screen_result.json').then(function(d){
      var s=d.summary||{};
      var h='<div class="panel"><div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">'
        + '<div><h3>🤖 自动选股 · 全A四层扫描</h3><div class="panel-sub" style="margin-bottom:0">小狼策略自动筛选 · 生成于 '+esc(d.generated)+'</div></div>'
        + '<div style="font-size:12px;color:var(--t2)">候选 <b>'+(s.cand||0)+'</b> · 🟢A <b>'+(s.A||0)+'</b> · 🔵B <b>'+(s.B||0)+'</b> · 🔴C <b>'+(s.C||0)+'</b> · ⚪D <b>'+(s.D||0)+'</b></div></div></div>';
      h+='<div class="panel"><h3 style="margin-bottom:6px">🟢 A · 建议低吸（四层全过 '+(s.A||0)+'只）</h3>'+ (d.A||[]).map(autoCard).join('') +'</div>';
      h+='<details class="panel"><summary style="cursor:pointer;font-weight:600;color:var(--t1)">🔵 B · 观察（'+(s.B||0)+'只）</summary>'+ autoTable(d.B) +'</details>';
      h+='<details class="panel"><summary style="cursor:pointer;font-weight:600;color:var(--t1)">🔴 C · 禁止（'+(s.C||0)+'只）</summary>'+ autoTable(d.C) +'</details>';
      h+='<details class="panel"><summary style="cursor:pointer;font-weight:600;color:var(--t1)">⚪ D · 观望（'+(s.D||0)+'只）</summary>'+ autoTable(d.D) +'</details>';
      var el=document.getElementById('autoMount'); if(el) el.innerHTML=h;
    }).catch(function(e){ errBox('autoMount','自动选股数据加载失败（'+esc(e.message)+'）。请通过部署后的网页(https://seonkoo.github.io/wolf-screener/)查看，并确认 auto_screen_result.json 已随仓库部署。'); });
  }
  function loadBlue(){
    loadJSON('blue_chip_result.json').then(function(d){
      var s=d.summary||{};
      var h='<div class="panel"><div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">'
        + '<div><h3>💎 蓝筹低吸 · '+esc(s.universe||'沪深300')+'</h3><div class="panel-sub" style="margin-bottom:0">长期价值+低吸区 · 生成于 '+esc(d.generated)+'</div></div>'
        + '<div style="font-size:12px;color:var(--t2)">蓝筹池 <b>'+(s.cand||0)+'</b> → 估值分红过 <b>'+(s.passed_valuation||0)+'</b> → 质量过 <b>'+(s.passed_quality||0)+'</b> → 推荐 <b>'+(s.selected||0)+'</b></div></div></div>';
      h+='<div class="panel"><h3 style="margin-bottom:6px">💎 推荐慢慢低吸（'+(s.selected||0)+'只）</h3>'+ (d.picks||[]).map(blueCard).join('') +'</div>';
      var el=document.getElementById('blueMount'); if(el) el.innerHTML=h;
    }).catch(function(e){ errBox('blueMount','蓝筹低吸数据加载失败（'+esc(e.message)+'）。请通过部署后的网页查看，并确认 blue_chip_result.json 已随仓库部署。'); });
  }
  if(document.readyState!=='loading'){ loadAuto(); loadBlue(); }
  else { document.addEventListener('DOMContentLoaded', function(){ loadAuto(); loadBlue(); }); }
})();
</script>
'''

def patch(fn):
    p = os.path.join(HERE, fn)
    s = open(p, encoding='utf-8').read()
    orig = s
    # 1) 加蓝筹 tab 按钮（在 auto tab 按钮之后）
    if 'data-tab="bluechip"' not in s:
        idx = s.find('data-tab="auto"')
        if idx >= 0:
            # 找到该 button 行的结尾 '>'
            end = s.find('>', idx) + 1
            s = s[:end] + '\n' + BLUE_TAB_BTN.rstrip('\n') + s[end:]
            print('  + 蓝筹tab按钮 ->', fn)
        else:
            print('  ! 未找到 auto tab 按钮', fn)
    # 2) 替换自动选股 pane
    start = s.find('<section class="pane" id="pane-auto">')
    if start >= 0:
        end = s.find('</section>', start)
        if end >= 0:
            end += len('</section>')
            s = s[:start] + AUTO_PANE + s[end:]
            print('  ~ 自动选股pane改为fetch ->', fn)
        else:
            print('  ! 未找到 auto pane 结束', fn)
    else:
        print('  ! 未找到 pane-auto', fn)
    # 3) 插入蓝筹 pane（在 auto pane 结束后）
    if 'id="pane-bluechip"' not in s:
        ins = s.find('</section>', s.find('<section class="pane" id="pane-auto">'))
        if ins >= 0:
            ins += len('</section>')
            s = s[:ins] + '\n' + BLUE_PANE + s[ins:]
            print('  + 蓝筹pane ->', fn)
        else:
            print('  ! 无法定位插入点', fn)
    # 4) 注入脚本（在 </body> 前）
    if 'function loadBlue' not in s:
        bidx = s.rfind('</body>')
        if bidx >= 0:
            s = s[:bidx] + SCRIPT + '\n' + s[bidx:]
            print('  + 渲染脚本 ->', fn)
        else:
            print('  ! 未找到 </body>', fn)
    if s != orig:
        open(p, 'w', encoding='utf-8').write(s)
        print('OK 已写入', fn, '(', len(s), '字节 )')
    else:
        print('无变更', fn)

if __name__ == '__main__':
    for f in FILES:
        print('==', f)
        patch(f)
