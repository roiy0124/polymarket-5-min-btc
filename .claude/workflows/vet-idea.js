export const meta = {
  name: 'vet-idea',
  description: 'Run the quant OPERATING PROCEDURE on a candidate idea/strategy/signal: frame it as a factor with a story, locate the money + the opponent, set the base-rate prior from the kill-list, run a pre-mortem, design the cheapest kill-test, and return a PURSUE / KILL-ON-PRIORS / PARK verdict + a pre-registration card. Operationalizes the `quant` skill end-to-end. Pass the idea via args.',
  whenToUse: 'When you have a trading/strategy IDEA (not yet a result) and want a disciplined go/no-go + a test plan before building anything. For vetting an existing RESULT, use the `second-mind` workflow instead.',
  phases: [
    { title: 'Frame', detail: 'factor+story, money/opponent, base-rate prior, pre-mortem, cheapest kill-test — parallel quant lenses' },
    { title: 'Verdict', detail: 'PURSUE / KILL-ON-PRIORS / PARK + pre-registration card + test plan' },
  ],
}

const IDEA = typeof args === 'string' ? args : JSON.stringify(args, null, 1)
if (!IDEA || IDEA === 'undefined') {
  log('ERROR: pass the idea via args (a string describing the candidate strategy/signal/edge, + any data context).')
  return { error: 'no idea provided in args' }
}

const SKILL = 'C:/Users/roiy0/.claude/skills/quant/references'
const BASE = `You are applying the quant skill (a professional quant's judgment) to a candidate idea. Read the
relevant skill references first and apply them concretely — do not be generic.
THE IDEA:
${IDEA}`

phase('Frame')
const FRAME_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['factor_story', 'payer', 'opponent', 'predatory_or_compressive', 'variant_card', 'base_rate_prior', 'walled_family', 'verdict_so_far'],
  properties: {
    factor_story: { type: 'string', description: 'the idea as a FACTOR + trader-behavior story: who is forced/biased to do what, moving which price, why it persists (the limit to arbitrage). "no real story" if none.' },
    payer: { type: 'string', description: 'who structurally pays, and why they keep paying — or "another trader playing the same game = noise/priced"' },
    opponent: { type: 'string', description: 'who you compete against + the winning axis (speed/capital/info/patience); are you the Bolt\'s prey here?' },
    predatory_or_compressive: { type: 'string', enum: ['PREDATORY (profits from your trade = fatal)', 'COMPRESSIVE (only lowers return = survivable)', 'NON-ADVERSARIAL', 'UNCLEAR'] },
    variant_card: { type: 'string', description: 'the <5-line variant-perception card: idea / what the price already implies / your residual claim won-mid + mechanism / the observable trigger' },
    base_rate_prior: { type: 'number', description: 'P(this is a real, tradeable edge that clears the fee), 0-1, anchored on the kill-list base rate (low by default)' },
    walled_family: { type: 'string', description: 'which walled family (if any) this belongs to per 05-battle-scars, and whether there is a STRUCTURAL reason it differs this time' },
    verdict_so_far: { type: 'string' },
  },
}
const PREMORTEM_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['failure_modes', 'most_likely_kill', 'decisive_control'],
  properties: {
    failure_modes: { type: 'array', items: { type: 'string' }, description: 'pre-mortem: "it is 6 months later and this lost money — why?" the 5 most likely paths (priced / look-ahead / fee-eaten / best-of-N / overlap / regime)' },
    most_likely_kill: { type: 'string' },
    decisive_control: { type: 'string', description: 'the single control/test most likely to KILL it (run this first)' },
  },
}
const TESTPLAN_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['cheapest_kill_test', 'measurement', 'gate', 'locked_config', 'kill_criteria'],
  properties: {
    cheapest_kill_test: { type: 'string', description: 'the cheapest test that could falsify it, on free/historical data, before any build/capital' },
    measurement: { type: 'string', description: 'the residual/estimand to compute, the baseline/control, the clustering' },
    gate: { type: 'string', description: 'how to gate it (deflated cluster-bootstrap, n_loss>=30, joint-control vs the priced variable, net of verified fee)' },
    locked_config: { type: 'string', description: 'the params + SIGN to lock before looking (no flip-and-retest)' },
    kill_criteria: { type: 'string', description: 'pre-committed: what result = DEAD' },
  },
}

const [frame, premortem, testplan] = await parallel([
  () => agent(`${BASE}\n\nFRAMER role. Read ${SKILL}/01-mindset-and-models.md and ${SKILL}/02-discovery.md. Frame the idea: the factor+story, the payer, the opponent + winning axis (predatory vs compressive), the variant-perception card, the base-rate prior, and which walled family it belongs to (if any) + whether anything is structurally different this time.`,
    { label: 'frame', phase: 'Frame', schema: FRAME_SCHEMA }),
  () => agent(`${BASE}\n\nPRE-MORTEM critic. Read ${SKILL}/03-critique-and-rigor.md and ${SKILL}/05-battle-scars.md. It is 6 months later and this idea LOST money — write the post-mortem: the 5 most likely failure paths, the single most likely kill, and the one decisive control to run first.`,
    { label: 'premortem', phase: 'Frame', schema: PREMORTEM_SCHEMA }),
  () => agent(`${BASE}\n\nTEST-DESIGNER. Read ${SKILL}/03-critique-and-rigor.md and ${SKILL}/04-toolkit-and-workflow.md. Design the cheapest falsifying test: the measurement (residual + baseline + clustering), the gate (deflated cluster-bootstrap, n_loss>=30, joint-control vs the priced variable, net of the verified fee), the LOCKED config + sign, and the pre-committed kill criteria.`,
    { label: 'testplan', phase: 'Frame', schema: TESTPLAN_SCHEMA }),
])

phase('Verdict')
const VERDICT_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['verdict', 'why', 'preregistration_card', 'next_step'],
  properties: {
    verdict: { type: 'string', enum: ['PURSUE (run the cheap kill-test)', 'KILL-ON-PRIORS (walled family / no story / no payer)', 'PARK (real-but-gated; record the unlock)'] },
    why: { type: 'string' },
    preregistration_card: { type: 'string', description: 'the journal entry: STORY / PRIOR / CONSENSUS / RESIDUAL claim / LOCKED config+sign / KILL-IF — ready to paste into the decision journal' },
    next_step: { type: 'string', description: 'the single concrete next action; if a positive result emerges, run the `second-mind` workflow on it before believing it' },
  },
}
const verdict = await agent(`${BASE}\n\nSYNTHESIS judge. Combine the three lenses into a go/no-go. KILL-ON-PRIORS if it's a walled family with no structural difference, or has no payer / no real story (don't waste a test). PURSUE only with a concrete cheapest-kill-test. PARK if real-but-gated (record the unlock). Output the pre-registration card ready to journal, and the single next step (note: run the second-mind workflow on any positive result before believing it).\n\nFRAME:\n${JSON.stringify(frame, null, 1)}\n\nPRE-MORTEM:\n${JSON.stringify(premortem, null, 1)}\n\nTEST PLAN:\n${JSON.stringify(testplan, null, 1)}`,
  { label: 'verdict', phase: 'Verdict', schema: VERDICT_SCHEMA })

return { frame, premortem, testplan, verdict }
