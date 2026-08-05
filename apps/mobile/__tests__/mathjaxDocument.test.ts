/**
 * Spec section 11's second tier: KaTeX → **MathJax** → LaTeX source.
 *
 * This document runs the same untrusted string in the same kind of WebView as the KaTeX
 * one, so the security assertions are the same assertions — repeated here rather than
 * assumed, because "the other document already tests that" is how a second renderer ends up
 * with the first one's guarantees and none of its checks.
 *
 * What the tests cannot see is whether MathJax typesets anything, so that was checked in a
 * real Chromium (DECISIONS.md D-062 records the run): five of the formulas KaTeX refuses
 * came back typeset with assistive MathML, `\href` fell through to the source tier with no
 * anchor element ever created, and the whole batch made zero network requests.
 */

import { MATH_MESSAGE_KIND } from '../src/math/document';
import { buildMathJaxDocument } from '../src/math/mathjaxDocument';
import {
  MATHJAX_RUNTIME_DIGEST,
  MATHJAX_SCRIPT,
  MATHJAX_VERSION,
} from '../src/math/mathjaxRuntime';

const latex = String.raw`\buildrel \rm def \over =`;

/** Pull the JSON payload back out of a built document. */
function payloadOf(html: string): string {
  const match = html.match(/<script type="application\/json" id="payload">([\s\S]*?)<\/script>/);
  if (match?.[1] === undefined) throw new Error('no payload block in the document');
  return match[1];
}

describe('buildMathJaxDocument', () => {
  it('carries the formula as data, not as markup', () => {
    // The same attack the KaTeX document is tested against: a formula that closes the
    // payload block and opens its own script. What must not survive is a parseable tag.
    const hostile = String.raw`</script><script>window.__alerted=1</script>`;
    const html = buildMathJaxDocument(hostile);

    const opening = html.match(/<script(\s|>)/g) ?? [];
    // The payload block, the config block, the runtime, and the driver. Nothing from the
    // formula.
    expect(opening).toHaveLength(4);
    expect(JSON.parse(payloadOf(html)).latex).toBe(hostile);
  });

  it('forbids every kind of load, and needs no font source at all', () => {
    const policy = buildMathJaxDocument(latex).match(
      /<meta http-equiv="Content-Security-Policy" content="([^"]*)"/,
    )?.[1];

    expect(policy).toContain("default-src 'none'");
    // Tighter than the KaTeX tier by one directive: SVG glyphs are paths in the document,
    // so there is no webfont to allow. A `font-src` in the policy would mean the bundle had
    // grown a dependency the offline requirement (spec section 26) does not permit.
    expect(policy).not.toContain('font-src');
    expect(policy).not.toContain('img-src');
  });

  it('names its TeX packages instead of taking the defaults', () => {
    const html = buildMathJaxDocument(latex);

    // `require` and `autoload` fetch extension files by URL — the one thing spec section
    // 25 rules out at render time.
    expect(html).not.toContain("'require'");
    expect(html).not.toContain("'autoload'");
    // `noundefined` renders an unknown macro as its own name in red inside an otherwise
    // typeset formula, which looks correct and is not. Without it the formula falls to the
    // source tier, which a reader can check against the paper.
    expect(html).not.toContain("'noundefined'");
    expect(html).toContain("packages: ['base', 'ams', 'newcommand', 'configmacros']");
  });

  it('turns off the two features that would reach for the network', () => {
    const html = buildMathJaxDocument(latex);

    // The contextual menu links to mathjax.org; the explorer and enrichment paths pull the
    // Speech Rule Engine's language tables. Those are the only URLs left in the bundle,
    // and `scripts/build-mathjax-runtime.mjs` fails the build if a new one appears.
    expect(html).toContain('enableMenu: false');
    expect(html).toContain('enableExplorer: false');
    expect(html).toContain('enableEnrichment: false');
  });

  it('bounds macro expansion the same way the other tier does', () => {
    // A formula is untrusted input, and expansion is where it becomes unbounded.
    const html = buildMathJaxDocument(latex);
    expect(html).toContain('maxMacros: 200');
    expect(html).toContain('maxBuffer:');
  });

  it('treats a parse error reported as a node, not as a throw', () => {
    // MathJax reports a bad formula by returning an `merror` element rather than by
    // throwing. A document that only caught exceptions would post `ok: true` and show the
    // reader a red "Undefined control sequence" where a formula should be.
    expect(buildMathJaxDocument(latex)).toContain("querySelector('merror, [data-mjx-error]')");
  });

  it('shows the LaTeX source when it cannot typeset', () => {
    // Spec section 11's third tier, and the one that matters for trust.
    const html = buildMathJaxDocument(latex);
    expect(html).toContain('fallback.textContent = data.latex');
    expect(html).toContain("fallback.style.display = 'block'");
  });

  it('hides the visual half from a screen reader so the formula is read once', () => {
    // MathJax places assistive MathML alongside the SVG; announcing both reads the formula
    // twice (spec section 11).
    const html = buildMathJaxDocument(latex);
    expect(html).toContain('mjx-assistive-mml');
    expect(html).toContain("visual.setAttribute('aria-hidden', 'true')");
  });

  it('says which engine every message is about', () => {
    // `MathView` escalates by replacing the document, so a late message from the KaTeX
    // frame must be distinguishable from this one's verdict.
    expect(JSON.parse(payloadOf(buildMathJaxDocument(latex))).engine).toBe('mathjax');
    expect(buildMathJaxDocument(latex)).toContain('engine: data.engine');
  });

  it('tags its message the same way the other tier does', () => {
    expect(JSON.parse(payloadOf(buildMathJaxDocument(latex))).kind).toBe(MATH_MESSAGE_KIND);
  });

  it('reports back to a parent frame as well as to a WebView', () => {
    const html = buildMathJaxDocument(latex);
    expect(html).toContain('window.ReactNativeWebView.postMessage');
    expect(html).toContain('window.parent.postMessage');
  });

  it('applies the caller font size so formulas follow Dynamic Type', () => {
    expect(buildMathJaxDocument(latex, { fontSize: 27 })).toContain('font-size: 27px');
  });

  it('fills the SVG glyphs with the theme colour', () => {
    // MathJax draws glyphs as filled paths using `currentColor`. Without this rule the
    // formula is black on a dark theme — invisible rather than merely wrong.
    expect(buildMathJaxDocument(latex, { color: 'rgb(1, 2, 3)' })).toContain(
      'mjx-container svg { color: rgb(1, 2, 3); }',
    );
  });

  it('honours display and inline', () => {
    expect(JSON.parse(payloadOf(buildMathJaxDocument(latex, { display: false }))).display).toBe(
      false,
    );
    expect(JSON.parse(payloadOf(buildMathJaxDocument(latex, { display: true }))).display).toBe(
      true,
    );
  });

  it('passes a screen-reader label through when one is given', () => {
    const payload = JSON.parse(payloadOf(buildMathJaxDocument(latex, { ariaLabel: '定義' })));
    expect(payload.label).toBe('定義');
  });
});

describe('the bundled MathJax runtime', () => {
  it('is present and self-contained', () => {
    expect(MATHJAX_VERSION).toMatch(/^\d+\.\d+\.\d+$/);
    expect(MATHJAX_SCRIPT.length).toBeGreaterThan(1_000_000);
    expect(MATHJAX_RUNTIME_DIGEST).toMatch(/^[0-9a-f]{16}$/);
  });

  it('carries no font file reference', () => {
    // The SVG build draws glyphs as paths. A `url(...woff2)` in here would be a silent
    // network request on a train (spec section 26).
    expect(MATHJAX_SCRIPT).not.toMatch(/url\((['"]?)[^)'"]*\.(woff2?|ttf)\1\)/);
  });
});
