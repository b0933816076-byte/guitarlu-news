# -*- coding: utf-8 -*-
"""盧家宏《吉他故事館》吉他新聞:每天自動抓國外吉他新聞 → AI 寫繁體中文短摘要 → 按月存檔。
在 GitHub Actions 排程跑(電腦不用開、不用 Claude 額度)。不轉載原文:只寫自己的短摘要+出處+原文連結。

老師 10-27:「新聞可以少、不能錯」「寧可更新慢也不能有錯字」「翻譯不好寧可不更新」。
每則都要過全部關卡才發布(st=ok),任一關不過就不放:
  1. Google Gemini 免費額度寫稿(GitHub Models 已於 2026-07-30 停止服務)
  2. 程式檢查:OpenCC 查簡體字/大陸用語、譯名照故事館 names.json、字數、全形標點
  3. AI 對照英文原文審事實與人名
  4. AI 校對錯字、通順
  沒過 → 校對給的「原句→改法」直接套用、其他問題請 AI 修這一篇(不重寫),每次修完都從第 2 關重審;
  審 5 輪還沒過 → rejected,永不發布。AI 連不上 → pending,下次再試。
存檔:data/archive/YYYY-MM.json(全部,永久)、data/news.json(網站用,最新 200 則已通過)、data/months.json(歷史新聞月份)。
Gemini 免費額度用完就停、下次再寫(老師 10-27:新聞不是義務,有額度再更新、沒有就等);不寄失敗信。

用法: python news.py [--dry] [--max N]
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
AD = re.compile(r'\b(ad feature|advertorial|sponsored|paid content|partner content|in partnership with|brought to you by)\b', re.I)
PER_RUN = 4   # 每次最多寫 4 則(一天兩次);Gemini 免費額度每天有次數上限

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
        # 原文常把 and 寫成 &(Derek & the Dominos),兩種都要認得(10-28 沒認到 → 譯名跟故事館不一樣)
        if len(en) > 3 and re.search(r'\b' + re.escape(en).replace(r'\ and\ ', r'\ (?:and|&)\ ') + r'\b', text):
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
7. 舊訪談、舊事件要寫出年份,不能寫得像最近才發生;原文說「首次推出」和「原有產品」要分清楚。
8. 同一個外文名字(例如姓氏 Powers)在全文只能有一種譯法。
只回 JSON,不要其他文字:{{"title":"...","body":["第一段","第二段"],"cat":"...","names_en":["文中提到的英文人名或品牌"]}}

英文新聞標題:{title}
來源:{src}
內文:
{text}"""

GEMINI = 'https://generativelanguage.googleapis.com/v1beta/'
_model = None
_models = None

def gemini_models(key):
    """用環境變數 GEMINI_MODEL;沒設就列出可用的 Flash 文字模型,新版在前(Google 會換版本,不寫死)。"""
    global _models
    if _models is None:
        if os.environ.get('GEMINI_MODEL'):
            _models = [os.environ['GEMINI_MODEL']]
        else:
            r = requests.get(GEMINI + 'models', headers={'x-goog-api-key': key}, params={'pageSize': 200}, timeout=60)
            r.raise_for_status()
            names = [m['name'].split('/')[-1] for m in r.json().get('models', [])
                     if 'generateContent' in m.get('supportedGenerationMethods', [])]
            ver = lambda n: [float(x) if x.replace('.', '', 1).isdigit() else 0 for x in re.findall(r'[\d.]+', n)][:1]
            exact = sorted([n for n in names if re.match(r'gemini-[\d.]+-flash$', n)], key=ver, reverse=True)
            other = sorted([n for n in names if 'flash' in n and n not in exact
                            and not re.search(r'lite|image|tts|audio|live|exp|preview|thinking', n)], key=ver, reverse=True)
            flash = (exact + other)[:4]
            # 10-28:新 Flash 常忙線、舊 Flash 免費每天次數很少 → 後面接 Flash-Lite(免費額度分開算);寫得好不好仍由審稿關卡決定
            lite = sorted([n for n in names if re.match(r'gemini-[\d.]+-flash-lite$', n)], key=ver, reverse=True)[:2]
            if not flash + lite:
                raise RuntimeError('找不到可用的 Gemini Flash 模型:%s' % names[:20])
            _models = flash + lite
        print('  可用模型', _models)
    return _models

class QuotaOut(Exception):
    """Gemini 今天的免費額度用完,或每個模型都一直忙線。"""

START = time.time()
_dead = set()       # 這次執行裡「今天額度已用完」的模型
_busy = {}          # 這次執行裡各模型「一直忙線」的次數
_last_call = [0.0]

def ask_ai(prompt):
    """Google Gemini 免費額度(GitHub Models 已於 2026-07-30 停止服務)。金鑰放 GitHub Secrets 的 GEMINI_API_KEY。
    10-28 修:以前 503 忙線就永久換掉模型、四個輪完就說「額度用完」→ 其實額度還在,從來沒發出新聞。
    現在:忙線(500/503/逾時)→ 同一個模型等一下再試(20/60/120 秒),還不行這一次換別的模型,下次呼叫仍從最新的開始;
    429 每分鐘上限 → 等 65 秒再試;只有 Google 說「每天額度」用完的模型才停用。全部停用或全部一直忙 → QuotaOut,下次排程再寫。"""
    global _model
    key = os.environ.get('GEMINI_API_KEY')
    if not key:
        raise RuntimeError('沒有 GEMINI_API_KEY')
    models = gemini_models(key)
    if time.time() - START > 45 * 60:
        raise QuotaOut('這次已跑 45 分鐘')      # 雲端一次最多 60 分鐘,留時間存檔
    last = None
    # 這次執行裡一直忙線的模型排到最後,先用有回應的(免得每次呼叫都白等 3 分鐘)
    for m in sorted([x for x in models if x not in _dead], key=lambda x: _busy.get(x, 0)):
        for wait in (20, 60, 120, None):
            gap = time.time() - _last_call[0]
            if gap < 6:
                time.sleep(6 - gap)       # 免費版每分鐘次數少,呼叫之間至少隔 6 秒
            _last_call[0] = time.time()
            try:
                r = requests.post(GEMINI + 'models/%s:generateContent' % m, headers={'x-goog-api-key': key, 'Content-Type': 'application/json'},
                                  json={'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
                                        'generationConfig': {'temperature': 0.2, 'responseMimeType': 'application/json'}}, timeout=180)
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                r = None
            if r is not None and r.status_code == 200:
                try:
                    _model = m
                    return ''.join(p.get('text', '') for p in r.json()['candidates'][0]['content']['parts'])
                except Exception:
                    raise RuntimeError('AI 回應格式不對:%r' % r.text[:200])
            last = 'timeout' if r is None else r.status_code
            if r is not None and r.status_code not in (429, 500, 502, 503, 504):
                r.raise_for_status()
            if r is not None and r.status_code == 429:
                if re.search(r'PerDay|per day|daily', r.text, re.I):
                    print('  %s 今天的免費額度用完' % m)
                    _dead.add(m)
                    break
                wait = 65 if wait else None   # 每分鐘上限:等過這一分鐘
            if wait is None:
                break
            print('  %s 忙線(%s),等 %d 秒再試' % (m, last, wait))
            time.sleep(wait)
        if m not in _dead:
            _busy[m] = _busy.get(m, 0) + 1
            print('  %s 一直沒回應(%s),這次先換下一個模型' % (m, last))
    raise QuotaOut('全部模型額度用完' if len(_dead) == len(models) else '全部模型一直忙線(%s)' % last)

def js(txt):
    return json.loads(re.search(r'\{.*\}', txt, re.S).group(0))

def parse(txt):
    o = js(txt)
    body = [p.strip() for p in (o.get('body') or []) if p and p.strip()]
    title = (o.get('title') or '').strip()
    if not title or not body:
        raise ValueError('AI 回覆不完整')
    # 人名中間點統一成故事館用的「·」(U+00B7)
    fixdot = lambda x: x.replace('‧', '·').replace('・', '·')
    title, body = fixdot(title), [fixdot(p) for p in body]
    if o.get('cat') not in CATS:
        o['cat'] = '吉他手'
    return title, body, o['cat']

# ---------- 把關(老師 10-27:寧可慢也不能有錯字、翻不好就不放) ----------
try:
    from opencc import OpenCC
    _cc = OpenCC('s2t')
except Exception:
    _cc = None
# OpenCC 會改、但台灣繁體本來就這樣寫的字(人名「范」、「公里」「台灣」「岳飛」…)
OK_CHARS = set('台吃岩峰托范干只里余后征群唇咸皂床秘栗祢厘岳')
# 台灣不用的大陸用語(出現就退稿)
CN_WORDS = ['視頻', '質量', '信息', '軟件', '硬件', '網絡', '默認', '屏幕', '鼠標', '博客', '短信', '打印', '激光', '光盤',
            '互聯網', '數據庫', '音頻', '錄像', '帖子', '高清', '給力', '靠譜', '水平很', '優化了', '牛逼', '粉絲們紛紛', '小夥伴',
            '吉他手們', '搖滾樂隊', '樂隊', '專輯封面照', '單曲循環', '演唱會門票']
NAMES_STRICT = load(os.path.join(DATA, 'names_strict.json'), {})

def rule_check(title, body):
    """程式檢查:簡體字、大陸用語、吉他手譯名要照故事館、字數、全形標點。回傳問題清單(空=通過)。"""
    txt = title + '\n' + '\n'.join(body)
    bad = []
    if _cc is None:
        bad.append('OpenCC 沒裝,無法檢查簡體字')
    else:
        simp = sorted({ch for ch in re.findall(r'[一-鿿]', txt) if ch not in OK_CHARS and _cc.convert(ch) != ch})
        if simp:
            bad.append('有簡體字:' + ''.join(simp))
    for w in CN_WORDS:
        if w in txt:
            bad.append('大陸用語:' + w)
    for en, want in NAMES_STRICT.items():
        for zh in re.findall(r'([一-鿿·]{1,14})（' + re.escape(en) + r'）', txt):
            if not zh.endswith(want):
                bad.append('譯名要跟故事館一樣:%s（%s）應為 %s' % (zh, en, want))
    n = len(re.sub(r'\s', '', ''.join(body)))
    if n < 120 or n > 480:
        bad.append('字數 %d 不在 120～480' % n)
    if not 10 <= len(title) <= 75:
        bad.append('標題長度不對')
    if re.search(r'[,;:?!](?=[一-鿿])|(?<=[一-鿿])[,;:?!]', txt):
        bad.append('中文句子用了半形標點')
    if '�' in txt or '??' in txt:
        bad.append('有亂碼')
    return bad

REVIEW_FACT = """你是嚴格的新聞審稿編輯。下面是英文原文和一則繁體中文短新聞。逐句檢查中文稿:
- 任何與原文不符的事實、數字、日期、人名、品牌、型號、地名
- 原文沒有、中文卻寫出來的內容(包括把原文旁邊其他文章的內容混進來)
- 翻錯意思、人名或專有名詞音譯明顯錯誤
- 原文是舊訪談或舊事件,中文卻沒寫年份、讀起來像最近發生
- 把原有產品寫成新品,或把新品寫成原有產品
有任何一點問題就判不通過。只回 JSON:{{"ok":true或false,"problems":["具體問題"]}}

英文原文標題:{title_en}
英文原文:
{text}

中文稿:
{zh}"""

REVIEW_TEXT = """你是台灣出版社的資深校對。下面是一則要刊登的繁體中文短新聞,請只看中文本身,逐字檢查:
- 錯字、別字、漏字、多字(例如「在/再」「的/得/地」「做/作」用錯)
- 簡體字、異體字、大陸用語(例如視頻、質量、信息、軟件)
- 語句不通順、讀起來像機器翻譯、主詞不清楚
- 標點錯誤(中文要用全形標點)
- 同一個外文名字前後譯法不一致(例如同一個 Powers 一處寫鮑爾斯、一處寫寶爾斯)
本站規定:外國人名中間點一律用「·」(故事館統一寫法,例如 約翰·梅爾),這不是錯誤,不要改成「‧」。
只列「確定是錯」的地方;可改可不改的風格偏好、換個說法也行的句子,不要列。
找到任何一個確定的錯誤就判不通過。只回 JSON:{{"ok":true或false,"problems":["原句→建議改法"]}}

中文稿:
{zh}"""

REVISE = """你是《吉他故事館》新聞編輯。下面這則中文短新聞被審稿退回,請「修改這一篇」,不要整篇重寫:
只改審稿指出的地方(必要時連同那一句一起改順),其他沒問題的句子一個字都不要動。
修改時仍要遵守:只寫英文原文裡有的事實、台灣繁體中文、全形標點、外國人名中間點用「·」、
人名品牌第一次出現寫「中文（English）」、譯名照這份對照表:{hints}
只回 JSON,不要其他文字:{{"title":"...","body":["第一段","第二段"],"cat":"{cat}"}}

審稿問題:
{probs}

英文原文標題:{title_en}
英文原文:
{text}

被退回的中文稿(JSON):
{draft}"""

def review(c, text, title, body):
    """回傳 (問題清單, 哪一關):'rule' 程式檢查、'fact' 對照原文、'text' 校對;沒問題回 ([], '')。"""
    zh = title + '\n' + '\n'.join(body)
    probs = rule_check(title, body)
    if probs:
        return probs, 'rule'
    for kind, tpl in (('fact', REVIEW_FACT), ('text', REVIEW_TEXT)):
        o = js(ask_ai(tpl.format(title_en=c['title_en'], text=text, zh=zh)))
        if not o.get('ok') or o.get('problems'):
            return [str(p) for p in (o.get('problems') or ['不通過'])], kind
    return [], ''

def apply_fixes(title, body, probs):
    """校對給的「原句→改法」直接套進稿子(10-28:以前退稿就整篇重寫,新稿又冒新錯字,永遠過不了)。
    每一條都要在稿子裡找得到原句才套;有一條套不上就回 None,改請 AI 修稿。套完一樣要從頭再審一次。"""
    strip = lambda s: s.strip().strip('「」『』"\'“”').strip()
    t, b = title, list(body)
    for p in probs:
        q = re.findall(r'「([^」]+)」', p)
        if '→' in p:
            old, new = (strip(x) for x in p.split('→', 1))
        elif len(q) == 2:                       # 「態在大變」是錯字,應為「態度大變」
            old, new = q
        else:
            return None
        if len(q) == 2 and old not in t + ''.join(b):
            old, new = q
        old = re.sub(r'^.*?[:：]', '', old) if old not in t + ''.join(b) else old   # 去掉「錯字:」這類前綴
        if not old or not new or old == new or abs(len(old) - len(new)) > 20:
            return None
        if old in t:
            t = t.replace(old, new, 1)
        elif any(old in x for x in b):
            i = next(i for i, x in enumerate(b) if old in x)
            b[i] = b[i].replace(old, new, 1)
        else:
            return None
    return t, b

def story_links(text):
    out = []
    for en, v in LINKS.get('people', {}).items():
        if re.search(r'\b' + re.escape(en) + r'\b', text):
            out.append({'url': v['url'], 'title': v['title']})
    topic = [(r'\bauction|Heritage Auctions|Christie|Sotheby|Bonhams|Julien', 'lesson-hist-140-rare-auction-records.html', '吉他拍賣天價紀錄'),
             (r'\bFender\b', 'lesson-hist-20-brand-fender.html', '芬達（Fender）品牌故事'),
             (r'\bGibson\b|\bEpiphone\b', 'lesson-hist-19-brand-gibson.html', '吉布森（Gibson）品牌故事'),
             (r'\bpedals?\b|\beffects\b|\bNAM\b|modeler', 'lesson-hist-06-effects-pedal-history.html', '效果器的歷史'),
             (r'\bamp\b|amplifier|Marshall|Vox\b', 'lesson-hist-05-amplifier-history.html', '音箱的歷史')]
    for pat, u, t in topic:
        if len(out) >= 3:
            break
        if re.search(pat, text, re.I) and all(o['url'] != u for o in out):
            out.append({'url': u, 'title': t})
    return out[:3]

def write_item(c):
    """寫稿→把關→沒過就照審稿意見修這一篇(不是重寫)→再從頭審;最多審 5 輪、AI 修稿最多 2 次。
    st=ok 才會出現在網站;rejected 永不發布;pending=AI 連不上,下次再試。"""
    text = article_text(c['url'], c['rss'])
    links = story_links(c['title_en'] + ' ' + text)
    # 業配/贊助文不是新聞(10-28 Powers Electric 那篇原文寫 Ad feature,被寫成新聞上了網站)
    if AD.search(c['title_en'] + ' ' + text[:1000]):
        print('  業配文,不寫')
        return dict(st='rejected', title='', body=[], cat='', problems=['業配/贊助內容,不當新聞']), links
    hint = json.dumps(hints(c['title_en'] + ' ' + text), ensure_ascii=False)
    prompt = PROMPT.format(hints=hint, cats='、'.join(CATS), title=c['title_en'], src=c['src'], text=text)
    probs = []
    revised = 0
    try:
        title, body, cat = parse(ask_ai(prompt))
        for n in range(5):
            probs, kind = review(c, text, title, body)
            if not probs:
                return dict(st='ok', title=title, body=body, cat=cat, by='gemini:' + (_model or ''), problems=[]), links
            print('  第 %d 輪沒過(%s):' % (n + 1, kind), probs[:3])
            fixed = apply_fixes(title, body, probs) if kind == 'text' else None
            if fixed:
                title, body = fixed
                print('  照校對改法修正,再審一次')
                continue
            if revised >= 2:
                break
            revised += 1
            draft = json.dumps({'title': title, 'body': body, 'cat': cat}, ensure_ascii=False)
            title, body, cat = parse(ask_ai(REVISE.format(hints=hint, cat=cat, probs='\n'.join(probs[:8]),
                                                          title_en=c['title_en'], text=text, draft=draft)))
            print('  AI 照審稿意見修稿,再審一次')
    except QuotaOut:
        raise
    except Exception as e:
        print('  AI 連不上/格式錯:', str(e)[:150])
        return dict(st='pending', title='', body=[], cat='', problems=['AI 連不上']), links
    return dict(st='rejected', title='', body=[], cat='', problems=probs[:8]), links

# ---------- 存檔:按月永久保存 ----------
ARCH = os.path.join(DATA, 'archive')

def load_all():
    items = []
    if os.path.isdir(ARCH):
        for f in sorted(os.listdir(ARCH)):
            if f.endswith('.json'):
                items += load(os.path.join(ARCH, f), [])
    return items

def save_all(items):
    os.makedirs(ARCH, exist_ok=True)
    by = {}
    for it in items:
        by.setdefault(it['date'][:7], []).append(it)
    months = []
    for m, lst in sorted(by.items()):
        lst.sort(key=lambda x: x['when'], reverse=True)
        save(os.path.join(ARCH, m + '.json'), lst)
        months.append({'month': m, 'count': sum(1 for x in lst if x['st'] == 'ok')})
    ok = sorted([x for x in items if x['st'] == 'ok'], key=lambda x: x['when'], reverse=True)
    save(NEWS, ok[:200])                      # 網站首頁用:最新 200 則(已通過把關)
    save(os.path.join(DATA, 'months.json'), [m for m in reversed(months) if m['count']])

# ---------- 主程式 ----------
def main():
    dry = '--dry' in sys.argv
    mx = PER_RUN
    if '--max' in sys.argv:
        mx = int(sys.argv[sys.argv.index('--max') + 1])
    items = load_all()
    st = load(STATUS, {})
    stats = {'ok': 0, 'rejected': 0, 'pending': 0}

    # 老師 10-27:新聞不是義務、不用天天更新;有額度再更新,沒有就等 → 額度用完就停,寫好的照存,下次再接著寫
    try:
        # 先補寫上次 AI 連不上的(只補 14 天內的)
        for it in items:
            if it['st'] == 'pending' and mx > 0 and now() - dt.datetime.fromisoformat(it['when']) < dt.timedelta(days=14):
                w, links = write_item({'url': it['url'], 'rss': '', 'title_en': it['title_en'], 'src': it['src']})
                it.update(w); it['links'] = links; mx -= 1
                stats[w['st']] += 1
                print('補寫', it['id'], w['st'])

        seen_urls = {it['url'] for it in items}
        seen_titles = [norm(it['title_en']) for it in sorted(items, key=lambda x: x['when'], reverse=True)[:400]]
        for c in fetch_candidates(seen_urls, seen_titles)[:max(mx, 0)]:
            print('寫', c['src'], c['title_en'][:70])
            w, links = write_item(c)
            stats[w['st']] += 1
            day = c['when'][:10]
            it = {'id': day + '-' + slug(c['title_en']), 'date': day, 'when': c['when'], 'src': c['src'], 'url': c['url'],
                  'title_en': c['title_en'], 'links': links, 'added': now().isoformat()}
            it.update(w)
            items.append(it)
    except QuotaOut as e:
        print('Gemini 不能用(%s),這次先停,下次排程再寫' % e)
        st['last_quota_out'] = now().isoformat()

    t = now().isoformat()
    st['last_run'] = t
    if stats['ok']:
        st['last_new'] = t
    st['last_run_stats'] = stats
    st['total_ok'] = sum(1 for x in items if x['st'] == 'ok')
    ln = st.get('last_new') or st.setdefault('first_run', t)
    if not dry:
        save_all(items)
        save(STATUS, st)
    print('本次 通過 %(ok)d、退稿 %(rejected)d、待補 %(pending)d' % stats, '總計已發布', st['total_ok'])


if __name__ == '__main__':
    main()
