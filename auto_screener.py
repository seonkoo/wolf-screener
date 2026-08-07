# -*- coding: utf-8 -*-
"""
小狼交易策略 · A股全自动扫描器
精确复刻 wolf-screener3.0.html 的 runScreening 四层判定逻辑：
  1️⃣ 情绪海选  -> 自建750日价格分位贪婪指数(calcGreedFromKline)
  2️⃣ 浪型过滤  -> 日线MACD金叉/绿柱缩短
  3️⃣ 技术共振  -> 15分钟MACD(金叉/底背离/绿柱缩短) + 日线布林(下轨/中轨)
  4️⃣ 资金校验  -> 近5日主力净流入(真实+K线估算)
Template: A建议低吸 / B观察 / C禁止 / D观望

数据：东方财富(push2delay 列表&资金流) + 腾讯(ifzq.gtimg.cn K线)
用法：python auto_screener.py  [topN=100]  [minInflow=0]
"""
import urllib.request, json, ssl, urllib.parse, math, random, sys, time, concurrent.futures, threading, os

CTX = ssl.create_default_context(); CTX.check_hostname=False; CTX.verify_mode=ssl.CERT_NONE
HDR = {'User-Agent':'Mozilla/5.0','Referer':'https://quote.eastmoney.com/'}

# ---- 回测验证后的最优参数(见 opt_backtest.py) ----
GREED_PASS = 40      # 低位/恐慌阈值：回测显示 <40 与 <35 胜率相近(64.7% vs 65.5%)但信号更多；原策略用35
HOLD_DAYS  = 20      # 最优持有期(2026-08-07 多持有期网格回测)：10/20/30/40 日中 20 日峰值
                     #   胜率 52.9→61.5→54.0→53.4%，均值 1.47→4.11→3.51→3.48%（n=174）
                     #   10日太短(均值回归没走完)、30-40日回吐；止盈15%/止损8%仍先触发先执行
STOP_PCT   = 0.08    # 止损 8%
TP_PCT     = 0.15    # 止盈 15%

# ---- 小狼 2.0 强化层（策略实验室 8 年回测定稿，见 wolf2_validation.json）----
# 恐慌急跌(RSI<35 或 20日跌幅>12%) + 小市值(总市值后50%) + 剔除放量(>2倍)/高波动(>4%) → 胜率 74.2%（基准70.9%）
WOLF2_GREED_MAX = 25   # L1 恐慌：价格分位 < 25（比 1.0 的 40 更严格，只抓真正恐慌低位）
WOLF2_TECH_MIN  = 2     # L3 技术共振 >= 2
WOLF2_RET20_MAX = -0.12 # 20日跌幅 > 12% 视为急跌
WOLF2_RSI_MAX   = 35    # 或 RSI14 < 35 超卖（二者满足其一即"恐慌"）
WOLF2_VOLRATIO_MAX = 2.0  # 剔除当日放量 > 2 倍（超额 -1.04%）
WOLF2_VOLA_MAX      = 0.04 # 剔除20日波动 > 4%（超额 -1.26%）
WOLF2_HOLD = 90    # 持有约 90 日（均值回归需要时间；10日过短）
WOLF2_TP   = 0.10   # 止盈 10%（不贪，急跌修复即走）
WOLF2_STOP = 0.20   # 止损 20%：回测证明止损是胜率杀手，越宽越好(5%→45%，不设→77%)

# ---- 右侧(趋势跟随/突破) 分支：买强不买弱，解决"全是买跌"的不踏实感 ----
# 与左侧低吸(均值回归)并列；右侧单顺势买入，止损更紧、错了快速走，比抄底接飞刀更可控
RIGHT_STOP = 0.06   # 顺势单止损 6%（比左侧 8% 更紧：趋势单错了立刻走）
RIGHT_TP   = 0.15   # 顺势单止盈 15%
RIGHT_HOLD = 30     # 顺势单基础持有 30 日；主升浪(3浪)拉长到 60，末升浪(5)缩到 15

# ---- E 档：热点早期突破（右侧·小仓试错）----
# 解决"资金主线轮动初期，板块已持续净流入、个股放量长阳，却被 L1 贪婪过热一刀切禁买"的病根。
# 触发：板块是资金主线(sector_hot) + 个股主力净流入>1亿 + 当日放量上涨(量比>1.5)。
# 豁免 L1 贪婪过热(板块共振盖过个股过热)；但用小仓(conv 低于 M)、严格止损 8%、持有期更短来兜"追涨 Alpha 有限"的回测结论。
E_STOP = 0.08      # 严格止损 8%（不放松：早期突破假突破概率高，错了快走）
E_TP   = 0.15      # 止盈 15%
E_HOLD = 15        # 早期突破试错持有期更短（板块轮动快，不长期恋战）
E_INFLOW_MIN = 1e8 # 个股主力净流入下限 1 亿（确认资金真在涌向该标的，而非随板块微涨；用户定稿 1 亿门槛）


def get(u):
    req = urllib.request.Request(u, headers=HDR)
    return urllib.request.urlopen(req, timeout=20).read().decode('utf-8','ignore')

# ---------- 指标计算（与网页 JS 一一对应） ----------
def calc_ema(data, period):
    k = 2/(period+1); ema=[data[0]]
    for i in range(1,len(data)): ema.append(data[i]*k + ema[-1]*(1-k))
    return ema

def calc_macd(closes):
    if len(closes) < 30: return None
    e12=calc_ema(closes,12); e26=calc_ema(closes,26)
    dif=[e12[i]-e26[i] for i in range(len(closes))]
    dea=calc_ema(dif,9)
    macd=[(dif[i]-dea[i])*2 for i in range(len(closes))]
    return {'dif':dif,'dea':dea,'macd':macd}

def check_macd_cross(dif,dea):
    if len(dif)<2: return 'none'
    n=len(dif)
    if dif[n-2]<=dea[n-2] and dif[n-1]>dea[n-1]: return 'golden'
    if dif[n-2]>=dea[n-2] and dif[n-1]<dea[n-1]: return 'dead'
    if dif[n-1]>dea[n-1]: return 'above'
    return 'below'

def check_macd_green_shorten(macd):
    if len(macd)<3: return False
    n=len(macd)
    if macd[n-1]<0 and macd[n-2]<0 and macd[n-3]<0:
        return abs(macd[n-1])<abs(macd[n-2]) and abs(macd[n-2])<abs(macd[n-3])
    return False

def check_macd_divergence(closes,dif):
    if len(closes)<20 or len(dif)<20: return False
    n=len(closes); low1=-1; low2=-1; look=min(n,60)
    for i in range(n-look,n):
        if 0<i<n-1 and closes[i]<closes[i-1] and closes[i]<closes[i+1]:
            if low2==-1: low2=i
            elif low1==-1 and i<low2-3: low1=i
    if low1>=0 and low2>=0:
        if closes[low2]<closes[low1] and dif[low2]>dif[low1]: return True
    return False

def calc_bollinger(closes, period=20, mult=2):
    if len(closes)<period: return None
    n=len(closes); sma=[];up=[];lo=[]
    for i in range(period-1,n):
        sl=closes[i-period+1:i+1]; mean=sum(sl)/period
        std=(sum((b-mean)**2 for b in sl)/period)**0.5
        sma.append(mean);up.append(mean+mult*std);lo.append(mean-mult*std)
    li=len(sma)-1; price=closes[n-1]
    pos='下轨支撑' if price<=lo[li] else '中轨附近' if price<=sma[li] else '上轨突破' if price>=up[li] else '中上轨间'
    return {'mid':sma[li],'upper':up[li],'lower':lo[li],'price':price,'position':pos}

def calc_greed(closes):
    if len(closes)<30: return 50.0
    cur=closes[-1]; look=min(len(closes)-1,750); hist=closes[-look-1:-1]
    if not hist: return 50.0
    below=sum(1 for c in hist if c<cur)
    return round(below/len(hist)*1000)/10

def calc_rsi(closes, period=14):
    """RSI-14 (Wilder 平滑)。用于小狼2.0 的'恐慌/超卖'判定。"""
    if len(closes) < period+1: return 50.0
    deltas=[closes[i]-closes[i-1] for i in range(1,len(closes))]
    gains=[max(d,0) for d in deltas]; losses=[max(-d,0) for d in deltas]
    ag=sum(gains[:period])/period; al=sum(losses[:period])/period
    for i in range(period,len(deltas)):
        ag=(ag*(period-1)+gains[i])/period
        al=(al*(period-1)+losses[i])/period
    if al==0: return 100.0
    rs=ag/al
    return round(100-100/(1+rs),1)

# ---------- 小狼 2.0 强化层 ----------
def wolf2_layer(kd, greed, tech, small):
    """复刻 strategy_lab.wolf2_mask 的独立判定（不依赖四层法的 L3 tech）。
    关键：tech2 用实验室定义 = bl+am+vs+div，其中 div 为 MACD 底背离；
    由于 WOLF2 剔除放量(excl_vol_surge)，tech2>=2 等价于「MACD 底背离存在」。
    回测：通过此层样本胜率 74.2%（同日随机买基准 70.9%）。"""
    res={'pass':False,'greed':round(greed,1),'tech2':0,'tech_l3':int(tech),'small':bool(small),
         'ret20':None,'rsi':None,'volratio':None,'vola':None,
         'panic':False,'vol_surge':False,'high_vola':False,'reasons':[]}
    if not kd or len(kd)<60:
        res['reasons'].append('K线不足'); return res
    import statistics
    closes=[k['close'] for k in kd]; vols=[k['volume'] for k in kd]; n=len(closes)
    g = greed  # calc_greed 已是 750 日分位，与实验室一致
    # 20日跌幅
    ret20 = closes[-1]/closes[-21]-1 if n>=21 else 0.0
    res['ret20']=round(ret20,4)
    rsi = calc_rsi(closes,14); res['rsi']=rsi
    # 量比（当日量 / 20日均量）
    v20 = sum(vols[-20:])/20 if n>=20 else 0
    vr = (vols[-1]/v20) if v20>0 else 1.0; res['volratio']=round(vr,2)
    # 20日波动率（日收益率标准差）
    vola=0.0
    if n>=21:
        rets=[closes[i]/closes[i-1]-1 for i in range(max(1,n-20),n)]
        vola=statistics.pstdev(rets) if len(rets)>1 else 0.0
        res['vola']=round(vola,4)
    # tech2 = bl + am + vs + div（实验室同款）
    ma20 = sum(closes[-20:])/20 if n>=20 else closes[-1]
    bl = 1 if closes[-1] <= ma20 else 0
    am = 1 if closes[-1] >= ma20 else 0
    vs = 1 if (v20>0 and vols[-1] > 1.5*v20) else 0
    div = 0
    md = calc_macd(closes)
    if md and n>=20:
        div = 1 if check_macd_divergence(closes, md['dif']) else 0
    tech2 = bl + am + vs + div
    res['tech2']=tech2
    # 判定（与 wolf2_mask 一致）
    panic = (ret20 < WOLF2_RET20_MAX) or (rsi < WOLF2_RSI_MAX)
    res['panic']=bool(panic)
    res['vol_surge']=bool(vr > WOLF2_VOLRATIO_MAX)
    res['high_vola']=bool(vola > WOLF2_VOLA_MAX)
    ok = (g < WOLF2_GREED_MAX) and (tech2 >= WOLF2_TECH_MIN) and panic \
         and bool(small) and (not res['vol_surge']) and (not res['high_vola'])
    res['pass']=bool(ok)
    if ok:
        bits=[]
        if ret20 < WOLF2_RET20_MAX: bits.append('20日跌%.1f%%'%(ret20*100))
        if rsi < WOLF2_RSI_MAX: bits.append('RSI%s超卖'%rsi)
        if small: bits.append('小市值')
        if div: bits.append('MACD底背离')
        if not res['vol_surge']: bits.append('非放量')
        if not res['high_vola']: bits.append('低波动')
        res['reasons'].append(' + '.join(bits))
    return res

# ---------- 数据获取 ----------
def get_secid(code):
    return ('1.' if code[0] in '69' else '0.')+code

def fetch_kline(code, period='day'):
    tcode=('sh' if code[0] in '69' else 'sz')+code
    varn='k'+code+'_'+str(random.randint(0,999999))
    if period=='min15':
        url='https://ifzq.gtimg.cn/appstock/app/kline/mkline?_var=%s&param=%s,min15,,,320'%(varn,tcode)
    else:
        url='https://ifzq.gtimg.cn/appstock/app/kline/kline?_var=%s&param=%s,day,,,320'%(varn,tcode)
    for _ in range(3):
        try:
            raw=get(url); raw=raw[raw.index('=')+1:]
            d=json.loads(raw); data=d.get('data',{}); kd=data.get(tcode,{})
            kl=kd.get('m15') if period=='min15' else (kd.get('day') or kd.get('qfqday'))
            if not kl: return []
            return [{'date':k[0],'open':float(k[1]),'close':float(k[2]),'high':float(k[3]),'low':float(k[4]),
                     'volume':float(k[5]) if len(k)>5 else 0} for k in kl]
        except Exception:
            time.sleep(0.15)
    return []

def fetch_fund_flow(secid):
    fields='&fields1=f1,f2,f3,f7&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65'
    url='https://push2delay.eastmoney.com/api/qt/stock/fflow/daykline/get?secid=%s&lmt=5%s'%(secid,fields)
    for _ in range(2):
        try:
            d=json.loads(get(url))
            if d.get('data') and d['data'].get('klines'):
                return [{'date':k.split(',')[0],'main':float(k.split(',')[1])} for k in d['data']['klines']]
        except Exception:
            time.sleep(0.1)
    return []

# ---------- 大盘方向门控（沪深300 年线/120日线）----------
# 这是我们回测发现胜率的最大开关：大盘下行期低吸胜率仅~18%，上行期~40%。
# 故把"大盘下行禁止开仓"写进实盘，避免接飞刀。
_market_cache={}
def get_market_regime():
    """返回沪深300 趋势：up(收盘在年线/120线上方) / neutral(年线附近) / down(跌破年线)。"""
    if _market_cache: return _market_cache
    out={'trend':'na','close':None,'ma120':None,'ma250':None,'dev_pct':None}
    try:
        tcode='sh000300'
        url='https://ifzq.gtimg.cn/appstock/app/kline/kline?_var=k&param=%s,day,,,400'%tcode
        raw=get(url); raw=raw[raw.index('=')+1:]; kd=json.loads(raw)['data'][tcode]['day']
        closes=[float(k[2]) for k in kd]; n=len(closes)
        if n>=250:
            ma250=sum(closes[-250:])/250; ma120=sum(closes[-120:])/120; c=closes[-1]
            out.update({'close':round(c,2),'ma120':round(ma120,2),'ma250':round(ma250,2),'dev_pct':round((c/ma250-1)*100,1)})
            if c>=ma250 and c>=ma120: out['trend']='up'
            elif c < ma250*0.95: out['trend']='down'
            else: out['trend']='neutral'
    except Exception as e:
        out['err']=str(e)
    _market_cache.update(out)
    return _market_cache

def regime_gate(template, regime):
    """大盘方向门控（仅作提示，不硬删信号）。
    重要：回测显示本策略是"买恐慌"均值回归，下行/恐慌期胜率反而更高(46% vs 上行34%)，
    故下行期绝不禁止开仓，只提示控仓；真正该禁止的是贪婪过热(已在 L1 处理)。"""
    t=regime.get('trend','na')
    if template=='A':
        if t=='down':
            return 'A', '大盘处下行/恐慌区——本策略正是"买恐慌"策略，此处低吸信号反而更有效；但波动大，务必小仓、严格止损%d%%。'%(int(STOP_PCT*100))
        if t=='neutral':
            return 'A', '大盘震荡（年线附近），可小仓试探，严格止损%d%%。'%(int(STOP_PCT*100))
        if t=='up':
            return 'A', '大盘上行（沪深300在年线上方），可正常按计划低吸。'
    return template, ''

def right_side(day_closes, kd, md):
    """右侧(趋势跟随)判定：均线多头 + 近新高/突破 + 放量 + MACD 零轴上方。
    与左侧低吸(买跌)并列，让"顺势买入强势股"也能被系统识别，解决'全是买跌'的不踏实感。"""
    n = len(day_closes)
    if n < 60:
        return {'pass': False, 'score': 0, 'detail': 'K线不足(需≥60日)', 'why': []}
    c = day_closes[-1]
    ma20 = sum(day_closes[-20:]) / 20
    ma60 = sum(day_closes[-60:]) / 60
    uptrend = c > ma20 > ma60
    hi20 = max(day_closes[-20:])
    breakout = c >= hi20 * 0.97
    lastvol = kd[-1]['volume'] if kd else 0
    avgvol = sum(k['volume'] for k in kd[-20:]) / 20 if kd else 0
    vol_up = avgvol > 0 and lastvol > 1.5 * avgvol
    macd_up = False
    if md:
        dif, dea = md['dif'][-1], md['dea'][-1]
        macd_up = dif > dea > 0
    why, score = [], 0
    if uptrend: score += 1; why.append('均线多头(价>MA20>MA60)')
    if breakout: score += 1; why.append('近20日新高/突破')
    if vol_up: score += 1; why.append('放量×%.1f' % (lastvol / avgvol if avgvol else 0))
    if macd_up: score += 1; why.append('MACD零轴上方金叉')
    return {'pass': bool(uptrend and score >= 3), 'score': score,
            'detail': '右侧趋势: ' + (' / '.join(why) if why else '无信号'), 'why': why}


def wave_stage(day_closes):
    """艾略特波浪「阶段」研判（不求精确数浪，只给阶段操作建议）。
    主升浪(3)→长持 / 调整浪(2/4)→短线低吸高卖 / 末升浪(5)→分批止盈 / 下跌浪→回避 / 震荡→轻仓。"""
    n = len(day_closes)
    if n < 60:
        return {'key': 'na', 'label': '波浪数据不足', 'op': '暂无阶段建议', 'hold': HOLD_DAYS}
    c = day_closes[-1]
    ma20 = sum(day_closes[-20:]) / 20
    ma60 = sum(day_closes[-60:]) / 60
    ret20 = c / day_closes[-21] - 1 if n >= 21 else 0
    up = c > ma60 and ma20 > ma60
    down = c < ma60 and ma20 < ma60
    rsi = calc_rsi(day_closes, 14)
    hh = max(day_closes[-20:])
    pullback = c <= hh * 0.97
    if down:
        return {'key': 'down', 'label': '下跌浪(C/大A)', 'op': '回避，不抄底；等止跌信号', 'hold': HOLD_DAYS}
    if up:
        if ret20 > 0.15 and rsi and rsi > 70:
            return {'key': 'v', 'label': '末升浪(5)', 'op': '分批止盈，不追高', 'hold': 15}
        if pullback:
            return {'key': 'corr', 'label': '调整浪(2/4)', 'op': '短线低吸高卖，快进快出', 'hold': 20}
        return {'key': 'imp3', 'label': '主升浪(3)', 'op': '长持为主，回踩加仓', 'hold': 60}
    return {'key': 'side', 'label': '震荡蓄势', 'op': '轻仓高抛低吸', 'hold': HOLD_DAYS}


def load_quality_set():
    """best-effort 读 李大霄/蓝筹 优质集(blue_chip_result.json 的 picks)，标识体系内标的。"""
    import os as _os
    HERE = _os.path.dirname(_os.path.abspath(__file__))
    p = _os.path.join(HERE, 'blue_chip_result.json')
    try:
        if _os.path.exists(p):
            d = json.load(open(p, encoding='utf-8'))
            return set(str(x['code']) for x in d.get('picks', []) if x.get('code'))
    except Exception:
        pass
    return set()


def base_trade_plan(res):
    """把分散的底层信号收敛成「买卖时机」结构化决策：开仓信号 / 买入时机 / 持股时间 / 止盈止损。
    这是小狼系统对外输出的「主产品」；李大霄温度、波浪、板块资金、四层、小狼2.0 都是它的底层判断逻辑。"""
    l1 = res.get('l1', {}) or {}
    l2 = res.get('l2', {}) or {}
    l3 = res.get('l3', {}) or {}
    l4 = res.get('l4', {}) or {}
    l5 = res.get('l5', {}) or {}
    wave = res.get('wave', {}) or {}
    w2 = res.get('wolf2', {}) or {}
    template = res.get('template', '')
    market = res.get('market', {}) or {}
    side = 'right' if (l5.get('pass') or template == 'E') else 'left'
    # —— 开仓信号（大市环境是否适合开仓，个股层）——
    if w2.get('pass'):
        open_sig, open_reason = 'open', '小狼2.0恐慌底部（回测胜率74.2%），买恐慌策略生效'
    elif template == 'E':
        open_sig, open_reason = 'open', '热点早期突破（板块资金主线+个股放量长阳），小仓试错跟随，严格止损'
    elif l5.get('pass'):
        if l2.get('status') == 'fail':
            open_sig, open_reason = 'watch', '右侧趋势雏形但MACD仍死叉，等短期企稳再顺势跟进'
        else:
            open_sig, open_reason = 'open', '右侧趋势确认（均线多头+放量突破），顺势买入比抄底更稳'
    elif l1.get('status') == 'pass' and l3.get('status') == 'pass':
        open_sig, open_reason = 'open', '低位 + 技术共振，可分批低吸'
    elif l1.get('status') == 'pass':
        open_sig, open_reason = 'watch', '低位但技术未共振，等回调/放量确认'
    elif l1.get('status') == 'fail':
        open_sig, open_reason = 'no', '贪婪过热，禁止新开仓'
    elif l2.get('status') == 'fail':
        if market.get('trend') == 'down':
            open_sig, open_reason = 'watch', '主跌阶段但处恐慌区，仅小狼2.0恐慌信号可轻仓'
        else:
            open_sig, open_reason = 'no', '主跌阶段（MACD死叉绿柱未缩短），规避下跌风险'
    else:
        open_sig, open_reason = 'watch', '信号未共振，纳入观察池等待'
    # —— 买入时机 ——
    if w2.get('pass'):
        buy_trigger, buy_detail = '小狼2.0恐慌底部', ' / '.join(w2.get('reasons', [])) or '多因子共振'
    elif template == 'E':
        buy_trigger, buy_detail = '热点早期突破', '板块资金持续净流入主线 + 个股主力净流入>1亿 + 放量上涨(量比>1.5)'
    elif l5.get('pass'):
        buy_trigger, buy_detail = '右侧趋势突破', l5.get('detail', '')
    elif l1.get('status') == 'pass' and l3.get('status') == 'pass':
        buy_trigger, buy_detail = '低位技术共振', l3.get('detail', '')
    elif l3.get('status') == 'pass':
        buy_trigger, buy_detail = '技术反弹信号', l3.get('detail', '')
    elif l4.get('status') == 'pass':
        buy_trigger, buy_detail = '主力资金回流', l4.get('detail', '')
    else:
        buy_trigger, buy_detail = '等待信号共振', '四层信号尚未共振，暂不宜入场'
    # —— 持股时间 ——
    if w2.get('pass'):
        hold_days = WOLF2_HOLD
    elif template == 'E':
        hold_days = E_HOLD
    elif l5.get('pass'):
        hold_days = wave.get('hold') or RIGHT_HOLD
    else:
        hold_days = HOLD_DAYS
    # —— 止盈止损 ——
    if w2.get('pass'):
        stop_pct, target_pct = -WOLF2_STOP, WOLF2_TP
    elif template == 'E':
        stop_pct, target_pct = -E_STOP, E_TP
    elif l5.get('pass'):
        stop_pct, target_pct = -RIGHT_STOP, RIGHT_TP
    else:
        stop_pct, target_pct = -STOP_PCT, TP_PCT
    # —— 确定性评分（用于排序，0-100）——
    conv = {'A': 70, 'B': 45, 'C': 20, 'D': 10, 'M': 60, 'E': 40}.get(template, 10)  # E 小仓试错，确定性低于 M
    if w2.get('pass'):
        conv += 20
    if l5.get('pass'):
        conv += 25
    conv += min(int(l5.get('score', 0) or 0), 4) * 3
    conv += min(int(l3.get('tech', 0) or 0), 3) * 4
    g = l1.get('greed')
    if isinstance(g, (int, float)):
        if g < 25:
            conv += 10
        elif g < 40:
            conv += 5
    if l2.get('status') == 'pass':
        conv += 5
    if l4.get('status') == 'pass':
        conv += 3
    if market.get('trend') == 'down':
        conv += 5   # 买恐慌：下行期反而更该低吸
    if res.get('is_leader'):
        conv += 12  # 行业龙头：基本面确定性加成
    conv = max(0, min(100, conv))
    # —— 买入理由（数据驱动的"信服理由"，个股/ETF/基金通用）——
    asset = res.get('asset_type', '个股')
    sig = []
    if l1.get('detail'): sig.append('①' + l1['detail'])
    if l2.get('detail'): sig.append('②' + l2['detail'])
    if l3.get('detail'): sig.append('③' + l3['detail'])
    if w2.get('pass'): sig.append('④小狼2.0恐慌底部命中：' + (' / '.join(w2.get('reasons', [])) or '多因子共振'))
    if l4.get('detail'): sig.append('⑤' + l4['detail'])
    head = {'open': '✅ 建议开仓', 'watch': '👁 建议观望/小仓', 'no': '⛔ 暂不开仓'}.get(open_sig, '⚠ 信号不明')
    side_txt = '【右侧顺势·买强】' if side == 'right' else '【左侧低吸·买跌】'
    wave_txt = (' 波浪阶段：' + wave.get('label', '') + '——' + wave.get('op', '') + '。') if wave.get('label') else ''
    leader_txt = ''
    if res.get('is_leader') and res.get('industry_rank'):
        leader_txt = ' 龙头属性：所属行业总市值排名第%d/%d（行业龙头，基本面确定性更强）。' % (res['industry_rank'], res['industry_count'])
    rationale = (side_txt + head + '（' + open_reason + '）。'
                 + (' 技术面：' + '；'.join(sig) + '。' if sig else '')
                 + wave_txt + leader_txt
                 + ' 操作计划：持股约%d日，止损%.0f%%（≈%.2f），止盈%.0f%%（≈%.2f）。' % (
                     hold_days, abs(stop_pct) * 100, res.get('stop') or 0, target_pct * 100, res.get('target') or 0))
    return {
        'open': open_sig, 'open_reason': open_reason,
        'buy_trigger': buy_trigger, 'buy_detail': buy_detail,
        'side': side, 'wave': wave,
        'hold_days': hold_days,
        'stop_price': res.get('stop'), 'stop_pct': stop_pct,
        'target_price': res.get('target'), 'target_pct': target_pct,
        'conviction': conv,
        'rationale': rationale,
        'lidaxiao_pick': bool(res.get('lidaxiao_pick')),
    }

# ---------- 四层判定（复刻 runScreening） ----------
def run_screening(stock):
    code=stock['code']; name=stock['name']; price=stock.get('price',0); chg=stock.get('change',0)
    res={'code':code,'name':name,'price':price,'change':chg,'inflow':stock.get('inflow',0),
         'darkpool':stock.get('darkpool'),'sector':stock.get('sector',''),
         'sector_hot':stock.get('sector_hot',False),'sector_net':stock.get('sector_net',0),'sector_rank':None,
         'mcap':stock.get('mcap',0),'is_leader':bool(stock.get('is_leader',False)),
         'industry_rank':stock.get('industry_rank'),'industry_count':stock.get('industry_count'),
         'hot_leader':False,
         'template':'','suggestion':'',
         'asset_type':'个股',
         'stop':round(price*(1-STOP_PCT),3) if price else 0,'target':round(price*(1+TP_PCT),3) if price else 0,
         'l1':{},'l2':{},'l3':{},'l4':{},'flows':[],'market':get_market_regime(),'wolf2':{}}
    kd=fetch_kline(code,'day')
    if not kd or len(kd)<30:
        res['l1']={'status':'wait','greed':0.0,'detail':'K线数据不足，无法计算贪婪指数'}
        res['template']='D'; res['suggestion']='K线数据不足，无法判定'; res['l2']={'status':'wait','detail':'K线数据不足'}
        res['l3']={'status':'wait','detail':'K线数据不足'}; res['l4']={'status':'wait','detail':'资金流数据不足'}
        return res
    day_closes=[k['close'] for k in kd]
    # Layer 1
    greed=calc_greed(day_closes)
    if greed<GREED_PASS: l1=('pass',greed,'低位/恐慌区间，入观察池')
    elif greed>65: l1=('fail',greed,'贪婪过热，禁止开仓')
    else: l1=('neutral',greed,'中性区间，观望')
    res['l1']={'status':l1[0],'greed':greed,'detail':'自建贪婪指数 %.1f%% → %s'%(greed,l1[1])}
    # Layer 2
    md=calc_macd(day_closes)
    if md:
        cr=check_macd_cross(md['dif'],md['dea'])
        if cr in ('golden','above'): res['l2']={'status':'pass','detail':'日线MACD金叉/DIF在DEA上方，存在反弹窗口'}
        else:
            gs=check_macd_green_shorten(md['macd'])
            if gs: res['l2']={'status':'wait','detail':'日线MACD零轴下方绿柱缩短，酝酿反弹'}
            else: res['l2']={'status':'fail','detail':'日线MACD死叉且绿柱未缩短，持续下行风险高'}
    else: res['l2']={'status':'wait','detail':'K线不足，无法判断浪型'}
    # Layer 3 — 优先用15分钟(与网页一致)；沙箱取不到15分钟时改用日线代理共振
    km=fetch_kline(code,'min15'); tech=0; l3macd='无明确信号'; div=False; gs15=False; l3_proxy=False
    if km and len(km)>30:
        m15=[k['close'] for k in km]; m15m=calc_macd(m15)
        if m15m:
            c15=check_macd_cross(m15m['dif'],m15m['dea']); div=check_macd_divergence(m15,m15m['dif'])
            gs15=check_macd_green_shorten(m15m['macd'])
            if div: tech+=1
            if c15=='golden': tech+=1; l3macd='15min金叉'
            elif gs15: tech+=1; l3macd='绿柱缩短'
            elif c15=='above': l3macd='DIF在DEA上方'
        l3boll=''
        if len(kd)>20:
            b=calc_bollinger(day_closes)
            if b:
                l3boll=b['position']
                if b['position'] in ('下轨支撑','中轨附近'): tech+=1
        l3status='pass' if tech>=2 else ('wait' if tech>=1 else 'fail')
        l3detail='15min MACD: '+l3macd+(' | 底背离✓' if div else '')+(' | 绿柱缩短✓' if gs15 else '')+' | 布林: '+l3boll
    else:
        # 日线代理共振（15分钟数据在扫描环境不可达，网页端用真实15min）
        l3_proxy=True
        closes=day_closes
        ma20=sum(closes[-20:])/20; price=closes[-1]
        lastvol=kd[-1]['volume']; avgvol=sum(k['volume'] for k in kd[-20:])/20 if len(kd)>=20 else 0
        b=calc_bollinger(closes); sig=[]
        if b and b['position'] in ('下轨支撑','中轨附近'): tech+=1; sig.append('布林'+b['position'])
        if price>=ma20: tech+=1; sig.append('站上MA20')
        if avgvol>0 and lastvol>1.5*avgvol: tech+=1; sig.append('放量×%.1f'%(lastvol/avgvol))
        if md and check_macd_divergence(closes,md['dif']): tech+=1; sig.append('日线底背离')
        l3status='pass' if tech>=2 else ('wait' if tech>=1 else 'fail')
        l3detail='日线代理共振(15min不可用): '+(' / '.join(sig) if sig else '无信号')
    res['l3']={'status':l3status,'detail':l3detail,'tech':tech,'proxy':l3_proxy}
    # 小狼 2.0 强化层：在 L1(贪婪) + L3(技术) 基础上，叠加 恐慌急跌/小市值/剔除负因子
    # （实验室 8 年回测：通过此层样本胜率 74.2%，同日随机买基准 70.9%）
    res['wolf2']=wolf2_layer(kd, greed, tech, stock.get('small', False))
    # Layer 4
    flows=fetch_fund_flow(get_secid(code))
    if flows and len(flows)<5:
        real={f['date'] for f in flows}
        for k in kd[-5:]:
            if k['date'] and k['date'] not in real and k['open']>0 and k['volume']>0:
                avg=(k['open']+k['close'])/2; turnover=k['volume']*100*avg; pct=(k['close']-k['open'])/k['open']
                flows.append({'date':k['date'],'main':turnover*pct,'estimated':True})
        flows.sort(key=lambda x:x['date'])
    res['flows']=flows
    l4status='wait'; l4flow=''; l4detail='资金流数据不足'
    if flows:
        recent=flows[-3:]; allout=all(f['main']<0 for f in recent)
        slowing=allout and abs(recent[-1]['main'])<abs(recent[0]['main'])
        last=recent[-1]; lastin=last['main']>0; amt=last['main']/1e8
        est=any(f.get('estimated') for f in flows)
        note=' (部分为价量估算)' if est else ''
        if lastin: l4status,l4flow,l4detail='pass','主力回流','最近一日主力净流入 %.2f亿%s'%((amt if amt>=0 else amt),note)
        elif slowing: l4status,l4flow,l4detail='wait','流出放缓','近3日持续流出但幅度收窄%s'%note
        elif allout: l4status,l4flow,l4detail='fail','持续流出','近3日主力持续净流出%s'%note
        else: l4status,l4flow,l4detail='neutral','资金mixed','资金流向不明朗%s'%note
    res['l4']={'status':l4status,'flow':l4flow,'detail':l4detail}
    # Layer 5 右侧(趋势跟随)：与左侧低吸并列，让顺势买入被识别
    res['l5']=right_side(day_closes, kd, md)
    res['wave']=wave_stage(day_closes)
    # Layer 0 好公司过滤：仅当进入 A 候选(恐慌低位+技术共振)时才校验，避免全量拉取
    good_company=False; fund_detail=''
    if l1[0]=='pass' and l3status=='pass':
        if not YJ_MAP and not YJ_SNAPS:
            # 基本面数据完全不可用：保留技术信号，标注未验证(避免误杀)
            good_company=True; fund_detail='基本面数据暂不可用，技术信号保留(未验证好公司)'
        else:
            try:
                good_company, fund_detail = get_fundamentals(code)
            except Exception as e:
                good_company=True; fund_detail='基本面校验异常:%s，技术信号保留'%e
    res['fund']={'good':good_company,'detail':fund_detail}
    # 热点早期突破(E 档)判定用：当日是否放量（量比>1.5）。板块轮动初期主线个股常"放量长阳"，
    # 是资金真进场的直接证据；与 L3 代理里的放量判据保持一致口径。
    _lastvol = kd[-1]['volume'] if kd else 0
    _avgvol = sum(k['volume'] for k in kd[-20:]) / 20 if (kd and len(kd) >= 20) else 0
    _vol_up = _avgvol > 0 and _lastvol > 1.5 * _avgvol
    # Template —— 小狼 2.0 为最高优先级独立信号（回测 74.2%，不依赖四层 L1/L3 共振）
    # 恐慌急跌底部常表现为 L2 死叉/L3 无量，四层法会误杀；WOLF2 单独捕获这类均值回归买点。
    w2 = res['wolf2'].get('pass')
    l5score = res['l5'].get('score', 0); inf = res.get('inflow', 0) or 0
    if w2:
        res['template']='A'
        res['stop']=round(price*(1-WOLF2_STOP),3) if price else 0
        res['target']=round(price*(1+WOLF2_TP),3) if price else 0
        w=res['wolf2']
        res['suggestion']=('【小狼2.0强化·回测胜率74.2%%】低位恐慌+小市值+技术底背离，命中：%s。'
            '分批低吸，持有约%d日做均值回归，止损%d%%目标%d%%，急跌修复即走，不长期持有。')%(
            ' / '.join(w.get('reasons',[])) or '多因子共振', WOLF2_HOLD, int(WOLF2_STOP*100), int(WOLF2_TP*100))
    elif l5score>=2 and inf>0 and chg>0:
        # M 档 — 强势顺势(右侧·跟主力): 趋势向上(L5≥2)+主力净流入>0(L4)+当日上涨(处于"上涨阶段")。
        # 豁免 L1 贪婪过热: 领涨强势股本就处高位, 顺势追强不应被"贪婪过热禁止"误杀。
        # 板块/龙头备注在 main 的 sector_hot 回填后统一补全(避免 run_screening 阶段 sector_hot 尚未知的顺序陷阱)。
        res['template']='M'
        sig=res['l5'].get('why',[])
        opp='量价齐升' if ('放量' in sig and chg>0) else ('均线多头' if '均线多头' in sig else '趋势向上')
        dp=res.get('darkpool')
        dp_note='；明暗双线(主力+暗盘同流入)' if (dp is not None and dp>0) else ''
        res['suggestion']='强势顺势(右侧·跟主力): %s+主力净流入%.2f亿%s，沿5/10/20日线持有，止损%d%%、目标%d%%。'%(opp, inf/1e8, dp_note, int(STOP_PCT*100), int(TP_PCT*100))
    elif res['sector_hot'] and inf>E_INFLOW_MIN and chg>0 and _vol_up:
        # E 档 — 热点早期突破(右侧·小仓试错): 板块是资金持续净流入主线 + 个股主力净流入大(>1亿)
        #        + 当日放量上涨(量比>1.5)。板块共振盖过"个股贪婪过热"，许可跟随主线。
        # 豁免 L1 贪婪过热: 板块轮动初期主线个股贪婪常>65, 但板块资金主线给出"跟随"许可(本质追强)。
        # 小仓试错: conv 比 M 更低(见 base_trade_plan)、严格止损 8%、持有期更短, 兜住"追涨 Alpha 有限"的回测结论。
        res['template']='E'
        sec=res.get('sector',''); net=res.get('sector_net',0)
        dp=res.get('darkpool')
        dp_note='；明暗双线(主力+暗盘同流入)' if (dp is not None and dp>0) else ''
        vr=(_lastvol/_avgvol) if _avgvol else 0
        res['stop']=round(price*(1-E_STOP),3) if price else 0
        res['target']=round(price*(1+E_TP),3) if price else 0
        res['suggestion']=('热点早期突破(右侧·小仓试错): 所属板块【%s】资金持续净流入%.1f亿为当前主线，个股主力净流入%.2f亿+放量上涨(量比×%.1f)%s → 小仓位跟随主线，严格止损%d%%、目标%d%%，不恋战。'
            %(sec, net, inf/1e8, vr, dp_note, int(E_STOP*100), int(E_TP*100)))
    elif l1[0]=='fail': res['template']='C'; res['suggestion']='贪婪过热，禁止新开仓，持仓逢高逐步兑现。'
    elif res['l2']['status']=='fail': res['template']='D'; res['suggestion']='主跌阶段，观望，规避下跌风险。'
    elif l1[0]=='pass' and l3status=='pass':
        # 进入 A：低位 + 技术共振(1.0)。好公司仅作"优先级"(回测显示好公司过滤不增Alpha，
        # 但会丢弃93%信号)，故不再硬降级为B，而是好公司排前、非好公司轻仓/观察。
        res['template']='A'
        if good_company:
            res['suggestion']='好公司+低位共振(1.0)：小仓位分批低吸，持有约%d日做均值回归，止损%d%%目标%d%%，反弹属急跌修复，不长期持有。'%(
                HOLD_DAYS, int(STOP_PCT*100), int(TP_PCT*100))
        else:
            res['suggestion']='低位+技术共振(1.0,非好公司)：仅轻仓或观察，若参与同样止损%d%%目标%d%%；好公司优先级更低。'%(
                int(STOP_PCT*100), int(TP_PCT*100))
    else: res['template']='B'; res['suggestion']='纳入观察池，等待信号共振，暂不入场。'
    # 大盘方向门控：下行趋势禁止低吸接飞刀（回测显示下行期胜率仅~18%）
    gated, gnote = regime_gate(res['template'], res['market'])
    if gated != res['template']:
        res['template']=gated
        res['suggestion']=gnote
    elif gnote:
        res['suggestion']=res['suggestion'].rstrip('。')+'。'+gnote
    # 交易时机结构化决策（开仓/买入时机/持股/止盈止损），稍后由 apply_macro 用大市环境调制
    res['trade_plan'] = base_trade_plan(res)
    return res

# ---------- Layer 0: 好公司基本面过滤 ----------
# 规则：营收 同环比 正增长(YoY&QoQ) + ROE连续3年>8% + 经营现金流净额连续3年>0
YJ_MAP={}            # 最新一期业绩报表(实盘用)
YJ_MAP_PERIOD=None   # YJ_MAP 对应的报告期(用于判断是否年报)
YJ_SNAPS={}          # 历史各期业绩报表(回测 as-of 用)
FUND_LOCK=threading.Lock()

def load_yj_map(date=None):
    """载入业绩报表。date=None 载入最新一期到 YJ_MAP；给定 date 载入到 YJ_SNAPS[date]。"""
    global YJ_MAP, YJ_MAP_PERIOD
    import akshare as ak
    # 优先年报(12-31)：其"季度环比"=Q4 vs Q3 具参考意义；Q1单季环比因季节性普遍为负，不用于硬性过滤
    dates=[date] if date else ['20251231','20260331']
    for dt in dates:
        try:
            df=ak.stock_yjbb_em(date=dt)
            m={str(r['股票代码']):r for _,r in df.iterrows()}
            print('      业绩报表(%s) 载入 %d 只'%(dt,len(m)))
            if date: YJ_SNAPS[date]=m
            else: YJ_MAP=m; YJ_MAP_PERIOD=dt
            return m
        except Exception as e:
            print('      业绩报表(%s)失败: %s'%(dt,e))
    if date: YJ_SNAPS[date]={}
    return {}

def get_fundamentals(code, yj_row=None, asof=None, annual=None):
    """返回 (good, detail)。
       yj_row: 业绩报表行(含同环比增长)，不传则用 YJ_MAP[code]。
       asof:   'YYYY-MM-DD' 回测时点，过滤该时点前已披露的年报(避免未来函数)。
       annual: 该业绩报表是否为年报(12-31)。年报才纳入"季度环比(Q4 vs Q3)"硬性要求，
               避免 Q1 单季环比因季节性普遍为负而误杀。None 时按 YJ_MAP_PERIOD 推断。"""
    import akshare as ak
    import pandas as pd, datetime as _dt
    grow=False
    row=yj_row if yj_row is not None else YJ_MAP.get(code)
    if row is not None:
        try:
            rev_yoy=float(row['营业总收入-同比增长'])>0
            np_yoy=float(row['净利润-同比增长'])>0
            grow=rev_yoy and np_yoy
            if annual is None:
                annual = (YJ_MAP_PERIOD.endswith('1231') if YJ_MAP_PERIOD else False)
            if annual:
                rev_qoq=float(row['营业总收入-季度环比增长'])>0
                np_qoq=float(row['净利润-季度环比增长'])>0
                grow=grow and rev_qoq and np_qoq
        except Exception:
            grow=False
    roe_ok=ocf_ok=False
    try:
        if asof:
            ey=int(asof[:4]); sy=ey-3
        else:
            sy=_dt.datetime.now().year-3
        with FUND_LOCK:
            df=ak.stock_financial_analysis_indicator(symbol=code, start_year=str(sy))
        df=df.copy(); df['_d']=df['日期'].astype(str)
        if asof:
            df=df[pd.to_datetime(df['日期'])<=pd.Timestamp(asof[:10])]
        yr_df=df[df['_d'].str.endswith('12-31')].tail(3)
        if len(yr_df)>=3:
            roe_ok=all(float(x['净资产收益率(%)'])>8 for _,x in yr_df.iterrows())
            ocf_ok=all(float(x['每股经营性现金流(元)'])>0 for _,x in yr_df.iterrows())
    except Exception:
        pass
    good=bool(grow) and roe_ok and ocf_ok
    detail='ROE3年>8%%:%s 现金流3年>0:%s 增长(YoY%s):%s'%(roe_ok,ocf_ok,('&QoQ' if annual else ''),grow)
    return good, detail

# ---------- 大市环境调制（开仓总开关）----------
def load_macro_best_effort():
    """best-effort 读 李大霄温度 / 情绪，用于调制开仓信号（缺失不报错、不影响主线）。"""
    import os as _os
    HERE = _os.path.dirname(_os.path.abspath(__file__))
    ld = sd = None
    try:
        p = _os.path.join(HERE, 'li_daxiao.json')
        if _os.path.exists(p):
            with open(p, encoding='utf-8') as f:
                ld = json.load(f)
    except Exception:
        ld = None
    try:
        p = _os.path.join(HERE, 'sentiment.json')
        if _os.path.exists(p):
            with open(p, encoding='utf-8') as f:
                sd = json.load(f)
    except Exception:
        sd = None
    return ld, sd

def apply_macro(res, lidaxiao, sentiment):
    """用大市环境(李大霄温度 + 情绪指数)调制 per-pick 的 open 信号。
    李大霄原旨：底部温度只对【优质/蓝筹】构成"买"信号；其他标的底部仅作参考，不可生搬硬套（抄底劣质股=接飞刀）。"""
    tp = res.get('trade_plan')
    if not tp:
        return
    notes = []
    macro_open = None
    tier = ((lidaxiao or {}).get('sz50', {}) or {}).get('tier')
    sidx = (sentiment or {}).get('index')
    is_ld = bool(res.get('lidaxiao_pick'))
    qtxt = '（李大霄体系·优质蓝筹）' if is_ld else ''
    if tier in ('极致底部', '温和底部'):
        if is_ld:
            macro_open = 'open'; notes.append('李大霄温度=%s%s（估值底部，可重点配置优质蓝筹）' % (tier, qtxt))
        else:
            notes.append('李大霄温度=%s（底部区域，但本标的非蓝筹，底部信号仅供参考，以技术面为主）' % tier)
    elif tier == '接近底部':
        notes.append('李大霄温度=接近底部（下行空间收敛，可小仓优质蓝筹）')
    if isinstance(sidx, (int, float)):
        if sidx < 25:
            if is_ld:
                macro_open = 'open' if macro_open != 'no' else macro_open
            notes.append('情绪=恐慌(%.0f)%s，逆向买点' % (sidx, qtxt))
        elif sidx > 75:
            macro_open = 'no'; notes.append('情绪=狂热(%.0f)，逆向卖、控仓' % sidx)
    if macro_open == 'open' and tp['open'] == 'watch':
        tp['open'] = 'open'
        tp['open_reason'] = ('底层信号观望，但大市环境（%s）支持分批低吸' % '；'.join(notes)) + ('' if is_ld else '（注：非李大霄体系标的，仅技术面参考）')
    elif macro_open == 'no' and tp['open'] == 'open':
        tp['open'] = 'watch'
        tp['open_reason'] = '个股信号可开仓，但大市环境（%s）提示控仓，降为观察' % '；'.join(notes)
    if notes:
        tp['macro_note'] = '；'.join(notes)
        if 'rationale' in tp:
            tp['rationale'] += ' 大市环境：' + tp['macro_note'] + '。'

# ---------- 全市场预筛 ----------
def get_universe(top_n, min_inflow):
    """候选预筛。
    ⚠️ 重要(回测结论)：不要再按"主力净流入"排序/过滤！回测证明高净流入名单会系统性漏掉
    真正的恐慌低位股(贪困<40 的票往往仍在被抛售、净流入为负)，导致信号质量骤降
    (按净流入预筛的回测仅 36% 胜率/-3.4% 中位；全市场宽扫描为 61-65% 胜率/+6% 中位)。
    改为：拉取较宽的全市场，按"当日跌幅"升序偏向已被打压的弱势股，再由四层逻辑精选。"""
    fs='m:0+t:6'
    out=[]
    for pn in range(1,16):   # 拉取更宽的全市场(约3000只)，供上层四层逻辑精选
        u='https://push2delay.eastmoney.com/api/qt/clist/get?pn=%d&pz=200&fid=f3&po=0&fltt=2&invt=2&np=1&ut=fa5fd079d0a4d4f8f8f8f8&fs=%s&fields=f12,f14,f2,f3,f62,f21'%(pn,urllib.parse.quote(fs))
        try:
            d=json.loads(get(u)); rows=d.get('data',{}).get('diff',[]) if d.get('data') else []
        except Exception:
            rows=[]
        if not rows: break
        out+=rows
        if len(out)>=3000: break
        time.sleep(0.08)
    # 小狼2.0 的"小市值"因子：用全市场总市值(f21)中位数作分界，低于中位数=小市值。
    # （实验室用"20日成交额后50%"，与总市值后50%高度相关，此处用市值更稳定、无需历史成交额。）
    mcaps=[]
    for r in out:
        try:
            v=float(r.get('f21') or 0)
            if v>0: mcaps.append(v)
        except Exception: pass
    med_mcap=sorted(mcaps)[len(mcaps)//2] if mcaps else 0
    cand=[]
    for r in out:
        code=str(r.get('f12') or ''); name=str(r.get('f14') or ''); inflow=0; mcap=0
        try: price=float(r.get('f2') or 0)
        except Exception: price=0
        try: chg=float(r.get('f3') or 0)
        except Exception: chg=0
        try: inflow=float(r.get('f62') or 0)
        except Exception: inflow=0
        try: mcap=float(r.get('f21') or 0)
        except Exception: mcap=0
        if not code or len(code)<6: continue
        if code[0] in '849': continue          # 排除北交所/三板/B股
        if 'ST' in name or '退' in name: continue
        if price<2 or chg<-6 or chg>9.5: continue
        small = (0 < mcap <= med_mcap) if med_mcap>0 else False
        cand.append({'code':code,'name':name,'price':price,'change':chg,'inflow':inflow,'mcap':mcap,'small':small})
    # 按当日跌幅升序：越跌越靠前(更可能处于恐慌低位)，再由四层逻辑判定
    cand.sort(key=lambda x:x['change'])
    return cand[:top_n]

# ---------- 动量顺势候选池 / 暗盘 / 行业映射 / 板块热度 ----------
def get_flow_rank(top=60):
    """动量顺势候选池：全市场主力净流入排行 Top（"跟主力资金走"）。
    复用 push2 clist(fid=f62 排序)，与网页「个股资金流向」榜同源；只作顺势候选，
    绝不用于预筛/排序 A 档（A 仍全市场宽扫，遵守回测铁律）。"""
    fs='m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23'
    out=[]; pn=1
    while len(out)<top and pn<=4:
        u='https://push2delay.eastmoney.com/api/qt/clist/get?pn=%d&pz=100&fid=f62&po=1&fltt=2&invt=2&np=1&fs=%s&fields=f12,f14,f2,f3,f62'%(pn,urllib.parse.quote(fs))
        try:
            d=json.loads(get(u)); rows=d.get('data',{}).get('diff',[]) if d.get('data') else []
        except Exception:
            rows=[]
        if not rows: break
        out+=rows; pn+=1; time.sleep(0.05)
    res=[]
    for r in out[:top]:
        code=str(r.get('f12') or ''); name=str(r.get('f14') or '')
        try: price=float(r.get('f2') or 0)
        except Exception: price=0
        try: chg=float(r.get('f3') or 0)
        except Exception: chg=0
        try: inflow=float(r.get('f62') or 0)
        except Exception: inflow=0
        if not code or len(code)<6: continue
        if code[0] in '849': continue
        if 'ST' in name or '退' in name: continue
        if price<2: continue
        res.append({'code':code,'name':name,'price':price,'change':chg,'inflow':inflow})
    return res

def load_darkpool_rank(path='darkpool_rank.json'):
    """加载「暗盘资金榜」快照(由 emrnweb 暗盘资金页抓取保存)。
    暗盘资金=东财算法估算的隐藏主力行为(中单+小单拆单)，与主力净流入(明盘)互为补充。
    文件缺失时返回空 dict，M 档自动降级为仅看主力净流入(不阻断流水线)。"""
    try:
        d=json.load(open(path,encoding='utf-8'))
        return {str(x.get('code','')):float(x.get('amount_yi',0) or 0) for x in d if x.get('code')}
    except Exception:
        return {}

def load_industry_map(cache='industry_map.json'):
    """一次性构建 code→{'ind':行业, 'mcap':总市值} 映射（push2delay f100+f21，缓存当日）。
    不用 akshare stock_zh_a_spot_em：该端点在本环境频繁 RemoteDisconnected，push2delay 稳定。
    失败则降级为空 dict：板块加成失效，但 M 顺势档仍可基于 L5+净流入+涨幅工作。
    返回值是 dict-of-dict（{code:{'ind','mcap'}}），旧版 dict-of-string 缓存会被形状校验拒绝并重拉。"""
    HERE=os.path.dirname(os.path.abspath(__file__)); p=os.path.join(HERE,cache)
    today=time.strftime('%Y-%m-%d')
    MIN_MAP=3000   # 全市场行业归属应远多于 3000；少于此视为拉取不完整，不复用
    try:
        if os.path.exists(p):
            d=json.load(open(p,encoding='utf-8'))
            m0=d.get('map',{})
            # 仅当日且"足够完整"且"形状正确(dict-of-dict)"才复用；否则重拉
            if d.get('date')==today and len(m0)>=MIN_MAP and isinstance(next(iter(m0.values())),dict):
                return m0
    except Exception: pass
    mp={}
    ALL_FS='m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23'   # 深A主板/创业板/沪A主板/科创板 全覆盖(含沪市)
    def _page(pn):
        u='https://push2delay.eastmoney.com/api/qt/clist/get?pn=%d&pz=200&po=1&np=1&fltt=2&invt=2&fid=f3&fs=%s&fields=f12,f14,f100,f21'%(pn,urllib.parse.quote(ALL_FS))
        try:
            d=json.loads(get(u))
            data=d.get('data') or {}   # 个别分页返回 data:null，需 None 安全
            return data.get('diff') or []
        except Exception:
            return None
    try:
        pn=1
        while len(mp)<6000 and pn<=60:
            rows=_page(pn)
            if rows is None:
                time.sleep(0.2); rows=_page(pn)   # 单页瞬时失败重试一次
                if rows is None: break
            if not rows: break
            for r in rows:
                code=str(r.get('f12') or ''); ind=r.get('f100')
                if code and ind:
                    try: mcap=float(r.get('f21') or 0)
                    except Exception: mcap=0
                    mp[code]={'ind':str(ind),'mcap':mcap}
            pn+=1; time.sleep(0.05)
        print('      [行业映射] push2delay 获取 %d 只行业归属(含总市值)'%len(mp))
    except Exception as e:
        print('  [warn] 行业映射获取失败(板块加成降级):',e)
    try:
        # 仅当足够完整才落盘缓存，避免污染后续运行
        if len(mp)>=MIN_MAP:
            json.dump({'date':today,'map':mp}, open(p,'w',encoding='utf-8'), ensure_ascii=False)
    except Exception: pass
    return mp

def build_leaders(ind_map):
    """由 code->{'ind','mcap'} 映射计算「行业龙头」：按行业分组，总市值降序排名。
    is_leader = 行业内总市值前2(行业>=3只) 或 唯一/首位(行业<3只)。
    返回 code->{'industry','mcap','industry_rank','industry_count','is_leader'}。
    注：市值龙头是"行业地位"的最稳代理（营收/净利排名需逐季财报，此处用市值更稳、零额外请求）。"""
    by_ind={}
    for code,v in ind_map.items():
        if not isinstance(v,dict): continue
        m=v.get('mcap',0) or 0
        if m>0: by_ind.setdefault(v.get('ind',''),[]).append((code,m))
    out={}
    for ind,lst in by_ind.items():
        lst.sort(key=lambda x:-x[1]); cnt=len(lst)
        for i,(code,m) in enumerate(lst):
            r=i+1
            is_lead = (cnt>=3 and r<=2) or (cnt<3 and r==1)
            out[code]={'industry':ind,'mcap':m,'industry_rank':r,'industry_count':cnt,'is_leader':is_lead}
    return out

def load_sector_flow(path='sector_flow.json'):
    """读取板块资金流快照，返回 {行业名: sector_dict} 仅含"资金持续/短线流入"的热点板块。
    个股行业命中即视为市场动态主线。文件缺失则空 dict（板块加成失效，M 档仍可独立工作）。"""
    try:
        d=json.load(open(path,encoding='utf-8'))
        return {s['name']:s for s in (d.get('sectors',[]) or [])
                if s.get('net1',0)>0 and s.get('state') in ('持续流入','短线回流')}
    except Exception:
        return {}

def main():
    top_n=int(sys.argv[1]) if len(sys.argv)>1 else 100
    min_inflow=float(sys.argv[2]) if len(sys.argv)>2 else 0
    print('[1/3] 拉取候选（低位池 + 主力净流入顺势池）...')
    cand=get_universe(top_n, min_inflow); n_dec=len(cand)
    m_cand=get_flow_rank(60); n_mom=len(m_cand)
    seen=set(); merged=[]
    for c in cand+m_cand:
        if c['code'] in seen: continue
        seen.add(c['code']); merged.append(c)
    cand=merged
    dp_map=load_darkpool_rank()
    if dp_map: print('      暗盘资金榜快照载入 %d 只(明暗双线确认启用)'%len(dp_map))
    ind_map=load_industry_map(); sec_flow=load_sector_flow()
    leaders=build_leaders(ind_map)
    n_lead=sum(1 for v in leaders.values() if v['is_leader'])
    print('      [行业龙头] 覆盖 %d 个行业，标记龙头股 %d 只'%(len({v['industry'] for v in leaders.values()}), n_lead))
    for c in cand:
        c['darkpool']=dp_map.get(c['code'])
        info=ind_map.get(c['code'])
        c['sector']=info.get('ind','') if isinstance(info,dict) else ''
        c['mcap']=info.get('mcap',0) if isinstance(info,dict) else 0
        ld=leaders.get(c['code'])
        c['is_leader']=bool(ld['is_leader']) if ld else False
        c['industry_rank']=ld.get('industry_rank') if ld else None
        c['industry_count']=ld.get('industry_count') if ld else None
        # 板块热点标记：供 run_screening 判定 E 档(热点早期突破)使用，避免 run_screening 阶段
        # sector_hot 尚未知的顺序陷阱（与下方 main 统一回填逻辑保持一致）。
        sif=sec_flow.get(c['sector']) if c.get('sector') else None
        c['sector_hot']=bool(sif and sif.get('net1',0)>0 and sif.get('state') in ('持续流入','短线回流')) if sif else False
        c['sector_net']=sif.get('net1',0) if sif else 0
    print('      候选 %d 只（低位池 %d + 顺势池 %d，去重后 %d），开始四层判定...'%(n_dec+n_mom, n_dec, n_mom, len(cand)))
    print('[2/3] 载入最新业绩报表(好公司过滤用)...')
    load_yj_map()
    if not YJ_MAP:
        print('      ⚠️ 业绩报表载入失败，好公司过滤将暂不启用(技术信号保留为A)')
    results=[]
    done=0
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
        futs={ex.submit(run_screening,c):c for c in cand}
        for f in concurrent.futures.as_completed(futs):
            done+=1
            r=f.result(); results.append(r)
            if done%10==0 or done==len(cand):
                print('      [%d/%d] %s %s -> %s'%(done,len(cand),r['code'],r['name'],r['template']))
    # 板块热度标注：个股行业命中资金持续流入的板块 → sector_hot
    for r in results:
        sec=r.get('sector',''); info=sec_flow.get(sec) if sec else None
        if info:
            r['sector_hot']=bool(info.get('net1',0)>0 and info.get('state') in ('持续流入','短线回流'))
            r['sector_net']=info.get('net1',0); r['sector_rank']=info.get('rank')
        else:
            r['sector_hot']=False; r['sector_net']=0; r['sector_rank']=None
    # M / E 档建议补全「板块主线 + 行业龙头」备注（此时 sector_hot 已回填，修复此前为空的顺序陷阱）
    for r in results:
        if r.get('template') not in ('M','E'): continue
        sec=r.get('sector',''); hot=r.get('sector_hot')
        lead=r.get('is_leader'); ir=r.get('industry_rank'); ic=r.get('industry_count')
        add=''
        # E 档建议已自带「板块资金净流入N亿为当前主线」，不再重复；只补龙头属性
        if hot and r.get('template')!='E': add+='；所属板块【%s】资金持续流入，市场动态主线'%(sec)
        if lead: add+='；行业龙头(市值第%d/%d，基本面确定性高)'%(ir,ic)
        else: add+='；非龙头(行业第%d/%d)'%(ir,ic) if ir else ''
        if add: r['suggestion']=r['suggestion'].rstrip('。')+add+'。'
    A=[r for r in results if r['template']=='A']
    B=[r for r in results if r['template']=='B']
    C=[r for r in results if r['template']=='C']
    D=[r for r in results if r['template']=='D']
    M=[r for r in results if r['template']=='M']
    M.sort(key=lambda r:(0 if r.get('sector_hot') else 1, -(r.get('sector_net') or 0), -(r.get('darkpool') or 0), -(r.get('l5',{}).get('score',0))))
    E=[r for r in results if r['template']=='E']
    E.sort(key=lambda r:(0 if r.get('is_leader') else 1, -(r.get('sector_net') or 0), -(r.get('inflow',0) or 0), -(r.get('l5',{}).get('score',0))))
    A.sort(key=lambda r:(0 if r.get('sector_hot') else 1, 0 if r.get('fund',{}).get('good',False) else 1, r['l1']['greed'], -r.get('inflow',0)))
    B.sort(key=lambda r:(r['l1']['greed'], -r.get('inflow',0)))
    # 大市环境调制开仓信号（best-effort 读 李大霄温度 + 情绪）
    ld, sd = load_macro_best_effort()
    if ld or sd:
        qset = load_quality_set()   # 李大霄体系优质蓝筹集：底部温度只对它们构成"买"信号
        for r in results:
            r['lidaxiao_pick'] = r['code'] in qset
            apply_macro(r, ld, sd)
        print('      大市环境调制：李大霄=%s 情绪=%s' % (
            ((ld or {}).get('sz50', {}) or {}).get('tier'), (sd or {}).get('index')))
    # 热点板块龙头（资金净流入主线 + 行业龙头 + 顺势时机 三重确认）= 用户要的"捕捉市场动态"核心标的
    for r in results:
        r['hot_leader']=bool(r.get('is_leader') and r.get('sector_hot'))
    # 只收可操作档位（M 顺势 / A 低吸），避免把 C禁止/D观望 混进"龙头买入"面板
    LEAD=[r for r in results if r.get('hot_leader') and r.get('template') in ('M','A')]
    LEAD.sort(key=lambda r:(0 if r.get('template')=='M' else 1, -(r.get('sector_net') or 0), -(r.get('inflow',0) or 0), -(r.get('l5',{}).get('score',0))))
    # 资金主线龙头但当前不可买（过热/未共振）：不追高，只登记等回踩 —— 仍属"捕捉市场动态"，但给的是"不买"的建议
    LEADW=[r for r in results if r.get('hot_leader') and r.get('template') in ('B','C')]
    LEADW.sort(key=lambda r:(-(r.get('sector_net') or 0), -(r.get('inflow',0) or 0)))
    for r in LEADW:
        ir=r.get('industry_rank'); ic=r.get('industry_count')
        hot='贪婪%.0f%%已过热' % r['l1']['greed'] if r['l1']['greed']>=70 else '四层未共振'
        # 注：sector_flow.json 的 net1 单位已经是「亿元」，不要再除 1e8
        r['watch_note']='【%s·行业第%d/%d】板块资金净流入%.1f亿，龙头地位在，但%s → 不追高，等回踩 5/10 日线且缩量企稳再看，跌破 20 日线放弃。'%(
            r.get('sector',''), ir or 0, ic or 0, (r.get('sector_net') or 0), hot)
    # 输出
    wolf2A=[r for r in A if r.get('wolf2',{}).get('pass')]
    goodA=[r for r in A if r.get('fund',{}).get('good',False)]
    print('\n========== 小狼策略 · A股自动扫描结果 ==========')
    print('候选 %d 只 | 🚀M强势顺势 %d | 🔥E早期突破 %d | 🏆热点龙头 %d | A建议买入 %d (★小狼2.0 %d·好公司 %d) | B观察 %d | C禁止 %d | D观望 %d'%(
        len(results),len(M),len(E),len(LEAD),len(A),len(wolf2A),len(goodA),len(B),len(C),len(D)))
    if any(r['l3'].get('proxy') for r in results):
        print('⚠️ 注：本扫描环境取不到15分钟K线，第3层"技术共振"改用日线代理(布林支撑/站上MA20/放量/日线底背离)。')
        print('   网页端(wolf-screener3.0.html)以真实15分钟MACD复核可得严格结论，两者第1/2/4层完全一致。')
    def line(r):
        g=r['l1']['greed']; inflow=r.get('inflow',0)/1e8
        tag='★好公司' if r.get('fund',{}).get('good',False) else ''
        if r.get('wolf2',{}).get('pass'): tag='★小狼2.0 '+tag
        return '%s %s %s 价%.2f 涨%.2f%%  贪婪%.1f%%  主力净流入%.2f亿  [%s/%s/%s/%s]'%(
            r['code'],r['name'],tag,r['price'],r['change'],g,inflow,
            r['l1']['status'],r['l2']['status'],r['l3']['status'],r['l4']['status'])
    print('\n--- 🟢 A 建议低吸（低位+技术共振，★好公司优先） ---')
    for r in A: print(' '+line(r)+'\n    '+r['suggestion'])
    if M:
        print('\n--- 🚀 M 强势顺势（右侧·跟主力，捕捉上涨阶段/市场动态主线） ---')
        for r in M[:30]: print(' '+line(r)+('  [板块]%s%s'%(r.get('sector',''),'·🔥热点' if r.get('sector_hot') else ''))+'\n    '+r['suggestion'])
    if E:
        print('\n--- 🔥 E 热点早期突破（板块资金主线+个股放量长阳，小仓试错跟随） ---')
        for r in E[:30]: print(' '+line(r)+('  [板块]%s%s%s'%(r.get('sector',''),'·🔥热点' if r.get('sector_hot') else '','·🏆龙头' if r.get('is_leader') else ''))+'\n    '+r['suggestion'])
    print('\n--- 🟡 B 纳入观察池 ---')
    for r in B[:30]: print(' '+line(r))
    if LEAD:
        print('\n--- 🏆 热点板块龙头（板块资金净流入+行业龙头+顺势时机 三重确认，可操作） ---')
        for r in LEAD[:30]: print(' '+line(r)+('  [板块]%s·🔥热点%s'%(r.get('sector',''),'·🏆龙头' if r.get('is_leader') else ''))+'\n    '+r['suggestion'])
    if LEADW:
        print('\n--- ⏸ 资金主线龙头·当前不可买（过热/未共振，等回踩） ---')
        for r in LEADW[:15]: print(' '+line(r)+'\n    '+r.get('watch_note',''))
    if C:
        print('\n--- 🔴 C 贪婪过热禁止 ---'); 
        for r in C[:10]: print(' '+line(r))
    if D:
        print('\n--- ⚪ D 主跌观望 ---')
        for r in D[:10]: print(' '+line(r))
    # 保存
    out={'generated':time.strftime('%Y-%m-%d %H:%M'),'summary':{'cand':len(results),'M':len(M),'E':len(E),'leaders':len(LEAD),'leaders_wait':len(LEADW),'A':len(A),'B':len(B),'C':len(C),'D':len(D)},
         'market':get_market_regime(),'leaders':LEAD,'leaders_wait':LEADW,'M':M,'E':E,'A':A,'B':B,'C':C,'D':D}
    # 浏览器 JSON.parse 不接受 NaN/Infinity，写盘前先清洗成 null
    def _clean(o):
        if isinstance(o,dict): return {k:_clean(v) for k,v in o.items()}
        if isinstance(o,(list,tuple)): return [_clean(v) for v in o]
        if isinstance(o,float) and (math.isnan(o) or math.isinf(o)): return None
        return o
    json.dump(_clean(out), open('auto_screen_result.json','w',encoding='utf-8'), ensure_ascii=False, indent=1, allow_nan=False)
    print('\n✅ 已保存 auto_screen_result.json')

if __name__=='__main__':
    main()
