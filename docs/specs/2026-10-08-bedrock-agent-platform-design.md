# Atlas on Bedrock: models, agents and briefs

**Date:** 2026-10-08 · **Status:** Proposed, pending team review · **Shared page:** https://claude.ai/code/artifact/0f2dffbe-c01d-4443-986f-d65ac26eb8d3
**Depends on:** MVP design (2026-09-23), auth + RBAC design (2026-10-08), atlas agentic north star (P0–P5)

## 1. Summary

- **Model access.** Atlas calls Claude through Bedrock's **bedrock-runtime** endpoint from ap-south-1. It does not use Mantle, which does not serve Claude in that region.
- **Chat** stays on the EC2 FastAPI loop.
- **Deep analysis** (multi-agent) runs on AgentCore Runtime. It reaches data only through atlas's governed tools.
- **Morning briefs** compute shared facts once. Each user's brief is then personalised with one cheap Haiku call.

## 2. Decisions

| Topic | Decision | Why |
|---|---|---|
| Model endpoint | **bedrock-runtime**, not bedrock-mantle | Mantle serves Claude only in-region in us-east-1, eu-west-1, eu-north-1, ap-southeast-4 and GovCloud. AWS recommends bedrock-runtime for new apps; it adds cross-region profiles and Guardrails |
| Client | `AsyncAnthropicBedrock(aws_region="ap-south-1")` (installed `anthropic` 1.8) | Same Messages request body as `anthropic_loop.py`; SigV4 through the EC2 instance role; no keys in `.env` |
| Chat hosting | EC2 FastAPI loop (unchanged) | Lowest latency, owns the SSE contract; source DBs accept only the EC2 box |
| Deep-analysis hosting | AgentCore Runtime, VPC mode, one session per job | Isolates long jobs from chat, scales out, 8-hour async jobs, built-in tracing |
| Orchestration | Bounded orchestrator-worker inside a fixed pipeline; no open swarms | The main risk is a wrong number; every extra agent is another place one can creep in |

**Governance lives at atlas's boundary.** Allowlists, audit, provenance, k-anonymity and number grounding all run inside atlas. Any agent runtime that calls atlas is held to them.

## 3. Models from ap-south-1 (bedrock-runtime)

| Model | Launched on Bedrock | Routing from ap-south-1 | Role |
|---|---|---|---|
| Opus 5.5 | 2026-09-22 | Global only | Deep-analysis lead (thinking always on, default effort medium) |
| Sonnet 5.5 | 2026-09-28 | Global only | Chat agent, deep-analysis workers |
| Haiku 5.5 | ~2026-10-07 | Global only | Per-user briefs, classification |
| Opus 5 | 2026-07-24 | Global or `in.` (Mumbai + Hyderabad) | Lead, if data must stay in India |
| Sonnet 5 | 2026-06-30 | Global or `in.` | Chat and workers, if data must stay in India |

Model ID formats:
- `global.anthropic.claude-sonnet-5-5` for Global routing
- `in.anthropic.claude-sonnet-5` for India-only routing

Other notes from the model cards:
- Regional routing carries a 10% premium over Global, per Anthropic's docs.
- Batch inference is offered for Opus 5, but not for Opus 5.5 or Sonnet 5.5.
- Structured outputs are not supported for the 5.x models; use strict tool schemas instead.

## 4. Claude features on Bedrock

| Claude feature | On Bedrock | Substitute |
|---|---|---|
| Messages, streaming, tool use, 1M context, 128K output | Yes | |
| Prompt caching (5 min / 1 h, ≤4 breakpoints) | Yes | |
| Adaptive thinking, effort | Yes | |
| Compaction (beta) | Yes (Opus 5.5 card: `compact-2026-09-04`) | |
| Context editing, memory tool, citations, PDF | Yes | |
| Mid-conversation system messages | Yes via InvokeModel (not Sonnet 5) | |
| Structured outputs | No for 5.x | Strict tool schemas |
| Code execution, programmatic tool calling | No | AgentCore Code Interpreter |
| Web search / fetch | No | AgentCore Gateway Web Search (not needed) |
| MCP connector | No | AgentCore Gateway |
| Managed Agents | No | AgentCore Harness |
| Message Batches API | No | Bedrock batch inference, per model |
| Agent Skills | No | Harness skills catalog |
| Server-side fallbacks, task budgets | No | Own code |

## 5. AWS building blocks

| Service | When | Purpose |
|---|---|---|
| bedrock-runtime (Claude) | Now | All model calls |
| Bedrock Guardrails `ApplyGuardrail` | Now | Prompt-attack and PII checks on input/output |
| AgentCore Runtime (VPC) | Now | Deep-analysis jobs |
| AgentCore Code Interpreter (SANDBOX) | Now | pandas / DuckDB over PII-free S3 extracts |
| AgentCore Observability | Now | OpenTelemetry → CloudWatch |
| Gateway + Policy + Guardrails | Later | P5 write actions; atwork calling atlas |
| Step Functions + Harness | Later | Durable multi-stage pipelines with approval steps |
| Managed Knowledge Base | Later | Search over PII-redacted CS feedback |
| Evaluations, A/B testing, Failure Insights | Later | Online quality on deep-analysis traces |
| Identity on-behalf-of, Agent Registry | Later | Cross-agent identity, catalog |
| Mantle | Skip | Not offered for Claude in ap-south-1 |
| KB structured-data retrieval | Skip | Text-to-SQL, violates guardrail 1 |
| Classic Bedrock Agents, Flows | Skip | Superseded by AgentCore |
| AgentCore Memory | Skip | Atlas's session event log is the memory |
| Browser, Payments | Skip | No use case |

## 6. Architecture

```
                     ┌──────────── atlas EC2 (ap-south-1) = GOVERNED DATA PLANE ────────────┐
Browser ──SSE──────► │ Chat loop (own code) ──► bedrock-runtime                               │
(Firebase JWT)       │ Governed tools / MCP: registry · allowlists · audit · provenance ·     │
                     │   k-anonymity ──► source DBs (read-only, IP-locked)                    │
                     │ Number grounding · Extract service ─► S3 Parquet (PII-free, 7-day TTL) │
                     │ Jobs API + session event log ◄──── progress / results ─────────┐       │
                     │ Brief workers (Haiku 5.5) ◄── EventBridge Scheduler             │       │
                     └────────┬─────────────────────────────▲─────────────────────────┼───────┘
        InvokeAgentRuntime    │ (job-scoped token)          │ governed tool calls,     │
                              ▼                             │ private VPC              │
        ┌─ AgentCore Runtime (VPC) = ELASTIC COMPUTE PLANE ─┴─────────────────────────┴─┐
        │ Lead (Opus 5.5) → Workers ×3–8 (Sonnet 5.5) → Verify → Report                 │
        │    └► Code Interpreter (SANDBOX, reads only that job's S3 prefix)             │
        └───────────────────────────────────────────────────────────────────────────────┘
```

**Rules:**
1. **Agents on AgentCore never connect to source DBs.** They see data only through atlas's governed tools, so the IP-allowlist rule (CLAUDE.md guardrail 3) still holds.
2. **Scope comes from a job token, never from the prompt.** Atlas checks the user's Firebase token, then issues a short-lived job token (user, scopes, job id, allowed tools). AgentCore never holds DB credentials.
3. **Number grounding runs in atlas when a result is submitted.** Every number in a report must trace to logged tool or program output. This holds for any agent framework.

## 7. Deep analysis flow

1. **Plan (Opus 5.5).**
   - Turn the question into hypotheses across dimensions: cohort retention, RFM segments, channel ROAS, CAC vs LTV, creative fatigue, campaign lift.
   - The user approves a plan card that shows the cost estimate.
2. **Fan out (Sonnet 5.5 workers, 3–8).** Each worker has its own context. It:
   - calls `atlas.metric`, `breakdown` or `records()` (which writes PII-free Parquet to S3)
   - runs Python in Code Interpreter
   - returns only a compact finding: claim, numbers, provenance refs, program, caveats
3. **Verify.**
   - A deterministic number-grounding pass.
   - A critic that checks the confounder registry (e.g. the May 2025 `users_user` id cutover), data freshness and attribution caveats.
   - At most two follow-up rounds.
4. **Report.**
   - Provenance chips expand to the program behind each number.
   - Charts go to S3, and the user is notified.

**Guards:**
- per-job token and wall-clock budgets
- prompt caching on the shared system prompt and tool prefix
- every step appended to the atlas event log

**Code Interpreter is a compute box, not a security boundary.** Unit 42 and BeyondTrust published escapes from its sandbox network isolation. So:
- only PII-free extracts go in
- its role can read only that job's S3 prefix
- the planned local no-network sandbox stays as a second provider behind the same `ExecutionRuntime` interface

## 8. Per-user morning brief

Each brief is one Haiku call over facts computed once for everyone, not an agent per user.

1. **Shared facts, no LLM (~05:30 per timezone group).**
   - For every metric × segment: deltas, seasonality-aware anomalies, freshness, and a confounder-registry check.
   - Results go into a `daily_facts` table with provenance.
   - Stale sources are flagged, never reported as fresh.
2. **Shared insights (Sonnet 5.5, once per anomaly).**
   - Each significant anomaly is explained once.
   - A large anomaly can trigger one shared deep-analysis job, reused by every user who follows that metric.
3. **Personalise (Haiku 5.5, one call per user).**
   - Filter the facts by RBAC scope and subscriptions.
   - The day's shared facts sit in the cached prompt prefix.
   - Every number must exist in `daily_facts`; otherwise the sentence is regenerated or dropped.
4. **Deliver** by email (SES), Slack or in-app.
   - The user approves the subscription once through a review card, which pre-approves each daily send (DESIGN.md).

**Plumbing:**
- EventBridge Scheduler → atlas jobs table / SQS → plain worker containers.
- No AgentCore needed: it's one LLM call per user.
- Bedrock batch inference doesn't cover Haiku 5.5 or Sonnet 5.5, so workers use plain concurrency within the tokens-per-minute quota.

## 9. Swarm or graph

**No large swarm.** Atlas uses a fixed pipeline with a bounded set of parallel workers, and scales by splitting data, not by adding agents.

- **Multi-agent pays off** for breadth-first research with independent subtasks: roughly 15× the tokens of a chat, for large quality gains (Anthropic's research system).
- **It hurts** when reasoning is tightly coupled, and errors compound across agents.
- **Swarms** are non-deterministic, hard to audit and expensive.
- **Graphs** (a fixed pipeline with LLMs inside each step) are the pattern proven in production.

| Job | Orchestration |
|---|---|
| Under ~30 minutes | In-process fan-out (asyncio or Strands) in one Runtime session |
| Multi-day or approval-gated (P4/P5) | Step Functions running Harness steps, with human-approval states |
| Same analysis across many segments | Map one worker over the segments |

Revisit only when evals show a single agent hitting a ceiling on breadth tasks, judged by cost per completed task.

## 10. Framework fit

| Workload | Choice | Why |
|---|---|---|
| Chat | Atlas's own loop | Built, lowest latency, owns the SSE contract |
| Deep-analysis lead | Strands on AgentCore Runtime | Custom plan/verify control; team already runs Strands in atwork_agent |
| Leaf workers, scheduled pipelines | AgentCore Harness | Declarative; Lambda lifecycle hooks allow/deny tool calls; native Step Functions |
| Morning briefs | Plain worker calling Bedrock | One LLM call per user |

**Strands sdk-python is at 1.59; atwork_agent is pinned to 1.22** and should be upgraded. Recent additions:
- a subagent tool
- `agent.cancel()`
- interrupts that resume through nested agent-as-tool calls
- `SnapshotSessionManager`
- an open-source Strands harness

## 11. Rollout

1. **A. Chat on Bedrock.**
   - Attach an EC2 IAM role with `bedrock:InvokeModel` and `bedrock:InvokeModelWithResponseStream` on the inference profiles and model ARNs.
   - Set the IMDS hop limit to 2 so containers get credentials.
   - Switch chat to `AsyncAnthropicBedrock`.
   - Reach eval parity with the OpenAI baseline (15/15 on gpt-4.1).
2. **B. Governed compute.**
   - `records()` writes PII-free Parquet to S3.
   - Add the `ExecutionRuntime` seam with local and Code Interpreter providers.
   - Add number grounding.
3. **C. Deep analysis.** Job API, job tokens, a Strands agent on Runtime in VPC mode, plan card, progress events, report artifact.
4. **D. Morning briefs.** `daily_facts`, then Scheduler and Haiku 5.5 workers.
5. **E. Platform.** Step Functions + Harness pipelines, Gateway + Policy for P5 writes, KB over redacted feedback.

Each phase needs golden coverage in `evals/goldens/` before merge (CLAUDE.md guardrail 6).

**Smoke tests before committing:**
- [ ] `AsyncAnthropicBedrock` streams with tools against `global.anthropic.claude-sonnet-5-5`
- [ ] Model access is enabled in the AWS account
- [ ] AgentCore Runtime in VPC mode reaches the atlas MCP port
- [ ] Code Interpreter has the needed Python libraries preinstalled

## 12. Open questions

- [ ] Is Global routing acceptable for business aggregates, or must inference stay in India? This decides between the 5.5 family and Opus 5 / Sonnet 5 with `in.` profiles.
- [ ] Is the atlas EC2 box in the same AWS account as atwork_agent (685617232486)?
- [ ] Which brief delivery channel ships first: email, Slack or in-app?
- [ ] What minimum cohort size should `records()` enforce?

## Sources

- [Bedrock endpoints](https://docs.aws.amazon.com/bedrock/latest/userguide/endpoints.html)
- AWS model cards: [Opus 5](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-opus-5.html), [Opus 5.5](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-opus-5-5.html), [Sonnet 5](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-sonnet-5.html), [Sonnet 5.5](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-sonnet-5-5.html), [Haiku 5.5](https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-anthropic-claude-haiku-5-5.html)
- Anthropic: [Claude in Amazon Bedrock](https://platform.claude.com/docs/en/build-with-claude/claude-in-amazon-bedrock), [legacy integration](https://platform.claude.com/docs/en/build-with-claude/claude-on-amazon-bedrock-legacy)
- [AgentCore release notes](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/release-notes.html), [Harness GA](https://aws.amazon.com/about-aws/whats-new/2026/06/amazon-bedrock-agentcore-harness-generally-available/), [AgentCore limits](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/bedrock-agentcore-limits.html)
- Code Interpreter: [S3 integration](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-s3-integration.html), [Unit 42 research](https://unit42.paloaltonetworks.com/bypass-of-aws-sandbox-network-isolation-mode/)
- Strands: [sdk-python releases](https://github.com/strands-agents/sdk-python/releases), [Bedrock provider](https://strandsagents.com/docs/user-guide/sdk/model-providers/amazon-bedrock/)
- [AWS weekly roundup, 28 Sep 2026](https://aws.amazon.com/blogs/aws/aws-weekly-roundup-gpt-6-sol-and-luna-claude-opus-5-5-on-amazon-bedrock-strands-harness-and-more-september-28-2026/)
