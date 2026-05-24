# SuperContext vs grep Evaluation Report

**Generated:** 2026-05-24T12:04:42.278881+00:00
**Target:** github/CodeSearchNet (25 queries)

## Summary

| Metric | Value |
|--------|-------|
| SuperContext wins | 23 |
| grep wins | 0 |
| Ties | 2 |
| SuperContext win rate | 92.0% |
| Avg latency (SC) | 141.1ms |
| Avg latency (grep) | 12.1ms |

## Results by Category

| Category | SC wins | grep wins | Ties |
|----------|---------|-----------|------|
| dependency | 6 | 0 | 0 |
| call_graph | 7 | 0 | 0 |
| symbol | 5 | 0 | 0 |
| blast_radius | 2 | 0 | 1 |
| structural | 3 | 0 | 1 |

## Per-Query Results

| ID | Query | SC results | grep results | Winner | Reason |
|----|-------|-----------|-------------|--------|--------|
| DEP-01 | modules-importing tensorflow | 13 | 12 | supercontext | Richer metadata (evidence, structure) for same coverage |
| DEP-02 | modules-importing wandb | 5 | 4 | supercontext | Richer metadata (evidence, structure) for same coverage |
| DEP-03 | modules-importing numpy | 8 | 8 | supercontext | Richer metadata (evidence, structure) for same coverage |
| DEP-04 | modules-importing docopt | 14 | 14 | supercontext | Richer metadata (evidence, structure) for same coverage |
| DEP-05 | top-dependencies | 1 | 55 | supercontext | Richer metadata (evidence, structure) for same coverage |
| DEP-06 | top-internal-dependencies | 6 | 0 | supercontext | SuperContext found results, grep found none |
| CALL-01 | find-callers get_shape_list | 7 | 1 | supercontext | Qualified names + evidence vs flat file matches |
| CALL-02 | find-callers create_initializer | 5 | 1 | supercontext | Qualified names + evidence vs flat file matches |
| CALL-03 | find-callers dropout | 3 | 7 | supercontext | Qualified names + evidence vs flat file matches |
| CALL-04 | find-callers train_log | 3 | 2 | supercontext | Qualified names + evidence vs flat file matches |
| CALL-05 | find-callees Model.train | 6 | 18 | supercontext | Qualified names + evidence vs flat file matches |
| CALL-06 | find-callees Model.make_model | 4 | 9 | supercontext | Qualified names + evidence vs flat file matches |
| CALL-07 | top-fan-in-symbols | 93 | 0 | supercontext | Call graph analysis not possible with grep |
| SYM-01 | symbols-in-file src/models/model.py | 37 | 42 | supercontext | Qualified names + evidence vs flat file matches |
| SYM-02 | symbols-in-file src/encoders/seq_encoder.py | 12 | 12 | supercontext | Qualified names + evidence vs flat file matches |
| SYM-03 | lookup-symbol Model | 0 | 1 | supercontext | Qualified names + evidence vs flat file matches |
| SYM-04 | lookup-symbol SeqEncoder | 0 | 1 | supercontext | Qualified names + evidence vs flat file matches |
| SYM-05 | lookup-symbol NeuralBoWModel | 0 | 1 | supercontext | Qualified names + evidence vs flat file matches |
| BLAST-01 | blast-radius get_shape_list --depth 2 | 1 | 1 | supercontext | Transitive closure vs string match |
| BLAST-02 | blast-radius Model.train --depth 2 | 11 | 18 | supercontext | Transitive closure vs string match |
| BLAST-03 | blast-radius SeqEncoder --depth 2 --include-all | 0 | 9 | tie | Neither found results |
| STRUCT-01 | summary | 463 | 60 | tie | Similar coverage |
| STRUCT-02 | who-imports src.models.model | 3 | 0 | supercontext | Qualified names + evidence vs flat file matches |
| STRUCT-03 | who-imports src.encoders.seq_encoder | 2 | 0 | supercontext | Qualified names + evidence vs flat file matches |
| STRUCT-04 | dependency-path Model.train get_shape_list | 0 | 0 | supercontext | Graph traversal not possible with grep |

## CodeSearchNet Dataset

| Metric | Value |
|--------|-------|
| Total annotations | 4006 |
| Python annotations | 2079 |
| Unique Python queries | 99 |
| Languages | Go, Java, JavaScript, PHP, Python, Ruby |
