# Architecture

仕様書 22 節の構成を、Phase 0 で実際に存在するものに絞って説明します。将来のフェーズで追加される部分は「Phase N で追加」と明記します。

---

## 全体像

```
┌────────────────────────────────────────────┐
│ apps/mobile — Expo / React Native          │
│   Expo Router · ThemeProvider · ApiClient  │
└───────────────────┬────────────────────────┘
                    │ HTTP (JSON, camelCase)
┌───────────────────▼────────────────────────┐
│ apps/api — FastAPI                         │
│   routers → services → models              │
│                  ↓                         │
│         providers (interface)              │
│    mock │ arxiv* │ openalex* │ …           │
└───────────────────┬────────────────────────┘
                    │ SQLAlchemy
┌───────────────────▼────────────────────────┐
│ PostgreSQL 16                              │
│   26 tables · Alembic migrations           │
└────────────────────────────────────────────┘

packages/shared-types   ← 両側が読む型と語彙
packages/design-tokens  ← UI が読む唯一の視覚定義
                                    * Phase 1 で追加
```

---

## 設計を貫く 4 つの規則

### 1. 外部依存はすべて interface の背後にある

`papermatch_api/providers/base.py` に 6 つの Protocol があります。

| Interface | 役割 | Phase 0 の実装 |
| --- | --- | --- |
| `PaperProvider` | 論文メタデータ | `MockPaperProvider`（fixture） |
| `TranslationProvider` | 選択範囲の翻訳 | `MockTranslationProvider` |
| `EmbeddingProvider` | 意味ベクトル | `LocalEmbeddingProvider`（Phase 3・プロセス内） |
| `ExplanationProvider` | AI 説明 | 未実装（Phase 2） |
| `MathVerifier` | 数式変形の検証 | 未実装（Phase 5） |
| `FullTextProvider` | 本文・LaTeX ソース | 未実装（Phase 5） |

`LocalEmbeddingProvider` は代用品ではなく実装です（ハッシュ化 BoW・512 次元・決定的）。言い換えの検出は文埋め込みに劣りますが、16 節が類似度に求めているのは「次のカードがさっきのカードと同じ話か」で、これは共有された専門語彙として現れます。ホスト型モデルに差し替えるときは `embeddings` 行の `model` / `version` が変わるだけで、両者が混ざることはありません（D-006）。

ルータは具象クラスを import しません。`providers/registry.py` に設定値から解決を依頼します。arXiv を OpenAlex に差し替えても、mock を本物に差し替えても、ハンドラは変わりません。

すべての Provider は `health()` を持ち、これが `GET /health` に集約されます。クライアントは「フィードが低下している理由」を具体的に言えます。

### 2. 出自と生成方法は消えない

- **外部由来のもの**（`Paper`）は取得元・取得日時・URL・ライセンス・再配布可否・キャッシュ方針を持ちます。`abstract_redistributable` が false のレコードは、そもそも取り込み時に保存されません。
- **AI が作ったもの**（`Translation`、`DerivationStep`、`MathCard`）は provider / model / prompt_version / input_hash を持ちます（`GenerationProvenanceMixin`）。
- **数式**は `provenance_kind`（原論文の式 / 検証済み補完 / AI 説明 / 仮定 / 人手確認済み）と `verification_status` を別々に持ちます。前者は「どこから来たか」、後者は「どこまで確かめたか」で、混同すると未検証の AI 出力が原論文の式に見えてしまいます。
- 取り込み・重複統合・ライセンス判定は `audit_log` に記録されます。

`unverified` は既定で非表示です（仕様書 12 節）。この判定は `vocab.is_visible_by_default()` の 1 か所にあります。

### 3. 語彙は言語をまたいで 1 つ

`packages/shared-types/enums.json` が唯一の定義で、TypeScript と Python の両方がこのファイルを読みます。

- Python: `papermatch_api/vocab.py` が読み込み、DB の `CHECK` 制約を生成します。
- TypeScript: `packages/shared-types/src/vocab.ts` がリテラル型として再掲し、`vocab.test.ts` が JSON と 1 語ずつ突き合わせます。
- `tests/test_vocab_parity.py` が、DB の `CHECK` 制約と JSON の一致を検証します。

つまり片側だけに値を足すと、必ずどこかのテストが落ちます。

### 4. 原文は上書きされない

`papers.abstract` は英語原文です。翻訳は `translations` に、構造分類は `abstract_segments` に **オフセットとして** 入ります。分類器も翻訳も、原文の 1 文字も書き換えません。

---

## apps/api

```
papermatch_api/
  main.py            アプリ生成、CORS、統一エラー形式
  config.py          pydantic-settings。本番で既定の秘密鍵を拒否
  db.py              エンジンとセッション
  models.py          26 テーブル（仕様書 23 節）
  schemas.py         リクエスト/レスポンス（camelCase 変換）
  security.py        ゲスト JWT と current_user 依存
  vocab.py           enums.json のローダ
  cli.py             seed コマンド
  routers/           health, auth, fields, papers, translations, feed, saved, equations
  services/          ingestion（取り込み・重複統合・監査）, feed（枠配分・多様性・調整）,
                     scoring（推薦スコア）, embeddings（ベクトルの保存と読み出し）,
                     structure / method_kind（規則ベースの分類器）, activity, math_content
  providers/         base（interface）, arxiv, openalex, local_embedding, mock_*, registry
  text/              normalize, dedup, math_placeholders, latex_safety
  mathcheck/         数値代入と次元解析
alembic/versions/    0001_initial … 0004_feed_feedback
tests/
```

### text/ が独立している理由

正規化・重複排除・数式プレースホルダーは、DB も HTTP も知らない純粋関数です。仕様書 29 節の完了条件のうち 3 つ（重複カードが出ない / 同じ論文が再表示されない / 数式を含む選択で LaTeX が壊れない）がここに集中しているため、副作用なしで網羅的にテストできる形にしてあります。

### 重複排除の流れ

1. 各レコードから識別キーを計算する（`compute_identity`）。DOI → arXiv → Semantic Scholar → OpenAlex → 正規化タイトル+著者+年 の優先順位。
2. **正規化キーは 1 つではなく全部保持する。** これにより、あとから片方の識別子しか持たないレコードが来ても同じ束に入ります。
3. バッチ内では union-find で連結成分にまとめます。arXiv v1 と出版版に共通キーが無くても、v2 を介して繋がれば 1 件になります。
4. 統合時は「出版版 > プレプリント」「新しい版 > 古い版」で勝者を決め、識別子は全員分を union し、負けた側の出自を `mergedFrom` に残します。

### 数式保護

```
選択範囲 → mask_math() → ⟦MATH_1⟧ を含む文字列 → Provider
                                                     ↓
原文の LaTeX ← restore_math() ← 翻訳結果 → unmasked_tokens() で欠落検査
```

トークンが 1 つでも失われていれば、壊れた翻訳を出さずに原文を返し、`fellBackToOriginal: true` を立てます。

選択範囲が数式の途中から始まる場合の検出は、**選択範囲だけを見ても判定できません** — `"$ ... where $"` は構文的に正しいインライン数式に見えるからです。そのため `selection_splits_math()` は Abstract 全体を受け取り、境界が数式スパンの内側に落ちていないかを見ます。

---

## apps/mobile

```
app/
  _layout.tsx        Expo Router のルート。SafeArea + ThemeProvider
  index.tsx          Phase 0 の基盤確認画面（実 API に接続）
src/
  theme/             トークンからテーマを解決（配色・Reduce Motion・Dynamic Type）
  components/        Text, PressableRow — アクセシビリティ既定つき
  api/               型付きクライアント。NetworkError と ApiError を区別
  i18n/              全 UI 文字列
```

`app/index.tsx` はモックではなく実際に API を叩きます。仕様書 0 節の「UI はモックではなく、MVP から実データに接続可能な境界を持たせる」を Phase 0 の時点で満たすためです。

### アクセシビリティを既定にする仕掛け

- `Text` は `variant` を取り、サイズ・行間・書体をトークンから引きます。画面側でフォントサイズを書くことはありません。Dynamic Type の倍率は 1.0–2.0 にクランプ済みで、RN 側の二重スケーリングは切ってあります。
- `PressableRow` は `accessibilityLabel` を **必須** にし、最小タップ領域を保証します。素の `Pressable` を使うよりラベル付きのほうが楽、という状態を作っています。
- `theme.duration(speed)` は Reduce Motion を反映済みの値を返します。呼び出し側が設定を見に行く必要はありません。
- 状態は必ず文字（と記号）を伴います。色だけで意味を運ぶ箇所はありません。

---

## packages

### design-tokens

`tokens/tokens.json` が唯一の定義。TypeScript 側は型と解決ヘルパのみを足します。`src/index.test.ts` が、light/dark の役割が揃っていること、本文色のコントラストが WCAG 4.5:1 を満たすこと、Reduce Motion が全 duration を短縮すること、最大 Dynamic Type でも行間が字送りを上回ることを検証します。

### shared-types

`enums.json`（言語横断の語彙）と、`models.ts` / `api.ts`（ドメイン型と HTTP 契約）。Phase 1 以降の `/feed`、`/saved`、`/math-cards`、`/canvas` のレスポンス型もすでに宣言してあり、実装が追いつく形にしています。

---

## データフロー（Phase 0）

**取り込み**

```
MockPaperProvider.search()
  → ingest()
      → 各レコードの識別キーを計算
      → 既存行を canonical_id または任意の識別子で探す
      → 無ければ INSERT、あれば新しいほうで UPDATE
      → 識別子・分野重み・Abstract 構造を反映
  → audit_log に 1 行
```

冪等です。2 回目の `make seed` は `inserted: 0` になります。

**部分翻訳**

```
POST /translations
  → 論文と選択範囲の一致を検証（ハッシュ不一致は 409）
  → 長さ制限（選択であって全文ではない）
  → ライセンス確認（再配布不可なら 403 で Provider に送らない）
  → 数式境界の確認（途中で切れていれば 422）
  → mask → Provider → 欠落検査 → restore
  → TextSelection と Translation を保存
```

---

## Phase 1 以降で足りるもの

| フェーズ | 追加 | 触る場所 |
| --- | --- | --- |
| 1 | arXiv / OpenAlex Provider | `providers/` に 2 ファイル + registry に登録。ルータは無変更 |
| 1 | `/feed`、`/impressions`、`/actions`、`/saved` | `routers/` 追加。表示履歴テーブルは既に存在 |
| 1 | スワイプデッキ、オンボーディング、翻訳シート | `apps/mobile/app/` |
| 3 | ~~埋め込みと多様性スコア~~ 済 | `local_embedding` + `services/scoring`。残るは pgvector 列の migration（D-006） |
| 4–5 | 数式カードと検証 | `Equation` / `DerivationStep` / `MathCard` は既にスキーマにある |
| 6 | Canvas | `CanvasPosition` は既にスキーマにある |

スキーマが最初から全エンティティを持っているのは、あとから足すと既存データの移行が必要になるからです。テーブルが空であることのコストは、あとで列を足すコストよりずっと小さいと判断しました（DECISIONS.md D-004）。
