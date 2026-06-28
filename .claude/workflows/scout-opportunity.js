export const meta = {
  name: 'scout-opportunity',
  description: 'Opponent-first reconnaissance of a market/venue/asset BEFORE building anything: run the scouting checklist (is a fair-value MM home? dislocation half-life? fill toxicity?), locate the money-source + the opponent (predatory vs compressive), name the demon + check small-account reach, and recommend the cheapest no-capital measurement to confirm. Operationalizes the `quant` skill (opponent-first scouting). Pass the target market via args.',
  whenToUse: 'When considering a NEW market/venue/instrument to trade — to check if the Bolt is absent/weak/too-big-to-fit and whether a small account can actually fish there, before sinking effort into a strategy.',
  phases: [
    { title: 'Scout', detail: 'opponent (scouting signatures) + money-source/payer + demon/reachability — parallel' },
    { title: 'Verdict', detail: 'pond rating + the cheapest confirming measurement + the demon' },
  ],
}

const TARGET = typeof args === 'string' ? args : JSON.stringify(args, null, 1)
if (!TARGET || TARGET === 'undefined') {
  log('ERROR: pass the market/venue/asset to scout via args (e.g. "Hyperliquid BTC perp funding" or "Kalshi weather markets").')
  return { error: 'no target provided in args' }
}

const SKILL = 'C:/Users/roiy0/.claude/skills/quant/references'
const BASE = `You are scouting a market OPPONENT-FIRST (the quant skill): find whether the "Bolt" (the sharpest player
on the deciding axis) is absent/weak/too-big-to-fit, and whether a SMALL retail account can fish here, BEFORE any
strategy is built. Read ${SKILL}/02-discovery.md (the scouting checklist + money/opponent triage) and
${SKILL}/01-mindset-and-models.md. Do REAL web research on the venue's microstructure where needed. Be concrete and
honest; flag a HIDDEN BOLT (a venue that looks soft but has an HFT/fund/fair-value-bot already in it).
THE TARGET TO SCOUT:
${TARGET}`

phase('Scout')
const OPP_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['fair_value_mm', 'dislocation_half_life', 'fill_toxicity', 'opponent_strength', 'hidden_bolt', 'how_to_measure'],
  properties: {
    fair_value_mm: { type: 'string', description: 'Signature 5: is a fair-value MM home (tight 2-sided, high-R2 vs a public reference, sub-1s re-quote = WALLED) or absent (wide/stale/lumpy = OPEN)? What is knowable, and how to measure it on free data.' },
    dislocation_half_life: { type: 'string', description: 'Sig 7: do dislocations persist >> a retail 1s latency (reachable) or <1-2s (HFT-only)?' },
    fill_toxicity: { type: 'string', description: 'Sig 3: would a passive fill mark against you (predatory/informed flow) or flat (uninformed/safe)? How to test.' },
    opponent_strength: { type: 'string', enum: ['WEAK', 'MEDIUM', 'STRONG_BOLT'] },
    hidden_bolt: { type: 'string', description: 'any HFT/fund/MM/fair-value-bot already in this venue that makes it harder than it looks; or "none evident"' },
    how_to_measure: { type: 'string', description: 'the cheapest free-data measurement that CONFIRMS opponent-strength before committing (Signature 5 first)' },
  },
}
const MONEY_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['money_source', 'payer', 'predatory_or_compressive', 'real_or_emission'],
  properties: {
    money_source: { type: 'string', enum: ['risk-premium', 'behavioral-bias', 'subsidy', 'arbitrage', 'edge/mistake', 'other'] },
    payer: { type: 'string', description: 'WHO structurally pays and WHY it persists (the forced/biased/non-economic counterparty), or "another trader = noise/priced"' },
    predatory_or_compressive: { type: 'string', enum: ['PREDATORY (takes your money = fatal)', 'COMPRESSIVE (only lowers return = survivable)', 'NON-ADVERSARIAL'] },
    real_or_emission: { type: 'string', description: 'is the profit a genuine structural premium/edge, or a token-emission/subsidy mirage that collapses when incentives end?' },
  },
}
const DEMON_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['demon', 'reachable_small_account', 'enter_and_exit', 'custody'],
  properties: {
    demon: { type: 'string', description: 'the specific catastrophe this is short (liquidation/funding-flip/depeg/adverse-selection/custody/hack/illiquidity), and how to size for it' },
    reachable_small_account: { type: 'string', enum: ['YES', 'PARTIAL', 'NO'] },
    enter_and_exit: { type: 'string', description: 'can a small account ENTER and (critically) EXIT without the illiquidity demon eating the edge?' },
    custody: { type: 'string', description: 'custody/counterparty model + KYC (self-custodial on-chain / CEX / smart-contract); the nostro risk' },
  },
}

const [opp, money, demon] = await parallel([
  () => agent(`${BASE}\n\nOPPONENT analyst — run the scouting checklist signatures on this venue.`, { label: 'opponent', phase: 'Scout', schema: OPP_SCHEMA }),
  () => agent(`${BASE}\n\nMONEY-SOURCE analyst — where does the profit come from, who pays, predatory vs compressive, real vs emission-mirage.`, { label: 'money', phase: 'Scout', schema: MONEY_SCHEMA }),
  () => agent(`${BASE}\n\nDEMON/REACH analyst — the tail risk, custody/nostro, and whether a small account can enter AND exit.`, { label: 'demon', phase: 'Scout', schema: DEMON_SCHEMA }),
])

phase('Verdict')
const VERDICT_SCHEMA = {
  type: 'object', additionalProperties: false,
  required: ['pond_rating', 'verdict', 'first_measurement', 'the_demon', 'bottom_line'],
  properties: {
    pond_rating: { type: 'string', enum: ['FISH HERE (weak opponent, reachable, non-predatory)', 'MAYBE (needs the confirming measurement)', 'WALLED (Bolt home / predatory / un-exitable)'] },
    verdict: { type: 'string' },
    first_measurement: { type: 'string', description: 'the single cheapest no-capital measurement to run first to confirm/deny (Signature 5 / the reliability diagram / the funding-persistence check)' },
    the_demon: { type: 'string' },
    bottom_line: { type: 'string' },
  },
}
const verdict = await agent(`${BASE}\n\nSYNTHESIS. Combine the three analyses into a pond verdict. FISH HERE only if the opponent is genuinely weak/absent, the money has a real payer, the worst opponent is compressive (not predatory), AND a small account can enter+exit. Otherwise MAYBE (with the confirming measurement) or WALLED. Give the cheapest no-capital first measurement and name the demon.\n\nOPPONENT:\n${JSON.stringify(opp, null, 1)}\n\nMONEY:\n${JSON.stringify(money, null, 1)}\n\nDEMON:\n${JSON.stringify(demon, null, 1)}`,
  { label: 'verdict', phase: 'Verdict', schema: VERDICT_SCHEMA })

return { opponent: opp, money, demon, verdict }
