/**
 * Domain model shapes (spec section 23).
 *
 * The rule that drives this file: original text, machine translation, AI explanation,
 * mechanically verified derivations and human-reviewed content are distinguishable in
 * the type system, not merged into one opaque "content" blob (spec section 0).
 */
import type {
  AbstractSection,
  ActionType,
  DetectionMethod,
  CanvasStyle,
  EnglishLevel,
  ExplorationLevel,
  FeedReason,
  IdentifierKind,
  InterestMode,
  MathCardType,
  MathLevel,
  MetricSignature,
  OpenAccessStatus,
  PaperType,
  ProvenanceKind,
  RelationType,
  RetractionStatus,
  SaveReason,
  ExpressionKind,
  SavedStatus,
  SourceProvider,
  TranslationStage,
  TranslationStyle,
  UnitSystem,
  VerificationStatus,
} from './vocab.ts';

export type Iso8601 = string;
export type Uuid = string;

/**
 * Where a record came from and under what terms (spec section 21).
 * Every stored paper carries one; nothing is displayed without it.
 */
export interface SourceProvenance {
  sourceProvider: SourceProvider;
  acquiredAt: Iso8601;
  sourceUrl: string;
  /** SPDX id or provider-specific string; `null` means unknown, which restricts reuse. */
  licenseId: string | null;
  licenseUrl: string | null;
  /** True only when the terms allow storing the abstract text itself. */
  abstractRedistributable: boolean;
  cachePolicy: 'no_store' | 'metadata_only' | 'full_cache';
}

/** Stamped onto every AI-generated artefact (spec section 23, final line). */
export interface GenerationProvenance {
  provider: string;
  model: string;
  promptVersion: string;
  inputHash: string;
  createdAt: Iso8601;
}

export interface PaperIdentifier {
  kind: IdentifierKind;
  value: string;
}

export interface Author {
  name: string;
  /** ORCID or provider author id when known. */
  externalId?: string | null;
  affiliation?: string | null;
}

export interface AbstractSegment {
  start: number;
  end: number;
  section: AbstractSection;
  /** Section 8: detected structure is labelled with how it was found, and never edits
   * the original text. */
  detectedBy: DetectionMethod;
  confidence: number;
}

export interface Paper {
  id: Uuid;
  /** Section 16: `${kind}:${value}` of the highest-precedence identifier available. */
  canonicalId: string;
  identifiers: PaperIdentifier[];
  title: string;
  /** Original English text. Never overwritten by a translation. */
  abstract: string;
  abstractSegments?: AbstractSegment[];
  authors: Author[];
  year: number;
  venue: string | null;
  paperTypes: PaperType[];
  primaryFieldId: string;
  fieldWeights: Record<string, number>;
  openAccess: OpenAccessStatus;
  retractionStatus: RetractionStatus;
  /** arXiv version or publisher version string. */
  version: string | null;
  /** Section 16: preprint ↔ published linkage. */
  supersedesPaperId?: Uuid | null;
  englishLevel: EnglishLevel;
  /** Display equations per 1000 abstract characters, used for the 数式密度 badge. */
  mathDensity: number;
  equationCount: number;
  estimatedReadingMinutes: number;
  sourceUrl: string;
  pdfUrl: string | null;
  provenance: SourceProvenance;
}

export interface Interest {
  fieldId: string;
  /** 0..1 */
  strength: number;
  mode: InterestMode;
}

export interface UserSettings {
  locale: string;
  timezone: string;
  colorScheme: 'system' | 'light' | 'dark';
  englishLevel: EnglishLevel;
  mathLevel: MathLevel;
  exploration: ExplorationLevel;
  translationStyle: TranslationStyle;
  initialTranslationStage: TranslationStage;
  metricSignature: MetricSignature;
  unitSystem: UnitSystem;
  canvasStyle: CanvasStyle;
  reduceMotion: boolean;
  hapticsEnabled: boolean;
  highContrast: boolean;
  /** Section 26: how many cards to keep available offline. */
  offlinePrefetchCount: number;
  /** Section 16: days before a skipped paper may return. */
  reshowAfterDays: number;
  /** Section 25: opt-in, off by default. */
  allowSelectionsForModelImprovement: boolean;
}

export interface User {
  id: Uuid;
  isGuest: boolean;
  displayName: string | null;
  createdAt: Iso8601;
  settings: UserSettings;
  interests: Interest[];
  onboardingCompletedAt: Iso8601 | null;
}

export interface Impression {
  id: Uuid;
  paperId: Uuid;
  shownAt: Iso8601;
  position: number;
  feedContext: string;
  dwellMs: number | null;
}

export interface UserAction {
  id: Uuid;
  paperId: Uuid | null;
  type: ActionType;
  createdAt: Iso8601;
  /** Set when this action reverses another (spec section 6: Undo). */
  undoesActionId?: Uuid | null;
  payload?: Record<string, unknown>;
}

export interface SavedPaper {
  paperId: Uuid;
  reasons: SaveReason[];
  status: SavedStatus;
  priority: number;
  notes: string | null;
  savedAt: Iso8601;
  lastVisitedAt: Iso8601 | null;
}

/** Section 23: TextSelection — offsets plus a hash so the anchor survives re-fetches. */
export interface TextSelection {
  id: Uuid;
  paperId: Uuid;
  field: 'abstract' | 'title';
  start: number;
  end: number;
  exactText: string;
  exactTextHash: string;
  contextBefore: string;
  contextAfter: string;
  createdAt: Iso8601;
}

/** Section 7: inline maths is masked before translation and restored afterwards. */
export interface MathPlaceholder {
  token: string;
  latex: string;
  display: boolean;
}

export interface Translation {
  id: Uuid;
  selectionId: Uuid | null;
  /** The English source, kept verbatim. */
  original: string;
  translated: string;
  style: TranslationStyle;
  stage: TranslationStage;
  mathPlaceholders: MathPlaceholder[];
  generation: GenerationProvenance;
  createdAt: Iso8601;
  /**
   * True when a formula did not survive the provider round trip, so `translated` holds
   * the original text instead. A missing formula is invisible to the reader, which is why
   * this is surfaced rather than silently absorbed (spec section 7).
   */
  fellBackToOriginal: boolean;
}

/** Section 9: an entry in the reader's own academic-English dictionary. */
export interface ExpressionCard {
  id: Uuid;
  kind: ExpressionKind;
  phrase: string;
  meaning: string;
  examples: string[];
  sourcePaperId: Uuid | null;
  /** The sentence it was taken from, so the entry keeps its context. */
  context: string | null;
  createdAt: Iso8601;
  reviewCount: number;
  lastReviewedAt: Iso8601 | null;
  /** When this entry is next due (spec section 9: 数日後に1件提示). */
  nextReviewAt: Iso8601 | null;
}

/** Section 11: LaTeX is the canonical form. Images are never the record of truth. */
export interface Equation {
  id: Uuid;
  paperId: Uuid;
  latex: string;
  equationNumber: string | null;
  section: string | null;
  display: boolean;
  provenanceKind: ProvenanceKind;
  verificationStatus: VerificationStatus;
  /** Present only for AI-produced content. */
  generation?: GenerationProvenance | null;
  licenseId: string | null;
}

export interface EquationSymbol {
  id: Uuid;
  equationId: Uuid;
  symbol: string;
  localMeaning: string;
  generalMeaning: string | null;
  definedInEquationId: Uuid | null;
  unit: string | null;
  scope: 'equation' | 'section' | 'paper' | 'field';
  provenanceKind: ProvenanceKind;
}

export interface DerivationStep {
  id: Uuid;
  fromEquationId: Uuid;
  toEquationId: Uuid;
  latex: string;
  operation: string;
  rationale: string;
  verificationStatus: VerificationStatus;
  provenanceKind: ProvenanceKind;
  generation?: GenerationProvenance | null;
}

export interface MathCard {
  id: Uuid;
  type: MathCardType;
  title: string;
  level: MathLevel;
  sourceEquationIds: Uuid[];
  reviewStatus: 'draft' | 'in_review' | 'approved' | 'rejected';
  provenanceKind: ProvenanceKind;
}

export interface PaperRelation {
  sourcePaperId: Uuid;
  targetPaperId: Uuid;
  relationType: RelationType;
  confidence: number;
  /** Section 17: never assert a relation from similarity alone. */
  evidence: {
    citationDirection?: 'cites' | 'cited_by' | 'none';
    publicationOrder?: 'before' | 'after' | 'same';
    mentionSnippet?: string | null;
    similarity?: number;
    model?: string | null;
  };
}

export interface Embedding {
  entityType: 'paper' | 'equation' | 'expression';
  entityId: Uuid;
  model: string;
  vector: number[];
  version: string;
}

export interface CanvasPosition {
  entityType: 'paper' | 'equation' | 'expression';
  entityId: Uuid;
  x: number;
  y: number;
  clusterId: string | null;
  layoutVersion: string;
  /** Section 13: manual placement is respected across re-layouts. */
  userOverride: boolean;
}

export interface Collection {
  id: Uuid;
  name: string;
  style: string | null;
  itemIds: Uuid[];
}

export interface ReviewEvent {
  id: Uuid;
  entityType: 'math_card' | 'derivation_step' | 'equation';
  entityId: Uuid;
  reviewerId: Uuid;
  decision: 'approved' | 'rejected' | 'needs_changes';
  notes: string | null;
  createdAt: Iso8601;
}

/** Which of the 70/20/10 pools a card was drawn from (spec section 16). */
export type FeedPool = 'matched' | 'adjacent' | 'exploration';

/** Section 6: the card shows why it was recommended, in words. */
export interface FeedItem {
  paper: Paper;
  reasons: FeedReason[];
  /** Short human-readable sentence, already localised by the API. */
  reasonText: string;
  position: number;
  pool: FeedPool;
  /**
   * Score components. Present so a surprising ranking can be explained; the UI shows
   * `reasonText`, never these numbers (spec section 6: 単一の不透明なスコアだけを見せない).
   */
  scoreBreakdown: Record<string, number>;
}
