/**
 * The abstract, rendered with its formulas typeset (spec sections 6, 7, 11, 20).
 *
 * 95% of the abstracts in this corpus carry inline maths, and until this existed the card
 * printed the LaTeX source in the middle of the prose —
 * `$\mathbb{P}(|f - \mathbb{E}f| > t) \le 2\exp(...)$` sitting in a sentence a reader is
 * meant to skim in ten seconds. Section 11 makes the source the **fallback** for a formula
 * that cannot be typeset, not the normal presentation.
 *
 * This is `document.ts` for a whole abstract rather than one formula, and it inherits every
 * rule from there, because the threat is the same and the input is worse: abstract text
 * comes from a provider, so both the prose and the formulas are untrusted.
 *
 * * **Nothing is interpolated into markup.** The sentences and their formulas travel in a
 *   `<script type="application/json">` block and are read back with `textContent`. Prose is
 *   inserted with `createTextNode`, never `innerHTML`.
 * * **KaTeX is configured to refuse what the server refuses** — `trust: false` kills
 *   `\href` and the `\html*` family, `maxExpand` bounds macro expansion.
 * * **A CSP forbids every load.** The document is self-contained.
 *
 * Two things are specific to the abstract and are the reason this is not just a loop over
 * `buildMathDocument`.
 *
 * **A sentence stays one tap target.** Section 7's partial translation selects whole
 * sentences (DECISIONS.md D-018), so each sentence is a single `role="button"` span and a
 * tap posts its index back. Rendering each formula in its own WebView would have broken the
 * sentence into pieces that cannot be selected as a unit — and put twenty WebViews on a card.
 *
 * **One formula failing does not cost the sentence.** Each run is rendered independently; a
 * formula KaTeX refuses falls back to its own source, in place, and the prose either side is
 * unaffected.
 */

import { getTheme, scaledType } from '@papermatch/design-tokens';

import { type TextRun, splitMathRuns } from '../reading/sentences';
import { encodeForScript } from './document';
import { KATEX_SCRIPT, KATEX_STYLES } from './katexRuntime';

const DEFAULT_THEME = getTheme('light');
/** The abstract's own role in the type scale — a serif reading face, not the UI sans. */
const DEFAULT_TYPE = scaledType('abstract');

/** The name the WebView posts under; shared so the native side cannot mistype it. */
export const ABSTRACT_MESSAGE_KIND = 'papermatch.abstract';

export interface AbstractDocumentOptions {
  /** Root font size in px, already multiplied by the clamped Dynamic Type scale. */
  fontSize?: number;
  lineHeight?: number;
  /** The app's reading face. Hardcoding a stack here made the abstract the one block of
   *  text on the card in a different typeface, which reads as a rendering fault. */
  fontFamily?: string;
  color?: string;
  backgroundColor?: string;
  /** Background behind a selected sentence. Paired with an underline, never colour alone. */
  selectionColor?: string;
  /** Indices of the sentences currently selected. */
  selected?: readonly number[];
  /** Announced on each sentence, so a screen reader user knows a tap does something. */
  tapHint?: string;
}

/** What the document posts back. */
export type AbstractMessage =
  | { kind: typeof ABSTRACT_MESSAGE_KIND; type: 'height'; height: number }
  | { kind: typeof ABSTRACT_MESSAGE_KIND; type: 'sentence'; index: number }
  | { kind: typeof ABSTRACT_MESSAGE_KIND; type: 'failed'; count: number };

export interface AbstractSentenceInput {
  index: number;
  text: string;
}

/** A sentence reduced to what the renderer needs: its index and its runs. */
export function sentenceRuns(sentences: readonly AbstractSentenceInput[]): {
  index: number;
  runs: TextRun[];
}[] {
  return sentences.map((sentence) => ({
    index: sentence.index,
    runs: splitMathRuns(sentence.text),
  }));
}

/**
 * JavaScript the native side can inject to change the selection without rebuilding.
 *
 * Rebuilding would mean re-parsing the whole KaTeX runtime on every tap, which on a swipe
 * deck is the difference between a highlight and a flicker.
 */
export function selectionScript(selected: readonly number[]): string {
  return `window.__papermatchSelect(${encodeForScript(selected)}); true;`;
}

/** The same instruction as a message, for the web frame, which cannot be reached into. */
export function selectionMessage(selected: readonly number[]): string {
  return JSON.stringify({ type: 'select', selected });
}

export function buildAbstractDocument(
  sentences: readonly AbstractSentenceInput[],
  options: AbstractDocumentOptions = {},
): string {
  const {
    fontSize = 17,
    lineHeight = 1.65,
    fontFamily = DEFAULT_TYPE.fontFamily,
    color = DEFAULT_THEME.color.textPrimary,
    backgroundColor = 'transparent',
    selectionColor = DEFAULT_THEME.color.translationSurface,
    selected = [],
    tapHint = '',
  } = options;

  const payload = encodeForScript({
    sentences: sentenceRuns(sentences),
    selected,
    tapHint,
    kind: ABSTRACT_MESSAGE_KIND,
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
    /* Dynamic Type: the abstract scales with the rest of the app (spec section 20). */
    font-size: ${fontSize}px;
    line-height: ${lineHeight};
    font-family: ${fontFamily};
    overflow-y: hidden;
    -webkit-text-size-adjust: none;
  }
  #root { padding: 0; }
  .s {
    cursor: pointer;
    border-radius: 3px;
    /* The tap target has to survive a formula sitting inside it, so padding is horizontal
       only — vertical padding on an inline box does not grow the line and would overlap. */
    padding: 0 1px;
    -webkit-tap-highlight-color: transparent;
  }
  .s.on {
    /* Tint *and* underline. Spec section 20: state must survive greyscale and colour
       blindness, so colour is never the only carrier. */
    background: ${selectionColor};
    text-decoration: underline;
    text-underline-offset: 2px;
  }
  .s:focus-visible { outline: 2px solid currentColor; outline-offset: 1px; }
  /* A formula must not push the card wider than the screen; it scrolls inside its own box. */
  .m {
    display: inline-block;
    max-width: 100%;
    /* One line, scrolling sideways if it must (spec section 11: 横スクロール). Allowed to
       wrap, KaTeX broke mid-expression and left the sentence's full stop stranded at the
       start of the next line. */
    white-space: nowrap;
    overflow-x: auto;
    vertical-align: middle;
  }
  .m.block { display: block; overflow-x: auto; margin: 0.4em 0; }
  /* Spec section 11: 失敗時は整形済みLaTeXソース. Shown in place, marked as source, so the
     reader can see it is a formula we could not typeset rather than mangled prose. */
  .src {
    font-family: ui-monospace, Menlo, Consolas, monospace;
    font-size: 0.85em;
    padding: 0 3px;
    border-radius: 3px;
    opacity: 0.9;
    white-space: nowrap;
  }
</style>
</head>
<body>
<div id="root"></div>
<script type="application/json" id="payload">${payload}</script>
<script>${KATEX_SCRIPT}</script>
<script>
(function () {
  // Read as text, never as markup — the reason the payload is a JSON block.
  var data = JSON.parse(document.getElementById('payload').textContent);
  var root = document.getElementById('root');
  var failed = 0;

  function post(message) {
    var serialised = JSON.stringify(message);
    if (window.ReactNativeWebView && window.ReactNativeWebView.postMessage) {
      window.ReactNativeWebView.postMessage(serialised);
    } else if (window.parent && window.parent !== window) {
      // The web build has no ReactNativeWebView; it renders this same document in an
      // iframe, so the message goes to the parent frame instead.
      window.parent.postMessage(serialised, '*');
    }
  }

  function reportHeight() {
    post({
      kind: data.kind,
      type: 'height',
      height: Math.ceil(document.body.getBoundingClientRect().height),
    });
  }

  data.sentences.forEach(function (sentence) {
    var span = document.createElement('span');
    span.className = 's';
    span.setAttribute('role', 'button');
    span.setAttribute('tabindex', '0');
    span.setAttribute('data-i', String(sentence.index));
    if (data.tapHint) { span.setAttribute('aria-description', data.tapHint); }

    sentence.runs.forEach(function (run) {
      if (run.kind === 'text') {
        // createTextNode, not innerHTML. The prose is provider text.
        span.appendChild(document.createTextNode(run.value));
        return;
      }
      var box = document.createElement('span');
      box.className = run.display ? 'm block' : 'm';
      try {
        katex.render(run.value, box, {
          displayMode: !!run.display,
          // Both false on purpose — the renderer is configured as though the server had
          // not already refused these (spec section 25).
          trust: false,
          strict: 'ignore',
          throwOnError: true,
          output: 'htmlAndMathml',
          maxSize: 20,
          maxExpand: 200,
        });
        // MathML is what a screen reader reads; announcing the visual half too would read
        // the formula twice.
        var htmlHalf = box.querySelector('.katex-html');
        if (htmlHalf) { htmlHalf.setAttribute('aria-hidden', 'true'); }
      } catch (error) {
        failed += 1;
        box.className = 'src';
        box.textContent = '$' + run.value + '$';
      }
      span.appendChild(box);
    });

    root.appendChild(span);
    root.appendChild(document.createTextNode(' '));
  });

  function applySelection(indices) {
    var wanted = {};
    (indices || []).forEach(function (i) { wanted[i] = true; });
    var spans = root.querySelectorAll('.s');
    for (var i = 0; i < spans.length; i += 1) {
      var on = !!wanted[Number(spans[i].getAttribute('data-i'))];
      spans[i].classList.toggle('on', on);
      spans[i].setAttribute('aria-pressed', on ? 'true' : 'false');
    }
  }
  // Two ways in, because the two platforms have different channels. Native injects
  // JavaScript, which calls this directly. Web renders the document in a sandboxed iframe
  // whose origin is opaque, so the parent *cannot* reach in and has to post a message.
  window.__papermatchSelect = applySelection;
  window.addEventListener('message', function (event) {
    try {
      var incoming = JSON.parse(event.data);
      if (incoming && incoming.type === 'select') { applySelection(incoming.selected); }
    } catch (error) {
      // Not ours. The page a frame sits on may post anything.
    }
  });
  applySelection(data.selected);

  function chose(event) {
    var span = event.target && event.target.closest ? event.target.closest('.s') : null;
    if (!span) return;
    post({ kind: data.kind, type: 'sentence', index: Number(span.getAttribute('data-i')) });
  }
  root.addEventListener('click', chose);
  root.addEventListener('keydown', function (event) {
    if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); chose(event); }
  });

  if (failed > 0) { post({ kind: data.kind, type: 'failed', count: failed }); }
  reportHeight();
  // Fonts land after first paint and change the height; re-measure once they have.
  if (document.fonts && document.fonts.ready) { document.fonts.ready.then(reportHeight); }
  window.addEventListener('resize', reportHeight);
})();
</script>
</body>
</html>`;
}
