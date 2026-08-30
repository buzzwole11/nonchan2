import {
  isSelected,
  normalizeRange,
  rangeToSelection,
  selectionFor,
  splitMathRuns,
  splitSentences,
  toggleSentence,
} from '../src/reading/sentences';

describe('splitSentences', () => {
  it('splits on sentence-ending punctuation and keeps exact offsets', () => {
    const abstract = 'First sentence. Second one? Third!';
    const sentences = splitSentences(abstract);

    expect(sentences.map((s) => s.text)).toEqual(['First sentence.', 'Second one?', 'Third!']);
    for (const sentence of sentences) {
      expect(abstract.slice(sentence.start, sentence.end)).toBe(sentence.text);
    }
  });

  it('does not split on a decimal point', () => {
    const sentences = splitSentences('The angle is 1.09 degrees and that matters.');
    expect(sentences).toHaveLength(1);
  });

  it('does not split inside inline maths', () => {
    const abstract = 'We find $\\theta = 1.09^{\\circ}$. The gap then closes.';
    const sentences = splitSentences(abstract);
    expect(sentences).toHaveLength(2);
    expect(sentences[0]?.text).toBe('We find $\\theta = 1.09^{\\circ}$.');
    expect(sentences[0]?.hasMath).toBe(true);
    expect(sentences[1]?.hasMath).toBe(false);
  });

  it('does not split inside display maths', () => {
    const abstract = 'Therefore $$E = m c^2 . $$ holds everywhere.';
    expect(splitSentences(abstract)).toHaveLength(1);
  });

  it('does not split on common abbreviations', () => {
    const abstract = 'We follow Ref. 3 and Eq. 7 throughout the paper.';
    expect(splitSentences(abstract)).toHaveLength(1);
  });

  it('handles a trailing sentence with no final punctuation', () => {
    const sentences = splitSentences('Complete one. Dangling tail');
    expect(sentences.map((s) => s.text)).toEqual(['Complete one.', 'Dangling tail']);
  });

  it('returns nothing for empty or whitespace-only input', () => {
    expect(splitSentences('')).toEqual([]);
    expect(splitSentences('   \n  ')).toEqual([]);
  });

  it('covers every non-whitespace character of a realistic abstract', () => {
    const abstract =
      'Flat bands amplify interaction effects. Measured resistivities scale as ' +
      '$\\rho(T) \\propto T$ over two decades. We combine tensor-network simulations at ' +
      'bond dimension $\\chi = 1024$ with a slave-boson treatment. The gap closes at ' +
      '$\\theta_c = 1.09^{\\circ} \\pm 0.02^{\\circ}$. This identifies a signature.';
    const sentences = splitSentences(abstract);

    expect(sentences).toHaveLength(5);
    const rebuilt = sentences.map((s) => abstract.slice(s.start, s.end)).join(' ');
    expect(rebuilt.replace(/\s+/g, ' ')).toBe(abstract.replace(/\s+/g, ' '));
  });
});

describe('range selection', () => {
  const abstract = 'One here. Two there. Three everywhere.';
  const sentences = splitSentences(abstract);

  it('produces offsets the API can anchor on', () => {
    const selection = rangeToSelection(abstract, sentences, { from: 1, to: 1 });
    expect(selection).not.toBeNull();
    expect(abstract.slice(selection!.start, selection!.end)).toBe(selection!.exactText);
    expect(selection!.exactText).toBe('Two there.');
  });

  it('spans multiple sentences including the text between them', () => {
    const selection = rangeToSelection(abstract, sentences, { from: 0, to: 2 });
    expect(selection!.exactText).toBe(abstract);
  });

  it('normalises a backwards range', () => {
    expect(normalizeRange({ from: 3, to: 1 })).toEqual({ from: 1, to: 3 });
    const selection = rangeToSelection(abstract, sentences, { from: 2, to: 0 });
    expect(selection!.exactText).toBe(abstract);
  });

  it('returns null for an out-of-bounds range', () => {
    expect(rangeToSelection(abstract, sentences, { from: 0, to: 99 })).toBeNull();
  });
});

describe('toggleSentence', () => {
  it('selects a sentence on the first tap', () => {
    expect(toggleSentence(null, 2)).toEqual({ from: 2, to: 2 });
  });

  it('clears the selection when the only selected sentence is tapped again', () => {
    expect(toggleSentence({ from: 2, to: 2 }, 2)).toBeNull();
  });

  it('extends forwards and backwards', () => {
    expect(toggleSentence({ from: 1, to: 1 }, 3)).toEqual({ from: 1, to: 3 });
    expect(toggleSentence({ from: 3, to: 3 }, 1)).toEqual({ from: 1, to: 3 });
  });

  it('collapses to one sentence when tapping inside an existing range', () => {
    expect(toggleSentence({ from: 0, to: 4 }, 2)).toEqual({ from: 2, to: 2 });
  });

  it('reports membership for highlighting', () => {
    expect(isSelected({ from: 1, to: 3 }, 2)).toBe(true);
    expect(isSelected({ from: 1, to: 3 }, 4)).toBe(false);
    expect(isSelected(null, 0)).toBe(false);
  });
});

describe('selectionFor', () => {
  it('returns the selection made on the card being shown', () => {
    expect(selectionFor({ paperId: 'p1', range: { from: 1, to: 2 } }, 'p1')).toEqual({
      from: 1,
      to: 2,
    });
  });

  it('does not carry a selection over to the next card', () => {
    // The bug this guards: sentence indices only mean something against the abstract they
    // were taken from. Applied to the next paper they resolve to different character
    // offsets, and the reader gets a translation of text they never selected.
    expect(selectionFor({ paperId: 'p1', range: { from: 1, to: 2 } }, 'p2')).toBeNull();
  });

  it('has nothing to show when the deck is empty', () => {
    expect(selectionFor({ paperId: 'p1', range: { from: 0, to: 0 } }, null)).toBeNull();
    expect(selectionFor(null, 'p1')).toBeNull();
  });
});

// ------------------------------------------------------------------- inline maths runs

describe('splitMathRuns', () => {
  it('separates a formula from the prose around it', () => {
    expect(splitMathRuns('We prove $n \\log n$ is tight.')).toEqual([
      { kind: 'text', value: 'We prove ' },
      { kind: 'math', value: 'n \\log n', display: false },
      { kind: 'text', value: ' is tight.' },
    ]);
  });

  it('gives KaTeX the formula without its delimiters', () => {
    const [run] = splitMathRuns('$\\lambda_2$');
    expect(run).toEqual({ kind: 'math', value: '\\lambda_2', display: false });
  });

  it('marks $$...$$ as display, which KaTeX puts on its own line', () => {
    expect(splitMathRuns('so $$E = mc^2$$ follows')[1]).toEqual({
      kind: 'math',
      value: 'E = mc^2',
      display: true,
    });
  });

  it('treats an unclosed dollar as prose, not as a formula running to the end', () => {
    // A stray `$` is far more likely a price or a typo than a formula that swallows the
    // rest of the abstract — and guessing the other way produces a parse failure whose
    // fallback then prints the whole remaining text as source.
    expect(splitMathRuns('costs $5 per query and scales well')).toEqual([
      { kind: 'text', value: 'costs $5 per query and scales well' },
    ]);
  });

  it('keeps an escaped dollar as a literal character', () => {
    expect(splitMathRuns('a \\$5 fee')).toEqual([{ kind: 'text', value: 'a $5 fee' }]);
  });

  it('handles several formulas in one sentence', () => {
    const runs = splitMathRuns('For $p$ and $q$ we bound $pq$.');
    expect(runs.filter((r) => r.kind === 'math').map((r) => r.value)).toEqual(['p', 'q', 'pq']);
  });

  it('drops an empty formula rather than asking KaTeX to render nothing', () => {
    // The prose either side merges into one run rather than being split around a formula
    // that was never there.
    expect(splitMathRuns('a $ $ b')).toEqual([{ kind: 'text', value: 'a  b' }]);
  });

  it('leaves a lone $$ as prose, because it never closes', () => {
    expect(splitMathRuns('a $$ b')).toEqual([{ kind: 'text', value: 'a $$ b' }]);
  });

  it('round-trips prose that contains no maths at all', () => {
    const text = 'Expander graphs combine sparsity with strong connectivity.';
    expect(splitMathRuns(text)).toEqual([{ kind: 'text', value: text }]);
  });

  it('loses nothing: the runs rebuild the original sentence', () => {
    const text = 'We show $S_8 = \\sigma_8 \\sqrt{\\Omega_m/0.3}$ agrees to $1.7\\sigma$.';
    const rebuilt = splitMathRuns(text)
      .map((r) => (r.kind === 'math' ? `$${r.value}$` : r.value))
      .join('');
    expect(rebuilt).toBe(text);
  });
});
