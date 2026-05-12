from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from source.kg.core.models import JsonObject
from source.kg.product.contract_reconciliation import ContractReconciliationSpec, ContractSide, reconcile_contract
from source.kg.query.snapshot import KgSnapshot


ScenarioCommand = Literal[
    "domain_references",
    "deploy_mappings",
    "endpoints",
    "event_channels",
    "reconcile_contract",
    "repo_dependencies",
    "symbols",
]


@dataclass(frozen=True)
class RetrievalStep:
    name: str
    command: ScenarioCommand
    args: JsonObject
    purpose: str

    def run(self, kg: KgSnapshot) -> JsonObject:
        if self.command == "domain_references":
            return kg.domain_references(str(self.args["domain"]), limit=int(self.args.get("limit", 25)))
        if self.command == "deploy_mappings":
            return kg.deploy_mappings(target_query=_optional_str(self.args.get("target")), limit=int(self.args.get("limit", 25)))
        if self.command == "endpoints":
            return kg.endpoints(path_query=_optional_str(self.args.get("path")), limit=int(self.args.get("limit", 25)))
        if self.command == "event_channels":
            return kg.event_channels(channel_query=_optional_str(self.args.get("channel")), limit=int(self.args.get("limit", 25)))
        if self.command == "reconcile_contract":
            return reconcile_contract(kg, _contract_spec_from_args(self.args))
        if self.command == "repo_dependencies":
            return kg.repo_dependencies(str(self.args["repo"]), limit=int(self.args.get("limit", 25)))
        if self.command == "symbols":
            return kg.lookup_symbol(str(self.args["query"]), limit=int(self.args.get("limit", 25)))
        raise ValueError(f"Unsupported scenario command: {self.command}")


@dataclass(frozen=True)
class ScenarioPlan:
    scenario_id: str
    user_query: str
    expected_answer_shape: str
    steps: tuple[RetrievalStep, ...]

    def run(self, kg: KgSnapshot) -> list[JsonObject]:
        return [
            {
                "step": step.name,
                "command": step.command,
                "args": step.args,
                "purpose": step.purpose,
                "result": step.run(kg),
            }
            for step in self.steps
        ]


SCENARIO_PLANS: dict[str, ScenarioPlan] = {
    "Q081": ScenarioPlan(
        scenario_id="Q081",
        user_query="What are the runtime building blocks of ShopAgain across these repos, and which domains route to each backend?",
        expected_answer_shape=(
            "Runtime topology map covering web/mobile clients, API backend, webhooks, tracking, campaign workers, "
            "websocket service, ML API dependency, and deploy/domain citations. Explicitly call out missing deploy "
            "evidence when a component has no routed domain mapping."
        ),
        steps=(
            RetrievalStep(
                name="domain_api_shopagain",
                command="domain_references",
                args={"domain": "api.shopagain.io", "limit": 100},
                purpose="Find production API domain references and the Apache/WSGI route to the backend service.",
            ),
            RetrievalStep(
                name="deploy_prod_shopagain_wsgi",
                command="deploy_mappings",
                args={"target": "prod_shopagain_wsgi.py", "limit": 25},
                purpose="Find the deployed backend target serving the production API domain.",
            ),
            RetrievalStep(
                name="domain_app_shopagain",
                command="domain_references",
                args={"domain": "app.shopagain.io", "limit": 100},
                purpose="Find web-app domain references, including Terraform environment configuration.",
            ),
            RetrievalStep(
                name="domain_webhooks_shopagain",
                command="domain_references",
                args={"domain": "webhooks.shopagain.io", "limit": 100},
                purpose="Find webhook service domain references from deployment/config files.",
            ),
            RetrievalStep(
                name="domain_tracking_shopagainmail",
                command="domain_references",
                args={"domain": "shopagainmail.net", "limit": 100},
                purpose="Find tracking service domain references from deployment/config files.",
            ),
            RetrievalStep(
                name="campaign_messages_queue",
                command="event_channels",
                args={"channel": "la-prod-campaign-messages", "limit": 100},
                purpose="Find campaign-message producer and consumer services.",
            ),
            RetrievalStep(
                name="websocket_post_chat_message",
                command="endpoints",
                args={"path": "postChatMessage", "limit": 100},
                purpose="Find websocket service routes used by live chat.",
            ),
            RetrievalStep(
                name="ml_api_depends_on_ml_library",
                command="repo_dependencies",
                args={"repo": "mercury_ml_api", "limit": 25},
                purpose="Find ML API dependency on the packaged ML library repo.",
            ),
            RetrievalStep(
                name="deploy_prod_ml_api",
                command="deploy_mappings",
                args={"target": "prod_ml_api", "limit": 25},
                purpose="Check whether the KG can prove the ML API deploy target from Apache/WSGI config.",
            ),
        ),
    ),
    "Q082": ScenarioPlan(
        scenario_id="Q082",
        user_query="Which clients call api.shopagain.io, and which deployed backend serves that domain?",
        expected_answer_shape="Client env/baseURL references plus Apache deploy mapping to the backend repo and WSGI entrypoint.",
        steps=(
            RetrievalStep(
                name="domain_api_shopagain",
                command="domain_references",
                args={"domain": "api.shopagain.io", "limit": 100},
                purpose="Find services, env vars, and config files that reference the production API domain.",
            ),
            RetrievalStep(
                name="deploy_prod_shopagain_wsgi",
                command="deploy_mappings",
                args={"target": "prod_shopagain_wsgi.py", "limit": 25},
                purpose="Find Apache/WSGI deploy mapping that serves the production API domain.",
            ),
        ),
    ),
    "Q083": ScenarioPlan(
        scenario_id="Q083",
        user_query="If token auth endpoints change in the backend, which web and mobile callers are affected?",
        expected_answer_shape="Backend auth/token routes plus frontend/mobile endpoint callers with file/line citations.",
        steps=(
            RetrievalStep(
                name="token_endpoints",
                command="endpoints",
                args={"path": "/api/token", "limit": 100},
                purpose="Find JWT token routes and direct frontend/mobile callers.",
            ),
            RetrievalStep(
                name="auth_endpoints",
                command="endpoints",
                args={"path": "auth", "limit": 100},
                purpose="Find broader auth routes and web auth callers.",
            ),
        ),
    ),
    "Q084": ScenarioPlan(
        scenario_id="Q084",
        user_query="If Stripe billing behavior changes, which UI flows, backend handlers, and webhook processors need validation?",
        expected_answer_shape=(
            "Feature-slice impact map covering billing UI screens/actions, backend Stripe routes and handlers, "
            "external webhook ingestion, queue producer/consumer evidence, and explicit gaps for unproved edges."
        ),
        steps=(
            RetrievalStep(
                name="ui_billing_screen_symbols",
                command="symbols",
                args={"query": "PlansAndBenifits", "limit": 25},
                purpose="Find the billing UI screen that launches Stripe portal or plan flows.",
            ),
            RetrievalStep(
                name="ui_billing_route_symbols",
                command="symbols",
                args={"query": "Billing", "limit": 25},
                purpose="Find UI billing route/navigation symbols.",
            ),
            RetrievalStep(
                name="backend_stripe_endpoints",
                command="endpoints",
                args={"path": "stripe", "limit": 100},
                purpose="Find backend Stripe routes and the external Stripe webhook route.",
            ),
            RetrievalStep(
                name="backend_create_charge_endpoint",
                command="endpoints",
                args={"path": "create-charge", "limit": 100},
                purpose="Find the backend create-charge endpoint used by billing plan flows.",
            ),
            RetrievalStep(
                name="backend_stripe_symbols",
                command="symbols",
                args={"query": "Stripe", "limit": 50},
                purpose="Find backend and webhook Stripe handler symbols.",
            ),
            RetrievalStep(
                name="stripe_event_channel",
                command="event_channels",
                args={"channel": "la-prod-stripe", "limit": 100},
                purpose="Find Stripe webhook queue producer/config references.",
            ),
            RetrievalStep(
                name="stripe_queue_consumer_symbols",
                command="symbols",
                args={"query": "stripe_event_processor", "limit": 25},
                purpose="Find backend Stripe queue consumer/processor symbols.",
            ),
            RetrievalStep(
                name="stripe_queue_command_symbols",
                command="symbols",
                args={"query": "process_stripe_queue", "limit": 25},
                purpose="Find the backend management command that polls or processes the Stripe queue.",
            ),
        ),
    ),
    "Q092": ScenarioPlan(
        scenario_id="Q092",
        user_query="What repos participate in live chat, from customer widget to websocket to backend API and operator UI?",
        expected_answer_shape=(
            "End-to-end live-chat topology covering storefront/widget entrypoints, websocket routes/handlers, "
            "backend live-chat APIs, mobile/operator UI callers, and explicit gaps for unproved callback edges."
        ),
        steps=(
            RetrievalStep(
                name="storefront_script_symbols",
                command="symbols",
                args={"query": "shopagain_script", "limit": 25},
                purpose="Find storefront script symbols that can expose customer widget entrypoints.",
            ),
            RetrievalStep(
                name="widget_model_symbols",
                command="symbols",
                args={"query": "Widget", "limit": 25},
                purpose="Find backend widget configuration symbols.",
            ),
            RetrievalStep(
                name="websocket_post_chat_route",
                command="endpoints",
                args={"path": "postChatMessage", "limit": 100},
                purpose="Find websocket route declarations for posting chat messages.",
            ),
            RetrievalStep(
                name="websocket_get_history_route",
                command="endpoints",
                args={"path": "getChatHistory", "limit": 100},
                purpose="Find websocket route declarations for chat history.",
            ),
            RetrievalStep(
                name="websocket_handler_symbols",
                command="symbols",
                args={"query": "postChatMessage", "limit": 25},
                purpose="Find websocket handler function symbols.",
            ),
            RetrievalStep(
                name="backend_live_chat_symbols",
                command="symbols",
                args={"query": "live_chat", "limit": 50},
                purpose="Find backend live-chat view and handler symbols.",
            ),
            RetrievalStep(
                name="chat_endpoint_inventory",
                command="endpoints",
                args={"path": "chat", "limit": 100},
                purpose="Find chat-related backend endpoints and client calls.",
            ),
            RetrievalStep(
                name="operator_conversation_symbols",
                command="symbols",
                args={"query": "Conversations", "limit": 25},
                purpose="Find operator/mobile conversation UI symbols.",
            ),
            RetrievalStep(
                name="backend_live_chat_endpoint",
                command="endpoints",
                args={"path": "campaigns/live_chat", "limit": 100},
                purpose="Check whether the KG can prove the exact backend live-chat callback endpoint.",
            ),
        ),
    ),
    "Q088": ScenarioPlan(
        scenario_id="Q088",
        user_query="Which SQS queues connect campaign scheduling to message delivery, and who consumes each queue?",
        expected_answer_shape="Queue names, config references, consumer handlers, and Zappa event citations.",
        steps=(
            RetrievalStep(
                name="campaign_queue",
                command="event_channels",
                args={"channel": "la-prod-campaign", "limit": 100},
                purpose="Find campaign scheduling queue references.",
            ),
            RetrievalStep(
                name="campaign_messages_queue",
                command="event_channels",
                args={"channel": "la-prod-campaign-messages", "limit": 100},
                purpose="Find campaign message delivery queue references and consumers.",
            ),
            RetrievalStep(
                name="delivery_status_queue",
                command="event_channels",
                args={"channel": "la-prod-email", "limit": 100},
                purpose="Find downstream delivery-status queue references and producers.",
            ),
        ),
    ),
    "Q095": ScenarioPlan(
        scenario_id="Q095",
        user_query="If prod_shopagain_wsgi.py deployment changes, which public domains and clients are impacted?",
        expected_answer_shape="Domain-to-WSGI mapping, client baseURLs pointing to that domain, and backend repo evidence.",
        steps=(
            RetrievalStep(
                name="deploy_prod_shopagain_wsgi",
                command="deploy_mappings",
                args={"target": "prod_shopagain_wsgi.py", "limit": 25},
                purpose="Find public domain and WSGI deploy target.",
            ),
            RetrievalStep(
                name="domain_api_shopagain",
                command="domain_references",
                args={"domain": "api.shopagain.io", "limit": 100},
                purpose="Find clients/configs impacted by the production API domain.",
            ),
        ),
    ),
    "Q100": ScenarioPlan(
        scenario_id="Q100",
        user_query="Which documented ShopAgain API endpoints are not obviously implemented or called by any client?",
        expected_answer_shape="Endpoint inventory across docs, backend implementation, and callers, with drift caveats.",
        steps=(
            RetrievalStep(
                name="docs_vs_backend_v1_endpoints",
                command="reconcile_contract",
                args={
                    "name": "shopagain_docs_vs_backend_v1_endpoints",
                    "identity_key": "endpoint_path",
                    "left": {
                        "name": "documented_endpoints",
                        "predicates": ["DOCUMENTS_ENDPOINT"],
                        "repos": ["shopagain_api_docs"],
                        "path_prefix": "/v1/",
                    },
                    "right": {
                        "name": "implemented_endpoints",
                        "predicates": ["EXPOSES_ENDPOINT"],
                        "repos": ["mercury_api", "mercury_webhooks"],
                        "path_prefix": "/v1/",
                    },
                },
                purpose="Compare ShopAgain public API docs against scoped backend implementations.",
            ),
            RetrievalStep(
                name="clients_vs_docs_v1_endpoints",
                command="reconcile_contract",
                args={
                    "name": "shopagain_clients_vs_docs_v1_endpoints",
                    "identity_key": "endpoint_path",
                    "left": {
                        "name": "client_called_endpoints",
                        "predicates": ["CALLS_ENDPOINT"],
                        "repos": ["mercury_ui", "ShopAgainMobile", "shopagain-chat-widget"],
                        "path_prefix": "/v1/",
                    },
                    "right": {
                        "name": "documented_endpoints",
                        "predicates": ["DOCUMENTS_ENDPOINT"],
                        "repos": ["shopagain_api_docs"],
                        "path_prefix": "/v1/",
                    },
                },
                purpose="Compare scoped client v1 calls against public API docs.",
            ),
        ),
    ),
    "Q106": ScenarioPlan(
        scenario_id="Q106",
        user_query="For la-prod-campaign-messages, who produces messages, who consumes them, and what evidence proves the edge?",
        expected_answer_shape="Producer config/send-site candidates, Zappa consumer handler, queue ARN/name, and explicit unknowns.",
        steps=(
            RetrievalStep(
                name="campaign_messages_queue",
                command="event_channels",
                args={"channel": "la-prod-campaign-messages", "limit": 100},
                purpose="Find queue references and configured consumers for campaign message delivery.",
            ),
            RetrievalStep(
                name="delivery_status_queue",
                command="event_channels",
                args={"channel": "la-prod-email", "limit": 100},
                purpose="Find downstream delivery-status queue references and producer evidence from the consumer.",
            ),
        ),
    ),
}


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _contract_spec_from_args(args: JsonObject) -> ContractReconciliationSpec:
    return ContractReconciliationSpec(
        name=str(args["name"]),
        identity_key=args.get("identity_key", "display_name"),
        left=_contract_side_from_args(args["left"]),
        right=_contract_side_from_args(args["right"]),
        possible_match_threshold=float(args.get("possible_match_threshold", 0.78)),
    )


def _contract_side_from_args(args: JsonObject) -> ContractSide:
    return ContractSide(
        name=str(args["name"]),
        predicates=tuple(str(predicate) for predicate in args.get("predicates", [])),
        repos=tuple(str(repo) for repo in args.get("repos", [])),
        path_prefix=_optional_str(args.get("path_prefix")),
    )
