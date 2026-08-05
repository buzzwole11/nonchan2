/**
 * The HTML document a formula is rendered in (spec sections 11, 20, 25).
 *
 * This is the security boundary of the maths feature. Everything below runs inside a
 * WebView, which is a browser: a formula string that reaches it as *markup* rather than as
 * *data* is script execution. So the rules here are narrow and absolute.
 *
 * **The LaTeX is never interpolated into HTML.** It is carried in a
 * `<script type="application/json">` block and read back with `textContent`, so the browser
 * parses it as text and not as tags. `JSON.stringify` alone is not enough — a payload
 * containing `</script>` ends the block early no matter how the quotes are escaped — which
 * is why `<`, `>` and `&` are escaped to their `\uXXXX` forms on the way in. The tests
 * cover exactly that string.
 *
 * **KaTeX is configured to refuse the same things the server refuses.** `trust: false`
 * turns off `\href` and the `\html*` family at the renderer, and `maxExpand` bounds macro
 * expansion. The server already rejects those (see `text/latex_safety.py`), so this is the
 * second of two independent barriers rather than the only one — the server decides what to
 * send, and the renderer is configured as though it had not.
 *
 * **A Content-Security-Policy forbids every kind of load.** The document is entirely
 * self-contained; if a formula ever did manage to ask for a remote resource, the policy is
 * what stops it. `default-src 'none'` with `'unsafe-inline'` only for the inline script and
 * style we ship ourselves.
 *
 * Two accessibility requirements from the spec are structural, not decoration:
 *
 * * Section 11 asks for **MathML alongside** the visual output. KaTeX's `htmlAndMathml`
 *   output emits both, and the MathML is what a screen reader actually reads — without it
 *   the formula is a pile of unlabelled spans.
 * * Section 20 asks for **Dynamic Type**. The base font size is passed in and applied to
 *   the root, so a formula scales with the rest of the app rather than staying pinned at
 *   16px while the text around it grows.
 */

import { getTheme } from '@papermatch/design-tokens';

import { KATEX_SCRIPT, KATEX_STYLES } from './katexRuntime';

/**
 * Only a fallback for callers that do not pass a colour — `MathView` always does, from the
 * active theme. Taken from the tokens rather than written as a literal, because spec
 * section 19 puts the palette in one place and section 20's contrast guarantees depend on
 * that being the only source.
 */
const DEFAULT_COLOR = getTheme('light').color.textPrimary;

export interface MathDocumentOptions {
  /** Display (centred, own line) or inline. Spec section 11 requires both. */
  display?: boolean;
  /** Root font size in px, already multiplied by the clamped Dynamic Type scale. */
  fontSize?: number;
  color?: string;
  backgroundColor?: string;
  /** Read by a screen reader in place of the formula's markup (spec section 11, 20). */
  ariaLabel?: string;
}

/**
 * Which of spec section 11's engines produced a result.
 *
 * Carried on every message so `MathView` cannot mistake a late message from the KaTeX
 * document for the MathJax one's verdict — escalating replaces the document, and a stale
 * message arriving afterwards would otherwise send the view back to a tier it had left.
 */
export type MathEngine = 'katex' | 'mathjax';

/** What the WebView posts back once it has tried to render. */
export interface MathRenderResult {
  ok: boolean;
  /** Which engine this result is about. Absent only from a document built before D-062. */
  engine?: MathEngine;
  /** Height in CSS pixels, so the native side can size the view to its content. */
  height: number;
  /**
   * True when the formula is wider than the space it has and is scrolling sideways.
   *
   * Reported because only the renderer can measure it, and a formula cut off at the edge
   * with no cue reads as a bug rather than as something with more to see.
   */
  overflow?: boolean;
  /** KaTeX's message when it could not parse the formula. */
  error?: string;
}

/**
 * Escape a string for embedding inside a `<script>` block.
 *
 * `JSON.stringify` produces a valid JavaScript literal but not a safe *HTML* one: the
 * parser looks for `</script` before the script is ever handed to the JS engine, so a
 * formula containing that sequence closes the block and everything after it becomes
 * markup. Escaping the three characters that can start a tag or an entity removes the
 * possibility rather than filtering for the one spelling of it.
 */
export function encodeForScript(value: unknown): string {
  return (
    JSON.stringify(value)
      .replace(/</g, '\\u003c')
      .replace(/>/g, '\\u003e')
      .replace(/&/g, '\\u0026')
      // U+2028 and U+2029 are line terminators in JavaScript but not in JSON, so a payload
      // containing one is valid JSON and a syntax error once inlined. Written as escapes
      // rather than as the characters themselves, which are invisible in an editor.
      .replace(/\u2028/g, '\\u2028')
      .replace(/\u2029/g, '\\u2029')
  );
}

/** The name the WebView posts results under; shared so the native side cannot mistype it. */
export const MATH_MESSAGE_KIND = 'papermatch.math.rendered';

export function buildMathDocument(latex: string, options: MathDocumentOptions = {}): string {
  const {
    display = true,
    fontSize = 18,
    color = DEFAULT_COLOR,
    backgroundColor = 'transparent',
    ariaLabel,
  } = options;

  const payload = encodeForScript({
    latex,
    display,
    label: ariaLabel ?? null,
    kind: MATH_MESSAGE_KIND,
    engine: 'katex' satisfies MathEngine,
  });

  return `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=5">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; font-src data:;">
<style>${KATEX_STYLES}</style>
<style>
  html, body {
    margin: 0;
    padding: 0;
    background: ${backgroundColor};
    color: ${color};
    /* Dynamic Type: the formula scales with the app's text (spec section 20). */
    font-size: ${fontSize}px;
    /* The WebView must never scroll vertically — the native side sizes it to content. */
    overflow-y: hidden;
  }
  #root {
    /* A long equation scrolls sideways rather than being cut off (spec section 11). */
    overflow-x: auto;
    padding: 4px 2px;
    -webkit-overflow-scrolling: touch;
    /* Firefox; the WebKit rules below do the same on the platforms that ignore this. */
    scrollbar-width: thin;
  }
  /* Drawn permanently rather than on hover. An overlay scrollbar that appears only while
     scrolling cannot tell a reader that there is something to scroll to — which is the
     whole job it has here (spec sections 11, 20). */
  #root::-webkit-scrollbar {
    height: 4px;
    -webkit-appearance: none;
  }
  #root::-webkit-scrollbar-thumb {
    background: ${color};
    opacity: 0.4;
    border-radius: 2px;
  }
  /* KaTeX's own error colour is a red that does not survive greyscale on its own; the
     source fallback below is what actually communicates the failure (spec section 20). */
  #fallback {
    display: none;
    font-family: ui-monospace, Menlo, Consolas, monospace;
    font-size: 0.85em;
    white-space: pre-wrap;
    word-break: break-word;
    opacity: 0.85;
  }
</style>
</head>
<body>
<div id="root"></div>
<pre id="fallback"></pre>
<script type="application/json" id="payload">${payload}</script>
<script>${KATEX_SCRIPT}</script>
<script>
(function () {
  // Read as text, never as markup. This is the whole reason the payload is in a JSON
  // block rather than interpolated into the script below.
  var data = JSON.parse(document.getElementById('payload').textContent);
  var root = document.getElementById('root');
  var fallback = document.getElementById('fallback');

  function post(message) {
    var serialised = JSON.stringify(message);
    if (window.ReactNativeWebView && window.ReactNativeWebView.postMessage) {
      window.ReactNativeWebView.postMessage(serialised);
    } else if (window.parent && window.parent !== window) {
      // The web build has no ReactNativeWebView; it renders this same document in a
      // sandboxed iframe, which can only talk to its parent this way. '*' as the target
      // origin because a sandboxed frame's origin is opaque and cannot be named — and
      // nothing secret travels here, only a height and whether KaTeX succeeded.
      window.parent.postMessage(serialised, '*');
    }
  }

  function height() {
    return Math.ceil(document.body.getBoundingClientRect().height);
  }

  // Whether the formula is wider than the space it has. The native side cannot measure
  // inside the renderer, and a formula that is cut off with no visible edge looks like a
  // rendering fault rather than something to scroll (spec sections 11, 20).
  function overflows() {
    return root.scrollWidth > root.clientWidth + 1;
  }

  try {
    katex.render(data.latex, root, {
      displayMode: data.display,
      // Both false on purpose. The server has already refused \\href and the \\html*
      // family; configuring the renderer as though it had not is the second of two
      // independent barriers (spec section 25).
      trust: false,
      strict: 'ignore',
      throwOnError: true,
      // MathML is what a screen reader reads. Without it the formula is unlabelled spans
      // (spec section 11).
      output: 'htmlAndMathml',
      maxSize: 50,
      maxExpand: 200,
    });

    // The visual half is decorative once MathML is present; announcing both would read
    // the formula twice.
    var htmlHalf = root.querySelector('.katex-html');
    if (htmlHalf) { htmlHalf.setAttribute('aria-hidden', 'true'); }

    if (data.label) {
      root.setAttribute('role', 'math');
      root.setAttribute('aria-label', data.label);
    }

    post({ kind: data.kind, engine: data.engine, ok: true, height: height(), overflow: overflows() });
  } catch (error) {
    // The source is shown *here* as well as reported, because this document may be the
    // last word: MathView escalates to MathJax (spec section 11's second tier) only when
    // it is mounted with an escalation path. Where it is not, a reader who can see the
    // source can still check the paper, and a blank space tells them nothing.
    root.style.display = 'none';
    fallback.style.display = 'block';
    fallback.textContent = data.latex;
    post({
      kind: data.kind,
      engine: data.engine,
      ok: false,
      height: height(),
      error: String((error && error.message) || error),
    });
  }
})();
</script>
</body>
</html>`;
}
