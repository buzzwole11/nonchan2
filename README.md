# PaperMatch

原文を主役にし、論文との出会い、部分翻訳、数式理解、保存・再発見、知識空間の可視化を一体化するモバイルアプリ。

完全な企画・技術仕様は [`PaperMatch_SPEC.md`](./PaperMatch_SPEC.md) にあります。この README は、いま何が動くのか、どう動かすのかだけを書いています。

**現在の状態: Phase 0（基盤）完了。** 実装フェーズの全体像は [`TASKS.md`](./TASKS.md)、設計上の判断とその理由は [`DECISIONS.md`](./DECISIONS.md)、構成の説明は [`ARCHITECTURE.md`](./ARCHITECTURE.md) を参照してください。

---

## Phase 0 で動くもの

- **モノレポ** — Expo モバイルアプリ、FastAPI、共有パッケージ、CI。
- **PostgreSQL スキーマとマイグレーション** — 仕様書 23 節の全エンティティ（26 テーブル）。models と migration の乖離はテストで検出されます。
- **Provider interface 一式** — `PaperProvider` / `TranslationProvider` / `EmbeddingProvider` / `ExplanationProvider` / `MathVerifier` / `FullTextProvider`。Phase 0 では `mock` 実装が動きます。
- **合成サンプルコーパス 60 件**（+ 重複検出用の変種 3 件）。物理・数学・情報系 12 分野に均等配分。
- **重複排除** — DOI / arXiv / Semantic Scholar / OpenAlex / 正規化タイトルの優先順位で正規化し、プレプリントと出版版、arXiv v1/v2 を 1 件に統合します。
- **数式保護つき部分翻訳** — 選択範囲だけを翻訳し、LaTeX はプレースホルダー化して原文のまま復元します。
- **ゲスト認証、分野一覧、設定、論文一覧・詳細** の API。
- **デザイントークン** — 仕様書 19 節の配色・書体・余白・モーションを単一の JSON から供給。コントラスト比はテストで検証。
- **アクセシビリティの基盤** — light/dark、Reduce Motion、Dynamic Type、最小タップ領域、色に依存しないラベル。

### まだ無いもの（Phase 1 以降）

Discover のスワイプデッキ、オンボーディング 5 画面、翻訳ボトムシート、Saved 一覧、Undo、arXiv/OpenAlex への実接続、数式カード、Knowledge Canvas。着手順は [`TASKS.md`](./TASKS.md) にあります。

---

## セットアップ

必要なもの: Node.js 22（`.nvmrc`）、Python 3.11、[uv](https://docs.astral.sh/uv/)、Docker。

```bash
# 依存関係（Node ワークスペース + Python API）
make setup

# PostgreSQL と Redis を起動
make db-up

# マイグレーションとサンプルデータ投入
make seed
```

`make seed` は次のように出力します。

```
fields: 15
papers inserted: 49
papers updated: 0
duplicates merged: 0
skipped (licence unknown): 11
```

`skipped (licence unknown)` は意図的な挙動です。利用条件が確認できないレコードは Abstract を保存しません（仕様書 21 節）。パイプラインがその分岐を実際に通るよう、fixture にライセンス不明のレコードを混ぜてあります。

### 起動

```bash
make api      # http://localhost:8000  （/docs に OpenAPI UI）
make mobile   # Expo dev server
```

モバイルアプリの接続先は `apps/mobile/app.json` の `expo.extra.apiBaseUrl` です。実機から繋ぐ場合は開発マシンの LAN IP に変更してください。

### 動作確認

```bash
curl -s localhost:8000/health | jq
curl -s 'localhost:8000/papers?limit=2' | jq '.papers[].title'
curl -s localhost:8000/fields | jq '.fields[] | select(.parentId == null)'
```

---

## テスト

```bash
make test        # すべて
make test-api    # Python（統合テストは DB が必要）
make test-unit   # DB 不要のものだけ
make test-ts     # TypeScript
make lint        # ruff + mypy + tsc
```

DB が無い環境では統合テストと E2E テストは失敗ではなく **skip** され、起動方法が理由に表示されます。

現在: Python 141 件 / TypeScript 42 件。

| 種別 | 対象 |
| --- | --- |
| 単体 | タイトル・DOI・arXiv 正規化、重複排除、数式プレースホルダー、語彙の整合、Provider、デザイントークンのコントラスト、i18n、テーマ解決、API クライアント |
| 統合 | Provider → DB 取り込み、冪等性、重複統合、ライセンス判定、監査ログ、マイグレーション乖離検出 |
| E2E | ゲスト認証 → 設定 → 分野選択 → 論文一覧 → 範囲選択翻訳（数式保持を含む） |

---

## リポジトリ構成

```
apps/
  api/                FastAPI + SQLAlchemy + Alembic
  mobile/             Expo + React Native + Expo Router
packages/
  design-tokens/      仕様書 19 節の配色・書体・余白・モーション
  shared-types/       ドメイン型、API 契約、言語横断の語彙（enums.json）
fixtures/             分野タクソノミと合成サンプルコーパス
scripts/              fixture ジェネレータ
infra/                コンテナ初期化 SQL
```

---

## サンプルデータについて

`fixtures/papers.sample.json` のタイトル・Abstract・著者名・掲載誌・識別子は **すべてこのリポジトリのために書かれた合成テキスト**で、CC0-1.0 です。実在論文の Abstract は含まれていません（仕様書 31 節 4 項）。

`node scripts/generate-fixtures.mjs` で再生成できます。ジェネレータは決定論的なので、出力は毎回同一になります（CI がこれを検証します）。

Phase 1 で arXiv / OpenAlex に接続したあとも、このコーパスはオフライン動作とテストのフォールバックとして残ります。

---

## ライセンスと権利について

- 出版社サイトのスクレイピングは行いません。
- 各レコードは取得元・取得日時・ライセンス・再配布可否を保持し、それらは API レスポンスにも含まれます。
- ライセンスが不明なレコードの本文は保存も再利用もしません。
- 撤回・訂正の状態を表現できるスキーマを持ちます。

詳細は仕様書 21 節と [`DECISIONS.md`](./DECISIONS.md) を参照してください。
