#!/usr/bin/env node
/**
 * Deterministic generator for the Phase 0 sample corpus.
 *
 * Spec section 31 item 4 warns against shipping real abstracts in a public repository
 * without checking their terms. Everything produced here is synthetic text written for
 * this repository (CC0), composed from per-field sentence banks so the cards read like
 * real abstracts — with inline LaTeX, identifiers, licences and provenance — without
 * copying anyone's work. Phase 1 swaps `MockPaperProvider` for arXiv/OpenAlex and this
 * corpus becomes the offline/test fallback.
 *
 * Output: fixtures/papers.sample.json (committed, regenerate with `npm run fixtures:generate`).
 */
import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, '..');
const OUT_PATH = join(ROOT, 'fixtures', 'papers.sample.json');

const TARGET_UNIQUE_PAPERS = 60;
const GENERATOR_VERSION = '0.1.0';

/** Deterministic PRNG so regenerating the corpus produces a byte-identical file. */
function mulberry32(seed) {
  let a = seed >>> 0;
  return function next() {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const rand = mulberry32(20260730);
const pick = (list) => list[Math.floor(rand() * list.length)];
const pickN = (list, n) => {
  const pool = [...list];
  const out = [];
  while (out.length < n && pool.length > 0) {
    out.push(pool.splice(Math.floor(rand() * pool.length), 1)[0]);
  }
  return out;
};
const intBetween = (lo, hi) => lo + Math.floor(rand() * (hi - lo + 1));

const SURNAMES = [
  'Aoki', 'Bergmann', 'Chatterjee', 'Duarte', 'Ellingsen', 'Fujimoto', 'Grabowski', 'Haddad',
  'Ibarra', 'Jankowski', 'Kaneko', 'Lindqvist', 'Mkhize', 'Novak', 'Okonkwo', 'Pahlavi',
  'Quesada', 'Rousseau', 'Sasaki', 'Tikhonov', 'Ueda', 'Vasquez', 'Wierzbicka', 'Xu',
  'Yamashita', 'Zubkov', 'Almeida', 'Brennan', 'Castellanos', 'Delacroix',
];
const INITIALS = ['A.', 'B.', 'C.', 'D.', 'E.', 'F.', 'H.', 'I.', 'J.', 'K.', 'L.', 'M.', 'N.', 'R.', 'S.', 'T.', 'Y.'];

/**
 * Sentence banks per leaf field. Each abstract is assembled as
 * Background → Problem → Method → Result → Significance (spec section 8), which also
 * gives Phase 2 a ground-truth structure to check its classifier against.
 */
const FIELD_CONTENT = {
  'hep-th': {
    venues: ['arXiv (hep-th)', 'Journal of High Energy Physics', 'Physical Review D', 'Nuclear Physics B'],
    titleHead: [
      'Holographic Entanglement in {A} Backgrounds',
      'Anomaly Inflow and {A} Defects in Six Dimensions',
      'Bootstrapping {A} Correlators at Finite Coupling',
      'Non-perturbative Corrections to {A} Partition Functions',
      'Celestial Amplitudes for {A} Scattering',
    ],
    titleFill: ['Asymptotically AdS', 'Deformed Conformal', 'Supersymmetric', 'Chern-Simons', 'Near-Extremal'],
    background: [
      'Gauge/gravity duality relates strongly coupled field theories to classical gravity in one higher dimension.',
      'Conformal bootstrap methods constrain operator spectra without reference to a Lagrangian.',
      'Effective field theories organise quantum corrections as an expansion in $1/\\Lambda$.',
    ],
    problem: [
      'The behaviour of the entanglement entropy $S_{\\mathrm{EE}}$ across a first-order transition remains poorly understood.',
      'Existing results break down once the coupling $\\lambda$ leaves the perturbative regime.',
      'It is unclear whether the anomaly coefficient $c - a$ is monotonic along the renormalisation group flow.',
    ],
    method: [
      'We evaluate the on-shell action using a covariant holographic renormalisation scheme and match it to boundary counterterms.',
      'We combine numerical bootstrap bounds with an analytic expansion around the free theory.',
      'We construct the effective action to two loops and resum the leading logarithms with the renormalisation group.',
    ],
    result: [
      'We obtain the closed form $S_{\\mathrm{EE}} = \\frac{c}{3}\\log\\frac{\\ell}{\\epsilon} + \\gamma$, with $\\gamma$ independent of the cutoff.',
      'The spectrum organises into a discrete family labelled by $\\Delta_n = \\Delta_0 + 2n + O(\\lambda^2)$.',
      'The corrected free energy satisfies $F(T) = F_0(T)\\left[1 - \\alpha \\left(T/T_c\\right)^4\\right]$ in the regime studied.',
    ],
    significance: [
      'The result gives a concrete check of the duality outside the supergravity approximation.',
      'This narrows the space of consistent theories and suggests a sharper form of the $a$-theorem.',
      'The construction extends to a wider class of backgrounds and clarifies which corrections are universal.',
    ],
  },
  'cond-mat': {
    venues: ['arXiv (cond-mat)', 'Physical Review B', 'Physical Review Letters', 'npj Quantum Materials'],
    titleHead: [
      'Topological Edge Modes in {A} Lattices',
      'Anomalous Transport in {A} Metals',
      'Emergent {A} Order Near a Quantum Critical Point',
      'Disorder-Driven Localisation in {A} Systems',
      'Phonon-Mediated Pairing in {A} Superconductors',
    ],
    titleFill: ['Kagome', 'Twisted Bilayer', 'Kitaev', 'Moiré', 'Heavy-Fermion'],
    background: [
      'Flat bands amplify interaction effects because the kinetic scale is quenched relative to the Coulomb scale.',
      'Topological invariants classify insulating phases that cannot be deformed into one another without closing the gap.',
      'Quantum critical points reorganise the low-energy excitations of a metal into a non-Fermi-liquid form.',
    ],
    problem: [
      'Measured resistivities scale as $\\rho(T) \\propto T$ over two decades, which no quasiparticle picture reproduces.',
      'Whether the observed gap $\\Delta \\approx 1.8\\,\\mathrm{meV}$ is of topological origin has not been settled.',
      'Existing simulations cannot reach the system sizes at which the localisation length saturates.',
    ],
    method: [
      'We combine tensor-network simulations at bond dimension $\\chi = 1024$ with an analytic slave-boson treatment.',
      'We derive a low-energy Hamiltonian $H = \\sum_{k} \\psi_k^{\\dagger} h(k) \\psi_k$ and compute its Chern number numerically.',
      'We perform large-scale exact diagonalisation on clusters of up to $N = 24$ sites with twisted boundary conditions.',
    ],
    result: [
      'The gap closes at a critical twist angle $\\theta_c = 1.09^{\\circ} \\pm 0.02^{\\circ}$, with edge modes surviving moderate disorder.',
      'We find a conductivity $\\sigma(\\omega) \\sim \\omega^{-2/3}$ in the quantum critical fan, consistent with the scaling ansatz.',
      'The pairing susceptibility diverges only when the phonon coupling exceeds $\\lambda_{\\mathrm{ph}} \\simeq 0.4$.',
    ],
    significance: [
      'This identifies a concrete experimental signature that distinguishes the two competing scenarios.',
      'The scaling form applies to several materials in the same family and explains the reported deviations.',
      'It sets a quantitative target for growth efforts aiming at the topological regime.',
    ],
  },
  'quant-ph': {
    venues: ['arXiv (quant-ph)', 'Quantum', 'Physical Review A', 'PRX Quantum'],
    titleHead: [
      'Error Mitigation for {A} Circuits',
      'Optimal Control of {A} Qubits Under Dephasing',
      'Entanglement Growth in {A} Dynamics',
      'Certifying Randomness from {A} Devices',
      'Variational Preparation of {A} States',
    ],
    titleFill: ['Shallow Trotterised', 'Superconducting', 'Random Unitary', 'Untrusted', 'Matrix Product'],
    background: [
      'Near-term quantum processors operate without full error correction, so residual noise dominates the output.',
      'Entanglement entropy is a diagnostic for whether a quantum dynamics can be simulated classically.',
      'Device-independent protocols certify quantum properties from measurement statistics alone.',
    ],
    problem: [
      'The sampling overhead of existing mitigation schemes grows as $e^{\\gamma L}$ with circuit depth $L$.',
      'Control pulses optimised in the noiseless limit lose fidelity once $T_2$ is finite.',
      'It is not known how much randomness can be extracted when the device violates a Bell inequality only weakly.',
    ],
    method: [
      'We formulate mitigation as a quasi-probability decomposition and bound its variance with a matrix concentration inequality.',
      'We solve the Lindblad equation $\\dot{\\rho} = -i[H,\\rho] + \\sum_k \\mathcal{D}[L_k]\\rho$ under a GRAPE-style optimiser.',
      'We derive a semidefinite relaxation whose optimum upper-bounds the guessing probability.',
    ],
    result: [
      'The overhead improves to $e^{\\gamma L / 2}$ for circuits with bounded light-cone overlap, verified on $12$-qubit instances.',
      'Optimised pulses reach a fidelity $F = 0.9971$ at $T_2 = 40\\,\\mu\\mathrm{s}$, against $0.982$ for the noiseless-optimal pulse.',
      'We certify $0.31$ bits of randomness per round at a CHSH value of $S = 2.16$.',
    ],
    significance: [
      'The bound is tight enough to guide which circuits are worth running on current hardware.',
      'The protocol needs no additional calibration data and fits inside existing control stacks.',
      'This closes part of the gap between theoretical certification rates and what devices actually achieve.',
    ],
  },
  'astro-ph': {
    venues: ['arXiv (astro-ph)', 'The Astrophysical Journal', 'Monthly Notices of the RAS', 'Astronomy & Astrophysics'],
    titleHead: [
      'Constraints on {A} from Weak Lensing Surveys',
      'The {A} Population in Nearby Dwarf Galaxies',
      'Gravitational Wave Signatures of {A} Mergers',
      'Radiative Transfer in {A} Discs',
      'Chemical Evolution of {A} Environments',
    ],
    titleFill: ['Modified Gravity', 'Intermediate-Mass Black Hole', 'Eccentric Binary', 'Protoplanetary', 'Metal-Poor'],
    background: [
      'Weak lensing measures the projected matter distribution without assuming that light traces mass.',
      'Stellar population synthesis links observed colours to star formation histories.',
      'Compact binary mergers encode their formation channel in the eccentricity at a given frequency.',
    ],
    problem: [
      'Reported values of $S_8 = \\sigma_8 \\sqrt{\\Omega_m/0.3}$ differ between surveys by more than the quoted errors.',
      'Current samples are too small to determine whether the occupation fraction depends on stellar mass.',
      'Waveform models neglect eccentricity, biasing the inferred masses by an unknown amount.',
    ],
    method: [
      'We reanalyse the shear catalogue with a forward-modelled likelihood that marginalises over intrinsic alignments.',
      'We fit spectral energy distributions with a nested-sampling pipeline and propagate the full posterior.',
      'We inject eccentric signals into simulated noise and recover them with circular templates to quantify the bias.',
    ],
    result: [
      'We obtain $S_8 = 0.769^{+0.021}_{-0.019}$, reducing the tension with the CMB value to $1.7\\sigma$.',
      'The occupation fraction rises from $0.06$ to $0.34$ across the mass range $10^{7}$–$10^{9}\\,M_{\\odot}$.',
      'Neglecting an eccentricity $e_{10} = 0.05$ biases the chirp mass by $1.4\\%$, comparable to the statistical error.',
    ],
    significance: [
      'The shift is large enough to change how the tension between probes should be interpreted.',
      'The trend favours a formation channel seeded in the early universe over late dynamical capture.',
      'Waveform systematics will dominate once detector sensitivity improves by a further factor of two.',
    ],
  },
  'math.AP': {
    venues: ['arXiv (math.AP)', 'Communications in PDE', 'Archive for Rational Mechanics', 'Analysis & PDE'],
    titleHead: [
      'Global Well-Posedness for the {A} Equation',
      'Blow-Up Criteria for {A} Systems',
      'Regularity of Minimisers in {A} Problems',
      'Long-Time Asymptotics of {A} Flows',
      'Homogenisation of {A} Operators',
    ],
    titleFill: ['Damped Wave', 'Quasi-Geostrophic', 'Free Boundary', 'Fractional Heat', 'Degenerate Elliptic'],
    background: [
      'Energy methods control the growth of solutions when the nonlinearity is subcritical in the relevant norm.',
      'Free boundary problems couple an elliptic equation to an unknown interface determined by the solution itself.',
      'Homogenisation replaces rapidly oscillating coefficients by an effective constant tensor.',
    ],
    problem: [
      'Existing results require the initial data to satisfy $\\|u_0\\|_{H^s} < \\varepsilon$ for an unspecified small $\\varepsilon$.',
      'Whether solutions remain smooth past the critical time $T^*$ is open in the borderline case $s = d/2$.',
      'The known convergence rate is not sharp and degenerates as the ellipticity constant tends to zero.',
    ],
    method: [
      'We build a modified energy functional and close a bootstrap argument with a Strichartz estimate.',
      'We combine a De Giorgi–Nash–Moser iteration with a monotonicity formula adapted to the degenerate weight.',
      'We use two-scale convergence together with a corrector estimate in the space $H^1_{\\mathrm{loc}}$.',
    ],
    result: [
      'We prove global well-posedness for all data in $H^s$ with $s > d/2 - 1$, removing the smallness assumption.',
      'We show that blow-up at $T^*$ forces $\\int_0^{T^*}\\|\\nabla u(t)\\|_{L^\\infty}\\,dt = \\infty$.',
      'The corrector satisfies $\\|u_\\varepsilon - u_0\\|_{L^2} \\le C\\varepsilon^{1/2}$, and the exponent is optimal.',
    ],
    significance: [
      'The argument is robust and applies unchanged to several related dispersive equations.',
      'This settles the borderline case left open in earlier work and identifies the obstruction precisely.',
      'The sharp rate makes the result usable in numerical error analysis.',
    ],
  },
  'math.CO': {
    venues: ['arXiv (math.CO)', 'Combinatorica', 'Journal of Combinatorial Theory B', 'Electronic Journal of Combinatorics'],
    titleHead: [
      'Improved Bounds for {A} Ramsey Numbers',
      'Extremal Problems on {A} Hypergraphs',
      'Spectral Properties of {A} Expanders',
      'Enumerating {A} Tilings',
      'Thresholds for {A} Subgraphs',
    ],
    titleFill: ['Off-Diagonal', 'Sparse', 'Cayley', 'Rhombic', 'Random'],
    background: [
      'Ramsey theory asks how large a structure must be before order appears in every colouring.',
      'The container method reduces counting problems on sparse structures to a bounded family of dense ones.',
      'Expander graphs combine sparsity with strong connectivity, measured by the spectral gap $\\lambda_1 - \\lambda_2$.',
    ],
    problem: [
      'The gap between the upper bound $R(3,t) = O(t^2/\\log t)$ and the lower bound has resisted improvement.',
      'The extremal number $\\mathrm{ex}(n, F)$ is unknown for the family considered here even up to a constant.',
      'Existing threshold results assume a bounded degeneracy that many natural families violate.',
    ],
    method: [
      'We use a randomised greedy process and analyse it with the differential equation method.',
      'We apply hypergraph containers together with a supersaturation lemma proved by entropy compression.',
      'We combine a spectral argument with a careful second-moment computation.',
    ],
    result: [
      'We prove $\\mathrm{ex}(n, F) = \\left(\\tfrac{1}{2} + o(1)\\right)\\binom{n}{2}$, matching the conjectured constant.',
      'The threshold is $p^* = n^{-2/3}(\\log n)^{1/3}$, sharp up to the constant factor.',
      'We improve the leading constant from $1$ to $1/4 + o(1)$, and the construction is explicit.',
    ],
    significance: [
      'The method removes the degeneracy hypothesis and so applies to a substantially larger family.',
      'This brings the upper and lower bounds within a constant factor for the first time.',
      'The explicit construction can be used directly in derandomisation arguments.',
    ],
  },
  'math.NT': {
    venues: ['arXiv (math.NT)', 'Journal of Number Theory', 'Compositio Mathematica', 'Algebra & Number Theory'],
    titleHead: [
      'Moments of {A} L-Functions',
      'Rational Points on {A} Varieties',
      'Distribution of {A} Sums',
      'Congruences for {A} Forms',
      'Effective Bounds for {A} Heights',
    ],
    titleFill: ['Dirichlet', 'Del Pezzo', 'Kloosterman', 'Modular', 'Canonical'],
    background: [
      'Moments of $L$-functions encode the statistics of their zeros and connect to random matrix predictions.',
      'The circle method converts a counting problem into an integral over major and minor arcs.',
      'Heights measure arithmetic complexity and control how many points of bounded size a variety can have.',
    ],
    problem: [
      'The fourth moment is known unconditionally only for a restricted family of characters.',
      'The expected asymptotic $N(B) \\sim c B (\\log B)^{r-1}$ has not been proved for the surfaces treated here.',
      'Existing bounds are ineffective and so cannot be used to enumerate solutions.',
    ],
    method: [
      'We use an approximate functional equation together with a large sieve inequality for the relevant family.',
      'We refine the delta-method of Duke–Friedlander–Iwaniec and control the minor arcs with a bilinear estimate.',
      'We combine Arakelov-theoretic height comparisons with an explicit version of the Chebotarev density theorem.',
    ],
    result: [
      'We establish the asymptotic $\\sum_{\\chi} |L(\\tfrac12,\\chi)|^4 \\sim c\\, q (\\log q)^{4}$ with an explicit constant $c$.',
      'We prove $N(B) = cB(\\log B)^{r-1}\\left(1 + O((\\log B)^{-1/2})\\right)$ for all surfaces in the family.',
      'The bound is effective, with all constants computable from the discriminant.',
    ],
    significance: [
      'The result matches the random matrix prediction and extends it to a wider family.',
      'Effectivity makes the theorem usable for explicit computations, not only for asymptotic statements.',
      'The technique should transfer to higher moments with a bounded amount of additional work.',
    ],
  },
  'math.PR': {
    venues: ['arXiv (math.PR)', 'Annals of Probability', 'Probability Theory and Related Fields', 'Electronic Journal of Probability'],
    titleHead: [
      'Mixing Times for {A} Chains',
      'Scaling Limits of {A} Random Walks',
      'Concentration for {A} Measures',
      'Large Deviations in {A} Models',
      'Cutoff Phenomena for {A} Dynamics',
    ],
    titleFill: ['Interchange', 'Reinforced', 'Log-Concave', 'Spin Glass', 'Non-Reversible'],
    background: [
      'The mixing time measures how long a Markov chain needs before its law is close to stationarity.',
      'Scaling limits identify the universal object that a discrete model converges to after rescaling.',
      'Concentration inequalities bound the probability that a function of many variables deviates from its mean.',
    ],
    problem: [
      'Whether the chain exhibits cutoff on general graphs of bounded degree has remained open.',
      'The conjectured limit is known only for the mean-field case, where correlations are absent.',
      'Standard log-Sobolev arguments fail because the measure is not uniformly log-concave.',
    ],
    method: [
      'We construct a coupling that contracts a suitably weighted metric and estimate its contraction rate.',
      'We prove tightness in the Skorokhod topology and identify the limit by a martingale problem.',
      'We use a transport-entropy inequality combined with a localisation argument.',
    ],
    result: [
      'We show cutoff at time $t_{\\mathrm{mix}} = \\frac{1}{2\\lambda}\\log n$ with a window of order $1/\\lambda$.',
      'The rescaled process converges weakly to the solution of $dX_t = -\\nabla V(X_t)\\,dt + \\sqrt{2}\\,dB_t$.',
      'We obtain the deviation bound $\\mathbb{P}(|f - \\mathbb{E}f| > t) \\le 2\\exp(-ct^2/\\|f\\|_{\\mathrm{Lip}}^2)$.',
    ],
    significance: [
      'The coupling is simple enough to be reused for other non-reversible chains.',
      'This confirms the predicted universality class beyond the mean-field setting.',
      'The bound removes the log-concavity assumption that limited earlier applications.',
    ],
  },
  'cs.LG': {
    venues: ['arXiv (cs.LG)', 'NeurIPS', 'ICML', 'Transactions on Machine Learning Research'],
    titleHead: [
      'On the Generalisation of {A} Networks',
      'Sample-Efficient {A} Reinforcement Learning',
      'Implicit Regularisation in {A} Training',
      'Robustness of {A} Representations',
      'Scaling Laws for {A} Models',
    ],
    titleFill: ['Overparameterised', 'Model-Based', 'Gradient-Descent', 'Contrastive', 'Sparse Mixture'],
    background: [
      'Overparameterised networks fit their training data exactly yet still generalise, which classical bounds do not explain.',
      'Model-based agents learn a dynamics model and plan against it, trading sample cost for compute.',
      'Contrastive objectives learn representations by pulling together views of the same input.',
    ],
    problem: [
      'Uniform-convergence bounds are vacuous once the parameter count exceeds the sample size $n$.',
      'Reported gains vanish when the evaluation protocol controls for the number of environment interactions.',
      'It is unclear which components of the objective drive robustness and which are incidental.',
    ],
    method: [
      'We analyse the training dynamics in the neural tangent kernel regime and track the effective rank of the Jacobian.',
      'We run a controlled study across five environments with matched interaction budgets and three seeds each.',
      'We ablate each term of the loss and measure the effect under distribution shift on held-out corruptions.',
    ],
    result: [
      'The generalisation gap scales as $O(\\sqrt{r_{\\mathrm{eff}}/n})$ with the effective rank, not the parameter count.',
      'Under matched budgets the advantage shrinks from $38\\%$ to $6\\%$, and disappears entirely in two environments.',
      'Removing the temperature schedule costs $11.2$ points of accuracy under shift but only $0.4$ in distribution.',
    ],
    significance: [
      'The bound is non-vacuous in the regime where these models are actually trained.',
      'The finding argues for reporting interaction budgets alongside returns in this literature.',
      'The ablation identifies a single cheap component that accounts for most of the robustness.',
    ],
  },
  'cs.DS': {
    venues: ['arXiv (cs.DS)', 'SODA', 'STOC', 'ACM Transactions on Algorithms'],
    titleHead: [
      'Faster Algorithms for {A} Flow',
      'Dynamic {A} Data Structures',
      'Approximation Schemes for {A} Packing',
      'Lower Bounds for {A} Sketching',
      'Sublinear {A} Estimation',
    ],
    titleFill: ['Min-Cost', 'Connectivity', 'Geometric', 'Streaming', 'Triangle-Count'],
    background: [
      'Interior-point methods reduced flow problems to a sequence of linear system solves.',
      'Dynamic data structures maintain a solution under updates rather than recomputing from scratch.',
      'Sketching compresses a stream into small space while preserving a target statistic.',
    ],
    problem: [
      'The best known bound $\\tilde{O}(m^{3/2})$ has not improved for sparse instances in two decades.',
      'Existing structures support updates in $O(\\sqrt{n})$ amortised time but degrade badly in the worst case.',
      'No lower bound is known that separates one-pass from two-pass algorithms for this problem.',
    ],
    method: [
      'We combine a dynamic spectral sparsifier with a robust interior-point framework tolerant of approximate solves.',
      'We use a hierarchical decomposition with lazily rebuilt levels and amortise the rebuild cost against updates.',
      'We reduce from set disjointness and analyse the communication cost of the induced protocol.',
    ],
    result: [
      'We achieve $\\tilde{O}(m^{4/3})$ total time, improving on the previous bound for all $m = O(n^{3/2})$.',
      'Updates take $O(\\log^2 n)$ worst-case time and queries $O(\\log n)$, both deterministic.',
      'Any one-pass algorithm requires $\\Omega(n/\\log n)$ bits, separating it from the two-pass case.',
    ],
    significance: [
      'The improvement is the first for sparse graphs since the original interior-point reduction.',
      'Worst-case guarantees make the structure usable inside latency-sensitive systems.',
      'The separation explains why practical implementations use a second pass.',
    ],
  },
  'cs.CL': {
    venues: ['arXiv (cs.CL)', 'ACL', 'EMNLP', 'Transactions of the ACL'],
    titleHead: [
      'Measuring {A} in Multilingual Models',
      'Compositional Generalisation in {A} Parsing',
      'Evaluating {A} Faithfulness',
      'Cross-Lingual Transfer for {A} Tasks',
      'Probing {A} Structure in Sentence Encoders',
    ],
    titleFill: ['Morphological Bias', 'Semantic', 'Summarisation', 'Low-Resource', 'Syntactic'],
    background: [
      'Multilingual encoders share parameters across languages, so improvements in one language can help another.',
      'Compositional generalisation asks whether a model that has seen the parts can handle an unseen combination.',
      'Faithfulness measures whether a generated summary is entailed by its source, independent of fluency.',
    ],
    problem: [
      'Aggregate benchmark scores hide large differences between typologically distant languages.',
      'Accuracy on standard splits stays high while accuracy on compositional splits collapses, and no diagnostic explains why.',
      'Automatic faithfulness metrics correlate weakly with human judgement outside the news domain.',
    ],
    method: [
      'We construct a controlled evaluation set covering eleven languages with matched sentence lengths and frequency profiles.',
      'We compare structural probes against a behavioural test suite designed so that both measure the same construction.',
      'We collect $3{,}200$ human annotations across four domains and fit a mixed-effects model to the metric residuals.',
    ],
    result: [
      'Scores range from $84.1$ to $52.7$ across languages, and the gap correlates with morphological complexity ($r = -0.71$).',
      'Structural probes report high accuracy on constructions the model gets wrong behaviourally in $46\\%$ of cases.',
      'Correlation with human judgement drops from $0.62$ on news to $0.24$ on dialogue.',
    ],
    significance: [
      'Reporting a single aggregate number is misleading for this class of model, and the per-language breakdown is cheap to add.',
      'Probing accuracy alone should not be taken as evidence that a model uses a structure.',
      'Domain-specific calibration is necessary before these metrics can be used for model selection.',
    ],
  },
  'cs.CR': {
    venues: ['arXiv (cs.CR)', 'IEEE S&P', 'ACM CCS', 'USENIX Security'],
    titleHead: [
      'Formal Analysis of {A} Protocols',
      'Side-Channel Resistance of {A} Implementations',
      'Privacy Accounting for {A} Mechanisms',
      'Post-Quantum {A} Key Exchange',
      'Detecting {A} Supply-Chain Tampering',
    ],
    titleFill: ['Authenticated', 'Constant-Time', 'Shuffled', 'Lattice-Based', 'Build-Reproducible'],
    background: [
      'Symbolic verification proves protocol properties against an attacker who controls the network.',
      'Differential privacy bounds what an adversary can learn about any single record.',
      'Reproducible builds let a third party check that a binary corresponds to its stated source.',
    ],
    problem: [
      'The existing proof assumes an idealised key-derivation function that no deployed implementation matches.',
      'Composition bounds are loose, so deployments spend far more of their budget $\\varepsilon$ than necessary.',
      'Timing variation reintroduces a channel that the constant-time transformation was meant to close.',
    ],
    method: [
      'We model the protocol in the applied pi-calculus and discharge the obligations with an automated prover.',
      'We derive a tighter composition theorem using Rényi divergence and validate it against numerical accounting.',
      'We instrument the implementation and measure cycle counts across $10^{6}$ executions on three microarchitectures.',
    ],
    result: [
      'We prove authentication and forward secrecy under a realistic key-derivation assumption, and find one attack on an earlier draft.',
      'The bound reduces the required noise by $23\\%$ at $\\varepsilon = 1$ for the composition depths used in practice.',
      'Two of three microarchitectures leak the secret-dependent branch, recoverable in under $2^{14}$ traces.',
    ],
    significance: [
      'The attack was reported and the draft amended before deployment.',
      'The saving translates directly into utility at a fixed privacy budget.',
      'The result shows that constant-time source is not sufficient without per-microarchitecture validation.',
    ],
  },
};

const FIELD_IDS = Object.keys(FIELD_CONTENT);

const PARENT_OF = {
  'hep-th': 'physics', 'cond-mat': 'physics', 'quant-ph': 'physics', 'astro-ph': 'physics',
  'math.AP': 'math', 'math.CO': 'math', 'math.NT': 'math', 'math.PR': 'math',
  'cs.LG': 'cs', 'cs.DS': 'cs', 'cs.CL': 'cs', 'cs.CR': 'cs',
};

const ARXIV_PRIMARY = {
  'hep-th': 'hep-th', 'cond-mat': 'cond-mat.str-el', 'quant-ph': 'quant-ph', 'astro-ph': 'astro-ph.CO',
  'math.AP': 'math.AP', 'math.CO': 'math.CO', 'math.NT': 'math.NT', 'math.PR': 'math.PR',
  'cs.LG': 'cs.LG', 'cs.DS': 'cs.DS', 'cs.CL': 'cs.CL', 'cs.CR': 'cs.CR',
};

const DOI_PREFIX = {
  physics: '10.1103', math: '10.4171', cs: '10.1145',
};

function makeAuthors() {
  const n = intBetween(1, 5);
  return pickN(SURNAMES, n).map((surname) => ({
    name: `${pick(INITIALS)} ${surname}`,
    externalId: null,
    affiliation: null,
  }));
}

function countInlineMath(text) {
  const matches = text.match(/\$[^$]+\$/g);
  return matches ? matches.length : 0;
}

/** Section 8: assemble the abstract and record the offsets of each structural role. */
function buildAbstract(content) {
  const parts = [
    { section: 'background', text: pick(content.background) },
    { section: 'problem', text: pick(content.problem) },
    { section: 'method', text: pick(content.method) },
    { section: 'result', text: pick(content.result) },
    { section: 'significance', text: pick(content.significance) },
  ];
  let cursor = 0;
  const segments = [];
  const chunks = [];
  for (const part of parts) {
    const start = cursor;
    chunks.push(part.text);
    cursor += part.text.length;
    segments.push({
      start,
      end: cursor,
      section: part.section,
      // The fixture knows the true structure, so it is labelled as coming from the source
      // rather than from a classifier. Phase 2 evaluates its classifier against this.
      detectedBy: 'source',
      confidence: 1.0,
    });
    cursor += 1; // joining space
  }
  return { abstract: chunks.join(' '), segments };
}

function estimateReadingMinutes(abstract) {
  const words = abstract.split(/\s+/).length;
  return Math.max(1, Math.round((words / 130) * 10) / 10);
}

function englishLevelFor(abstract) {
  const words = abstract.split(/\s+/);
  const longWords = words.filter((w) => w.replace(/[^A-Za-z]/g, '').length >= 11).length;
  const ratio = longWords / words.length;
  if (ratio > 0.14) return 'advanced';
  if (ratio > 0.09) return 'intermediate';
  return 'beginner';
}

function mathLevelDensity(abstract) {
  const inline = countInlineMath(abstract);
  return Math.round((inline / (abstract.length / 1000)) * 100) / 100;
}

function hashId(...parts) {
  return createHash('sha256').update(parts.join('|')).digest('hex').slice(0, 32);
}

function uuidFrom(seedString) {
  const h = createHash('sha256').update(seedString).digest('hex');
  // Deterministic RFC-4122-shaped id (version 4 nibble set) so fixtures are stable.
  return [
    h.slice(0, 8),
    h.slice(8, 12),
    `4${h.slice(13, 16)}`,
    ((parseInt(h.slice(16, 17), 16) & 0x3) | 0x8).toString(16) + h.slice(17, 20),
    h.slice(20, 32),
  ].join('-');
}

const LICENSES = [
  { id: 'CC0-1.0', url: 'https://creativecommons.org/publicdomain/zero/1.0/', redistributable: true },
  { id: 'CC-BY-4.0', url: 'https://creativecommons.org/licenses/by/4.0/', redistributable: true },
  { id: 'CC-BY-SA-4.0', url: 'https://creativecommons.org/licenses/by-sa/4.0/', redistributable: true },
  // Deliberately included: the pipeline must be able to hold a record whose terms are
  // unknown, and must refuse to reuse its text (spec section 21).
  { id: null, url: null, redistributable: false },
];

function makePaper(index) {
  const fieldId = FIELD_IDS[index % FIELD_IDS.length];
  const content = FIELD_CONTENT[fieldId];
  const parent = PARENT_OF[fieldId];
  const year = intBetween(2016, 2026);
  const month = intBetween(1, 12);
  const title = pick(content.titleHead).replace('{A}', pick(content.titleFill));
  const { abstract, segments } = buildAbstract(content);
  const authors = makeAuthors();
  const arxivId = `${String(year % 100).padStart(2, '0')}${String(month).padStart(2, '0')}.${String(10000 + index * 137).slice(0, 5)}`;
  const isPreprintOnly = rand() < 0.35;
  const license = isPreprintOnly ? LICENSES[intBetween(0, 2)] : pick(LICENSES);
  const doi = isPreprintOnly ? null : `${DOI_PREFIX[parent]}/pm.${year}.${String(index).padStart(4, '0')}`;
  const paperTypes = [
    isPreprintOnly ? 'preprint' : 'published',
    rand() < 0.15 ? 'review' : 'original',
    year >= 2024 ? 'recent' : year <= 2018 ? 'classic' : null,
  ].filter(Boolean);

  const identifiers = [];
  if (doi) identifiers.push({ kind: 'doi', value: doi });
  identifiers.push({ kind: 'arxiv', value: `arXiv:${arxivId}` });
  identifiers.push({
    kind: 'title_author_year',
    value: `${title.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()}|${authors[0].name.split(' ').pop().toLowerCase()}|${year}`,
  });

  const canonicalId = doi ? `doi:${doi}` : `arxiv:${arxivId}`;
  const equationCount = countInlineMath(abstract) + intBetween(3, 40);

  const fieldWeights = { [fieldId]: 0.7, [parent]: 0.2 };
  const secondary = pick(FIELD_IDS.filter((f) => f !== fieldId));
  fieldWeights[secondary] = 0.1;

  return {
    id: uuidFrom(canonicalId),
    canonicalId,
    identifiers,
    title,
    abstract,
    abstractSegments: segments,
    authors,
    year,
    venue: pick(content.venues),
    paperTypes,
    primaryFieldId: fieldId,
    fieldWeights,
    openAccess: isPreprintOnly ? 'green' : pick(['gold', 'green', 'hybrid', 'closed']),
    retractionStatus: index === 17 ? 'corrected' : index === 41 ? 'withdrawn' : 'none',
    version: 'v1',
    supersedesPaperId: null,
    englishLevel: englishLevelFor(abstract),
    mathDensity: mathLevelDensity(abstract),
    equationCount,
    estimatedReadingMinutes: estimateReadingMinutes(abstract),
    sourceUrl: `https://arxiv.org/abs/${arxivId}`,
    pdfUrl: `https://arxiv.org/pdf/${arxivId}`,
    provenance: {
      sourceProvider: 'mock',
      acquiredAt: `${year}-${String(month).padStart(2, '0')}-15T09:00:00Z`,
      sourceUrl: `https://arxiv.org/abs/${arxivId}`,
      licenseId: license.id,
      licenseUrl: license.url,
      abstractRedistributable: license.redistributable,
      cachePolicy: license.redistributable ? 'full_cache' : 'metadata_only',
      // Explicit marker: nothing here was copied from a real paper.
      synthetic: true,
      generator: `scripts/generate-fixtures.mjs@${GENERATOR_VERSION}`,
    },
    contentHash: hashId(title, abstract),
  };
}

/**
 * Near-duplicate variants that the Phase 1 deduplicator must collapse
 * (spec section 16 / section 29: 同一DOI/arXivの重複カードが出ない).
 */
function makeDuplicateVariants(papers) {
  const variants = [];

  // 1. Same DOI, different formatting and casing, different provider.
  const a = papers.find((p) => p.canonicalId.startsWith('doi:'));
  if (a) {
    const doi = a.identifiers.find((i) => i.kind === 'doi').value;
    variants.push({
      ...structuredClone(a),
      id: uuidFrom(`${a.canonicalId}#dupe-doi-format`),
      identifiers: [
        { kind: 'doi', value: `https://doi.org/${doi.toUpperCase()}` },
        { kind: 'openalex', value: 'W2741809807' },
      ],
      title: `${a.title} `,
      venue: 'OpenAlex record',
      provenance: { ...a.provenance, sourceProvider: 'openalex', sourceUrl: `https://openalex.org/W2741809807` },
      $duplicateOf: a.canonicalId,
      $duplicateKind: 'doi_formatting',
    });
  }

  // 2. Same arXiv id, later version.
  const b = papers.find((p) => p.canonicalId.startsWith('arxiv:') && p !== a);
  if (b) {
    const arxiv = b.identifiers.find((i) => i.kind === 'arxiv').value;
    variants.push({
      ...structuredClone(b),
      id: uuidFrom(`${b.canonicalId}#v2`),
      version: 'v2',
      identifiers: [{ kind: 'arxiv', value: `${arxiv}v2` }],
      abstract: `${b.abstract} A typo in the statement of the main theorem has been corrected in this version.`,
      provenance: { ...b.provenance, acquiredAt: '2026-03-01T09:00:00Z' },
      $duplicateOf: b.canonicalId,
      $duplicateKind: 'arxiv_version',
    });
  }

  // 3. Preprint later published: no shared identifier, only normalised title + author + year.
  const c = papers.find((p) => p.canonicalId.startsWith('arxiv:') && p !== b && p !== a);
  if (c) {
    variants.push({
      ...structuredClone(c),
      id: uuidFrom(`${c.canonicalId}#published`),
      // Same words, different typography: en dashes for hyphens, doubled spacing and a
      // trailing period. Normalisation must see through all of it (spec section 16).
      title: `${c.title.replace(/-/g, '–').replace(/ /g, '  ')}.`,
      identifiers: [
        { kind: 'doi', value: `10.1103/pm.published.${c.year}` },
        {
          kind: 'title_author_year',
          value: c.identifiers.find((i) => i.kind === 'title_author_year').value,
        },
      ],
      canonicalId: `doi:10.1103/pm.published.${c.year}`,
      paperTypes: ['published', 'original'],
      openAccess: 'hybrid',
      venue: 'Physical Review D',
      provenance: { ...c.provenance, sourceProvider: 'crossref', sourceUrl: 'https://api.crossref.org/works/10.1103/pm.published' },
      $duplicateOf: c.canonicalId,
      $duplicateKind: 'preprint_published',
    });
  }

  return variants;
}

function main() {
  const papers = [];
  const seenCanonical = new Set();
  let index = 0;
  while (papers.length < TARGET_UNIQUE_PAPERS) {
    const paper = makePaper(index++);
    if (seenCanonical.has(paper.canonicalId)) continue;
    seenCanonical.add(paper.canonicalId);
    papers.push(paper);
  }

  const duplicates = makeDuplicateVariants(papers);

  const doc = {
    $meta: {
      note:
        'Synthetic sample corpus for Phase 0. All titles, abstracts, author names, venues and ' +
        'identifiers are fabricated for this repository and released under CC0-1.0. No real ' +
        'abstract text is included (spec section 31, item 4). Regenerate with `npm run fixtures:generate`.',
      generator: `scripts/generate-fixtures.mjs@${GENERATOR_VERSION}`,
      license: 'CC0-1.0',
      uniquePapers: papers.length,
      duplicateVariants: duplicates.length,
    },
    papers,
    duplicateVariants: duplicates,
  };

  mkdirSync(dirname(OUT_PATH), { recursive: true });
  writeFileSync(OUT_PATH, `${JSON.stringify(doc, null, 2)}\n`, 'utf8');

  const fields = JSON.parse(readFileSync(join(ROOT, 'fixtures', 'fields.json'), 'utf8')).fields;
  const known = new Set(fields.map((f) => f.id));
  for (const paper of papers) {
    for (const fieldId of Object.keys(paper.fieldWeights)) {
      if (!known.has(fieldId)) throw new Error(`Unknown field id in fixture: ${fieldId}`);
    }
  }

  console.log(
    `Wrote ${papers.length} synthetic papers + ${duplicates.length} duplicate variants to ${OUT_PATH}`,
  );
}

main();
