# -*- coding: utf-8 -*-
"""狼大发言抓取 (NGA authorid=150058)

产出 wolf_voice.json：最近发言、情绪倾向、提及的板块/个股关键词。
定位：**参考信息，不参与买卖打分**（与李大霄温度同级别 —— 只展示不决策）。
理由：单一意见领袖的观点无法回测验证，一旦给权重就是把不可证伪的东西塞进策略。
"""
import json, os, re, ssl, time, html, urllib.request

def clean_nan(o):
    """递归把 NaN/Infinity 换成 None，避免写出浏览器解析不了的 NaN（非法 JSON）。"""
    if isinstance(o, float):
        return o if (o == o and o != float('inf') and o != float('-inf')) else None
    if isinstance(o, dict):
        return {k: clean_nan(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean_nan(v) for v in o]
    return o

HERE = os.path.dirname(os.path.abspath(__file__))
CTX = ssl.create_default_context(); CTX.check_hostname = False; CTX.verify_mode = ssl.CERT_NONE
AUTHOR_ID = '150058'
THREADS = ['47288722', '47207407']        # 狼大主帖(新/旧)
MAX_POSTS = 30
HDRS = {'User-Agent': 'Nga_Official',
        'X-User-Agent': 'NGA_skull/7.3.1(iPhone13,2;iOS 16.0)',
        'Referer': 'https://ngabbs.com/'}

# 情绪词典（贴合狼大口语风格：技术+筹码+资金博弈视角，不是研报腔）
BULL = ['抄底', '低吸', '加仓', '满仓', '看多', '反弹', '止跌', '企稳', '机会', '布局',
        '底部', '超跌', '买入', '进场', '乐观', '扛住', '护盘', '净流入', '信心',
        '放量拉', '缩量拉', '吃筹码', '洗盘', '拿住', '有肉', '套利', '起来了', '强势',
        '主升', '资金进', '接盘完', '错杀', '性价比']
BEAR = ['减仓', '清仓', '看空', '出货', '风险', '踩踏', '下杀', '破位', '止损', '离场',
        '谨慎', '观望', '套牢', '杀跌', '崩', '恐慌', '多杀多', '流出',
        '诱多', '出货了', '接盘', '被套', '割肉', '追高', '别追', '不追', '横在上面',
        '砸盘', '跳水', '缩量跌', '没量', '资金走', '骗线']
SECTORS = ['科技', '半导体', '存储', '光纤', '芯片', '算力', '军工', '医药', '白酒', '新能源',
           '光伏', '锂电', '证券', '券商', '银行', '地产', '消费', 'AI', '机器人', '有色',
           '煤炭', '电力', '化工', '汽车', '沪深300', '创业板', '科创板', '中证500', '宽基']


def get(url, timeout=15):
    req = urllib.request.Request(url, headers=HDRS)
    raw = urllib.request.urlopen(req, timeout=timeout, context=CTX).read()
    try:
        return raw.decode('gbk', 'ignore')
    except Exception:
        return raw.decode('utf-8', 'ignore')


def clean(raw):
    """NGA UBB → 纯文本"""
    t = re.sub(r'\[quote\].*?\[/quote\]', '', raw, flags=re.S)      # 去引用
    t = re.sub(r'<br\s*/?>', '\n', t)
    t = re.sub(r'\[/?[^\]]{1,40}\]', '', t)                          # 去UBB标签
    t = re.sub(r'<[^>]+>', '', t)
    t = html.unescape(t)
    t = re.sub(r'改动commonui\.loadAlertInfo\([^)]*\)', '', t)
    t = re.sub(r'\n{3,}', '\n\n', t)
    return t.strip()


def parse_thread(tid, page=1):
    url = ('https://ngabbs.com/read.php?tid=%s&authorid=%s&opt=262144&page=%d'
           % (tid, AUTHOR_ID, page))
    t = get(url)
    title = ''
    m = re.search(r'<title>(.*?)</title>', t, re.S)
    if m:
        title = re.sub(r'\s*-\s*NGA玩家社区\s*$', '', html.unescape(m.group(1))).strip()
    bodies = re.findall(r'id=[\'"]postcontent\d+[\'"][^>]*>(.*?)</(?:p|div)>', t, re.S)
    dates = re.findall(r'postdate\d*[\'"]?[^>]*>([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2})<', t)
    posts = []
    for i, b in enumerate(bodies):
        txt = clean(b)
        if len(txt) < 8:
            continue
        posts.append({'date': dates[i] if i < len(dates) else '',
                      'text': txt[:1200], 'tid': tid})
    has_next = ('page=%d' % (page + 1)) in t
    return title, posts, has_next


def score_sentiment(text):
    b = sum(text.count(w) for w in BULL)
    s = sum(text.count(w) for w in BEAR)
    total = b + s
    if total == 0:
        return 'neutral', 0.0
    v = (b - s) / total
    if v >= 0.3:
        return 'bull', round(v, 2)
    if v <= -0.3:
        return 'bear', round(v, 2)
    return 'neutral', round(v, 2)


def extract_tags(text):
    return sorted({s for s in SECTORS if s in text})


def main():
    all_posts, titles = [], []
    for tid in THREADS:
        try:
            for pg in (1, 2):
                title, posts, nxt = parse_thread(tid, pg)
                if pg == 1 and title:
                    titles.append(title)
                all_posts.extend(posts)
                if not nxt:
                    break
            print('  tid=%s 抓到 %d 条' % (tid, len(all_posts)))
        except Exception as e:
            print('  ! tid=%s 抓取失败: %s' % (tid, e))
    # 去重 + 按时间倒序
    seen, uniq = set(), []
    for p in all_posts:
        k = p['text'][:60]
        if k in seen:
            continue
        seen.add(k)
        uniq.append(p)
    uniq.sort(key=lambda x: x['date'] or '', reverse=True)
    uniq = uniq[:MAX_POSTS]

    for p in uniq:
        p['mood'], p['score'] = score_sentiment(p['text'])
        p['tags'] = extract_tags(p['text'])

    recent = uniq[:8]
    if recent:
        avg = sum(p['score'] for p in recent) / len(recent)
        overall = 'bull' if avg >= 0.2 else ('bear' if avg <= -0.2 else 'neutral')
    else:
        avg, overall = 0.0, 'na'
    tag_cnt = {}
    for p in recent:
        for t in p['tags']:
            tag_cnt[t] = tag_cnt.get(t, 0) + 1

    out = {'generated': time.strftime('%Y-%m-%d %H:%M'),
           'source': 'NGA authorid=%s' % AUTHOR_ID,
           'threads': THREADS, 'titles': titles,
           'overall_mood': overall, 'overall_score': round(avg, 2),
           'hot_tags': sorted(tag_cnt.items(), key=lambda x: -x[1])[:8],
           'posts': uniq,
           'note': '参考信息，不参与买卖打分'}
    json.dump(clean_nan(out), open(os.path.join(HERE, 'wolf_voice.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, allow_nan=False)
    print('OK wolf_voice.json  %d条  总体情绪=%s(%.2f)  热词=%s'
          % (len(uniq), overall, avg, [t for t, _ in out['hot_tags'][:5]]))


if __name__ == '__main__':
    main()
