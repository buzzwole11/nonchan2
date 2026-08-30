/**
 * Building a shareable image of a saved paper (spec sections 15, 21).
 *
 * Section 15 asks for 選択範囲を画像として書き出し with the title, authors, year and notes
 * each selectable, and section 21 states the constraint that shapes this module:
 * **共有画像から私的データを既定で除外**.
 *
 * **Private fields are opt-in; everything else is opt-out.** The default answer to "does
 * this go in the image" is no for anything the reader wrote or that records what they did.
 * A reader who shares a card and only afterwards notices their own note in the corner
 * cannot take it back — the image is already on someone else's timeline. Getting the
 * default the other way round would be a mistake that only ever surfaces after the harm.
 *
 * **The card says what it left out.** `omitted` lists the private fields that were
 * available and excluded, so the UI can tell the reader their note is not in the picture
 * rather than leaving them to squint at it. Silence would be indistinguishable from having
 * no note at all.
 *
 * **Reading history is never offered.** Section 15 lists 閲覧履歴 among the things excluded
 * by default, but nothing in the product wants "opened five times" on a shared image, and
 * an option nobody needs is one somebody can turn on by accident. It is not a parameter.
 *
 * **SVG, not a bitmap.** It is text, so it can be asserted on in a test — a rasteriser
 * would leave the redaction rules verifiable only by looking. The caller rasterises for
 * platforms that need pixels.
 */
import { tokens } from '@papermatch/design-tokens';
import type { Paper, SavedPaper } from '@papermatch/shared-types';

export interface ShareCardOptions {
  /** Default true. The title is the paper's, not the reader's. */
  includeTitle?: boolean;
  includeAuthors?: boolean;
  includeYear?: boolean;
  includeVenue?: boolean;
  /** **Default false.** The reader wrote this (spec section 21). */
  includeNotes?: boolean;
  /** **Default false.** Which reasons someone saved a paper for is about them. */
  includeReasons?: boolean;
}

export interface ShareCard {
  title: string | null;
  authors: string | null;
  year: number | null;
  venue: string | null;
  notes: string | null;
  reasons: string[] | null;
  /** Always present: section 21 requires the source to be stated. */
  sourceUrl: string;
  /** Always present when known; a shared image must not launder the licence. */
  licenseId: string | null;
  /** Private fields that existed and were left out, so the UI can say so. */
  omitted: ('notes' | 'reasons')[];
}

/** Longer than this and the note is cropped rather than shrinking the whole card. */
const MAX_NOTE_LENGTH = 140;

const MAX_AUTHORS = 3;

function authorLine(paper: Paper): string | null {
  const names = (paper.authors ?? [])
    .map((author) => author.name)
    .filter((name): name is string => typeof name === 'string' && name.length > 0);
  if (names.length === 0) return null;
  return names.length > MAX_AUTHORS
    ? `${names.slice(0, MAX_AUTHORS).join(', ')} ほか`
    : names.join(', ');
}

export function buildShareCard(
  paper: Paper,
  saved: SavedPaper | null,
  options: ShareCardOptions = {},
): ShareCard {
  const {
    includeTitle = true,
    includeAuthors = true,
    includeYear = true,
    includeVenue = true,
    // Opt-in. See the module comment: the cost of the wrong default is unrecoverable.
    includeNotes = false,
    includeReasons = false,
  } = options;

  const hasNotes = typeof saved?.notes === 'string' && saved.notes.trim().length > 0;
  const hasReasons = (saved?.reasons?.length ?? 0) > 0;

  const omitted: ShareCard['omitted'] = [];
  if (hasNotes && !includeNotes) omitted.push('notes');
  if (hasReasons && !includeReasons) omitted.push('reasons');

  const note = hasNotes ? (saved?.notes ?? '').trim() : null;

  return {
    title: includeTitle ? paper.title : null,
    authors: includeAuthors ? authorLine(paper) : null,
    year: includeYear ? paper.year : null,
    venue: includeVenue ? paper.venue : null,
    notes:
      includeNotes && note !== null
        ? note.length > MAX_NOTE_LENGTH
          ? `${note.slice(0, MAX_NOTE_LENGTH)}…`
          : note
        : null,
    reasons: includeReasons && hasReasons ? [...(saved?.reasons ?? [])] : null,
    // Section 21: 原文リンクを明示. Not optional — an image of someone's work that does
    // not say whose it is or where it came from is the thing the rule exists to prevent.
    sourceUrl: paper.sourceUrl,
    licenseId: paper.provenance?.licenseId ?? null,
    omitted,
  };
}

/** XML-escape. The card carries a title and a note, both of which are arbitrary text. */
function escapeXml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;');
}

/** Break a line at roughly `perLine` characters, without splitting inside a word. */
function wrap(text: string, perLine: number, maxLines: number): string[] {
  const lines: string[] = [];
  let current = '';
  for (const word of text.split(/\s+/)) {
    if (current.length === 0) {
      current = word;
    } else if (current.length + word.length + 1 <= perLine) {
      current = `${current} ${word}`;
    } else {
      lines.push(current);
      current = word;
      if (lines.length === maxLines) break;
    }
  }
  if (current.length > 0 && lines.length < maxLines) lines.push(current);
  return lines.slice(0, maxLines);
}

export interface ShareSvgOptions {
  width?: number;
  background?: string;
  ink?: string;
  muted?: string;
  accent?: string;
}

/**
 * Render a card to SVG.
 *
 * Every string goes through `escapeXml`. The title and the note are arbitrary text from a
 * paper and from the reader, so interpolating them raw would let a `<` in a title break
 * the document — and a share image is exactly the artefact that travels furthest from the
 * person who could notice.
 */
export function shareCardSvg(card: ShareCard, options: ShareSvgOptions = {}): string {
  // The light scheme, not the reader's: a shared image is looked at by other people, on
  // other devices, and a card exported in dark mode would arrive as dark grey on whatever
  // background the recipient's app happens to use. The caller can still override.
  const {
    width = 1080,
    background = tokens.color.light.card,
    ink = tokens.color.light.textPrimary,
    muted = tokens.color.light.textSecondary,
    accent = tokens.color.light.accent,
  } = options;

  const pad = 72;
  const titleLines = card.title === null ? [] : wrap(card.title, 34, 3);
  const noteLines = card.notes === null ? [] : wrap(card.notes, 46, 3);

  let y = pad + 56;
  const parts: string[] = [];

  for (const line of titleLines) {
    parts.push(
      `<text x="${pad}" y="${y}" font-size="52" font-weight="600" fill="${ink}">${escapeXml(line)}</text>`,
    );
    y += 68;
  }

  const meta = [card.authors, card.venue, card.year === null ? null : String(card.year)]
    .filter((value): value is string => value !== null && value.length > 0)
    .join(' · ');
  if (meta.length > 0) {
    y += 8;
    parts.push(
      `<text x="${pad}" y="${y}" font-size="32" fill="${muted}">${escapeXml(meta)}</text>`,
    );
    y += 52;
  }

  if (card.reasons !== null && card.reasons.length > 0) {
    parts.push(
      `<text x="${pad}" y="${y}" font-size="28" fill="${accent}">${escapeXml(card.reasons.join(' · '))}</text>`,
    );
    y += 48;
  }

  for (const line of noteLines) {
    parts.push(`<text x="${pad}" y="${y}" font-size="30" fill="${ink}">${escapeXml(line)}</text>`);
    y += 44;
  }

  // The footer is not optional (section 21): source and licence travel with the image.
  const footer = [card.sourceUrl, card.licenseId ?? 'ライセンス不明'].join('  ·  ');
  const height = Math.max(560, y + pad + 40);

  return [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">`,
    `<rect width="${width}" height="${height}" fill="${background}"/>`,
    `<rect x="0" y="0" width="12" height="${height}" fill="${accent}"/>`,
    ...parts,
    `<text x="${pad}" y="${height - pad}" font-size="24" fill="${muted}">${escapeXml(footer)}</text>`,
    '</svg>',
  ].join('\n');
}
