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
  AbstractSection,
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
  /**
   * Section 14's 関心度. The same notion of interest the Canvas sizes a tile by
   * (`services/canvas.personal_weight`) — what the reader marked as important and whether
   * they came back to it — so a paper that looks big on the plane sorts high in the list.
   */
  'interest',
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

/**
 * The four routes through a paper (spec section 17): 全体を知る / 数式を追う / 結果だけ見る /
 * 引用に使えるか確認.
 */
export const READING_PURPOSES = [
  'overview',
  'follow_math',
  'results_only',
  'citation_check',
] as const;

export type ReadingPurpose = (typeof READING_PURPOSES)[number];

/**
 * One stop on a route.
 *
 * `held` is the field that carries the honesty of the whole feature: true means the app has
 * this content, false means "open the paper and look". The app does not hold paper bodies,
 * so a route can point at the abstract sentences and equations it extracted and no further —
 * rendering an unheld step as though it were content would promise something that is not
 * there.
 */
export interface ReadingStep {
  kind: 'abstract_segment' | 'equation' | 'metadata' | 'external';
  /** An i18n key. Section 25 keeps UI strings on the client. */
  labelKey: string;
  held: boolean;
  section: AbstractSection | null;
  start: number | null;
  end: number | null;
  equationId: Uuid | null;
  equationNumber: string | null;
  /** A factual value — a licence id, a URL, a venue. The same in every language. */
  detail: string | null;
}

export interface ReadingRoute {
  purpose: ReadingPurpose;
  steps: ReadingStep[];
  /**
   * What this route could not cover. Always contains `full_text`, because the body of the
   * paper is not something the app has ever seen.
   */
  missing: string[];
}

export interface ReadingPathResponse {
  paperId: Uuid;
  routes: ReadingRoute[];
}

/**
 * The formula knowledge graph (spec section 28, Phase 7).
 *
 * Edges come only from recorded symbol definitions and derivation steps. Two equations that
 * share a letter are not connected by that.
 */
export interface EquationNode {
  equationId: Uuid;
  latex: string;
  equationNumber: string | null;
  section: string | null;
  provenanceKind: ProvenanceKind;
  verificationStatus: VerificationStatus;
}

export interface EquationEdge {
  fromEquationId: Uuid;
  toEquationId: Uuid;
  /** `defines`: a symbol used there was defined here. `derives`: a transformation step. */
  kind: 'defines' | 'derives';
  /** The symbol, for `defines`; the operation, for `derives`. */
  label: string;
  verificationStatus: VerificationStatus;
  provenanceKind: ProvenanceKind;
}

export interface EquationGraphResponse {
  paperId: Uuid;
  nodes: EquationNode[];
  edges: EquationEdge[];
  /** Equations with no edge at all, so the client can say why they stand alone. */
  isolated: Uuid[];
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
  /** When the reader saved it. Section 13's timeline slider replays the plane by this. */
  savedAt: Iso8601;
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
