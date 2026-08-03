# Tasks

仕様書 28 節のフェーズ分割に沿った実装計画です。各 PR は小さく分け、スクリーンショット・動作確認手順・未実装点・設計判断を添えます（仕様書 31 節）。

- [x] 完了
- [ ] 未着手

---

## Phase 0 — 基盤 ✅

| | 項目 | 実装 |
| --- | --- | --- |
| [x] | モノレポ | npm workspaces。`apps/{api,mobile}`, `packages/{design-tokens,shared-types}` |
| [x] | CI | `.github/workflows/ci.yml` — API（lint / mypy / pytest / migration 適用）、TypeScript（typecheck / test）、fixture 再現性 |
| [x] | デザイントークン | `packages/design-tokens`。コントラスト・Reduce Motion・Dynamic Type をテストで検証 |
| [x] | 認証の最小実装 | `POST /auth/guest`、`GET /me`、`PATCH /me/settings`、`PUT /me/interests` |
| [x] | DB migrations | Alembic `0001_initial`（26 テーブル）。models との乖離をテストで検出 |
| [x] | Provider interfaces | 6 種の Protocol + mock 実装 2 種 + registry |
| [x] | サンプルデータ | 合成 60 件 + 重複変種 3 件。決定論的ジェネレータ |
| [x] | 重複排除 | DOI/arXiv/S2/OpenAlex/正規化タイトル。union-find で推移的統合 |
| [x] | 数式保護 | mask / restore / 欠落検査 / 選択境界の検証 |
| [x] | テスト | Python 141、TypeScript 42（単体・統合・E2E） |

### 仕様書 31 節「最初の実装タスク」の対応状況

| # | 項目 | 状態 |
| --- | --- | --- |
| 1 | Expo + FastAPI + shared packages のモノレポ | ✅ |
| 2 | PostgreSQL スキーマと migration | ✅ |
| 3 | `PaperProvider` と `MockPaperProvider` | ✅ |
| 4 | 50 件以上のサンプル Abstract | ✅ 合成 60 件（DECISIONS.md D-005） |
| 5 | オンボーディング 5 画面 | ✅ Phase 1-C |
| 6 | スワイプデッキ | ✅ Phase 1-C |
| 7 | ボタン操作と Undo | ✅ Phase 1-B/1-C |
| 8 | Saved の整然リスト | ✅ Phase 1-C |
| 9 | `TranslationProvider` と `MockTranslationProvider` | ✅（`POST /translations` まで通っている） |
| 10 | 英文選択 → ボトムシート | ✅ Phase 1-C（文単位。実機確認は 1-C の残タスク） |
| 11 | light/dark、Reduce Motion、Dynamic Type | ✅ 自動テストあり。実機確認は下記チェックリスト |
| 12 | 単体・統合・E2E とCI | ✅（モバイル UI の E2E は Phase 1-D） |

---

## Phase 1 — MVP

完了条件は仕様書 29 節。

### 1-A データソース接続 — 実装済み。疎通のみ未確認（DECISIONS.md D-016 / D-025）
> この開発環境はパッケージレジストリ以外への外向き接続を遮断しており、arXiv と OpenAlex に一度も到達できません（proxy が CONNECT を拒否）。そのため **パーサとクライアントは記録形状のレスポンスに対して完成させ、実 API への疎通だけを opt-in テストに切り出しています**。`PAPERMATCH_LIVE_PROVIDERS=1 pytest -m live` で、外向き接続のある環境から疎通を確認してください。fixture は公開スキーマから手で起こしたもので、構造は本物・中身は合成です（各ファイル冒頭に明記）。

- [x] `ArxivPaperProvider`（Atom API、3 秒間隔のレート制限、`arXiv:` 識別子、カテゴリ→分野マッピング、
      DOI 優先の canonical id、版番号の保持、journal_ref による published 判定）
- [x] `OpenAlexPaperProvider`（inverted index からの Abstract 復元、OA 状態、著者と ORCID、
      識別子統合、cursor ページング、論文ごとのライセンス判定）
- [x] Provider ごとのサーキットブレーカーとレート制限（仕様書 25 節）— `providers/http.py`。
      429 / 5xx はブレーカーを開き、それ以外の 4xx は開かない（自分側のクエリ不備で Provider を落とさない）
- [x] ライセンスの立場を明文化し、レコードに根拠 URL を同梱（DECISIONS.md D-025）
- [ ] **実 API への疎通確認**（`-m live`。この環境では実行不可）
- [x] **取り込み worker**（`services/worker.py`、`cli.py worker` / `cli.py runs`）—
      discovery（新着を追う・cursor を永続化）と refresh（撤回・版更新を取り込み直す）の 2 種類。
      再取得キューは `last_refreshed_at` で並べる（DECISIONS.md D-034）。
      provider が返さない論文を撤回扱いにしない、失敗した run の cursor を継がない、
      1 つの job の失敗が他を止めない、をテストで固定
- [ ] 実データ 100 件以上でフィードが構成できることの確認（仕様書 29 節）— worker と疎通が前提

### 1-B フィード API ✅
- [x] `GET /feed?mode=discover&cursor=` — 70/20/10 の枠配分、表示履歴による除外、推薦理由の付与
- [x] `POST /impressions` — 滞在時間を含む、再投稿は更新
- [x] `POST /actions` / `POST /actions/{id}/undo` / `GET /actions/undoable`
- [x] `GET /saved` / `POST|PATCH|DELETE /saved/{paperId}` — 7 種の並べ替え、状態・理由・分野での絞り込み
- [x] 再投入条件（期間経過 + スキップのみ + 長時間閲覧なし）
- [x] `hide_topic` / `hide_author`（action ログから導出、Undo で解除）
- [x] `actions.sequence`（migration 0002）— 「直前の action」を一意に決める

### 1-C モバイル UI ✅（一部は実機確認待ち）
- [x] オンボーディング 5 画面（分野 / 論文種別 / 英語 / 数式 / 冒険度）+ 「あとで設定する」
- [x] Abstract カード（仕様書 6 節のカード上部・本文・下部の全項目、推薦理由つき）
- [x] スワイプデッキ（Reanimated + Gesture Handler、左右上下）
- [x] **スワイプと等価なボタン**（同じハンドラを呼ぶ。テストで等価性を検証）
- [x] Undo トースト（サーバ確認前は無効、取り消すとカードがデッキ先頭に戻る）
- [x] 文単位の範囲選択 → 翻訳ボトムシート（段階タブつき、DECISIONS.md D-018）
- [x] Saved の整然リスト（並べ替えチップ、状態・保存理由の表示、解除）
- [x] 原文リンク（`expo-web-browser` で外部ブラウザ。WebView は使わない）
- [x] オフラインキャッシュ（AsyncStorage、フィード 20 件 + 保存一覧）
- [x] タブナビゲーション 4 面（Learn は Phase 2 と明示した空画面）
- [x] トークンを `expo-secure-store` へ（web ではメモリにフォールバック）
- [ ] **実機で文タップ選択を確認する** — web ブラウザでは選択・翻訳シートとも動作を確認済み
      （DECISIONS.md D-021 の訂正）。ただしマウスのクリックはタッチのジェスチャーではなく、
      Pan と tap が実際に競合するのはタッチ入力なので、実機確認は残しています。

### 1-D 品質
- [x] **TypeScript の lint（ESLint 9 + Prettier 3）** — `make lint` と CI の必須チェック。
      色リテラル禁止と画面間 import 禁止をプロジェクト固有ルールとして追加（DECISIONS.md D-026）
- [x] トークンを `expo-secure-store` へ移す（DECISIONS.md D-007）
- [ ] `saved` / `learn` / 翻訳シートのデータ取得を `@tanstack/react-query` へ移す —
      `react-hooks/set-state-in-effect` の指摘 3 件はこれが本来の直し方（DECISIONS.md D-026）。
      現状は行ごとの disable。オフライン時のキャッシュ・フォールバックを壊さないことが条件
- [ ] Maestro による E2E（オンボーディング / スワイプ / Undo / 範囲選択翻訳 / オフライン / VoiceOver 操作）
- [ ] Visual regression（light・dark / 小画面・大画面 / 日本語長文 / Dynamic Type / Reduce Motion）

---

## Phase 2 — 学習体験（AI 非依存部分は完了）

AI が要る項目は環境制約で未着手です（DECISIONS.md D-024）。

- [x] 段階ヒント 6 段階の UI（翻訳シートのタブ。中身の充実は実 Provider 接続後）
- [x] **Abstract 構造分類** — キューフレーズ + 位置による規則ベース。`heuristic` として保存し、
      fixture の `detectedBy: source` を正解データに一致率をテストで測定（平均 0.89 / 完全一致 34-60）
- [x] **用語・表現の保存**（`expression_cards`）— 単語 / 連語 / 構文 / 一文 の自動判定、
      文脈の保持、同一句のマージ
- [x] **Learn タブと復習の再提示** — 2 択・固定間隔・点数なし（DECISIONS.md D-023）
- [x] 翻訳シートからの「表現を保存」
- [ ] 実翻訳 Provider の接続（`ExplanationProvider` 含む）— ネットワーク遮断のため未着手
- [ ] Before you read（背景知識 3 項目、専門用語 3–5 項目）— AI 生成部分が必要
- [ ] Why it matters（AI 生成であることの明示）— 同上
- [x] **保存理由チップの UI**（`src/discover/saveReasons.ts`、`UndoToast.tsx`）— 保存は先に済み、
      タグは任意。既定の `interesting` はチップに出さず、どのタグを付けても残す。
      サーバが保存を確認するまでチップを出さない（未確定の行に PATCH を送らないため）
- [ ] 英語難易度の推定を実データで較正（実データ取得が Phase 1-A 待ち）

---

## Phase 3 — 推薦

- [x] **`EmbeddingProvider` 実装**（`providers/local_embedding.py`）— ハッシュ化 BoW、512 次元、
      L2 正規化。決定的で、ネットワークを必要としない（DECISIONS.md D-016）
- [x] **取り込み時にベクトルを保存**（`services/embeddings.py`）— フィードを読み取りのままに保つ。
      500 本のベクトルを、次のカードを待っている人の前で計算する取引はしない
- [x] **スコアリング**（`services/scoring.py`）— interest + quality + freshness + difficulty
      − similarity − author。**探索ボーナスは置かない**（DECISIONS.md D-032）
- [x] **フィードへの接続**（`services/feed.py`）— インラインの式を差し替え。理由の語彙はそのまま
- [x] 配合の既定値 70/20/10（仕様書 16 節）— Phase 1 で実装済み、今回も変えていない
- [x] **直近 20 件との類似ペナルティ**（埋め込みで測る）、**同一著者の連続抑制**（正規化キーで照合）
- [x] 推薦理由の文言生成（単一スコアを見せない）— Phase 1 で実装済み。スコアラーとは語彙が別
- [x] **フィード調整のフィードバック UI** — 16 節の 5 つすべて。うち 3 つは action type
      自体が無かったので追加（migration `0004`）。理論/実験の判定器も新規（DECISIONS.md D-033）
- [ ] pgvector 列と HNSW インデックスの migration（DECISIONS.md D-006）

> **いま interest の項が平らである件。** 種データでも実データでも、arXiv provider は主分野に一律
> 0.7、親に 0.2 を振ります（`providers/arxiv.py`）。興味の強さも既定が 1.0 です。したがって
> matched プールの中では interest が全員 0.7 になり、並び順は quality / difficulty / freshness と
> ペナルティで決まっています。**式のせいではなく上流のせい**で、強さを変えれば実際に刻まれること
> は確認済み（hep-th 1.0 → 0.700 / cs.LG 0.4 → 0.280）。差し替え前のインラインの式も同じ理由で
> 平らでした。分野の重みを本当に推定するのは分類器の仕事で、ここではありません。

---

## Phase 4 — 数式

### 4-A サーバ側の土台 ✅
- [x] **危険な LaTeX の判定**（`text/latex_safety.py`）— サニタイズではなく可否判定。
      仕様書 11 節「原式を勝手に変換しない」に従い、拒否した式もソースとして返す（DECISIONS.md D-027）
- [x] **機械的検証**（`mathcheck/`）— 数値代入と次元解析。式言語は AST で検証した算術のみ
- [x] **手動作成の数式カード** 5 枚（`fixtures/math-cards.json`）— 検証状態は fixture に書かず、
      取り込み時にチェックを走らせた結果を保存（DECISIONS.md D-028）
- [x] `Equation` / `EquationSymbol` / `DerivationStep` の投入経路（`services/math_content.py`）
- [x] **未検証の変形を既定で非表示**（仕様書 12 節）— 隠した件数は返すので、
      導出が完全であるかのように見えることはない
- [x] API — `GET /papers/{id}/equations`、`GET /math-cards`、`GET /math-cards/{id}`
- [x] **問題報告 `POST /math-cards/{id}/feedback`**（`services/reports.py`、migration `0006`）—
      読者の報告は `review_events`（判断）とは別テーブル。`verification_status` を動かさず、
      カードも隠さない。1 人 1 対象 1 理由につき 1 件（27 節の指標は「率」なので重複を数えない）。
      由来別に数えられる（AI 説明の問題報告率、DECISIONS.md D-038）

### 4-B レンダリング — 文書生成は完了。WebView 統合は実機確認待ち
- [x] **Abstract のインライン数式を組版**（`src/math/abstractDocument.ts`、`src/discover/AbstractBody.tsx`）—
      カード 1 枚につき文書 1 つ。文はタップ対象のまま、式ごとにレンダラを置かない。
      web は blob URL の iframe（`srcdoc` は CSP でスクリプトが走らない）。
      平文の経路はフォールバックとして残す（DECISIONS.md D-035）
- [x] **KaTeX をアプリに同梱**（`katexRuntime.ts`、woff2 20 面をデータ URI 化。ネットワーク 0 件を実測）
- [x] **数式をデータとしてのみ渡す** — `</script>` を含む式でも注入スクリプトが走らないことを実ブラウザで確認（DECISIONS.md D-029）
- [x] **MathML 併記**（`htmlAndMathml`）と、視覚側の `aria-hidden` — 同じ式を 2 回読み上げさせない
- [x] 失敗時の LaTeX ソース表示（仕様書 11 節のフォールバック）
- [x] Dynamic Type（式が本文と一緒に拡大する）、横スクロール、ライト/ダーク
- [x] `MathView` コンポーネント（高さの自動調整、ナビゲーション拒否、サーバが拒否した式は WebView を起動しない）
- [x] 実機確認用の画面 `/dev/math` — 7 ケースを 1 画面に並べ、各項目に「期待」と実測の高さを表示
- [ ] **実機で WebView を確認する — 保留中**（Expo Go で起動せず、原因を切り分けられなかった）
      > Android + Expo Go で、白画面のまま数秒でアプリが終了します。Metro にエラーは出ず、
      > 開発メニューも出ないため、JS 例外ではなくネイティブ側の問題と見ています。
      > ネイティブモジュールは `bundledNativeModules.json` と完全に一致させ
      > （gesture-handler 2.32、worklets 0.10.1 — DECISIONS.md D-030）、無限レンダリング
      > ループも直しましたが、症状は変わりませんでした。**adb か development build
      > （`npx expo run:android`）が使える環境で `FATAL EXCEPTION` を見るのが次の一手です。**
      > web ハーネスではアプリ全体が正常に動くので、切り分けは実機側に閉じています。

      復帰したら `/dev/math` を開いて以下を確認（DECISIONS.md D-029）:
      - [ ] 1〜4 が組版され、枠の高さが式に合っている（上下が切れていたら高さ通知が効いていない）
      - [ ] 3 が右端で切れず横スクロールできる
      - [ ] 5 が LaTeX ソース + 警告文になる（空白にならない）
      - [ ] 7 でアラートが出ない／レイアウトが崩れない
      - [ ] テーマ切り替えで背景が白く残らない（Android の透過 WebView）
      - [ ] VoiceOver / TalkBack が各式をラベルとして読み上げる（マークアップを読み上げない）
      - [ ] 機内モードでも組版される（同梱の確認）
- [ ] MathJax へのフォールバック — 同梱で約 1MB 増。KaTeX が扱えない構文の大半はサーバ側で
      弾いており、信頼上効いているのはソース表示（実装済み）なので後回し
- [ ] タップで全画面、LaTeX コピー

### 4-C Focus Mode ✅（実機確認は 4-B と同じく保留）
- [x] 記号 / 構造 / 導出 / 意味 / 極限 の 5 タブ（`app/math/[id].tsx`）
- [x] 導出の Step 表示 — 式の間に操作・検証状態・「なぜ?」を置く
- [x] **詳細度** 4 段階 — 最短は両端の式 + 省略件数、初学者向けは「なぜ?」を最初から開く。
      どのレベルも保存されていない step を作らない（DECISIONS.md D-031）
- [x] 記号タップ（この論文での意味 / 一般的な意味 / 単位 / 適用スコープ / 由来ラベル）
- [x] **理解チェック** — カードの導出から組み立てる 次の一手。誤答の選択肢は同じカードの
      他の操作。結果は文のみで点数を出さない（仕様書 10 節）
- [x] **極限タブ** — 各変形が実際に確認された範囲と次元。evidence の無い step には何も書かない
- [x] 未検証の変形の非表示と、隠した件数の明示（仕様書 12 節）
- [x] Learn タブからの入口（仕様書 10 節の「Learnから復習」）
- [ ] 矢印タップで中間式を開く — 中間式は Phase 5 の自動パイプラインが作るもので、
      いまのコーパスには存在しません。作れば捏造になります
- [ ] 通知 / Discover への低頻度混入 / Canvas タイル（それぞれ通知基盤・推薦・Canvas 待ち）

---

## Phase 5 — 自動数式パイプライン

- [ ] `FullTextProvider`（許諾済み LaTeX / XML のみ）
- [ ] 式・定義・仮定の抽出、記号表の構築
- [ ] 中間変形候補の生成
- [ ] `MathVerifier`（数式処理 / 数値代入 / 次元解析 / 極限）
- [ ] 検証状態の付与と、未検証の既定非表示
- [ ] 人手レビューキュー（`review_events`）

---

## Phase 6 — Canvas

- [ ] Mosaic レイアウト
- [ ] 安定座標（新規追加で全体を再配置しない、手動配置を尊重、レイアウト版を保持）
- [ ] 分野の知覚的グラデーション（RGB 単純平均を避ける）
- [ ] 選択時の浮遊と周辺の強調
- [ ] Library との連続変形（Reduce Motion ではフェード）
- [ ] フィルターとクラスタズーム

---

## Phase 7 — 高度探索

- [ ] Constellation / Landscape / Spectrum
- [ ] 論文関係（基礎 / 対立 / 後続 / 類似）と根拠の保持
- [ ] 目的別読書ルート
- [ ] Timeline 再生
- [ ] 数式知識グラフ
- [ ] 共有画像の書き出し（私的メモを既定で除外）

---

## 実機確認チェックリスト（各 PR で実施）

自動テストで代替できない項目です。

- [ ] ライトテーマ / ダークテーマの両方で全画面を確認
- [ ] iOS の文字サイズを最大にして、見切れ・重なりが無いこと
- [ ] Reduce Motion を有効にして、連続変形が短いフェードになること
- [ ] VoiceOver / TalkBack でフォーカス順序が論理的であること
- [ ] すべてのジェスチャーにボタンの代替があること
- [ ] 色を除いても状態が区別できること（グレースケールで確認）
- [ ] 機内モードでキャッシュ済みカードが表示されること
- [ ] 依存を変えたら実機で起動を確認する（Expo Go のネイティブ不一致は白画面で出る — DECISIONS.md D-030）
- [ ] 数式が実機の WebView で組版され、高さが正しく、VoiceOver が MathML を読むこと

---

## 既知の未対応事項

| 項目 | 状況 |
| --- | --- |
| データ取得の effect | `saved` / `learn` / 翻訳シートは react-query へ移すべき（DECISIONS.md D-026） |
| 実データ Provider | 実装済み。実 API への疎通のみ未確認（`-m live`、DECISIONS.md D-016 / D-025） |
| 取り込み worker | 実装済み（`cli.py worker`）。実 API に対して回したことはまだない |
| 文タップ選択の実機確認 | web ブラウザでは動作確認済み。タッチ入力での Pan/tap 競合は未確認（D-021 訂正） |
| Discover の下スワイプ | 「Before you read」は Phase 2。現状は無反応 |
| モバイルの E2E | Phase 1-D（Maestro）。Phase 0 の E2E は API レベル |
| pgvector 列 | Phase 3（DECISIONS.md D-006） |
| レート制限 | Provider 側は実装済み（`providers/http.py`）。API 側の呼び出し元制限は未実装 |
| 観測性 | 構造化ログ・トレース・Provider レイテンシ指標は未実装。27 節の指標は `cli.py metrics` で集計できる |
| クライアント計測 | クラッシュ率・ジェスチャー失敗率（27 節のガードレール）を送る仕組みが無い |
| 数式カード完了率 | 「完了」を記録するイベントが無いので算出できない（27 節） |
| 数式の LaTeX 解析 | チェックは著者が並記した機械可読形に対して行う。LaTeX 本体との食い違いは検出できない（D-028） |
| AI 説明・実翻訳 | 環境がネットワークを遮断（DECISIONS.md D-024）。interface は Phase 0 から存在 |
