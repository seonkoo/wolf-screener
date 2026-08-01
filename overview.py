# -*- coding: utf-8 -*-
"""
overview.py — 综合研判总览（B1）

把五个维度的信号合成一个「机会分(0-100)」+ 一句话研判 + 建议动作，
解决多信号可能互相打架、新手不知如何加权的问题。

输入（均已在先前步骤生成）：
  strategy_guard.json : 市场状态/仓位系数/风险等级/实盘回检
  national_team.json  : 国家队资金态度（进场托市/降温离场/观望）
  sentiment.json      : 情绪指数 + 区带（冰点/恐慌/中性/乐观/狂热）
  auto_screen_result.json : A 类建议买入数量
  watch_pool.json     : 观察池真实命中率 vs 回测

输出：overview.json
"""
import json, time, os, math

HERE = os.path.dirname(os.path.abspath(__file__))

def load(name, default=None):
    try:
        return json.load(open(os.path.join(HERE, name), encoding='utf-8'))
    except Exception:
        return default

def clamp(x, lo=0, hi=100):
    return max(lo, min(hi, x))

def main():
    guard = load('strategy_guard.json', {})
    team = load('national_team.json', {})
    sent = load('sentiment.json', {})
    auto = load('auto_screen_result.json', {})
    watch = load('watch_pool.json', {})

    comp = {}
    score = 50.0

    # —— 情绪（反向指标）：越冰点越加分 ——
    zone = sent.get('zone', '')
    sidx = sent.get('index')
    if '冰点' in zone: sc = 20
    elif '恐慌' in zone: sc = 12
    elif '中性偏弱' in zone: sc = 4
    elif '中性偏强' in zone: sc = -4
    elif '乐观' in zone: sc = -12
    elif '狂热' in zone: sc = -20
    else: sc = 0
    comp['sentiment'] = {'zone': zone, 'index': sidx, '贡献': sc}
    score += sc

    # —— 国家队资金：托市加分，撤离减分 ——
    att = (team.get('conclusion') or {}).get('attitude', '')
    if '进场' in att: tc = 15
    elif '离场' in att: tc = -15
    else: tc = 0
    comp['national_team'] = {'attitude': att, '贡献': tc}
    score += tc

    # —— 市场状态（guard.regime）：熊/弱略减，强/震荡略加 ——
    lvl = (guard.get('regime') or {}).get('level', '')
    if lvl in ('BULL', '震荡反弹', '强势'): mc = 5
    elif lvl in ('WEAK', '弱势', '弱势震荡'): mc = 0   # 弱势本身中性，靠仓位系数控风险
    elif lvl in ('BEAR', '熊'): mc = -5
    else: mc = 0
    comp['regime'] = {'level': lvl, '贡献': mc}
    score += mc

    # —— 观察池真实命中率：高于回测加分，低于减分（自我纠正关键输入）——
    vs = (watch.get('stats') or {}).get('vs_backtest', '')
    wr = (watch.get('stats') or {}).get('win_rate')
    wn = (watch.get('stats') or {}).get('closed', 0)
    if wn and wr is not None:
        if vs == '高于回测': wc = 8
        elif vs == '低于回测': wc = -10
        else: wc = 3
        comp['watch_pool'] = {'vs_backtest': vs, 'win_rate': wr, 'closed': wn, '贡献': wc}
        score += wc
    else:
        comp['watch_pool'] = {'vs_backtest': '样本不足', '贡献': 0}

    # —— 自动选股 A 数量：有信号略加分（说明低位共振标的存在）——
    a_n = (auto.get('summary') or {}).get('A', 0)
    comp['auto_A'] = {'count': a_n}
    if a_n and a_n > 0:
        score += min(5, a_n / 10.0)  # 最多+5

    score = clamp(score)

    # —— 研判分级 ——
    if score >= 70:
        verdict, action = '积极布局窗口', '多维度共振偏多，可小仓分批低吸优质标的，严守止损纪律。'
    elif score >= 50:
        verdict, action = '偏乐观 · 可分批', '情绪/资金偏友好，按信号小仓参与，控制总仓位。'
    elif score >= 30:
        verdict, action = '中性 · 按纪律', '信号交织，不追不杀，仅做最强共振，设好止损。'
    elif score >= 15:
        verdict, action = '偏谨慎 · 防守', '情绪偏热或资金退潮，减仓观望，仅留底仓。'
    else:
        verdict, action = '防守 · 控仓', '多维度偏空，建议空仓/极轻仓，等待冰点共振。'

    # 风险等级（沿用 guard，红色优先）
    risk = guard.get('risk_level', 'GREEN')

    # 综合一句话（解释主要驱动）
    drivers = sorted(comp.items(), key=lambda kv: abs(kv[1].get('贡献', 0)), reverse=True)
    parts = []
    for k, v in drivers:
        c = v.get('贡献', 0)
        if c == 0 and k != 'auto_A':
            continue
        label = {'sentiment': '情绪', 'national_team': '国家队', 'regime': '市场',
                 'watch_pool': '实盘验证', 'auto_A': '选股信号'}.get(k, k)
        if k == 'auto_A':
            parts.append('%s有%d只A信号' % (label, v['count']))
        else:
            parts.append('%s%s(%+d)' % (label, v.get('zone') or v.get('attitude') or v.get('vs_backtest', ''), c))
    sentence = '；'.join(parts) if parts else '各维度信号交织'

    out = {
        'generated': time.strftime('%Y-%m-%d %H:%M'),
        'score': round(score, 1),
        'verdict': verdict,
        'action': action,
        'risk_level': risk,
        'sentence': sentence,
        'components': comp,
        'caveat': '综合研判为多维启发式合成（非机器学习/非确定性结论），用于辅助加权，不构成投资建议；各维度独立 Tab 可下钻查证。',
    }
    # NaN 清洗
    def clean(o):
        if isinstance(o, dict): return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list): return [clean(v) for v in o]
        if isinstance(o, float) and (math.isnan(o) or math.isinf(o)): return None
        return o
    out = clean(out)
    json.dump(out, open(os.path.join(HERE, 'overview.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, allow_nan=False)
    print('[总览] 机会分 %.1f → %s（风险%s）' % (score, verdict, risk))
    print('       驱动:', sentence)

if __name__ == '__main__':
    main()
