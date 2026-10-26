# -*- coding: utf-8 -*-
"""盧家宏《吉他故事館》吉他新聞:每天自動抓國外吉他新聞 → AI 寫繁體中文短摘要 → data/news.json。
在 GitHub Actions 每天跑(電腦不用開)。不轉載原文:只寫自己的短摘要+出處+原文連結。

AI 三層備援(老師 10-27:不用 Claude 額度、一切自動化、不能哪天停更):
  1. GitHub Models(免費,用 GITHUB_TOKEN)
  2. Ollama 本機模型(雲端電腦上臨時裝;本機測試時用老師 D 槽的 Ollama)
  3. 都失敗 → 只放英文原標題+連結(raw=1),下次跑會自動補寫中文
連續 2 天沒有新新聞 → 程式回傳失敗 → GitHub 寄信通知。

用法: python news.py [--ollama] [--dry] [--max N]
"""
import os, re, sys, json, time, hashlib, difflib, datetime as dt
import requests, feedparser

try:
    import trafilatura
except Exception:
    trafilatura = None

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data')
NEWS = os.path.join(DATA, 'news.json')
STATUS = os.path.join(DATA, 'status.json')
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36'}
TZ = dt.timezone(dt.timedelta(hours=8))

FEEDS = [  # (來源名稱, RSS, 是否只收吉他相關)
    ('Guitar World', 'https://www.guitarworld.com/feeds/all', False),
    ('Guitar Player', 'https://www.guitarplayer.com/feeds/all', False),
    ('Premier Guitar', 'https://www.premierguitar.com/feeds/feed.rss', False),
    ('Guitar.com', 'https://guitar.com/feed/', False),
    ('Acoustic Guitar', 'https://acousticguitar.com/feed/', False),
    ('Classical Guitar', 'https://www.classicalguitarmagazine.com/feed/', False),
    ('MusicRadar', 'https://www.musicradar.com/feeds/all', True),
]
SKIP = re.compile(r'\b(deal|deals|sale|discount|price drop|lowest[- ]ever|save \$|quiz|buying guide|best .{0,30} (for|under)|coupon|sponsored|giveaway|win a|black friday|cyber monday|prime day|newsletter|subscribe|podcast)\b', re.I)
GUITARISH = re.compile(r'guitar|bass|amp\b|amplifier|pedal|fret|riff|strat|tele|les paul|luthier|pickup|string', re.I)
CATS = ['新琴・器材', '吉他手', '拍賣・名琴', '演出・活動', '效果器・科技', '教學・觀念']
PER_DAY = 6

def now():
    return dt.datetime.now(TZ)

def load(p, d):
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return d

def save(p, o):
    tmp = p + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(o, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)

def norm(t):
    return re.sub(r'[^a-z0-9 ]', '', t.lower())

def slug(t):
    s = re.sub(r'[^a-z0-9]+', '-', t.lower()).strip('-')
    return s[:60].rstrip('-') or hashlib.md5(t.encode()).hexdigest()[:8]

# ---------- 抓新聞 ----------
def fetch_candidates(seen_urls, seen_titles):
    out = []
    for src, url, need in FEEDS:
        try:
            r = requests.get(url, headers=UA, timeout=30)
            fp = feedparser.parse(r.content)
        except Exception as e:
            print('來源失敗', src, e)
            continue
        n = 0
        for e in fp.entries:
            link = (e.get('link') or '').split('?')[0]
            title = re.sub(r'\s+', ' ', e.get('title', '')).strip()
            if not link or not title or link in seen_urls:
                continue
            summ = re.sub(r'<[^>]+>', ' ', e.get('summary', ''))
            if SKIP.search(title) or SKIP.search(link):
                continue
            if need and not GUITARISH.search(title + ' ' + summ):
                continue
            t = e.get('published_parsed') or e.get('updated_parsed')
            when = dt.datetime(*t[:6], tzinfo=dt.timezone.utc).astimezone(TZ) if t else now()
            if now() - when > dt.timedelta(days=4):
                continue
            nt = norm(title)
            if any(difflib.SequenceMatcher(None, nt, s).ratio() > 0.72 for s in seen_titles):
                continue
            seen_titles.append(nt)
            out.append({'src': src, 'url': link, 'title_en': title, 'when': when.isoformat(), 'rss': summ[:600]})
            n += 1
        print(src, '新候選', n)
    # 各來源輪流挑,避免全是同一家
    by = {}
    for c in sorted(out, key=lambda c: c['when'], reverse=True):
        by.setdefault(c['src'], []).append(c)
    pick = []
    while len(pick) < len(out) and any(by.values()):
        for k in list(by):
            if by[k]:
                pick.append(by[k].pop(0))
    return pick

def article_text(url, fallback):
    try:
        r = requests.get(url, headers=UA, timeout=30)
        if trafilatura:
            t = trafilatura.extract(r.text, include_comments=False, include_tables=False, include_links=False, favor_precision=True) or ''
        else:
            t = re.sub(r'<[^>]+>', ' ', ' '.join(re.findall(r'<p[^>]*>(.*?)</p>', r.text, re.S)))
        t = re.sub(r'\s+', ' ', t).strip()
        if len(t) > 300:
            return t[:7000]
    except Exception as e:
        print('  內文失敗', e)
    return fallback

# ---------- AI ----------
NAMES = load(os.path.join(DATA, 'names.json'), {})
LINKS = load(os.path.join(DATA, 'story-links.json'), {'people': {}, 'articles': []})

def hints(text):
    h = {}
    for en, zh in NAMES.items():
        if len(en) > 3 and re.search(r'\b' + re.escape(en) + r'\b', text):
            h[en] = zh
        if len(h) >= 40:
            break
    return h

PROMPT = """你是台灣吉他教室「盧家宏吉他音樂教室」網站《吉他故事館》的新聞編輯。
請根據下面的英文新聞,用台灣繁體中文寫一則短新聞。規則:
1. 只寫這則新聞本身的事實,不要猜、不要加評論、不要編造數字或引言;內文裡混進來的其他文章標題、廣告、「延伸閱讀」一律忽略。
2. 用自己的話改寫,不要逐句翻譯,不要引用超過 15 個英文字的原句。
3. 國外人名、地名、品牌、專有名詞第一次出現寫「中文（English）」,例如「查克·貝瑞（Chuck Berry）」;之後只寫中文。型號、專輯、歌名保留英文。
4. 譯名一律照這份對照表(表裡沒有的再自己音譯):{hints}
5. 標題 18～40 字,吸引人但不誇大。內文 2～3 段,共 150～260 字。
6. 分類只能選一個:{cats}
只回 JSON,不要其他文字:{{"title":"...","body":["第一段","第二段"],"cat":"...","names_en":["文中提到的英文人名或品牌"]}}

英文新聞標題:{title}
來源:{src}
內文:
{text}"""

def ask_github(prompt):
    tok = os.environ.get('GITHUB_TOKEN')
    if not tok:
        raise RuntimeError('沒有 GITHUB_TOKEN')
    last = None
    for model in ('openai/gpt-4.1-mini', 'openai/gpt-4o-mini'):
        try:
            r = requests.post('https://models.github.ai/inference/chat/completions',
                              headers={'Authorization': 'Bearer ' + tok, 'Content-Type': 'application/json'},
                              json={'model': model, 'temperature': 0.3, 'messages': [{'role': 'user', 'content': prompt}]}, timeout=120)
            if r.status_code == 429:
                time.sleep(20)
                r = requests.post('https://models.github.ai/inference/chat/completions',
                                  headers={'Authorization': 'Bearer ' + tok, 'Content-Type': 'application/json'},
                                  json={'model': model, 'temperature': 0.3, 'messages': [{'role': 'user', 'content': prompt}]}, timeout=120)
            r.raise_for_status()
            return r.json()['choices'][0]['message']['content'], 'github:' + model
        except Exception as e:
            last = e
    raise RuntimeError('GitHub Models 失敗: %s' % last)

def ask_ollama(prompt):
    r = requests.post('http://127.0.0.1:11434/api/generate',
                      json={'model': os.environ.get('OLLAMA_MODEL', 'qwen2.5:7b'), 'prompt': prompt, 'stream': False,
                            'format': 'json', 'options': {'temperature': 0.3, 'num_ctx': 8192}}, timeout=900)
    r.raise_for_status()
    return r.json()['response'], 'ollama'

def parse(txt):
    m = re.search(r'\{.*\}', txt, re.S)
    o = json.loads(m.group(0))
    body = [p.strip() for p in (o.get('body') or []) if p and p.strip()]
    title = (o.get('title') or '').strip()
    if not title or not body or not re.search(r'[一-鿿]', title + ''.join(body)):
        raise ValueError('AI 回覆不完整')
    if o.get('cat') not in CATS:
        o['cat'] = '吉他手'
    return title, body, o['cat'], o.get('names_en') or []

def story_links(text):
    out = []
    for en, v in LINKS.get('people', {}).items():
        if re.search(r'\b' + re.escape(en) + r'\b', text):
            out.append({'url': v['url'], 'title': v['title']})
    topic = [(r'\bauction|Heritage Auctions|Christie|Sotheby|Bonhams|Julien', 'lesson-hist-140-rare-auction-records.html', '吉他拍賣天價紀錄'),
             (r'\bFender\b', 'lesson-hist-20-brand-fender.html', '芬達（Fender）品牌故事'),
             (r'\bGibson\b|\bEpiphone\b', 'lesson-hist-19-brand-gibson.html', '吉布森（Gibson）品牌故事'),
             (r'\bpedal|effects|NAM\b|modeler', 'lesson-hist-06-effects-pedal-history.html', '效果器的歷史'),
             (r'\bamp\b|amplifier|Marshall|Vox\b', 'lesson-hist-05-amplifier-history.html', '音箱的歷史')]
    for pat, u, t in topic:
        if len(out) >= 3:
            break
        if re.search(pat, text, re.I) and all(o['url'] != u for o in out):
            out.append({'url': u, 'title': t})
    return out[:3]

def write_item(c, use_ollama):
    text = article_text(c['url'], c['rss'])
    prompt = PROMPT.format(hints=json.dumps(hints(c['title_en'] + ' ' + text), ensure_ascii=False),
                           cats='、'.join(CATS), title=c['title_en'], src=c['src'], text=text)
    errs = []
    for fn in ([ask_ollama] if use_ollama else [ask_github, ask_ollama]):
        try:
            raw, by = fn(prompt)
            title, body, cat, _ = parse(raw)
            return dict(title=title, body=body, cat=cat, by=by, raw=0), story_links(c['title_en'] + ' ' + text)
        except Exception as e:
            errs.append(str(e)[:120])
    print('  AI 全失敗:', errs)
    return dict(title=c['title_en'], body=[], cat='吉他手', by='none', raw=1), story_links(c['title_en'] + ' ' + text)

# ---------- 主程式 ----------
def main():
    use_ollama = '--ollama' in sys.argv
    dry = '--dry' in sys.argv
    mx = PER_DAY
    if '--max' in sys.argv:
        mx = int(sys.argv[sys.argv.index('--max') + 1])
    items = load(NEWS, [])
    st = load(STATUS, {})
    ai_fail = 0

    # 先補寫之前 AI 失敗、只有英文標題的
    for it in items:
        if it.get('raw') and mx > 0:
            w, links = write_item({'url': it['url'], 'rss': '', 'title_en': it['title_en'], 'src': it['src']}, use_ollama)
            if not w['raw']:
                it.update(w); it['links'] = links; mx -= 1
                print('補寫', it['id'])

    seen_urls = {it['url'] for it in items}
    seen_titles = [norm(it['title_en']) for it in items[:400]]
    added = 0
    for c in fetch_candidates(seen_urls, seen_titles)[:max(mx, 0)]:
        print('寫', c['src'], c['title_en'][:70])
        w, links = write_item(c, use_ollama)
        ai_fail += w['raw']
        day = c['when'][:10]
        it = {'id': day + '-' + slug(c['title_en']), 'date': day, 'when': c['when'], 'src': c['src'], 'url': c['url'],
              'title_en': c['title_en'], 'links': links, 'added': now().isoformat()}
        it.update(w)
        items.insert(0, it)
        added += 1

    items.sort(key=lambda x: x['when'], reverse=True)
    items = items[:1500]
    t = now().isoformat()
    st['last_run'] = t
    if added:
        st['last_new'] = t
    st['added_last_run'] = added
    st['ai_fail_last_run'] = ai_fail
    st['total'] = len(items)
    if not dry:
        save(NEWS, items)
        save(STATUS, st)
    print('新增', added, 'AI失敗', ai_fail, '總數', len(items))

    # 防停更:2 天沒新新聞 → 失敗 → GitHub 寄信
    ln = st.get('last_new')
    if ln and now() - dt.datetime.fromisoformat(ln) > dt.timedelta(days=2):
        print('★超過 2 天沒有新新聞')
        sys.exit(2)
    if ai_fail and ai_fail == added and not use_ollama:
        sys.exit(3)   # GitHub Models 全掛 → 讓排程改用 Ollama 再跑一次

if __name__ == '__main__':
    main()
