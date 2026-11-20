// =====================================================================
// 「ジモ君に聞く」の設定（ここだけ書きかえます）
//
//   endpoint ：Edge Function の URL
//              https://（プロジェクトID）.supabase.co/functions/v1/hojokin-ask
//   key      ：公開用の鍵（Publishable key か anon public の鍵）
//
// ※ 公開用の鍵は、GitHub に上げても大丈夫です。
// ※ Claude の API キー（ANTHROPIC_API_KEY）や service_role の鍵は、
//    ぜったいにここに書かないでください。Supabase の Secrets にだけ置きます。
// =====================================================================
window.HOJOKIN_AI = {
  endpoint: "https://mtctyeezzycwqoyfjdmd.supabase.co/functions/v1/hojokin-ask",
  key: "sb_publishable_ZUDkLIqizJXlLmHA7xw_Fw_QWBKy_vy"
};
