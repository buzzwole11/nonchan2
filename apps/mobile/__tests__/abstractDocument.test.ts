/**
 * The abstract document (spec sections 6, 7, 11, 20).
 *
 * The document is a browser page built from provider text, so most of these tests are about
 * what must *not* be possible. What the page looks like once it renders is checked in a real
 * browser instead — a string assertion cannot tell you whether KaTeX typeset anything.
 */
import {
  ABSTRACT_MESSAGE_KIND,
  buildAbstractDocument,
  selectionMessage,
  selectionScript,
  sentenceRuns,
} from '../src/math/abstractDocument';

const sentences = [
  { index: 0, text: 'Concentration inequalities bound the deviation.' },
  { index: 1, text: 'We obtain $\\mathbb{P}(|f| > t) \\le 2\\exp(-ct^2)$ for all $t$.' },
];

// ------------------------------------------------------------------------ the payload

describe('sentenceRuns', () => {
  it('hands the renderer runs, not a string to parse itself', () => {
    expect(sentenceRuns(sentences)[1]).toEqual({
      index: 1,
      runs: [
        { kind: 'text', value: 'We obtain ' },
        { kind: 'math', value: '\\mathbb{P}(|f| > t) \\le 2\\exp(-ct^2)', display: false },
        { kind: 'text', value: ' for all ' },
        { kind: 'math', value: 't', display: false },
        { kind: 'text', value: '.' },
      ],
    });
  });

  it('keeps the sentence index, because that is what a tap reports back', () => {
    expect(sentenceRuns([{ index: 7, text: 'Only one.' }])[0]?.index).toBe(7);
  });
});

// -------------------------------------------------------------- data, never markup

describe('the document', () => {
  it('carries the text as JSON data and not as markup', () => {
    const html = buildAbstractDocument(sentences);
    // Exactly three scripts: the payload, the KaTeX runtime, and our own. A fourth means
    // something in the data was parsed as a tag.
    expect(html.split('<script').length - 1).toBe(3);
    expect(html).toContain('type="application/json"');
  });

  it('cannot be closed early by an abstract containing </script>', () => {
    // The attack that `JSON.stringify` alone does not stop: the HTML parser looks for
    // `</script` before any JavaScript runs, so the sequence has to be impossible to write.
    const hostile = buildAbstractDocument([
      { index: 0, text: 'Consider </script><img src=x onerror=alert(1)> the bound.' },
    ]);
    expect(hostile.split('<script').length - 1).toBe(3);
    expect(hostile).not.toContain('</script><img');
    expect(hostile).toContain('\\u003c');
  });

  it('round-trips the text through the payload byte for byte', () => {
    const text = 'Bounds hold for $x < y$ & $y > z$ — see §3.';
    const html = buildAbstractDocument([{ index: 0, text }]);
    const payload = html.slice(
      html.indexOf('id="payload">') + 'id="payload">'.length,
      html.indexOf('</script>'),
    );
    const parsed = JSON.parse(payload) as { sentences: { runs: { value: string }[] }[] };
    const first = parsed.sentences[0];
    expect(first).toBeDefined();
    const rebuilt = (first?.runs ?? [])
      .map((run, i) => (i % 2 === 1 ? `$${run.value}$` : run.value))
      .join('');
    expect(rebuilt).toBe(text);
  });

  it('escapes the JavaScript line terminators that are legal in JSON', () => {
    const html = buildAbstractDocument([{ index: 0, text: 'a b c' }]);
    expect(html).toContain('\\u2028');
    expect(html).not.toContain(' ');
  });
});

// ------------------------------------------------------------------ what it forbids

describe('the renderer is configured to refuse', () => {
  it('turns off \\href and the \\html* family', () => {
    // The server refuses these too (text/latex_safety.py). Configuring the renderer as
    // though it had not is the second of two independent barriers, not a duplicate.
    expect(buildAbstractDocument(sentences)).toContain('trust: false');
  });

  it('bounds macro expansion, so an expansion bomb cannot hang the card', () => {
    expect(buildAbstractDocument(sentences)).toContain('maxExpand: 200');
  });

  it('forbids every kind of load with a content security policy', () => {
    const html = buildAbstractDocument(sentences);
    expect(html).toContain("default-src 'none'");
    // Fonts are inlined as data URIs; nothing is fetched over the network.
    expect(html).toContain('font-src data:');
  });
});

// --------------------------------------------------------------- accessibility

describe('accessibility', () => {
  it('emits MathML alongside the visual output (spec section 11)', () => {
    expect(buildAbstractDocument(sentences)).toContain("output: 'htmlAndMathml'");
  });

  it('makes every sentence a button a screen reader can reach (spec section 20)', () => {
    const html = buildAbstractDocument(sentences);
    expect(html).toContain("setAttribute('role', 'button')");
    expect(html).toContain("setAttribute('tabindex', '0')");
  });

  it('scales with Dynamic Type rather than pinning a size', () => {
    expect(buildAbstractDocument(sentences, { fontSize: 34 })).toContain('font-size: 34px');
  });

  it('uses the reading face it is given, not a stack of its own', () => {
    // Hardcoding a stack made the abstract the one block of text on the card in a
    // different typeface, which reads as a rendering fault rather than a design.
    expect(buildAbstractDocument(sentences, { fontFamily: 'Literata, serif' })).toContain(
      'font-family: Literata, serif',
    );
  });

  it('marks a selected sentence with an underline as well as a tint', () => {
    // Spec section 20: state must survive greyscale and colour blindness.
    const html = buildAbstractDocument(sentences, { selected: [1] });
    expect(html).toContain('text-decoration: underline');
  });
});

// ------------------------------------------------------------------- the selection

describe('changing the selection', () => {
  it('updates in place rather than rebuilding the document', () => {
    // Rebuilding re-parses the bundled KaTeX runtime; on a swipe deck that is the
    // difference between a highlight and a flicker.
    expect(selectionScript([1, 3])).toContain('__papermatchSelect');
    expect(selectionScript([1, 3])).toContain('[1,3]');
  });

  it('has a message form too, because a sandboxed frame cannot be reached into', () => {
    expect(JSON.parse(selectionMessage([2]))).toEqual({ type: 'select', selected: [2] });
  });

  it('names its messages so the native side cannot mistype the kind', () => {
    expect(buildAbstractDocument(sentences)).toContain(ABSTRACT_MESSAGE_KIND);
  });
});
