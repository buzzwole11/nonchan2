import { MATH_MESSAGE_KIND, buildMathDocument, encodeForScript } from '../src/math/document';
import {
  KATEX_RUNTIME_DIGEST,
  KATEX_SCRIPT,
  KATEX_STYLES,
  KATEX_VERSION,
} from '../src/math/katexRuntime';

describe('encodeForScript', () => {
  it('round-trips ordinary values', () => {
    expect(JSON.parse(encodeForScript({ a: 1, b: 'x' }))).toEqual({ a: 1, b: 'x' });
  });

  it('never emits a character that could start a tag', () => {
    // The attack: a formula containing `</script>` ends the JSON block early, and
    // everything after it is parsed as markup by the browser — before the JS engine ever
    // sees it, so no amount of quote escaping helps.
    const encoded = encodeForScript({ latex: '</script><img src=x onerror=alert(1)>' });
    expect(encoded).not.toContain('<');
    expect(encoded).not.toContain('>');
    expect(encoded).toContain('\\u003c');
  });

  it('escapes ampersands so an entity cannot be smuggled through', () => {
    expect(encodeForScript('a & b')).not.toContain('&');
  });

  it('escapes the line terminators that are valid JSON but not valid JavaScript', () => {
    // U+2028 passes JSON.parse and then breaks the script it is inlined into.
    const encoded = encodeForScript('a b c');
    expect(encoded).not.toContain(' ');
    expect(encoded).not.toContain(' ');
    expect(JSON.parse(encoded)).toBe('a b c');
  });

  it('leaves the value itself unchanged after decoding', () => {
    const latex = String.raw`\frac{a}{b} & <x> \\ y`;
    expect(JSON.parse(encodeForScript(latex))).toBe(latex);
  });
});

describe('buildMathDocument', () => {
  const latex = String.raw`E = mc^2`;

  it('carries the formula as data, not as markup', () => {
    // A formula that tries to close the payload block and open its own script. The text
    // `alert(1)` is still in the document afterwards, and that is fine — it is inert
    // characters inside a JSON block. What must not survive is a *parseable tag*, so the
    // assertion is on the number of script elements the browser would see, not on whether
    // the payload looks alarming.
    const hostile = String.raw`</script><script>alert(1)</script>`;
    const html = buildMathDocument(hostile);

    // Exactly three: the JSON payload, KaTeX, and our bootstrap.
    expect(html.match(/<script/g)).toHaveLength(3);

    // And the formula itself is preserved byte for byte, because spec section 11 says the
    // original is never rewritten — including when it is hostile.
    expect(JSON.parse(payloadOf(html)).latex).toBe(hostile);
  });

  it('embeds KaTeX rather than fetching it', () => {
    const html = buildMathDocument(latex);
    expect(html).toContain(KATEX_SCRIPT.slice(0, 64));
    expect(html).not.toMatch(/src\s*=\s*["']https?:/);
    expect(html).not.toMatch(/href\s*=\s*["']https?:/);
  });

  it('forbids every kind of remote load through a policy as well', () => {
    // Belt and braces: the document is self-contained, and the policy is what stops a
    // formula that somehow did ask for something.
    const html = buildMathDocument(latex);
    expect(html).toContain("default-src 'none'");
    expect(html).toContain('font-src data:');
  });

  it('turns off the renderer features the server already refuses', () => {
    // Two independent barriers, not one: the server decides what to send, and the
    // renderer is configured as though it had not.
    const html = buildMathDocument(latex);
    expect(html).toContain('trust: false');
    expect(html).toContain('maxExpand: 200');
  });

  it('asks KaTeX for MathML alongside the visual output', () => {
    // Spec section 11. Without it a screen reader gets unlabelled spans.
    expect(buildMathDocument(latex)).toContain("output: 'htmlAndMathml'");
  });

  it('applies the caller font size so formulas follow Dynamic Type', () => {
    expect(buildMathDocument(latex, { fontSize: 27 })).toContain('font-size: 27px');
  });

  it('honours display and inline', () => {
    expect(JSON.parse(payloadOf(buildMathDocument(latex, { display: false }))).display).toBe(false);
    expect(JSON.parse(payloadOf(buildMathDocument(latex, { display: true }))).display).toBe(true);
  });

  it('passes a screen-reader label through when one is given', () => {
    const payload = JSON.parse(
      payloadOf(buildMathDocument(latex, { ariaLabel: '質量とエネルギー' })),
    );
    expect(payload.label).toBe('質量とエネルギー');
  });

  it('tags its message so the native side can tell it apart', () => {
    expect(JSON.parse(payloadOf(buildMathDocument(latex))).kind).toBe(MATH_MESSAGE_KIND);
  });

  it('reports back to a parent frame as well as to a WebView', () => {
    // The web build renders this same document in a sandboxed iframe, which has no
    // `ReactNativeWebView`. Without the second branch the height never arrives and the
    // formula stays at its placeholder height forever.
    const html = buildMathDocument(latex);
    expect(html).toContain('window.ReactNativeWebView.postMessage');
    expect(html).toContain('window.parent.postMessage');
  });

  it('measures whether the formula overflows rather than guessing', () => {
    // Only the renderer can know; the native side cannot see inside it.
    const html = buildMathDocument(latex);
    expect(html).toContain('root.scrollWidth > root.clientWidth');
    expect(html).toContain('overflow: overflows()');
  });

  it('draws the horizontal scrollbar permanently', () => {
    // An overlay scrollbar that appears only while scrolling cannot tell a reader that
    // there is something to scroll to, which is the only job it has here.
    const html = buildMathDocument(latex);
    expect(html).toContain('#root::-webkit-scrollbar');
    expect(html).toContain('scrollbar-width: thin');
  });
});

describe('the bundled KaTeX runtime', () => {
  it('is present and self-contained', () => {
    expect(KATEX_VERSION).toMatch(/^\d+\.\d+\.\d+$/);
    expect(KATEX_SCRIPT.length).toBeGreaterThan(100_000);
    expect(KATEX_RUNTIME_DIGEST).toMatch(/^[0-9a-f]{16}$/);
  });

  it('has no font reference pointing outside the bundle', () => {
    // A leftover `url(fonts/...)` would be a silent network request on a train.
    expect(KATEX_STYLES).not.toContain('url(fonts/');
    expect(KATEX_STYLES).toContain('data:font/woff2;base64,');
  });
});

/** Pull the JSON payload back out of a built document. */
function payloadOf(html: string): string {
  const match = html.match(/<script type="application\/json" id="payload">([\s\S]*?)<\/script>/);
  if (match?.[1] === undefined) throw new Error('no payload block in the document');
  return match[1];
}
