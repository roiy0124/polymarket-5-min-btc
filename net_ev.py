"""net_ev — fee-aware net expected value per $1 staked for the 5-min binary markets.

Encodes the project's DECIDED accounting (IDEAS.md A.1 + memory exit-execution-verdict /
polymarket-taker-fee):
  - TAKER entry pays the dynamic crypto fee  fee/stake = 0.07*(1 - p)  (p = fill price).
  - MAKER entry/exit pays 0 fee and earns a small CAPPED rebate.
  - HOLD to the 0/1 resolution pays NO exit fee (settlement is not a taker trade).
  - a miss is the full -100% of stake (binary).
Everything is per $1 STAKED so positions at different prices compare directly.

The favorite-tail strategy uses entry_mode='taker', exit_mode='hold' -> only the entry fee bites.

    from net_ev import net_ev_per_dollar, breakeven_winrate, wilson_lb
"""

import math

FEE_RATE = 0.07          # crypto_fees_v2, confirmed live on the 5-min market
REBATE_SHARE = 0.20      # maker rebate share — RE-VERIFY live before arming (memory polymarket-taker-fee)


def taker_fee_per_stake(p):
    """Taker fee as a fraction of stake at fill price p:  0.07*(1-p)."""
    return FEE_RATE * (1.0 - p)


def maker_rebate_per_stake(p, share=REBATE_SHARE, cap=0.004):
    """Maker rebate per stake — mirrors the p(1-p) fee curve, scaled by the maker share,
    then HARD-CAPPED so it can never on its own flip a marginal maker leg positive
    (prevents silently re-introducing rebate-farming). Largest at p=0.5, ~0 at the tails."""
    r = share * FEE_RATE * p * (1.0 - p)
    return min(r, cap)


def net_ev_per_dollar(entry_price, won, entry_mode="taker", exit_mode="hold",
                      exit_price=None, exit_filled=False, rebate=False):
    """Net EV per $1 staked for ONE position.

    entry_price : fill price (ask for a taker buy).
    won         : 1 if the bought side won at resolution else 0.
    entry_mode  : 'taker' (pays 0.07*(1-p) fee) | 'maker' (0 fee, optional rebate).
    exit_mode   : 'hold' (hold to 0/1, no exit fee) |
                  'maker_rest' (rest a sell at exit_price; if exit_filled realize it, else hold to 0/1).
    rebate      : credit the capped maker rebate on maker legs.
    """
    a = entry_price
    if a <= 0 or a >= 1:
        return None
    if exit_mode == "maker_rest" and exit_filled and exit_price is not None:
        gross = (exit_price - a) / a            # resting sell filled
    else:
        gross = (won - a) / a                   # hold to 0/1: +(1/a - 1) on win, -1.0 on loss (the -100%)
    fee = 0.0
    if entry_mode == "taker":
        fee += taker_fee_per_stake(a)
    elif entry_mode == "maker" and rebate:
        fee -= maker_rebate_per_stake(a)
    if exit_mode == "maker_rest" and exit_filled and rebate:
        fee -= maker_rebate_per_stake(exit_price)
    return gross - fee


def breakeven_winrate(a, entry_mode="taker"):
    """Win-rate at which net EV = 0 for a buy at price a (taker-entry, hold exit).
    EV = w/a - 1 - fee = 0  ->  w* = a*(1 + fee_per_stake)."""
    fee = taker_fee_per_stake(a) if entry_mode == "taker" else 0.0
    return a * (1.0 + fee)


def wilson_lb(k, n, z=1.96):
    """One-sided Wilson lower bound of a win-rate k/n. The honest test for high-win-rate /
    loss-light subsets where the bootstrap CI is degenerate (loss=0 -> falsely excludes 0)."""
    if n == 0:
        return 0.0
    p = k / n
    d = 1.0 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (c - m) / d
