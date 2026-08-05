/**
 * The second of spec section 11's three tiers: KaTeX → **MathJax** → LaTeX source.
 *
 * Reached only when KaTeX has already refused a particular formula. `MathView` escalates on
 * a failed render, so the common path never parses this ~2MB script — but it is in the app
 * bundle either way, and that is the cost of the tier (DECISIONS.md D-062).
 *
 * **Every security rule from `document.ts` applies here unchanged**, because this document
 * runs the same untrusted string in the same kind of WebView. The formula travels as data
 * in a JSON block, never interpolated into markup; the CSP forbids every kind of load; the
 * renderer is configured to refuse what the server already refuses. What differs is only
 * the engine, so the escaping and the message shape are imported from `document.ts` rather
 * than written again — two copies of an escaping rule is one copy that gets fixed.
 *
 * **The package list is written out rather than defaulted.** MathJax's default set includes
 * `require` and `autoload`, which fetch extension files by URL the first time a formula
 * uses something not already loaded. The CSP would block the request, but the outcome would
 * be a formula that fails for a reason no one can see. Naming the packages means an
 * unsupported macro fails immediately and falls through to the source display, which is a
 * tier the reader can actually use.
 *
 * **`enableMenu: false`.** MathJax's contextual menu is desktop chrome — it offers to
 * switch renderers, open mathjax.org, and copy MathML — and none of it belongs in a
 * formula inside a reading view.
 *
 * **SVG output, with `assistive-mml` for the screen reader.** The visual glyphs are paths,
 * so nothing is fetched and the height measured right after typesetting is the final
 * height. Section 11's MathML requirement is met by the assistive MathML that MathJax
 * places alongside, exactly as KaTeX's `htmlAndMathml` does in the other tier.
 */

import { getTheme } from '@papermatch/design-tokens';

import {
  MATH_MESSAGE_KIND,
  encodeForScript,
  type MathDocumentOptions,
  type MathEngine,
} from './document';
import { MATHJAX_SCRIPT } from './mathjaxRuntime';

const DEFAULT_COLOR = getTheme('light').color.textPrimary;

export function buildMathJaxDocument(latex: string, options: MathDocumentOptions = {}): string {
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
    engine: 'mathjax' satisfies MathEngine,
  });

  return `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=5">
<!-- Tighter than the KaTeX tier's policy by one directive: SVG glyphs are paths in the
     document, so unlike KaTeX there is no \`font-src\` to allow at all. --><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline';">
<style>
  html, body {
    margin: 0;
    padding: 0;
    background: ${backgroundColor};
    color: ${color};
    font-size: ${fontSize}px;
    overflow-y: hidden;
  }
  #root {
    overflow-x: auto;
    padding: 4px 2px;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: thin;
  }
  #root::-webkit-scrollbar {
    height: 4px;
    -webkit-appearance: none;
  }
  #root::-webkit-scrollbar-thumb {
    background: ${color};
    opacity: 0.4;
    border-radius: 2px;
  }
  /* SVG glyphs are drawn as filled paths, and MathJax fills them with \`currentColor\`.
     Without this the formula is black on a dark theme — invisible rather than merely
     wrong (spec section 20). */
  mjx-container svg { color: ${color}; }
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
<script>
  // Configured before the script below loads, which is how MathJax reads its settings.
  window.MathJax = {
    tex: {
      // Written out rather than defaulted. The default set includes \`require\` and
      // \`autoload\`, which fetch extension files by URL, and \`noundefined\`, which
      // renders an unknown macro as its own name in red *inside an otherwise typeset
      // formula*. That last one is the worse failure: it looks typeset, so a reader has
      // no reason to doubt it, while what they are looking at is not what the paper says.
      // Without it an unknown macro is an error, and the third tier shows the source —
      // which is checkable against the paper.
      packages: ['base', 'ams', 'newcommand', 'configmacros'],
      // The same two limits the other tier sets, for the same reason — a formula is
      // untrusted input and macro expansion is where it becomes unbounded.
      maxMacros: 200,
      maxBuffer: 32 * 1024,
    },
    options: {
      // Desktop chrome, and one of the two places a URL in this bundle could be reached.
      enableMenu: false,
      // Spoken maths, which would pull the Speech Rule Engine's language tables over the
      // network. The assistive MathML below is what a screen reader reads instead.
      enableExplorer: false,
      enableEnrichment: false,
    },
    svg: { fontCache: 'local' },
    startup: {
      // Nothing is typeset on load; the block below drives it, so a failure is ours to
      // catch rather than something MathJax reports to a console nobody reads.
      typeset: false,
    },
  };
</script>
<script>${MATHJAX_SCRIPT}</script>
<script>
(function () {
  var data = JSON.parse(document.getElementById('payload').textContent);
  var root = document.getElementById('root');
  var fallback = document.getElementById('fallback');

  function post(message) {
    var serialised = JSON.stringify(message);
    if (window.ReactNativeWebView && window.ReactNativeWebView.postMessage) {
      window.ReactNativeWebView.postMessage(serialised);
    } else if (window.parent && window.parent !== window) {
      window.parent.postMessage(serialised, '*');
    }
  }

  function height() {
    return Math.ceil(document.body.getBoundingClientRect().height);
  }

  function overflows() {
    return root.scrollWidth > root.clientWidth + 1;
  }

  function fail(error) {
    // Spec section 11: 失敗時は整形済みLaTeXソース. This is the third tier, and it is the
    // one that matters for trust — a reader who can see the source can still check the
    // paper, where a blank space tells them nothing.
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

  try {
    var node = window.MathJax.tex2svg(data.latex, { display: data.display });
    // MathJax reports a parse failure as an \`merror\` node rather than by throwing, so a
    // document that only caught exceptions would report success and show the reader a
    // red "Undefined control sequence" where a formula should be.
    if (node.querySelector('merror, [data-mjx-error]')) {
      fail(node.textContent || 'MathJax could not parse the formula');
      return;
    }
    root.appendChild(node);

    var assistive = root.querySelector('mjx-assistive-mml');
    var visual = root.querySelector('mjx-container > svg');
    if (assistive && visual) {
      // The MathML is what is read; announcing the SVG as well would read the formula
      // twice (spec section 11).
      visual.setAttribute('aria-hidden', 'true');
    }
    if (data.label) {
      root.setAttribute('role', 'math');
      root.setAttribute('aria-label', data.label);
    }

    post({ kind: data.kind, engine: data.engine, ok: true, height: height(), overflow: overflows() });
  } catch (error) {
    fail(error);
  }
})();
</script>
</body>
</html>`;
}
