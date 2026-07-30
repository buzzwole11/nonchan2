/**
 * Sentence segmentation for range selection (spec section 7).
 *
 * React Native's `selectable` text gives the platform's own selection UI but no way to
 * read back the selected offsets, and the API needs exact offsets to anchor a translation
 * (and to refuse a span that cuts through a formula). So selection is built from
 * sentences: each one is a tappable region with known offsets, and a range is a run of
 * them.
 *
 * That is a smaller unit than the spec's ideal of an arbitrary drag, but it is the right
 * granularity for the job — "分からない箇所だけ選択" is almost always a sentence or two —
 * and it has two properties an invisible native selection does not: every unit is
 * individually reachable by a screen reader, and the offsets handed to the API are exact.
 * Word-level selection needs a native module or a WebView; see DECISIONS.md D-018.
 */

export interface Sentence {
  index: number;
  /** Offset into the original abstract, inclusive. */
  start: number;
  /** Offset into the original abstract, exclusive. */
  end: number;
  text: string;
  /** True when the sentence contains inline maths, so the UI can hint at it. */
  hasMath: boolean;
}

/** Abbreviations that end in a period but do not end a sentence. */
const ABBREVIATIONS = [
  'e.g.',
  'i.e.',
  'cf.',
  'et al.',
  'etc.',
  'vs.',
  'Fig.',
  'Eq.',
  'Eqs.',
  'Ref.',
  'Refs.',
  'Sec.',
  'App.',
  'Ch.',
  'No.',
  'Dr.',
  'Prof.',
  'approx.',
];

function endsWithAbbreviation(text: string): boolean {
  const trimmed = text.trimEnd();
  return ABBREVIATIONS.some((abbrev) => trimmed.endsWith(abbrev));
}

/** Are we inside `$...$` at this offset? */
function insideMath(text: string, offset: number): boolean {
  let open = false;
  let i = 0;
  while (i < offset && i < text.length) {
    const char = text[i];
    if (char === '\\' && i + 1 < text.length && text[i + 1] === '$') {
      i += 2;
      continue;
    }
    if (char === '$') {
      // `$$` opens and closes as one delimiter.
      if (text[i + 1] === '$') {
        open = !open;
        i += 2;
        continue;
      }
      open = !open;
    }
    i += 1;
  }
  return open;
}

/**
 * Split an abstract into sentences with exact offsets.
 *
 * A period inside maths (`$n = 1.5$`), a decimal point, and a known abbreviation all fail
 * to end a sentence. Getting this wrong would let the user select half a formula, which
 * the API rejects — so the boundary rules live here rather than in a component.
 */
export function splitSentences(abstract: string): Sentence[] {
  const sentences: Sentence[] = [];
  let start = 0;
  let index = 0;

  for (let i = 0; i < abstract.length; i += 1) {
    const char = abstract[i];
    if (char !== '.' && char !== '?' && char !== '!') continue;
    if (insideMath(abstract, i)) continue;

    const next = abstract[i + 1];
    // A decimal point or a version number: "1.09", "v1.2".
    if (char === '.' && next !== undefined && /[0-9]/.test(next)) continue;
    // Must be followed by whitespace or end of text.
    if (next !== undefined && !/\s/.test(next)) continue;

    const candidate = abstract.slice(start, i + 1);
    if (endsWithAbbreviation(candidate)) continue;

    const trimmed = candidate.trim();
    if (trimmed.length > 0) {
      const leading = candidate.length - candidate.trimStart().length;
      sentences.push({
        index,
        start: start + leading,
        end: i + 1,
        text: trimmed,
        hasMath: /\$/.test(trimmed),
      });
      index += 1;
    }
    start = i + 1;
  }

  const tail = abstract.slice(start);
  if (tail.trim().length > 0) {
    const leading = tail.length - tail.trimStart().length;
    sentences.push({
      index,
      start: start + leading,
      end: abstract.length,
      text: tail.trim(),
      hasMath: /\$/.test(tail),
    });
  }

  return sentences;
}

export interface SelectionRange {
  /** Sentence indices, inclusive. */
  from: number;
  to: number;
}

export function normalizeRange(range: SelectionRange): SelectionRange {
  return range.from <= range.to ? range : { from: range.to, to: range.from };
}

/** Character offsets and exact text for a run of sentences. */
export function rangeToSelection(
  abstract: string,
  sentences: Sentence[],
  range: SelectionRange,
): { start: number; end: number; exactText: string } | null {
  const { from, to } = normalizeRange(range);
  const first = sentences[from];
  const last = sentences[to];
  if (first === undefined || last === undefined) return null;
  return {
    start: first.start,
    end: last.end,
    exactText: abstract.slice(first.start, last.end),
  };
}

/**
 * Tapping a sentence: the first tap selects it, tapping it again clears, and tapping a
 * different one extends the range so two adjacent sentences can be translated together.
 */
export function toggleSentence(
  current: SelectionRange | null,
  index: number,
): SelectionRange | null {
  if (current === null) return { from: index, to: index };
  const { from, to } = normalizeRange(current);
  if (from === index && to === index) return null;
  if (index >= from && index <= to) return { from: index, to: index };
  return index < from ? { from: index, to } : { from, to: index };
}

export function isSelected(range: SelectionRange | null, index: number): boolean {
  if (range === null) return false;
  const { from, to } = normalizeRange(range);
  return index >= from && index <= to;
}

/** A selection together with the paper it was made on. */
export interface ScopedSelection {
  paperId: string;
  range: SelectionRange;
}

/**
 * The selection that applies to `paperId`, or null if it belongs to another paper.
 *
 * Sentence indices only mean something against the abstract they were taken from, and
 * `rangeToSelection` turns them into character offsets without knowing which paper they
 * came from. Scoping the selection to its paper — rather than clearing it in an effect
 * after the card changes — removes the render in between, where indices from the previous
 * abstract would be resolved against this one and a translation requested for text the
 * reader never selected.
 */
export function selectionFor(
  scoped: ScopedSelection | null,
  paperId: string | null,
): SelectionRange | null {
  if (scoped === null || paperId === null) return null;
  return scoped.paperId === paperId ? scoped.range : null;
}
