import streamlit as st
import requests
import json
import time
import os
from datetime import datetime

try:
    from databricks.sdk import WorkspaceClient
except ImportError:
    WorkspaceClient = None

# ============================================================================
# Configuration - Databricks Apps automatically provides authentication
# ============================================================================

def normalize_databricks_host(host: str) -> str:
    host = host.strip().rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = f"https://{host}"
    return host


DATABRICKS_HOST = normalize_databricks_host(
    os.getenv("DATABRICKS_HOST", "https://dbc-de54b796-a6c4.cloud.databricks.com")
)


def get_env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


GENIE_SPACE_ID = "01f14d5383a21f0e8626a80d72315de3"
DASHBOARD_URL = f"{DATABRICKS_HOST}/dashboardsv3/01f1425e745118cf87a3d81fdf2ee5a7/published"
GENIE_SPACE_URL = f"{DATABRICKS_HOST}/genie/rooms/{GENIE_SPACE_ID}"
CONTEXT_MAX_EXCHANGES = 3
CONTEXT_ENTRY_MAX_CHARS = 900
VECTOR_INDEX_NAME = os.getenv(
    "VECTOR_INDEX_NAME",
    "amit.bertopic.bertopic_input_index",
)
VECTOR_INDEX_COLUMNS = [
    column.strip()
    for column in os.getenv("VECTOR_INDEX_COLUMNS", "id,text").split(",")
    if column.strip()
]
VECTOR_SOURCE_TEXT_COLUMNS = [
    column.strip()
    for column in os.getenv(
        "VECTOR_SOURCE_TEXT_COLUMNS",
        "text,content,message,body,input_text,document",
    ).split(",")
    if column.strip()
]
VECTOR_SOURCE_NUM_RESULTS = get_env_int("VECTOR_SOURCE_NUM_RESULTS", 10)
VECTOR_SOURCE_MAX_CHARS = get_env_int("VECTOR_SOURCE_MAX_CHARS", 1200)
VECTOR_SOURCE_QUERY_TYPE = os.getenv("VECTOR_SOURCE_QUERY_TYPE", "HYBRID").upper()
DEFAULT_AGENT_LLM_ENDPOINT = os.getenv(
    "AGENT_LLM_ENDPOINT",
    "databricks-meta-llama-3-1-8b-instruct",
)
AGENT_LLM_OPTIONS = {
    "databricks-meta-llama-3-1-8b-instruct": "Llama 3.1 8B Instruct",
    "databricks-gemma-3-12b": "Gemma 3 12B",
    "databricks-gpt-oss-20b": "GPT OSS 20B",
}
if DEFAULT_AGENT_LLM_ENDPOINT not in AGENT_LLM_OPTIONS:
    DEFAULT_AGENT_LLM_ENDPOINT = next(iter(AGENT_LLM_OPTIONS))
AGENT_LLM_MAX_TOKENS = get_env_int("AGENT_LLM_MAX_TOKENS", 1200)
AGENT_LLM_TIMEOUT_SECONDS = get_env_int("AGENT_LLM_TIMEOUT_SECONDS", 90)
AGENT_MODE_NO_RAG = "no_rag"
AGENT_MODE_WITH_RAG = "with_rag"
AGENT_MODE_ONLY_VECTOR = "only_vector"
DEFAULT_AGENT_MODE = AGENT_MODE_NO_RAG
AGENT_MODE_LABELS = {
    AGENT_MODE_NO_RAG: "Genie only",
    AGENT_MODE_WITH_RAG: "Agent",
    AGENT_MODE_ONLY_VECTOR: "Vector only",
}
AGENT_MODE_CAPTIONS = {
    AGENT_MODE_NO_RAG: "Uses only the curated Genie Space. No app-side vector search or selectable model.",
    AGENT_MODE_WITH_RAG: "Uses Genie for structured analysis, vector search for evidence, and the selected model for synthesis.",
    AGENT_MODE_ONLY_VECTOR: "Uses vector search for evidence and the selected model for synthesis. Skips Genie.",
}
AGENT_MODE_HELP = "\n\n".join(
    f"{AGENT_MODE_LABELS[mode]}: {caption}"
    for mode, caption in AGENT_MODE_CAPTIONS.items()
)

ANSWER_INSTRUCTIONS = """
Answering instructions:
- Write for analysts, not engineers. Prefer interpretation, implications, and investigative takeaways over technical implementation details.
- Start with the main insight in plain language, then support it with the most relevant counts, percentages, comparisons, and examples.
- Use the retrieved source snippets from amit.bertopic.bertopic_input_index as supporting evidence whenever they are provided and relevant to the question.
- When drawing from a retrieved snippet, identify it by source number or source id so the evidence can be traced.
- When results show a pattern, explain why it may matter and what an analyst should look at next.
- Call out caveats clearly, including small sample sizes, missing labels, zero-row results, ambiguous topic names, or filters such as execution_id/model/layer.
- Keep SQL mechanics, table names, and IDs secondary unless they are needed to verify or reproduce the finding.
- When presenting topics or narratives, never identify them only by ID. Include the topic title, name, description, or full_topic whenever available.
- If a topic ID is useful, show it alongside the human-readable name, not instead of it.
- If the data does not contain a human-readable topic name for a topic ID, say that explicitly.
- When asked about a narrative or nerative, discuss the related topic(s), incitement level or label, and include relevant example messages when available.
- Do not stop with "there are no messages" just because the exact term in the question is absent. If the exact concept is missing, say that direct evidence is limited, then analyze the closest relevant themes in the data. For questions about government or goverment, also check municipal services, local authorities, public institutions, service delivery, security, economy, public order, legitimacy, and trust in authorities.
""".strip()

# ============================================================================
# Sample Questions
# ============================================================================

SAMPLE_QUESTIONS = {
    "Arena Readout": [
        "look at incitement messages and summarize who the hatress is pointing",
        "What are the main subjects being discussed, and what do they reveal about the arena?",
        "What are the dominant narratives in the text, with topic names, incitement level, and representative examples?",
        "What are the narratives reflected from the text about the functioning of the government?",
        "What are the strongest grievances, fears, and hopes expressed by people?",
        "Which narratives appear most widespread, and which appear more intense or emotionally charged?",
        "What changed between broad parent topics and more specific child topics?"
    ],
    "Governance": [
        "What is the narrative toward municipal services and local authorities?",
        "What is the narrative toward national government performance and legitimacy?",
        "Are people satisfied in general? Break down satisfaction by topic and incitement level.",
        "What do people like in the current situation, and which topics or examples support that?",
        "What do people dislike in the current situation, and which topics or examples support that?",
        "Where do people describe failures in service delivery, security, economy, or public order?"
    ],
    "Peace & Conflict": [
        "מה הנרטיב כלפי יהודים וישראל?",
        "What is the narrative toward peace?",
        "What is the narrative toward conflict, escalation, or resistance?",
        "Which topics contain the highest incitement or abusive language, and what narratives drive it?",
        "Are there narratives that encourage compromise, coexistence, or de-escalation?",
        "Are there narratives that could increase tension, mobilization, or hostility?",
        "What are the main emotional drivers behind support or opposition to peace?"
    ],
    "Public Mood": [
        "What is the overall public mood: anger, fear, frustration, hope, resignation, or confidence?",
        "Which topics show the most negative sentiment, and what are the key examples?",
        "Which topics show positive sentiment or satisfaction, and what are the key examples?",
        "What are people asking for or expecting from authorities?",
        "What are the signs of trust or distrust toward institutions?",
        "Which narratives are most likely to influence public behavior?"
    ],
    "Analyst Checks": [
        "What are the early warning indicators in the text that an intelligence analyst should monitor?",
        "Which actors, institutions, or groups are blamed, praised, or targeted in the narratives?",
        "What are the information gaps or ambiguities that require further collection?",
        "Which narratives appear coordinated, repeated, or unusually consistent across messages?",
        "What are the most relevant example messages for each major narrative?",
        "Give me an intelligence-style summary: key judgments, supporting evidence, caveats, and recommended follow-up questions."
    ]
}

# ============================================================================
# Databricks Genie API Functions
# ============================================================================

def truncate_text(text: str, max_chars: int) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def build_context_prompt(context_items: list[dict]) -> str:
    if not context_items:
        return ""

    context_lines = [
        "Recent session context. Use this only to resolve follow-up references; "
        "do not treat it as a substitute for querying the data."
    ]

    for idx, item in enumerate(context_items[-CONTEXT_MAX_EXCHANGES:], start=1):
        context_lines.append(
            f"{idx}. Previous question: {truncate_text(item.get('question'), 260)}"
        )
        answer = truncate_text(item.get("answer"), CONTEXT_ENTRY_MAX_CHARS)
        if answer:
            context_lines.append(f"   Previous answer summary: {answer}")
        if item.get("row_count") is not None:
            context_lines.append(f"   Previous row count: {item['row_count']}")

    return "\n".join(context_lines)


def build_genie_prompt(
    question: str,
    context_items: list[dict] | None = None,
    source_context: str | None = None,
) -> str:
    prompt_parts = [ANSWER_INSTRUCTIONS]
    context_prompt = build_context_prompt(context_items or [])
    if context_prompt:
        prompt_parts.append(context_prompt)
    if source_context:
        prompt_parts.append(source_context)
    prompt_parts.append(f"Current user question:\n{question}")
    return "\n\n".join(prompt_parts)


def build_context_item(question: str, results: dict) -> dict:
    answer = results.get("text_response") or ""
    if not answer and results.get("row_count") == 0:
        answer = "The generated SQL query returned 0 rows."
    if not answer and results.get("sql_query"):
        answer = "A SQL query was generated, but no narrative answer was returned."

    return {
        "question": question,
        "answer": truncate_text(answer, CONTEXT_ENTRY_MAX_CHARS),
        "row_count": results.get("row_count"),
    }


def get_workspace_client() -> tuple[object | None, str | None]:
    """Return a Databricks SDK workspace client for local dev or Apps."""
    if WorkspaceClient is None:
        return None, "databricks-sdk is not installed in the app environment."

    try:
        token = os.getenv("DATABRICKS_TOKEN")
        client_id = os.getenv("DATABRICKS_CLIENT_ID")
        client_secret = os.getenv("DATABRICKS_CLIENT_SECRET")

        if token:
            return WorkspaceClient(host=DATABRICKS_HOST, token=token), None

        if client_id and client_secret:
            return WorkspaceClient(
                host=DATABRICKS_HOST,
                client_id=client_id,
                client_secret=client_secret,
            ), None

        return WorkspaceClient(host=DATABRICKS_HOST), None
    except Exception as e:
        return None, f"Databricks SDK client initialization failed: {e}"


def get_databricks_auth_headers() -> tuple[dict, str | None]:
    """Return Databricks API auth headers for local dev or Databricks Apps."""
    token = os.getenv("DATABRICKS_TOKEN")
    if token:
        return {"Authorization": f"Bearer {token}"}, None

    workspace, client_error = get_workspace_client()
    if client_error:
        return {}, client_error

    try:
        headers = workspace.config.authenticate()
        if not headers.get("Authorization"):
            return {}, "Databricks SDK did not return an Authorization header."

        return headers, None
    except Exception as e:
        return {}, f"Databricks SDK authentication failed: {e}"


def extract_vector_sources(vector_response: object) -> list[dict]:
    """Extract ranked source snippets from a Vector Search query response."""
    response_data = (
        vector_response.as_dict()
        if hasattr(vector_response, "as_dict")
        else vector_response
    )
    if not isinstance(response_data, dict):
        return []

    manifest = response_data.get("manifest") or {}
    result = response_data.get("result") or {}
    manifest_columns = manifest.get("columns") or []
    column_names = [
        column.get("name")
        for column in manifest_columns
        if isinstance(column, dict) and column.get("name")
    ] or VECTOR_INDEX_COLUMNS

    sources = []
    for rank, row in enumerate(result.get("data_array") or [], start=1):
        if isinstance(row, dict):
            row_values = row
        else:
            row_values = dict(zip(column_names, row))

        text_column = next(
            (
                column
                for column in VECTOR_SOURCE_TEXT_COLUMNS
                if str(row_values.get(column) or "").strip()
            ),
            None,
        )
        source_text = str(row_values.get(text_column) or "").strip() if text_column else ""

        if not source_text:
            for key, value in row_values.items():
                if key in {"id", "score", "distance"}:
                    continue
                candidate_text = str(value or "").strip()
                if candidate_text:
                    text_column = key
                    source_text = candidate_text
                    break

        if not source_text:
            continue

        metadata = {
            key: value
            for key, value in row_values.items()
            if key != text_column and value not in (None, "")
        }
        sources.append(
            {
                "rank": rank,
                "text": truncate_text(source_text, VECTOR_SOURCE_MAX_CHARS),
                "metadata": metadata,
            }
        )

    return sources


def query_vector_sources(question: str, num_results: int = VECTOR_SOURCE_NUM_RESULTS) -> dict:
    """Retrieve source snippets from the BERTopic Vector Search index."""
    if not VECTOR_INDEX_NAME or not VECTOR_INDEX_COLUMNS:
        return {"source_documents": [], "warning": None}

    workspace, client_error = get_workspace_client()
    if client_error:
        return {
            "source_documents": [],
            "warning": f"Vector source lookup skipped: {client_error}",
        }

    def run_query(query_type: str | None) -> object:
        kwargs = {
            "index_name": VECTOR_INDEX_NAME,
            "columns": VECTOR_INDEX_COLUMNS,
            "num_results": num_results,
            "query_text": question,
        }
        if query_type:
            kwargs["query_type"] = query_type
        return workspace.vector_search_indexes.query_index(**kwargs)

    try:
        vector_response = run_query(VECTOR_SOURCE_QUERY_TYPE)
        return {
            "source_documents": extract_vector_sources(vector_response),
            "warning": None,
        }
    except Exception as e:
        if VECTOR_SOURCE_QUERY_TYPE != "ANN":
            try:
                vector_response = run_query("ANN")
                return {
                    "source_documents": extract_vector_sources(vector_response),
                    "warning": (
                        f"Vector source lookup used ANN fallback after "
                        f"{VECTOR_SOURCE_QUERY_TYPE} failed: {e}"
                    ),
                }
            except Exception as fallback_error:
                return {
                    "source_documents": [],
                    "warning": (
                        f"Vector source lookup failed for {VECTOR_INDEX_NAME}: "
                        f"{e}; ANN fallback also failed: {fallback_error}"
                    ),
                }

        return {
            "source_documents": [],
            "warning": f"Vector source lookup failed for {VECTOR_INDEX_NAME}: {e}",
        }


def build_source_context_prompt(source_documents: list[dict]) -> str:
    if not source_documents:
        return ""

    lines = [
        f"Retrieved source snippets from {VECTOR_INDEX_NAME}.",
        "Use these snippets as source evidence for the current question when relevant. "
        "Cite source numbers or ids for examples drawn from them.",
    ]
    for source in source_documents:
        metadata = source.get("metadata") or {}
        source_id = metadata.get("id") or metadata.get("primary_key")
        score = metadata.get("score")
        label_parts = [f"Source {source.get('rank')}"]
        if source_id is not None:
            label_parts.append(f"id={source_id}")
        if score is not None:
            label_parts.append(f"score={score}")
        lines.append(f"{' | '.join(label_parts)}:")
        lines.append(source.get("text", ""))

    return "\n".join(lines)


def format_source_documents(source_documents: list[dict]) -> str:
    if not source_documents:
        return "No vector source snippets were retrieved."

    sections = []
    for source in source_documents:
        metadata = source.get("metadata") or {}
        source_id = metadata.get("id") or metadata.get("primary_key")
        label_parts = [f"Source {source.get('rank')}"]
        if source_id is not None:
            label_parts.append(f"id={source_id}")

        metadata_items = [
            f"{key}={value}"
            for key, value in metadata.items()
            if key not in VECTOR_SOURCE_TEXT_COLUMNS
            and key not in {"id", "primary_key"}
        ]
        if metadata_items:
            label_parts.append("; ".join(metadata_items[:6]))

        sections.append(
            f"{' | '.join(label_parts)}\n{source.get('text', '')}"
        )

    return "\n\n".join(sections)


def format_structured_results(results: dict | None) -> str:
    if not results:
        return "No structured results were returned."

    sections = []
    if results.get("text_response"):
        sections.append(f"Genie answer:\n{results['text_response']}")

    if results.get("sql_query"):
        sections.append(f"Generated SQL:\n{results['sql_query']}")

    columns = results.get("columns") or []
    data_rows = results.get("data_rows") or []
    if columns and data_rows:
        preview_rows = data_rows[:20]
        row_lines = [", ".join(columns)]
        for row in preview_rows:
            row_lines.append(", ".join(str(value) for value in row))
        sections.append("Structured data preview:\n" + "\n".join(row_lines))
        if len(data_rows) > len(preview_rows):
            sections.append(
                f"Structured data preview truncated to {len(preview_rows)} "
                f"of {len(data_rows)} rows."
            )
    elif results.get("row_count") == 0:
        sections.append("Structured query returned 0 rows.")

    return "\n\n".join(sections) if sections else "No structured results were returned."


def extract_chat_response_text(response_data: dict) -> str:
    choices = response_data.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "\n".join(
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("text")
            )

    predictions = response_data.get("predictions") or []
    if predictions:
        first_prediction = predictions[0]
        if isinstance(first_prediction, str):
            return first_prediction
        if isinstance(first_prediction, dict):
            return (
                first_prediction.get("content")
                or first_prediction.get("text")
                or json.dumps(first_prediction)
            )

    return response_data.get("content") or ""


def query_chat_model(
    messages: list[dict],
    auth_headers: dict,
    endpoint_name: str,
) -> dict:
    endpoint_url = f"{DATABRICKS_HOST}/serving-endpoints/{endpoint_name}/invocations"
    headers = {**auth_headers, "Content-Type": "application/json"}

    try:
        response = requests.post(
            endpoint_url,
            headers=headers,
            json={
                "messages": messages,
                "max_tokens": AGENT_LLM_MAX_TOKENS,
                "temperature": 0.1,
            },
            timeout=AGENT_LLM_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        response_data = response.json()
        response_text = extract_chat_response_text(response_data)
        if not response_text:
            return {
                "error": "LLM endpoint returned no text.",
                "details": response_data,
            }

        return {
            "success": True,
            "text": response_text,
            "raw_response": response_data,
        }
    except requests.exceptions.RequestException as e:
        return {"error": f"LLM endpoint request failed: {e}"}
    except Exception as e:
        return {"error": f"Unexpected LLM endpoint error: {e}"}


def synthesize_agent_answer(
    question: str,
    auth_headers: dict,
    structured_results: dict | None,
    source_documents: list[dict],
    mode_label: str,
    endpoint_name: str,
) -> dict:
    system_prompt = f"""
You are a narrative analysis agent.
Use the supplied structured metadata results and vector source snippets to answer the user's question.
Prefer a direct analytic answer over tool mechanics.
Use structured results for counts, topic metadata, labels, and aggregate claims.
Use vector snippets for example language, qualitative evidence, and grounding.
If structured data and vector snippets disagree or one is missing, say that plainly.
When citing examples from vector snippets, cite Source N or id when available.
Do not invent rows, counts, topic names, or messages that are not present in the supplied context.
Mode: {mode_label}
""".strip()

    user_prompt = f"""
Question:
{question}

Structured metadata context:
{format_structured_results(structured_results)}

Vector source context:
{format_source_documents(source_documents)}
""".strip()

    return query_chat_model(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        auth_headers=auth_headers,
        endpoint_name=endpoint_name,
    )


def build_agent_results(
    question: str,
    genie_response: dict | None,
    structured_results: dict | None,
    source_documents: list[dict],
    source_warning: str | None,
    synthesis_response: dict,
) -> tuple[dict, dict]:
    response = {
        "success": True,
        "question": question,
        "source_documents": source_documents,
        "source_warning": source_warning,
        "synthesis_response": synthesis_response,
    }
    if genie_response:
        response["conversation_id"] = genie_response.get("conversation_id")
        response["message_id"] = genie_response.get("message_id")

    if synthesis_response.get("error"):
        fallback_parts = [
            "Agent synthesis failed, so showing available tool context instead.",
            synthesis_response["error"],
        ]
        if structured_results and structured_results.get("text_response"):
            fallback_parts.append(structured_results["text_response"])
        if source_documents:
            fallback_parts.append(
                f"{len(source_documents)} vector source snippets were retrieved."
            )
        answer = "\n\n".join(fallback_parts)
    else:
        answer = synthesis_response.get("text", "")

    results = {
        "text_response": answer,
        "sql_query": structured_results.get("sql_query") if structured_results else None,
        "data_rows": structured_results.get("data_rows", []) if structured_results else [],
        "columns": structured_results.get("columns", []) if structured_results else [],
        "chart_spec": structured_results.get("chart_spec") if structured_results else None,
        "suggested_questions": (
            structured_results.get("suggested_questions", [])
            if structured_results
            else []
        ),
        "source_documents": source_documents,
        "source_warning": source_warning,
        "row_count": structured_results.get("row_count") if structured_results else None,
        "query_result_error": (
            structured_results.get("query_result_error") if structured_results else None
        ),
        "raw_result": {
            "structured_results": structured_results or {},
            "synthesis_response": synthesis_response,
        },
        "structured_answer": (
            structured_results.get("text_response") if structured_results else None
        ),
        "synthesis_error": synthesis_response.get("error"),
        "error": None,
    }
    return response, results


def build_vector_only_response(
    question: str,
    source_documents: list[dict],
    source_warning: str | None,
) -> tuple[dict, dict]:
    if source_documents:
        response_text = (
            f"Vector-only mode returned {len(source_documents)} source snippets "
            f"from {VECTOR_INDEX_NAME}. Genie was not queried."
        )
    else:
        response_text = (
            f"Vector-only mode did not return source snippets from "
            f"{VECTOR_INDEX_NAME}. Genie was not queried."
        )

    response = {
        "success": True,
        "question": question,
        "source_documents": source_documents,
        "source_warning": source_warning,
    }
    results = {
        "text_response": response_text,
        "sql_query": None,
        "data_rows": [],
        "columns": [],
        "chart_spec": None,
        "suggested_questions": [],
        "source_documents": source_documents,
        "source_warning": source_warning,
        "row_count": len(source_documents),
        "query_result_error": None,
        "raw_result": {},
        "error": None,
    }
    return response, results


def query_genie_space(
    question: str,
    space_id: str,
    auth_headers: dict,
    host: str,
    context_items: list[dict] | None = None,
    source_context: str | None = None,
) -> dict:
    """
    Query a Databricks Genie space with a natural language question.
    
    Args:
        question: Natural language question to ask
        space_id: Genie space ID
        auth_headers: Databricks API authentication headers
        host: Databricks workspace URL
    
    Returns:
        Dictionary containing the response
    """
    conversation_url = f"{host}/api/2.0/genie/spaces/{space_id}/start-conversation"
    headers = {**auth_headers, "Content-Type": "application/json"}
    prompt = build_genie_prompt(question, context_items, source_context)
    
    try:
        # Start conversation
        response = requests.post(
            conversation_url,
            headers=headers,
            json={"content": prompt},
            timeout=30
        )
        response.raise_for_status()
        conversation_data = response.json()
        
        conversation_id = conversation_data.get("conversation_id")
        message_id = conversation_data.get("message_id")
        
        if not conversation_id or not message_id:
            return {"error": "Failed to start conversation", "details": conversation_data}
        
        # Poll for results
        result_url = f"{host}/api/2.0/genie/spaces/{space_id}/conversations/{conversation_id}/messages/{message_id}"
        
        max_attempts = 180  # Genie queries can take several minutes.
        for attempt in range(max_attempts):
            result_response = requests.get(result_url, headers=headers, timeout=30)
            result_response.raise_for_status()
            result_data = result_response.json()
            
            status = result_data.get("status")
            
            if status == "COMPLETED":
                for attachment in result_data.get("attachments", []):
                    attachment_id = attachment.get("attachment_id")
                    if not attachment_id or not attachment.get("query"):
                        continue

                    query_result_url = (
                        f"{result_url}/attachments/{attachment_id}/query-result"
                    )
                    query_result_response = requests.get(
                        query_result_url,
                        headers=headers,
                        timeout=30,
                    )
                    if query_result_response.ok:
                        attachment["query_result"] = query_result_response.json()
                    else:
                        attachment["query_result_error"] = {
                            "status_code": query_result_response.status_code,
                            "message": query_result_response.text,
                        }

                return {
                    "success": True,
                    "question": question,
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                    "result": result_data
                }
            elif status in ["FAILED", "CANCELLED"]:
                error_msg = result_data.get("error", {}).get("message", "Unknown error")
                return {
                    "error": f"Query {status.lower()}: {error_msg}",
                    "details": result_data
                }
            
            time.sleep(2)
        
        return {"error": "Query timed out after 2 minutes"}
        
    except requests.exceptions.RequestException as e:
        return {"error": f"API request failed: {str(e)}"}
    except Exception as e:
        return {"error": f"Unexpected error: {str(e)}"}

def extract_query_results(genie_response: dict) -> dict:
    """Extract and format results from Genie API response."""
    if not genie_response.get("success"):
        return genie_response
    
    result = genie_response.get("result", {})
    attachments = result.get("attachments", [])
    
    formatted_results = {
        "text_response": "",
        "sql_query": None,
        "data_rows": [],
        "columns": [],
        "chart_spec": None,
        "suggested_questions": [],
        "source_documents": genie_response.get("source_documents", []),
        "source_warning": genie_response.get("source_warning"),
        "row_count": None,
        "query_result_error": None,
        "raw_result": result,
        "error": None
    }
    text_parts = []
    
    # Extract SQL, data, and visualizations from Genie attachment formats.
    for attachment in attachments:
        attachment_type = attachment.get("type")

        if attachment.get("text", {}).get("content"):
            text_parts.append(attachment["text"]["content"])

        if attachment.get("suggested_questions", {}).get("questions"):
            formatted_results["suggested_questions"].extend(
                attachment["suggested_questions"]["questions"]
            )

        if attachment.get("query"):
            query_info = attachment["query"]
            formatted_results["sql_query"] = query_info.get("query")
            query_metadata = query_info.get("query_result_metadata", {})
            if query_metadata.get("row_count") is not None:
                formatted_results["row_count"] = query_metadata["row_count"]

            query_result = attachment.get("query_result", {})
            statement_response = query_result.get("statement_response", {})
            manifest = statement_response.get("manifest", {})
            schema = manifest.get("schema", {})
            columns = schema.get("columns", [])
            formatted_results["columns"] = [
                col.get("name") for col in columns if col.get("name")
            ]
            formatted_results["data_rows"] = (
                statement_response.get("result", {}).get("data_array", [])
            )

            if manifest.get("total_row_count") is not None:
                formatted_results["row_count"] = manifest["total_row_count"]

            if attachment.get("query_result_error"):
                formatted_results["query_result_error"] = attachment["query_result_error"]

        if attachment_type == "QUERY":
            query_info = attachment.get("query", {})
            formatted_results["sql_query"] = query_info.get("query")
            
            # Extract data if available
            if query_info.get("status") == "SUCCEEDED":
                result_data = query_info.get("result", {})
                formatted_results["data_rows"] = result_data.get("data_array", [])
                
                # Extract column information
                schema = result_data.get("schema", {})
                formatted_results["columns"] = [
                    col.get("name") for col in schema.get("columns", [])
                ]
        
        elif attachment_type == "CHART":
            formatted_results["chart_spec"] = attachment.get("chart", {})

    if not text_parts:
        content = result.get("content", "")
        if content and content != genie_response.get("question"):
            text_parts.append(content)

    formatted_results["text_response"] = "\n\n".join(text_parts)
    
    return formatted_results


def display_genie_response(response: dict, results: dict | None) -> None:
    if response.get("error"):
        st.error(f"❌ Error: {response['error']}")
        if response.get("details"):
            with st.expander("Show error details"):
                st.json(response["details"])
        return

    if not results:
        return

    st.markdown("---")
    st.markdown("## Results")

    displayed_content = False

    if results.get("text_response"):
        st.markdown("### Answer")
        st.markdown(results["text_response"])
        displayed_content = True

    if results.get("source_documents"):
        st.markdown("### Source snippets")
        with st.expander(
            f"Vector index sources ({len(results['source_documents'])})",
            expanded=False,
        ):
            for source in results["source_documents"]:
                metadata = source.get("metadata") or {}
                source_id = metadata.get("id") or metadata.get("primary_key")
                source_label = f"Source {source.get('rank')}"
                if source_id is not None:
                    source_label = f"{source_label} | id={source_id}"
                st.markdown(f"**{source_label}**")
                st.write(source.get("text", ""))

                display_metadata = {
                    key: value
                    for key, value in metadata.items()
                    if key not in VECTOR_SOURCE_TEXT_COLUMNS
                    and key not in {"id", "primary_key"}
                }
                if display_metadata:
                    st.json(display_metadata, expanded=False)
        displayed_content = True

    if results.get("source_warning"):
        with st.expander("Vector index source warning"):
            st.warning(results["source_warning"])

    if results.get("structured_answer"):
        with st.expander("Structured metadata answer"):
            st.markdown(results["structured_answer"])

    if results.get("synthesis_error"):
        with st.expander("Agent synthesis warning"):
            st.warning(results["synthesis_error"])

    if results.get("data_rows") and results.get("columns"):
        st.markdown("### Data")
        import pandas as pd
        df = pd.DataFrame(results["data_rows"], columns=results["columns"])
        st.dataframe(df, use_container_width=True, height=400)

        csv = df.to_csv(index=False)
        st.download_button(
            label="Download CSV",
            data=csv,
            file_name=f"bertopic_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv"
        )
        displayed_content = True
    elif results.get("row_count") == 0 and results.get("sql_query"):
        st.info("The generated SQL query returned 0 rows.")
        displayed_content = True

    if results.get("sql_query"):
        with st.expander("View generated SQL query"):
            st.code(results["sql_query"], language="sql")

    if results.get("suggested_questions"):
        st.markdown("### Suggested follow-ups")
        for question in results["suggested_questions"]:
            st.markdown(f"- {question}")
        displayed_content = True

    if results.get("query_result_error"):
        with st.expander("Show query result fetch warning"):
            st.json(results["query_result_error"])

    if not displayed_content:
        st.warning("Genie completed, but the response did not include displayable text or rows.")
        with st.expander("Show raw Genie response"):
            st.json(results.get("raw_result", {}))

    if response.get("conversation_id"):
        conversation_url = f"{DATABRICKS_HOST}/genie/rooms/{GENIE_SPACE_ID}?conversationId={response['conversation_id']}"
        st.markdown(f"[View full conversation in Genie]({conversation_url})")

# ============================================================================
# Streamlit UI
# ============================================================================

def main():
    st.set_page_config(
        page_title="Narrative Analysis",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Initialize session state
    if "selected_question" not in st.session_state:
        st.session_state.selected_question = ""
    if "query_history" not in st.session_state:
        st.session_state.query_history = []
    if "last_response" not in st.session_state:
        st.session_state.last_response = None
    if "last_results" not in st.session_state:
        st.session_state.last_results = None
    if "context_cache" not in st.session_state:
        st.session_state.context_cache = []
    if "agent_mode" not in st.session_state:
        st.session_state.agent_mode = DEFAULT_AGENT_MODE
    if st.session_state.agent_mode not in AGENT_MODE_LABELS:
        st.session_state.agent_mode = DEFAULT_AGENT_MODE
    if "rag_top_n" not in st.session_state:
        st.session_state.rag_top_n = VECTOR_SOURCE_NUM_RESULTS
    if "agent_llm_endpoint" not in st.session_state:
        st.session_state.agent_llm_endpoint = DEFAULT_AGENT_LLM_ENDPOINT
    if st.session_state.agent_llm_endpoint not in AGENT_LLM_OPTIONS:
        st.session_state.agent_llm_endpoint = DEFAULT_AGENT_LLM_ENDPOINT
    
    # Custom CSS
    st.markdown("""
        <style>
        .main-header {
            font-size: 2.5rem;
            font-weight: bold;
            color: #077A9D;
            margin-bottom: 0.5rem;
        }
        .sub-header {
            font-size: 1.2rem;
            color: #666;
            margin-bottom: 2rem;
        }
        .metric-card {
            background-color: #f0f2f6;
            padding: 1rem;
            border-radius: 8px;
            text-align: center;
        }
        .stButton>button {
            width: 100%;
        }
        .sample-btn {
            text-align: left;
            padding: 0.5rem;
            margin: 0.2rem 0;
        }
        </style>
    """, unsafe_allow_html=True)
    
    # Header
    st.markdown('<div class="main-header">🔍 Narrative Analysis</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Explore topics, narratives, and incitement patterns </div>', unsafe_allow_html=True)
    
    # Sidebar
    with st.sidebar:
        st.markdown("### 📊 Quick Links")
        st.markdown(f"🔗 [Open Dashboard]({DASHBOARD_URL})")
        st.markdown(f"🤖 [Open Genie Space]({GENIE_SPACE_URL})")
        
        st.markdown("---")
        
        # Data Summary
        st.markdown("### 📈 Data Summary")
        
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Messages", "5,433")
            st.metric("Topics", "12")
        with col2:
            st.metric("Models", "2")
            st.metric("Layers", "2")
        
        st.markdown("**Incitement Distribution:**")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Normal", "4,822", delta="88.7%", delta_color="off")
        with col2:
            st.metric("Abusive", "553", delta="10.2%", delta_color="off")
        with col3:
            st.metric("Incite", "58", delta="1.1%", delta_color="off")
        
        st.markdown("---")
        
        # Sample Questions
        st.markdown("### 💡 Sample Questions")
        
        selected_category = st.selectbox(
            "Choose a category:",
            list(SAMPLE_QUESTIONS.keys()),
            label_visibility="collapsed"
        )
        
        st.markdown("**Click to use:**")
        
        for idx, question in enumerate(SAMPLE_QUESTIONS[selected_category]):
            if st.button(
                f"💬 {question[:50]}{'...' if len(question) > 50 else ''}", 
                key=f"sample_{selected_category}_{idx}",
                help=question,
                use_container_width=True
            ):
                st.session_state.selected_question = question
                st.rerun()
        
        st.markdown("---")
        
        # Query History
        if st.session_state.query_history:
            st.markdown("### 📜 Recent Queries")
            for i, hist_q in enumerate(st.session_state.query_history[-3:]):
                if st.button(f"🔄 {hist_q[:40]}...", key=f"hist_{i}", use_container_width=True):
                    st.session_state.selected_question = hist_q
                    st.rerun()

        st.markdown("---")

        # Short-lived context cache for follow-up questions in this Streamlit session.
        st.markdown("### 🧠 Context")
        context_count = len(st.session_state.context_cache)
        context_label = "exchange" if context_count == 1 else "exchanges"
        st.caption(
            f"{context_count} recent {context_label} cached for follow-up questions."
        )
        if st.button(
            "Clear Context",
            key="clear_context",
            use_container_width=True,
            disabled=context_count == 0,
        ):
            st.session_state.context_cache = []
            st.rerun()
    
    # Main content area
    col1, col2 = st.columns([3, 1])
    
    with col1:
        st.markdown("### 🤔 Ask a Question")
        
        # Question input
        user_question = st.text_area(
            "Enter your question about the data:",
            value=st.session_state.selected_question,
            height=120,
            placeholder="e.g., What are the top narratives by message count?",
            label_visibility="collapsed"
        )
        
        col_btn1, col_btn2, col_btn3, col_btn4 = st.columns([2, 1, 1, 2])
        with col_btn1:
            submit_button = st.button("🚀 Ask Question", type="primary", use_container_width=True)
        with col_btn2:
            clear_button = st.button("🗑️ Clear", use_container_width=True)
        
        if clear_button:
            st.session_state.selected_question = ""
            st.session_state.last_response = None
            st.session_state.last_results = None
            st.rerun()
    
    with col2:
        st.markdown("### Agent Mode")
        st.radio(
            "Agent Mode",
            options=list(AGENT_MODE_LABELS.keys()),
            format_func=lambda mode: AGENT_MODE_LABELS[mode],
            key="agent_mode",
            label_visibility="collapsed",
            help=AGENT_MODE_HELP,
        )
        st.caption(AGENT_MODE_CAPTIONS[st.session_state.agent_mode])

        if st.session_state.agent_mode != AGENT_MODE_NO_RAG:
            st.selectbox(
                "Agent Model",
                options=list(AGENT_LLM_OPTIONS.keys()),
                format_func=lambda endpoint: AGENT_LLM_OPTIONS[endpoint],
                key="agent_llm_endpoint",
                help="Model serving endpoint used to synthesize Agent and Vector only answers.",
            )

            st.number_input(
                "RAG Top N",
                min_value=1,
                max_value=50,
                step=1,
                key="rag_top_n",
                help="Number of vector search snippets to retrieve.",
            )

        st.markdown("---")
        st.markdown("### ℹ️ Tips")
        st.info("""
        **Ask about:**
        - Topic counts & distributions
        - Incitement patterns
        - Sample texts
        - Hierarchies
        - Time ranges
        - Comparisons
        """)
    
    # Process question
    if submit_button and user_question:
        st.session_state.last_response = None
        st.session_state.last_results = None

        if user_question not in st.session_state.query_history:
            st.session_state.query_history.append(user_question)

        agent_mode = st.session_state.agent_mode
        rag_top_n = int(st.session_state.rag_top_n)
        agent_llm_endpoint = st.session_state.agent_llm_endpoint

        if agent_mode == AGENT_MODE_ONLY_VECTOR:
            auth_headers, auth_error = get_databricks_auth_headers()
            if auth_error:
                st.session_state.last_response = {
                    "error": f"Unable to authenticate: {auth_error}"
                }
            else:
                with st.spinner("🔄 Retrieving vector evidence and synthesizing answer..."):
                    source_lookup = query_vector_sources(user_question, rag_top_n)
                    source_documents = source_lookup.get("source_documents", [])
                    synthesis_response = synthesize_agent_answer(
                        question=user_question,
                        auth_headers=auth_headers,
                        structured_results=None,
                        source_documents=source_documents,
                        mode_label=AGENT_MODE_LABELS[agent_mode],
                        endpoint_name=agent_llm_endpoint,
                    )
                    response, results = build_agent_results(
                        question=user_question,
                        genie_response=None,
                        structured_results=None,
                        source_documents=source_documents,
                        source_warning=source_lookup.get("warning"),
                        synthesis_response=synthesis_response,
                    )
                    st.session_state.last_response = response
                    st.session_state.last_results = results
                    st.session_state.context_cache.append(
                        build_context_item(user_question, results)
                    )
                    st.session_state.context_cache = st.session_state.context_cache[
                        -CONTEXT_MAX_EXCHANGES:
                    ]
        else:
            auth_headers, auth_error = get_databricks_auth_headers()
            if auth_error:
                st.session_state.last_response = {
                    "error": f"Unable to authenticate: {auth_error}"
                }
            else:
                source_documents = []
                source_warning = None
                source_context = None
                spinner_text = "🔄 Querying Genie space..."

                if agent_mode == AGENT_MODE_WITH_RAG:
                    spinner_text = "🔄 Querying metadata, retrieving vector evidence, and synthesizing answer..."

                with st.spinner(spinner_text):
                    if agent_mode == AGENT_MODE_WITH_RAG:
                        source_lookup = query_vector_sources(user_question, rag_top_n)
                        source_documents = source_lookup.get("source_documents", [])
                        source_warning = source_lookup.get("warning")

                    response = query_genie_space(
                        question=user_question,
                        space_id=GENIE_SPACE_ID,
                        auth_headers=auth_headers,
                        host=DATABRICKS_HOST,
                        context_items=st.session_state.context_cache,
                        source_context=source_context,
                    )
                    response["source_documents"] = source_documents
                    response["source_warning"] = source_warning
                    st.session_state.last_response = response
                    if not response.get("error"):
                        results = extract_query_results(response)
                        if agent_mode == AGENT_MODE_WITH_RAG:
                            synthesis_response = synthesize_agent_answer(
                                question=user_question,
                                auth_headers=auth_headers,
                                structured_results=results,
                                source_documents=source_documents,
                                mode_label=AGENT_MODE_LABELS[agent_mode],
                                endpoint_name=agent_llm_endpoint,
                            )
                            response, results = build_agent_results(
                                question=user_question,
                                genie_response=response,
                                structured_results=results,
                                source_documents=source_documents,
                                source_warning=source_warning,
                                synthesis_response=synthesis_response,
                            )
                            st.session_state.last_response = response

                        st.session_state.last_results = results
                        st.session_state.context_cache.append(
                            build_context_item(user_question, results)
                        )
                        st.session_state.context_cache = st.session_state.context_cache[
                            -CONTEXT_MAX_EXCHANGES:
                        ]
    
    elif submit_button and not user_question:
        st.warning("⚠️ Please enter a question")

    if st.session_state.last_response:
        display_genie_response(
            st.session_state.last_response,
            st.session_state.last_results,
        )
    
    # Footer
    st.markdown("---")
    st.markdown("""
    <div style='text-align: center; color: #666; padding: 1rem;'>
        <p><strong>Powered by Databricks Genie</strong> | Analysis Dashboard</p>
        <p style='font-size: 0.85rem;'>📊 Data: amit.bertopic catalog | Two-layer recursion with incitement enrichment</p>
        <p style='font-size: 0.75rem; color: #999;'>Last updated: May 8, 2026</p>
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
    except ImportError:
        get_script_run_ctx = None

    # Databricks Apps may invoke the app as `python app.py`. Re-exec into
    # Streamlit so session state and the web server are initialized correctly.
    if get_script_run_ctx is None or get_script_run_ctx() is None:
        server_port = (
            os.getenv("DATABRICKS_APP_PORT")
            or os.getenv("STREAMLIT_SERVER_PORT")
            or "8080"
        )
        server_address = os.getenv("STREAMLIT_SERVER_ADDRESS") or "0.0.0.0"
        os.execvp(
            "streamlit",
            [
                "streamlit",
                "run",
                "app.py",
                f"--server.port={server_port}",
                f"--server.address={server_address}",
            ],
        )

    main()
