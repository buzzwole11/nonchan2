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

### 1-A データソース接続 — 未着手（環境制約、DECISIONS.md D-016）
> この開発環境はパッケージレジストリ以外への外向き接続を遮断しており、arXiv と OpenAlex に一度も到達できません。実レスポンスに対して動かせないコードを完了扱いにしないため、次のスライスに送っています。実装時は記録済みレスポンス（Atom XML / OpenAlex JSON）に対するオフラインテストを本体とし、疎通確認は手動手順として残します。

- [ ] `ArxivPaperProvider`（Atom API、レート制限、`arXiv:` 識別子、カテゴリ→分野マッピング）
- [ ] `OpenAlexPaperProvider`（候補発見、OA 状態、著者、識別子統合）
- [ ] Provider ごとのサーキットブレーカーとキャッシュ（仕様書 25 節）
- [ ] 取り込み worker（定期実行、撤回・版更新の同期）
- [ ] 実データ 100 件以上でフィードが構成できることの確認（仕様書 29 節）

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
- [ ] **実機で文タップ選択を確認する** — web ビルドでは react-native-gesture-handler が
      ポインタを横取りするため未確認（DECISIONS.md D-021）。タップハンドラ自体は
      コンポーネントテストで担保済み。

### 1-D 品質
- [ ] Maestro による E2E（オンボーディング / スワイプ / Undo / 範囲選択翻訳 / オフライン / VoiceOver 操作）
- [ ] Visual regression（light・dark / 小画面・大画面 / 日本語長文 / Dynamic Type / Reduce Motion）
- [x] トークンを `expo-secure-store` へ移す（DECISIONS.md D-007）
- [ ] TypeScript の lint（ESLint + Prettier）。Phase 0 では tsc のみで、スタイル統一は未整備

---

## Phase 2 — 学習体験

- [ ] 段階ヒント 6 段階の UI（難語 / 骨格 / 句構造 / 直訳 / 自然訳 / 分野的意味）
- [ ] 実翻訳 Provider の接続（`ExplanationProvider` 含む）
- [ ] Abstract 構造分類（AI 判定ラベル付き。fixture の `detectedBy: source` を正解データとして評価）
- [ ] Before you read（背景知識 3 項目、専門用語 3–5 項目）
- [ ] Why it matters（AI 生成であることの明示）
- [ ] 用語・表現の保存（`expression_cards`）
- [ ] 保存理由チップ
- [ ] Learn タブと復習の再提示
- [ ] 英語難易度の推定を実データで較正

---

## Phase 3 — 推薦

- [ ] `EmbeddingProvider` 実装
- [ ] pgvector 列と HNSW インデックスの migration（DECISIONS.md D-006）
- [ ] スコアリング（interest + quality + freshness + difficulty + exploration − similarity − author）
- [ ] 配合の既定値 70/20/10（仕様書 16 節）
- [ ] 直近 20 件との類似ペナルティ、同一著者・同一テーマの連続抑制
- [ ] 推薦理由の文言生成（単一スコアを見せない）
- [ ] フィード調整のフィードバック UI

---

## Phase 4 — 数式

- [ ] KaTeX / MathJax の WebView レンダラとフォールバック
- [ ] `Equation` / `EquationSymbol` の投入経路
- [ ] 人手で作成した検証済み数式カード
- [ ] Focus Mode（記号 / 構造 / 導出 / 意味 / 極限）
- [ ] 詳細度スライダーと Why? ボタン
- [ ] 理解チェック
- [ ] MathML 併記とスクリーンリーダー用説明
- [ ] 危険な LaTeX 入力のサニタイズテスト

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

---

## 既知の未対応事項

| 項目 | 状況 |
| --- | --- |
| TypeScript の lint | tsc のみ。ESLint / Prettier は Phase 1-D で導入 |
| 実データ Provider | Phase 1-A。環境がネットワークを遮断（DECISIONS.md D-016） |
| web での文タップ選択 | RNGH の web 実装がポインタを横取り。出荷対象外だが実機確認は必要 |
| Discover の下スワイプ | 「Before you read」は Phase 2。現状は無反応 |
| モバイルの E2E | Phase 1-D（Maestro）。Phase 0 の E2E は API レベル |
| pgvector 列 | Phase 3（DECISIONS.md D-006） |
| レート制限 | 未実装。実 Provider を繋ぐ Phase 1-A と同時に入れる |
| 観測性 | 構造化ログ・トレース・Provider レイテンシ指標は Phase 1-A |
