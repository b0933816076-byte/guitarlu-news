"""吉他史上的今天:AI 自己從英文維基百科找吉他史大事(10-29 老師:「讓 AI 用程式自己找然後轉載,類似吉他新聞」「不是用 Claude 額度」)。
來源:data/today-sources.json(百大吉他手、百大吉他名曲的英文維基條目,各自連回故事館文章)。
流程:抓條目全文 → 程式挑出有完整日期(月日年)的句子、生日忌日不收 → Gemini 挑「值得報導」的(轉捩點、傳奇演出、名曲誕生、
改變命運、名琴)並寫成中文 → 程式檢查＋AI 對照原文審事實＋AI 校對,全過才收。日期由程式從原文讀,不讓 AI 寫。
存檔:data/today.json {"MM-DD":[{y,t,cat,src,story,en,id,added}]},只加不改;總數變少就不存。
共用吉他新聞的 Gemini 免費額度:新聞先跑,這支排在後面;額度用完就停,下次接著做。
用法: python today.py [--dry] [--max 頁數]"""
import json, os, re, sys, hashlib, time
import requests
import news as N

DATA = N.DATA
OUT = os.path.join(DATA, 'today.json')
SRC = os.path.join(DATA, 'today-sources.json')
STATE = os.path.join(DATA, 'today-state.json')
PER_RUN = 3          # 每次最多讀 3 個條目(額度先給新聞)
CATS = ['轉捩點', '傳奇演出', '名曲誕生', '改變命運', '名琴']
MON = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
DATE = re.compile(r'\b(?:(%s) (\d{1,2}),? (\d{4})|(\d{1,2}) (%s),? (\d{4}))\b' % ('|'.join(MON), '|'.join(MON)))
SKIP = re.compile(r'\b(born|died|dies|death|deaths|funeral|buried|obituary|passed away|was killed|retrieved|archived|accessed)\b', re.I)

JUDGE = """你是台灣《吉他故事館》「吉他史上的今天」的編輯。下面是英文維基百科「{wiki}」條目裡寫到完整日期的句子(每句前面有編號)。
故事館裡對應的文章是:{zh}。
請挑出「值得在吉他史上的今天介紹」的事。必須屬於其中一類:{cats}
- 轉捩點:改變吉他或音樂走向的第一次、發明、專利、新樂器或新技術誕生
- 傳奇演出:後來被反覆提起的演出(不是普通巡演的某一場)
- 名曲誕生:名曲或名專輯的錄音日、發行日
- 改變命運:讓這位吉他手人生轉彎的事(加入或離開樂團、意外、第一次登台、被發掘)
- 名琴:名琴誕生、失竊、尋回、拍賣紀錄
不收:生日忌日、普通演出、獎項提名、排行榜名次、官司細節、和吉他無關的事、跟「{zh}」不是同一個人或同一首歌的事。
寧可少,不夠格就不要選;一句都不夠格就回空陣列。每則用台灣繁體中文寫 1～2 句(40～110 字):
- 第一句說發生什麼事,第二句說為什麼重要;只能用句子裡有的事實,不要猜、不要加原文沒有的數字或形容
- 不要寫日期和年份(網站會自己加),不要用「今天」開頭
- 國外人名、樂團、地名第一次出現寫「中文（English）」,譯名照這份對照表:{hints};歌名、專輯名保留英文並用〈〉或《》
- 全形標點,外國人名中間點用「·」
只回 JSON:{{"pick":[{{"i":編號,"score":1到5分(5=吉他史上非常重要),"cat":"類別","zh":"中文"}}]}}

句子:
{lines}"""


WRITE = """你是台灣《吉他故事館》「吉他史上的今天」的編輯。下面是英文維基百科「{wiki}」裡的一段原文,其中這一句講的是 {date} 發生的事:
「{sent}」
請用台灣繁體中文寫 1～2 句(40～110 字)介紹這件事:
- 第一句:發生了什麼事(誰、在哪裡、做了什麼),寫具體,讓沒聽過的人也看得懂
- 第二句(可省略):只有這段原文「明白寫到」這件事帶來的結果或影響時才寫,而且只能寫原文說的結果;原文沒寫就不要第二句
- 絕對不要加原文沒有的形容或評價(例如劃時代、傳奇、震撼、里程碑、改寫歷史),不要猜、不要加數字
- 不要寫日期和年份,不要用「今天」開頭
- 國外人名、樂團、地名第一次出現寫「中文（English）」,譯名照這份對照表:{hints};歌名、專輯名保留英文並用〈〉或《》
- 全形標點,外國人名中間點用「·」
只回 JSON:{{"zh":"中文"}}

原文段落:
{para}"""


def load(p, d):
    return N.load(p, d)


def save(p, o):
    N.save(p, o)


def wiki_text(title):
    for wait in (10, 30, 90, None):      # 維基百科限速(429)就等一下再試
        r = requests.get('https://en.wikipedia.org/w/api.php', headers={'User-Agent': 'guitarlu-today/1.0 (github b0933816076-byte)'},
                         params=dict(action='query', prop='extracts|revisions', rvprop='ids', explaintext=1, titles=title, redirects=1, format='json'), timeout=60)
        if r.status_code != 429 or wait is None:
            break
        time.sleep(wait)
    r.raise_for_status()
    pg = next(iter(r.json()['query']['pages'].values()))
    return pg.get('extract') or '', (pg.get('revisions') or [{}])[0].get('revid')


def candidates(text):
    """有完整日期、不是生日忌日的句子。回傳 [(月, 日, 年, 句子, 前後文)]"""
    text = re.split(r'\n== ?(See also|References|Notes|External links|Further reading|Bibliography|Discography) ?==', text)[0]
    paras = [x.strip() for x in text.split('\n') if len(x.strip()) > 40 and not x.strip().startswith('=')]
    out, seen = [], set()
    for para in paras:
        for s in re.split(r'(?<=[.!?])\s+(?=[A-Z"“])', para):
            if len(s) > 400 or SKIP.search(s):
                continue
            for m in DATE.finditer(s):
                mon = m.group(1) or m.group(5)
                day = int(m.group(2) or m.group(4))
                yr = int(m.group(3) or m.group(6))
                if not 1500 <= yr <= 2030 or day > 31:
                    continue
                k = (mon, day, yr)
                if k in seen:
                    continue
                seen.add(k)
                out.append((MON.index(mon) + 1, day, yr, s, para[:2500]))   # 前後文=整段;「為什麼重要」只能用這段裡有的事實
    return out[:40]


def check_zh(zh, yr):
    """程式檢查:沿用新聞的簡體字/大陸用語/譯名規則,字數改成短文。"""
    bad = [p for p in N.rule_check('吉他史上的今天短文', [zh]) if not p.startswith(('字數', '標題'))]
    n = len(re.sub(r'\s', '', zh))
    if n < 25 or n > 160:
        bad.append('字數 %d 不在 25～160' % n)
    if re.search(r'\d{4}\s*年|今天', zh):
        bad.append('不要寫年份或「今天」')
    return bad


REVIEW_FACT = """你是嚴格的審稿編輯。下面是英文維基百科原文和一則「吉他史上的今天」繁體中文短文。網站會在短文前面自動加上「{date}」,所以中文稿本身沒寫日期是正常的。
逐句檢查中文稿:
- 任何與原文不符的事實、數字、人名、樂團、歌名、地名、樂器型號
- 原文沒有、中文卻寫出來的內容(包括誇大的形容、原文沒說的「為什麼重要」)
- 這件事真的發生在 {date}(看原文日期是不是指這件事,不是同一句裡別的事)
- 翻錯意思、人名或專有名詞音譯明顯錯誤
有任何一點問題就判不通過。只回 JSON:{{"ok":true或false,"problems":["具體問題"]}}

英文原文(維基百科 {src}):
{text}

中文稿:
{zh}"""


# 10-29 試跑:「寶麗多唱片」「丹佛」沒附英文也過了 → 校對加一條中英對照
REVIEW_TEXT = N.REVIEW_TEXT.replace('- 同一個外文名字', '- 國外人名、樂團、唱片公司、錄音室、場地、地名第一次出現沒寫成「中文（English）」(例如只寫「寶麗多唱片」沒附（Polydor）);本來就是英文的歌名、專輯名不算\n- 同一個外文名字', 1)
assert REVIEW_TEXT != N.REVIEW_TEXT


def review(zh, src, ctx, date):
    probs = check_zh(zh, None)
    if probs:
        return probs, 'rule'
    for kind, tpl in (('fact', REVIEW_FACT), ('text', REVIEW_TEXT)):
        o = N.js(N.ask_ai(tpl.format(date=date, src=src, text=ctx, zh=zh)))
        if not o.get('ok') or o.get('problems'):
            return [str(p) for p in (o.get('problems') or ['不通過'])], kind
    return [], ''


def main():
    dry = '--dry' in sys.argv
    mx = int(sys.argv[sys.argv.index('--max') + 1]) if '--max' in sys.argv else PER_RUN
    src = load(SRC, [])
    data = load(OUT, {})
    state = load(STATE, {'done': {}})
    n_old = sum(len(v) for v in data.values())
    have = {e['id'] for v in data.values() for e in v}
    # 還沒讀過的條目先讀;都讀過了就重讀最久以前讀的(維基會更新)
    todo = sorted(src, key=lambda s: state['done'].get(s['wiki'], {}).get('at', ''))[:mx]
    stats = {'pages': 0, 'cand': 0, 'pick': 0, 'ok': 0, 'rejected': 0}
    try:
        for s in todo:
            print('讀', s['wiki'], '→', s['story'])
            text, rev = wiki_text(s['wiki'])
            if state['done'].get(s['wiki'], {}).get('rev') == rev:
                state['done'][s['wiki']]['at'] = N.now().isoformat()
                print('  條目沒改過,跳過'); continue
            cs = candidates(text)
            stats['pages'] += 1; stats['cand'] += len(cs)
            if cs:
                lines = '\n'.join('%d. %s' % (i, c[3]) for i, c in enumerate(cs))
                hint = json.dumps(N.hints(text[:20000]), ensure_ascii=False)
                o = N.js(N.ask_ai(JUDGE.format(wiki=s['wiki'], zh=s['zh'], cats='、'.join(CATS), hints=hint, lines=lines)))
                for p in o.get('pick') or []:
                    try:
                        i, sc, cat, zh = int(p['i']), int(p['score']), p['cat'], p['zh'].strip()
                    except Exception:
                        continue
                    if not 0 <= i < len(cs) or sc < 4 or cat not in CATS:
                        continue
                    mo, dy, yr, sent, ctx = cs[i]
                    k = '%02d-%02d' % (mo, dy)
                    eid = hashlib.md5(('%s|%d|%s' % (k, yr, s['story'])).encode()).hexdigest()[:10]
                    if eid in have:
                        continue
                    stats['pick'] += 1
                    try:   # 挑選時只看到一句;改用整段原文重寫,重要性只能照原文
                        w = N.js(N.ask_ai(WRITE.format(wiki=s['wiki'], date='%d 年 %d 月 %d 日' % (yr, mo, dy), sent=sent, para=ctx, hints=hint)))
                        zh = (w.get('zh') or '').strip() or zh
                    except N.QuotaOut:
                        raise
                    except Exception:
                        pass
                    print('  候選 %d/%s %d分 %s:%s' % (yr, k, sc, cat, zh))
                    ok = False
                    for rnd in range(3):
                        probs, kind = review(zh, s['wiki'], ctx, '%d 年 %d 月 %d 日' % (yr, mo, dy))
                        if not probs:
                            ok = True; break
                        print('   沒過(%s):' % kind, probs[:2])
                        fixed = N.apply_fixes('吉他史上的今天', [zh], probs) if kind == 'text' else None
                        if not fixed:
                            break
                        zh = fixed[1][0]
                    if ok:
                        data.setdefault(k, []).append({'y': str(yr), 't': zh, 'cat': cat, 'score': sc, 'src': 'https://en.wikipedia.org/wiki/' + s['wiki'].replace(' ', '_'),
                                                       'story': s['story'], 'en': sent, 'id': eid, 'added': N.now().isoformat()})
                        have.add(eid); stats['ok'] += 1
                        print('   通過:', zh)
                    else:
                        stats['rejected'] += 1
            state['done'][s['wiki']] = {'rev': rev, 'at': N.now().isoformat()}
    except N.QuotaOut as e:
        print('Gemini 不能用(%s),這次先停,下次排程再接著做' % e)
    for k in data:
        data[k].sort(key=lambda e: e['y'])
    data = dict(sorted(data.items()))
    n = sum(len(v) for v in data.values())
    print('本次', stats, '總計', n)
    if n < n_old:
        sys.exit('總數變少(%d < %d),不存檔' % (n, n_old))
    if not dry:
        save(OUT, data)
        save(STATE, state)


if __name__ == '__main__':
    main()
