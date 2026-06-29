export const meta = {
  name: 'second-mind',
  description: 'Adversarial refutation of a quant finding/result. Spawns independent skeptics, each with a distinct kill-lens (look-ahead, priced/confound, loss-light/multiplicity, same-wall-in-disguise, data-artifact), whose ONLY job is to REFUTE the claim. Majority-refute => KILL. Operationalizes the `quant` skill (references 03-critique + 05-battle-scars). Pass the finding via args.',
  whenToUse: 'Run on EVERY positive result before believing it — a candidate edge, a backtest that looks good, a "this works" claim. The mandatory second-mind pass.',
  phases: [
    { title: 'Refute', detail: 'independent skeptics, diverse kill-lenses, each tries to falsify' },
    { title: 'Verdict', detail: 'aggregate refutations -> KILL / SURVIVES-REFUTATION + the decisive tests' },
  ],
}

// args = the finding to refute. A string, or {claim, evidence, how_measured, data_context}.
const FINDING = typeof args === 'string' ? args : JSON.stringify(args, null, 1)
if (!FINDING || FINDING === 'undefined') {
  log('ERROR: pass the finding to refute via args (a string describing the claim + the numbers + how it was measured).')
  return { error: 'no finding provided in args' }
}

const SKILL = 'C:/Users/roiy0/.claude/skills/quant/references'
const CONTEXT = `You are a SECOND MIND — an independent adversary in a quant-research process. Your ONLY job is to
REFUTE the finding below: prove it is NOT a real, tradeable edge. Do NOT review or improve it — try to KILL it. The
default is disbelief; in this domain most positives are artifacts. Read these skill references first and apply them:
  - ${SKILL}/03-critique-and-rigor.md  (the trap catalog + the gate + the joint-control + the verdict vocabulary)
  - ${SKILL}/05-battle-scars.md        (the kill-list — is this the same wall in disguise?)
Be concrete and specific. A vague "seems fine" is useless; find the SPECIFIC flaw or prove there isn't one.

THE FINDING TO REFUTE:
${FINDING}`

const REFUTER_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['lens', 'refuted', 'confidence', 'the_kill', 'decisive_test', 'verdict_one_line'],
  properties: {
    lens: { type: 'string' },
    refuted: { type: 'boolean', description: 'true if you found a flaw that kills or seriously threatens the finding' },
    confidence: { type: 'number', description: '0-1, how confident you are in the refutation (or in its absence)' },
    the_kill: { type: 'string', description: 'the SPECIFIC flaw found (mechanism + why it invalidates), or "none found via this lens"' },
    decisive_test: { type: 'string', description: 'the single concrete test that would confirm/deny this kill on the data' },
    verdict_one_line: { type: 'string' },
  },
}

const LENSES = [
  { key: 'look-ahead', prompt: `LOOK-AHEAD / LEAKAGE lens: is any future information in a "causal" feature? Subtle anchoring (e.g. entry anchored on an outcome-dependent timestamp), label leakage, survivorship in the sample, train/test contamination. The corrupt-the-future test: would the past-only signal be unchanged if all future data were corrupted? Find the leak or prove there isn't one.` },
  { key: 'priced-confound', prompt: `PRICED / CONFOUND lens (the most common kill): does the signal predict the OUTCOME but not the unpriced RESIDUAL? Run the joint-control mentally — if the obvious priced variable (the mid / closing/sharp line / the asset's own recent move) already explains it, it's "priced, just slow" = dead. Also hunt outcome-mix/Simpson confounds (control for won / measure within-winners). Is it real residual, or a restatement of the quote?` },
  { key: 'loss-light-multiplicity', prompt: `LOSS-LIGHT / MULTIPLICITY lens: how many LOSERS (n_loss)? <30 = INSUFFICIENT, a degenerate CI, not a result. How many configs/thresholds/coins/framings were tried to find this (best-of-N)? Is the p-value deflated for the HONEST trial count? Would a few extra losers flip it? Best-of-N pulses regress to the mean — is this one of them?` },
  { key: 'same-wall', prompt: `SAME-WALL-IN-DISGUISE lens: cross-reference the kill-list (05-battle-scars). Is this a walled family in new clothes (directional/knowledge=efficient-walled, microstructure/lead-lag=HFT-walled, sigma=self-priced, loss-light-filter=INSUFFICIENT-by-construction, fee-capped)? Is the apparent edge below the verified fee? Is it a convergence/look-ahead artifact (a residual that vanishes at the sharp price)? Name the wall it maps to, or prove it's genuinely novel.` },
  { key: 'data-artifact', prompt: `DATA-ARTIFACT / ROBUSTNESS lens: is it one-instrument / one-regime / one-cutoff driven (fails LOCO or by-thirds)? Cost under-charged (wrong side, missing slippage, both legs)? i.i.d. illusion (un-clustered CI on overlapping/within-window data)? Does flipping the sign make it WORSE (= no-signal, not sign-error)? Is the cost/fee the verified live number? Find the fragility or confirm robustness.` },
]

phase('Refute')
const refutations = (await parallel(LENSES.map(L => () =>
  agent(`${CONTEXT}\n\nYOUR KILL-LENS: ${L.key.toUpperCase()}\n${L.prompt}\n\nApply ONLY this lens, hard. Return your verdict.`,
    { label: `refute:${L.key}`, phase: 'Refute', schema: REFUTER_SCHEMA })
))).filter(Boolean)

const nRefuted = refutations.filter(r => r.refuted).length
const kills = refutations.filter(r => r.refuted)
log(`${nRefuted}/${refutations.length} lenses refuted the finding.`)

phase('Verdict')
const SYNTH_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['verdict', 'strongest_kills', 'decisive_tests', 'survived_concerns', 'bottom_line'],
  properties: {
    verdict: { type: 'string', enum: ['REFUTED (do not believe)', 'SERIOUSLY_THREATENED (run decisive tests first)', 'SURVIVED_REFUTATION (still default to disbelief; verify on data)'] },
    strongest_kills: { type: 'array', items: { type: 'string' } },
    decisive_tests: { type: 'array', items: { type: 'string' }, description: 'the concrete tests to run to settle it, ordered by cost-to-falsify (cheapest/most-decisive first)' },
    survived_concerns: { type: 'array', items: { type: 'string' }, description: 'residual concerns even if not outright refuted' },
    bottom_line: { type: 'string' },
  },
}
const synthesis = await agent(`${CONTEXT}

You are the SYNTHESIS judge. ${refutations.length} independent skeptics each applied one kill-lens. Below are their
verdicts. Aggregate honestly: majority-refute (or any single decisive, well-evidenced kill) => REFUTED. A real
positive must survive ALL lenses. Order the decisive follow-up tests by cost-to-falsify (cheapest/most-decisive
first). Do not manufacture either optimism or doom — weigh the evidence.

SKEPTIC VERDICTS (JSON):
${JSON.stringify(refutations, null, 1)}`,
  { label: 'verdict', phase: 'Verdict', schema: SYNTH_SCHEMA })

return { refutations, n_refuted: nRefuted, synthesis }
