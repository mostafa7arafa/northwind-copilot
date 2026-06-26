from dotenv import load_dotenv

load_dotenv()

from collections.abc import Callable

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
    before_model,
)
from langchain_community.agent_toolkits import SQLDatabaseToolkit
from langchain_community.utilities import SQLDatabase
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import trim_messages
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from agent.tools.docs_tool import search_docs

SYSTEM_PROMPT = """You are a retail data analyst for the Northwind database. \
You answer questions by querying the database and searching internal knowledge docs.

Rules:
1. Always call sql_db_list_tables before writing any SQL — never assume table names.
2. Call sql_db_schema on the relevant tables before writing SQL.
3. Call search_docs for any question involving KPIs (AOV, margin), campaign dates, \
product categories, or return policies — before writing SQL.
4. Always use sql_db_query_checker to validate SQL before executing it.
5. Revenue = UnitPrice * Quantity * (1 - Discount). Margin = 30% of UnitPrice.
6. Dates are stored as text; use strftime('%Y-%m', OrderDate) for month filtering.
7. Be concise — show numbers, not explanations, unless the user asks for detail.
8. NEVER end your turn with an empty reply. Every turn must be either a tool \
call or a final answer. If a query is complex, write the SQL step by step — \
do not stop and produce nothing.

Worked example — gross margin by customer (margin = 30% of revenue):
  SELECT c.CompanyName,
         ROUND(SUM(oi.UnitPrice * 0.3 * oi.Quantity * (1 - oi.Discount)), 2) AS margin
  FROM Customers c
  JOIN Orders o ON c.CustomerID = o.CustomerID
  JOIN "Order Details" oi ON o.OrderID = oi.OrderID
  WHERE strftime('%Y', o.OrderDate) = '2017'
  GROUP BY c.CompanyName
  ORDER BY margin DESC
  LIMIT 1;"""


@before_model
def _trim_context(state, runtime):
    trimmed = trim_messages(state["messages"], token_counter="approximate" ,max_tokens=8000, strategy="last")
    return {"messages": trimmed}


def _is_degenerate(response: ModelResponse) -> bool:
    """True if the model produced no usable output — no text and no tool call.

    The local model sometimes returns an empty completion on the hardest
    reasoning steps. The agent loop reads that as "done" and stops, so the
    failure is silent. Treating it as degenerate lets us escalate instead.
    """
    messages = getattr(response, "result", None) or []
    if not messages:
        return True
    last = messages[-1]
    has_text = bool(str(getattr(last, "content", "") or "").strip())
    has_tool_calls = bool(getattr(last, "tool_calls", None))
    return not (has_text or has_tool_calls)


class EscalateToFallbackMiddleware(AgentMiddleware):
    """Escalate a model call to fallback models on an error OR an empty response.

    `ModelFallbackMiddleware` only retries on exceptions, so a local model that
    silently returns nothing slips through. This also escalates when the primary
    produces a degenerate response, returning the first usable result.
    """

    def __init__(self, *fallback_models: BaseChatModel) -> None:
        super().__init__()
        self.fallbacks = list(fallback_models)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        last_response: ModelResponse | None = None
        last_exc: Exception | None = None

        try:
            response = handler(request)
            if not _is_degenerate(response):
                return response
            last_response = response  # usable-looking but empty; try fallbacks
        except Exception as exc:  # noqa: BLE001 - escalate, then re-raise if all fail
            last_exc = exc

        for model in self.fallbacks:
            try:
                response = handler(request.override(model=model))
                if not _is_degenerate(response):
                    return response
                last_response = response
            except Exception as exc:  # noqa: BLE001
                last_exc = exc

        if last_response is not None:
            return last_response
        raise last_exc  # type: ignore[misc]


def _build_agent():
    # temperature=0: NL-to-SQL needs deterministic, reproducible output.
    primary = ChatOllama(model="gemma4-12b", temperature=0)
    fallback = ChatOpenAI(model="gpt-4.1-mini", temperature=0)

    # sample_rows_in_table_info=0 strips the per-table "/* 3 rows ... */" dump
    # from sql_db_schema. That block is the largest payload re-sent on every
    # agent step; the column names, types, and FKs are what SQL generation
    # actually needs.
    db = SQLDatabase.from_uri(
        "sqlite:///data/northwind.sqlite", sample_rows_in_table_info=0
    )
    sql_tools = SQLDatabaseToolkit(db=db, llm=primary).get_tools()

    return create_agent(
        model=primary,
        tools=sql_tools + [search_docs],
        system_prompt=SYSTEM_PROMPT,
        checkpointer=None,
        middleware=[
            EscalateToFallbackMiddleware(fallback),
            _trim_context,
        ],
    )


graph = _build_agent()
