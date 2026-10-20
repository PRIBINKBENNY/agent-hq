---
name: uk-trading-rules
description: "Use when the task needs Trading rules and context for a UK retail trader. Current practice as of 2026-10-18, with sources."
metadata:
  updated: 2026-10-18
  source: Agent HQ (github.com/PRIBINKBENNY/agent-hq), office/skills/uk-trading-rules.md
---

# Trading rules and context for a UK retail trader

- This desk trades the Capital.com DEMO account only. Nothing here is financial advice. Live trading stays locked.
- UK retail CFDs: firms must warn that CFDs are complex and carry a high risk of losing money rapidly due to leverage,
  with a per-provider percentage of retail accounts that lose money (roughly 50-80% across UK brokers in 2026).
  Most retail accounts lose money: the desk's edge must be proven out of sample before any real money is considered.
- Leverage caps for UK/EU retail CFDs (ESMA-derived): 30:1 major FX, 20:1 minor FX/gold/major indices, 10:1 other
  commodities/minor indices, 5:1 shares. Crypto derivatives are BANNED for UK retail clients (FCA, since January 2021):
  crypto strategies are demo research; they could not be traded live on a UK retail account.
- Risk process: 1% risk per trade, reward/risk >= 1.5, 5 trades a day, daily loss limit; position size from the stop
  distance, never from conviction. Weekend gaps: markets other than crypto are closed; stops can be jumped on the open.

(provider warnings), ESMA/FCA CFD measures (CMS summary). Check the FCA Handbook before relying on any figure.

## Sources

FCA Handbook COBS 22.5 (CFD risk warning), theinvestorscentre.co.uk (UK CFD statistics 2026), brokerchooser.com
