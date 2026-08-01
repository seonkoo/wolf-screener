# -*- coding: utf-8 -*-
"""
改造 wolf-mobile4.2.html 与 wolf-screener3.0.html：
  1) 增加「💎 蓝筹低吸」tab 按钮
  2) 自动选股 pane 改为运行时 fetch auto_screen_result.json 渲染
  3) 新增 pane-bluechip，fetch blue_chip_result.json 渲染
  4) 在 </body> 前注入共享渲染脚本（带标记，可重复覆盖）

两个挂载点内置 <!--AUTOPICK_START/END--> 与 <!--BLUECHIP_START/END--> 标记，
sync_auto_tab.py 会把最新快照烘焙进标记之间，作为 file:// 本地打开时的离线兜底；
联网(GitHub Pages)打开时 fetch 成功会覆盖为最新数据。

用法：python patch_pages.py   （幂等，可反复执行）
"""
import os, re

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = ['wolf-mobile4.2.html', 'wolf-screener3.0.html']

LOADING_AUTO = ('<div class="panel"><div class="loading"><div class="spinner"></div>'
                '<div style="margin-top:8px">正在加载自动选股数据…</div></div></div>')
LOADING_BLUE = ('<div class="panel"><div class="loading"><div class="spinner"></div>'
                '<div style="margin-top:8px">正在加载蓝筹低吸数据…</div></div></div>')

# ---- 自动选股 pane（fetch 渲染 + 离线兜底标记）----
AUTO_PANE = '''<section class="pane" id="pane-auto">
  <div class="panel" style="font-size:11px;color:var(--t3);line-height:1.5">⚠️ 波段反弹信号，非投资建议；止损8% / 目标15%。第3层技术共振在扫描环境用「日线代理」（沙箱取不到15min K线），切到本Tab后用「🎯 选股雷达」以真实15min MACD复核。</div>
  <div id="autoMount"><!--AUTOPICK_START-->''' + LOADING_AUTO + '''<!--AUTOPICK_END--></div>
</section>'''

# ---- 蓝筹低吸 pane ----
BLUE_PANE = '''<section class="pane" id="pane-bluechip">
  <div class="panel" style="font-size:11px;color:var(--t3);line-height:1.5">💎 蓝筹价值 + 低吸区：沪深300里连续3年ROE&gt;12%、经营现金流为正、估值处近一年低位的公司。适合长期持有、分批慢慢低吸，以年为单位，忽略短期波动。非投资建议。</div>
  <div id="blueMount"><!--BLUECHIP_START-->''' + LOADING_BLUE + '''<!--BLUECHIP_END--></div>
</section>'''

BLUE_TAB_BTN = '  <button class="tab" data-tab="bluechip">💎 蓝筹低吸</button>'

JS_START = '<!--WOLF_RENDER_JS_START-->'
JS_END = '<!--WOLF_RENDER_JS_END-->'

# ---- 共享渲染脚本 ----
SCRIPT = JS_START + r'''
<script>
(function(){
  function esc(s){ return (s==null?'':String(s)).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
  function colorOf(v){ return v>=0 ? 'var(--red2)' : 'var(--green2)'; }
  function num(v,n){ return (v==null||isNaN(v)) ? '-' : Number(v).toFixed(n==null?2:n); }
  function chg(v){ return (v>=0?'+':'') + num(v,2) + '%'; }
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
      + '<div style="text-align:right"><div style="color:var(--t1);font-weight:700">'+num(r.price)+'</div>'
      + '<div style="font-size:12px;color:'+cc+'">'+chg(r.change)+'</div></div></div>'
      + '<div style="margin-top:6px;font-size:12px;color:var(--t2);display:flex;gap:8px;flex-wrap:wrap;align-items:center">'
      + greedBadge(l1.greed) + ' <span>主力 <b style="color:var(--green2)">'+money(r.inflow)+'</b></span></div>'
      + '<div style="margin-top:5px;font-size:11px;color:var(--t3);display:flex;gap:5px;flex-wrap:wrap">'
      + pill('①情绪',l1.status) + pill('②浪型',l2.status) + pill('③技术'+l3t,l3.status) + pill('④资金',l4.status) + '</div>'
      + '<div style="margin-top:5px;font-size:11px;color:var(--t3)">止损 <b>'+num(r.stop,3)+'</b> · 目标 <b>'+num(r.target,3)+'</b></div>'
      + '<div style="margin-top:4px;font-size:12px;color:var(--t2);line-height:1.5">'+esc(r.suggestion)+'</div></div>';
  }
  function autoRow(r){
    var col=colorOf(r.change||0);
    return '<tr style="font-size:12px;border-top:1px solid var(--line)">'
      + '<td style="padding:5px 4px;color:var(--t1)">'+esc(r.name)+'<br><span style="color:var(--t4);font-size:10px">'+esc(r.code)+'</span></td>'
      + '<td style="padding:5px 4px;color:var(--t1)">'+num(r.price)+'</td>'
      + '<td style="padding:5px 4px;color:'+col+'">'+chg(r.change)+'</td>'
      + '<td style="padding:5px 4px">'+((r.l1&&r.l1.greed!=null)?r.l1.greed.toFixed(1)+'%':'-')+'</td>'
      + '<td style="padding:5px 4px;color:var(--t3)">'+esc(r.template||'')+'</td></tr>';
  }
  function autoTable(items){
    var h='<div style="max-height:52vh;overflow-y:auto"><table style="width:100%;border-collapse:collapse">';
    h+='<tr style="color:var(--t4);font-size:11px;text-align:left"><th style="padding:4px">名称</th><th style="padding:4px">价</th><th style="padding:4px">涨跌</th><th style="padding:4px">贪婪</th><th style="padding:4px">判定</th></tr>';
    (items||[]).forEach(function(r){ h+=autoRow(r); });
    return h+'</table></div>';
  }
  function blueCard(p){
    var zone = p.below_ma ? '<span class="badge b-green">低吸区·低于年线</span>'
             : (p.near_low ? '<span class="badge b-green">近52周低位</span>'
                           : '<span class="badge b-amber">估值合理·待回调</span>');
    var pct = (p.pe_pct!=null) ? '<span class="badge b-green">PE近一年分位 '+Math.round(p.pe_pct*100)+'%</span>' : '';
    var gm  = (p.gm!=null) ? '<span>毛利 '+num(p.gm,1)+'%</span>' : '';
    return '<div style="padding:10px;margin-bottom:8px;background:var(--bg2);border-radius:10px;border-left:3px solid var(--blue)">'
      + '<div style="display:flex;justify-content:space-between;align-items:baseline">'
      + '<div style="font-weight:700;color:var(--t1)">'+esc(p.name)+' <span style="color:var(--t3);font-weight:400;font-size:12px">'+esc(p.code)+'</span></div>'
      + '<div style="text-align:right"><div style="color:var(--t1);font-weight:700">'+num(p.price)+'</div>'
      + '<div style="font-size:11px;color:var(--t3)">评分 '+num(p.score,1)+'</div></div></div>'
      + '<div style="margin-top:6px;font-size:11px;color:var(--t2);display:flex;gap:6px;flex-wrap:wrap;align-items:center">'
      + '<span class="badge b-green">3年ROE均 '+num(p.roe_avg,1)+'%</span>'
      + '<span>PE '+num(p.pe,1)+' · PB '+num(p.pb,2)+'</span>'
      + pct + gm + zone + '</div>'
      + '<div style="margin-top:5px;font-size:12px;color:var(--t2);line-height:1.5">'+esc(p.why)+'</div></div>';
  }
  function loadJSON(u){ return fetch(u,{cache:'no-store'}).then(function(r){ if(!r.ok) throw new Error(u+' '+r.status); return r.json(); }); }
  // fetch 失败时：若已有烘焙的离线快照就保留它，只加一条提示；否则显示错误框
  function fallback(id, msg){
    var el=document.getElementById(id); if(!el) return;
    var baked = el.innerHTML.indexOf('正在加载')<0 && el.innerHTML.replace(/<!--[\s\S]*?-->/g,'').trim().length>50;
    var tip='<div class="panel" style="font-size:11px;color:var(--t3);line-height:1.5">'+msg+'</div>';
    if(baked){ el.insertAdjacentHTML('afterbegin', tip); }
    else { el.innerHTML = tip; }
  }
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
    }).catch(function(e){
      fallback('autoMount','📴 未能实时拉取 auto_screen_result.json（'+esc(e.message)+'），以下为本地烘焙快照。要看每日最新，请访问 <a href="https://seonkoo.github.io/wolf-screener/" style="color:var(--blue)">seonkoo.github.io/wolf-screener</a>。');
    });
  }
  function loadBlue(){
    loadJSON('blue_chip_result.json').then(function(d){
      var s=d.summary||{};
      var h='<div class="panel"><div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">'
        + '<div><h3>💎 蓝筹低吸 · '+esc(s.universe||'沪深300')+'</h3><div class="panel-sub" style="margin-bottom:0">长期价值 + 低吸区 · 生成于 '+esc(d.generated)+'</div></div>'
        + '<div style="font-size:12px;color:var(--t2)">蓝筹池 <b>'+(s.cand||0)+'</b> → 质量过 <b>'+(s.passed_quality||0)+'</b> → 估值过 <b>'+(s.passed_valuation||0)+'</b> → 推荐 <b>'+(s.selected||0)+'</b></div></div></div>';
      var picks=d.picks||[];
      var low=picks.filter(function(p){return p.below_ma||p.near_low;});
      var wait=picks.filter(function(p){return !(p.below_ma||p.near_low);});
      h+='<div class="panel"><h3 style="margin-bottom:6px">🟢 现在就可分批低吸（'+low.length+'只）</h3>'
        + '<div style="font-size:11px;color:var(--t3);margin-bottom:8px">质地过关 + 估值低位 + 价格已在年线下方或近52周低位，建议分3-5批、每批间隔≥2周买入。</div>'
        + (low.length? low.map(blueCard).join('') : '<div style="font-size:12px;color:var(--t3)">今日无标的落入低吸区。</div>') +'</div>';
      h+='<details class="panel"><summary style="cursor:pointer;font-weight:600;color:var(--t1)">🟡 优质但仍需等回调（'+wait.length+'只）</summary>'
        + '<div style="font-size:11px;color:var(--t3);margin:6px 0">质地与估值都合格，但价格未进入低吸区，可加自选等回踩年线。</div>'
        + wait.map(blueCard).join('') +'</details>';
      var el=document.getElementById('blueMount'); if(el) el.innerHTML=h;
    }).catch(function(e){
      fallback('blueMount','📴 未能实时拉取 blue_chip_result.json（'+esc(e.message)+'），以下为本地烘焙快照。要看每日最新，请访问 <a href="https://seonkoo.github.io/wolf-screener/" style="color:var(--blue)">seonkoo.github.io/wolf-screener</a>。');
    });
  }
  // 支持 URL 锚点直达某个 tab，如 xxx.html#bluechip
  function applyHash(){
    if(!document.querySelector || typeof location==='undefined') return;
    var h=(location.hash||'').replace('#','');
    if(!h) return;
    var btn=document.querySelector('.tab[data-tab="'+h+'"]');
    if(btn) btn.click();
  }
  function boot(){ loadAuto(); loadBlue(); applyHash(); }
  if(document.readyState!=='loading'){ boot(); }
  else { document.addEventListener('DOMContentLoaded', boot); }
})();
</script>
''' + JS_END


def replace_section(s, sec_id, new_html):
    """整段替换 <section class="pane" id="xxx"> ... </section>（内部无嵌套 section）"""
    head = '<section class="pane" id="%s">' % sec_id
    start = s.find(head)
    if start < 0:
        return s, False
    end = s.find('</section>', start)
    if end < 0:
        return s, False
    end += len('</section>')
    return s[:start] + new_html + s[end:], True


def patch(fn):
    p = os.path.join(HERE, fn)
    s = open(p, encoding='utf-8').read()
    orig = s

    # 1) 蓝筹 tab 按钮（在 auto tab 按钮之后）
    if 'data-tab="bluechip"' not in s:
        idx = s.find('data-tab="auto"')
        if idx >= 0:
            # 必须插在「自动选股」按钮 </button> 之后，否则会变成嵌套 button
            end = s.find('</button>', idx)
            end = (end + len('</button>')) if end >= 0 else (s.find('>', idx) + 1)
            s = s[:end] + '\n' + BLUE_TAB_BTN + s[end:]
            print('  + 蓝筹tab按钮')
        else:
            print('  ! 未找到 auto tab 按钮')

    # 2) 自动选股 pane -> fetch 结构（保留已烘焙快照）
    m = re.search(r'<!--AUTOPICK_START-->(.*?)<!--AUTOPICK_END-->', s, re.S)
    baked_auto = m.group(1) if m else None
    s, ok = replace_section(s, 'pane-auto', AUTO_PANE)
    print(('  ~ 自动选股pane已刷新' if ok else '  ! 未找到 pane-auto'))
    if ok and baked_auto and '正在加载' not in baked_auto:
        s = s.replace('<!--AUTOPICK_START-->' + LOADING_AUTO + '<!--AUTOPICK_END-->',
                      '<!--AUTOPICK_START-->' + baked_auto + '<!--AUTOPICK_END-->', 1)
        print('    · 保留原离线快照')

    # 3) 蓝筹 pane
    m = re.search(r'<!--BLUECHIP_START-->(.*?)<!--BLUECHIP_END-->', s, re.S)
    baked_blue = m.group(1) if m else None
    s, ok = replace_section(s, 'pane-bluechip', BLUE_PANE)
    if not ok:  # 首次：插到 auto pane 之后
        ins = s.find('</section>', s.find('<section class="pane" id="pane-auto">'))
        if ins >= 0:
            ins += len('</section>')
            s = s[:ins] + '\n' + BLUE_PANE + s[ins:]
            print('  + 蓝筹pane（新建）')
        else:
            print('  ! 无法定位蓝筹pane插入点')
    else:
        print('  ~ 蓝筹pane已刷新')
    if baked_blue and '正在加载' not in baked_blue:
        s = s.replace('<!--BLUECHIP_START-->' + LOADING_BLUE + '<!--BLUECHIP_END-->',
                      '<!--BLUECHIP_START-->' + baked_blue + '<!--BLUECHIP_END-->', 1)
        print('    · 保留原离线快照')

    # 4) 渲染脚本（带标记，可覆盖）
    if JS_START in s and JS_END in s:
        i, j = s.index(JS_START), s.index(JS_END) + len(JS_END)
        s = s[:i] + SCRIPT + s[j:]
        print('  ~ 渲染脚本已更新')
    else:
        # 清掉旧的无标记脚本（上一版注入的）
        old = re.search(r'\n<script>\n\(function\(\)\{\n  function esc\(s\).*?\n</script>\n', s, re.S)
        if old:
            s = s[:old.start()] + s[old.end():]
            print('    · 移除旧版无标记脚本')
        bidx = s.rfind('</body>')
        if bidx >= 0:
            s = s[:bidx] + SCRIPT + '\n' + s[bidx:]
            print('  + 渲染脚本（新建）')
        else:
            print('  ! 未找到 </body>')

    if s != orig:
        open(p, 'w', encoding='utf-8').write(s)
        print('OK 已写入 %s (%d 字节)' % (fn, len(s)))
    else:
        print('无变更', fn)


if __name__ == '__main__':
    for f in FILES:
        print('==', f)
        patch(f)
