# PaperMatch 完全企画・実装仕様書

**用途:** Claude Codeに段階的に実装させるためのプロダクト企画書兼技術仕様書  
**版:** 1.0  
**作成日:** 2026-07-30

> 原文を主役にし、論文との出会い、部分翻訳、数式理解、保存・再発見、知識空間の可視化を一体化する。

## 0. Claude Codeへの最上位指示

この文書は、英語学術論文との出会い、部分翻訳、数式理解、保存・再発見、知識空間の可視化を一体化したモバイルアプリの完全仕様である。

Claude Codeは以下を守ること。

- まずリポジトリを作成し、README、ARCHITECTURE、DECISIONS、TASKSを用意する。
- 一度に全機能を実装せず、Phase 0から順に、各フェーズを動作確認可能な状態で完了する。
- UIはモックではなく、MVPから実データに接続可能な境界を持たせる。
- 外部API、翻訳、埋め込み、数式抽出、AI説明はすべてProvider interfaceで交換可能にする。
- 原文、機械翻訳、AI説明、機械検証済み導出、人手レビュー済み情報をデータモデルとUIの両方で明確に区別する。
- 論文本文やAbstractの利用条件を尊重し、出典、識別子、ライセンス、取得元を追跡可能にする。
- スワイプ以外の操作手段、Reduce Motion、色覚多様性、スクリーンリーダー、文字拡大を初期設計に含める。
- 数式は画像を正本にせず、LaTeX文字列を正規データとして保存する。
- テスト、型、安全なマイグレーション、監査ログ、失敗時のフォールバックを省略しない。
- 不明点は勝手に仕様を削らず、合理的な既定値を採用してDECISIONS.mdへ記録する。

最初の実装目標は、物理・数学・情報系のオープンな論文メタデータを対象にした「Abstractスワイプ、範囲選択翻訳、保存、重複排除、整然ライブラリ」である。数式カードとKnowledge Canvasは、基盤を壊さない形で後続フェーズに追加する。

## 1. 企画概要

仮称：PaperMatch / Abstract Swipe / Abs.

プロダクトコンセプト：
「論文を読む」ことを要求するのではなく、「論文と出会い、少し理解し、気になったら深く読む」体験を提供する。

ユーザーは事前に研究分野、英語難易度、数式レベル、推薦の冒険度を設定する。アプリは選択分野の英語論文Abstractをカードとして提示する。左スワイプで今回は見送り、右スワイプで保存する。英文の任意範囲を選択すると、その範囲だけが画面下のボトムシートで日本語訳される。保存後は、英語表現、専門用語、数式カード、原論文への読書ルートとして再提示される。

長期的には、保存論文を意味ベクトルに基づく色付きタイルとして可視化し、アーティスティックなKnowledge Canvasと、検索・整理に強いLibrary Viewを滑らかに切り替えられるようにする。

中核価値：
- 全文翻訳に逃げず、必要な範囲だけ補助する。
- 偶然の発見を残しつつ、同じ論文や似すぎた論文の連続を防ぐ。
- 数式を美しいLaTeX表示だけでなく、操作可能な学習オブジェクトにする。
- 保存を墓場にせず、別の入口から再会させる。
- 自分の関心分野を「知的風景」として眺められる。

## 2. 想定ユーザーとジョブ

主要ユーザー：
- 英語論文に慣れたい学部生・大学院生
- 隣接分野を探索したい研究者・技術者
- 理論物理、数学、情報系で数式を含む論文を読みたい人
- 通勤や短時間で研究動向に触れたい人

主要ジョブ：
1. 興味のある分野から、読む価値のありそうな論文を低負荷で見つけたい。
2. 分からない英文だけを翻訳し、原文を読む力を失いたくない。
3. Abstractの背景、方法、結果、意義を短時間で把握したい。
4. 省略された数式変形や記号の意味を、その場で確認したい。
5. 保存した論文を後から検索し、学習素材として再利用したい。
6. 自分の関心がどの分野に広がっているか視覚的に眺めたい。

非目標：
- 査読品質を判定するアプリではない。
- AI要約だけを消費するアプリではない。
- 出版社PDFを無断で再配布するアプリではない。
- 専門家の確認なしにAI生成の数式変形を真実として提示しない。

## 3. 体験原則

1. Original first：原文を主役にする。翻訳や説明は補助として段階的に出す。
2. Progressive disclosure：難しい情報は一度に出さず、タップや展開で深くする。
3. Calm interaction：派手なゲーム演出より、静かな達成感と滑らかな反応を重視する。
4. Trust by provenance：出典と生成方法を常に追跡できるようにする。
5. Serendipity with control：偶然性を残しつつ、ユーザーが推薦の幅を調整できるようにする。
6. Spatial memory：Canvas上の位置を安定させ、ユーザーが知識の場所を覚えられるようにする。
7. Accessible by default：色、ジェスチャー、動きだけに意味を依存させない。

## 4. コアユーザーフロー

初回：
1. 研究分野を階層タグで選択。
2. 論文種別を選択。
3. 英語難易度を選択。
4. 数式レベルを選択。
5. 推薦の冒険度を選択。
6. スワイプと範囲選択翻訳を短く体験。

日常利用：
1. DiscoverでAbstractカードを表示。
2. 必要なら下スワイプまたは準備ボタンで予備知識を見る。
3. 英文を読み、分からない箇所だけ選択。
4. 用語、文骨格、直訳、自然訳、専門的意味を段階表示。
5. 左スワイプで見送り、右スワイプで保存、上スワイプで原論文。
6. 保存時に任意で目的タグを付与。
7. 後日Learnで英語表現や数式カードとして再会。
8. SavedをLibraryまたはCanvasで閲覧。

深掘り：
1. 保存論文のRecommended Pathを選択。
2. Abstract、主要図、Introduction、主要式、Conclusionを目的別に案内。
3. 数式をタップしてFocus Modeへ。
4. 記号、構造、導出、意味、極限を確認。
5. 原論文の節・式番号へ戻る。

## 5. 画面構成とナビゲーション

下部ナビゲーション：
- Discover：新しいAbstractと出会う。
- Saved：保存した論文を管理する。
- Learn：英語表現、用語、数式、復習。
- Profile：興味、難易度、表示、通知、データ設定。

Saved内の表示切替：
- Canvas View：意味空間をアーティスティックに探索。
- Library View：一覧、グリッド、分野、年、状態で整然と管理。

目的モード：
- Discover：新規論文中心。
- Focus：保存した1本を10～20分で読む。
- Learn：英語表現と数式の復習。
- Explore：基礎、類似、対立、後続研究をたどる。

## 6. DiscoverのAbstractカード仕様

カード上部：
- 主分野
- 論文種別
- 発表年
- 推定読了時間
- Open Access表示
- 英語難易度
- 数式密度
- 推薦理由への入口

カード本文：
- タイトル
- 著者
- 掲載誌またはarXiv
- Abstract原文
- 長い場合はフェード付きでカード内展開
- Abstractの役割ラベル：Background / Problem / Method / Result / Significance

カード下部：
- 数式数
- OA状態
- DOIまたはarXiv識別
- Skip / Save / Readボタン

ジェスチャー：
- 左：Not for now。スキップ後にUndo。
- 右：Save for later。保存理由チップを任意表示。
- 上：原文候補を開く。
- 下：Before you read。予備知識を表示。

カードの推薦理由：
- 保存済みテーマとの類似
- 選択分野との一致
- 隣接分野探索
- 古典的・基礎的研究
- 最新研究

推薦理由は短く説明可能であること。単一の不透明なスコアだけを見せない。

## 7. 部分翻訳と学術英語支援

英文を選択すると、フローティングツールバーを表示：
- 訳す
- 文法
- 用語
- 保存

翻訳ボトムシート：
- 選択原文を上部に固定
- 難語ヒント
- 文の骨格
- 逐語対応
- 直訳
- 自然訳
- 学術的・専門的意味
- 音声読み上げ
- 表現保存

段階的ヒント：
1. 難しい語だけ
2. Subject / Verb / Object / Modifier
3. 句・節の構造
4. 直訳
5. 自然訳
6. 分野固有の意味

翻訳設定：
- 自然な日本語
- 原文に忠実
- 逐語的
- 学術文体
- やさしい日本語
- 初期タブの指定
- 即時表示、3秒考える、自分の訳を入力、単語ヒント先行

数式保護：
翻訳前にインライン数式をプレースホルダー化し、翻訳後に元のLaTeXを復元する。数式や式番号を翻訳モデルに改変させない。

翻訳済み箇所の表示：
- 青点：翻訳済み
- 紫点：構文確認済み
- 星：保存済み
本文を汚さないよう余白に控えめに表示する。

## 8. Abstract理解支援

Before you read：
- 背景知識3項目
- 専門用語3～5項目
- 必要なら学部レベルの短い説明
- 強制表示しない

構造分類：
- Background
- Problem
- Method
- Result
- Significance
AI分類の場合は自動検出ラベルを付け、原文を変更しない。

読み終わり任意チェック：
- この論文が行ったことを選択肢で確認
- 正解競争ではなく、主旨をつかんだことを静かに示す

Why it matters：
- 初学者向け
- 研究者向け
- 応用上の意味
- 分野史上の位置づけ
AI生成であることを明示する。

## 9. 保存と再発見

右スワイプの既定は「気になる」。任意タグ：
- あとで読む
- 英語表現
- 数式
- 研究に関連
- なんとなく気になる

保存論文の状態：
- 未読
- Abstract確認中
- Abstract確認済み
- 原論文を開いた
- Focus中
- 読了
- アーカイブ

保存を墓場にしない再提示：
- 数日後に保存論文の表現を1件提示
- 数式ステップを1件提示
- Abstractの主旨確認
- 新しい版、正式出版、後続研究の通知
- 保存理由に応じて入口を変える

個人用学術英語辞典：
- 単語
- 連語
- 構文
- 一文
- 数式と説明
- 実際に読んだ論文の用例

成長表示：
- 読んだAbstract数
- 翻訳した割合
- 翻訳なしで読んだ割合
- 保存表現数
- 原論文を開いた数
評価や罰ではなく、次の学習設定提案につなげる。

## 10. 数式カードのプロダクト仕様

数式カード種別：
- DERIVATION：導出・式変形
- DEFINITION：定義
- PHYSICAL MEANING：物理的意味
- APPROXIMATION：近似
- CONSISTENCY CHECK：次元・極限・特別な場合
- NOTATION：記号
- CONNECTION：他理論との接続

カード入口：
- 保存した論文に数式カードがある場合に通知
- Discoverフィードへ低頻度で混ぜる
- Learnから復習
- Canvas上の独立タイル

Focus Mode：
数式を中央に大きく表示し、周囲を暗くする。下部に次のタブを置く。
- 記号
- 構造
- 導出
- 意味
- 極限

導出表示：
- Step 1, Step 2として縦に展開
- 式間の矢印をタップすると中間式を開く
- 最短 / 標準 / 一行ずつ / 初学者向け
- 詳細度スライダー
- 各操作にWhy?ボタン

記号タップ：
- この論文での意味
- 一般的な意味
- 最初の定義位置
- 単位・次元
- 適用スコープ：式 / 節 / 論文 / 分野

理解チェック：
- 穴埋め
- 次の一手
- 物理的意味
- 次元整合性
- 非相対論的極限など
派手な点数化はせず、整合性と理解の確認を重視する。

## 11. LaTeXと数式レンダリング

正規データはLaTeX文字列とする。PNGやSVGを正本にしない。

表示方式：
- 通常はKaTeX
- 非対応マクロや環境はMathJaxへフォールバック
- 失敗時は整形済みLaTeXソースと原文リンク
- SNS共有時のみ画像生成可能

必要機能：
- インライン / ディスプレイ
- MathML併記
- コピー
- LaTeXコピー
- 記号タップ領域
- 横スクロール
- タップで全画面
- フォント拡大
- スクリーンリーダー用説明

数式の由来ラベル：
- Original：原論文の式
- Verified step：機械的に検証済みの補完
- AI explanation：AI説明
- Assumption：追加仮定
- Human reviewed：人手確認済み

色だけでなくアイコンと文字ラベルを使う。

規約設定：
- 計量符号：原論文に従う / (+---) / (-+++)
- 単位系：SI / Gaussian / Heaviside-Lorentz / 自然単位 / 幾何単位
原式を勝手に変換しない。ユーザー設定と異なる場合は注意を出す。将来の変換表示は参考表示として原式と並べる。

## 12. 数式抽出・説明パイプライン

対象は、利用条件を確認でき、構造化本文またはLaTeXソースを合法的に取得できる論文に限定する。

パイプライン：
1. 文書、ライセンス、識別子、版を取得。
2. LaTeXまたは構造化XMLを解析。
3. display math、式番号、前後段落を抽出。
4. 参照される式、定義、仮定を解決。
5. 記号表を作る。
6. 連続する式の関係を分類。
7. 中間変形候補を生成。
8. 数式処理、数値代入、次元解析、極限で検証。
9. 原文由来と補完を分離して保存。
10. 必要なカードのみ人手レビューへ送る。

検証状態：
- source_exact
- mechanically_verified
- dimensionally_checked
- numerically_spot_checked
- human_reviewed
- unverified

未検証の変形は既定で非表示。AI説明は数式的真偽を保証しないことを明示する。

## 13. Knowledge Canvas

目的：保存論文、数式、概念、英語表現を意味空間上の美しいタイルとして表示し、自分の知的関心を眺め、探索できるようにする。

表現：
- 位置：意味ベクトルの近さ
- 色：研究分野の重み付き混合
- サイズ：個人的な関心・操作量
- 明るさ：最近の活動
- 境界：読書状態や種類
- 距離：意味的な近さ
- 背景面：分野クラスタ

高次元ベクトルを2次元へ写像するが、座標は安定させる。
- 新規論文は近い領域に加える
- 全体再配置を最小化
- 手動配置を尊重
- 配置アルゴリズムの版を保持

個人的重み候補：
- 保存強度
- 滞在時間
- 再訪回数
- 翻訳回数
- 数式展開回数
- 明示的重要度
サイズは対数圧縮して極端な差を防ぐ。

色：
- 分野ごとの基準色
- 複数分野は知覚的色空間でグラデーション
- RGB単純平均を避ける
- 分野以外に年、状態、英語難易度、数式密度へ切替可能

ズーム：
- 遠景：分野島と件数
- 中景：論文タイルとキーワード
- 近景：タイトル、著者、年、保存理由
- 最接近：Abstractと翻訳履歴

選択：
- タイルが約1.15倍で浮く
- 周囲が少し離れる
- 背景が暗くなる
- 関連論文が穏やかに強調
- 基礎、対立、後続、類似を方向別に表示

Canvasスタイル：
- Mosaic：色付きタイル
- Constellation：星と関係線
- Landscape：分野の島・地形
- Spectrum：時系列の色帯
MVP後の最初はMosaicを実装する。

## 14. Organized Library

Canvasと同じ保存データを、検索・管理に適した整然UIで表示する。

レイアウト：
- Compact list
- Detailed list
- Grid
- Grouped by field

グループ：
- 分野
- 保存理由
- 読書状態
- 年
- 著者
- コレクション
- 数式カード有無

並べ替え：
- 最近保存
- 最近閲覧
- 関心度
- 発表日
- 推定読了時間
- 英語難易度
- 数式密度
- 未読優先

Canvasとの切替：
- 選択中のタイルがLibraryの該当行へ連続変形
- 逆方向も位置関係を失わない
- Reduce Motionではフェードまたは即時切替

## 15. アーティスティックUIの詳細

タイル形状：
- 論文：角丸長方形
- 数式：正方形に近い
- 英語表現：細長い
- 著者：円ノード
- コレクション：半透明領域
主役は論文と数式に絞る。

Canvas内フィルター：
- 分野
- 年
- 未読
- 数式あり
- OA
対象外は既定で半透明。必要なら非表示。

時間表示：
- 年月スライダーで保存履歴を再生
- 関心領域の拡大を客観的に表示

未探索領域：
- 保存論文に近いが未探索の分野を淡い輪郭で提示
- タップすると3件だけ提案

手動編集：
- ドラッグ
- ピン留め
- コレクション化
- 名前付け
- メモ
- 重要式を中央配置
- 意味上の元位置を補助表示

共有：
- 選択範囲を画像として書き出し
- タイトル、著者、年、メモの含有を選択
- 閲覧履歴や私的メモを既定で除外

## 16. 推薦と重複排除

同一論文の正規化優先順位：
1. DOI
2. arXiv ID
3. Semantic Scholar Paper ID
4. OpenAlex Work ID
5. 正規化タイトル + 第一著者 + 年

正規化：
- 小文字化
- Unicode正規化
- 記号・余分空白の整理
- LaTeX命令の正規化
- プレプリントと出版版の関連付け
- 版情報保持

一度表示した論文は原則再表示しない。再投入条件：
- 設定した期間経過
- スキップのみ
- 翻訳や長時間閲覧なし
- 復習モード

候補スコア概念：
interest match + quality + freshness + difficulty fit + exploration bonus - recent similarity - repeated author penalty

配合の既定値：
- 70% 選択分野と関心に合う
- 20% 隣接分野
- 10% 未知の探索

多様性制御：
- 直近20件との意味類似ペナルティ
- 同一著者・研究グループの連続抑制
- 同一テーマの連続抑制
- 理論 / 実験 / レビューのバランス

フィードバック：
- この話題を減らす
- この著者をしばらく表示しない
- 類似論文を減らす
- 実験系を増やす
- 古典的論文を増やす

否定的フィードバックを「嫌い」と決めつけない。「今回は見送る」として扱う。

## 17. 論文関係と探索

保存論文の周辺を役割で整理する。
- Related work：類似問題
- Contrasting work：異なる結論や方法
- Foundational work：基礎となる研究
- Follow-up work：後続研究

単なる類似度だけで関係ラベルを断定しない。引用方向、公開日、本文中の言及、モデル分類の根拠を保持する。

原論文を読む目的別ルート：
- 全体を知る
- 数式を追う
- 結果だけ見る
- 引用に使えるか確認

推奨ルート例：Abstract → Figure 1 → Introduction 1～3段落 → Eq. 7 → Conclusion。

## 18. 初回設定と詳細設定

初回に聞くのは5項目：
1. 研究分野
2. 論文種別
3. 英語レベル
4. 数式レベル
5. 推薦の冒険度

研究分野の強さ：
- メイン
- ときどき
- 偶然の出会い

論文種別：
- 原著
- レビュー
- 講義ノート
- 学会予稿
- プレプリント
- 出版済み
- 古典的
- 最近

数式レベル：
- Level 0：表示しない
- Level 1：記号と意味
- Level 2：主要3～5段階
- Level 3：省略計算
- Level 4：仮定・定理・近似・検証

詳細設定：
- 翻訳スタイル
- 初期翻訳タブ
- 数式表示サイズ
- 長い式の横スクロール / 全画面
- 計量規約と単位系
- 再表示期間
- 類似論文間隔
- 時代バランス
- スワイプ感度
- 触覚フィードバック
- Canvasスタイル
- タイルサイズ・色の意味
- アニメーション強度
- 通知頻度
- オフライン件数

## 19. デザインシステム

視覚キーワード：静か、知的、触りたくなる、数式が美しい。

ライト：
- Background #F5F6F8
- Card #FFFFFF
- Primary Text #17202A
- Secondary #667085
- Accent #2F6FED
- Saved #19A974
- Formula Surface #F0F4FF
- Translation #EEF8F4
- Warning #D68C24

ダーク：
- Background #0D1117
- Card #151B24
- Primary #EDF2F7
- Secondary #98A2B3
- Accent #78A6FF
- Formula #182033
- Translation #102820

書体：
- UI：Inter / Noto Sans JP
- タイトル・Abstract：Source Serif 4 またはLiterata
- 数式：STIX Two MathまたはKaTeX既定

余白：
- 画面左右20
- カード内24
- 段落間16
- Abstract 17px、行間1.6前後
- タイトル24px前後

動き：
- 保存時は軽い触覚と収納アニメーション
- スキップは落ち着いた反応
- Canvasは常時漂わせず、選択時だけ反応
- Reduce Motion対応

## 20. アクセシビリティ

- スワイプと同等のボタン操作を用意。
- 色だけで分野、状態、信頼度を表現しない。
- タイルにラベル、模様、アイコン、位置を併用。
- Dynamic Typeと画面拡大。
- 数式のMathMLと読み上げ説明。
- フォーカス順序を論理的にする。
- 翻訳ボトムシートのフォーカストラップ。
- 触覚を無効化可能。
- Reduce Motionで連続変形を短いフェードへ。
- 高コントラストテーマ。
- 長押しだけに機能を隠さない。

## 21. データソースと権利設計

初期は物理・数学・情報系のオープンなメタデータを中心にする。

推奨役割：
- arXiv：タイトル、著者、Abstract、カテゴリ、版、原文リンク。利用規約と謝辞を遵守。
- OpenAlex：候補発見、分野、著者、機関、OA、識別子、重複統合。
- Semantic Scholar：引用・参考文献、推薦、類似、補助識別子。
- Crossref：DOIと書誌情報。Abstractは権利が異なり得るため無条件再配布しない。

各レコードに保存：
- source provider
- acquired_at
- source_url
- canonical identifiers
- license metadata
- content provenance
- cache policy
- deletion or correction status

原則：
- 出版社サイトをスクレイピングしない。
- 原文リンクを明示。
- ライセンス不明の本文断片を数式カード化しない。
- 商用化前に利用規約と権利を個別確認。
- 削除・訂正・撤回情報を反映できる。

参考：
- arXiv API Access: https://info.arxiv.org/help/api/index.html
- OpenAlex API: https://developers.openalex.org/api-reference/introduction
- Semantic Scholar API: https://www.semanticscholar.org/product/api
- Crossref REST API: https://www.crossref.org/documentation/retrieve-metadata/rest-api/

## 22. 推奨アーキテクチャ

モノレポ構成例：

apps/mobile
- Expo / React Native / TypeScript
- Expo Router
- TanStack Query
- ZustandまたはRedux Toolkit
- Reanimated + Gesture Handler
- WebView上のKaTeX / MathJax

apps/api
- FastAPIまたはNestJS
- RESTまたは型付きRPC
- OpenAPI生成
- 認証、フィード、保存、翻訳、検索、Canvas座標

workers
- metadata ingestion
- normalization and deduplication
- topic classification
- difficulty scoring
- embeddings
- relation extraction
- math parsing and verification

packages
- shared types
- design tokens
- API client
- ranking
- LaTeX utilities
- provenance labels

storage
- PostgreSQL + pgvector
- Redis for queues and cache
- Object storage for allowed source artifacts and generated share images

observability
- structured logs
- traces
- error reporting
- provider latency and quota metrics

外部機能はinterfacesで抽象化：
PaperProvider, TranslationProvider, EmbeddingProvider, ExplanationProvider, MathVerifier, FullTextProvider。

## 23. 主要データモデル

User：locale, timezone, accessibility, settings。
Interest：field_id, strength, mode。
Paper：canonical_id, title, abstract, authors, year, venue, identifiers, source, license, version, retraction_status。
PaperTopic：topic_id, weight。
PaperRelation：source_paper, target_paper, relation_type, confidence, evidence。
Impression：user, paper, shown_at, position, feed_context, dwell_time。
Action：skip, save, open_source, translate, expand_math, hide_topic, undo。
SavedPaper：reason, status, priority, notes。
TextSelection：start/end offsets, exact text hash, context, action。
Translation：original, translated, style, provider, model, created_at, math_placeholders。
ExpressionCard：phrase, meaning, examples, source_paper。
Equation：latex, equation_number, section, source_type, provenance, license。
EquationSymbol：symbol, local meaning, definition location, unit, scope。
DerivationStep：from_equation, to_equation, latex, operation, rationale, verification_status。
MathCard：type, title, level, source_equations, review_status。
Embedding：entity_type, entity_id, model, vector, version。
CanvasPosition：entity, x, y, cluster, layout_version, user_override。
Collection：name, style, items。
ReviewEvent：human reviewer, decision, notes。

すべてのAI生成物にprovider/model/prompt_version/input_hash/created_atを持たせる。

## 24. APIの概略

認証：
- POST /auth/guest
- POST /auth/login
- GET /me
- PATCH /me/settings

分野：
- GET /fields
- PUT /me/interests

フィード：
- GET /feed?mode=discover&cursor=...
- POST /impressions
- POST /actions
- POST /actions/{id}/undo

翻訳：
- POST /translations
- GET /translations/{id}
- POST /expressions

保存：
- GET /saved
- POST /saved/{paperId}
- PATCH /saved/{paperId}
- DELETE /saved/{paperId}

論文：
- GET /papers/{id}
- GET /papers/{id}/relations
- GET /papers/{id}/reading-path
- GET /papers/{id}/math-cards

数式：
- GET /math-cards/{id}
- POST /math-cards/{id}/feedback
- GET /equations/{id}/symbols

Canvas：
- GET /canvas?layout=mosaic&cursor=...
- PATCH /canvas/positions
- GET /canvas/timeline

検索：
- GET /search?q=...

応答にはprovenance、license、feature flags、verification statusを含める。

## 25. 非機能要件

性能：
- 次カードを事前取得し、通常操作で待ち時間を感じさせない。
- 画面表示後100ms以内にジェスチャー応答。
- 翻訳開始を即時表示し、ストリーミングまたは進行表示。
- Canvasは可視領域のみ描画し、クラスタリングで数千件に対応。

信頼性：
- 外部API失敗時もキャッシュ済みフィードを表示。
- Providerごとのサーキットブレーカー。
- 冪等な取り込みとジョブ。
- 版更新、撤回、削除の同期。

プライバシー：
- 選択英文やメモを学習利用する場合は明示同意。
- 共有画像から私的データを既定で除外。
- データのエクスポートと削除。
- 最小限の分析イベント。

セキュリティ：
- APIキーをクライアントへ置かない。
- 入力長制限とレート制限。
- LaTeXとHTMLのサニタイズ。
- WebViewのナビゲーション制限。
- PDF・ソース処理を隔離。

国際化：
- 初期は英語原文 + 日本語UI/翻訳。
- UI文字列は最初からi18n化。

## 26. オフラインと通知

オフライン：
- 次の20件を事前取得
- 保存Abstract
- 翻訳結果
- 数式カードのレンダリング資産
- PDFはユーザー明示操作でのみ保存

通知：
- 今日のAbstract 1件
- 重要な新着
- 保存論文の版更新・正式出版
- 復習待ち表現
- 新しい数式カード

プリセット：通知なし / 静か / 1日1回 / 平日のみ / 重要時のみ。

## 27. 分析指標

North Star候補：
「週内に、原文の一部を自力で読み、保存または原論文へ進んだ有意義なAbstractセッション数」

主要指標：
- カード表示から10秒以上読まれた割合
- 部分翻訳率と翻訳範囲長
- 保存率
- 原論文遷移率
- 保存後7日以内の再訪率
- Saved墓場率
- Undo率
- 連続類似カードに対するスキップ増加
- 数式カード完了率
- Canvasから論文詳細への遷移率

ガードレール：
- 全文に近い範囲の連続翻訳増加
- 同一ソースへの過剰APIアクセス
- AI説明の問題報告率
- 権利不明コンテンツ表示件数
- クラッシュ率とジェスチャー失敗率

## 28. 実装フェーズ

Phase 0：基盤
- モノレポ
- CI
- デザインtokens
- 認証の最小実装
- DB migrations
- Provider interfaces
- サンプルデータ

Phase 1：MVP
- 分野選択
- arXiv/OpenAlex中心の取り込み
- Abstractカード
- 左右スワイプ + ボタン
- Undo
- 範囲選択
- 翻訳ボトムシート
- 保存一覧
- 原文リンク
- DOI/arXiv重複排除
- ダークテーマ
- オフライン20件

Phase 2：学習体験
- 段階ヒント
- Abstract構造
- Why it matters
- 用語・表現保存
- 保存理由
- Learn
- 復習再提示
- 英語難易度

Phase 3：推薦
- 埋め込み
- 多様性スコア
- 探索枠
- 類似連続防止
- 著者連続防止
- 推薦理由
- フィード調整

Phase 4：数式
- KaTeX / MathJax
- Equation/Symbolモデル
- 手動作成した検証済み数式カード
- Focus Mode
- 詳細度
- Why操作
- 理解チェック

Phase 5：自動数式パイプライン
- 許諾済みLaTeX/XML取得
- 式・定義抽出
- 中間変形
- 検証
- レビューキュー

Phase 6：Canvas
- Mosaic
- 安定座標
- 分野グラデーション
- 浮遊選択
- Library連続変形
- フィルター
- クラスタズーム

Phase 7：高度探索
- Constellation / Landscape / Spectrum
- 基礎・対立・後続
- 読書ルート
- Timeline
- 数式知識グラフ
- 共有

## 29. MVP完了条件

- 初回設定から最初のカードまで完走できる。
- 100件以上の実データ候補からフィードを作れる。
- 同一DOI/arXivの重複カードが出ない。
- 表示履歴により同じ正規論文が再表示されない。
- 左右スワイプとボタン操作が同等に働く。
- Undoが機能する。
- 英文範囲を選び、選択範囲だけを翻訳できる。
- 数式を含む選択でLaTeXが壊れない。
- 保存・削除・状態変更が永続化される。
- 原文リンクと出典が表示される。
- ダークテーマ、文字拡大、Reduce Motionの基本対応。
- API障害時にキャッシュ済みカードを表示。
- テストとREADMEでローカル起動できる。

## 30. テスト戦略

単体：
- タイトル正規化
- DOI/arXiv統合
- フィードスコア
- 多様性ペナルティ
- 数式プレースホルダー復元
- provenance状態

統合：
- ProviderからDB取り込み
- 翻訳リクエスト
- 保存と履歴
- フィード再取得で非重複
- 版統合

E2E：
- オンボーディング
- スワイプ・Undo
- 範囲選択翻訳
- 保存一覧
- 原文遷移
- オフライン
- アクセシビリティ操作

数式：
- KaTeXレンダリングスナップショット
- フォールバック
- 長い式
- 危険なLaTeX入力
- MathML
- 記号タップ

Visual regression：
- ライト / ダーク
- 小画面 / 大画面
- 日本語長文
- Dynamic Type
- Reduce Motion
- Canvasの主要状態

## 31. Claude Code向け最初の実装タスク

最初のPRで実行すること：
1. Expo + TypeScriptのmobile、FastAPIまたはNestJSのapi、shared packagesを含むモノレポを作る。
2. PostgreSQL用スキーマとmigrationを作る。
3. PaperProvider interfaceとMockPaperProviderを作る。
4. 50件以上のサンプルAbstractをfixtureで読み込む。ただし公開リポジトリへ実在Abstract全文を同梱する場合は利用条件を確認し、難しければ短い合成fixtureとAPI接続手順を使う。
5. オンボーディング5画面を作る。
6. Abstractカードのスワイプデッキを作る。
7. ボタン操作とUndoを作る。
8. Savedの整然リストを作る。
9. 翻訳Provider interfaceとMockTranslationProviderを作る。
10. 英文選択からボトムシートへ渡す最小体験を作る。
11. light/dark、Reduce Motion、Dynamic Typeを確認する。
12. ユニット、統合、E2Eの最小テストとCIを作る。

PRを小さく分けること。各PRにスクリーンショット、動作確認手順、未実装点、設計判断を付ける。

## 32. 将来アイデア

- 自分の計量規約・単位系との比較表示
- arXiv版更新の数式差分
- 数式の系譜と知識グラフ
- 研究室・講義ごとの共有デッキ
- 人間レビュー済み数式カード
- 読書会モード
- Zotero/BibTeX/Obsidian連携
- 保存論文から研究ノート生成
- 音声でAbstractを聞き、選択箇所を確認
- 専門外から一枚
- 10-minute paper break
- 関心風景の年次アーカイブ

## 33. 最終的なプロダクト像

Discoverでは論文と偶然に出会う。部分翻訳は英語を置き換えず、読むための足場になる。保存した論文は英語表現や数式カードとして再び現れ、原論文へ進む道を作る。Libraryでは必要な論文を確実に探せる。Canvasでは、自由な色の風景が整然とした書架へ変形し、自分の知的関心の広がりを眺められる。

目指す状態は、単なる論文版マッチングアプリではない。

「以前は読めなかった英文や飛ばした数式が、次に出会ったときには少し読めるようになっている」

その変化を、静かで美しく、信頼できる形で積み重ねるアプリである。
