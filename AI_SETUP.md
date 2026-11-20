# ジモ君に聞く（AI質問機能）の設定と仕組み

補助金サイトに、AIの「ジモ君」が質問に答える欄を足しました。
ジモ君は、このサイトの補助金データ（`data/subsidies.json`）の中のことだけを根拠に、やさしい鹿児島弁で答えます。

## 追加したファイル

| ファイル | 置き場所 | 中身 |
| --- | --- | --- |
| `index.html` | GitHub | 質問欄、マイクボタン、回答の表示（上書き） |
| `ai-config.js` | GitHub | Edge Function の URL と公開用の鍵（ここだけ書きかえる） |
| `supabase/hojokin_setup.sql` | Supabase の SQL Editor に貼る | 質問を記録するテーブル `hojokin_questions` |
| `supabase/functions/hojokin-ask/index.ts` | Supabase の Edge Function に貼る | ジモ君の本体（キャラ設定・制限・Claude への問い合わせ・記録） |

便利サイトのテーブル（requests、admins）や設定には触りません。補助金サイト用のものには、すべて `hojokin` を付けています。

## Supabase のダッシュボードで操作する手順

便利サイトと同じプロジェクトを開いてから、上から順に進めます。

1. **テーブルを作る**
   - 左のメニュー「SQL Editor」を開く
   - `supabase/hojokin_setup.sql` の中身を全部貼り付けて「Run」
   - 「Potential issue detected」が出たら「Run query」（revoke が入っているため。データは消えません）
   - 「Table Editor」に `hojokin_questions` ができていれば成功
2. **APIキーを確かめる**
   - 左のメニュー「Edge Functions」→「Secrets」を開く
   - `ANTHROPIC_API_KEY` があることを確かめる（登録ずみなので、何もしなくてよい）
   - `SUPABASE_URL` と `SUPABASE_SERVICE_ROLE_KEY` は Supabase が自動で用意するので、足さない
3. **Edge Function を作って公開する**
   - 「Edge Functions」→「Deploy a new function」→「Via Editor」
   - 関数の名前を `hojokin-ask` にする
   - 最初から入っているコードを全部消し、`supabase/functions/hojokin-ask/index.ts` の中身を全部貼り付ける
   - 「Deploy function」を押す
4. **JWT の確認をオフにする**
   - できた `hojokin-ask` を開き、「Details」（または Settings）にある「Verify JWT（Enforce JWT verification）」をオフにして保存
   - 理由：公開用の鍵（`sb_publishable_` で始まる鍵）は JWT ではないので、オンのままだと画面から呼べません。守りは Edge Function の中（文字数・回数の制限、呼んでよいサイトの確認）で行っています
5. **動くか試す**
   - `hojokin-ask` の画面の「Test」を押し、Method を POST、Body に `{"question":"創業の補助金はありますか？"}` を入れて「Send Request」
   - ジモ君の答え（`answer`）が返ってくればOK。「Table Editor」の `hojokin_questions` にも1行増える
6. **URL をコピーする**
   - `hojokin-ask` の画面に出ている URL（`https://（プロジェクトID）.supabase.co/functions/v1/hojokin-ask`）をコピーする
7. **ai-config.js に書く**
   - `endpoint` にコピーした URL、`key` に便利サイトの `config.js` と同じ公開用の鍵を書く
8. **GitHub に上げる**
   - `index.html`、`ai-config.js`、`supabase` フォルダ、`AI_SETUP.md` をアップロードする（`data` フォルダはそのまま）
9. **使いすぎ防止（おすすめ）**
   - Anthropic Console（console.anthropic.com）の「Limits」で、月の使用額の上限を決めておく

## 使いすぎ対策

| 対策 | 場所 | 中身 |
| --- | --- | --- |
| 200文字まで | 画面と Edge Function | 画面を通さずに送られても、Edge Function で断る |
| 続けて送れない | 画面 | 1回送ったら30秒待つ |
| サイト全体の上限 | Edge Function | 1分に10回、1日（日本時間）に300回まで |
| 呼んでよいサイト | Edge Function | ブラウザからは `https://reou913.github.io` のページからだけ |

数字は `index.ts` の上の「設定」で変えられます（変えたら、Edge Function に貼り直して Deploy）。

「同じ人」をサーバー側で見分けるには IP アドレスなどを保存する必要があるため、今回は保存しない方針に合わせて、画面の30秒制限と、サイト全体の上限の2段構えにしています。

## iPhone で音声入力を確かめる方法

1. iPhone の **Safari** でサイトを開く（LINE や Instagram の中のブラウザでは、マイクボタンが出ません）
2. 質問欄の右上にマイクボタンが出ているか見る
3. マイクボタンを押す → 「マイクへのアクセス」を聞かれたら「許可」
4. 「空き家の補助金はある？」などと話す → 質問欄に文字が入れば成功
5. 「聞いてみる」を押して、ジモ君が答えるか見る

**うまくいかないとき**

| 症状 | 確かめること |
| --- | --- |
| マイクボタンが出ない | Safari で開いているか。iOS が古くないか（「設定」→「一般」→「情報」） |
| 「マイクが使えません」と出る | Safari のアドレスバーの「ぁあ」→「Webサイトの設定」→「マイク」を「許可」。または「設定」→「アプリ」→「Safari」→「マイク」 |
| 押しても聞き取らない | 「設定」→「Siri」や、キーボードの「音声入力」がオンか |
| ホーム画面に追加したアイコンから開くと動かない | ホーム画面のアプリ表示では使えないことがある。Safari で開く |

**どのブラウザでも使える代わりの方法**：キーボードのマイク（音声入力）ボタンを押して話すと、質問欄に文字が入ります。

**くわしく調べたいとき**：iPhone の「設定」→「アプリ」→「Safari」→「詳細」→「Webインスペクタ」をオンにし、Mac とケーブルでつなぐと、Mac の Safari の「開発」メニューから、iPhone で起きているエラーを見られます。

## 質問の記録を見る

- 「Table Editor」→ `hojokin_questions` で、質問・回答・日時が見られます
- `status` が `error` の行は、AI につながらなかったものです。「Edge Functions」→ `hojokin-ask` →「Logs」で理由を見られます
- 記録はサイトの改善（よく聞かれる質問を一覧に足すなど）に使います。画面からはだれも読めません

## データの流れ（仕組み）

```
① 利用者が質問を書く（またはマイクで話す）
      ↓
② 画面（index.html）が、Edge Function（hojokin-ask）に質問だけを送る
      ↓
③ Edge Function が確かめる：200文字以内か、1分・1日の上限をこえていないか
      ↓
④ Edge Function が GitHub Pages から subsidies.json を読み、答えに必要な項目だけの短い一覧にする
      ↓
⑤ Edge Function が Claude（claude-haiku-5-5）に送る
      ・ジモ君の設定とルール（データにないことは答えない など）
      ・補助金の一覧
      ・質問
   このとき、Secrets にしまった ANTHROPIC_API_KEY を使う（画面からは見えない）
      ↓
⑥ Claude の答えを受け取り、最後の一文がなければ足す
      ↓
⑦ 質問・回答・日時を hojokin_questions に記録する（IPアドレスなどは保存しない）
      ↓
⑧ 画面に答えを表示する（答えはただの文字として表示し、https のURLだけリンクにする）
```

**大事なポイント**
- Claude の APIキーは Supabase の Secrets にだけあり、画面のコードにも GitHub にもありません
- 補助金データは、画面からではなく Edge Function が自分で取りに行くので、書きかえたデータを送られる心配がありません
- 補助金データは毎回同じなので、Claude の「プロンプトキャッシュ」で安く送っています。料金は Anthropic Console の「Usage」で確かめられます

## ジモ君の設定を変えるとき

`index.ts` の上の方にある `CHARACTER` の文章を書きかえて、Edge Function に貼り直して Deploy します。
「データにないことは答えない」「最後に確認の一文を付ける」などのルールは、消さないでください。
