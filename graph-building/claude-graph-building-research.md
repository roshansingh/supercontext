# Graph-Building Research — SuperContext Product 1

> **✅ RESOLVED — 2026-04-29.** The binding decision now lives in [`GRAPH-BUILDING-RECOMMENDATION.md`](./GRAPH-BUILDING-RECOMMENDATION.md) and [`../adr/0004-canonical-graph-plus-candidate-enrichment-sidecar.md`](../adr/0004-canonical-graph-plus-candidate-enrichment-sidecar.md). This document is preserved as a research input that supported the final decision; do not treat it as the final authority. The architecture is closed, but the exact canonical entity and relation vocabulary remains a follow-up research item.

- **Status:** Recommendation
- **Date:** 2026-04-28
- **Authors:** Roshan Singh, Maruti Agarwal
- **Anchors:** `PRD.md` §6.1 (engine + 5 ingestion sources), §6.2 (8 MCP tools), §7 (UX — provenance, refusal), `overall-architecture/adr/0001-claude-agent-sdk-for-internal-runtime.md`, `graph/claude-graph-storage-research.md` (storage), `agentic-layer/AGENTIC-LAYER-RECOMMENDATION-V2.md` (ingestion runtime is Claude Agent SDK)

---

## 1. TL;DR + the framing call

**Build a precise, typed knowledge graph. Do not build a GraphRAG-style noisy KG. This is load-bearing, not a stylistic preference.**

Every wedge query in PRD §6.2 — `blast_radius`, `find_callers`, `get_event_consumers`, `deploy_blockers_for` — is a deterministic graph traversal where a wrong-but-plausible answer is catastrophic: it gets merged and breaks service B in production. PRD §6.1 demands `commit_sha + file:line` (code) or `topic + schema_version + last_seen_at` (events) on every fact. That requirement is structurally incompatible with LLM-extracted-from-prose KGs, where the "source" is a paragraph and the "edge" is the model's interpretation. PRD §6.4's "refuse when uninstrumented" further requires us to know edge *absence*, which GraphRAG cannot represent — it returns the closest community summary, not "I don't know." The competitive seam against Multiplayer.app and Sourcegraph is correctness on cross-service edges; a noisy KG forfeits that seam in week one.

**Where GraphRAG fits — narrowly, Phase 2+, on prose surfaces only.** READMEs, ADRs, runbooks, incident postmortems, Confluence pages, Jira tickets are exactly the regime where an LLM extracting `{entity_mention → entity_mention}` triples with a paragraph-span citation beats a static parser. This is the entity-mention layer, *separate* from the typed service graph, joined by entity-resolution links. Onboarding-style Q&A ("what's the convention for retry logic?") and re-ranking traversal results are the legitimate use cases. Phase 2+, never Phase 1.

**The load-bearing pattern for Phase 1:** schema-guided structural extractors per source, plus Claude Agent SDK with strict structured outputs as a *gap-filler*, never as an LLM-extract-into-typed-schema step. Every typed edge in the graph for Phase 1 originates from a parser, not a prompt. The ingestion worker (ADR-0001) uses Glob/Grep/Read to drive deterministic extractors; LLM tool-use only enters when the structural extractor flags "I see this looks like an HTTP client call but I can't resolve the typed endpoint" — at which point the agent emits a *typed* upsert through a Claude strict-mode tool schema, with the file:line span as provenance, and a `confidence` property the graph stores explicitly.

---

## 2. Per-source recommendation

For each of the 5 PRD §6.1 ingestion sources, the concrete picks:

**1. Git repos (manifests, CODEOWNERS, IaC)**
- **Tree-sitter** (MIT, 305 pre-compiled parsers) for source-file and config-file parsing where YAML alone isn't enough.
- **Backstage community CodeOwnersProcessor** (`@backstage-community/plugin-catalog-backend-module-codeowners`) — battle-tested CODEOWNERS resolution for Owner edges. Wrap, don't rebuild. Original `CodeOwnersProcessor` is deprecated; use the community fork.
- **`js-yaml` / `PyYAML` + Pydantic schema** for `catalog-info.yaml`, manifests, etc. Typed parsing, no regex.

**2. API specs (OpenAPI, gRPC `.proto`, GraphQL SDL, AsyncAPI)**
- **Redocly CLI / `@redocly/openapi-core`** (MIT) — supports OpenAPI 3.2, 3.1, 3.0, Swagger 2.0, AsyncAPI 3.0/2.6, Arazzo 1.0. One library covers REST + AsyncAPI. Actively maintained 2025-2026.
- **`bufbuild/protocompile`** (Apache 2) — pure-Go protoc replacement; the linker stage resolves cross-message references natively. Equivalence-tested against protoc.
- **`graphql-js`** (MIT) for SDL parsing. Reference implementation, no alternatives needed.
- **`asyncapi/parser-js`** (Apache 2) — official AsyncAPI parser. Use Redocly as primary path; `parser-js` as fallback for edge cases since AsyncAPI's official parser does additional custom validations beyond JSON Schema.
- **Spectral** (Apache 2) for *custom extraction rules* via JSONPath — extract producer-side fields (which paths return what schema, which event types fan in), not just lint. Right tool, but write our own ruleset for extraction.

**3. Static call-site detection**
- **Sourcegraph SCIP indexers** for type-aware extraction when the language has one: `scip-typescript` (3-10× faster than lsif-node; covers TS+JS), `scip-java` (Java/Scala/Kotlin via compiler plugins), `scip-python` (built on Pyright), `scip-go`. All Apache 2. SCIP is now under open governance with a Core Steering Committee, reducing single-vendor risk. `scip-rust` is a rust-analyzer wrapper — fine, but doesn't add intelligence beyond rust-analyzer.
- **`github/stack-graphs`** (MIT/Apache) — file-incremental cross-file name resolution, powers GitHub's Precise Code Navigation in production. Use for languages not yet covered by SCIP and for incremental re-indexing on change.
- **Tree-sitter + ast-grep** (MIT) for typed-client call-site patterns (Retrofit, gRPC stubs, OpenAPI-generated SDKs). Rust, fast, dedicated MCP server, AST-driven not regex. **Pick ast-grep over Opengrep for pattern matching.**
- **Opengrep** (LGPL 2.1, forked Jan 2025 from Semgrep CE by Aikido + Endor + Jit + Orca) for taint-analysis-style rules where we need cross-function flow. **Avoid Semgrep** — license moved cross-function taint and other features behind commercial; LGPL is acceptable for distribution but Opengrep keeps the OSS feature set intact. Note Opengrep rules fork lags Dec 13, 2024 baseline of `semgrep-rules`.
- **Glean schemas** (BSD) — *steal the Angle schema definitions* (`codemarkup.angle` etc.) for code facts even though we won't run Glean itself. Per `graph/claude-graph-storage-research.md` §3, asking customers to operate Haskell/RocksDB is a non-starter; the schema borrow is the value.

**4. Kubernetes / Helm manifests**
- **`helm template` (subprocess) + `kustomize build`** to fully render manifests, then parse the rendered YAML with **`kubernetes-sigs/yaml`** (Go) or `pyyaml` + the **`kubernetes` Python client** typed models. There is no library that does "parse Helm chart and tell me what services it deploys" without rendering it — the rendering step is unavoidable. The PRD wedge claim of "ConfigMap-injected URLs (the declarative edge nobody mines)" requires the rendered output, not the chart source.
- **Skip `khelm` and other Kustomize/Helm meta-tools** for v1 — added complexity without payoff.

**5. Distributed tracing (OTel-compatible)**
- **OpenTelemetry Collector with `servicegraphconnector` and `spanmetricsconnector`** (Apache 2). Inspects parent-child span pairs using OTel semantic conventions and emits service-edge metrics with rate/error/latency. Run as a tail processor; emit typed edges with `last_seen_at`. **This is the primary path.**
- **Datadog Service Dependencies API** (public beta) — pulls precomputed APM service graph filtered by env. Use when customer is Datadog-only.
- **Tempo customers:** Tempo's `service_graphs` metrics-generator + `metrics-generator/service-graph-view`.
- **Jaeger customers:** Jaeger's dependency graph API.
- **Defer Pixie/Hubble/eBPF to Phase 3.** Cilium Hubble exposes a gRPC streaming API that's powerful, but per PRD §13 trace ingestion is "a multiplier, not a prerequisite" — we don't make eBPF a customer prerequisite for v1. PRD already deferred service mesh / eBPF ingestion to non-MVP.

---

## 3. Schema-guided extraction landscape

| Library | Lang | License | What it extracts | Verdict |
|---|---|---|---|---|
| Tree-sitter | C core, bindings everywhere | MIT | CSTs for 305 languages | **Use.** Substrate for everything else. |
| ast-grep | Rust | MIT | AST-pattern matches over tree-sitter | **Use.** Pattern engine; better DX than raw queries. |
| Stack Graphs | Rust | MIT/Apache | File-incremental cross-file name resolution | **Use.** Production-proven (GitHub). |
| SCIP indexers | Per-lang | Apache 2 | Compiler-precise references/definitions | **Use** for TS, JS, Java, Kotlin, Scala, Python, Go. |
| scip-rust | Rust | Apache 2 | Wrapper around rust-analyzer | Use, but expect only what rust-analyzer gives. |
| scip-clang | C++ | Apache 2 | Needs JSON compilation database | Use for C/C++ if customer ships `compile_commands.json`. |
| Opengrep | OCaml | LGPL 2.1 | Pattern + taint rules across 30+ langs | **Use** when cross-function taint flow needed. |
| Semgrep CE | OCaml | LGPL 2.1 (engine) + commercial (analyses) | Same as Opengrep, features paywalled | **Skip** — Opengrep is the community-clean fork. |
| Comby | OCaml | Apache 2 | Structural search/replace | Skip Phase 1 — not extraction-shaped. |
| Glean | Haskell | BSD | Code facts via Angle queries | **Steal schemas, don't run.** Operability is the disqualifier. |
| Redocly CLI | TS | MIT | OpenAPI/AsyncAPI/Arazzo parsing+lint | **Use** as the OpenAPI spine. |
| `@scalar/openapi-parser` | TS | MIT | OpenAPI 3.1/3.0/Swagger 2 with plugin refs | Strong alternative if Redocly has gaps. |
| `bufbuild/protocompile` | Go | Apache 2 | Pure-Go protoc replacement, linker resolves cross-msg refs | **Use.** |
| `graphql-js` | JS | MIT | GraphQL SDL parser | **Use.** No alternatives. |
| `asyncapi/parser-js` | JS | Apache 2 | AsyncAPI 2.x/3.x + Spectral validation | **Use** (or Redocly — pick one). |
| Spectral | TS | Apache 2 | JSONPath-driven rule engine over OpenAPI/AsyncAPI | **Use** for *extraction rules*, not just lint. |
| OTel Collector + servicegraphconnector | Go | Apache 2 | Service-edge metrics from spans | **Use** as primary trace path. |

---

## 4. The role of Claude Agent SDK + structured outputs

Per ADR-0001 (Layers A+B run on Claude Agent SDK), the ingestion worker emits typed graph upserts via **strict-mode tool use**. As of November 2025, Anthropic ships constrained decoding for Claude (`output_config.format` for JSON schema and `strict: true` on tool definitions). Per the Anthropic structured-outputs docs, the schema is compiled into a grammar that actively restricts token generation — the model literally cannot emit non-conforming tokens. This is true constrained generation, not retry-and-validate.

**Concrete pattern:**

1. **Define each edge type as a Pydantic model.** `Calls`, `Produces`, `Consumes`, `Owns`, `Gates`, `MigratesWith`, `SharesDbWith`, each with required `provenance: Provenance` (one of `CodeSpan{commit_sha, file_path, start_line, end_line}` or `EventTrace{topic, schema_version, last_seen_at, observed_at}`) and optional `confidence: float`.
2. **Expose each edge type as a strict-mode Claude tool** (`upsert_calls_edge`, `upsert_produces_edge`, etc.). Tool schemas are derived from the Pydantic models. The model can only emit valid edges — no provenance, no edge.
3. **The structural extractor runs first and emits high-confidence edges directly** via in-process MCP server tool calls. Claude Agent SDK doesn't ship a `@function_tool` decorator like OpenAI Agents SDK — wrap the upsert tools as an in-process MCP server.
4. **The agent only enters when the extractor flags "uninstrumented region."** Layer B's "agentic-fallback explorer" reads the relevant span (Glob/Grep/Read), reasons, and emits typed upserts with explicit `confidence < 1.0` and `source: "llm_inference"` provenance markers. The graph layer keeps these in a separate provenance class so consumers can filter.
5. **Use Instructor only as a fallback for non-Claude models.** Instructor is the right shape (Pydantic + retry), but with Claude's native strict mode shipping November 2025 it's redundant. Keep Instructor as the abstraction *if* we later support OpenAI Agents SDK per ADR-0001's swap clause.
6. **Skip Outlines for now.** Outlines does true constrained generation but requires logit-level access — only useful for self-hosted local models. Claude API delivers equivalent guarantees.

The discipline: every LLM-emitted edge carries the same provenance shape as a parser-emitted edge, plus a `confidence` and `source: "llm_inference"`. PRD §7's "refuse when unsafe" surfaces this directly: query results filter by source class.

---

## 5. GraphRAG — honest evaluation

**Microsoft GraphRAG** (MIT). Architecture: LLM extracts entities + relations via prompt → Leiden community clusters → community summaries → query-time map-reduce over summaries. Failure modes:
- **Cost.** Reported $33K indexing on large datasets pre-LazyGraphRAG; LazyGraphRAG (June 2025) cut this 99% but is still expensive at scale.
- **Provenance** is paragraph-level not span-level (`commit_sha + file:line` is not native).
- **Entity resolution** is an open issue and requires a separate ER step for accuracy.
- **Absence representation** does not exist (community summaries always return *something*).

Wrong tool for our typed service graph. Right tool for prose Q&A in Phase 2+.

**nano-graphrag** — lighter port, ~top-k community selection vs full map-reduce. Same architectural failures, smaller bill. Still wrong for Phase 1.

**fast-graphrag / Circlemind** — PageRank-based traversal, reportedly cheaper. Same shape. Worth tracking for Phase 2 prose layer.

**LangChain LLMGraphTransformer** — `allowed_nodes`, `allowed_relationships`, `strict_mode=True` defaults. *This is the closest existing library to "schema-constrained extraction."* The pattern is right; the implementation is light. **Use it as a reference, not a dependency** — wire the same idea to Claude strict tool use directly for fewer layers.

**LlamaIndex PropertyGraphIndex** — orchestrates a sequence of `kg_extractors` over chunks, hybrid retrieval (Cypher + vector). Heavier framework; Phase 2 prose-layer candidate; not Phase 1.

**REBEL** — BART seq2seq trained on 200 Wikipedia relation types. Wrong domain (knows "born_in" not "calls_endpoint"). Skip.

**GLiNER** — zero-shot NER, identifies any entity type without fine-tuning. Useful for Phase 2 incident/runbook ingestion ("which services are mentioned in this postmortem"). Not relevant to Phase 1.

**Triplex** — Phi-3 finetune for triplet extraction. Marketed as 98% cost reduction vs GPT-4. Same prose-extraction shape, smaller box. Phase 2 candidate.

**KG-Gen** (NeurIPS '25) — explicitly addresses the entity-resolution-and-sparsity problem in LLM KG extraction. Phase 2 candidate.

**Cognee** — agent-memory KG framework, vector + graph hybrid. Promiscuous scope. Skip — too much surface area.

**Diffbot** — commercial web KG. Skip.

**The mode of failure to internalize.** Every GraphRAG framework's claim of "30-40% reduction in factual errors" is measured against *baseline LLM generation on prose corpora*. None benchmark against a parser on structured input — the baseline is always weaker than what we get for free from `protocompile` or `tree-sitter`. Using GraphRAG on structured inputs is leaving precision on the table.

---

## 6. Build vs adopt matrix

| Sub-task | Approach |
|---|---|
| Git repo walk + manifest YAML | Use `kubernetes-sigs/yaml` + `pyyaml`. |
| CODEOWNERS resolution | Use Backstage community CodeOwnersProcessor. |
| Backstage `catalog-info.yaml` parsing | Use Backstage's own parser/types. |
| OpenAPI spec parsing | Use Redocly CLI; fall back to Scalar parser. |
| Custom OpenAPI extraction rules | Wrap Spectral with our own ruleset. |
| Protobuf parsing + linking | Use `bufbuild/protocompile`. |
| GraphQL SDL | Use `graphql-js`. |
| AsyncAPI | Use Redocly (or `asyncapi/parser-js`). |
| Tree-sitter parses for top-3 langs | Use tree-sitter directly. |
| Cross-file name resolution (TS, Java, Go, Python) | Use SCIP indexers. |
| Cross-file name resolution (others / fallback) | Use Stack Graphs. |
| Pattern-based call-site detection | Use ast-grep + custom rules. |
| Cross-function taint / flow rules | Use Opengrep + custom rules. |
| Helm/kustomize render | Subprocess `helm template` + `kustomize build`; parse output. |
| OTel trace → service edges | Use OTel Collector with servicegraphconnector. |
| Datadog APM ingestion | Wrap Datadog Service Dependencies API. |
| Tempo ingestion | Use Tempo metrics-generator service-graphs. |
| Jaeger ingestion | Use Jaeger query API + dependency endpoint. |
| LLM gap-fill | **Build ourselves** (Claude strict tool use). |
| Multi-source reconciliation | **Build ourselves.** No fit-for-purpose library. |
| Provenance attachment | **Build ourselves.** Pydantic models inside ingestion worker. |
| GraphRAG (Phase 2 prose) | LangChain `LLMGraphTransformer` or LlamaIndex PropertyGraphIndex; defer the choice. |
| Code-fact schema definitions | **Borrow from Glean** (`codemarkup.angle`); reimplement in our schema. |

---

## 7. Reconciliation / multi-source facts

The same `Service.calls.Endpoint` edge will be proven by static analysis (SCIP says service A's TypeScript types reference service B's OpenAPI client), by manifest analysis (k8s ConfigMap injects `B_BASE_URL` into A), and by trace analysis (10K spans last hour from A → B). These three pieces of evidence are not redundant — they are different kinds of evidence with different provenance and different lifetimes.

**No off-the-shelf library handles this for our shape.** Senzing-style entity resolution is for entity duplicates ("Microsoft" vs "MSFT"), not multi-source edge proofs. GraphRAG community summaries collapse evidence rather than preserve it. Datomic and XTDB v2 (covered in `graph/claude-graph-storage-research.md`) preserve bitemporal lineage but don't aggregate confidence.

**Recommendation: separate Fact rows per source, edge as a derived view.**

- Each ingestion worker writes a `Fact` row with `(predicate, subject_id, object_id, source_type, provenance_jsonb, observed_at, confidence)` to a `facts` table in Postgres.
- The graph edge in AGE (per the storage decision) is a *materialized view over facts*, with one edge per `(predicate, subject_id, object_id)` and aggregated metadata (`max(confidence)`, `array_agg(source_type)`, `min(observed_at)`, `max(last_seen_at)`).
- This gives us provenance per fact (PRD §7 satisfied), absence representation (no facts → no edge → "uninstrumented"), and reconciliation (multi-source confirmation surfaces as `len(sources) > 1`).
- Trade-off: writes are 2× (facts table + graph edge view refresh). Reads unaffected. Matches the storage doc's note that AGE has a known bulk-load gotcha — keep heavy writes in the facts table, refresh the AGE view as a batch.

The pattern is "facts as immutable append-only, edges as derived." Borrowed from Datalog-style designs (Datomic, XTDB v2, Glean) but implemented over Postgres, which the team already runs.

---

## 8. Open questions

1. **SCIP coverage gaps.** TS/JS/Java/Kotlin/Scala/Python/Go are clean. Ruby, PHP, C/C++, Rust, .NET, Dart all have indexers but with varying maturity. For the MVP top-3 (PRD §9) we are clean. Question: do design partners have meaningful Ruby/Python/C++ surface in mixed monorepos that we'll trip on?
2. **Stack Graphs vs SCIP overlap for top-3.** Stack Graphs is incremental; SCIP is full-rebuild. Hybrid (SCIP for fresh indexing, Stack Graphs for incremental update) is appealing but doubles the indexer surface. 1-week prototype to settle.
3. **Helm rendering performance at scale.** A 50-microservice repo can have 50+ Helm charts; rendering all of them on every commit is heavy. Cache by chart values hash? Needs a benchmark before commit.
4. **OTel servicegraphconnector accuracy at low traffic.** The connector uses parent-child span pairs; sparse-traffic services emit edges that look identical to "uninstrumented." When does an edge transition from "live" to "stale" to "uninstrumented"? PRD §7 says we refuse when uninstrumented — what's the threshold?
5. **Datadog Service Dependencies API rate limits.** Public beta. Pull cadence unknown. Production-grade ingestion needs rate limits known before promising SLAs to a Datadog-shop design partner.
6. **Confidence aggregation across sources.** Multi-source facts is the right pattern, but what's the actual aggregation rule? `max(confidence)`? `1 - prod(1 - c_i)` (independence)? Bayesian? Needs a sketch before code.
7. **Glean schema borrow legality.** BSD permits it. But the *language-specific Angle schemas* in Glean are tied to Meta's indexers. Is a "schema-only" borrow useful, or do we need their indexer logic too? An hour reading `codemarkup.angle` would settle.
8. **Phase 2 prose KG runtime separation.** Will the Phase 2 GraphRAG/PropertyGraphIndex layer share the same Postgres + AGE store, or sit in its own substrate? Mixing entity-mention edges with provenance-strict typed edges in one graph risks contamination of confidence; separate schema with explicit join edges suggested. Worth deciding before Phase 2 starts.

---

## 9. Sources

- [SCIP — Sourcegraph announcement](https://sourcegraph.com/blog/announcing-scip)
- [SCIP repo](https://github.com/sourcegraph/scip)
- [scip-typescript](https://github.com/sourcegraph/scip-typescript)
- [scip-typescript announcement](https://sourcegraph.com/blog/announcing-scip-typescript)
- [scip-python](https://github.com/sourcegraph/scip-python)
- [scip-python announcement](https://sourcegraph.com/blog/scip-python)
- [scip-go](https://github.com/sourcegraph/scip-go)
- [scip-clang](https://github.com/sourcegraph/scip-clang)
- [scip-rust](https://github.com/sourcegraph/scip-rust)
- [scip-dotnet](https://github.com/sourcegraph/scip-dotnet)
- [The future of SCIP — open governance](https://sourcegraph.com/blog/the-future-of-scip)
- [Sourcegraph Indexers reference](https://sourcegraph.com/docs/code-search/code-navigation/writing_an_indexer)
- [github/stack-graphs introduction](https://github.blog/open-source/introducing-stack-graphs/)
- [tree-sitter homepage](https://tree-sitter.github.io/tree-sitter/)
- [tree-sitter-language-pack on PyPI](https://pypi.org/project/tree-sitter-language-pack/)
- [ast-grep](https://github.com/ast-grep/ast-grep)
- [ast-grep MCP server](https://github.com/ast-grep/ast-grep-mcp)
- [Opengrep](https://github.com/opengrep/opengrep)
- [Opengrep rules fork](https://github.com/opengrep/opengrep-rules)
- [Opengrep launch — InfoQ](https://www.infoq.com/news/2025/02/semgrep-forked-opengrep/)
- [Semgrep Licensing page](https://semgrep.dev/docs/licensing)
- [Glean repo](https://github.com/facebookincubator/Glean)
- [Glean — Indexing code at scale at Meta](https://engineering.fb.com/2024/12/19/developer-tools/glean-open-source-code-indexing/)
- [Glean codemarkup.angle schema](https://github.com/facebookincubator/Glean/blob/main/glean/schema/source/codemarkup.angle)
- [Redocly CLI](https://github.com/Redocly/redocly-cli)
- [bufbuild/buf](https://github.com/bufbuild/buf)
- [bufbuild/protocompile](https://github.com/bufbuild/protocompile)
- [Buf Schema Registry docs](https://buf.build/docs/bsr/)
- [Confluent Schema Registry docs](https://docs.confluent.io/platform/current/schema-registry/index.html)
- [AsyncAPI parser-js](https://github.com/asyncapi/parser-js)
- [Spectral on GitHub](https://github.com/stoplightio/spectral)
- [Backstage CodeOwnersProcessor reference](https://backstage.io/api/next/classes/_backstage_plugin-catalog-backend.index.CodeOwnersProcessor.html)
- [Backstage descriptor format](https://backstage.io/docs/features/software-catalog/descriptor-format/)
- [OTel servicegraph connector README](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/main/connector/servicegraphconnector/README.md)
- [Tempo service graph view](https://grafana.com/docs/tempo/latest/metrics-generator/service-graph-view/)
- [Datadog Service Dependencies API](https://docs.datadoghq.com/api/latest/service-dependencies/)
- [Datadog Service Map docs](https://docs.datadoghq.com/tracing/services/services_map/)
- [Cilium Hubble docs](https://docs.cilium.io/en/stable/gettingstarted/hubble/)
- [Anthropic Structured Outputs docs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)
- [Claude Agent SDK structured outputs](https://platform.claude.com/docs/en/agent-sdk/structured-outputs)
- [Instructor library](https://github.com/567-labs/instructor)
- [Outlines library](https://github.com/dottxt-ai/outlines)
- [Microsoft GraphRAG project](https://www.microsoft.com/en-us/research/project/graphrag/)
- [Microsoft GraphRAG entity resolution issue](https://github.com/microsoft/graphrag/issues/847)
- [GraphRAG cost reduction analysis](https://medium.com/graph-praxis/cutting-graphrag-token-costs-by-90-in-production-5885b3ffaef0)
- [VeriTrail — Microsoft Research provenance/hallucination detector](https://www.microsoft.com/en-us/research/blog/veritrail-detecting-hallucination-and-tracing-provenance-in-multi-step-ai-workflows/)
- [nano-graphrag](https://github.com/gusye1234/nano-graphrag)
- [fast-graphrag (Circlemind)](https://github.com/circlemind-ai/fast-graphrag)
- [LangChain LLMGraphTransformer reference](https://python.langchain.com/api_reference/experimental/graph_transformers/langchain_experimental.graph_transformers.llm.LLMGraphTransformer.html)
- [LlamaIndex PropertyGraphIndex announcement](https://www.llamaindex.ai/blog/introducing-the-property-graph-index-a-powerful-new-way-to-build-knowledge-graphs-with-llms)
- [REBEL — Babelscape](https://github.com/Babelscape/rebel)
- [Triplex — SciPhi (HuggingFace)](https://huggingface.co/SciPhi/Triplex)
- [KG-Gen (NeurIPS '25)](https://github.com/stair-lab/kg-gen)
- [Cognee](https://github.com/topoteretes/cognee)
- [Stack graphs — Name resolution at scale (paper)](https://arxiv.org/pdf/2211.01224)

---

**Bottom line:** Phase 1 is parsers + Claude strict-mode tool use + multi-source Fact reconciliation. **Not GraphRAG.** GraphRAG is a Phase 2+ tool for prose surfaces (READMEs, ADRs, runbooks, incidents) where the source itself is unstructured. Mixing the two would contaminate the provenance contract that is the product's competitive seam.
