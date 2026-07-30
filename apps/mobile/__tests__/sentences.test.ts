import {
  isSelected,
  normalizeRange,
  rangeToSelection,
  splitSentences,
  toggleSentence,
} from '../src/reading/sentences';

describe('splitSentences', () => {
  it('splits on sentence-ending punctuation and keeps exact offsets', () => {
    const abstract = 'First sentence. Second one? Third!';
    const sentences = splitSentences(abstract);

    expect(sentences.map((s) => s.text)).toEqual([
      'First sentence.',
      'Second one?',
      'Third!',
    ]);
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
