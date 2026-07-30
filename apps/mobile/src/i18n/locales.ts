/**
 * UI strings.
 *
 * Spec section 25: UI文字列は最初からi18n化する. Even in Phase 0, with only the Japanese
 * UI shipping, no visible string is written inline in a component — otherwise the
 * translation pass later becomes an audit of every file.
 */
export const LOCALES = ['ja', 'en'] as const;
export type Locale = (typeof LOCALES)[number];

export const messages = {
  ja: {
    'app.name': 'PaperMatch',
    'app.tagline': '論文と出会い、少しずつ読めるようになる',

    'nav.discover': 'さがす',
    'nav.saved': '保存',
    'nav.learn': '学ぶ',
    'nav.profile': '設定',

    'status.title': 'Phase 0 の状態',
    'status.description':
      'この画面は基盤の確認用です。オンボーディングとスワイプデッキは Phase 1 で追加します。',
    'status.api': 'API 接続',
    'status.api.ok': '接続できています',
    'status.api.degraded': '一部の機能が低下しています',
    'status.api.offline': 'API に接続できません（キャッシュ表示に切り替わります）',
    'status.retry': '再試行',
    'status.papers': 'サンプル論文',
    'status.papersLoaded': '{count} 件を読み込みました',
    'status.theme': '表示テーマ',
    'status.reduceMotion': 'アニメーション軽減',
    'status.fontScale': '文字サイズ倍率',
    'status.on': 'オン',
    'status.off': 'オフ',

    'theme.system': '端末に合わせる',
    'theme.light': 'ライト',
    'theme.dark': 'ダーク',

    'provenance.original': '原論文の式',
    'provenance.verifiedStep': '検証済みの補完',
    'provenance.aiExplanation': 'AI による説明',
    'provenance.assumption': '追加の仮定',
    'provenance.humanReviewed': '人手で確認済み',

    'paper.openAccess': 'オープンアクセス',
    'paper.source': '出典',
    'paper.license': 'ライセンス',
    'paper.licenseUnknown': 'ライセンス不明',
    'paper.readingMinutes': '約 {minutes} 分',

    'a11y.skipButton': 'この論文を見送る',
    'a11y.saveButton': 'この論文を保存する',
    'a11y.openSourceButton': '原論文を開く',
    'a11y.undoButton': '直前の操作を取り消す',
  },
  en: {
    'app.name': 'PaperMatch',
    'app.tagline': 'Meet papers, and read a little more of them each time',

    'nav.discover': 'Discover',
    'nav.saved': 'Saved',
    'nav.learn': 'Learn',
    'nav.profile': 'Profile',

    'status.title': 'Phase 0 status',
    'status.description':
      'This screen verifies the foundation. Onboarding and the swipe deck arrive in Phase 1.',
    'status.api': 'API connection',
    'status.api.ok': 'Connected',
    'status.api.degraded': 'Running degraded',
    'status.api.offline': 'Cannot reach the API (cached content would be shown)',
    'status.retry': 'Retry',
    'status.papers': 'Sample papers',
    'status.papersLoaded': 'Loaded {count}',
    'status.theme': 'Theme',
    'status.reduceMotion': 'Reduce Motion',
    'status.fontScale': 'Font scale',
    'status.on': 'On',
    'status.off': 'Off',

    'theme.system': 'Match device',
    'theme.light': 'Light',
    'theme.dark': 'Dark',

    'provenance.original': 'Original equation',
    'provenance.verifiedStep': 'Verified step',
    'provenance.aiExplanation': 'AI explanation',
    'provenance.assumption': 'Assumption',
    'provenance.humanReviewed': 'Human reviewed',

    'paper.openAccess': 'Open access',
    'paper.source': 'Source',
    'paper.license': 'Licence',
    'paper.licenseUnknown': 'Licence unknown',
    'paper.readingMinutes': 'About {minutes} min',

    'a11y.skipButton': 'Skip this paper',
    'a11y.saveButton': 'Save this paper',
    'a11y.openSourceButton': 'Open the original paper',
    'a11y.undoButton': 'Undo the last action',
  },
} as const;

export type MessageKey = keyof (typeof messages)['ja'];
