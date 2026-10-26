<?php
/* 盧家宏《吉他故事館》吉他新聞頁(老師 10-27:固定更新國際吉他新聞、一切自動化、不用 Claude 額度)
   ■ 新聞資料由 GitHub 倉庫 b0933816076-byte/guitarlu-news 每天自動產生(data/news.json),這裡只負責讀取＋排版。
   ■ 網址:
       /guitar-news.php               新聞首頁(?c=分類)
       /guitar-news.php/<新聞id>      單則新聞(可分享、Google 收錄;網址永久不變)
       /guitar-news.php/rss.xml       RSS
   ■ 外框沿用 guitar-stories.html(選單、頁尾、樣式版本號自動跟著網站更新)。
   ■ 讀不到 GitHub 時用上次的快取,頁面不會壞。不想用了刪掉這個檔案和 guitar-news-cache 資料夾即可。 */
define('SRC', getenv('GN_SRC') ?: 'https://raw.githubusercontent.com/b0933816076-byte/guitarlu-news/main/data/');   // 本機測試可用 GN_SRC 指到本機資料夾
const SITE = 'https://www.guitarlu.net/';
const SELF = 'https://www.guitarlu.net/guitar-news.php';
const CATS = array('新琴・器材', '吉他手', '拍賣・名琴', '演出・活動', '效果器・科技', '教學・觀念');
const PER_PAGE = 30;

function h($s){ return htmlspecialchars((string)$s, ENT_QUOTES, 'UTF-8'); }

function fetch_json($name, $ttl){
    $dir = __DIR__ . '/guitar-news-cache';
    if(!is_dir($dir)) @mkdir($dir, 0755);
    $f = $dir . '/' . str_replace('/', '_', $name);
    $age = file_exists($f) ? time() - filemtime($f) : 1e9;
    if($age > $ttl){
        $ctx = stream_context_create(array('http' => array('timeout' => 8, 'header' => "User-Agent: guitarlu-news\r\n")));
        $src = SRC . $name . (strpos(SRC, 'http') === 0 ? '?t=' . floor(time() / $ttl) : '');
        $j = @file_get_contents($src, false, strpos(SRC, 'http') === 0 ? $ctx : null);
        if($j !== false && is_array(json_decode($j, true))) @file_put_contents($f, $j, LOCK_EX);
        elseif(file_exists($f)) @touch($f);   // 失敗:沿用舊快取,過一陣子再試
    }
    $a = file_exists($f) ? json_decode(file_get_contents($f), true) : array();
    return is_array($a) ? $a : array();
}
function only_ok($a){                       // 只放通過全部審稿的(st=ok)
    $out = array();
    foreach($a as $it){ if(isset($it['st']) && $it['st'] === 'ok' && !empty($it['body'])) $out[] = $it; }
    return $out;
}
function news(){ return only_ok(fetch_json('news.json', 1800)); }
function months(){ return fetch_json('months.json', 1800); }
function month_news($m){ return preg_match('/^\d{4}-\d{2}$/', $m) ? only_ok(fetch_json('archive/' . $m . '.json', 21600)) : array(); }

function cn_date($d){ $p = explode('-', $d); return count($p) == 3 ? intval($p[0]) . ' 年 ' . intval($p[1]) . ' 月 ' . intval($p[2]) . ' 日' : $d; }

function share($url, $title){
    $u = rawurlencode($url);
    return '<div class="gn-share"><a class="ln" href="https://social-plugins.line.me/lineit/share?url=' . $u . '" target="_blank" rel="noopener">LINE 分享</a>'
         . '<a href="https://www.facebook.com/sharer/sharer.php?u=' . $u . '" target="_blank" rel="noopener">FB 分享</a>'
         . '<a href="#" onclick="navigator.clipboard&&navigator.clipboard.writeText(\'' . h($url) . '\');this.textContent=\'已複製\';return false">複製連結</a></div>';
}

function item_html($it, $full){
    $url = SELF . '/' . $it['id'];
    $o = '<article class="gn-item"><div class="gn-meta"><b>' . h($it['cat']) . '</b>' . h($it['date']) . '</div>';
    $o .= $full ? '<h1>' . h($it['title']) . '</h1>' : '<h2><a href="' . h($url) . '">' . h($it['title']) . '</a></h2>';
    foreach($it['body'] as $p) $o .= '<p>' . h($p) . '</p>';
    if(!empty($it['links'])){
        $ls = array();
        foreach($it['links'] as $l) $ls[] = '<a href="' . h(SITE . $l['url']) . '">' . h($l['title']) . '</a>';
        $o .= '<div class="gn-more">📜 故事館延伸閱讀：' . implode('・', $ls) . '</div>';
    }
    $o .= '<div class="gn-src">資料來源：' . h($it['src']) . '〈<a href="' . h($it['url']) . '" target="_blank" rel="noopener nofollow">' . h($it['title_en']) . '</a>〉' . h($it['date']) . '</div>';
    return $o . share($url, $it['title']) . '</article>';
}

$all = news();
$path = trim(isset($_SERVER['PATH_INFO']) ? $_SERVER['PATH_INFO'] : '', '/');

/* ---------- RSS ---------- */
if($path === 'rss.xml'){
    header('Content-Type: application/rss+xml; charset=utf-8');
    echo '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>吉他新聞｜盧家宏《吉他故事館》</title><link>' . SELF . '</link><description>每天整理國際吉他新聞</description><language>zh-TW</language>';
    foreach(array_slice($all, 0, 40) as $it){
        echo '<item><title>' . h($it['title']) . '</title><link>' . h(SELF . '/' . $it['id']) . '</link><guid>' . h(SELF . '/' . $it['id']) . '</guid><pubDate>' . date(DATE_RSS, strtotime($it['when'])) . '</pubDate><description>' . h(implode("\n", $it['body'])) . '</description></item>';
    }
    echo '</channel></rss>';
    exit;
}

/* ---------- 內容 ---------- */
$one = null;
if($path !== ''){
    foreach($all as $it){ if($it['id'] === $path){ $one = $it; break; } }
    if(!$one) foreach(month_news(substr($path, 0, 7)) as $it){ if($it['id'] === $path){ $one = $it; break; } }
    if(!$one){ http_response_code(404); }
}
$mon = isset($_GET['m']) && preg_match('/^\d{4}-\d{2}$/', $_GET['m']) ? $_GET['m'] : '';
$cat = isset($_GET['c']) && in_array($_GET['c'], CATS, true) ? $_GET['c'] : '';
$pg = max(1, intval(isset($_GET['p']) ? $_GET['p'] : 1));
$list = $mon ? month_news($mon) : $all;
$list = $cat ? array_values(array_filter($list, function($i) use ($cat){ return $i['cat'] === $cat; })) : $list;

$side = '<aside class="gn-side"><div class="gn-box"><b>吉他新聞、故事館新文章第一時間看</b><br>加入盧家宏吉他音樂教室 LINE，有新文章就通知你。<br><a class="btn" href="https://line.me/ti/p/@434ttzne" target="_blank" rel="noopener">加入 LINE</a></div>'
      . '<h3>逛逛吉他故事館</h3><ol><li><a href="' . SITE . 'course-legends.html">世界百大吉他手</a></li><li><a href="' . SITE . 'course-songs.html">世界百大吉他名曲</a></li><li><a href="' . SITE . 'course-history.html">世界吉他歷史</a></li><li><a href="' . SITE . 'course-oddities.html">吉他奇聞軼事</a></li><li><a href="' . SITE . 'guitar-stories.html">故事館大廳</a></li></ol>';
$ms = months();
if($ms){
    $side .= '<h3>歷史新聞</h3><ul class="gn-months">';
    foreach($ms as $m) $side .= '<li><a href="' . SELF . '?m=' . h($m['month']) . '">' . intval(substr($m['month'], 0, 4)) . ' 年 ' . intval(substr($m['month'], 5)) . ' 月</a> <small>' . intval($m['count']) . ' 則</small></li>';
    $side .= '</ul>';
}
$side .= '</aside>';

$main = '<main class="gn">';
if($one){
    $title = $one['title'] . '｜吉他新聞';
    $desc = preg_match('/^.{0,110}/us', $one['body'][0], $mm) ? $mm[0] : '';   // 不靠 mbstring,主機沒裝也能跑
    $canon = SELF . '/' . $one['id'];
    $main .= '<nav class="gn-crumb"><a href="' . SITE . '">首頁</a> › <a href="' . SITE . 'guitar-stories.html">吉他故事館</a> › <a href="' . SELF . '">吉他新聞</a></nav>';
    $main .= '<div class="gn-grid"><div class="gn-one">' . item_html($one, true);
    $more = array_slice(array_values(array_filter($all, function($i) use ($one){ return $i['id'] !== $one['id']; })), 0, 6);
    $main .= '<h3 class="gn-h3">更多吉他新聞</h3><ul class="gn-list">';
    foreach($more as $m) $main .= '<li><a href="' . h(SELF . '/' . $m['id']) . '">' . h($m['title']) . '</a> <small>' . h($m['date']) . '</small></li>';
    $main .= '</ul></div>' . $side . '</div>';
    $ld = array('@context' => 'https://schema.org', '@type' => 'NewsArticle', 'headline' => $one['title'], 'datePublished' => $one['when'],
                'dateModified' => isset($one['added']) ? $one['added'] : $one['when'], 'inLanguage' => 'zh-TW', 'mainEntityOfPage' => $canon,
                'author' => array('@type' => 'Person', 'name' => '盧家宏'), 'publisher' => array('@type' => 'Organization', 'name' => '盧家宏吉他音樂教室'),
                'isBasedOn' => $one['url']);
} else {
    $mlabel = $mon ? intval(substr($mon, 0, 4)) . ' 年 ' . intval(substr($mon, 5)) . ' 月' : '';
    $title = $path !== '' ? '找不到這則新聞｜吉他新聞' : ($mon ? $mlabel . '吉他新聞｜歷史新聞' : ($cat ? $cat . '｜吉他新聞' : '吉他新聞：每天整理國際吉他新聞｜盧家宏《吉他故事館》'));
    $desc = '每天整理國際吉他新聞：新琴、器材、吉他手動態、名琴拍賣、效果器科技，繁體中文重點整理，附原文出處與吉他故事館延伸閱讀。';
    $canon = SELF . ($mon ? '?m=' . $mon : ($cat ? '?c=' . rawurlencode($cat) : ''));
    $upd = $all ? cn_date($all[0]['date']) : '';
    $main .= '<header class="gn-mast"><h1>吉他新聞<small>GUITAR NEWS · 吉他故事館</small></h1><p>每天整理國際吉他新聞・盧家宏 編撰' . ($upd ? '・最新 ' . $upd : '') . '</p></header>';
    if($mon) $main .= '<h2 class="gn-h3">歷史新聞：' . h($mlabel) . '（' . count($list) . ' 則）</h2>';
    $main .= '<ul class="gn-tags"><li><a' . ($cat || $mon ? '' : ' class="on"') . ' href="' . SELF . '">全部</a></li>';
    foreach(CATS as $c) $main .= '<li><a' . ($cat === $c ? ' class="on"' : '') . ' href="' . SELF . '?c=' . rawurlencode($c) . '">' . h($c) . '</a></li>';
    $main .= '</ul><div class="gn-grid"><div>';
    if($path !== '') $main .= '<p>找不到這則新聞，可能已下架。以下是最新吉他新聞：</p>';
    $chunk = array_slice($list, ($pg - 1) * PER_PAGE, PER_PAGE);
    if(!$chunk) $main .= '<p>新聞整理中，請稍後再來。</p>';
    foreach($chunk as $i => $it) $main .= ($i === 0 && $pg === 1 && !$cat && !$mon ? '<div class="gn-lead">' . item_html($it, false) . '</div>' : item_html($it, false));
    $q = ($mon ? 'm=' . $mon . '&' : '') . ($cat ? 'c=' . rawurlencode($cat) . '&' : '');
    $main .= '<nav class="gn-pages">' . ($pg > 1 ? '<a href="' . SELF . '?' . $q . 'p=' . ($pg - 1) . '">← 較新</a>' : '') . (count($list) > $pg * PER_PAGE ? '<a href="' . SELF . '?' . $q . 'p=' . ($pg + 1) . '">較舊 →</a>' : '') . '</nav>';
    $main .= '</div>' . $side . '</div>';
    $ld = array('@context' => 'https://schema.org', '@type' => 'CollectionPage', 'name' => '吉他新聞', 'url' => SELF, 'inLanguage' => 'zh-TW');
}
$main .= '</main>';

/* ---------- 套進網站外框(取 guitar-stories.html) ---------- */
$tpl = @file_get_contents(__DIR__ . '/guitar-stories.html');
if(!$tpl) $tpl = '<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>x</title><link rel="stylesheet" href="site.css"></head><body><div id="site-header"></div><main></main><div id="site-footer"></div><script src="partials.js"></script></body></html>';
$css = <<<'CSS'
.gn{max-width:1180px;margin:0 auto;padding:28px 16px 60px;color:var(--ink)}
.gn-mast{border-bottom:3px double var(--ink);padding-bottom:14px;margin-bottom:22px;display:flex;flex-wrap:wrap;align-items:flex-end;justify-content:space-between;gap:8px}
.gn-mast h1{font-family:var(--serif);font-size:clamp(30px,5vw,46px);margin:0;letter-spacing:.04em}
.gn-mast h1 small{display:block;font-size:13px;letter-spacing:.3em;color:var(--muted);font-family:var(--sans);margin-top:4px}
.gn-mast p{margin:0;color:var(--muted);font-size:14px}
.gn-tags{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 22px;padding:0;list-style:none}
.gn-tags a{display:inline-block;padding:6px 14px;border:1px solid var(--line);border-radius:999px;font-size:15px;text-decoration:none;color:var(--ink)}
@media(max-width:767px){.gn-tags{flex-wrap:nowrap;overflow-x:auto;scrollbar-width:none}.gn-tags li{flex:none}.gn-tags a{font-size:14px;padding:5px 12px}}
.gn-tags a.on{background:var(--ink);color:var(--bg);border-color:var(--ink)}
.gn-grid{display:grid;grid-template-columns:2fr 1fr;gap:28px}
@media(max-width:860px){.gn-grid{grid-template-columns:1fr}}
.gn-item{border-bottom:1px solid var(--line);padding:0 0 22px;margin:0 0 22px}
.gn-meta{font-size:14px;color:var(--muted);margin-bottom:6px}
.gn-meta b{display:inline-block;background:var(--gold);color:#222;font-weight:600;padding:1px 9px;border-radius:4px;margin-right:8px;font-size:13px}
.gn-item h2{font-family:var(--serif);font-size:clamp(21px,2.6vw,27px);line-height:1.4;margin:0 0 10px}
.gn-item h2 a{color:inherit;text-decoration:none}
.gn-lead .gn-item h2{font-size:clamp(25px,3.4vw,34px)}
.gn-item p{font-size:17px;line-height:1.85;margin:0 0 10px}
.gn-more{background:var(--bg-alt);border-left:4px solid var(--gold);padding:10px 14px;font-size:15.5px;line-height:1.7;margin:12px 0 8px}
.gn-more a{font-weight:600}
.gn-src{font-size:13px;color:var(--muted)}
.gn-share{display:flex;gap:8px;margin-top:10px}
.gn-share a{font-size:14px;padding:5px 12px;border-radius:6px;text-decoration:none;border:1px solid var(--line);color:var(--ink)}
.gn-share a.ln{background:var(--line-green);color:#fff;border-color:var(--line-green)}
.gn-side h3{font-family:var(--serif);font-size:19px;border-bottom:2px solid var(--ink);padding-bottom:6px;margin:0 0 12px}
.gn-side ol{padding-left:20px;margin:0 0 26px}
.gn-side li{margin:0 0 10px;font-size:16px;line-height:1.6}
.gn-box{background:var(--bg-alt);padding:16px;border-radius:var(--radius,10px);margin-bottom:26px;font-size:15.5px;line-height:1.7}
.gn-box a.btn{display:inline-block;margin-top:8px;background:var(--line-green);color:#fff;padding:8px 16px;border-radius:999px;text-decoration:none;font-weight:600}
.gn-crumb{font-size:14px;color:var(--muted);margin-bottom:16px}.gn-crumb a{color:inherit}
.gn-one h1{font-family:var(--serif);font-size:clamp(25px,3.6vw,36px);line-height:1.4;margin:0 0 14px}
.gn-h3{font-family:var(--serif);font-size:20px;margin:30px 0 10px}
.gn-list{padding-left:20px}.gn-list li{margin:0 0 10px;font-size:16.5px;line-height:1.6}.gn-list small{color:var(--muted)}
.gn-pages{display:flex;justify-content:space-between;margin-top:10px}.gn-pages a{font-weight:600}
.gn-src a{color:inherit}
.gn-months{list-style:none;padding:0;margin:0 0 26px}.gn-months li{margin:0 0 8px;font-size:16px}.gn-months small{color:var(--muted)}
CSS;
function rep($pat, $str, $tpl){ return preg_replace_callback($pat, function($m) use ($str){ return $str; }, $tpl, 1); }
$tpl = preg_replace('#<script type="application/ld\+json">.*?</script>#s', '', $tpl);
$tpl = rep('#<title>.*?</title>#s', '<title>' . h($title) . '</title>', $tpl);
$tpl = rep('#<meta name="description"[^>]*>#', '<meta name="description" content="' . h($desc) . '">', $tpl);
$tpl = rep('#<link rel="canonical"[^>]*>#', '<link rel="canonical" href="' . h($canon) . '">', $tpl);
$tpl = rep('#<meta property="og:title"[^>]*>#', '<meta property="og:title" content="' . h($title) . '">', $tpl);
$tpl = rep('#<meta property="og:description"[^>]*>#', '<meta property="og:description" content="' . h($desc) . '">', $tpl);
$tpl = rep('#<meta property="og:type"[^>]*>#', '<meta property="og:type" content="' . ($one ? 'article' : 'website') . '">', $tpl);
$tpl = preg_replace('#<meta property="og:url"[^>]*>#', '', $tpl);
$head = '<base href="' . SITE . '"><meta property="og:url" content="' . h($canon) . '"><link rel="alternate" type="application/rss+xml" title="吉他新聞" href="' . SELF . '/rss.xml">'
      . '<script type="application/ld+json">' . json_encode($ld, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES) . '</script><style>' . $css . '</style>';
$tpl = rep('#<head>#', '<head>' . $head, $tpl);
$a = strpos($tpl, '<main'); $b = strpos($tpl, '</main>');
if($a !== false && $b !== false) $tpl = substr($tpl, 0, $a) . $main . substr($tpl, $b + 7);
header('Content-Type: text/html; charset=utf-8');
header('Cache-Control: public, max-age=600');
echo $tpl;
