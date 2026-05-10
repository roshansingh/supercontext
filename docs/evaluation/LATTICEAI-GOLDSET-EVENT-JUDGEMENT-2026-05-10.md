# Goldset Judgement

- Query set: `docs/evaluation/PRODUCT-QUERY-SET.md`
- Packets: `data/kg_runs/latticeai_23_event_eval_2026_05_10/goldset_packets_event_eval_2026_05_10.json`
- Answers: `data/kg_runs/latticeai_23_event_eval_2026_05_10/goldset_answers_event_eval_2026_05_10.json`
- Model: `opus`
- Scenario count: 3
- Skipped missing ground truth: None

## Summary

| Scenario | Evidence | Answer | Failure Owner | Notes |
|---|---|---|---|---|
| Q088 | complete | Pass | none | The EvidencePacket contains all the producer, consumer, Zappa event source, and config references needed to reconstruct the ground truth. The generated answer covers all three queues called out in the ground truth (la-prod-campaign, la-prod-campaign-messages, la-prod-email) with the correct producer functions, consumer handlers, file/line citations, and the Zappa SQS trigger for mercury-campaign-messages. |
| Q095 | complete | Pass | none | Evidence packet contains the apache vhost route from api.shopagain.io to prod_shopagain_wsgi.py in mercury_api, plus all client/config references (ShopAgainMobile, mercury_ui, mercury_campaign_messages, mercury_tracking, mercury_webhooks). The generated answer correctly synthesizes the domain-to-WSGI mapping, backend repo, and impacted clients with citations. |
| Q106 | complete | Pass | none | The packet retrieves the producer (user_messaging.send_email_to_queue resolving settings.CAMPAIGN_MESSAGE_SQS to la-prod-campaign-messages), the Zappa-bound consumer (process_campaign_message_delivery with the full SQS ARN on stage prod), and downstream evidence (email_sender.py producing to la-prod-email and configmanager/prod.ini reference). The generated answer correctly identifies producer, consumer handler, ARN, and edge evidence with citations matching ground truth. |

## Q088 - Pass

**Evidence completeness:** complete

**Failure owner:** none

### Summary

The EvidencePacket contains all the producer, consumer, Zappa event source, and config references needed to reconstruct the ground truth. The generated answer covers all three queues called out in the ground truth (la-prod-campaign, la-prod-campaign-messages, la-prod-email) with the correct producer functions, consumer handlers, file/line citations, and the Zappa SQS trigger for mercury-campaign-messages.

### Ground Truth Coverage

- CAMPAIGN_SQS / la-prod-campaign covered: producer campaign_event.py L58 and consumer campaign_event_processor.py L25 cited.
- CAMPAIGN_MESSAGE_SQS / la-prod-campaign-messages covered: producer user_messaging.py L469 and Zappa-bound consumer process_campaign_message_delivery cited with ARN.
- la-prod-email covered: prod.ini L5 reference and email_sender.py L71 producer cited; consume_email_queue mentioned as a downstream consumer.

### Missing Or Weak Evidence

- Settings line citations from mercury_api/settings/prod.py:31 and :44 are not explicitly in the EvidencePacket as separate items, though resolution metadata implicitly references those settings modules; this did not affect answer correctness.

### Answer Issues

- Answer omits the explicit settings/prod.py line citations (31, 44) named in ground truth, but provides equivalent CAMPAIGN_SQS / CAMPAIGN_MESSAGE_SQS resolution context.
- Adds an extra la-prod-email-activity flow not required by ground truth, but this is supplementary and not incorrect.

### Recommended Next Action

Accept the answer; optionally enrich future packets with explicit settings-file citations to better mirror ground-truth phrasing.

## Q095 - Pass

**Evidence completeness:** complete

**Failure owner:** none

### Summary

Evidence packet contains the apache vhost route from api.shopagain.io to prod_shopagain_wsgi.py in mercury_api, plus all client/config references (ShopAgainMobile, mercury_ui, mercury_campaign_messages, mercury_tracking, mercury_webhooks). The generated answer correctly synthesizes the domain-to-WSGI mapping, backend repo, and impacted clients with citations.

### Ground Truth Coverage

- api.shopagain.io routes to /home/ubuntu/mercury_api/mercury_api/prod_shopagain_wsgi.py via ansible-playbooks/apache/prod_shopagain.conf:2-7 — covered
- Backend repo mercury_api — covered
- mercury_ui REACT_APP_API_ROOT=https://api.shopagain.io/ — covered
- ShopAgainMobile VITE_API_ROOT=https://api.shopagain.io — covered
- mercury_campaign_messages/configmanager/prod.ini:8 — covered
- mercury_tracking/common/configmanager/prod.ini:8 — covered
- mercury_webhooks/common/configmanager/prod.ini:28 — covered

### Missing Or Weak Evidence

- None.

### Answer Issues

- Includes shopagain_api_docs references which are not in the ground truth, but appropriately caveated as documentation artifacts.

### Recommended Next Action

Accept the answer; optional improvement is to differentiate runtime clients from documentation-only references more strongly upfront.

## Q106 - Pass

**Evidence completeness:** complete

**Failure owner:** none

### Summary

The packet retrieves the producer (user_messaging.send_email_to_queue resolving settings.CAMPAIGN_MESSAGE_SQS to la-prod-campaign-messages), the Zappa-bound consumer (process_campaign_message_delivery with the full SQS ARN on stage prod), and downstream evidence (email_sender.py producing to la-prod-email and configmanager/prod.ini reference). The generated answer correctly identifies producer, consumer handler, ARN, and edge evidence with citations matching ground truth.

### Ground Truth Coverage

- Producer file/function: user_messaging.send_email_to_queue with settings.CAMPAIGN_MESSAGE_SQS — covered
- Prod setting value la-prod-campaign-messages — covered (via resolution literal_ref)
- Consumer handler mercury_campaign_messages.email_sender.process_campaign_message_delivery — covered
- Zappa wiring with ARN arn:aws:sqs:eu-west-1:015424956416:la-prod-campaign-messages on stage prod — covered
- Downstream emission to la-prod-email via email_sender.py and configmanager/prod.ini — present in evidence but not surfaced explicitly in the answer

### Missing Or Weak Evidence

- Producer evidence reports only line 469 rather than the 425-469 range mentioned in GT (minor).
- Settings file location prod.py:44 is implied via resolution.source but not given as a discrete line citation.

### Answer Issues

- Answer does not explicitly mention the consumer's downstream emission to la-prod-email (email_sender.py:71, configmanager/prod.ini:5), which GT includes as supporting context. Not strictly required by the question (which targets la-prod-campaign-messages edge), so does not break Pass.

### Recommended Next Action

Optionally extend the answer with a brief note on the consumer's downstream emit to la-prod-email to fully mirror the ground truth narrative.
