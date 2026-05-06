# DeepWiki OSS Analysis for SuperContext

Status: research note  
Date: 2026-05-01  
Scope: evaluate DeepWiki-like OSS projects for ideas SuperContext can borrow.

## Executive Verdict

DeepWiki is adjacent, not equivalent.

The open-source DeepWiki projects are primarily **repo-to-wiki + RAG/chat systems**. They help humans and agents understand a repository by generating documentation, diagrams, and conversational answers. SuperContext is building a **provenance-first operational service graph** for cross-service change safety.

We should borrow selected implementation patterns, but not use DeepWiki as the core runtime.

## Projects Inspected

| Project | Repo | License | Stack | Fit for SuperContext |
|---|---|---|---|---|
| DeepWiki-Open | `AsyncFuncAI/deepwiki-open` | MIT | Python FastAPI, Next.js, AdalFlow, FAISS, embeddings, Mermaid | Useful reference for wiki UX, generated docs, source-file citations, multi-provider config |
| OpenDeepWiki | `AIDotNet/OpenDeepWiki` | MIT | .NET, Semantic Kernel / Microsoft Agents, EF Core, SQLite/Postgres, MCP | Better reference for background processing, repo state, MCP tools, incremental updates |

Inspected commits:

- `AsyncFuncAI/deepwiki-open`: `5b43df5`
- `AIDotNet/OpenDeepWiki`: `e104940`

## What DeepWiki Actually Does

### DeepWiki-Open

DeepWiki-Open advertises repo analysis, documentation generation, Mermaid diagrams, RAG-powered chat, DeepResearch, multiple model providers, and flexible embeddings. Its documented flow is: clone repo, create embeddings, generate docs, create diagrams, organize wiki, then answer questions. Sources: `README.md:5-10`, `README.md:19-29`, `README.md:116-126`.

Implementation shape:

- Clones GitHub/GitLab/Bitbucket repos with `git clone --depth=1 --single-branch`. Source: `api/data_pipeline.py:72-130`.
- Reads code/docs by extension and builds `Document` objects with `file_path`, type, and token metadata. Source: `api/data_pipeline.py:260-430`.
- Stores transformed chunks in AdalFlow `LocalDB` under `~/.adalflow/databases/*.pkl`. Source: `api/data_pipeline.py:785-900`.
- Uses embeddings + FAISS for retrieval. Source: `api/rag.py:251-413`.
- Generates wiki page content from a frontend prompt that requires relevant source files, Mermaid diagrams, and source citations. Source: `src/app/[owner]/[repo]/page.tsx:419-504`.
- Caches generated wiki structures as JSON files under `~/.adalflow/wikicache`. Source: `api/api.py:405-504`.

### OpenDeepWiki

OpenDeepWiki is more platform-shaped. It supports repository CRUD, multiple databases, MCP, background workers, incremental updates, and user/admin features. Sources: `README.md:32-60`, `README.md:64-113`, `README.md:183-190`.

Implementation shape:

- Represents repositories, branches, language variants, generated doc catalogs, and doc files in EF Core. Source: `OpenDeepWiki.EFCore/MasterDbContext.cs:9-49`, `MasterDbContext.cs:116-140`.
- Uses `LibGit2Sharp` to clone/pull repos, record HEAD commit, and compute changed files between commits. Source: `RepositoryAnalyzer.cs:71-150`, `RepositoryAnalyzer.cs:198-240`, `RepositoryAnalyzer.cs:690-765`.
- Runs a background worker that processes pending repositories and records status/logs. Source: `RepositoryProcessingWorker.cs:1-160`.
- Runs incremental update checks and regenerates docs when commits change. Source: `IncrementalUpdateService.cs:64-230`.
- Exposes MCP tools for `SearchDoc`, `GetRepoStructure`, and `ReadFile`. Source: `McpRepositoryTools.cs:17-249`.
- Tracks generated document source files by recording files read through the Git tool. Source: `DocTool.cs:76-110`, `DocFile.cs:23-27`.

## What We Should Borrow

1. **Repository workspace abstraction**
   Borrow the OpenDeepWiki pattern of `RepositoryWorkspace`: org/repo/branch/current commit/previous commit/working directory/source type. We need the same concept for Layer A ingestion and evidence retrieval.

2. **Commit-delta processing**
   OpenDeepWiki already separates initial processing from incremental updates by comparing previous and current commit IDs. This maps directly to our coverage/freshness and extractor scheduling needs.

3. **Processing state + logs**
   `Pending`, `Processing`, `Completed`, `Failed` plus per-step logs are useful for enterprise debugging. We should add this to the ingestion/control plane ADR.

4. **Source-file provenance for generated docs**
   OpenDeepWiki records `SourceFiles` for generated docs and instructs assistants to verify docs against source files. This is weaker than our fact evidence model, but useful for candidate/enrichment docs.

5. **Generated wiki/mindmap as candidate sidecar content**
   DeepWiki-style documentation should live in our candidate/enrichment sidecar, not the canonical graph. It can power `get_service_brief`, onboarding, and human-readable explanations.

6. **MCP scoping pattern**
   OpenDeepWiki scopes MCP calls to a repository via the MCP endpoint/session context. Our equivalent should scope by tenant, repo/service, and tool contract.

7. **Simple code-reading tools**
   OpenDeepWiki's `ReadFile`, `ListFiles`, and `Grep`-style tools are useful references for bounded agent tools, especially path normalization, line-numbered reads, and max-result limits.

8. **Mermaid rendering and diagram UX**
   DeepWiki's wiki UI and Mermaid-heavy docs are useful for admin/debug surfaces and generated architecture explanations.

9. **Model/provider config separation**
   Both projects separate model/provider settings from application logic. Useful for self-hosted deployments, but not core to the Product 1 architecture.

## What We Should Not Borrow

1. **Do not make embeddings-first retrieval core**
   DeepWiki-Open relies on chunk embeddings + FAISS for repo Q&A. ADR-0005 explicitly chooses coordinate fetch + lexical/targeted structural search first, with agentic exploration budgeted.

2. **Do not treat generated wiki docs as canonical facts**
   DeepWiki pages are LLM-generated summaries. They can be candidate/enrichment artifacts only. Canonical `CALLS`, `PRODUCES`, `CONSUMES`, `DEPENDS_ON`, etc. must come from deterministic/authoritative/runtime evidence per ADR-0006.

3. **Do not reuse DeepWiki's storage model for the graph**
   JSON wiki cache, local pickle DB, or doc catalog tables are not substitutes for our Entity + Fact + Evidence + Coverage tables and AGE projection.

4. **Do not adopt broad "all languages" claims**
   Both projects are language-agnostic because they mostly read text and ask LLMs to summarize. Our v1 precision depends on selected extractors and evidence contracts, not broad language promises.

5. **Do not copy token/credential handling**
   DeepWiki-Open injects PATs into clone URLs, though it tries to sanitize errors. OpenDeepWiki's repository entity has `AuthPassword` with a comment saying plaintext storage. These are not acceptable defaults for our enterprise/security posture.

6. **Do not use AI-generated diagrams as graph truth**
   Mermaid diagrams are useful explanations. They are not evidence, not AGE projection input, and not canonical relations.

## Mapping to SuperContext ADRs

| SuperContext area | DeepWiki lesson | Action |
|---|---|---|
| ADR-0001 internal runtime | Agent tools over local repo files are useful, but must stay allowlisted and read-mostly. | Keep Claude Agent SDK; borrow bounded tool patterns only. |
| ADR-0003 storage | DeepWiki persistent DB is app/document state, not graph storage. | No change to Postgres + AGE. |
| ADR-0004 sidecar | Generated docs/mindmaps are good candidate/enrichment artifacts. | Add to sidecar backlog, not canonical graph. |
| ADR-0005 evidence retrieval | Source-file backlinks and line-numbered reads support grounding. | Borrow source-file tracking and path-safe read/list/grep patterns. |
| ADR-0006 ontology | DeepWiki does not define an operational service ontology. | No ontology changes. |
| Tool Query Contract ADR | DeepWiki shows that answers should cite docs and source files, and fall back to source verification. | Include source-verification behavior in tool response/refusal contract. |
| Source Connector + Extractor ADR | Workspace/commit-delta design should drive extractor scheduling. | Borrow workspace + changed-files pattern. |

## Concrete Borrow Candidates

### High Value

- `RepositoryWorkspace` model: tenant, repo, branch/ref, current commit, previous commit, working directory, source type.
- `ChangedFilesProvider`: compute full file set on first index and changed file set after previous commit.
- `IngestionProcessingLog`: per-repo/per-source/per-extractor status and error log.
- `SourceFiles` metadata for candidate docs and generated service briefs.
- MCP/session scoping pattern, adapted to tenant + service/repo context.

### Medium Value

- Wiki tree UI for human-readable service/repo briefs.
- Mermaid renderer for admin/debug docs.
- Prompt pattern requiring generated docs to begin with relevant source files.
- Multi-provider model configuration for self-hosted customers.

### Low Value / Later

- DeepResearch-style multi-turn investigation for exploratory docs.
- Generated workshops/slides.
- SEO/wiki publishing features.

## Gaps DeepWiki Does Not Solve

- No canonical typed service graph.
- No operational ontology for services/endpoints/events/deployments/owners.
- No graph projection equivalent to AGE.
- No strict per-fact provenance envelope.
- No coverage sidecar with known-empty/unknown/stale/partial semantics.
- No source-controlled coordinate fetch guarantee for every surfaced code fact.
- No runtime trace ingestion or service dependency truth.
- No PR blast-radius semantics.
- No deploy blocker model.

## Recommended Architecture Impact

No ADR should change because of DeepWiki.

The useful impact is on upcoming implementation ADRs:

1. **Tool Query Contract ADR**
   Add a rule that generated explanatory text must distinguish canonical facts, candidate/enrichment summaries, and source-file evidence.

2. **Source Connector + Extractor ADR**
   Include a `RepositoryWorkspace` + changed-files abstraction inspired by OpenDeepWiki, but backed by our `go-git` / `pygit2` decision from ADR-0005.

3. **Graph Building ADR**
   Treat generated docs/mindmaps as candidate/enrichment outputs. They may summarize canonical facts but cannot create canonical edges without promotion evidence.

4. **Observability / Operations ADR**
   Add processing states, per-step logs, retry tracking, and token/tool usage metrics.

## Final Recommendation

Use DeepWiki as a reference for **human-facing repository understanding**, not as the core product substrate.

Borrow:

- repo workspace + commit-delta processing
- processing logs/statuses
- source-file backlinks for generated docs
- MCP-scoped repository tools
- Mermaid/wiki UX for explainability

Reject:

- embeddings-first core retrieval
- LLM-generated graph truth
- local pickle/JSON cache as product storage
- broad language precision claims
- insecure credential patterns

DeepWiki is useful for the candidate/enrichment sidecar and human docs. SuperContext's differentiator remains the canonical operational graph plus evidence/refusal contract.

## Sources

- `AsyncFuncAI/deepwiki-open`: https://github.com/AsyncFuncAI/deepwiki-open
- `AIDotNet/OpenDeepWiki`: https://github.com/AIDotNet/OpenDeepWiki
- Local clone inspected at `AsyncFuncAI/deepwiki-open@5b43df5`.
- Local clone inspected at `AIDotNet/OpenDeepWiki@e104940`.
