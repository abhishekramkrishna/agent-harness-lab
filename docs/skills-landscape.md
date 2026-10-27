# Agent skill collections worth knowing (October 2026)

Notes from reading the repositories, written while building the `skills/` pack in this repo. Each entry says what the collection does well and what this repo borrowed. Facts are from the repositories themselves unless a source is linked.

## Matt Pocock: `mattpocock/skills`

"Skills for real engineers, not vibe coding." Small, composable skills, each introduced by the failure it fixes (the agent misunderstood you, the agent is too verbose, the code does not work, the codebase became a ball of mud), with a quote from the engineering book the fix comes from.

What stands out:

- **User-invoked vs model-invoked.** User-invoked skills (`/grill-me`, `/to-spec`, `/wayfinder`) orchestrate and only run when typed. Model-invoked skills (`tdd`, `diagnosing-bugs`, `grilling`) hold reusable discipline and may be picked up automatically. A user-invoked skill may call model-invoked ones, never another user-invoked one.
- **Grilling as a primitive.** `grilling` interviews in rounds over a design tree, asking the whole frontier at once, each question with a recommended answer. Many other skills call it.
- **Shared language.** `grill-with-docs` and `domain-modeling` maintain a glossary so the agent uses one word where it used twenty.
- **Tiny files.** `grill-me` is one line: "Call the Skill tool with grilling." Composition does the work.

Borrowed here: the user/model split and the no user-to-user rule (enforced by `harnesslab skills`), interview rounds with recommended answers (`interview-rounds`, credited), and naming each skill after the failure it fixes.

## Addy Osmani: `addyosmani/agent-skills`

"Production-grade engineering skills for AI coding agents." About 25 skills mapped onto a lifecycle (define, plan, build, verify, review, ship) with slash commands for each phase (`/spec`, `/plan`, `/build`, `/test`, `/review`, `/ship`), reviewer personas, hooks, and shared checklists (security, performance, accessibility, observability).

What stands out:

- **Common Rationalizations tables.** Each skill lists the excuses an agent (or engineer) uses to skip it, with the reply. This is the most transferable writing pattern in any collection.
- **Skills are tested.** A zero-dependency eval runner checks that every skill's own prompts route to it (top-3), that other skills' prompts do not (not rank 1), and that no two descriptions are near-duplicates (cosine similarity warn at 0.5, fail at 0.75). A separate opt-in tier runs behavioural evals through headless Claude Code.
- **Doubt-driven development.** A skill that sends non-trivial decisions to a fresh-context reviewer biased to disprove them.

Borrowed here: rationalization tables, "Done when" checklists, trigger evals with positive and negative prompts, and the collision thresholds.

## Anthropic: `anthropics/skills`

The reference implementation and the Agent Skills specification (agentskills.io): document skills (docx, pdf, pptx, xlsx), `skill-creator`, `mcp-builder`, `webapp-testing`, design skills. Read it for the package format and for `skill-creator`, which builds and measures skills.

## Jesse Vincent: `obra/superpowers`

A process library for Claude Code: brainstorming before building, writing plans, test-driven development, systematic debugging, verification before completion, subagent-driven development. Its `writing-skills` skill treats a skill like code under TDD: run a pressure scenario with a subagent, watch it fail without the skill, write the skill, watch it pass, close loopholes. That is the strongest answer anywhere to "how do you know a skill works?".

## Others worth a look

- **Vercel** (`vercel-labs/agent-skills`) for React and Next.js, and the `npx skills` installer (`vercel-labs/skills`) that most collections now document.
- **Trail of Bits** security-auditing skills.
- **Vendor skills** from Supabase, Cloudflare, Sentry, NVIDIA and others: the pattern of a vendor shipping "how to use our product correctly" as a skill. NVIDIA's adds signatures, skill cards and evaluation datasets ([overview](https://shop.zimaspace.com/blogs/tech-ai-hub/2026-june-top-ai-agent-skills-recommended)).
- **VoltAgent `awesome-agent-skills`**, a curated directory of about 1,500 skills across vendors and the community ([GitTrend](https://gittrend.io/repo/VoltAgent/awesome-agent-skills)).

## What this repo adds

The two leading collections are about writing software with an agent. This pack is about **building and running the agent harness itself**, and each skill is tied to code that demonstrates it:

1. **Every skill has a "Proof" section** pointing at a test or benchmark in this repo that shows the failure and the fix. A claim in a skill is only as good as its demo.
2. **The pack is tested as a whole on every commit:** lint, collisions, trigger evals and the composition rules (`harnesslab skills`, run in CI).
3. **Failure-mode taxonomy shared across skills, traces and tests.** The failure modes in `trace-autopsy` are the faults the mock model injects, so every row of the table can be reproduced with one command.
