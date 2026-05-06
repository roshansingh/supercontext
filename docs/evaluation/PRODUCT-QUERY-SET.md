# Product Query Set

Status: v1 evaluation corpus  
Purpose: define realistic user questions before adding more KG features.

This is the acceptance input for evidence-driven development. Run these questions against the current system, record `pass`, `partial`, `fail`, or `refused correctly`, and use the gaps to choose the next implementation slice.

## Difficulty

| Level | Meaning |
|---|---|
| Low | Single repo or one indexed fact family; should be answerable with deterministic code/import/symbol facts and citations. |
| Medium | Multi-file, multi-service, or requires normalized imports, reverse traversal, ownership, contracts, coverage, or query-contract behavior. |
| Hard | Cross-repo/service graph, runtime traces, schema/event semantics, deploy ordering, freshness, refusal, pagination, or candidate enrichment. |

## Test Corpus Assumption

For local testing, use 3-6 repos that simulate one tenant:

- one API/service repo
- one downstream consumer repo
- one shared library/client repo
- one event producer/consumer repo
- one deployment/manifests repo
- optional test/fixtures repo with known broken, uninstrumented, candidate-only, alias, and multi-source corroboration cases

Fixture variables should be used in tests so Mercury-specific names do not become product assumptions:

| Variable | Mercury v0 value | Portable meaning |
|---|---|---|
| `$PY_REPO` | `mercury_ml` | A Python repo fixture. |
| `$ENTRY_SYMBOL` | `predict_on_session` | A function/method with several outgoing calls. |
| `$CALLER_SYMBOL` | `load_model` | An intentionally ambiguous symbol name. |
| `$INTERNAL_MODULE` | `mercury_ml.chatbot.apis.openai_instructor` | Internal module imported by multiple modules. |
| `$THIRD_PARTY_PACKAGE` | `openai` | External package dependency. |
| `$BROKEN_FILE` | `mercury_ml/tests/intent_based_predictions/feature_builder_test.py` | File that should produce uninstrumented/parse-failed coverage. |
| `$SERVICE` | `payments` or `checkout-service` | Service fixture in multi-repo tests. |
| `$ENDPOINT` | `POST /checkout/charge` | Endpoint fixture in API tests. |
| `$EVENT` | `orders.created` | Event topic/message fixture. |

## Grading Rubric

| Result | Definition |
|---|---|
| `pass` | Correct target resolution, correct facts, required citations/evidence present, expected refusal/coverage behavior satisfied, and no material false positives. |
| `partial` | Core target/facts are correct, but one required contract element is missing, such as citation, normalized category, pagination metadata, ambiguity metadata, or a bounded transitive hop. |
| `fail` | Wrong target, wrong facts, hidden guess on ambiguity, missing required refusal, missing evidence for surfaced claims, or materially misleading answer. |
| `refused correctly` | The system cannot safely answer because coverage is missing/stale/ambiguous/out-of-scope, and it explains the exact reason and scope. |

Partial examples:

- Correct entities but missing citations = `partial`.
- Correct citations but missing reverse traversal depth requested = `partial`.
- Correct direct callers but silently omits ambiguous same-name candidates = `fail`.
- Candidate-only fact appears in default canonical query = `fail`.
- Missing trace coverage is surfaced and bounded = `refused correctly` or `partial`, depending on whether a partial answer was requested.

## Standard Input Shapes

| Input kind | Required shape |
|---|---|
| Symbol query | `{repo, symbol_query, optional path, optional line, include_all=false}` |
| Coordinate query | `{repo, commit_sha, path, line_start, line_end}` |
| Service query | `{tenant_id, service_ref}` where `service_ref` can be slug, URN, or identity tuple. |
| Endpoint query | `{service_ref optional, protocol, method/path or grpc service/method or graphql field}` |
| Event query | `{broker_kind, channel/topic, optional message_name}` |
| PR query | `{provider, repo, pr_url, base_sha, head_sha, changed_files[], diff}`. PR URL alone is not enough for deterministic tests. |
| Time-window query | `{query, as_of optional, since optional, until optional}` |

## MCP Tool Mapping

| Tool | Covered by queries |
|---|---|
| `search_services` | Q011, Q031, Q045, Q047, Q055 |
| `get_service_brief` | Q015, Q031, Q047 |
| `find_callers` | Q003, Q013, Q016, Q020, Q021, Q033, Q036, Q051 |
| `find_callees` | Q004, Q026, Q045 |
| `get_event_consumers` | Q038, Q048 |
| `get_event_producers` | Q038 |
| `blast_radius` | Q016, Q021, Q022, Q034, Q037, Q040, Q042, Q048, Q053 |
| `deploy_blockers_for` | Q035, Q040, Q049 |
| Tool-contract / support behavior | Q006, Q007, Q008, Q009, Q010, Q012, Q014, Q017, Q018, Q019, Q023, Q024, Q025, Q027, Q028, Q029, Q030, Q032, Q039, Q041, Q043, Q044, Q046, Q050, Q052, Q054 |

## Low-Tier Golden Expectations

Low-tier queries must have concrete expected outputs for the active fixture. For Mercury v0, the initial goldens are:

| ID | Golden expectation for `$PY_REPO=mercury_ml` |
|---|---|
| Q001 | Includes `examples.clv.example-1` at `examples/clv/example-1.py:2`, `examples.clv.example-2` at `examples/clv/example-2.py:8`, and `mercury_ml.chatbot.frustration_classification.data_preparation` at `data_preparation.py:4` among `pandas` importers. |
| Q002 | Includes direct `openai` imports in chatbot specialist agents, for example `duplicate_agent.py:3`, `hallucination_detector.py:2`, and `handover_dspy_agent.py:4`; internal `openai_instructor` imports must not be counted as direct third-party `openai` imports after normalization. |
| Q003 | Returns ambiguity for `load_model`, including at least `HumanHandoverAgentDspy.load_model` and `FrustrationPredictor.load_model`, unless `include_all=true`. |
| Q004 | For `$ENTRY_SYMBOL=predict_on_session`, includes outgoing calls to `use_dumped_feature_builder`, `get_data`, `impute_data`, `build_features`, prediction methods, and `write_result_on_disk` with citations in `batch_predict.py:71-88`. |
| Q005 | For `batch_predict.py`, lists class/function symbols with line ranges, including `predict_intent.predict_on_session` starting at line 70. |
| Q006 | Includes `$BROKEN_FILE` with uninstrumented/parse-failed coverage at or around line 39. |
| Q007 | Returns evidence for `$ENTRY_SYMBOL -> build_features` at `mercury_ml/intent_based_predictions/batch_predict.py:77` with commit `c83cacf1df7fa37cc5dfc51916e02b8d8933eccc`. |
| Q008 | Classifies `os` as `stdlib`; it must not appear in default top third-party dependency results. |
| Q009 | Excludes stdlib packages such as `os`, `logging`, `json`, and `pickle`; includes third-party packages such as `pandas`, `openai`, `numpy`, and `sklearn`/`scikit-learn`. |
| Q010 | Returns `FeatureBuilder`/`build_features` candidates with fully qualified name, path, and line range; does not silently pick one if ambiguous. |
| Q011 | Service/repo identity includes repo `mercury_ml`, package name `la_mercury_ml`, service slug `la-mercury-ml`, and a human-readable service URN when URN support lands. |
| Q012 | Includes `sklearn.model_selection` imports in `frustration_classification/train.py:2` and `session_train_test_split.py:5`, mapped to distribution `scikit-learn` when alias mapping lands. |
| Q013 | Direct callers of `write_result_on_disk` include `predict_intent.predict_on_session` at `batch_predict.py:88`. |
| Q014 | For a default query over an `inferred_llm` `CALLS` fact with `canonical_status='candidate'`, default `find_callers` must not return the candidate fact; explicit candidate/enrichment mode may return it. |
| Q015 | Compact summary reports 225 Python files, 1266 entities, 3653 facts, 6567 evidence rows, and 2 coverage rows for the current v0 snapshot, or explains why counts changed after extractor changes. |

Goldens are fixture-specific. Regenerate them when the active test corpus or extractor behavior changes, and record the reason for the change.

## Query Table

| ID | Difficulty | Tool / surface | Persona | Fixture | User question | Expected answer shape | Main capabilities exercised |
|---|---|---|---|---|---|---|---|
| Q001 | Low | Support / CLI | Engineer | `$PY_REPO`, `$PACKAGE=pandas` | What modules import `$PACKAGE`? | Importer modules with file/line citations; stdlib excluded. | Import extraction, normalization, evidence. |
| Q002 | Low | Support / CLI | Engineer | `$PY_REPO`, `$THIRD_PARTY_PACKAGE` | What modules import `$THIRD_PARTY_PACKAGE` directly? | Direct third-party importers only; internal similarly named modules separated. | Third-party vs internal import classification. |
| Q003 | Low | `find_callers` / CLI | Engineer | `$PY_REPO`, `$CALLER_SYMBOL` | Who calls `$CALLER_SYMBOL`? | Ambiguity response or callers with citations if resolved/include_all. | Symbol lookup, ambiguity handling, reverse `CALLS`. |
| Q004 | Low | `find_callees` / CLI | Engineer | `$PY_REPO`, `$ENTRY_SYMBOL` | What does `$ENTRY_SYMBOL` call directly? | Direct outgoing callees with file/line evidence. | Symbol lookup, outgoing call traversal. |
| Q005 | Low | Support / CLI | Engineer | `$PY_REPO`, `batch_predict.py` | Which symbols are defined in this file? | Functions/classes/methods with line ranges. | Symbol index, coordinate evidence. |
| Q006 | Low | Support / CLI | Engineer | `$BROKEN_FILE` | Which files could not be parsed or indexed? | Coverage rows with path, reason, extractor, and state. | Coverage, refusal metadata. |
| Q007 | Low | Support / CLI | Engineer | `$ENTRY_SYMBOL -> build_features` | Show the evidence for this call edge. | Exact citation plus source snippet from commit-pinned bytes. | Evidence lookup, Mode A coordinate fetch input. |
| Q008 | Low | Support / CLI | Engineer | `$PY_REPO`, `os` | Is `os` third-party or standard library usage? | `stdlib` classification with down-rank note. | Import normalization, stdlib map. |
| Q009 | Low | Support / CLI | Engineer | `$PY_REPO` | What are the top third-party dependencies by importer count? | Ranked packages excluding stdlib with counts and sample citations. | Import aggregation. |
| Q010 | Low | Support / CLI | Engineer | `$PY_REPO`, `FeatureBuilder` | Find all symbols matching this name. | Exact/fuzzy candidates with module/path/line and ambiguity metadata. | Symbol lookup, fuzzy ranking. |
| Q011 | Low | `search_services` / CLI | Engineer | `$PY_REPO` | What service identity and URN did this repo produce? | Service identity tuple, slug, URN, repo evidence. | Service identity, URN contract. |
| Q012 | Low | Support / CLI | Engineer | `$PY_REPO`, `sklearn` | Which modules import `sklearn`? | Importers mapped to `scikit-learn` distribution when known. | Import alias mapping, evidence. |
| Q013 | Low | `find_callers` / CLI | Engineer | `$PY_REPO`, `write_result_on_disk` | What are the direct callers of this symbol? | Caller symbols with citations. | Reverse call traversal. |
| Q014 | Low | `find_callers` / CLI | Engineer | Candidate fixture | Does a candidate-only `inferred_llm` `CALLS` edge appear in default `find_callers`? | Expected: no; only explicit candidate/enrichment mode may show it. | Candidate vs canonical guardrail. |
| Q015 | Low | `get_service_brief` / CLI | New hire | `$PY_REPO` | Give me a compact summary of this repo's KG. | Counts, top dependencies, parse gaps, evidence coverage summary. | KG inventory, compact output. |
| Q016 | Medium | `blast_radius` / IDE | Engineer | `$PY_REPO`, `build_features` | If I change this symbol, what symbols may be affected? | Reverse callers and bounded transitive callers with evidence paths. | `impact-of-symbol`, reverse traversal. |
| Q017 | Medium | Support / IDE | Engineer | `$INTERNAL_MODULE` | If I change this internal module, which modules import it? | Importers grouped by module/package area with citations. | Internal import normalization, `who-imports`. |
| Q018 | Medium | Support / IDE | Engineer | `$THIRD_PARTY_PACKAGE=openai` | Which code paths use OpenAI APIs indirectly through internal wrappers? | Internal wrapper modules plus importers/callers of wrappers. | Imports + calls merge. |
| Q019 | Medium | Support / IDE | Engineer | `FeatureBuilder` | Which files should I inspect before refactoring this symbol? | Defining file, direct callers, importers, nearby tests if indexed. | Symbol lookup, reverse traversal, lexical evidence. |
| Q020 | Medium | `find_callers` / IDE | Engineer | `$CALLER_SYMBOL` | Is this symbol ambiguous? If yes, show all candidates. | Candidate list with fully-qualified names and line ranges. | Ambiguity response. |
| Q021 | Medium | `blast_radius` / PR bot | Engineer | PR input shape | This PR changes `batch_predict.py`; what functions did it touch and who calls them? | Changed symbols, reverse callers, evidence per changed line. | PR diff, coordinate-to-symbol, reverse calls. |
| Q022 | Medium | `blast_radius` / PR bot | Engineer | PR input shape | This PR changes an internal helper module; who imports it? | Importers with citations and stdlib/third-party excluded. | PR diff, coordinate-to-module, reverse imports. |
| Q023 | Medium | Support / CLI | Engineer | `$PY_REPO` | Which modules combine `pandas` and `sklearn` usage? | Modules importing both dependency families with citations. | Normalized import intersections. |
| Q024 | Medium | Support / CLI | Tech lead | `$PY_REPO` | Which functions call external package APIs most heavily? | Ranked caller symbols by external package call edges. | Calls + import classification aggregation. |
| Q025 | Medium | Support / CLI | Tech lead | `$PY_REPO` | Which internal modules are most depended on? | Ranked internal modules by importer count. | Internal import graph, reverse imports. |
| Q026 | Medium | `find_callees` / CLI | Engineer | `$ENTRY_SYMBOL`, `sklearn` | What dependency path connects this symbol to `sklearn`, if any? | Path through calls/imports, or not_found/refusal. | Path search, calls + imports merge. |
| Q027 | Medium | Support / IDE | Engineer | `$PACKAGE=pandas` | If I remove this dependency, which files break first? | Direct importers and likely call sites with citations. | Third-party dependency impact. |
| Q028 | Medium | Support / IDE | Engineer | `build_features` | Which tests mention or call this symbol? | Test files/symbols with evidence; warn on uninstrumented test coverage. | Symbol lookup, lexical retrieval, coverage. |
| Q029 | Medium | Support / CLI | SRE | Tenant/repo coverage | Show stale or uninstrumented areas in the repo graph. | Coverage gaps grouped by reason/source/scope. | Coverage table, freshness/refusal. |
| Q030 | Medium | Support / CLI | Tech lead | `$PY_REPO` | What are the top 10 risky functions by fan-in? | Functions with highest caller count and citations. | Reverse call aggregation. |
| Q031 | Medium | `search_services` / IDE | Engineer | catalog fixture | Which service owns this repo and who owns that service? | Service and owner with source provenance. | Service identity, ownership facts. |
| Q032 | Medium | Support / IDE | Engineer | API repo fixture | What endpoints does `$SERVICE` expose? | Endpoint list, method/path/schema, evidence. | OpenAPI/gRPC/GraphQL extraction. |
| Q033 | Medium | `find_callers` / IDE | Engineer | Few repos, `$ENDPOINT` | What services call `$ENDPOINT`? | Callers by service/repo, static/runtime evidence. | Endpoint identity, static call-site extraction. |
| Q034 | Medium | `blast_radius` / PR bot | Engineer | PR input shape | This PR changes an endpoint response schema; who consumes it? | Consumer services, parser strictness if known, evidence. | Schema diff, endpoint consumers. |
| Q035 | Medium | `deploy_blockers_for` / CLI | Platform | manifest fixture | Which Kubernetes deployable runs `$SERVICE`? | Deployable/environment mapping with manifest citation. | k8s/Helm extraction, service identity. |
| Q036 | Hard | `find_callers` / IDE | Engineer | cross-repo schema fixture | If I remove field `discount_code`, which services will fail deserialization? | Consumers, strictness, schema evidence, refusal/deprecation path. | Schema field lineage, consumer parsing. |
| Q037 | Hard | `blast_radius` / PR bot | Engineer | PR input shape | Given this PR, compute blast radius across services, schemas, deploys, and owners. | Affected services/contracts/deployables/owners with confidence/refusal metadata. | Diff parsing, graph traversal. |
| Q038 | Hard | `get_event_consumers`, `get_event_producers` / CLI | Platform | `$EVENT`, runtime window | Can we delete this event topic? Prove zero consumers in 30 days. | Producers/consumers, last_seen_at, coverage; refusal if traces missing. | Event graph, runtime freshness, refusal. |
| Q039 | Hard | Support / oncall | SRE | runtime + deploy fixture | p99 spiked in `$SERVICE`; what new upstream edges or deploys appeared in the last hour? | Changed call edges, upstream deploys, freshness windows, citations. | Temporal graph diff, traces, deploy topology. |
| Q040 | Hard | `deploy_blockers_for` / IDE | Engineer | multi-service schema fixture | What must deploy before `$SERVICE` can safely deploy this schema change? | Deploy blockers and ordering with reasons/evidence. | Deploy blockers, schema consumers. |
| Q041 | Hard | Support / migration | Platform | cross-repo auth fixture | We are migrating auth v1 to v2; which repos/services need code changes? | Impacted services, call sites, owners, migration status. | Cross-repo search, ownership, candidate enrichment. |
| Q042 | Hard | `blast_radius` / PR bot | Security | PR input shape | This PR changes auth middleware; which public endpoints and downstream services are affected? | Endpoints, callers, owners, deployables, evidence. | Symbol-to-endpoint, reverse calls, service graph. |
| Q043 | Hard | Support / planning | Tech lead / EM | `$ENDPOINT` | Produce an impact memo for deprecating this endpoint. | Affected consumers, owners, traffic, schema versions, rollout inputs. | Service graph, runtime traffic, ownership, summarization. |
| Q044 | Hard | Support / IDE | Engineer | schema fixture | Which services share this schema version, and which can move independently? | Shared schemas, consumers/producers, compatibility notes. | Schema identity, `USES_SCHEMA`, `EVOLVES_TO`. |
| Q045 | Hard | `find_callees`, `search_services` / CLI | Platform | cross-service fixture | Which services depend on `$SERVICE` directly and indirectly up to depth 3? | Direct/transitive dependencies, edge type, evidence, depth. | Graph traversal, pagination, evidence. |
| Q046 | Hard | Support / oncall | SRE | runtime + time window | What changed in the service graph between 2 hours ago and now for checkout flow? | Added/removed/stale edges, deploys, confidence/refusals. | Bitemporal/freshness, runtime observed edges. |
| Q047 | Hard | `get_service_brief`, `search_services` / IDE | New hire | service fixture | Give me the 5 most important upstream deps and 3 noisiest downstream consumers for this service. | Ranked neighbors by traffic/fan-in/freshness with citations. | Service brief, ranking, runtime/static merge. |
| Q048 | Hard | `blast_radius`, `get_event_consumers` / PR bot | Engineer | PR input + coverage gap | This contract PR has no trace coverage for one consumer. What can we safely say and where must we refuse? | Partial answer plus explicit uninstrumented scope. | Coverage-aware refusal, graph/evidence merge. |
| Q049 | Hard | `deploy_blockers_for` / migration | Platform / EM | cross-repo ownership fixture | Generate the ordered list of teams to coordinate for a breaking schema migration. | Owners, services, dependency order, unknowns/refusals. | Ownership, schema consumers, deployment order. |
| Q050 | Hard | Support / platform | Platform | 5-repo tenant | Across 5 repos, which source systems are missing enough coverage that answers may be unsafe? | Coverage dashboard by source/repo/fact type and recommended next ingestion. | Coverage-update pipeline, observability, refusal policy. |
| Q051 | Medium | `find_callers` / CLI | Platform | Promotion fixture | A candidate `CALLS` fact gains a second qualifying static/runtime source; does it become visible in default caller queries? | Before second source: hidden by default; after second source: `canonical_status='canonical'`, `sources_count>=2`, default `find_callers` returns it with both evidence rows. | Promotion rules, candidate-to-canonical transition, multi-source corroboration. |
| Q052 | Medium | Support / CLI | Security | schema/API fixture | Which services or endpoints read, write, or return PII fields such as `email`, `phone`, or `ssn`? | Services/endpoints/schemas grouped by PII field with evidence; refuse or mark unknown when schema/source coverage is missing. | Schema field lineage, endpoint evidence, coverage-aware refusal. |
| Q053 | Hard | `blast_radius` / IDE | Security | authz fixture | Which public endpoints can reach privileged actions, and where is the authorization check proven? | Endpoint-to-handler-to-authz paths with citations; candidate gaps separated from canonical facts; explicit refusal for unindexed frameworks. | Authz path tracing, symbol-to-endpoint, candidate separation. |
| Q054 | Medium | Support / CLI | Security | any repo | Is this code secure? | Refuse as too broad and out of product scope; suggest narrower supported questions such as authz path checks, PII lineage, dependency usage, or endpoint blast radius. | Product-scope refusal, safe narrowing. |
| Q055 | Medium | `search_services` / CLI | Platform | alias fixture | Do `payments-svc`, `payments`, catalog ID, k8s app label, and OTel service name collapse to the same service? | One canonical service only when Alias/identity evidence supports it; otherwise separate entities with conflict explanation. | Identity tuple merge, Alias table behavior, provenance. |

## Additional Contract Checks

These are not separate numbered user queries, but they must be checked while executing the table:

| Contract | Covered by | Expected behavior |
|---|---|---|
| Candidate facts hidden by default | Q014 | `canonical_status='candidate'` and `derivation_class='inferred_llm'` facts do not appear in default operational tools. |
| Promotion transition | Q051 | Candidate facts promote to canonical only when ADR-0006 promotion rules are satisfied; default tools show the fact after promotion, not before. |
| Identity tuple merge | Q011, Q031, Q055 | Same service observed through catalog, k8s, and traces collapses to one canonical entity when identity tuple matches. |
| Alias merge | Q011, Q031, Q055 | Alias `payments-svc -> payments` resolves only when explicit Alias evidence exists; otherwise separate entities. |
| URN format | Q011 | Service URN should be human-readable, e.g. `supercontext://service/default/payments`; v0 opaque URNs are a known gap. |
| Derivation class | Q007, Q033, Q038 | Returned facts expose `derivation_class`; filters like deterministic-only must be supported by Tool Query Contract. |
| Mode A byte round-trip | Q007 | Given `repo + commit_sha + path + line`, coordinate fetch returns the exact bytes or refuses; never silently falls back to `HEAD`. |
| Multi-source corroboration | Q033, Q038, Q051 | Facts with static + runtime evidence expose `sources_count >= 2` and show both evidence rows. |
| Pagination and depth limits | Q045, Q047 | Default depth is 1; large neighborhoods paginate with cursor metadata and summary-first behavior. |
| Negative/out-of-scope refusal | Q014, Q048, Q050, Q054 | Unsafe, uninstrumented, ambiguous, or out-of-scope questions refuse explicitly instead of guessing. |

## How To Use

1. Start with Low queries and record `pass`, `partial`, `fail`, or `refused correctly`.
2. For Low queries, compare against the golden expectation table before using judgment.
3. Do not implement speculative features until a query fails for a concrete reason.
4. Promote repeated failures into focused implementation tasks.
5. Add fixtures/repos only when a query cannot be tested honestly with the current corpus.
