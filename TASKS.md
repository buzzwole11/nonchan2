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
| 5 | オンボーディング 5 画面 | Phase 1 — API 側（`/fields`、`/me/interests`、`/me/settings`）は完成済み |
| 6 | スワイプデッキ | Phase 1 |
| 7 | ボタン操作と Undo | Phase 1 — `actions.undoes_action_id` はスキーマにあり |
| 8 | Saved の整然リスト | Phase 1 — `saved_papers` はスキーマにあり |
| 9 | `TranslationProvider` と `MockTranslationProvider` | ✅（`POST /translations` まで通っている） |
| 10 | 英文選択 → ボトムシート | Phase 1 — API 側は完成済み、UI が未着手 |
| 11 | light/dark、Reduce Motion、Dynamic Type | ✅ 自動テストあり。実機確認は下記チェックリスト |
| 12 | 単体・統合・E2E とCI | ✅（モバイル UI の E2E は Phase 1） |

---

## Phase 1 — MVP

完了条件は仕様書 29 節。

### 1-A データソース接続
- [ ] `ArxivPaperProvider`（Atom API、レート制限、`arXiv:` 識別子、カテゴリ→分野マッピング）
- [ ] `OpenAlexPaperProvider`（候補発見、OA 状態、著者、識別子統合）
- [ ] Provider ごとのサーキットブレーカーとキャッシュ（仕様書 25 節）
- [ ] 取り込み worker（定期実行、撤回・版更新の同期）
- [ ] 実データ 100 件以上でフィードが構成できることの確認（仕様書 29 節）

### 1-B フィード API
- [ ] `GET /feed?mode=discover&cursor=` — 表示履歴による除外、推薦理由の付与
- [ ] `POST /impressions` — 滞在時間を含む
- [ ] `POST /actions` / `POST /actions/{id}/undo`
- [ ] `GET /saved` / `POST|PATCH|DELETE /saved/{paperId}`
- [ ] オフライン用に次の 20 件を返す仕組み（仕様書 26 節）

### 1-C モバイル UI
- [ ] オンボーディング 5 画面（分野 / 論文種別 / 英語 / 数式 / 冒険度）
- [ ] Abstract カード（仕様書 6 節のカード上部・本文・下部の全項目）
- [ ] スワイプデッキ（Reanimated + Gesture Handler、左右上下）
- [ ] **スワイプと等価なボタン**（仕様書 20 節。ジェスチャーだけに機能を置かない）
- [ ] Undo（スキップ直後のトースト + Profile からの取り消し）
- [ ] 範囲選択 → フローティングツールバー → 翻訳ボトムシート
- [ ] Saved の整然リスト（Library View の最小形）
- [ ] 原文リンク（外部ブラウザ、WebView のナビゲーション制限）
- [ ] オフライン 20 件のキャッシュと、API 障害時のキャッシュ表示

### 1-D 品質
- [ ] Maestro による E2E（オンボーディング / スワイプ / Undo / 範囲選択翻訳 / オフライン / VoiceOver 操作）
- [ ] Visual regression（light・dark / 小画面・大画面 / 日本語長文 / Dynamic Type / Reduce Motion）
- [ ] トークンを `expo-secure-store` へ移す（DECISIONS.md D-007）
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
| モバイルの E2E | Phase 1-D（Maestro）。Phase 0 の E2E は API レベル |
| pgvector 列 | Phase 3（DECISIONS.md D-006） |
| トークンの永続化 | メモリ内のみ。Phase 1-D で secure-store へ |
| レート制限 | 未実装。実 Provider を繋ぐ Phase 1-A と同時に入れる |
| 観測性 | 構造化ログ・トレース・Provider レイテンシ指標は Phase 1-A |
