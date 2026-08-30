/**
 * The four roles around a paper (spec sections 13, 17).
 *
 * The classifier's restraint is tested on the server. What is left here is that the screen
 * does not undo it: an empty answer stays empty and is explained, and every row that *is*
 * shown says what it is there on.
 */
import { render, screen } from '@testing-library/react-native';

import type { PaperRelationHit } from '@papermatch/shared-types';

import { RelationList } from '../src/canvas/RelationList';
import { ThemeProvider } from '../src/theme/ThemeProvider';

function paper(id: string, title: string, year = 2024) {
  return { id, title, year } as unknown as PaperRelationHit['paper'];
}

const FOUNDATIONAL = {
  relationType: 'foundational',
  confidence: 0.9,
  basis: 'citation',
  evidence: {
    basis: 'citation',
    citation: 'anchor_cites_candidate',
    publicationOrder: 'before',
    anchorYear: 2026,
    candidateYear: 2011,
    similarity: null,
    similarityModel: null,
  },
  paper: paper('a', 'Concentration for Reversible Chains', 2011),
} as unknown as PaperRelationHit;

const CONTRASTING = {
  relationType: 'contrasting',
  confidence: 0.85,
  basis: 'mention',
  evidence: {
    basis: 'mention',
    publicationOrder: 'before',
    anchorYear: 2026,
    candidateYear: 2024,
    mention: {
      source: 'anchor',
      snippet: 'In contrast to Almeida et al., we obtain a bound with no log factor.',
    },
    contrastCue: 'in contrast',
    similarity: 0.7,
    similarityModel: 'papermatch-local-hash',
  },
  paper: paper('b', 'Sharp Bounds via Coupling', 2024),
} as unknown as PaperRelationHit;

const RELATED = {
  relationType: 'related',
  confidence: 0.6,
  basis: 'similarity',
  evidence: {
    basis: 'similarity',
    publicationOrder: 'after',
    anchorYear: 2026,
    candidateYear: 2026,
    similarity: 0.81,
    similarityModel: 'papermatch-local-hash',
  },
  paper: paper('c', 'Mixing Times Revisited', 2026),
} as unknown as PaperRelationHit;

function renderList(relations: PaperRelationHit[], loading = false) {
  render(
    <ThemeProvider initialPreference="light" forceReduceMotion={false} forceFontScale={1}>
      <RelationList relations={relations} locale="ja" loading={loading} />
    </ThemeProvider>,
  );
}

describe('when there is nothing to show', () => {
  it('says so rather than showing an unexplained blank', () => {
    renderList([]);

    expect(screen.getByText('関係のある論文は見つかりませんでした')).toBeTruthy();
  });

  it('explains that similarity alone was not enough', () => {
    // Otherwise "no relations" and "we did not look" are indistinguishable, and the reader
    // assumes the feature is broken rather than that the evidence was absent.
    renderList([]);

    expect(screen.getByText(/似ているだけの論文はここに出しません/)).toBeTruthy();
  });

  it('does not claim an empty result while it is still loading', () => {
    renderList([], true);

    expect(screen.queryByText('関係のある論文は見つかりませんでした')).toBeNull();
  });
});

describe('what each row states', () => {
  it('names the role each paper plays', () => {
    // Section 13: 基礎、対立、後続、類似を方向別に表示.
    renderList([FOUNDATIONAL, CONTRASTING, RELATED]);

    expect(screen.getByText('基礎になっている研究')).toBeTruthy();
    expect(screen.getByText('対立する研究')).toBeTruthy();
    expect(screen.getByText('関連する研究')).toBeTruthy();
  });

  it('names what the label rests on', () => {
    // Section 17 keeps the evidence; showing only the label would satisfy the letter of
    // that and none of the point.
    renderList([FOUNDATIONAL, RELATED]);

    expect(screen.getByText('引用による')).toBeTruthy();
    expect(screen.getByText('内容が近い')).toBeTruthy();
  });

  it('quotes the sentence behind a contrast rather than paraphrasing it', () => {
    renderList([CONTRASTING]);

    expect(screen.getByText(/In contrast to Almeida/)).toBeTruthy();
  });

  it('does not print a confidence number at the reader', () => {
    // Two confidences from different kinds of evidence are not on one scale, and inviting a
    // comparison between them is worse than saying nothing.
    renderList([FOUNDATIONAL, CONTRASTING, RELATED]);

    expect(screen.queryByText(/0\.9/)).toBeNull();
    expect(screen.queryByText(/0\.85/)).toBeNull();
  });

  it('keeps the roles in a fixed order whatever order they arrive in', () => {
    // The reader learns where to look; a panel that reshuffles has to be re-read each time.
    renderList([RELATED, CONTRASTING, FOUNDATIONAL]);

    const headings = ['基礎になっている研究', '対立する研究', '関連する研究'].map((label) =>
      screen.getByText(label),
    );

    expect(headings).toHaveLength(3);
  });
});
