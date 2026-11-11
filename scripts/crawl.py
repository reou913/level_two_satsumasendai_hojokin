"""薩摩川内市の補助金・助成金を集めて、一覧ページ用のファイルを作るスクリプト。

使い方
  python3 scripts/crawl.py               いつもの巡回（各補助金のページも開いて、締切・金額・更新日を読む）
  python3 scripts/crawl.py --no-details  一覧ページだけ読む（速い。締切や金額は前回の値のまま）

作るファイル
  data/subsidies.json   補助金の一覧、セミナー・相談会、巡回の結果
  data/history.json     「新しく載った」「受付終了になった」などの変更の記録
  feed.xml              新着のRSS（ニュースアプリなどで受け取れる）

巡回するページは sources.json に書いてあります。追加のインストールは不要です。

相手のサーバーに負担をかけないためのルール
  ・robots.txt で「見ないで」と書かれたページは開かない
  ・1ページ開くごとに数秒あける
  ・1回の巡回で開くページの数に上限をつける
"""

import argparse
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import date, datetime, timedelta, timezone
from html import escape
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES_FILE = ROOT / "sources.json"
DATA_FILE = ROOT / "data" / "subsidies.json"
HISTORY_FILE = ROOT / "data" / "history.json"
FEED_FILE = ROOT / "feed.xml"

JST = timezone(timedelta(hours=9))
USER_AGENT = "satsumasendai-subsidy-list/2.0 (+GitHub Pages; weekly crawl)"
DELAY_SECONDS = 2.5      # 1ページごとにあける秒数
MAX_DETAIL_PAGES = 200   # 1回の巡回で開く補助金ページの上限
TIMEOUT = 30
HISTORY_KEEP = 300       # 変更の記録を残す件数
DROP_ALERT_RATIO = 0.5   # 件数が前回のこの割合より少なくなったら知らせる

# 補助金・助成金らしいリンクを見分ける言葉
INCLUDE_WORDS = ["補助", "助成", "支援", "奨励金", "給付", "交付金", "利子", "保証料", "保証制度", "奨学金",
                 "報奨", "手当", "医療費", "応援券"]
# 補助金そのものではないお知らせを外す言葉
EXCLUDE_WORDS = ["採択団体", "を決定しました", "制度移行", "あってよかった", "成果発表会", "相談窓口",
                 "届出について", "一覧", "支援センター", "支援戦略", "計画"]

# 分野（タグ）を決める言葉。1つの補助金に複数つくことがある
CATEGORY_RULES = [
    ("住まい・空き家", ["住宅", "リフォーム", "空き家", "廃屋", "ブロック塀", "耐震", "がけ地", "宅地", "井戸", "下水道"]),
    ("移住・定住", ["移住", "定住", "UIJ", "移定住", "Uターン", "ふるさと就職"]),
    ("子育て・結婚・学び", ["子育て", "結婚", "婚活", "キッズ", "通学", "高校生", "赤ちゃん", "就学", "保育", "児童", "子ども", "産後", "養育", "出産"]),
    ("仕事・人材", ["就職", "求人", "人材", "奨学金", "合同企業", "退職金", "研修", "就業", "就労", "雇用", "人手不足"]),
    ("創業・お店", ["創業", "出店", "店舗", "改装", "中心市街地", "移動販売", "チャレンジ", "起業"]),
    ("企業・経営", ["企業立地", "中小企業", "DX", "保証", "利子", "事業承継", "海外展開", "設備", "販路", "持続化",
                 "ものづくり", "にぎわい", "経済循環", "省力化", "生産性", "IT導入", "デジタル", "賃上げ", "輸出"]),
    ("観光", ["観光", "インバウンド"]),
    ("農林水産", ["漁業", "農地", "森林", "農業", "林業", "水産", "六次", "農商工", "農林", "畜産"]),
    ("環境・エネルギー", ["環境", "蓄電", "ZEH", "省エネ", "地球", "脱炭素", "再生可能", "EV", "カーボン"]),
    ("地域・市民活動", ["市民活動", "スポーツ", "文化", "閉校", "地域づくり"]),
    ("福祉・健康", ["高齢者", "見守り", "ターミナルケア", "介護", "障害", "医療", "福祉"]),
    ("防災", ["災害", "危険", "がけ地", "耐震", "土砂", "防災"]),
]

# 対象（だれ向けか）の目安。上から順に調べ、最初に当てはまったもの
TARGET_RULES = [
    ("団体向け", ["団体", "市民活動", "婚活イベントを実施", "スポーツ振興", "文化振興"]),
    ("事業者向け", ["事業者", "企業", "店舗", "創業", "出店", "建設業", "観光業", "漁業", "求人", "合同企業",
                 "立地", "DX", "保証", "退職金", "海外展開", "移動販売", "設備", "販路", "持続化",
                 "ものづくり", "にぎわい", "経済循環", "事業承継", "駐車場", "受入施設", "赤ちゃんの駅",
                 "スマイルキッズ", "利子", "六次", "農商工", "加工機械", "省力化", "生産性", "IT導入", "賃上げ"]),
]

STATUS_ORDER = {"募集中": 0, "要確認": 1, "受付終了": 2, "過去のお知らせ": 3}


# ===== HTML を読む部品 =====
class LinkParser(HTMLParser):
    """<a href="...">文字</a> を集める（ページ上部のメニューや下のフッターの中のリンクは除く）"""

    SKIP = {"header", "nav", "footer", "aside"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self._href, self._text, self._skip = [], None, [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "a" and not self._skip:
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "a" and self._href is not None:
            text = " ".join("".join(self._text).split())
            self.links.append((self._href, text))
            self._href = None


class TextParser(HTMLParser):
    """ページの本文の文字を取り出す（メニューやスクリプトは除く）"""

    SKIP = {"script", "style", "nav", "header", "footer", "noscript", "form"}
    BLOCK = {"p", "div", "li", "tr", "td", "th", "br", "h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd",
             "section", "article", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)

    def text(self):
        lines = [" ".join(l.split()) for l in "".join(self.parts).splitlines()]
        return "\n".join(l for l in lines if l)


# ===== ネットワーク =====
class Fetcher:
    def __init__(self):
        self.robots = {}
        self.last = 0.0
        self.count = 0

    def allowed(self, url):
        host = urllib.parse.urlsplit(url)
        base = f"{host.scheme}://{host.netloc}"
        if base not in self.robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                req = urllib.request.Request(base + "/robots.txt", headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
                    rp.parse(res.read().decode("utf-8", "replace").splitlines())
            except Exception:
                rp.parse([])  # robots.txt がない・読めないときは制限なしとして扱う
            self.robots[base] = rp
        return self.robots[base].can_fetch(USER_AGENT, url)

    def raw(self, url, accept="text/html"):
        if not self.allowed(url):
            raise PermissionError(f"robots.txt で禁止されています：{url}")
        wait = DELAY_SECONDS - (time.time() - self.last)
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "ja", "Accept": accept})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
                return res.read(), res.headers.get_content_charset()
        finally:
            self.last = time.time()
            self.count += 1

    def get(self, url):
        return decode(*self.raw(url))

    def get_json(self, url):
        body, charset = self.raw(url, accept="application/json")
        return json.loads(body.decode(charset or "utf-8"))


def decode(raw, charset=None):
    head = raw[:2000].decode("ascii", "ignore")
    m = re.search(r'charset=["\']?([\w-]+)', head, re.I)
    for enc in [charset, m.group(1) if m else None, "utf-8", "cp932"]:
        if not enc:
            continue
        try:
            return raw.decode(enc)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "replace")


# ===== 文字の整理と分類 =====
def nfkc(s):
    return unicodedata.normalize("NFKC", s or "").strip()


BRACKET = re.compile(r"[【\[]([^】\]]{1,30})[】\]]")


def split_title(text):
    """「【募集中】○○補助金」→ ("○○補助金", ["募集中"])"""
    labels = BRACKET.findall(text)
    title = BRACKET.sub("", text).strip(" 　")
    return title, labels


def title_key(title):
    """同じ補助金かどうかを比べるための形（空白や記号の違いをなくす）"""
    t = nfkc(title)
    t = re.sub(r"[\s・･「」『』()（）<>＜＞〈〉!！?？、。,.]", "", t)
    return t


def is_subsidy(title):
    t = nfkc(title)
    return any(w in t for w in INCLUDE_WORDS) and not any(w in t for w in EXCLUDE_WORDS)


def categories_of(title):
    t = nfkc(title)
    cats = [name for name, words in CATEGORY_RULES if any(nfkc(w) in t for w in words)]
    return cats or ["その他"]


def target_of(title, default="個人・家庭向け"):
    t = nfkc(title)
    for name, words in TARGET_RULES:
        if any(nfkc(w) in t for w in words):
            return name
    return default


def same_site(a, b):
    """www. のあり・なしを同じサイトとして扱う"""
    strip = lambda u: urllib.parse.urlsplit(u).netloc.lower().removeprefix("www.")
    return strip(a) == strip(b)


def canonical(url):
    """URLから「?」や「#」より後ろを取り、www. をそろえた形（同じページかどうかを比べるため）"""
    p = urllib.parse.urlsplit(url)
    return f"{p.netloc.lower().removeprefix('www.')}{p.path}"


# ===== 日付・金額の読み取り =====
ERA = {"令和": 2018, "平成": 1988}
DATE_RE = re.compile(r"(?:(令和|平成)\s*(元|[0-9]{1,2})\s*年|([0-9]{4})\s*年)?\s*([0-9]{1,2})\s*月\s*([0-9]{1,2})\s*日")
DATE_LABELED = re.compile(r"(更新日|掲載日|公開日|最終更新日)\s*[:：]?\s*([0-9]{4})年\s*([0-9]{1,2})月\s*([0-9]{1,2})日")
DATE_ANY = re.compile(r"([0-9]{4})年\s*([0-9]{1,2})月\s*([0-9]{1,2})日")
PERIOD = re.compile(r"(受付期間|募集期間|申請期間|申込期間|申請期限|受付期限|提出期限|募集期限|申込期限|締切|〆切)\s*[:：]?\s*([^\n。]{4,80})")
UNTIL = re.compile(r"((?:令和\s*(?:元|[0-9]{1,2})\s*年|[0-9]{4}\s*年)?\s*[0-9]{1,2}\s*月\s*[0-9]{1,2}\s*日)\s*(?:\([^)]{1,3}\))?\s*(?:[0-9]{1,2}\s*時\s*)?(?:まで|必着|締切)")
AMOUNT = re.compile(r"(上限|限度額|最大|補助上限|補助金額|補助額|助成額|助成金額|交付額|支給額)[^。\n]{0,25}?([0-9][0-9,]*(?:\.[0-9]+)?\s*(?:億|万|千)?\s*円)")
RATE = re.compile(r"([0-9]+)\s*分の\s*([0-9]+)|([0-9]+(?:\.[0-9]+)?)\s*%")


def to_iso(y, m, d):
    try:
        return date(int(y), int(m), int(d)).isoformat()
    except (ValueError, TypeError):
        return None


def dates_in(text, base_year):
    """文の中の日付をすべて西暦にする。年がないものは、直前の日付の年（なければ base_year）を使う"""
    out, year = [], base_year
    for era, ey, y4, m, d in DATE_RE.findall(nfkc(text)):
        if era:
            year = ERA[era] + (1 if ey == "元" else int(ey))
        elif y4:
            year = int(y4)
        iso = to_iso(year, m, d)
        if iso:
            out.append(iso)
    return out


def read_detail(raw_text, org, today):
    """補助金のページの本文から、更新日・受付期間・締切・金額・補助率を探す"""
    text = nfkc(raw_text)
    info = {}
    m = DATE_LABELED.search(text)
    if m:
        info["updated"] = to_iso(m.group(2), m.group(3), m.group(4))
    elif org != "薩摩川内市":
        m = DATE_ANY.search(text)
        if m:
            info["updated"] = to_iso(*m.groups())
    base_year = int((info.get("updated") or today)[:4])

    p = PERIOD.search(text)
    if p:
        info["period"] = (p.group(1) + "：" + p.group(2).strip(" 　:：")).strip()
        if re.search(r"随時|通年", p.group(2)):
            info["deadline_note"] = "随時"
        found = dates_in(p.group(2), base_year)
        if found:
            info["deadline"] = found[-1]
    if "deadline" not in info:
        for line in text.splitlines():
            if re.search(r"受付|申請|申込|募集|提出", line):
                u = UNTIL.search(line)
                if u:
                    found = dates_in(u.group(1), base_year)
                    if found:
                        info["deadline"] = found[-1]
                        info.setdefault("period", line[:80])
                        break
    # 年が書いていない締切が、更新日より前になったときは翌年とみなす
    if info.get("deadline") and info.get("updated") and info["deadline"] < info["updated"] and not re.search(r"(令和|平成|[0-9]{4})\s*(元|[0-9]*)\s*年", info.get("period", "")):
        d = date.fromisoformat(info["deadline"])
        info["deadline"] = d.replace(year=d.year + 1).isoformat()

    a = AMOUNT.search(text)
    if a:
        label = "上限" if a.group(1) in ("上限", "限度額", "最大", "補助上限") else a.group(1)
        unit = re.search(r"月額|年額|1人あたり|1件あたり", a.group(0))
        info["amount"] = f"{label} {unit.group(0) if unit else ''}{re.sub(r'[ 　]', '', a.group(2))}".replace("上限 ", "上限")
    for line in text.splitlines():
        if re.search(r"補助率|助成率|分の", line) and re.search(r"補助|助成|経費", line):
            r = RATE.search(line)
            if r:
                info["rate"] = f"{r.group(1)}分の{r.group(2)}" if r.group(1) else f"{r.group(3)}%"
                break
    return info


def yen_text(v):
    """1000000 → 上限100万円"""
    try:
        v = int(float(v))
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    if v >= 100_000_000 and v % 10_000_000 == 0:
        return f"上限{v / 100_000_000:g}億円"
    if v >= 10_000:
        return f"上限{v / 10_000:,.0f}万円" if v % 10_000 == 0 else f"上限{v / 10_000:,.1f}万円"
    return f"上限{v:,}円"


def status_of(item, today):
    joined = " ".join(item.get("labels", []))
    deadline = item.get("deadline")
    passed = bool(deadline and deadline < today)
    if item.get("source_type") == "jgrants":
        return "受付終了" if passed else "募集中"
    if re.search(r"募集中|受付中|随時", joined):
        return "要確認" if passed else "募集中"
    if re.search(r"終了|締切|しめきり", joined):
        return "受付終了"
    if passed:
        return "受付終了"
    if item["org"] != "薩摩川内市" and item.get("updated"):
        if item["updated"] < (date.fromisoformat(today) - timedelta(days=365)).isoformat():
            return "過去のお知らせ"
    return "要確認"


# ===== 巡回 =====
def collect_links(html, page_url, pattern, fetcher=None):
    lp = LinkParser()
    lp.feed(html)
    found, seen = [], set()
    for href, text in lp.links:
        if not href or not text:
            continue
        url = urllib.parse.urljoin(page_url, href).split("#")[0]
        parts = urllib.parse.urlsplit(url)
        if not same_site(url, page_url) or not re.search(pattern, parts.path):
            continue
        if canonical(url).rstrip("/") == canonical(page_url).rstrip("/") or canonical(url) in seen:
            continue
        if fetcher and not fetcher.allowed(url):
            continue  # robots.txt で禁止されたページは一覧にも載せない
        seen.add(canonical(url))
        found.append((url.split("?")[0] if not parts.query else url, text))
    return found


def crawl_list(src, fetcher):
    """ホームページの一覧ページから、補助金のリンクを拾う"""
    links, errors = [], []
    for page in [src["url"]] + src.get("extra_pages", []):
        try:
            links += collect_links(fetcher.get(page), page, src["link_pattern"], fetcher)
        except Exception as e:
            errors.append(f"{type(e).__name__}: {e}")
            print(f"  ! 読めませんでした：{page}（{errors[-1]}）")
    items = []
    for url, text in links:
        title, labels = split_title(text)
        if not title or (src.get("keyword_filter", True) and not is_subsidy(title)):
            continue
        items.append({"title": title, "labels": labels, "url": url,
                      "categories": categories_of(title), "target": target_of(title)})
    ok = not errors or bool(links)
    return items, ok, "; ".join(errors) or None


def crawl_jgrants(src, fetcher):
    """Jグランツ（国の補助金API）から、鹿児島県・全国が対象で受付中のものを取る"""
    items, seen, errors, any_ok = [], set(), [], False
    for kw in src.get("keywords", ["補助"]):
        q = urllib.parse.urlencode({"keyword": kw, "sort": "acceptance_end_datetime", "order": "ASC", "acceptance": "1"})
        try:
            data = fetcher.get_json(f"{src['url']}?{q}")
            any_ok = True
        except Exception as e:
            errors.append(f"{kw}: {type(e).__name__}: {e}")
            print(f"  ! Jグランツ（{kw}）を読めませんでした：{errors[-1]}")
            continue
        rows = data.get("result") or data.get("results") or []
        for r in rows:
            rid = str(r.get("id") or "")
            if not rid or rid in seen:
                continue
            area = nfkc(str(r.get("target_area_search") or ""))
            if not any(a in area for a in src.get("areas", ["鹿児島", "全国"])):
                continue
            seen.add(rid)
            title = nfkc(r.get("title") or r.get("name") or "")
            if not title:
                continue
            end = str(r.get("acceptance_end_datetime") or "")[:10] or None
            items.append({
                "title": title,
                "labels": [],
                "url": src.get("page_url", "https://www.jgrants-portal.go.jp/subsidy/{id}").format(id=rid),
                "categories": categories_of(title),
                "target": target_of(title, default="事業者向け"),
                "amount": yen_text(r.get("subsidy_max_limit")),
                "deadline": end,
                "period": f"受付終了：{end.replace('-', '/')}" if end else None,
                "area": "全国" if "全国" in area else area,
                "institution": r.get("institution_name") or None,
            })
    return items, any_ok, "; ".join(errors) or None


def crawl_events(src, fetcher, today, old_events):
    """セミナー・相談会のお知らせを拾う"""
    old = {e["url"]: e for e in old_events}
    try:
        links = collect_links(fetcher.get(src["url"]), src["url"], src["link_pattern"], fetcher)
    except Exception as e:
        print(f"  ! 読めませんでした：{src['url']}（{type(e).__name__}）")
        return [e for e in old_events if e.get("source") == src["id"]], False, f"{type(e).__name__}: {e}"
    events = []
    for url, text in links[: src.get("max_items", 12)]:
        title, _ = split_title(text)
        ev = {"title": title, "url": url, "org": src["org"], "source": src["id"],
              "first_seen": old.get(url, {}).get("first_seen", today), "posted": old.get(url, {}).get("posted")}
        if not ev["posted"]:
            try:
                tp = TextParser()
                tp.feed(fetcher.get(url))
                m = DATE_ANY.search(nfkc(tp.text()))
                if m:
                    ev["posted"] = to_iso(*m.groups())
            except Exception:
                pass
        events.append(ev)
    return events, True, None


# ===== 変更の記録・RSS =====
def record_history(history, old_items, new_items, ok_sources, first_run_sources, today):
    old_by = {title_key(i["title"]): i for i in old_items}
    new_by = {title_key(i["title"]): i for i in new_items}
    events = []
    for key, item in new_by.items():
        src = item["sources"][0]
        prev = old_by.get(key)
        if not prev:
            if src not in first_run_sources:
                events.append(("新しく載りました", item))
        elif prev.get("status") != item["status"]:
            if item["status"] == "受付終了":
                events.append(("受付終了になりました", item))
            elif item["status"] == "募集中":
                events.append(("募集が始まりました", item))
    for key, item in old_by.items():
        if key not in new_by and set(item.get("sources", [])) & ok_sources:
            events.append(("一覧から外れました", item))
    for kind, item in events:
        history.insert(0, {"date": today, "type": kind, "title": item["title"], "url": item["url"], "org": item["org"]})
    return history[:HISTORY_KEEP], len(events)


def write_feed(items, history, site_url, now):
    """新着のRSSを作る"""
    entries = [h for h in history if h["type"] in ("新しく載りました", "募集が始まりました")][:30]
    if not entries:  # 記録がまだないときは、締切が近い募集中のものを載せる
        entries = [{"date": i.get("first_seen"), "type": "募集中", "title": i["title"], "url": i["url"], "org": i["org"]}
                   for i in items if i["status"] == "募集中"][:30]
    def rfc822(iso):
        d = datetime.fromisoformat(iso or now.date().isoformat()).replace(tzinfo=JST)
        return d.strftime("%a, %d %b %Y %H:%M:%S +0900")
    body = "".join(f"""
    <item>
      <title>{escape(e['type'] + '：' + e['title'])}</title>
      <link>{escape(e['url'])}</link>
      <guid isPermaLink="false">{escape((e.get('date') or '') + e['url'])}</guid>
      <pubDate>{rfc822(e.get('date'))}</pubDate>
      <description>{escape(e['org'])}</description>
    </item>""" for e in entries)
    FEED_FILE.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>薩摩川内市 補助金・助成金さがし（新着）</title>
    <link>{escape(site_url)}</link>
    <description>薩摩川内市・川内商工会議所・Jグランツから集めた補助金・助成金の新着です。申し込む前に必ずリンク先で確かめてください。</description>
    <language>ja</language>
    <lastBuildDate>{now.strftime('%a, %d %b %Y %H:%M:%S +0900')}</lastBuildDate>{body}
  </channel>
</rss>
""", encoding="utf-8")


def site_url():
    if os.environ.get("SITE_URL"):
        return os.environ["SITE_URL"]
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner.lower()}.github.io/{name}/"
    return ""


# ===== 全体の流れ =====
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-details", action="store_true", help="補助金ごとのページは開かない")
    args = ap.parse_args()

    now = datetime.now(JST)
    today = now.date().isoformat()
    sources = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))["sources"]
    prev = json.loads(DATA_FILE.read_text(encoding="utf-8")) if DATA_FILE.exists() else {}
    old_items = prev.get("items", [])
    old = {title_key(i["title"]): i for i in old_items}
    old_meta = prev.get("meta", {})
    history = json.loads(HISTORY_FILE.read_text(encoding="utf-8")) if HISTORY_FILE.exists() else []

    fetcher = Fetcher()
    found, events, source_status = {}, [], []
    first_run = dict(old_meta.get("source_first_run", {}))
    sources_with_old = {s for i in old_items for s in i.get("sources", [])}

    for src in sorted(sources, key=lambda s: s.get("priority", 9)):
        kind = src.get("type", "list")
        if kind == "events":
            evs, ok, err = crawl_events(src, fetcher, today, prev.get("events", []))
            events += evs
            source_status.append({"id": src["id"], "name": src["name"], "url": src["url"], "type": kind,
                                  "ok": ok, "count": len(evs), "error": err})
            print(f"{src['name']}：{len(evs)}件")
            continue
        if kind == "jgrants":
            got, ok, err = crawl_jgrants(src, fetcher)
        else:
            got, ok, err = crawl_list(src, fetcher)
        if src["id"] not in sources_with_old and src["id"] not in first_run and got:
            first_run[src["id"]] = today   # この巡回先を初めて読んだ日（この日に見つけたものは「新着」にしない）
        kept = 0
        for g in got:
            key = title_key(g["title"])
            if key in found:
                if src["id"] not in found[key]["sources"]:
                    found[key]["sources"].append(src["id"])
                continue
            p = old.get(key, {})
            item = {
                "title": g["title"], "labels": g["labels"], "url": g["url"], "org": src["org"],
                "source_type": kind, "sources": [src["id"]],
                "categories": g["categories"], "target": g["target"],
                "first_seen": p.get("first_seen", today), "last_seen": today,
            }
            for f in ("updated", "period", "deadline", "deadline_note", "amount", "rate", "checked"):
                if g.get(f) is not None:
                    item[f] = g[f]
                elif p.get(f) is not None and kind != "jgrants":
                    item[f] = p[f]
            for f in ("area", "institution"):
                if g.get(f):
                    item[f] = g[f]
            if kind == "jgrants":
                item["checked"] = today
            found[key] = item
            kept += 1
        source_status.append({"id": src["id"], "name": src["name"], "url": src["url"], "type": kind,
                              "ok": ok, "count": kept, "error": err})
        print(f"{src['name']}：{kept}件" + ("" if ok else "（読み込み失敗）"))

    # 読み込みに失敗した巡回先は、前回の結果を残す（一時的なエラーで一覧が消えないように）
    failed = {s["id"] for s in source_status if not s["ok"]}
    for key, item in old.items():
        if key not in found and set(item.get("sources", [])) & failed:
            found[key] = item

    # 補助金ごとのページを開いて、締切・金額・更新日を読む（Jグランツは一覧に入っているので開かない）
    if not args.no_details:
        targets = [i for i in found.values() if i["last_seen"] == today and i.get("source_type") != "jgrants"][:MAX_DETAIL_PAGES]
        print(f"補助金のページを {len(targets)} 件読みます（1件あたり約{DELAY_SECONDS}秒）")
        for n, item in enumerate(targets, 1):
            try:
                tp = TextParser()
                tp.feed(fetcher.get(item["url"]))
                for f in ("deadline", "deadline_note", "amount", "rate", "period"):
                    item.pop(f, None)   # ページが変わったときに古い値が残らないように
                item.update({k: v for k, v in read_detail(tp.text(), item["org"], today).items() if v})
                item["checked"] = today
            except Exception as e:
                print(f"  ! {item['title']}：{type(e).__name__}")
            if n % 20 == 0:
                print(f"  {n}/{len(targets)}")

    for item in found.values():
        item["status"] = status_of(item, today)

    items = sorted(found.values(), key=lambda i: (STATUS_ORDER.get(i["status"], 9),
                                                  {"薩摩川内市": 0, "川内商工会議所": 1}.get(i["org"], 2),
                                                  i.get("deadline") or "9999", i["title"]))

    ok_sources = {s["id"] for s in source_status if s["ok"]}
    history, changes = record_history(history, old_items, items, ok_sources, {k for k, v in first_run.items() if v == today}, today)

    # 異常を知らせる：巡回先が読めない、件数が急に減った
    alerts = [f"「{s['name']}」を読み込めませんでした（{s['error']}）" for s in source_status if not s["ok"]]
    prev_counts = {s["id"]: s.get("count", 0) for s in old_meta.get("sources", [])}
    for s in source_status:
        before = prev_counts.get(s["id"], 0)
        if s["ok"] and before >= 6 and s["count"] < before * DROP_ALERT_RATIO:
            alerts.append(f"「{s['name']}」の件数が {before}件 → {s['count']}件 に減りました。ページのつくりが変わった可能性があります")

    events.sort(key=lambda e: e.get("posted") or e["first_seen"], reverse=True)
    out = {
        "meta": {
            "updated": now.isoformat(timespec="minutes"),
            "initial": old_meta.get("initial", today),
            "source_first_run": first_run,
            "count": len(items),
            "sources": source_status,
            "alerts": alerts,
        },
        "items": items,
        "events": events,
    }
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_feed(items, history, site_url(), now)
    print(f"保存しました：{len(items)}件（変更 {changes}件、セミナー {len(events)}件、開いたページ {fetcher.count}件）")
    for a in alerts:
        print(f"  ⚠ {a}")

    # Actions に「知らせることがあるか」を伝える
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as f:
            f.write(f"alert_count={len(alerts)}\n")
        Path(ROOT / ".alerts.md").write_text("\n".join(f"- {a}" for a in alerts) + "\n", encoding="utf-8") if alerts else None

    if failed and len(failed) == len(sources):
        sys.exit("すべての巡回先が読めませんでした。ネットワークかURLを確認してください。")


if __name__ == "__main__":
    main()
