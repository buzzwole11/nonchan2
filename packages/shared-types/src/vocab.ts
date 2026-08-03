/**
 * Cross-language vocabularies.
 *
 * `enums.json` at the package root is the source of truth: the Python API loads the
 * same file. TypeScript cannot derive literal unions from a JSON import, so the lists
 * below restate the values as `as const` tuples and `vocab.test.ts` asserts — value by
 * value, in order — that they match the JSON. Adding a value means editing both, and
 * the test fails loudly if only one side is edited.
 */
import enums from '../enums.json' with { type: 'json' };

/** Raw JSON document, including the `$note` provenance comments. */
export const vocabularies = enums;

/** Section 16: canonical-id precedence, highest first. */
export const IDENTIFIER_KINDS = [
  'doi',
  'arxiv',
  'semantic_scholar',
  'openalex',
  'title_author_year',
] as const;

export const SOURCE_PROVIDERS = [
  'arxiv',
  'openalex',
  'semantic_scholar',
  'crossref',
  'mock',
  'manual',
] as const;

export const PAPER_TYPES = [
  'original',
  'review',
  'lecture_notes',
  'conference_paper',
  'preprint',
  'published',
  'classic',
  'recent',
  'theoretical',
  'experimental',
] as const;

export const OPEN_ACCESS_STATUSES = [
  'gold',
  'green',
  'hybrid',
  'bronze',
  'closed',
  'unknown',
] as const;

export const RETRACTION_STATUSES = [
  'none',
  'corrected',
  'concern_expressed',
  'withdrawn',
  'retracted',
] as const;

export const ENGLISH_LEVELS = ['beginner', 'intermediate', 'advanced', 'native_like'] as const;

export const MATH_LEVELS = ['level_0', 'level_1', 'level_2', 'level_3', 'level_4'] as const;

export const EXPLORATION_LEVELS = ['focused', 'balanced', 'adventurous'] as const;

export const INTEREST_MODES = ['main', 'occasional', 'serendipity'] as const;

export const ABSTRACT_SECTIONS = [
  'background',
  'problem',
  'method',
  'result',
  'significance',
] as const;

/**
 * Section 8: how a structural label was produced. A rule-based pass is `heuristic`, not
 * `ai` — labelling it `ai` would claim more for the label than it is worth.
 */
export const DETECTION_METHODS = ['source', 'heuristic', 'ai', 'human'] as const;

export const SAVE_REASONS = [
  'interesting',
  'read_later',
  'english_expression',
  'math',
  'research_related',
  'vague_interest',
] as const;

/** Section 9: 個人用学術英語辞典 — 単語 / 連語 / 構文 / 一文. */
export const EXPRESSION_KINDS = ['word', 'collocation', 'pattern', 'sentence'] as const;

/** Section 9/10: 派手な点数化はせず — the review answer is binary and unscored. */
export const REVIEW_OUTCOMES = ['again', 'got_it'] as const;

export const SAVED_STATUSES = [
  'unread',
  'abstract_in_progress',
  'abstract_done',
  'source_opened',
  'focus',
  'finished',
  'archived',
] as const;

export const ACTION_TYPES = [
  'skip',
  'save',
  'open_source',
  'translate',
  'expand_math',
  'hide_topic',
  'hide_author',
  'less_similar',
  'more_experimental',
  'more_classic',
  'undo',
] as const;

export const REPORT_REASONS = [
  'formula_differs_from_paper',
  'step_wrong',
  'explanation_wrong',
  'symbol_wrong',
  'rendering_broken',
  'other',
] as const;

export const REPORT_STATUSES = ['new', 'triaged', 'resolved'] as const;

export const FEED_REASONS = [
  'similar_to_saved',
  'matches_field',
  'adjacent_field',
  'foundational',
  'recent',
] as const;

export const TRANSLATION_STYLES = [
  'natural',
  'faithful',
  'literal',
  'academic',
  'plain_japanese',
] as const;

export const TRANSLATION_STAGES = [
  'hard_words',
  'sentence_skeleton',
  'phrase_structure',
  'literal',
  'natural',
  'domain_meaning',
] as const;

export const PROVENANCE_KINDS = [
  'original',
  'verified_step',
  'ai_explanation',
  'assumption',
  'human_reviewed',
] as const;

export const VERIFICATION_STATUSES = [
  'source_exact',
  'mechanically_verified',
  'dimensionally_checked',
  'numerically_spot_checked',
  'human_reviewed',
  'unverified',
] as const;

export const MATH_CARD_TYPES = [
  'derivation',
  'definition',
  'physical_meaning',
  'approximation',
  'consistency_check',
  'notation',
  'connection',
] as const;

export const RELATION_TYPES = ['related', 'contrasting', 'foundational', 'follow_up'] as const;

export const CANVAS_STYLES = ['mosaic', 'constellation', 'landscape', 'spectrum'] as const;

export const METRIC_SIGNATURES = ['as_published', 'mostly_minus', 'mostly_plus'] as const;

export const UNIT_SYSTEMS = [
  'si',
  'gaussian',
  'heaviside_lorentz',
  'natural',
  'geometric',
] as const;

export type IdentifierKind = (typeof IDENTIFIER_KINDS)[number];
export type SourceProvider = (typeof SOURCE_PROVIDERS)[number];
export type PaperType = (typeof PAPER_TYPES)[number];
export type OpenAccessStatus = (typeof OPEN_ACCESS_STATUSES)[number];
export type RetractionStatus = (typeof RETRACTION_STATUSES)[number];
export type EnglishLevel = (typeof ENGLISH_LEVELS)[number];
export type MathLevel = (typeof MATH_LEVELS)[number];
export type ExplorationLevel = (typeof EXPLORATION_LEVELS)[number];
export type InterestMode = (typeof INTEREST_MODES)[number];
export type AbstractSection = (typeof ABSTRACT_SECTIONS)[number];
export type DetectionMethod = (typeof DETECTION_METHODS)[number];
export type ExpressionKind = (typeof EXPRESSION_KINDS)[number];
export type ReviewOutcome = (typeof REVIEW_OUTCOMES)[number];
export type SaveReason = (typeof SAVE_REASONS)[number];
export type ReportReason = (typeof REPORT_REASONS)[number];
export type ReportStatus = (typeof REPORT_STATUSES)[number];
export type SavedStatus = (typeof SAVED_STATUSES)[number];
export type ActionType = (typeof ACTION_TYPES)[number];
export type FeedReason = (typeof FEED_REASONS)[number];
export type TranslationStyle = (typeof TRANSLATION_STYLES)[number];
export type TranslationStage = (typeof TRANSLATION_STAGES)[number];
export type ProvenanceKind = (typeof PROVENANCE_KINDS)[number];
export type VerificationStatus = (typeof VERIFICATION_STATUSES)[number];
export type MathCardType = (typeof MATH_CARD_TYPES)[number];
export type RelationType = (typeof RELATION_TYPES)[number];
export type CanvasStyle = (typeof CANVAS_STYLES)[number];
export type MetricSignature = (typeof METRIC_SIGNATURES)[number];
export type UnitSystem = (typeof UNIT_SYSTEMS)[number];

/** Every `as const` tuple keyed by its `enums.json` key, for the parity test. */
export const VOCABULARY_TUPLES: Record<string, readonly string[]> = {
  identifierKind: IDENTIFIER_KINDS,
  sourceProvider: SOURCE_PROVIDERS,
  paperType: PAPER_TYPES,
  openAccessStatus: OPEN_ACCESS_STATUSES,
  retractionStatus: RETRACTION_STATUSES,
  englishLevel: ENGLISH_LEVELS,
  mathLevel: MATH_LEVELS,
  explorationLevel: EXPLORATION_LEVELS,
  interestMode: INTEREST_MODES,
  abstractSection: ABSTRACT_SECTIONS,
  detectionMethod: DETECTION_METHODS,
  saveReason: SAVE_REASONS,
  reportReason: REPORT_REASONS,
  reportStatus: REPORT_STATUSES,
  expressionKind: EXPRESSION_KINDS,
  reviewOutcome: REVIEW_OUTCOMES,
  savedStatus: SAVED_STATUSES,
  actionType: ACTION_TYPES,
  feedReason: FEED_REASONS,
  translationStyle: TRANSLATION_STYLES,
  translationStage: TRANSLATION_STAGES,
  provenanceKind: PROVENANCE_KINDS,
  verificationStatus: VERIFICATION_STATUSES,
  mathCardType: MATH_CARD_TYPES,
  relationType: RELATION_TYPES,
  canvasStyle: CANVAS_STYLES,
  metricSignature: METRIC_SIGNATURES,
  unitSystem: UNIT_SYSTEMS,
};

/**
 * Verification states that may be surfaced without an explicit opt-in.
 * Spec section 12: 未検証の変形は既定で非表示.
 */
export const DEFAULT_VISIBLE_VERIFICATION_STATUSES: readonly VerificationStatus[] = [
  'source_exact',
  'mechanically_verified',
  'dimensionally_checked',
  'numerically_spot_checked',
  'human_reviewed',
];

export function isVisibleByDefault(status: VerificationStatus): boolean {
  return DEFAULT_VISIBLE_VERIFICATION_STATUSES.includes(status);
}
