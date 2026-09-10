# implementation-examples
Examples of implementations of OVON interoperability specifications.

## OpenFloor installation note
`openfloor` is published on TestPyPI (not PyPI).

If you need to run code that imports `openfloor`, install it with:

```bash
pip install events==0.5
pip install --index-url https://test.pypi.org/simple/ --no-deps openfloor==0.1.4
```

See [assistantClient setup](./assistantClient/README.md#installation) for full local setup steps.

## Agents and Templates
- [erin](./erin/README.md) - Hallucination demo agent that intentionally includes at least one incorrect claim.
- [stella](./stella/README.md) - Space and astronomy assistant backed by NASA APIs.
- [verity](./verity/) - Fact-checking agent that detects and mitigates hallucinations.
- [time-agent](./time-agent/README.md) - World time agent for major cities.
- [agent-template](./agent-template/README.md) - OpenFloor agent template with full event handling.

## Multi-Agent Teams
A convener plus a set of domain specialists. The **floors** these teams run on -- the floor manager / gateway that owns conversation and floor state and drives every exchange -- live in the [`floor-implementations`](https://github.com/open-voice-interoperability/floor-implementations) repository (e.g. `web-floor`); these folders provide the participants a floor invites.

Every specialist and every convener here is a full, standalone OFP `BotAgent` with its own manifest and HTTP endpoint. Nothing binds them to their own team: any of them can be invited into a different OFP conversation, mixed with agents from another team, or used on its own, as long as a spec-compliant floor manager (or another convener) is driving.

### [cafeteria-ops](./cafeteria-ops/README.md) — cafeteria lunch-menu planning and supply chain
- **Cafeteria Ops Convener** (8300) - stateless decision service: tells the floor manager who to invite/grant next.
- **Menu Designer** (8301) - lunch-menu concepts, weekly variety and theme; generates an illustrative AI image per meal.
- **Nutrition Specialist** (8302) - calories, macros and sodium from real USDA FoodData Central data.
- **Recipe & Portion Specialist** (8303) - real recipe ideas (TheMealDB) and cafeteria-scale portion sizing.
- **Menu Optimization Specialist** (8304) - cost, ingredient reuse and waste reduction across the menu mix.
- **Inventory Specialist** (8305) - par levels, stockout and overstock risk.
- **Procurement Specialist** (8306) - sourcing grounded in real USDA AMS wholesale data, with a live web-search fallback for items USDA doesn't track.
- **Shopping List Specialist** (8310) - sums a week's menu into total ingredient quantities, estimated cost and cost-per-plate.

### [startup-strategy](./startup-strategy/README.md) — startup concept analysis
- **Convener** (8199) - stateless decision service: tells the floor manager who to invite/grant next.
- **Market Validator** (8200) - TAM/SAM/SOM and demand sizing.
- **Competitive Intelligence** (8201) - competitor and positioning analysis.
- **Business Model Designer** (8202) - monetization and model framing.
- **Risk Identifier** (8203) - risk register and failure modes.
- **Funding Strategist** (8204) - raise strategy and milestone planning.
- **Workforce Strategist** (8205) - team, hiring and labor planning.
- **Devil's Advocate** (8206) - contrarian challenge and downside pressure test.
- **Strategy Synthesizer** (8207) - consolidated recommendation.
- **Technical Feasibility** (8208) - technical implementation and feasibility analysis (available for direct use; not in the convener's core sequence).

## Earlier Specification Samples
These folders are based on earlier versions of the specifications and are kept for reference:
- [aws-interop-sample](./aws-interop-sample/README.md)
- [go-examples](./go-examples/)
- [js-examples](./js-examples/README.md)
- [mcp](./mcp/)
- [websockets](./websockets/README.md)
