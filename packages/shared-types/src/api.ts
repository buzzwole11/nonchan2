/**
 * HTTP contract shapes (spec section 24).
 *
 * Phase 0 implements the auth, fields and papers slices. Later phases fill in feed,
 * translations, saved, math cards and canvas; the request/response shapes are declared
 * here first so the client and the API move together.
 */
import type {
  ExpressionCard,
  FeedItem,
  Interest,
  Iso8601,
  Paper,
  RelationBasis,
  RelationEvidence,
  SavedPaper,
  Translation,
  User,
  UserSettings,
  Uuid,
} from './models.ts';
import type {
  ActionType,
  ExpressionKind,
  MathCardType,
  MathLevel,
  ProvenanceKind,
  RelationType,
  ReportReason,
  ReviewOutcome,
  SaveReason,
  SavedStatus,
  TranslationStage,
  TranslationStyle,
  VerificationStatus,
} from './vocab.ts';

/** Uniform error body for every non-2xx response. */
export interface ApiError {
  error: {
    code: string;
    message: string;
    /** Field-level detail for 422s. */
    details?: Record<string, string[]>;
  };
}

export interface AuthTokenResponse {
  accessToken: string;
  tokenType: 'bearer';
  expiresIn: number;
  user: User;
}

export interface GuestAuthRequest {
  locale?: string;
  timezone?: string;
}

export interface Field {
  id: string;
  parentId: string | null;
  label: { en: string; ja: string };
  /** Base colour for canvas tiles (spec section 13). */
  color: string;
  paperCount: number;
}

export interface FieldsResponse {
  fields: Field[];
}

export interface UpdateInterestsRequest {
  interests: Interest[];
}

export interface UpdateSettingsRequest {
  settings: Partial<UserSettings>;
}

export interface PaperListResponse {
  papers: Paper[];
  nextCursor: string | null;
}

export interface FeedResponse {
  items: FeedItem[];
  nextCursor: string | null;
  /** True when served from cache because a provider was unavailable (spec section 25). */
  degraded: boolean;
}

// ------------------------------------------------------------- impressions and actions

export interface ImpressionIn {
  paperId: string;
  position?: number;
  feedContext?: string;
  /** Reported when the card leaves the screen; feeds the re-injection rule (section 16). */
  dwellMs?: number | null;
}

export interface CreateImpressionsRequest {
  impressions: ImpressionIn[];
}

export interface CreateImpressionsResponse {
  recorded: number;
}

export interface CreateActionRequest {
  type: ActionType;
  paperId?: string | null;
  payload?: Record<string, unknown>;
}

export interface ActionOut {
  id: string;
  type: ActionType;
  paperId: string | null;
  createdAt: Iso8601;
  undone: boolean;
  undoesActionId: string | null;
  payload: Record<string, unknown>;
}

export interface ActionResponse {
  action: ActionOut;
  /** Present when the action changed the saved library. */
  saved: SavedPaper | null;
}

export interface UndoResponse {
  undo: ActionOut;
  undoneActionId: string;
  /** Eligible for the feed again, so the client can put the card back on the deck. */
  restoredPaperId: string | null;
}

export interface CreateTranslationRequest {
  paperId: string;
  selection: { field: 'abstract' | 'title'; start: number; end: number; exactText: string };
  style: TranslationStyle;
  stage: TranslationStage;
}

export interface CreateTranslationResponse {
  translation: Translation;
}

export interface SavedEntry {
  savedPaper: SavedPaper;
  paper: Paper;
}

export interface SavedListResponse {
  saved: SavedEntry[];
  nextCursor: string | null;
  /** Total matching the filters, not just this page — the Library shows a count. */
  total: number;
}

/** Sort keys for the Library View (spec section 14: 並べ替え). */
export const SAVED_SORT_KEYS = [
  'recently_saved',
  'recently_visited',
  'year',
  'reading_time',
  'english_level',
  'math_density',
  'unread_first',
] as const;

export type SavedSortKey = (typeof SAVED_SORT_KEYS)[number];

export interface SavedListQuery {
  status?: SavedStatus;
  reason?: SaveReason;
  fieldId?: string;
  sort?: SavedSortKey;
  limit?: number;
  cursor?: string;
}

export interface SavePaperRequest {
  reasons?: SaveReason[];
  notes?: string | null;
}

/**
 * Which field a search hit matched on, strongest first (spec section 24).
 *
 * Shown next to the result for the same reason a feed card carries its reason (section 6):
 * a hit with no visible cause looks like the search is guessing.
 */
export const SEARCH_MATCH_FIELDS = ['title', 'author', 'venue', 'note', 'abstract'] as const;

export type SearchMatchField = (typeof SEARCH_MATCH_FIELDS)[number];

export interface SearchHit {
  savedPaper: SavedPaper;
  paper: Paper;
  matchedField: SearchMatchField;
}

export interface SearchResponse {
  query: string;
  hits: SearchHit[];
  /**
   * True when the reader has not typed anything yet. Distinct from `hits: []` with a real
   * query, which means "searched, found nothing" — the two need different screens.
   */
  emptyQuery: boolean;
}

/**
 * One relation around a paper, with what produced it (spec section 17).
 *
 * `basis` is duplicated out of `evidence` because it is what the UI renders — the reader is
 * told "cited in the references" or "the paper says so", never a bare confidence number.
 */
export interface PaperRelationHit {
  relationType: RelationType;
  confidence: number;
  basis: RelationBasis;
  evidence: RelationEvidence;
  paper: Paper;
}

export interface PaperRelationsResponse {
  paperId: Uuid;
  /**
   * Empty when the evidence supports nothing. That is a real answer and the client says so:
   * falling back to "papers that look similar" is the one thing section 17 forbids.
   */
  relations: PaperRelationHit[];
}

export interface SavedPaperResponse {
  savedPaper: SavedPaper;
  paper: Paper;
}

export interface UpdateSavedRequest {
  status?: SavedStatus;
  reasons?: SaveReason[];
  notes?: string | null;
  priority?: number;
}

// ----------------------------------------------------------------------------- learn

export interface CreateExpressionRequest {
  phrase: string;
  meaning?: string;
  /** Omit to let the API work it out from the phrase. */
  kind?: ExpressionKind;
  /** The sentence it came from (spec section 9: 実際に読んだ論文の用例). */
  context?: string | null;
  sourcePaperId?: string | null;
  example?: string | null;
}

export interface ExpressionResponse {
  expression: ExpressionCard;
  /** False when the phrase was already saved and this call merged into it. */
  created: boolean;
}

export interface ExpressionListResponse {
  expressions: ExpressionCard[];
  total: number;
  dueCount: number;
}

export interface ReviewRequest {
  outcome: ReviewOutcome;
}

export interface ReviewQueueResponse {
  due: ExpressionCard[];
  totalDue: number;
}

export interface HealthResponse {
  status: 'ok' | 'degraded';
  version: string;
  /** Per-provider health so the client can explain a degraded feed. */
  providers: Record<string, { healthy: boolean; detail?: string }>;
  database: { connected: boolean; migrationRevision: string | null };
}

// ------------------------------------------------------------------------- equations

/**
 * An equation as the API sends it (spec sections 11, 24).
 *
 * Wider than the stored `Equation`: the server decides whether a formula may be handed to
 * the renderer and says so here, because spec section 25 keeps that judgement off the
 * client. `latex` is present either way — a refused formula is shown as source, which is
 * section 11's documented fallback, so refusing to typeset is not refusing to send.
 */
export interface EquationView {
  id: Uuid;
  paperId: Uuid;
  latex: string;
  equationNumber: string | null;
  section: string | null;
  display: boolean;
  provenanceKind: ProvenanceKind;
  verificationStatus: VerificationStatus;
  renderable: boolean;
  refusalReasons: string[];
  symbols: EquationSymbolView[];
}

export interface EquationSymbolView {
  symbol: string;
  localMeaning: string;
  generalMeaning: string | null;
  unit: string | null;
  scope: 'equation' | 'section' | 'paper' | 'field';
  provenanceKind: ProvenanceKind;
}

export interface DerivationStepView {
  id: Uuid;
  fromEquationId: Uuid;
  toEquationId: Uuid;
  latex: string;
  operation: string;
  rationale: string;
  verificationStatus: VerificationStatus;
  provenanceKind: ProvenanceKind;
  renderable: boolean;
  /** What the checks concluded, so a status can be explained rather than asserted. */
  evidence: Record<string, unknown> | null;
}

export interface MathCardView {
  id: Uuid;
  cardType: MathCardType;
  title: string;
  level: MathLevel;
  reviewStatus: 'draft' | 'in_review' | 'approved' | 'rejected';
  provenanceKind: ProvenanceKind;
  body: { summary?: string; whyItMatters?: string } & Record<string, unknown>;
}

export interface MathCardListResponse {
  cards: MathCardView[];
  total: number;
}

export interface MathCardDetailResponse {
  card: MathCardView;
  equations: EquationView[];
  steps: DerivationStepView[];
  /** Withheld because no check passed (spec section 12), reported so the derivation
   *  cannot look complete when it is not. */
  hiddenStepCount: number;
}

export interface EquationListResponse {
  equations: EquationView[];
}

/** A reader saying something on a maths card looks wrong (spec sections 12, 27). */
export interface ReportRequest {
  reason: ReportReason;
  /** Which part. Absent means the card as a whole; the two are mutually exclusive. */
  stepId?: string;
  equationId?: string;
  detail?: string;
}

export interface ReportResponse {
  reason: ReportReason;
  entityType: 'math_card' | 'derivation_step' | 'equation';
  entityId: string;
  /** True when this replaced the reader's earlier report of the same problem. */
  alreadyReported: boolean;
}

/**
 * One tile on the Knowledge Canvas (spec section 13).
 *
 * The paper travels with the tile because the plane draws a title at close zoom and
 * colours the tile from the field weights; fetching those per tile would make the plane
 * arrive in pieces.
 */
export interface CanvasTile {
  entityType: string;
  entityId: Uuid;
  x: number;
  y: number;
  clusterId: string | null;
  /** 0..1, already log-compressed (section 13: サイズは対数圧縮). */
  weight: number;
  /** True when the reader dragged this tile; a re-layout must not move it. */
  userOverride: boolean;
  paper: Paper;
}

export interface CanvasResponse {
  tiles: CanvasTile[];
  /** Which placement algorithm produced these coordinates (section 13). */
  layoutVersion: string;
}

export interface MoveTileRequest {
  x: number;
  y: number;
}
