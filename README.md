# PaperMatch

原文を主役にし、論文との出会い、部分翻訳、数式理解、保存・再発見、知識空間の可視化を一体化するモバイルアプリ。

完全な企画・技術仕様は [`PaperMatch_SPEC.md`](./PaperMatch_SPEC.md) にあります。この README は、いま何が動くのか、どう動かすのかだけを書いています。

**現在の状態: Phase 0 完了 / Phase 1 は 1-A〜1-D 完了（実 API への疎通と E2E は残）/ Phase 2 は AI 非依存部分が完了 / Phase 4 は 4-A〜4-C 完了（WebView の実機確認は保留）。** 実装フェーズの全体像は [`TASKS.md`](./TASKS.md)、設計上の判断とその理由は [`DECISIONS.md`](./DECISIONS.md)、構成の説明は [`ARCHITECTURE.md`](./ARCHITECTURE.md) を参照してください。

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

## Phase 1 で追加されたもの

- **Discover フィード** — 仕様書 16 節の 70/20/10 を「枠の配分」として実装。表示履歴による除外、再投入条件、分野・著者の連続抑制。各カードは推薦理由を文で持ちます。
- **取り込み worker** — `papermatch worker` で新着の追跡（cursor を永続化し、再起動しても 1 ページ目から読み直さない）と、撤回・版更新の取り込み直しを回します。**provider が返さなくなった論文を撤回扱いにはしません** — 上流の一時障害でフィードが静かに空になるからです。
- **推薦スコア** — 興味一致 + 質 + 新しさ + 難易度 − 直近 20 件との類似 − 同一著者。類似度は取り込み時に保存した埋め込みで測ります（プロセス内・決定的）。**スコアの数値は読者に見せません** — 理由は文で出します（仕様書 6 節）。
- **フィード調整** — 16 節の 5 つすべて（この話題を減らす / この著者をしばらく表示しない / 類似論文を減らす / 実験系を増やす / 古典的論文を増やす）。すべて取り消せて 30 日で失効します。「実験系」は要旨から規則ベースで判定し、**分からないときはラベルを付けません**。
- **スワイプデッキ** — 左右上下のジェスチャーと、それと同じハンドラを呼ぶボタン。
- **Undo** — 効果（保存行）と痕跡（impression）の両方を戻すので、取り消したカードは実際にデッキへ返ってきます。
- **オンボーディング 5 画面** — 分野 / 論文種別 / 英語 / 数式 / 冒険度。
- **文単位の範囲選択と翻訳シート** — 段階ヒントのタブつき。数式を壊した場合は原文にフォールバックし、その旨を表示します。
- **Saved（Library View）** — 7 種の並べ替え、状態・保存理由の表示、解除。
- **オフライン** — フィード 20 件と保存一覧を端末にキャッシュし、API 障害時に表示します。

## Phase 2 で追加されたもの

- **Abstract の構造分類** — Background / Problem / Method / Result / Significance を規則ベースで判定し、`heuristic` として保存します（`ai` とは名乗りません — DECISIONS.md D-022）。fixture の正解ラベルに対する一致率をテストで測定しています。
- **個人用学術英語辞典** — 翻訳シートから表現を保存。単語 / 連語 / 構文 / 一文 を自動判定し、出典の文をそのまま文脈として残します。
- **Learn タブと復習** — 数日後に 1 件ずつ再提示。答えは「わかった / もう一度」の 2 択のみで、点数も連続記録もありません（DECISIONS.md D-023）。

## Phase 4 で追加されたもの（数式）

- **危険な LaTeX の判定** — 数式は WebView 内の KaTeX に渡るので、式文字列はレンダリングエンジンに届く未検証入力です。`\href{javascript:...}` によるスクリプト実行、`\def` の展開爆弾、`\rule{1pt}{99999em}` のレイアウト爆弾などを拒否します。**サニタイズはしません** — 一部を削った式は「論文の式に見えるが論文の式ではないもの」で、仕様書 11 節の「原式を勝手に変換しない」に反します。拒否された式もソースとして返り、クライアントはそれを表示します（[`DECISIONS.md`](./DECISIONS.md) D-027）。
- **機械的検証** — 数値代入と次元解析。式の評価言語は AST で検証した算術のみで、`__import__` も属性アクセスも通りません。
- **手動作成の数式カード 5 枚** — 導出 / 定義 / 物理的意味 / 整合性チェック / 近似。**検証状態は fixture に書きません。** チェックそのものを書き、取り込み時に実際に走らせた結果を保存します（[`DECISIONS.md`](./DECISIONS.md) D-028）。
- **未検証の変形は既定で非表示**（仕様書 12 節）。ただし隠した件数は返すので、導出が完全であるかのようには見えません。
- **KaTeX をアプリに同梱** — CDN は使いません（オフライン動作と仕様書 25 節）。数式は `<script type="application/json">` に入れて渡し、**HTML へ文字列結合しません** — `</script>` を含む数式は WebView でのスクリプト実行になるからです。サーバの拒否・KaTeX の `trust: false`・CSP とナビゲーション拒否の 3 重で止めています（[`DECISIONS.md`](./DECISIONS.md) D-029）。
- **MathML 併記**とスクリーンリーダー用ラベル、Dynamic Type、ライト/ダーク、失敗時の LaTeX ソース表示。実ブラウザで、同梱コーパス 18 本すべての組版・注入スクリプトが走らないこと・**ネットワークリクエスト 0 件**を確認しています。
- **Focus Mode**（`/math/[id]`、Learn タブから）— 記号 / 構造 / 導出 / 意味 / 極限 の 5 タブ。詳細度は 4 段階ありますが、選ぶのは「説明の量」ではなく**カードが持っている導出の量**です。どのレベルも保存されていない step を作りません（[`DECISIONS.md`](./DECISIONS.md) D-031）。
- **理解チェック**はカードの導出から組み立てます（AI 生成ではありません）。誤答の選択肢は同じカードの他の操作なので、「ここで効くのはどれか」を分かっている必要があります。結果は文だけで、点数は出しません。
- **極限タブ**は各変形が実際に確認された範囲と次元を出し、「ここに書かれていない範囲については何も主張していません」と添えます。

```bash
curl -s localhost:8000/math-cards | jq '.cards[] | {cardType, title}'
curl -s localhost:8000/math-cards/$ID | jq '.steps[] | {verificationStatus, operation}'
curl -s "localhost:8000/math-cards/$ID?includeUnverified=true" | jq '.hiddenStepCount'
```

## 完成までに残っている操作（コードは全部書いてあります）

実装はすべて済んでいて、残りは**この開発環境の外でしかできない操作**だけです。それぞれ 1 つの設定変更か 1 コマンドで、コードの変更は要りません。

| # | 操作 | それで動くもの |
| --- | --- | --- |
| 1 | **egress の許可**: Claude Code の環境設定（ネットワークポリシー）で `export.arxiv.org` と `api.openalex.org` を許可する | 実データの取り込み（`PAPERMATCH_PAPER_PROVIDER=arxiv` + worker）、疎通テスト `pytest -m live`、実データ 100 件でのフィード確認、英語難易度の較正 |
| 2 | **API 鍵**: 環境変数 `PAPERMATCH_ANTHROPIC_API_KEY` を設定し、`PAPERMATCH_TRANSLATION_PROVIDER=anthropic` `PAPERMATCH_EXPLANATION_PROVIDER=anthropic` にする | 実翻訳（6 段階すべて）、Before you read の生成部分、Why it matters の 4 種。鍵はサーバ側だけに置く（仕様書 25 節） |
| 3 | **実機**: 手元のマシンで `npm install && npm run mobile`、Expo Go で開く | TASKS.md の実機チェックリスト（文タップ選択、WebView の数式、VoiceOver、Dynamic Type、機内モード）と Maestro E2E |
| 4 | **push 配信**（任意）: APNs / FCM などの配信チャネルを接続する | 通知が受信箱に加えて端末にも届く。プリセット・静音時間・1日1回は生成時に適用済みなので、チャネル側の判断は不要（`notifications` テーブルの行を送るだけ） |

この環境の egress 拒否は組織ポリシーの 403 で、回避はしません（proxy の指示どおり報告のみ）。1 と 2 は [claude.ai/code](https://claude.ai/code) の環境設定から変更できます。

## 実データ Provider（arXiv / OpenAlex）

`PAPERMATCH_PAPER_PROVIDER` で切り替えます。既定は `mock`（サンプルコーパス）です。

```bash
PAPERMATCH_PAPER_PROVIDER=arxiv     make api   # arXiv Atom API
PAPERMATCH_PAPER_PROVIDER=openalex  make api   # OpenAlex works API
PAPERMATCH_OPENALEX_MAILTO=you@example.org     # 任意。OpenAlex の polite pool に入ります
```

- **レート制限とサーキットブレーカー**は Provider 側にあります（`providers/http.py`）。arXiv は公表値どおり 3 秒間隔、OpenAlex は 200ms 間隔。連続失敗でブレーカーが開き、`GET /health` がどの Provider がなぜ落ちているかを個別に返します。429 と 5xx はブレーカーを開きますが、それ以外の 4xx は開きません（こちら側のクエリ不備で Provider 全体を止めないため）。
- **ライセンス**は各レコードに `licenseId` と根拠 URL を同梱します。判別できないライセンスは推測せず、その Abstract を取り込みません（[`DECISIONS.md`](./DECISIONS.md) D-025）。
- **疎通確認は opt-in テストです。** この環境は外向き接続が遮断されているため、パーサは記録形状の fixture に対して完成させ、実 API に触るテストだけを分離しました。ネットワークのある環境で:

```bash
cd apps/api && PAPERMATCH_LIVE_PROVIDERS=1 ./.venv/bin/pytest -m live -v
```

## 取り込み worker

```bash
cd apps/api
uv run python -m papermatch_api.cli worker --once   # 1 巡して終了（cron / 再起動ポリシー向き）
uv run python -m papermatch_api.cli worker          # 常駐。--interval 秒ごとに 1 巡
uv run python -m papermatch_api.cli runs            # 直近の実行ログ
```

2 種類の job が別々の周期で回ります。

- **discovery** — 「新しいものは何か」。分野ごとに 1 job で、cursor を DB に持つので**再起動しても 1 ページ目から読み直しません**（仕様書 27 節のガードレール「同一ソースへの過剰APIアクセス」）。
- **refresh** — 「いま持っているものはまだ正しいか」。仕様書 21 節の「削除・訂正・撤回情報を反映できる」がこれです。

3 つの挙動をテストで固定しています。

- **provider が返さなくなった論文を撤回扱いにしません。** `get_by_canonical_id` の `None` は「provider がくれなかった」であって、一時障害・識別子の移動・そもそも持っていない、のどれでもあり得ます。撤回と読むと、**上流の不調 1 回で読者のフィードが静かに空になります。**
- **失敗した run の cursor は継ぎません。** 途中で落ちた run の cursor は、保存されていないかもしれないページを指しています。読み直しは冪等なので無料ですが、飛ばすと誰も気づきません。
- **1 つの job の失敗が他を止めません。** 失敗は run 行に記録され、次の job は自分の番を貰います（仕様書 25 節）。

再取得キューは `acquired_at` ではなく `last_refreshed_at` で並べます。前者は provider が寄こす出自で、**取得時刻を返さない provider ではキューが永久に同じバッチを回り続けます**（[`DECISIONS.md`](./DECISIONS.md) D-034 — 実際に踏みました）。

## 分析指標（仕様書 27 節）

```bash
cd apps/api && uv run python -m papermatch_api.cli metrics --window 7
```

North Star、主要指標、ガードレールを出します。**算出できないものは省略せず、値なしで並べます** — 12 個の数字が並んだレポートは完成して見えますが、「これは算出できない、足りないのはこれ」の行が並んでいるほうが、**どこが見えていないか**を教えてくれます。いま算出できないのは 3 つです（数式カード完了率 / Canvas 遷移率 / クラッシュ率・ジェスチャー失敗率）。

**分母は必ず書きます。** 「10 秒以上読まれた割合」を全 impression で割ると、**クライアントが dwell を報告し損ねたときに数字が下がります** — いちばん動いてほしくないときに動くので、分母は「dwell が記録された impression」です。分母が 0 のときは `0.000` ではなく値なしにします（0.000 は「誰もやらない」と読めますが、実際は「まだ機会が無い」です）。

行頭の `!` はガードレールです。上がったら止まる種類の数字で、`guard.unlicensed_shown` は**構造上 0 のはず**のもの — 0 でなければ取り込みの規則が破れています。

## Lint と整形

| 言語 | lint | 整形 |
| --- | --- | --- |
| Python | ruff + mypy | ruff format |
| TypeScript | ESLint 9（flat config） | Prettier 3 |

TypeScript 側にはプロジェクト固有のルールが 2 つあります（[`DECISIONS.md`](./DECISIONS.md) D-026）。

- **スタイル中の 16 進カラーリテラルを禁止** — 配色は `@papermatch/design-tokens` の 1 箇所に置くと仕様書 19 節が決めており、20 節の色覚に依存しない対比はそれが単一の出所であることに依存しています。
- **画面どうしの相互 import を禁止** — 画面はエントリポイントで、再利用単位ではありません。共有したいものは `src/` に出します。

Markdown と手で整えた JSON は Prettier の対象外です（`.prettierignore` に理由を書いています）。

### まだ無いもの

コードとしては全機能が入っています。残るのは開発環境の外でしか行えない操作だけで、上の「完成までに残っている操作」にまとめました — 論文 API への疎通（egress 許可が要る）、実機確認と Maestro E2E、push の配信チャネル、そして実データでの英語難易度較正（疎通が前提）。

実翻訳と AI 説明の Provider は**実装済み**です（`PAPERMATCH_ANTHROPIC_API_KEY` を置いて `*_PROVIDER=anthropic` にすれば動きます）。鍵が無いときの既定は、翻訳が `mock`、説明が `derived`（論文から導ける事実だけを返し、導けないものは理由を添えて返さない）です。着手順は [`TASKS.md`](./TASKS.md) にあります。

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

### make が無い環境（Windows など）

`make` の各ターゲットは npm script からも叩けます。

```bash
npm install                                                        # make setup の前半
cd apps/api && uv venv --python 3.11 && uv pip install -e ".[dev]" # 後半
npm run db:up                                                      # make db-up
npm run db:migrate                                                 # make migrate
npm run api:dev                                                    # make api
npm run mobile                                                     # make mobile
npm run mobile:clear                                               # 同上 + Metro のキャッシュを消す
```

**`expo start` をリポジトリのルートで実行しないでください。** ルートの `package.json` には `main` が無いため、Expo が `expo-router/entry` ではなく既定の `expo/AppEntry.js` を入口だと判断し、この構成には存在しない `App.js` を探して `Unable to resolve module ../../App` で失敗します。`npm run mobile` はワークスペース経由で `apps/mobile` の中から起動するので、この取り違えが起きません。

### 数式レンダラだけを確認する

`/dev/math` は API もデータベースも使いません（ハードコードした LaTeX を `MathView` に流すだけ）。`npm run mobile` だけで起動でき、API に繋がらないときの入口画面に出る「開発用: 数式レンダラの確認」から入れます。このリンクは `__DEV__` の中にあるので製品ビルドには出ません。

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
make lint        # ruff + mypy + eslint + prettier + tsc
make format      # 両言語の自動整形
```

DB が無い環境では統合テストと E2E テストは失敗ではなく **skip** され、起動方法が理由に表示されます。

### 見た目の回帰テスト

```bash
npm run web              # 別のターミナルで web ビルドを起動しておく
npm run visual           # 8 条件を撮ってベースラインと画素比較
npm run visual:update    # 変更を意図したものとして受け入れる
```

`/dev/visual` に部品を並べたギャラリーがあり、ライト/ダーク・320/390/820px・Dynamic Type 1.0/1.5/2.0・
Reduce Motion・日英の 8 条件で撮ります。**内容は固定の定数、描くのは出荷されるコンポーネント**です
（DECISIONS.md D-044）。ベースラインはフォントのラスタライズに依存するため `npm run ci` には
入れていません。差分が出たら `apps/mobile/visual-output/` に実物と差分画像が出ます。

現在: Python 449 件 / TypeScript 131 件。

| 種別 | 対象 |
| --- | --- |
| 単体 | タイトル・DOI・arXiv 正規化、重複排除、数式プレースホルダー、語彙の整合、Provider、デザイントークンのコントラスト、i18n、テーマ解決、API クライアント |
| 統合 | Provider → DB 取り込み、冪等性、重複統合、ライセンス判定、監査ログ、マイグレーション乖離検出 |
| E2E | ゲスト認証 → 設定 → 分野選択 → フィード → スワイプ/ボタン → Undo → 保存一覧 → 範囲選択翻訳（数式保持を含む） |

---

## リポジトリ構成

```
apps/
  api/                FastAPI + SQLAlchemy + Alembic
  mobile/             Expo + React Native + Expo Router
packages/
  design-tokens/      仕様書 19 節の配色・書体・余白・モーション
  shared-types/       ドメイン型、API 契約、言語横断の語彙（enums.json）
fixtures/             分野タクソノミ、合成サンプルコーパス、手動作成の数式カード
scripts/              fixture ジェネレータ、KaTeX 同梱ビルド
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
