### Step 12: Downstream Integration (Highest User Value)

**Zero regime consumption exists in any strategy coordinator today.** The regime signal's value cannot be realized without integration.

**New file: `regime/context.py`**

```python
@dataclass(frozen=True)
class RegimeContext:
    regime: str                    # dominant macro regime (G/R/S/D)
    regime_confidence: float       # 0-1, posterior peakedness
    stress_level: float           # 0-1, P(stress) from stress HMM
    stress_onset: bool            # True if stress crossed above threshold this week
    shift_velocity: float         # rate of change in stress_level
    suggested_leverage_mult: float # 0-1, recommended sizing scalar
    regime_allocations: dict      # {SPY: 0.25, TLT: 0.55, ...} current optimal mix
```

#### Critical Design Constraint: Regime Allocations != Strategy Capital

The regime model produces macro ETF portfolio allocations (SPY/TLT/GLD/IBIT/EFA/CASH). The trading strategies trade **setups ON** those assets, not portfolio allocations OF them. BRS doesn't hold 27.8% SPY -- it trades QQQ breakout signals with $30 unit risk. The regime allocations cannot be directly mapped to strategy capital percentages. The regime signal's downstream value is in setting the **risk envelope** (caps, sizing, directional bias), not in picking individual trades or dictating per-strategy capital splits.

#### Refresh Frequency: Weekly (Not Daily)

The regime engine operates at **weekly frequency** (`rebalance_freq: "W-FRI"` in `regime/config.py`). R8/R9 were optimized and validated on weekly rebalance cadence. Daily refresh adds no value because:

1. **The signal barely changes day-to-day.** Near-binary posteriors (AvgP(dominant) = 0.993-1.000) with ~122-week average spells mean the regime classification is identical to yesterday's 99.9% of the time.
2. **The model was never validated at daily frequency.** The daily eval numbers (Sharpe 1.917) measure daily rebalancing of ETF portfolio weights (drift correction), not daily regime signal changes. Underlying macro features (growth, inflation, credit spreads, yield curve) update at weekly+ cadence.
3. **Daily refresh adds fragility without benefit.** A stale weekly signal has zero impact for 5 days. A daily dependency creates unnecessary operational risk.

**Recommended schedule:** Friday close or Monday pre-market, matching the model's native `W-FRI` rebalance frequency and macro feature update cadence.

#### Integration Architecture: 2-Tier Model

The existing coordinator architecture is explicitly designed for config-driven risk management. Momentum coordinator documents: "Cross-strategy coordination is config-driven via PortfolioRulesConfig, NOT via in-process signaling." The `RegimeContext` fits this philosophy. Integration follows two tiers:

- **Tier 1 (Family Coordinator Level):** RegimeContext mutates `PortfolioRulesConfig` fields at weekly refresh. No engine changes. Highest value.
- **Tier 2 (Per-Regime Strategy Config Profiles):** Pre-defined config overrides that swap when regime transitions (~every 2.3 years). Moderate value.

**Per-bar regime conditioning inside engines is NOT recommended** -- the regime transitions every ~122 weeks; injecting it into 5-15 minute bar loops violates the config-driven philosophy, creates signal frequency mismatch, and adds complexity (12 substrategies x 4 regimes x multiple assets) for negligible marginal value. The one exception is the **Overlay engine**, which IS a portfolio allocation strategy where regime allocations have a 1:1 mapping.

---

### Step 12a: Tier 1 -- Family Coordinator Config Mutations (Weekly Refresh)

This is where RegimeContext has the highest value. Each coordinator reads config at startup and passes `PortfolioRulesConfig` to the OMS. On each weekly regime refresh, the coordinator mutates these fields based on the current regime classification.

#### Stock Family (ALCB, IARIC, US_ORB -- 3 substrategies, per-strategy OMS, client_id=31)

All 3 substrategies trade the same universe (SPY/QQQ/IWM). The regime primarily controls **aggregate risk**, not which substrategy to favor. IARIC (pullback), ALCB (breakout), and US_ORB (opening range) have fundamentally different edge profiles that don't align cleanly to macro regimes -- a Defensive regime doesn't make IARIC better than ALCB, it makes all equity entries riskier.

| Knob | Goldilocks | Reflation | Stagflation | Defensive | Config Field |
|---|---|---|---|---|---|
| Directional cap | 8.0R (current) | 6.0R | 5.0R | 4.0R | `directional_cap_R` |
| Unit risk scaling | 1.0x | 0.9x | 0.7x | 0.5x | `unit_risk_dollars` per strategy |
| Priority headroom | 3.0R (current) | 3.0R | 2.0R | 1.5R | `priority_headroom_R` |
| DD tier trip points | Normal | Normal | 1% earlier | 2% earlier | `dd_tiers` |
| Symbol collision | half_size | half_size | block | block | `symbol_collision_action` |

**Rationale for directional cap as primary lever:** The family-scoped 8R directional cap (across ALCB + IARIC + US_ORB) is the single biggest risk control. Reducing it from 8R to 4R in Defensive halves the family's maximum aggregate long exposure. This is more effective than per-strategy unit risk scaling because it constrains total portfolio heat regardless of which substrategy generates signals.

**Rationale for tighter symbol collision in stress:** Currently "half_size" allows siblings to hold the same ticker at 50% size. In Stagflation/Defensive, switching to "block" prevents concentration risk when multiple substrategies pile into the same equity during a deteriorating regime.

#### Momentum Family (VdubusNQ, NQDTC, Helix, DownturnDominator -- 4 substrategies, per-strategy OMS, client_id=11)

Momentum is the family where regime matters most for **directional bias**. All 4 substrategies trade MNQ. The `directional_cap_long_R` / `directional_cap_short_R` asymmetry is the highest-value regime knob here.

| Knob | Goldilocks | Reflation | Stagflation | Defensive | Config Field |
|---|---|---|---|---|---|
| Directional cap (symmetric) | 3.5R (current) | 3.0R | 2.5R | 2.0R | `directional_cap_R` |
| Long cap (asymmetric) | 3.5R | 3.0R | 2.0R | 1.5R | `directional_cap_long_R` |
| Short cap (asymmetric) | 0 (disabled) | 1.0R | 2.0R | 2.5R | `directional_cap_short_R` |
| Unit risk scaling | 1.0x | 0.9x | 0.7x | 0.5x | `unit_risk_dollars` per strategy |
| MNQ contract cap | current | 0.9x | 0.7x | 0.5x | `max_family_contracts_mnq_eq` |
| DD tier trip points | Normal | Normal | 1% earlier | 2% earlier | `dd_tiers` |
| NQDTC oppose mult | 0.0 (block) | 0.0 | 0.5 (allow shorts) | 0.5 | `nqdtc_oppose_size_mult` |

**Rationale for asymmetric directional caps:** In Goldilocks, long-only is correct (all NQ alpha is long-biased in bull regimes). In Defensive, the long cap should tighten to 1.5R while the short cap opens to 2.5R. This lets DownturnDominator and counter-trend signals take meaningful short exposure during bear regimes without competing with long signals for directional headroom.

**Rationale for NQDTC oppose filter relaxation:** Currently `nqdtc_oppose_size_mult=0.0` blocks Vdubus from trading against NQDTC's direction. In Stagflation/Defensive, this filter should soften to 0.5x to allow short Vdubus signals when NQDTC is biased long -- the macro context overrides the intraday trend agreement requirement.

#### Swing Family (ATRSS, S5_PB, S5_DUAL, Breakout_V3, Helix, BRS -- 6 substrategies, shared OMS, client_id=7)

Swing has the multi-asset complexity (QQQ, GLD, IBIT). The Overlay engine is where regime has the most direct mapping -- regime allocations literally tell you the optimal asset mix. In Stagflation (GLD allocation 0.364, SPY 0.141), the overlay should shift heavily toward GLD. In Defensive (TLT 0.631, CASH 0.533), the overlay should be GLD-only or disabled.

| Knob | Goldilocks | Reflation | Stagflation | Defensive | Config Field |
|---|---|---|---|---|---|
| Directional cap | 6.0R (current) | 5.0R | 4.0R | 3.0R | `directional_cap_R` |
| Unit risk scaling | 1.0x | 0.9x | 0.8x | 0.6x | `unit_risk_dollars` per strategy |
| Overlay QQQ allocation | 60% | 50% | 20% | 0% | `OverlayConfig.capital_allocation` |
| Overlay GLD allocation | 40% | 50% | 80% | 100% | `OverlayConfig.capital_allocation` |
| Overlay enabled | Yes | Yes | Yes | GLD-only | `OverlayConfig.enabled` / symbols |
| DD tier trip points | Normal | Normal | 1% earlier | 2% earlier | `dd_tiers` |

**Rationale for Overlay as primary regime consumer:** The Overlay engine is the ONLY engine where regime allocations have a 1:1 mapping to what the engine does -- it deploys idle capital into QQQ/GLD via EMA crossover with configurable capital splits. The regime model's asset allocation signal (R9: SPY 0.278 in Goldilocks vs 0.042 in Defensive; GLD 0.031 in Goldilocks vs 0.364 in Stagflation) directly translates to Overlay capital weighting. This is the cleanest, highest-confidence regime integration point in the entire system.

**Rationale for GLD-only Overlay in Defensive:** In Defensive regime, regime allocations show TLT 0.631, CASH 0.533, GLD 0.104, SPY 0.042. Equity exposure should be minimal. Disabling QQQ overlay and keeping only GLD preserves some idle-capital deployment while respecting the regime's strong anti-equity signal. BRS bear regime check (already wired) provides intrabar confirmation.

---

### Step 12b: Tier 2 -- Per-Regime Strategy Config Profiles

Pre-defined config overrides that swap when regime transitions (~every 2.3 years on average). These control **which setups get taken** rather than how much risk per setup -- the "strategy selection" layer. Lower priority than Tier 1 because regime transitions are rare.

```yaml
regime_profiles:
  stock:
    Goldilocks:
      alcb_max_positions: 8        # full capacity, breakout-friendly
      iaric_max_positions: 5       # full capacity
      us_orb_enabled: true         # ORB works in trending markets
    Reflation:
      alcb_max_positions: 6        # slightly reduced
      iaric_max_positions: 5       # pullbacks still valid
      us_orb_enabled: true
    Stagflation:
      alcb_max_positions: 4        # breakouts less reliable
      iaric_max_positions: 3       # fewer pullback opportunities
      us_orb_enabled: false        # ORB fails in choppy markets
    Defensive:
      alcb_max_positions: 3        # minimal breakout exposure
      iaric_max_positions: 2       # minimal pullback exposure
      us_orb_enabled: false        # ORB disabled

  momentum:
    Goldilocks:
      downturn_enabled: false      # short-only strategy stays paper
      vdubus_long_bias: true       # favor long setups
    Reflation:
      downturn_enabled: false
      vdubus_long_bias: true
    Stagflation:
      downturn_enabled: true       # activate short-only in paper->live
      vdubus_long_bias: false      # allow both directions
    Defensive:
      downturn_enabled: true       # full short-only activation
      vdubus_long_bias: false

  swing:
    Goldilocks:
      brs_qqq_enabled: true        # QQQ breakouts in bull regime
      brs_gld_enabled: true
      s5_pb_ibit_enabled: true     # crypto pullbacks in risk-on
    Reflation:
      brs_qqq_enabled: true
      brs_gld_enabled: true        # GLD benefits from reflation
      s5_pb_ibit_enabled: true
    Stagflation:
      brs_qqq_enabled: false       # QQQ breakouts unreliable
      brs_gld_enabled: true        # GLD breakouts thrive
      s5_pb_ibit_enabled: false    # crypto weak in stagflation
    Defensive:
      brs_qqq_enabled: false       # minimal equity exposure
      brs_gld_enabled: true        # GLD as safe haven
      s5_pb_ibit_enabled: false
```

**Note:** Tier 2 profiles are illustrative defaults. Actual values should be validated via backtesting before deployment. The key principle is that regime config profiles are loaded once per transition and held static until the next transition -- they are NOT evaluated per-bar.

---

### What NOT To Integrate: Per-Bar Regime Conditioning Inside Engines

**Do NOT push RegimeContext into individual engine `on_bar()` loops.** Three reasons:

1. **Architecture violation**: Coordinators are "config-driven via PortfolioRulesConfig, NOT via in-process signaling." Per-bar regime checks break this contract.
2. **Signal frequency mismatch**: Regime transitions every ~122 weeks. Engine bars fire every 5-15 minutes. A macro signal has no business making per-bar decisions.
3. **Complexity explosion**: 12 substrategies x 4 regimes x multiple assets = dozens of per-bar regime branches to test and maintain. The marginal value vs Tier 1/2 is negligible.

**The one exception:** The Overlay engine should receive regime allocations directly because it IS a portfolio allocation strategy. This is the only engine where regime allocations have a 1:1 mapping.

---