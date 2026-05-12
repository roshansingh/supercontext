# Goldset Judgement

- Query set: `docs/evaluation/PRODUCT-QUERY-SET.md`
- Packets: `data/kg_runs/private_goldset_eval_2026_05_11/q081_packets_for_answers_eval_2026_05_12.json`
- Answers: `data/kg_runs/private_goldset_eval_2026_05_11/q081_answers_eval_2026_05_12.json`
- Model: `opus`
- Scenario count: 1
- Skipped missing ground truth: None

## Summary

| Scenario | Evidence | Answer | Failure Owner | Notes |
|---|---|---|---|---|
| Q081 | partial | Pass | none | The generated answer accurately reconstructs the ShopAgain runtime topology, citing api.shopagain.io→mercury_api via Apache/WSGI, app.shopagain.io for mercury_ui from Terraform, mercury_webhooks Zappa domain, mercury_tracking shopagainmail.net, campaign-message SQS producer/consumer pair, websocket route, and mercury_ml_api→mercury_ml dependency. It properly flags missing deploy evidence for prod_ml_api as required by the expected shape. |

## Q081 - Pass

**Evidence completeness:** partial

**Failure owner:** none

### Summary

The generated answer accurately reconstructs the ShopAgain runtime topology, citing api.shopagain.io→mercury_api via Apache/WSGI, app.shopagain.io for mercury_ui from Terraform, mercury_webhooks Zappa domain, mercury_tracking shopagainmail.net, campaign-message SQS producer/consumer pair, websocket route, and mercury_ml_api→mercury_ml dependency. It properly flags missing deploy evidence for prod_ml_api as required by the expected shape.

### Ground Truth Coverage

- mercury_api serves api.shopagain.io via ansible-playbooks/apache/prod_shopagain.conf and prod_shopagain_wsgi.py — covered with citation.
- mercury_ui web app with app.shopagain.io in latticeai-terraform/prod/variables.tf:75 — covered with citation.
- mercury_webhooks serves webhooks.shopagain.io via Zappa — covered with citation.
- mercury_tracking serves shopagainmail.net via Zappa — covered with citation.
- mercury_campaign_messages consumes campaign-message SQS via zappa_settings.json — covered with citation.
- mercury_websocket exposes websocket routes in serverless.yml — covered (ANY /postChatMessage).
- mercury_ml_api depends on mercury_ml — covered; deploy via prod_ml_api.conf not present in packet but answer explicitly flags this absence.

### Missing Or Weak Evidence

- ansible-playbooks/apache/prod_ml_api.conf is referenced by ground truth but not present in the evidence packet (deploy_prod_ml_api retrieval returned no facts).

### Answer Issues

- Minor: the answer cannot prove mercury_ml_api deploy target since the packet lacks prod_ml_api.conf evidence, but this is explicitly disclosed.

### Recommended Next Action

Re-run deploy_mappings with broader filename matching (e.g., prod_ml_api or apache/*ml*.conf) or fall back to a path search to retrieve ansible-playbooks/apache/prod_ml_api.conf so the ML API deploy evidence is captured.
