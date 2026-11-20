-- =====================================================================
-- 補助金サイト「ジモ君に聞く」：質問と回答を記録するテーブル
-- Supabase の「SQL Editor」に全部貼り付けて「Run」を1回押します。
-- 何回実行しても大丈夫です。便利サイトのテーブルや設定には触りません。
-- （revoke があるので注意の画面が出ますが、データは消えません）
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. 質問と回答を記録するテーブル
--    保存するのは「質問・回答・日時・うまくいったか・使ったAI」だけ。
--    IPアドレスなど、人を特定できる情報は保存しない。
-- ---------------------------------------------------------------------
create table if not exists public.hojokin_questions (
  id         bigint generated always as identity primary key,
  created_at timestamptz not null default now(),
  question   text not null check (char_length(question) between 1 and 200),
  answer     text,
  status     text not null default 'ok' check (status in ('ok', 'error')),
  model      text
);

comment on table public.hojokin_questions is '補助金サイトのAI質問（ジモ君）の記録。status: ok=回答できた、error=AIにつながらなかった';

-- 回数の制限（1分に何回・1日に何回）を数えるときに速くするための目次
create index if not exists hojokin_questions_created_at on public.hojokin_questions (created_at);

-- ---------------------------------------------------------------------
-- 2. RLS をオンにする。ルール（policy）は作らない。
--    → 画面（公開用の鍵）からは、だれも読めないし、書けない。
--    → 書きこむのは Edge Function（service_role）だけ。
--    → れおさんは、ダッシュボードの Table Editor で読める。
-- ---------------------------------------------------------------------
alter table public.hojokin_questions enable row level security;

-- ---------------------------------------------------------------------
-- 3. 権限（GRANT）
--    ログインなしの人（anon）とログインした人（authenticated）には何も許可しない。
--    Edge Function が使う service_role にだけ、読む・書くを許可する。
-- ---------------------------------------------------------------------
revoke all on public.hojokin_questions from anon, authenticated;
grant select, insert on public.hojokin_questions to service_role;
