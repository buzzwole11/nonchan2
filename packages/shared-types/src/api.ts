/**
 * HTTP contract shapes (spec section 24).
 *
 * Phase 0 implements the auth, fields and papers slices. Later phases fill in feed,
 * translations, saved, math cards and canvas; the request/response shapes are declared
 * here first so the client and the API move together.
 */
import type {
  FeedItem,
  Interest,
  Iso8601,
  Paper,
  SavedPaper,
  Translation,
  User,
  UserSettings,
} from './models.ts';
import type {
  ActionType,
  SaveReason,
  SavedStatus,
  TranslationStage,
  TranslationStyle,
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

export interface HealthResponse {
  status: 'ok' | 'degraded';
  version: string;
  /** Per-provider health so the client can explain a degraded feed. */
  providers: Record<string, { healthy: boolean; detail?: string }>;
  database: { connected: boolean; migrationRevision: string | null };
}
