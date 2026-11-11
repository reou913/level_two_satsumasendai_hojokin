"""薩摩川内市の補助金・助成金のページを巡回して、data/subsidies.json を作るスクリプト。

使い方
  python3 scripts/crawl.py               いつもの巡回（各補助金のページも開いて、更新日や受付期間を読む）
  python3 scripts/crawl.py --no-details  一覧ページだけ読む（速い。更新日や受付期間は前回の値のまま）

巡回するページは sources.json に書いてあります。
追加のインストールは不要です（Python の標準機能だけで動きます）。

相手のサーバーに負担をかけないためのルール
  ・robots.txt で「見ないで」と書かれたページは開かない
  ・1ページ開くごとに数秒あける
  ・1回の巡回で開くページの数に上限をつける
"""

import argparse
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES_FILE = ROOT / "sources.json"
DATA_FILE = ROOT / "data" / "subsidies.json"

JST = timezone(timedelta(hours=9))
USER_AGENT = "satsumasendai-subsidy-list/1.0 (+GitHub Pages; weekly crawl)"
DELAY_SECONDS = 2.5      # 1ページごとにあける秒数
MAX_DETAIL_PAGES = 150   # 1回の巡回で開く補助金ページの上限
TIMEOUT = 30

# 補助金・助成金らしいリンクを見分ける言葉
INCLUDE_WORDS = ["補助", "助成", "支援", "奨励金", "給付", "交付金", "利子", "保証料", "保証制度", "奨学金", "報奨"]
# 補助金そのものではないお知らせを外す言葉
EXCLUDE_WORDS = ["採択団体", "を決定しました", "制度移行", "あってよかった", "成果発表会", "相談窓口", "届出について", "一覧"]

# 分野（タグ）を決める言葉。1つの補助金に複数つくことがある
CATEGORY_RULES = [
    ("住まい・空き家", ["住宅", "リフォーム", "空き家", "廃屋", "ブロック塀", "耐震", "がけ地", "宅地", "井戸", "下水道"]),
    ("移住・定住", ["移住", "定住", "UIJ", "移定住", "Uターン", "ふるさと就職"]),
    ("子育て・結婚・学び", ["子育て", "結婚", "婚活", "キッズ", "通学", "高校生", "赤ちゃん", "就学", "保育"]),
    ("仕事・人材", ["就職", "求人", "人材", "奨学金", "合同企業", "退職金", "研修", "就業", "就労"]),
    ("創業・お店", ["創業", "出店", "店舗", "改装", "中心市街地", "移動販売", "チャレンジ"]),
    ("企業・経営", ["企業立地", "中小企業", "DX", "保証", "利子", "事業承継", "海外展開", "設備", "販路", "持続化", "ものづくり", "にぎわい", "経済循環"]),
    ("観光", ["観光"]),
    ("農林水産", ["漁業", "農地", "森林", "農業", "林業", "水産"]),
    ("環境・エネルギー", ["環境", "蓄電", "ZEH", "省エネ", "地球"]),
    ("地域・市民活動", ["市民活動", "スポーツ", "文化", "閉校"]),
    ("福祉・健康", ["高齢者", "見守り", "ターミナルケア", "介護", "障害"]),
    ("防災", ["災害", "危険", "がけ地", "耐震", "土砂"]),
]

# 対象（だれ向けか）の目安。上から順に調べ、最初に当てはまったもの
TARGET_RULES = [
    ("団体向け", ["団体", "市民活動", "婚活イベントを実施", "スポーツ振興", "文化振興"]),
    ("事業者向け", ["事業者", "企業", "店舗", "創業", "出店", "建設業", "観光業", "漁業", "求人", "合同企業",
                 "立地", "DX", "保証", "退職金", "海外展開", "移動販売", "設備投資", "販路", "持続化",
                 "ものづくり", "にぎわい", "経済循環", "事業承継", "駐車場", "受入施設", "赤ちゃんの駅", "スマイルキッズ", "利子"]),
]

DATE_LABELED = re.compile(r"(更新日|掲載日|公開日|最終更新日)\s*[:：]?\s*(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日")
DATE_ANY = re.compile(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日")
PERIOD = re.compile(r"(受付期間|募集期間|申請期間|申請期限|受付期限|提出期限|募集期限|締切|〆切)\s*[:：]?\s*([^\n。]{4,70})")


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
    BLOCK = {"p", "div", "li", "tr", "br", "h1", "h2", "h3", "h4", "h5", "h6", "dt", "dd", "section", "article", "table"}

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

    def get(self, url):
        if not self.allowed(url):
            raise PermissionError(f"robots.txt で禁止されています：{url}")
        wait = DELAY_SECONDS - (time.time() - self.last)
        if wait > 0:
            time.sleep(wait)
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "ja"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
                raw = res.read()
                charset = res.headers.get_content_charset()
        finally:
            self.last = time.time()
            self.count += 1
        return decode(raw, charset)


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


def status_of(labels, org, posted):
    joined = " ".join(labels)
    if re.search(r"募集中|受付中|随時", joined):
        return "募集中"
    if re.search(r"終了|締切|しめきり", joined):
        return "受付終了"
    if org != "薩摩川内市" and posted:
        try:
            if datetime.fromisoformat(posted).date() < (datetime.now(JST) - timedelta(days=365)).date():
                return "過去のお知らせ"
        except ValueError:
            pass
    return "要確認"


def is_subsidy(title):
    t = nfkc(title)
    return any(w in t for w in INCLUDE_WORDS) and not any(w in t for w in EXCLUDE_WORDS)


def categories_of(title):
    t = nfkc(title)
    cats = [name for name, words in CATEGORY_RULES if any(nfkc(w) in t for w in words)]
    return cats or ["その他"]


def target_of(title):
    t = nfkc(title)
    for name, words in TARGET_RULES:
        if any(nfkc(w) in t for w in words):
            return name
    return "個人・家庭向け"


def to_iso(y, m, d):
    try:
        return datetime(int(y), int(m), int(d)).date().isoformat()
    except ValueError:
        return None


def read_detail(text, org):
    """補助金のページの本文から、更新日・受付期間を探す"""
    info = {}
    m = DATE_LABELED.search(text)
    if m:
        info["updated"] = to_iso(m.group(2), m.group(3), m.group(4))
    elif org != "薩摩川内市":
        m = DATE_ANY.search(text)
        if m:
            info["updated"] = to_iso(*m.groups())
    p = PERIOD.search(text)
    if p:
        info["period"] = (p.group(1) + "：" + p.group(2).strip(" 　:：")).strip()
    return info


# ===== 巡回 =====
def canonical(url):
    """URLから「?」や「#」より後ろを取った形（同じページかどうかを比べるため）"""
    p = urllib.parse.urlsplit(url)
    return f"{p.scheme}://{p.netloc}{p.path}"


def collect_links(html, page_url, pattern, fetcher=None):
    lp = LinkParser()
    lp.feed(html)
    found, seen = [], set()
    page_host = urllib.parse.urlsplit(page_url).netloc
    for href, text in lp.links:
        if not href or not text:
            continue
        url = urllib.parse.urljoin(page_url, href).split("#")[0]
        parts = urllib.parse.urlsplit(url)
        if parts.netloc != page_host or not re.search(pattern, parts.path):
            continue
        if canonical(url).rstrip("/") == canonical(page_url).rstrip("/") or canonical(url) in seen:
            continue
        if fetcher and not fetcher.allowed(url):
            continue  # robots.txt で禁止されたページは一覧にも載せない
        seen.add(canonical(url))
        found.append((canonical(url) if not parts.query else url, text))
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-details", action="store_true", help="補助金ごとのページは開かない")
    args = ap.parse_args()

    sources = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))["sources"]
    old = {}
    old_meta = {}
    if DATA_FILE.exists():
        prev = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        old = {title_key(i["title"]): i for i in prev.get("items", [])}
        old_meta = prev.get("meta", {})

    today = datetime.now(JST).date().isoformat()
    fetcher = Fetcher()
    found = {}          # title_key → item
    source_status = []

    for src in sorted(sources, key=lambda s: s.get("priority", 9)):
        pages = [src["url"]] + src.get("extra_pages", [])
        links, error = [], None
        for page in pages:
            try:
                html = fetcher.get(page)
                links += collect_links(html, page, src["link_pattern"], fetcher)
            except Exception as e:  # 1ページ失敗しても、ほかは続ける
                error = f"{type(e).__name__}: {e}"
                print(f"  ! 読めませんでした：{page}（{error}）")
        kept = 0
        seen_urls = {canonical(i["url"]) for i in found.values()}
        for url, text in links:
            if canonical(url) in seen_urls and title_key(split_title(text)[0]) not in found:
                continue  # 同じページへの別の名前のリンク
            seen_urls.add(canonical(url))
            title, labels = split_title(text)
            if not title or (src.get("keyword_filter", True) and not is_subsidy(title)):
                continue
            key = title_key(title)
            if key in found:
                if src["id"] not in found[key]["sources"]:
                    found[key]["sources"].append(src["id"])
                continue
            prev = old.get(key, {})
            found[key] = {
                "title": title,
                "labels": labels,
                "url": url,
                "org": src["org"],
                "sources": [src["id"]],
                "categories": categories_of(title),
                "target": target_of(title),
                "updated": prev.get("updated"),
                "period": prev.get("period"),
                "first_seen": prev.get("first_seen", today),
                "last_seen": today,
            }
            kept += 1
        ok = error is None or bool(links)
        source_status.append({"id": src["id"], "name": src["name"], "url": src["url"],
                              "ok": ok, "count": kept, "error": error})
        print(f"{src['name']}：{kept}件" + ("" if ok else "（読み込み失敗）"))

    # 読み込みに失敗した巡回先は、前回の結果を残す（一時的なエラーで一覧が消えないように）
    failed = {s["id"] for s in source_status if not s["ok"]}
    for key, item in old.items():
        if key not in found and set(item.get("sources", [])) & failed:
            found[key] = item

    # 補助金ごとのページを開いて、更新日・受付期間を読む
    if not args.no_details:
        targets = [i for i in found.values() if i["last_seen"] == today][:MAX_DETAIL_PAGES]
        print(f"補助金のページを {len(targets)} 件読みます（1件あたり約{DELAY_SECONDS}秒）")
        for n, item in enumerate(targets, 1):
            try:
                tp = TextParser()
                tp.feed(fetcher.get(item["url"]))
                item.update({k: v for k, v in read_detail(tp.text(), item["org"]).items() if v})
            except Exception as e:
                print(f"  ! {item['title']}：{type(e).__name__}")
            if n % 20 == 0:
                print(f"  {n}/{len(targets)}")

    for item in found.values():
        item["status"] = status_of(item.get("labels", []), item["org"], item.get("updated"))

    order = {"募集中": 0, "要確認": 1, "受付終了": 2, "過去のお知らせ": 3}
    items = sorted(found.values(), key=lambda i: (order.get(i["status"], 9), i["org"] != "薩摩川内市", i["title"]))

    out = {
        "meta": {
            "updated": datetime.now(JST).isoformat(timespec="minutes"),
            "initial": old_meta.get("initial", today),
            "count": len(items),
            "sources": source_status,
        },
        "items": items,
    }
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"保存しました：{DATA_FILE}（{len(items)}件、開いたページ {fetcher.count}件）")

    if failed and len(failed) == len(sources):
        sys.exit("すべての巡回先が読めませんでした。ネットワークかURLを確認してください。")


if __name__ == "__main__":
    main()
