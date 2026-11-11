# 薩摩川内市 補助金・助成金さがし

薩摩川内市と川内商工会議所のホームページを巡回して、補助金・助成金の一覧を作るWebアプリです。
GitHub Actions が毎週月曜の朝7時に自動で巡回し、一覧を新しくします。

## ファイルの構成

```
index.html                    一覧ページ（キーワード検索・だれ向け・分野で絞り込み）
data/subsidies.json           集めた補助金の一覧（巡回するたびに書きかわる）
sources.json                  巡回するページのリスト
scripts/crawl.py              巡回するスクリプト（Pythonの標準機能だけで動く）
.github/workflows/crawl.yml   毎週自動で巡回するための設定（GitHub Actions）
```

## 公開と自動巡回のはじめかた

1. 新しいリポジトリを作り（Public）、この中身をすべてアップロードする
   - `.github` フォルダは名前が「.」で始まるため、パソコンによっては表示されません。見えないときは、Codespaces で作業するか、Claude Code に「.github/workflows/crawl.yml を作って」と頼みます
2. 「Settings」→「Pages」で、Branch を `main`、フォルダを `/(root)` にして「Save」
3. 「Settings」→「Actions」→「General」の一番下「Workflow permissions」を「Read and write permissions」にして「Save」
4. 「Actions」タブ →「補助金情報を巡回」→「Run workflow」を押して、1回目を手動で動かす
5. 緑のチェックになったら完了。次からは毎週月曜に自動で動きます

## 手動で巡回する（Codespaces）

```bash
python3 scripts/crawl.py              # いつもの巡回（3〜5分）
python3 scripts/crawl.py --no-details # 一覧ページだけ読む（数十秒）
```

終わったら `git add .` → `git commit -m "補助金情報を更新"` → `git push` で公開ページに反映します。

## 巡回するページを増やす

`sources.json` に1つ足します。

```json
{
  "id": "city-kosodate",
  "name": "薩摩川内市「子育て支援」",
  "org": "薩摩川内市",
  "url": "https://www.city.satsumasendai.lg.jp/〇〇/index.html",
  "link_pattern": "/〇〇/\\d+\\.html$",
  "keyword_filter": true,
  "priority": 5
}
```

- `link_pattern`：そのページの中から拾うリンクのURLの形です。市のサイトは「フォルダ名/数字.html」の形なので、上の書き方で拾えます
- `keyword_filter`：`true` にすると、見出しに「補助」「助成」「支援」などが入っているリンクだけを拾います
- `priority`：同じ補助金が複数のページに載っているとき、数字が小さいページのURLを使います

形がわからないときは、Claude Code に「このURLのページから補助金のリンクを拾えるように sources.json に追加して」と頼むのが早いです。

## 自動で読み取っているもの

| 項目 | 読み取り方 |
| --- | --- |
| 受付状況 | 見出しの【募集中】【受付終了】【随時受付中】など。書いていないものは「要確認」 |
| だれ向け・分野 | 見出しの言葉から自動で付けた目安（`crawl.py` の `TARGET_RULES`、`CATEGORY_RULES`） |
| ページ更新日・受付期間 | 各補助金のページの「更新日」「受付期間」「申請期限」などの文字 |
| 新着 | 初めて見つけてから30日以内のもの |

読み取りは機械的なので、まちがうことがあります。ページにも「申し込む前に必ずリンク先で確かめてください」と表示しています。

## 相手のサイトへの配慮

- robots.txt で禁止されているページは開きません
- 1ページ開くごとに2.5秒あけ、1回の巡回で開くページは最大150件です
- 巡回は週1回にしています。回数を増やしすぎないようにしてください

## うまくいかないとき

| 症状 | 対処 |
| --- | --- |
| Actions が赤い×になる | 「Workflow permissions」が「Read and write」になっているか確認する |
| 一覧が「前回は読み込めませんでした」になる | 市のサイトの一時的な不調か、ページの場所が変わった可能性。URLを開いて確かめ、変わっていたら `sources.json` を直す |
| 件数が急に減った | ページのつくりが変わった可能性。Claude Code に `crawl.py` の出力を見せて相談する |
| 自動巡回が止まった | GitHub は、60日間なにも変更がないリポジトリの自動実行を止めることがあります。「Actions」タブで「Enable workflow」を押す |

## 出典

- [薩摩川内市「市が交付する補助金」](https://www.city.satsumasendai.lg.jp/gyoseijoho/hojokin/1/index.html)
- [薩摩川内市「補助金・助成金（雇用・就業）」](https://www.city.satsumasendai.lg.jp/shigoto_sangyo/koyo_shugyo/202405221/index.html)
- [薩摩川内市「企業・商工事業者支援」](https://www.city.satsumasendai.lg.jp/shigoto_sangyo/chikikeizai-chusyokigyo/1/index.html)
- [薩摩川内市「移住・定住 助成・支援」](https://www.city.satsumasendai.lg.jp/ijuteiju/iju_shien/josei_shien/index.html)
- [川内商工会議所「各種補助金」](https://sendai-cci.jp/index.php/news/zyosei/)
