from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from source.kg.models import JsonObject
from source.kg.product.contract_reconciliation import ContractReconciliationSpec, ContractSide, reconcile_contract
from source.kg.queries import KgSnapshot


ScenarioCommand = Literal[
    "domain_references",
    "deploy_mappings",
    "endpoints",
    "event_channels",
    "reconcile_contract",
    "repo_dependencies",
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
                name="campaign_api_dependency",
                command="repo_dependencies",
                args={"repo": "mercury_api", "limit": 50},
                purpose="Find cross-repo package dependencies that may contextualize the producer service.",
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
