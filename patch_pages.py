# -*- coding: utf-8 -*-
"""
改造 wolf-mobile4.2.html 与 wolf-screener3.0.html：
  1) 自动选股 pane 改为运行时 fetch auto_screen_result.json 渲染
  2) 在 </body> 前注入共享渲染脚本（带标记，可重复覆盖）

挂载点内置 <!--AUTOPICK_START/END--> 等标记，sync_auto_tab.py 会把最新快照烘焙进标记之间，
作为 file:// 本地打开时的离线兜底；联网(GitHub Pages)打开时 fetch 成功会覆盖为最新数据。

注：原「💎 蓝筹低吸」独立 Tab 已删除（回测显示「跌破年线低吸」无超额收益）；
蓝筹「低值发现」仍保留在「📊 市场研判」李大霄模块内（按估值分位，非按破线低吸）。

用法：python patch_pages.py   （幂等，可反复执行）
"""
import os, re

HERE = os.path.dirname(os.path.abspath(__file__))
FILES = ['wolf-mobile4.2.html', 'wolf-screener3.0.html']

LOADING_AUTO = ('<div class="panel"><div class="loading"><div class="spinner"></div>'
                '<div style="margin-top:8px">正在加载自动选股数据…</div></div></div>')
LOADING_TEAM = ('<div class="panel"><div class="loading"><div class="spinner"></div>'
                '<div style="margin-top:8px">正在加载国家队资金数据…</div></div></div>')
LOADING_SENT = ('<div class="panel"><div class="loading"><div class="spinner"></div>'
                '<div style="margin-top:8px">正在加载市场情绪数据…</div></div></div>')
LOADING_OVERVIEW = ('<div class="panel"><div class="loading"><div class="spinner"></div>'
                '<div style="margin-top:8px">正在加载综合研判…</div></div></div>')
LOADING_WATCH = ('<div class="panel"><div class="loading"><div class="spinner"></div>'
                '<div style="margin-top:8px">正在加载观察池…</div></div></div>')
LOADING_LIDAXIAO = ('<div class="panel"><div class="loading"><div class="spinner"></div>'
                '<div style="margin-top:8px">正在加载李大霄底部研判…</div></div></div>')
LOADING_SECTOR = ('<div class="panel"><div class="loading"><div class="spinner"></div>'
                '<div style="margin-top:8px">正在加载板块资金流向…</div></div></div>')

# ---- 自动选股 pane（fetch 渲染 + 离线兜底标记）----
AUTO_PANE = '''<section class="pane" id="pane-auto">
  <div class="panel" style="font-size:11px;color:var(--t3);line-height:1.5">⚠️ 波段反弹信号，非投资建议；止损8% / 目标15%。第3层技术共振在扫描环境用「日线代理」（沙箱取不到15min K线），切到本Tab后用「🎯 选股雷达」以真实15min MACD复核。</div>
  <div id="guardMount"><!--GUARD_START--><div class="panel" style="font-size:11px;color:var(--t3)">正在加载策略体检…</div><!--GUARD_END--></div>
  <div id="autoMount"><!--AUTOPICK_START-->''' + LOADING_AUTO + '''<!--AUTOPICK_END--></div>
</section>'''

MARKET_TAB_BTN = '  <button class="tab" data-tab="market">📊 市场研判</button>'
WATCH_TAB_BTN = '  <button class="tab" data-tab="watch">📈 观察池</button>'
TRADETIME_TAB_BTN = '  <button class="tab" data-tab="tradetime">⏱️ 交易时机</button>'
LOADING_TRADETIME = ('<div class="panel"><div class="loading"><div class="spinner"></div>'
                '<div style="margin-top:8px">正在加载交易时机数据…</div></div></div>')

# ---- 市场研判（综合研判 + 全球市场 + 重大事件 + 国家队资金 + 情绪指数 合并为一个 Tab）----
# 注意：综合研判/国家队/情绪 用 snapshot 标记(sync_auto_tab.py 注入)；全球/重大事件 为前端独立渲染空壳(DOM id 由 renderGlobal/loadMajorEvents 填充)
MARKET_PANE = '''<section class="pane" id="pane-market">
  <div class="panel" style="font-size:11px;color:var(--t3);line-height:1.5">📊 市场研判（合并）：综合研判 + 全球市场 + 重大事件 + 国家队资金 + 情绪指数 五合一，解决多信号互相打架时不知如何加权。非投资建议。</div>

  <div class="panel" style="background:var(--bg2);font-size:11px;color:var(--t2);line-height:1.6">
    🏷️ <b>本页模块可信度分级</b>：
    <span style="color:var(--green2);border:1px solid var(--green2);border-radius:6px;padding:1px 6px;margin:0 4px">🟩 回测验证信号</span> 自动选股（胜率经历史回测，见「🐺 自动选股」Tab）
    <span style="color:#d99e00;border:1px solid #d99e00;border-radius:6px;padding:1px 6px;margin:0 4px">🟡 主观框架/辅助参考</span> 估值温度·波浪·情绪·国家队——供研判参考，<b>非买卖指令</b>，须与「回测信号」结合使用。
  </div>

  <!-- 0.5 板块资金 · 买卖策略导向 -->
  <div id="sectorMount"><!--SECTORFLOW_START-->''' + LOADING_SECTOR + '''<!--SECTORFLOW_END--></div>

  <!-- 1. 综合研判（置顶一句话 + 机会分） -->
  <div class="panel" style="font-size:11px;color:var(--t3);line-height:1.5">🧭 综合研判：把市场状态 / 国家队 / 情绪 / 选股 / 实盘验证 五个维度合成「机会分 + 一句话研判」。非投资建议。</div>
  <div id="synthesisMount"><!--SYNTHESIS_START-->''' + LOADING_OVERVIEW + '''<!--SYNTHESIS_END--></div>

  <!-- 1.5 李大霄历史底部研判 -->
  <div class="panel" style="font-size:11px;color:var(--t3);line-height:1.5">📉 李大霄历史底部研判体系：融合 2015婴儿底 / 2019年2440大底 / 2022年3000点 三套经典标准，适配2026全面注册制做量化修订。⚠️ 估值底部≠立刻上涨，仅代表下行空间收敛；只适用于优质龙头，垃圾股无安全垫。<span style="color:#d99e00;border:1px solid #d99e00;border-radius:6px;padding:1px 5px;margin-left:6px">🟡 主观框架·辅助参考</span></div>
  <div id="ldMount"><!--LIDAXIAO_START-->''' + LOADING_LIDAXIAO + '''<!--LIDAXIAO_END--></div>
  <details class="panel"><summary style="cursor:pointer;font-weight:600;color:var(--t1)">📜 研判框架（三套历史底部 + 2026修订规则 + 核心原则 + 融合小狼）</summary>
    <div style="font-size:12px;color:var(--t2);line-height:1.7;margin-top:6px">
      <b>三套历史底部原始基准</b><br>
      · 2015 婴儿底(沪指2850)：上证50 PE≈8.5、股息率3.66%；高杠杆出清、做空受限、暂停IPO/减持、救市政策密集。<br>
      · 2019 历史大底(沪指2440)：上证50 PE≈8.3、股息率3.44%；货币宽松、长线资金(外资/养老金/险资)入场、财政发力 → 政策底+市场底。<br>
      · 2022 3000点：上证50 PE≈8.7、股息率≈3.3%；长期逻辑(经济+龙头权重提升)、制度改善(长期资金+回购)。3000下方是稀缺布局窗口，仅限优质好股。<br><br>
      <b>2026 量化修订 · 三档估值锚（上证50 静态PE）</b><br>
      · ✅ 极致底部：PE ≤ 8.5（对标2440/2850）<br>
      · ✅ 温和底部：PE 8.5 ~ 10（对标2022年3000点）<br>
      · ⚠️ 接近底部：PE &gt; 10（当前现状）<br><br>
      <b>五维量化判定</b>：①估值(PE/股息率历史低位) ②杠杆(两融平稳) ③资金(外资/险资/产业资本增持回购) ④供给(IP节奏平稳、无解禁冲击) ⑤政策(货币宽松+活跃资本市场)。<br>
      判定：≥4项达标+极致底部→中长期底部分批布局；3项+温和底部→临近底部轻仓试错；≤2项/估值未达标→谨慎新开仓控仓。<br><br>
      <b>核心原则</b>：①指数低位≠所有股涨，只拥抱低估值稳定盈利龙头；②底部可反复磨，禁一次性满仓；③注册制下筹码持续供给，难复刻快速普涨，行情以结构性为主。<br><br>
      <b>与小狼策略融合</b>：李大霄体系判「大盘环境大时机」→ 达标后再用小狼策略(个股资金/波浪/技术)筛「个股买点」。先大后小，顺序不可颠倒。
    </div>
  </details>

  <!-- 1.6 艾略特波浪理论 -->
  <div class="panel" style="font-size:11px;color:var(--t3);line-height:1.5">🌊 艾略特波浪理论：用日K线拐点(ZigZag)识别「5浪推动 + 3浪调整」八浪循环，推测当前所处浪与细浪，给出操作参考。波浪划分具概率性、非精确预测；须结合大趋势/估值/资金，非投资建议。<span style="color:#d99e00;border:1px solid #d99e00;border-radius:6px;padding:1px 5px;margin-left:6px">🟡 技术分析框架·非买卖信号</span></div>
  <div class="panel" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
    <div><h3 style="margin-bottom:0">🌊 艾略特波浪 · 大盘与个股</h3><div class="panel-sub" style="margin-bottom:0">默认上证指数日K；可切深证/创业板，或输入个股代码实时分析。</div></div>
    <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
      <select id="ewIndex" class="ipt" style="padding:5px 8px">
        <option value="sh000001">上证指数</option>
        <option value="sz399001">深证成指</option>
        <option value="sz399006">创业板指</option>
      </select>
      <button class="btn primary" id="ewIndexBtn">分析</button>
    </div>
  </div>
  <div class="panel" style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
    <span style="color:var(--t2)">个股代码：</span>
    <input id="ewCode" class="ipt" style="width:120px;padding:5px 8px" placeholder="如 600519" />
    <button class="btn" id="ewCodeBtn">分析个股波浪</button>
    <span id="ewCodeMsg" style="font-size:11px;color:var(--t3)"></span>
  </div>
  <div id="ewMount"><div style="font-size:12px;color:var(--t3);padding:8px">🌊 正在拉取日K线并计算波浪结构…</div></div>
  <div id="ewAdvise"></div>

  <!-- 2. 全球市场 -->
  <div class="panel" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
    <div><h3 style="margin-bottom:0">🌐 全球市场 · 外围环境扫描</h3><div class="panel-sub" style="margin-bottom:0">数据来源：腾讯（美股七姐妹 / 韩股 / A50·黄金·原油ETF代理）、东方财富（韩国KOSPI指数）。与A股四层筛选联动研判。</div></div>
    <button class="btn primary" id="globalRefreshBtn">🔄 刷新</button>
  </div>
  <div id="globalLoading" class="loading"><div class="spinner"></div><div style="margin-top:8px">正在拉取全球行情...</div></div>
  <div class="panel" style="border:1px solid var(--blue)">
    <h3>📊 综合研判 · 外围对A股波段反弹的影响</h3>
    <div id="globalVerdict" style="margin-bottom:8px;font-size:14px">加载中...</div>
    <div id="globalLines" style="font-size:13px;color:var(--t2);line-height:1.7">—</div>
    <div class="suggest suggest-b" style="margin-top:10px"><div id="globalAdvice" style="font-size:13px;color:var(--t1)">—</div></div>
  </div>
  <div class="panel"><h3>纳指七姐妹（Magnificent 7）</h3><div class="panel-sub">美国科技龙头，反映全球风险偏好与AI产业景气，是A股成长板块的情绪锚</div><table><thead><tr><th>个股</th><th class="c">最新价(USD)</th><th class="c">涨跌幅</th></tr></thead><tbody id="mag7Body"><tr><td colspan="3" class="c" style="color:var(--t3);padding:16px">加载中...</td></tr></tbody></table></div>
  <div class="grid g2">
    <div class="panel"><h3>韩国市场 · 半导体风向标</h3><div class="panel-sub">三星 / 海力士为全球存储芯片景气领先指标，直接影响A股半导体链</div><div class="grid g3" id="krCards"></div></div>
    <div class="panel"><h3>大宗商品 & A50期货</h3><div class="panel-sub">黄金 = 避险温度，原油 = 通胀/成本压力，A50 = 境外对中国资产预期</div><div class="grid g3" id="comCards"></div><div style="font-size:11px;color:var(--t4);margin-top:8px">注：黄金 / 原油 / A50 采用A股ETF代理（A股交易时段内紧密追踪真实标的），非交易时段显示当日收盘值。</div></div>
  </div>

  <!-- 3. 重大事件 -->
  <div class="panel" id="eventsPanel">
    <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
      <div><h3>📅 重大事件 · 财经日历</h3><div class="panel-sub" style="margin-bottom:0">东方财富财经日历 · 经济数据 / 新股 / 会议 / 政策（今日及未来3天）· <span style="color:var(--red2)">🌍 影响全球资金流动性的新闻置顶</span></div></div>
      <button class="btn" id="eventsRefreshBtn" style="font-size:12px;padding:6px 10px">🔄 刷新</button>
    </div>
    <div id="eventsLoading" class="loading"><div class="spinner"></div><div style="margin-top:8px">正在拉取财经日历...</div></div>
    <div id="eventsBody" style="display:none;max-height:72vh;overflow-y:auto;margin-top:6px"></div>
  </div>

  <!-- 4. 国家队资金 -->
  <div class="panel" style="font-size:11px;color:var(--t3);line-height:1.5">🏛️ 国家队资金走向：中证1000/科创50/创业板/沪深300 宽基ETF 成交活跃度 + 实时份额 + 市场状态，推断大资金进场/离场。结论为活跃度推断，非精确持仓复刻，不构成投资建议。</div>
  <div id="teamMount"><!--TEAM_START-->''' + LOADING_TEAM + '''<!--TEAM_END--></div>

  <!-- 5. 情绪指数 -->
  <div class="panel" style="font-size:11px;color:var(--t3);line-height:1.5">🌡️ 市场情绪指数（恐惧贪婪 0-100，反向指标）：冰点逆向买入、狂热逆向卖出。数据=微博财经NLP舆情 + 市场代理。非投资建议。</div>
  <div id="sentMount"><!--SENT_START-->''' + LOADING_SENT + '''<!--SENT_END--></div>
</section>'''

# ---- 观察池 / 实盘验证 pane ----
WATCH_PANE = '''<section class="pane" id="pane-watch">
  <div class="panel" style="font-size:11px;color:var(--t3);line-height:1.5">📈 观察池 · 实盘验证：自动追踪「自动选股」输出的买入标的，自输出以来的真实走向与是否符合预期。命中率低于回测基线时策略体检将亮红灯。非投资建议。</div>
  <div id="watchMount"><!--WATCH_START-->''' + LOADING_WATCH + '''<!--WATCH_END--></div>
</section>'''

# ---- 交易时机 pane（默认第一个主入口：大市环境横幅 + 按确定性排序的买卖决策列表）----
TRADETIME_PANE = '''<section class="pane" id="pane-tradetime">
  <div class="panel" style="font-size:11px;color:var(--t3);line-height:1.5">⏱️ 交易时机：把「大市环境 + 信号」收敛成一句话买卖决策（开仓? / 买入时机 / 持股时间 / 止盈止损 / 买入理由）。李大霄温度·波浪·板块资金·四层·小狼2.0 是其底层判断逻辑。非投资建议。</div>
  <div id="ttBanner"><!--TTBANNER_START-->''' + LOADING_TRADETIME + '''<!--TTBANNER_END--></div>
  <div style="margin-top:10px">
    <div class="panel" style="font-weight:700;color:var(--t1);margin-bottom:6px">📈 个股交易时机</div>
    <div id="ttMount"><!--TRADETIME_START-->''' + LOADING_TRADETIME + '''<!--TRADETIME_END--></div>
  </div>
  <div style="margin-top:14px">
    <div class="panel" style="font-weight:700;color:var(--t1);margin-bottom:6px">📊 ETF / LOF 交易时机</div>
    <div id="etfMount"><!--ETFTIME_START-->''' + LOADING_TRADETIME + '''<!--ETFTIME_END--></div>
  </div>
</section>'''

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
  // 蓝筹卡片渲染 blueCard 已随「蓝筹低吸」Tab 删除（回测显示跌破年线低吸无超额）

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
  function loadGuard(){
    loadJSON('strategy_guard.json').then(function(g){
      var lvl=g.risk_level||'GREEN'; var rg=g.regime||{}; var pr=g.position_rule||{};
      var dot=lvl=='GREEN'?'🟢':(lvl=='AMBER'?'🟡':'🔴');
      var label=lvl=='GREEN'?'正常':(lvl=='AMBER'?'建议调整':'建议暂停');
      var border=lvl=='GREEN'?'var(--green2)':(lvl=='AMBER'?'#d99e00':'var(--red2)');
      var html='<div class="panel" style="border-left:4px solid '+border+';background:var(--bg2)">'
        +'<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px">'
        +'<div style="font-weight:700;color:var(--t1)">'+dot+' 策略体检 · '+label+'</div>'
        +'<div style="font-size:12px;color:var(--t2)">市场 '+(rg.level||'-')+' · 仓位 '+(pr.size_mult!=null?pr.size_mult:1)+'x · 止损 '+Math.round((pr.stop_pct!=null?pr.stop_pct:0.08)*100)+'%</div></div>'
        +'<div style="margin-top:5px;font-size:12px;color:var(--t2);line-height:1.5">'+esc(rg.note||'')+'</div>'
        +'<div style="margin-top:5px;font-size:11px;color:var(--t3)">'+(g.actions?g.actions.join(' ｜ '):'')+'</div></div>';
      var el=document.getElementById('guardMount'); if(el) el.innerHTML=html;
    }).catch(function(e){
      var el=document.getElementById('guardMount');
      if(el && el.innerHTML.indexOf('正在加载')>=0){ el.innerHTML='<div class="panel" style="font-size:11px;color:var(--t3)">📴 未能实时拉取策略体检（'+esc(e.message)+'），以下为本地烘焙快照。</div>'; }
    });
  }
  // 支持 URL 锚点直达某个 tab，如 xxx.html#market
  function applyHash(){
    if(!document.querySelector || typeof location==='undefined') return;
    var h=(location.hash||'').replace('#','');
    if(!h) return;
    var btn=document.querySelector('.tab[data-tab="'+h+'"]');
    if(btn) btn.click();
  }
  function loadTeam(){
    loadJSON('national_team.json').then(function(d){
      var rg=d.regime||{}; var c=d.conclusion||{}; var etfs=d.etfs||[];
      var att=c.attitude||'-';
      var attColor = att.indexOf('进场')>=0?'var(--green2)':(att.indexOf('离场')>=0?'var(--red2)':'var(--t3)');
      var h='<div class="panel"><div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">'
        +'<div><h3>🏛️ 国家队资金走向</h3><div class="panel-sub" style="margin-bottom:0">生成于 '+esc(d.generated)+' · 沪深300 '+esc(rg.state||'-')+'</div></div>'
        +'<div style="font-weight:700;color:'+attColor+'">大资金：'+esc(att)+'</div></div></div>';
      h+='<div class="panel" style="font-size:12px;color:var(--t2);line-height:1.6">'+esc(c.summary||'')+'</div>';
      h+='<div class="panel"><h3 style="margin-bottom:6px">宽基ETF 成交活跃度（估算成交额·亿元）</h3>';
      h+='<div style="max-height:46vh;overflow-y:auto"><table style="width:100%;border-collapse:collapse;font-size:12px">';
      h+='<tr style="color:var(--t4);text-align:left"><th style="padding:4px">ETF</th><th style="padding:4px">5日</th><th style="padding:4px">20日</th><th style="padding:4px">60日</th><th style="padding:4px">趋势</th><th style="padding:4px">份额(亿)</th></tr>';
      etfs.forEach(function(e){
        var tcol = e.trend==='上行'?'var(--red2)':(e.trend==='下行'?'var(--green2)':'var(--t3)');
        h+='<tr style="border-top:1px solid var(--line)">'
          +'<td style="padding:5px 4px;color:var(--t1)">'+esc(e.name)+'<br><span style="color:var(--t4);font-size:10px">'+esc(e.role||'')+'</span></td>'
          +'<td style="padding:5px 4px">'+num(e.turnover_5d,1)+'</td>'
          +'<td style="padding:5px 4px">'+num(e.turnover_20d,1)+'</td>'
          +'<td style="padding:5px 4px">'+num(e.turnover_60d,1)+'</td>'
          +'<td style="padding:5px 4px;color:'+tcol+'">'+esc(e.trend)+'<br><span style="font-size:10px;color:var(--t3)">'+esc(e.short_term)+'</span></td>'
          +'<td style="padding:5px 4px">'+((e.shares_now_亿份!=null)?num(e.shares_now_亿份,1):'-')+'</td></tr>';
      });
      h+='</table></div></div>';
      var v=d.validation||{};
      h+='<div class="panel" style="font-size:11px;color:var(--t3);line-height:1.5">✔ 验证：政策底由宽基ETF托市(True)；高位撤离(True,2026开年降温式调仓)。'+esc(v.note||'')+'</div>';
      h+='<div class="panel" style="font-size:11px;color:var(--t4);line-height:1.5">⚠ '+esc(d.caveat||'')+'</div>';
      var el=document.getElementById('teamMount'); if(el) el.innerHTML=h;
    }).catch(function(e){
      fallback('teamMount','📴 未能实时拉取 national_team.json（'+esc(e.message)+'），以下为本地烘焙快照。');
    });
  }
  function loadSent(){
    loadJSON('sentiment.json').then(function(d){
      var idx=d.index==null?50:d.index; var zone=d.zone||'中性'; var adv=d.advice||'';
      var barColor = idx<35?'var(--green2)':(idx>65?'var(--red2)':'#d99e00');
      var h='<div class="panel"><div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">'
        +'<div><h3>🌡️ 市场情绪指数</h3><div class="panel-sub" style="margin-bottom:0">恐惧贪婪 0-100 · 反向指标 · 生成于 '+esc(d.generated)+'</div></div>'
        +'<div style="font-weight:700;color:var(--t1)">'+num(idx,0)+' · '+esc(zone)+'</div></div></div>';
      h+='<div class="panel"><div style="height:14px;background:linear-gradient(90deg,var(--green2),#d99e00,var(--red2));border-radius:7px;position:relative;margin:8px 0 4px">'
        +'<div style="position:absolute;top:-4px;left:calc('+idx+'% - 3px);width:6px;height:22px;background:#fff;border:2px solid var(--t1);border-radius:3px"></div></div>'
        +'<div style="display:flex;justify-content:space-between;font-size:10px;color:var(--t4)"><span>冰点(逆向买)</span><span>中性</span><span>狂热(逆向卖)</span></div>';
      h+='<div style="margin-top:8px;font-size:13px;color:'+barColor+';font-weight:600">'+esc(adv)+'</div></div>';
      var comp=d.components||{};
      h+='<div class="panel" style="font-size:12px;color:var(--t2)">数据构成：微博舆情NLP <b>'+num(comp.weibo_sentiment,0)+'</b> ｜ 市场代理 <b>'+num(comp.market_proxy,0)+'</b> ｜ 合成 <b>'+num(idx,0)+'</b><br><span style="color:var(--t3);font-size:11px">来源：'+esc(d.source_detail||'')+'</span></div>';
      var fs=d.forums_status||{};
      h+='<details class="panel"><summary style="cursor:pointer;font-weight:600;color:var(--t1)">论坛接入状态</summary><div style="font-size:11px;color:var(--t3);margin-top:6px;line-height:1.6">'
        + Object.keys(fs).map(function(k){return '· '+esc(k)+'：'+esc(fs[k]);}).join('<br>') +'</div></details>';
      var v=d.validation||{};
      h+='<div class="panel" style="font-size:11px;color:var(--t3);line-height:1.5">✔ 验证：散户情绪作反向指标有效——回测极度悲观买入胜率68.1%、极度乐观卖出68.6%。'+esc(v.note||'')+'</div>';
      h+='<div class="panel" style="font-size:11px;color:var(--t4);line-height:1.5">⚠ '+esc(d.caveat||'')+'</div>';
      var el=document.getElementById('sentMount'); if(el) el.innerHTML=h;
    }).catch(function(e){
      fallback('sentMount','📴 未能实时拉取 sentiment.json（'+esc(e.message)+'），以下为本地烘焙快照。');
    });
  }
  function loadSynthesis(){
    loadJSON('overview.json').then(function(d){
      var sc=d.score==null?50:d.score;
      var vcol = sc>=70?'var(--green2)':(sc>=50?'#3a9b3a':(sc>=30?'#d99e00':'var(--red2)'));
      var dot = d.risk_level=='GREEN'?'🟢':(d.risk_level=='AMBER'?'🟡':'🔴');
      var h='<div class="panel" style="border-left:4px solid '+vcol+';background:var(--bg2)">'
        +'<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">'
        +'<div><h3>🧭 综合研判</h3><div class="panel-sub" style="margin-bottom:0">生成于 '+esc(d.generated)+'</div></div>'
        +'<div style="text-align:right"><div style="font-size:30px;font-weight:800;color:'+vcol+'">'+num(sc,0)+'</div>'
        +'<div style="font-size:12px;color:var(--t3)">机会分 0-100</div></div></div>'
        +'<div style="margin-top:6px;font-weight:700;color:var(--t1);font-size:15px">'+esc(d.verdict)+'</div>'
        +'<div style="margin-top:4px;font-size:12px;color:var(--t2);line-height:1.5">'+esc(d.action)+'</div>'
        +'<div style="margin-top:4px;font-size:11px;color:var(--t3)">'+dot+' 风险等级 '+esc(d.risk_level)+' ｜ '+esc(d.sentence)+'</div></div>';
      var c=d.components||{};
      h+='<div class="panel"><h3 style="margin-bottom:6px">各维度贡献</h3><div style="font-size:12px;color:var(--t2);line-height:1.9">';
      [['sentiment','情绪'],['national_team','国家队'],['regime','市场状态'],['watch_pool','实盘验证'],['auto_A','选股信号']].forEach(function(pair){
        var k=pair[0],label=pair[1],v=c[k]; if(!v) return;
        var val = k=='auto_A' ? (v.count+'只A信号') : (v.zone||v.attitude||v.vs_backtest||'');
        var cont = v['贡献']==null?0:v['贡献'];
        var ccol = cont>0?'var(--green2)':(cont<0?'var(--red2)':'var(--t3)');
        h+='· '+label+'：'+esc(val)+' <b style="color:'+ccol+'">'+(cont>=0?'+':'')+cont+'</b><br>';
      });
      h+='</div></div>';
      h+='<div class="panel" style="font-size:11px;color:var(--t4);line-height:1.5">'+esc(d.caveat||'')+'</div>';
      var el=document.getElementById('synthesisMount'); if(el) el.innerHTML=h;
    }).catch(function(e){
      fallback('synthesisMount','📴 未能实时拉取 overview.json（'+esc(e.message)+'），以下为本地烘焙快照。');
    });
  }
  function watchItem(it){
    var col=colorOf((it.return||0));
    var stcol = it.status=='持有中'?'var(--t3)':(it.expectation=='符合预期'?'var(--green2)':'var(--red2)');
    return '<tr style="font-size:12px;border-top:1px solid var(--line)">'
      +'<td style="padding:5px 4px;color:var(--t1)">'+esc(it.name)+'<br><span style="color:var(--t4);font-size:10px">'+esc(it.code)+'</span></td>'
      +'<td style="padding:5px 4px">'+num(it.entry_price)+'</td>'
      +'<td style="padding:5px 4px">'+num(it.last_price)+'</td>'
      +'<td style="padding:5px 4px;color:'+col+'">'+chg((it.return||0)*100)+'</td>'
      +'<td style="padding:5px 4px;color:'+stcol+'">'+esc(it.status)+'<br><span style="font-size:10px">'+esc(it.expectation)+'</span></td></tr>';
  }
  function loadWatch(){
    loadJSON('watch_pool.json').then(function(d){
      var s=d.stats||{}, base=d.baseline||{};
      var wr=s.win_rate, vs=s.vs_backtest||'样本不足';
      var wrcol = wr==null?'var(--t3)':(vs=='高于回测'?'var(--green2)':(vs=='低于回测'?'var(--red2)':'var(--t3)'));
      var h='<div class="panel"><div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">'
        +'<div><h3>📈 观察池 · 实盘验证</h3><div class="panel-sub" style="margin-bottom:0">生成于 '+esc(d.updated)+'</div></div>'
        +'<div style="text-align:right"><div style="font-size:20px;font-weight:800;color:'+wrcol+'">'+(wr==null?'—':(wr*100).toFixed(1)+'%')+'</div>'
        +'<div style="font-size:11px;color:var(--t3)">真实命中率 vs 回测'+(base.win?(' '+(base.win*100).toFixed(1)+'%'):'')+'</div></div></div>';
      h+='<div class="panel" style="font-size:12px;color:var(--t2);line-height:1.6">'
        + '总追踪 <b>'+(s.total||0)+'</b> 只 ｜ 已平仓 <b>'+(s.closed||0)+'</b> ｜ 持仓 <b>'+(s.open||0)+'</b>'
        + ' ｜ 止盈 <b style="color:var(--green2)">'+(s.tp||0)+'</b> ｜ 止损 <b style="color:var(--red2)">'+(s.stop||0)+'</b> ｜ 到期 <b>'+(s.expired||0)+'</b>'
        + ' ｜ 均值 <b>'+((s.avg_return==null)?'—':chg(s.avg_return*100))+'</b> ｜ <b style="color:'+wrcol+'">'+esc(vs)+'</b></div>';
      h+='<div class="panel"><h3 style="margin-bottom:6px">追踪明细</h3><div style="max-height:48vh;overflow-y:auto"><table style="width:100%;border-collapse:collapse;font-size:12px">';
      h+='<tr style="color:var(--t4);text-align:left"><th style="padding:4px">标的</th><th style="padding:4px">入场价</th><th style="padding:4px">现价</th><th style="padding:4px">收益</th><th style="padding:4px">状态</th></tr>';
      (d.items||[]).slice().reverse().forEach(function(it){ h+=watchItem(it); });
      h+='</table></div></div>';
      h+='<div class="panel" style="font-size:11px;color:var(--t4);line-height:1.5">自我纠正：观察池自动追踪「自动选股」输出的买入标的，自输出以来的真实走向即本表。命中率低于回测基线时策略体检将亮红灯。不构成投资建议。</div>';
      var el=document.getElementById('watchMount'); if(el) el.innerHTML=h;
    }).catch(function(e){
      fallback('watchMount','📴 未能实时拉取 watch_pool.json（'+esc(e.message)+'），以下为本地烘焙快照。');
    });
  }
  function dimPill(label, st){
    if(st=='pass') return '<span class="badge b-green">'+esc(label)+' ✓达标</span>';
    if(st=='fail') return '<span class="badge b-red">'+esc(label)+' ✗未达标</span>';
    if(st=='watch') return '<span class="badge b-amber">'+esc(label)+' ⏳观望</span>';
    return '<span class="badge" style="background:var(--bg3);color:var(--t3)">'+esc(label)+' —待确认</span>';
  }
  function sz50Row(name, cur, pctAll, sub){
    var p = (pctAll==null)?50:pctAll;
    var col = p<25?'var(--green2)':(p<50?'#7cb342':(p<75?'#d99e00':'var(--red2)'));
    var unit = name.indexOf('PE')>=0?'倍':'';
    return '<div style="margin:8px 0">'
      + '<div style="display:flex;justify-content:space-between;font-size:12px">'
      + '<span style="color:var(--t1);font-weight:600">'+esc(name)+'</span>'
      + '<span style="color:var(--t1)">'+num(cur)+unit+' <span style="color:var(--t3);font-size:11px">'+esc(sub||'')+'</span></span></div>'
      + '<div style="height:10px;background:linear-gradient(90deg,var(--green2),#d99e00,var(--red2));border-radius:5px;position:relative;margin-top:4px">'
      + '<div style="position:absolute;top:-3px;left:calc('+p+'% - 3px);width:6px;height:16px;background:#fff;border:2px solid var(--t1);border-radius:3px"></div></div>'
      + '</div>';
  }
  function ldCard(b){
    var low = b.low;
    var pct = b.pe_pct_hist!=null? b.pe_pct_hist : (b.pe_pct_1y!=null? b.pe_pct_1y : (b.cheap_score!=null?b.cheap_score:null));
    var pctTxt = pct==null?'—':(Math.round(pct)+'%');
    var pctLabel = b.pe_pct_hist!=null?'历史分位':(b.pe_pct_1y!=null?'近1年分位':'横截面');
    return '<div style="padding:8px 10px;margin-bottom:6px;background:var(--bg2);border-radius:8px;border-left:3px solid '+(low?'var(--green2)':'var(--line)')+'">'
      + '<div style="display:flex;justify-content:space-between;align-items:baseline">'
      + '<div style="font-weight:600;color:var(--t1)">'+esc(b.name)+' <span style="color:var(--t3);font-weight:400;font-size:11px">'+esc(b.code)+'</span>'+(low?' <span class="badge b-green">🟢低值</span>':'')+'</div>'
      + '<div style="font-size:12px;color:var(--t2)">PE '+num(b.pe)+' · PB '+num(b.pb)+'</div></div>'
      + '<div style="margin-top:3px;font-size:11px;color:var(--t3)">'+pctLabel+' <b style="color:'+(low?'var(--green2)':'var(--t2)')+'">'+pctTxt+'</b>'+(b.src=='fallback'?' · 降级数据':'')+'</div>'
      + '</div>';
  }
  function loadLiDaxiao(){
    loadJSON('li_daxiao.json').then(function(d){
      var s=d.sz50||{}, v=d.verdict||{}, blues=d.bluechips||[], dims=d.dims||{};
      var tier = s.tier||'未知';
      var tierColor = tier=='极致底部'?'var(--green2)':(tier=='温和底部'?'#d99e00':'var(--t3)');
      var srcMap={'realtime':['实时 · akshare','var(--green2)'],'cache_hit':['缓存(6h内)','var(--green2)'],'cache_fallback':['缓存降级 · 数据源不可达','#d99e00'],'empty':['无数据','var(--red2)']};
      var sm=srcMap[(d.source||'realtime')]||srcMap['realtime'];
      var h='';
      h+='<div class="panel" style="border-left:4px solid '+tierColor+';background:var(--bg2)">'
        +'<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">'
        +'<div><h3>📉 李大霄底部研判 · 综合结论</h3><div class="panel-sub" style="margin-bottom:0">上证50估值温度计 · 数据截至 '+esc(s.asof||'-')+' · 生成于 '+esc(d.generated||'-')+' <span style="color:'+sm[1]+';border:1px solid '+sm[1]+';border-radius:6px;padding:1px 6px">来源：'+sm[0]+'</span></div></div>'
        +'<div style="text-align:right"><div style="font-size:22px;font-weight:800;color:'+tierColor+'">'+esc(tier)+'</div>'
        +'<div style="font-size:12px;color:var(--t3)">上证50 静态PE '+num(s.pe)+'</div></div></div>';
      h+='<div style="margin-top:6px;font-size:13px;color:var(--t1);font-weight:600">'+esc(v.level||'')+'</div>';
      h+='<div style="margin-top:4px;font-size:12px;color:var(--t2);line-height:1.5">'+esc(v.action||'')+'</div>';
      h+='<div style="margin-top:4px;font-size:11px;color:var(--t3)">蓝筹低值 '+ (v.blue_low_count||0) +'/'+ (v.blue_total||0) +' 只处历史/近期低位</div></div>';
      h+='<div class="panel"><h3 style="margin-bottom:6px">📊 上证50 估值温度计（对比历年 PE/PB）</h3>';
      h+= sz50Row('静态PE', s.pe, s.pe_pct_all, '全历史'+num(s.pe_pct_all)+'% / 近5年'+num(s.pe_pct_5y)+'%');
      h+= sz50Row('市净率PB', s.pb, s.pb_pct_all, '全历史'+num(s.pb_pct_all)+'% / 近5年'+num(s.pb_pct_5y)+'%');
      h+='<div style="font-size:11px;color:var(--t4);margin-top:6px">分位越低=越便宜。参考区间：PE '+num(s.pe_min)+'~'+num(s.pe_max)+'（中位'+num(s.pe_med)+'）；李大霄三档：≤8.5极致 / 8.5~10温和 / &gt;10接近底部。</div></div>';
      h+='<div class="panel"><h3 style="margin-bottom:6px">💎 蓝筹低值发现（'+blues.length+'只，按便宜度排序）</h3>';
      h+='<div style="font-size:11px;color:var(--t3);margin-bottom:6px">标注🟢低值的蓝筹处历史/近期估值低位，可重点纳入观察池。'+(blues.length&&blues[0].src=='fallback'?'（个股历史接口限流，暂以1年分位+横截面替代）':'')+'</div>';
      h+= blues.map(ldCard).join('');
      h+='</div>';
      h+='<div class="panel"><h3 style="margin-bottom:6px">五维研判（量化修订版）</h3><div style="font-size:12px;color:var(--t2);line-height:1.9">';
      for(var k in dims){ var dm=dims[k]; h+= dimPill(k, dm.status)+' <span style="color:var(--t3)">'+esc(dm.text)+'</span><br>'; }
      h+='</div></div>';
      var bt=d.backtest||{};
      if(bt && bt.available){
        var bcol=bt.verified?'var(--green2)':'#d99e00';
        h+='<div class="panel"><h3 style="margin-bottom:6px">🔬 估值温度历史回测验证</h3><div style="font-size:12px;color:var(--t2);line-height:1.7">'
          +'样本 '+num(bt.sample_n)+' 个交易日；其中 PE分位&lt;'+num(bt.cheap_pct_threshold)+'% 的「便宜区」'+num(bt.cheap_n)+' 个观测。<br>'
          +'之后60日中位收益：便宜区 <b>'+num(bt.cheap_med60)+'%</b> vs 全样本 <b>'+num(bt.all_med60)+'%</b>；'
          +'之后120日：便宜区 <b>'+num(bt.cheap_med120)+'%</b> vs 全样本 <b>'+num(bt.all_med120)+'%</b>。<br>'
          +'<span style="color:'+bcol+';font-weight:600">结论：'+esc(bt.verdict)+'</span></div></div>';
      } else if(bt && bt.note){
        h+='<div class="panel"><h3 style="margin-bottom:6px">🔬 估值温度历史回测验证</h3><div style="font-size:12px;color:var(--t3)">'+esc(bt.note)+'</div></div>';
      }
      var el=document.getElementById('ldMount'); if(el) el.innerHTML=h;
    }).catch(function(e){
      fallback('ldMount','📴 未能实时拉取 li_daxiao.json（'+esc(e.message)+'），以下为本地烘焙快照。要看每日最新，请访问 <a href="https://seonkoo.github.io/wolf-screener/" style="color:var(--blue)">seonkoo.github.io/wolf-screener</a>。');
    });
  }
  // ===== 艾略特波浪理论（ZigZag + 斐波那契）=====
  function ewKline(tsCode, period){
    period = period||'day';
    var varName='ew'+tsCode+'_'+Date.now()+'_'+Math.floor(Math.random()*1000000);
    var url='https://ifzq.gtimg.cn/appstock/app/kline/kline?_var='+varName+'&param='+tsCode+','+period+',,,320';
    return new Promise(function(resolve){
      var s=document.createElement('script'); var done=false;
      s.onload=function(){ if(done)return; done=true;
        try{ var raw=window[varName]; if(!raw){resolve([]);return;}
          var data=raw.data||raw; var kl=(data[tsCode]&&(data[tsCode].day||data[tsCode].qfqday))||data.day||data.qfqday||[];
          var parsed=kl.map(function(k){return {date:k[0],open:+k[1],close:+k[2],high:+k[3],low:+k[4],volume:+k[5]||0};});
          resolve(parsed);
        }catch(e){ resolve([]); }
        try{delete window[varName];}catch(e){} s.remove();
      };
      s.onerror=function(){ if(!done){done=true;resolve([]);s.remove();} };
      s.src=url;
      setTimeout(function(){ if(!done){done=true;resolve([]);s.remove();} }, 12000);
      document.body.appendChild(s);
    });
  }
  function ewATR(bars, n){
    n=n||14; var tr=[];
    for(var i=1;i<bars.length;i++){
      var h=bars[i].high,l=bars[i].low,pc=bars[i-1].close;
      tr.push(Math.max(h-l, Math.abs(h-pc), Math.abs(l-pc)));
    }
    if(tr.length<n) return null;
    var s=0; for(var j=tr.length-n;j<tr.length;j++) s+=tr[j];
    return s/n;
  }
  function ewThreshold(bars){
    var atr=ewATR(bars); var price=bars[bars.length-1].close;
    var p = atr ? (2.2*atr/price) : 0.05;
    return Math.max(0.03, Math.min(0.09, p));
  }
  function ewZigzag(bars, pct){
    var n=bars.length; if(n<5) return [];
    var pivots=[], mode='H', ep=bars[0].high, ei=0;
    for(var i=1;i<n;i++){
      if(mode==='H'){
        if(bars[i].high>ep){ ep=bars[i].high; ei=i; }
        else if(bars[i].low < ep*(1-pct)){ pivots.push({index:ei,price:ep,type:'H',date:bars[ei].date}); mode='L'; ep=bars[i].low; ei=i; }
      } else {
        if(bars[i].low<ep){ ep=bars[i].low; ei=i; }
        else if(bars[i].high > ep*(1+pct)){ pivots.push({index:ei,price:ep,type:'L',date:bars[ei].date}); mode='H'; ep=bars[i].high; ei=i; }
      }
    }
    pivots.push({index:ei,price:ep,type:mode,date:bars[ei].date});
    return pivots;
  }
  function ewLabelWaves(pp, up){
    var seq=['1','2','3','4','5','A','B','C'];
    var arr=pp.slice(); if(arr.length>9) arr=arr.slice(arr.length-9);
    var want=up?'L':'H';
    if(arr[0].type!==want && arr.length>1) arr=arr.slice(1);
    if(arr.length>9) arr=arr.slice(arr.length-9);
    return arr.map(function(p,idx){ return {pivot:p, label: idx===0?'起':seq[Math.min(idx-1,seq.length-1)]}; });
  }
  function ewLen(lab,a,b){ return Math.abs(lab[a].pivot.price - lab[b].pivot.price); }
  function ewFib(lab){
    var f={};
    try{
      if(lab.length>=6){ f.w1=ewLen(lab,0,1); f.w2=ewLen(lab,1,2); f.w3=ewLen(lab,2,3); f.w4=ewLen(lab,3,4); f.w5=ewLen(lab,4,5);
        f.w3w1 = f.w1? f.w3/f.w1 : null; f.w2ret = f.w1? f.w2/f.w1 : null; f.w4ret = f.w3? f.w4/f.w3 : null; }
      if(lab.length>=9){ f.a=ewLen(lab,5,6); f.b=ewLen(lab,6,7); f.c=ewLen(lab,7,8);
        f.bret = f.a? f.b/f.a : null;
        f.ctarget = (lab[6].pivot.type==='H')? lab[6].pivot.price - f.a*1.618 : lab[6].pivot.price + f.a*1.618; }
    }catch(e){}
    return f;
  }
  function ewCurrent(lab){
    var last=lab[lab.length-1]; var lbl=last.label, typ=last.pivot.type; var s='';
    if(typ==='H'){
      if(lbl==='5') s='价格自第5浪高点回落，处A浪调整初期（或第5浪延长末端）';
      else if(lbl==='3') s='价格自第3浪高点回撤，处第4浪调整中';
      else if(lbl==='B') s='B浪反抽见顶，转C浪下行';
      else if(lbl==='起'||lbl==='1') s='第1浪高点，关注第2浪回调';
      else s='自近期高点回落，处调整浪（A/B）';
    } else {
      if(lbl==='C') s='C浪末端，关注新一轮第1浪启动（潜在底部区）';
      else if(lbl==='2') s='第2浪回调企稳，处第3浪主升启动';
      else if(lbl==='4') s='第4浪回调企稳，处第5浪末升段';
      else if(lbl==='A') s='A浪下探中，等待B浪反抽';
      else if(lbl==='起'||lbl==='1') s='自低点回升，处第1/第3推动浪';
      else s='自近期低点回升，处推动浪';
    }
    return s;
  }
  function ewSubwave(bars, lab){
    try{
      var last=lab[lab.length-1], pre=lab[lab.length-2];
      var start=Math.max(0, pre.pivot.index);
      var seg=bars.slice(start);
      if(seg.length<20) return '样本不足，细浪暂不判';
      var sub=ewZigzag(seg, ewThreshold(seg)*0.6);
      if(sub.length>=5) return '该浪内部呈5段细分（推动结构延续），约处第(4)/(5)子浪推进';
      if(sub.length>=3) return '该浪内部呈3段细分（调整结构），处子浪b/c';
      return '细浪结构尚不清晰';
    }catch(e){ return '细浪分析暂不可用'; }
  }
  function ewAdvice(cur, fib, lab, market, sector){
    var c=cur||''; var stop=null, target=null, act='', tone='neutral', style='观望';
    try{
      var last=lab[lab.length-1];
      for(var i=lab.length-2;i>=0;i--){ if(lab[i].pivot.type!==last.pivot.type && Math.abs(lab[i].pivot.index-last.pivot.index)>3){ stop=lab[i].pivot.price; break; } }
    }catch(e){}
    // 操作风格：长线持有 / 波段做T / 逢高减仓 / 观望（明确结论）
    if(/5/.test(c)||/A浪调整/.test(c)){ act='第5浪末端/调整初：分批止盈、不追高；放量滞涨警惕失败浪'; tone='b-amber'; style='逢高减仓'; }
    else if(/4浪/.test(c)||/4/.test(c)){ act='第4浪回调是低吸区，轻仓、止损第4浪低点下破'; tone='b-green'; style='波段做T'; }
    else if(/3/.test(c)||/主升/.test(c)){ act='主升段：顺势持有，回踩加仓；止损第4浪低点下方'; tone='b-green'; style='长线持有'; }
    else if(/2浪/.test(c)||/2/.test(c)){ act='第2浪回调企稳可试多，止损第1浪起点下方'; tone='b-green'; style='波段做T'; }
    else if(/C浪末端/.test(c)||/C/.test(c)){ act='C浪末端临近布局区，不接飞刀，等放量企稳再介入'; tone='b-amber'; style='观望'; }
    else if(/B浪/.test(c)){ act='B浪反抽减仓，防C浪下杀'; tone='b-amber'; style='逢高减仓'; }
    else { act='结构不清晰，观望等待确认'; tone='neutral'; style='观望'; }
    // 大盘方向调制：方向比个股浪型更优先
    if(market && market.trend==='down'){
      if(style==='长线持有'||style==='波段做T'){ style='降仓观望'; act='⚠️ 大盘处下行趋势（沪深300跌破年线 '+market.dev_pct+'%），即便个股处上升浪也应降仓/等企稳，不接飞刀。'+act; tone='b-amber'; }
      else if(style==='逢高减仓'){ act='⚠️ 大盘下行，'+act; }
    } else if(market && market.trend==='up'){
      if(style==='长线持有'||style==='波段做T'){ act='大盘上行配合，'+act; }
    }
    // 板块资金维度调制（"根据板块资金推荐买卖"）：板块顺风/逆风优先于个股浪型
    if(sector && sector.state){
      if(sector.state==='持续流出'){
        style='降仓观望'; tone='b-amber'; act='⚠️ 所属板块「'+sector.name+'」资金持续流出，逆势接盘风险高，即便个股浪型偏多也应降仓/等企稳。'+act;
      } else if(sector.state==='持续流入'){
        if(style==='长线持有'||style==='波段做T') act='✅ 所属板块「'+sector.name+'」资金持续流入（顺风），可放手按计划做。'+act;
      } else if(sector.state==='短线回流'){
        if(style==='长线持有'){ style='波段做T'; act='板块「'+sector.name+'」仅短线回流，不宜长拿，改为波段做T。'+act; }
        else if(style==='波段做T') act='板块「'+sector.name+'」短线回流中，可顺势做T。'+act;
      } else if(sector.state==='短期回调'){
        if(style==='长线持有'||style==='波段做T'){ style='等企稳'; act='板块「'+sector.name+'」处短期回调，先观望等企稳再介入。'+act; }
      }
    }
    if(fib&&fib.ctarget) target=fib.ctarget;
    return {act:act, stop:stop, target:target, tone:tone, style:style, sector:sector};
  }
  function ewMarketTrend(){
    // 拉沪深300 日K 算 年线/120日线 趋势，供波浪结论叠加大盘方向
    return new Promise(function(resolve){
      var url='https://ifzq.gtimg.cn/appstock/app/kline/kline?_var=mkt&param=sh000300,day,,,400';
      var s=document.createElement('script'); var done=false;
      s.onload=function(){ if(done)return; done=true;
        try{ var raw=window.mkt; var kd=(raw.data.sh000300&&(raw.data.sh000300.day||raw.data.sh000300.qfqday))||[];
          var closes=kd.map(function(k){return +k[2];});
          var n=closes.length;
          if(n>=250){ var ma250=closes.slice(n-250).reduce(function(a,b){return a+b;},0)/250;
            var ma120=closes.slice(n-120).reduce(function(a,b){return a+b;},0)/120; var c=closes[n-1];
            var trend = (c>=ma250&&c>=ma120)?'up':(c<ma250*0.95?'down':'neutral');
            resolve({trend:trend, dev_pct:Math.round((c/ma250-1)*1000)/10, close:Math.round(c*100)/100});
          } else resolve({trend:'na'});
        }catch(e){ resolve({trend:'na'}); }
        try{delete window.mkt;}catch(e){} s.remove();
      };
      s.onerror=function(){ if(!done){done=true;resolve({trend:'na'});s.remove();} };
      s.src=url; setTimeout(function(){ if(!done){done=true;resolve({trend:'na'});s.remove();} },10000);
      document.body.appendChild(s);
    });
  }
  function analyzeElliott(klines, label, market, sector){
    label=label||'标的';
    if(!klines||klines.length<60) return {error:'数据不足（需至少约60根日K线才能识别波浪结构）'};
    var pct=ewThreshold(klines);
    var pivots=ewZigzag(klines,pct);
    if(pivots.length<6) return {error:'波动平缓，暂无可识别的清晰拐点'};
    var pp=pivots.slice(-11);
    var up = pp[pp.length-1].price >= pp[0].price;
    var lab=ewLabelWaves(pp,up);
    var cur=ewCurrent(lab);
    var fib=ewFib(lab);
    var sub=ewSubwave(klines,lab);
    var adv=ewAdvice(cur,fib,lab,market,sector);
    var conf='低（结构不典型，仅供参考）';
    if(fib.w3w1!=null && fib.w2ret!=null && fib.bret!=null){
      if(fib.w3w1>=0.9 && fib.w2ret>0.3 && fib.w2ret<0.85 && fib.bret>0.3 && fib.bret<0.85) conf='中-高（浪型比例较贴合经典）';
      else conf='中（部分比例贴合）';
    }
    return {label:label, pct:pct, lab:lab, up:up, current:cur, fib:fib, sub:sub, advice:adv, conf:conf, market:market, sector:sector};
  }
  function drawElliott(res, market){
    var m=document.getElementById('ewMount'); var a=document.getElementById('ewAdvise');
    if(!m) return;
    if(res.error){ m.innerHTML='<div class="panel" style="border-left:4px solid var(--t3)"><div style="color:var(--t2)">⚠️ '+esc(res.error)+'</div></div>'; if(a)a.innerHTML=''; return; }
    var lab=res.lab; var html='';
    html+='<div class="panel" style="border-left:4px solid '+(res.up?'var(--red2)':'var(--green2)')+';background:var(--bg2)">';
    html+='<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">';
    html+='<div><h3>🌊 '+esc(res.label)+' · 波浪研判</h3><div class="panel-sub" style="margin-bottom:0">趋势：'+(res.up?'↑ 推动(偏多)':'↓ 调整(偏空)')+' · 拐点阈值 '+(res.pct*100).toFixed(1)+'% · 识别拐点 '+lab.length+' 个</div></div>';
    html+='<div style="text-align:right"><div style="font-size:13px;color:var(--t3)">置信度</div><div style="font-weight:700;color:'+(res.conf.indexOf('中-高')>=0?'var(--green2)':(res.conf.indexOf('中')>=0?'#d99e00':'var(--t3)'))+'">'+esc(res.conf)+'</div></div></div>';
    html+='<div style="margin-top:8px;display:flex;flex-wrap:wrap;gap:4px">';
    lab.forEach(function(x){
      var isCur=(x===lab[lab.length-1]);
      var col = (x.label==='5'||x.label==='3') ? 'var(--red2)' : ((x.label==='C'||x.label==='A')?'var(--green2)':'var(--t2)');
      html+='<span style="font-size:12px;padding:3px 7px;border-radius:6px;border:1px solid '+(isCur?'var(--blue)':'var(--line)')+';'+(isCur?'background:var(--blue);color:#fff':'color:'+col)+'">'+esc(x.label)+' '+(x.pivot.type==='H'?'▲':'▼')+num(x.pivot.price)+'</span>';
    });
    html+='</div>';
    html+='<div style="margin-top:8px;font-size:14px;font-weight:700;color:'+(res.up?'var(--red2)':'var(--green2)')+'">当前位置：'+esc(res.current)+'</div>';
    html+='<div style="font-size:12px;color:var(--t2);margin-top:3px">细浪：'+esc(res.sub)+'</div>';
    var f=res.fib;
    html+='<div class="panel" style="margin-top:8px"><h3 style="margin-bottom:6px">📐 斐波那契比例验证</h3><div style="font-size:12px;color:var(--t2);line-height:1.8">';
    if(f.w3w1!=null) html+='浪3/浪1 = '+num(f.w3w1,2)+'（理想 ≥1，常1.618）<br>';
    if(f.w2ret!=null) html+='浪2回撤浪1 = '+num(f.w2ret,2)+'（理想 0.5-0.618）<br>';
    if(f.w4ret!=null) html+='浪4回撤浪3 = '+num(f.w4ret,2)+'（理想 ≈0.382）<br>';
    if(f.bret!=null) html+='B浪回撤A = '+num(f.bret,2)+'（理想 0.5-0.618）<br>';
    html+='</div><div style="font-size:11px;color:var(--t4);margin-top:4px">比例越贴合经典区间，浪型判定越可信。</div></div>';
    html+='</div>';
    m.innerHTML=html;
    if(a){
      var adv=res.advice; var mk=res.market||market;
      var styleColor = (adv.style==='长线持有')?'var(--red2)':(adv.style==='波段做T')?'#1e88e5':(adv.style==='逢高减仓'||adv.style==='降仓观望')?'#d99e00':'var(--t3)';
      var box='<div class="suggest '+(adv.tone==='b-green'?'suggest-g':(adv.tone==='b-amber'?'suggest-b':'suggest'))+'" style="margin-top:8px">';
      box+='<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:6px">';
      box+='<div style="font-size:13px;color:var(--t1);font-weight:700">💡 操作结论</div>';
      box+='<span style="font-size:12px;font-weight:700;padding:2px 10px;border-radius:20px;border:1px solid '+styleColor+';color:'+styleColor+'">'+esc(adv.style)+'</span>';
      box+='</div>';
      box+='<div style="font-size:13px;color:var(--t1);margin-top:6px">'+esc(adv.act)+'</div>';
      if(mk&&mk.trend&&mk.trend!=='na'){
        var mt = mk.trend==='up'?'🟢 大盘上行':(mk.trend==='down'?'🔴 大盘下行':'🟡 大盘震荡');
        box+='<div style="font-size:12px;color:var(--t2);margin-top:6px">📊 大盘方向（沪深300）：'+mt+(mk.dev_pct!=null?'（年线偏离 '+mk.dev_pct+'%）':'')+' → 已纳入买卖策略</div>';
      }
      if(adv.sector&&adv.sector.state){
        var scol = adv.sector.state==='持续流入'?'var(--green2)':(adv.sector.state==='持续流出'?'var(--red2)':(adv.sector.state==='短线回流'?'#1e88e5':'var(--t3)'));
        box+='<div style="font-size:12px;color:var(--t2);margin-top:4px">🧭 板块资金「'+esc(adv.sector.name)+'」：<b style="color:'+scol+'">'+esc(adv.sector.state)+'</b>（5日净额 '+(adv.sector.net5!=null?num(adv.sector.net5,1):'-')+'亿）→ 已纳入买卖策略</div>';
      }
      if(adv.stop!=null) box+='<div style="font-size:12px;color:var(--t2);margin-top:4px">参考止损位：'+num(adv.stop)+'</div>';
      if(adv.target!=null) box+='<div style="font-size:12px;color:var(--t2);margin-top:4px">C浪目标参考：'+num(adv.target)+'</div>';
      box+='<div style="font-size:11px;color:var(--t4);margin-top:4px">波浪+大盘方向综合研判，具概率性，非投资建议。</div>';
      box+='</div>';
      a.innerHTML=box;
    }
  }
  // ---------------- 板块资金 · 买卖策略导向 ----------------
  // 把行业板块的资金净流向（持续流入/短线回流/短期回调/持续流出）转化为可执行的买卖导向；
  // 个股波浪分析时再用 fetchIndustry + lookupSector 把个股映射到所属板块，叠加板块顺风/逆风。
  function loadSectorFlow(){
    loadJSON('sector_flow.json').then(function(d){
      window.__SECTOR_FLOW__=d;
      renderSectorFlow(d);
    }).catch(function(e){
      var el=document.getElementById('sectorMount');
      if(el) el.innerHTML='<div class="panel" style="font-size:11px;color:var(--t3)">📴 未能实时拉取板块资金（'+esc(e.message)+'），以下为本地烘焙快照。</div>';
    });
  }
  function renderSectorFlow(d){
    if(!d) return;
    var secs=d.sectors||[];
    function byState(st){ return secs.filter(function(s){return s.state===st;}).sort(function(a,b){return (b.net5||0)-(a.net5||0);}); }
    var inflow=byState('持续流入').slice(0,8);
    var backflow=byState('短线回流').slice(0,6);
    var pullback=byState('短期回调').slice(0,6);
    var outflow=byState('持续流出').slice(0,8);
    var m=d.market||{};
    var h='<div class="panel" style="border-left:4px solid var(--blue);background:var(--bg2)">'
      +'<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">'
      +'<div><h3>🧭 板块资金 · 买卖策略导向</h3><div class="panel-sub" style="margin-bottom:0">生成于 '+esc(d.generated||'')+'</div></div>'
      +'<div style="font-size:12px;color:var(--t2)">↑流入板块 <b>'+(m.up_sectors||0)+'</b> · ↓流出 <b>'+(m.down_sectors||0)+'</b> · 广度 <b>'+(m.breadth||0)+'%</b></div></div>';
    h+='<div style="margin-top:6px;font-size:12px;color:var(--t2)">📌 策略：优先「持续流入」板块做多/持有；「短线回流」做波段；「短期回调」等企稳；「持续流出」回避。市场整体：'+(m.verdict||'')+'</div>';
    h+=sectorGroup('🟢 持续流入（可买/持有）', inflow, 'var(--green2)');
    h+=sectorGroup('🔵 短线回流（波段做T）', backflow, '#1e88e5');
    h+=sectorGroup('⚪ 短期回调（等企稳）', pullback, 'var(--t3)');
    h+=sectorGroup('🔴 持续流出（回避）', outflow, 'var(--red2)');
    h+='</div>';
    var el=document.getElementById('sectorMount'); if(el) el.innerHTML=h;
  }
  function sectorGroup(title, arr, col){
    if(!arr.length) return '';
    return '<div style="margin-top:8px"><div style="font-size:12px;font-weight:700;color:'+col+'">'+title+'（'+arr.length+'）</div>'
      +'<div style="display:flex;flex-wrap:wrap;gap:5px;margin-top:4px">'
      + arr.map(function(s){ return '<span style="font-size:11px;padding:2px 8px;border-radius:14px;border:1px solid '+col+';color:'+col+'">'+esc(s.name)+' <span style="opacity:.7">'+(s.net5!=null?num(s.net5,1):'-')+'亿</span></span>'; }).join('')
      +'</div></div>';
  }
  // 解析个股所属行业板块（东方财富 stock/get），再在已加载的 sector_flow 中定位其资金状态
  function fetchIndustry(code){
    return new Promise(function(resolve){
      var secid=(/^[69]/.test(code)?'1.':'0.')+code;
      var cb='__em_ind_'+code;
      function cleanup(){ try{delete window[cb];}catch(e){} if(s&&s.parentNode)s.parentNode.removeChild(s); }
      window[cb]=function(d){ cleanup(); resolve((d&&d.data&&(d.data.f127||d.data.f128||''))||''); };
      var s=document.createElement('script');
      s.onerror=function(){ cleanup(); resolve(''); };
      s.src='https://push2.eastmoney.com/api/qt/stock/get?secid='+secid+'&fields=f127,f128&cb='+cb+'&invt=2&fltt=2';
      document.body.appendChild(s);
      setTimeout(function(){ cleanup(); resolve(''); }, 8000);
    });
  }
  function lookupSector(ind){
    var sf=window.__SECTOR_FLOW__; if(!sf||!ind) return null;
    for(var i=0;i<sf.sectors.length;i++){ if(sf.sectors[i].name===ind) return sf.sectors[i]; }
    // 模糊匹配：行业名可能是板块名的子串（如 "白酒" vs "白酒Ⅱ"）
    for(var i=0;i<sf.sectors.length;i++){ if(ind.indexOf(sf.sectors[i].name)>=0||sf.sectors[i].name.indexOf(ind)>=0) return sf.sectors[i]; }
    return null;
  }
  function loadElliott(){
    function run(tsCode, name){
      var mount=document.getElementById('ewMount'); if(mount) mount.innerHTML='<div style="font-size:12px;color:var(--t3);padding:8px">🌊 正在拉取 '+esc(name)+' 日K线并计算波浪…</div>';
      Promise.all([ewKline(tsCode,'day'), ewMarketTrend()]).then(function(arr){
        var kl=arr[0], market=arr[1];
        if(!kl||kl.length<60){ drawElliott({error:'日K线获取不足（'+(kl?kl.length:0)+'根），请稍后重试'}, market); return; }
        drawElliott(analyzeElliott(kl, name, market, null), market);
      }).catch(function(e){ drawElliott({error:'波浪计算失败：'+esc(e&&e.message||e)}); });
    }
    var sel=document.getElementById('ewIndex'); var btn=document.getElementById('ewIndexBtn');
    var cinput=document.getElementById('ewCode'); var cbtn=document.getElementById('ewCodeBtn'); var cmsg=document.getElementById('ewCodeMsg');
    if(cbtn&&cinput){
        cbtn.onclick=function(){
        var code=(cinput.value||'').trim();
        if(!/^[0-9]{6}$/.test(code)){ if(cmsg)cmsg.textContent='请输入6位代码'; return; }
        if(cmsg)cmsg.textContent='计算中…';
        Promise.all([ewKline(getTencentCode(code),'day'), ewMarketTrend()]).then(function(arr){
          var kl=arr[0], market=arr[1];
          if(cmsg)cmsg.textContent='';
          if(!kl||kl.length<60){ drawElliott({error:esc(code)+' 日K线不足，无法分析'}, market); return; }
          var nm=code; try{ if(window.__EW_NAMES__&&window.__EW_NAMES__[code]) nm=window.__EW_NAMES__[code]; }catch(e){}
          // 解析个股所属板块 → 板块资金状态，纳入买卖策略
          fetchIndustry(code).then(function(ind){
            var sec=lookupSector(ind);
            drawElliott(analyzeElliott(kl, nm+' ('+code+')', market, sec), market, ind);
          });
        }).catch(function(e){ if(cmsg)cmsg.textContent='分析失败'; drawElliott({error:esc(code)+' 分析失败'}); });
      };
      cinput.onkeydown=function(e){ if(e&&e.key==='Enter') cbtn.onclick(); };
    }
  }
  // ===== 交易时机（主入口）：大市环境 + 按确定性排序的买卖决策 =====
  function loadTradeTime(){
    var autoP = loadJSON('auto_screen_result.json');
    var ldP = loadJSON('li_daxiao.json').catch(function(){ return null; });
    var sentP = loadJSON('sentiment.json').catch(function(){ return null; });
    Promise.all([autoP, ldP, sentP]).then(function(arr){
      renderTT(arr[0], arr[1], arr[2]);
    }).catch(function(e){
      fallback('ttMount', '📴 未能实时拉取 auto_screen_result.json（'+esc(e.message)+'），以下为本地烘焙快照。要看每日最新，请访问 <a href="https://seonkoo.github.io/wolf-screener/" style="color:var(--blue)">seonkoo.github.io/wolf-screener</a>。');
    });
  }
  function renderTT(d, ld, sent){
    var m=(d&&d.market)||{};
    var tier=((ld&&ld.sz50)||{}).tier||'-';
    var pe=((ld&&ld.sz50)||{}).pe;
    var sidx=(sent&&sent.index!=null)?sent.index:null;
    var szone=(sent&&sent.zone)||'';
    var mtrend=m.trend||'na';
    var mtrendTxt = mtrend==='up'?'🟢 大盘上行':(mtrend==='down'?'🔴 大盘下行(恐慌区)':'🟡 大盘震荡');
    var bEl=document.getElementById('ttBanner');
    if(bEl) bEl.innerHTML='<div class="panel" style="border-left:4px solid var(--blue);background:var(--bg2)">'
      +'<div style="font-weight:700;color:var(--t1)">⏱️ 交易时机 · 大市环境</div>'
      +'<div style="font-size:12px;color:var(--t2);margin-top:4px;line-height:1.6">李大霄温度 <b>'+esc(tier)+'</b>'+(pe!=null?'（PE '+num(pe)+'）':'')+' ｜ 情绪 <b>'+(sidx!=null?num(sidx,0):'-')+'</b> '+esc(szone)
      +' ｜ '+mtrendTxt+(m.dev_pct!=null?'（年线偏离 '+m.dev_pct+'%）':'')+'</div>'
      +'<div style="font-size:11px;color:var(--t3);margin-top:4px">大市环境为开仓「总开关」：温度底部+情绪冰点→可分批低吸；贪婪过热/狂热→控仓。个股 / ETF 买点见下方分区。</div></div>';
    var picks=[];
    ((d.A||[]).concat(d.B||[])).forEach(function(r){ if(r.trade_plan) picks.push(r); });
    picks.sort(function(a,b){ return (b.trade_plan.conviction||0)-(a.trade_plan.conviction||0); });
    var actionable=picks.filter(function(r){ return r.trade_plan.open!=='no'; });
    var h='';
    if(!actionable.length){
      h='<div class="panel" style="font-size:12px;color:var(--t3)">当前无可操作个股（大市环境或个股信号均未触发开仓）。可切「🤖 自动选股」看全部候选。</div>';
    } else {
      h+='<div class="panel" style="font-size:11px;color:var(--t3)">按确定性排序的可操作个股（开仓+观望共 '+actionable.length+' 只）。点击卡片展开四层明细与波浪买点。非投资建议。</div>';
      actionable.forEach(function(r){ h+=ttCard(r); });
    }
    var el=document.getElementById('ttMount'); if(el) el.innerHTML=h;
  }
  function ttCard(r, tag){
    var tp=r.trade_plan||{};
    var oc = tp.open==='open'?'var(--green2)':(tp.open==='watch'?'#d99e00':'var(--red2)');
    var olab = tp.open==='open'?'✅ 可开仓':(tp.open==='watch'?'⏳ 等/小仓':'⛔ 禁止');
    var col=colorOf(r.change||0);
    var conv=tp.conviction||0;
    var ccol = conv>=70?'var(--green2)':(conv>=45?'#1e88e5':(conv>=20?'#d99e00':'var(--t3)'));
    var cid='ttdet_'+r.code, wid='ttwave_'+r.code;
    var sp=(tp.stop_pct||0)*100, tp2=(tp.target_pct||0)*100;
    return '<div style="padding:10px;margin-bottom:8px;background:var(--bg2);border-radius:10px;border-left:3px solid '+oc+'">'
      +'<div style="display:flex;justify-content:space-between;align-items:baseline;cursor:pointer" onclick="ttToggle(\''+r.code+'\')">'
      +'<div style="font-weight:700;color:var(--t1)">'+esc(r.name)+' <span style="color:var(--t3);font-weight:400;font-size:12px">'+esc(r.code)+'</span></div>'
      +'<div style="text-align:right"><div style="color:var(--t1);font-weight:700">'+num(r.price)+'</div><div style="font-size:12px;color:'+col+'">'+chg(r.change)+'</div></div></div>'
      +'<div style="margin-top:6px;font-size:12px;display:flex;gap:8px;flex-wrap:wrap;align-items:center">'
      +'<span class="badge" style="border:1px solid '+oc+';color:'+oc+'">'+olab+'</span>'
      +'<span style="color:var(--t2)">📍 '+esc(tp.buy_trigger||'')+'</span>'
      +'<span style="font-size:11px;color:'+ccol+'">确定性 '+conv+'</span>'
      +(tag?'<span class="badge" style="border:1px solid var(--t3);color:var(--t3)">'+tag+'</span>':'')
      +'</div>'
      +'<div style="margin-top:5px;font-size:12px;color:var(--t2)">持股 <b>'+ (tp.hold_days||'-') +'</b> 日 · 止损 <b style="color:var(--red2)">'+num(tp.stop_price,3)+'</b> ('+sp.toFixed(0)+'%) · 止盈 <b style="color:var(--green2)">'+num(tp.target_price,3)+'</b> (+'+tp2.toFixed(0)+'%)</div>'
      +'<div style="margin-top:5px;font-size:12px;color:var(--t2);line-height:1.5;background:var(--bg3);padding:6px;border-radius:8px">📝 买入理由：'+esc(tp.rationale||'')+'</div>'
      +'<div id="'+cid+'" data-name="'+esc(r.name)+'" style="display:none;margin-top:6px">'
      +'<div style="font-size:11px;color:var(--t3)">'+esc(tp.open_reason||'')+(tp.macro_note?' ｜ '+esc(tp.macro_note):'')+'</div>'
      +'<div style="margin-top:4px;font-size:11px;color:var(--t3);display:flex;gap:5px;flex-wrap:wrap">'
      + pill('①情绪',(r.l1||{}).status) + pill('②浪型',(r.l2||{}).status) + pill('③技术',(r.l3||{}).status) + pill('④资金',(r.l4||{}).status)
      + (r.wolf2&&r.wolf2.pass?'<span class="badge b-green">★小狼2.0</span>':'') + '</div>'
      +'<div style="margin-top:4px;font-size:12px;color:var(--t2);line-height:1.5">'+esc(r.suggestion||'')+'</div>'
      +'<div id="'+wid+'" style="margin-top:4px"></div></div>'
      +'</div>';
  }
  function etfCard(r){ return ttCard(r, 'ETF'); }
  function loadETFTime(){
    fetch('etf_result.json').then(function(r){ return r.json(); }).then(function(d){ renderETF(d); }).catch(function(e){
      var el=document.getElementById('etfMount');
      if(el && el.innerHTML.indexOf('正在加载')>=0) el.innerHTML='<div class="panel" style="font-size:12px;color:var(--t3)">ETF 时机数据加载失败（离线快照见上方）。</div>';
    });
  }
  function renderETF(d){
    var el=document.getElementById('etfMount'); if(!el) return;
    if(!d){ el.innerHTML='<div class="panel" style="font-size:12px;color:var(--t3)">暂无 ETF 数据。</div>'; return; }
    var picks=[];
    ((d.A||[]).concat(d.B||[])).forEach(function(r){ if(r.trade_plan) picks.push(r); });
    picks.sort(function(a,b){ return (b.trade_plan.conviction||0)-(a.trade_plan.conviction||0); });
    var actionable=picks.filter(function(r){ return r.trade_plan.open!=='no'; });
    var h='';
    if(!actionable.length){
      h='<div class="panel" style="font-size:12px;color:var(--t3)">当前无操作信号 ETF。可观察 B 类（观望/小仓）标的，等信号共振。非投资建议。</div>';
    } else {
      h+='<div class="panel" style="font-size:11px;color:var(--t3)">按确定性排序的可操作 ETF（开仓+观望共 '+actionable.length+' 只）。非投资建议。</div>';
      actionable.forEach(function(r){ h+=etfCard(r); });
    }
    el.innerHTML=h;
  }
  function ttToggle(code){
    var el=document.getElementById('ttdet_'+code); if(!el) return;
    var hidden = el.style.display==='none';
    el.style.display = hidden?'block':'none';
    if(hidden){
      var wave=document.getElementById('ttwave_'+code);
      if(wave && !wave.dataset.loaded){ wave.dataset.loaded='1'; renderWaveMini(code, el.getAttribute('data-name')||code, wave); }
    }
  }
  function renderWaveMini(code, name, el){
    el.innerHTML='<div style="font-size:11px;color:var(--t3)">🌊 正在计算波浪买点…</div>';
    Promise.all([ewKline(getTencentCode(code),'day'), ewMarketTrend()]).then(function(arr){
      var kl=arr[0], market=arr[1];
      if(!kl||kl.length<60){ el.innerHTML='<div style="font-size:11px;color:var(--t3)">🌊 日K线不足，无法分析波浪</div>'; return; }
      var res=analyzeElliott(kl, name+' ('+code+')', market, null);
      if(res.error){ el.innerHTML='<div style="font-size:11px;color:var(--t3)">🌊 '+esc(res.error)+'</div>'; return; }
      var adv=res.advice;
      var col=(adv.style==='长线持有')?'var(--red2)':(adv.style==='波段做T')?'#1e88e5':(adv.style==='逢高减仓'||adv.style==='降仓观望')?'#d99e00':'var(--t3)';
      el.innerHTML='<div style="padding:6px;background:var(--bg3);border-radius:8px">'
        +'<div style="font-weight:600;color:'+col+'">🌊 波浪买点：'+esc(adv.style)+'</div>'
        +'<div style="font-size:11px;color:var(--t2);margin-top:3px">当前：'+esc(res.current)+'</div>'
        +'<div style="font-size:11px;color:var(--t2);margin-top:2px">'+esc(adv.act)+'</div>'
        +(adv.stop!=null?'<div style="font-size:11px;color:var(--t2)">参考止损 '+num(adv.stop)+'</div>':'')
        +(adv.target!=null?'<div style="font-size:11px;color:var(--t2)">C浪目标 '+num(adv.target)+'</div>':'')
        +'</div>';
    }).catch(function(e){ el.innerHTML='<div style="font-size:11px;color:var(--t3)">🌊 波浪计算失败</div>'; });
  }
  function boot(){ loadLiDaxiao(); loadSectorFlow(); loadSynthesis(); loadAuto(); loadGuard(); loadTeam(); loadSent(); loadWatch(); loadElliott(); loadTradeTime(); loadETFTime(); applyHash(); }
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

    # 1) tab 按钮
    # 1a) 市场研判按钮（综合研判+全球市场+重大事件+国家队资金+情绪指数 合并）
    if 'data-tab="market"' not in s:
        first = s.find('data-tab="')
        if first >= 0:
            end = s.find('</button>', first)
            end = (end + len('</button>')) if end >= 0 else (s.find('>', first) + 1)
            s = s[:end] + '\n' + MARKET_TAB_BTN + s[end:]
            print('  + tab按钮: market')
        else:
            print('  ! 未找到首个 tab 按钮')
    # 1b) 其余按钮（在 auto tab 按钮之后，按 bluechip/watch 顺序插入）
    tabs_to_add = []
    for key, btn in [('watch', WATCH_TAB_BTN)]:
        if ('data-tab="%s"' % key) not in s:
            tabs_to_add.append(btn)
    if tabs_to_add:
        idx = s.find('data-tab="auto"')
        if idx >= 0:
            end = s.find('</button>', idx)
            end = (end + len('</button>')) if end >= 0 else (s.find('>', idx) + 1)
            s = s[:end] + '\n' + '\n'.join(tabs_to_add) + s[end:]
            print('  + tab按钮:', ' '.join(t.split('data-tab="')[1].split('"')[0] for t in tabs_to_add))
        else:
            print('  ! 未找到 auto tab 按钮')

    # 1c) 交易时机（默认第一个主入口）：插到「最前面」，成为首个 tab 按钮
    if 'data-tab="tradetime"' not in s:
        first = s.find('data-tab="')
        if first >= 0:
            s = s[:first] + TRADETIME_TAB_BTN + '\n' + s[first:]
            print('  + tab按钮: tradetime (置顶)')
        else:
            print('  ! 未找到首个 tab 按钮')

    # 2) 自动选股 pane -> fetch 结构（保留已烘焙快照）
    m = re.search(r'<!--AUTOPICK_START-->(.*?)<!--AUTOPICK_END-->', s, re.S)
    baked_auto = m.group(1) if m else None
    s, ok = replace_section(s, 'pane-auto', AUTO_PANE)
    print(('  ~ 自动选股pane已刷新' if ok else '  ! 未找到 pane-auto'))
    if ok and baked_auto and '正在加载' not in baked_auto:
        s = s.replace('<!--AUTOPICK_START-->' + LOADING_AUTO + '<!--AUTOPICK_END-->',
                      '<!--AUTOPICK_START-->' + baked_auto + '<!--AUTOPICK_END-->', 1)
        print('    · 保留原离线快照')

    # 2b) 交易时机 pane（默认主入口）
    # 先归一化默认激活态的 class（避免 replace_section 因 "pane active" 匹配不到）
    s = s.replace('<section class="pane active" id="pane-tradetime">', '<section class="pane" id="pane-tradetime">')
    m = re.search(r'<!--TRADETIME_START-->(.*?)<!--TRADETIME_END-->', s, re.S)
    baked_tt = m.group(1) if m else None
    m2 = re.search(r'<!--TTBANNER_START-->(.*?)<!--TTBANNER_END-->', s, re.S)
    baked_tb = m2.group(1) if m2 else None
    m3 = re.search(r'<!--ETFTIME_START-->(.*?)<!--ETFTIME_END-->', s, re.S)
    baked_et = m3.group(1) if m3 else None
    s, ok = replace_section(s, 'pane-tradetime', TRADETIME_PANE)
    if not ok:
        ins = s.find('</section>', s.find('<section class="pane" id="pane-watch">'))
        if ins >= 0:
            ins += len('</section>')
            s = s[:ins] + '\n' + TRADETIME_PANE + s[ins:]
            print('  + 交易时机pane（新建）')
        else:
            print('  ! 无法定位交易时机pane插入点')
    else:
        print('  ~ 交易时机pane已刷新')
    if baked_tt and '正在加载' not in baked_tt:
        s = s.replace('<!--TRADETIME_START-->' + LOADING_TRADETIME + '<!--TRADETIME_END-->',
                      '<!--TRADETIME_START-->' + baked_tt + '<!--TRADETIME_END-->', 1)
        print('    · 保留原离线快照(交易时机)')
    if baked_tb and '正在加载' not in baked_tb:
        s = s.replace('<!--TTBANNER_START-->' + LOADING_TRADETIME + '<!--TTBANNER_END-->',
                      '<!--TTBANNER_START-->' + baked_tb + '<!--TTBANNER_END-->', 1)
        print('    · 保留原离线快照(大市环境横幅)')
    if baked_et and '正在加载' not in baked_et:
        s = s.replace('<!--ETFTIME_START-->' + LOADING_TRADETIME + '<!--ETFTIME_END-->',
                      '<!--ETFTIME_START-->' + baked_et + '<!--ETFTIME_END-->', 1)
        print('    · 保留原离线快照(ETF时机)')
    # 设为默认主入口：清除其他 active，激活 tradetime
    s = re.sub(r'class="tab active"', 'class="tab"', s)
    s = re.sub(r'class="pane active"', 'class="pane"', s)
    s = s.replace('<button class="tab" data-tab="tradetime">', '<button class="tab active" data-tab="tradetime">', 1)
    s = s.replace('<section class="pane" id="pane-tradetime">', '<section class="pane active" id="pane-tradetime">', 1)

    # 3) 清理可能残留的「蓝筹低吸」独立 pane/tab（已废弃：回测显示跌破年线低吸无超额）
    s = re.sub(r'<section class="pane" id="pane-bluechip">.*?</section>\s*', '', s, flags=re.S)
    s = re.sub(r'\s*<button class="tab" data-tab="bluechip">.*?</button>', '', s)

    # 3b) 市场研判 pane（综合研判+全球市场+重大事件+国家队资金+情绪指数 合并）
    m = re.search(r'<!--SYNTHESIS_START-->(.*?)<!--SYNTHESIS_END-->', s, re.S)
    baked_ov = m.group(1) if m else None
    m2 = re.search(r'<!--TEAM_START-->(.*?)<!--TEAM_END-->', s, re.S)
    baked_team = m2.group(1) if m2 else None
    m3 = re.search(r'<!--SENT_START-->(.*?)<!--SENT_END-->', s, re.S)
    baked_sent = m3.group(1) if m3 else None
    m4 = re.search(r'<!--LIDAXIAO_START-->(.*?)<!--LIDAXIAO_END-->', s, re.S)
    baked_ld = m4.group(1) if m4 else None
    s, ok = replace_section(s, 'pane-market', MARKET_PANE)
    if not ok:
        ins = s.find('</section>', s.find('<section class="pane" id="pane-auto">'))
        if ins >= 0:
            ins += len('</section>')
            s = s[:ins] + '\n' + MARKET_PANE + s[ins:]
            print('  + 市场研判pane（新建）')
        else:
            print('  ! 无法定位市场研判pane插入点')
    else:
        print('  ~ 市场研判pane已刷新')
    if baked_ov and '正在加载' not in baked_ov:
        s = s.replace('<!--SYNTHESIS_START-->' + LOADING_OVERVIEW + '<!--SYNTHESIS_END-->',
                      '<!--SYNTHESIS_START-->' + baked_ov + '<!--SYNTHESIS_END-->', 1)
        print('    · 保留原离线快照(综合研判)')
    if baked_team and '正在加载' not in baked_team:
        s = s.replace('<!--TEAM_START-->' + LOADING_TEAM + '<!--TEAM_END-->',
                      '<!--TEAM_START-->' + baked_team + '<!--TEAM_END-->', 1)
        print('    · 保留原离线快照(国家队)')
    if baked_sent and '正在加载' not in baked_sent:
        s = s.replace('<!--SENT_START-->' + LOADING_SENT + '<!--SENT_END-->',
                      '<!--SENT_START-->' + baked_sent + '<!--SENT_END-->', 1)
        print('    · 保留原离线快照(情绪)')
    if baked_ld and '正在加载' not in baked_ld:
        s = s.replace('<!--LIDAXIAO_START-->' + LOADING_LIDAXIAO + '<!--LIDAXIAO_END-->',
                      '<!--LIDAXIAO_START-->' + baked_ld + '<!--LIDAXIAO_END-->', 1)
        print('    · 保留原离线快照(李大霄)')

    # 3e) 观察池 pane
    m = re.search(r'<!--WATCH_START-->(.*?)<!--WATCH_END-->', s, re.S)
    baked_w = m.group(1) if m else None
    s, ok = replace_section(s, 'pane-watch', WATCH_PANE)
    if not ok:
        ins = s.find('</section>', s.find('<section class="pane" id="pane-sent">'))
        if ins >= 0:
            ins += len('</section>')
            s = s[:ins] + '\n' + WATCH_PANE + s[ins:]
            print('  + 观察池pane（新建）')
        else:
            print('  ! 无法定位观察池pane插入点')
    else:
        print('  ~ 观察池pane已刷新')
    if baked_w and '正在加载' not in baked_w:
        s = s.replace('<!--WATCH_START-->' + LOADING_WATCH + '<!--WATCH_END-->',
                      '<!--WATCH_START-->' + baked_w + '<!--WATCH_END-->', 1)
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
