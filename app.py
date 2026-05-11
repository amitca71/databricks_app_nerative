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

GENIE_SPACE_ID = "01f1455a882b1cd69cba447d909362d0"
DASHBOARD_URL = f"{DATABRICKS_HOST}/dashboardsv3/01f1425e745118cf87a3d81fdf2ee5a7/published"
GENIE_SPACE_URL = f"{DATABRICKS_HOST}/genie/rooms/{GENIE_SPACE_ID}"

ANSWER_INSTRUCTIONS = """
Answering instructions:
- Write for analysts, not engineers. Prefer interpretation, implications, and investigative takeaways over technical implementation details.
- Start with the main insight in plain language, then support it with the most relevant counts, percentages, comparisons, and examples.
- When results show a pattern, explain why it may matter and what an analyst should look at next.
- Call out caveats clearly, including small sample sizes, missing labels, zero-row results, ambiguous topic names, or filters such as execution_id/model/layer.
- Keep SQL mechanics, table names, and IDs secondary unless they are needed to verify or reproduce the finding.
- When presenting topics or narratives, never identify them only by ID. Include the topic title, name, description, or full_topic whenever available.
- If a topic ID is useful, show it alongside the human-readable name, not instead of it.
- If the data does not contain a human-readable topic name for a topic ID, say that explicitly.
- When asked about a narrative or nerative, discuss the related topic(s), incitement level or label, and include relevant example messages when available.
""".strip()

# ============================================================================
# Sample Questions
# ============================================================================

SAMPLE_QUESTIONS = {
    "Arena Readout": [
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

def get_databricks_auth_headers() -> tuple[dict, str | None]:
    """Return Databricks API auth headers for local dev or Databricks Apps."""
    token = os.getenv("DATABRICKS_TOKEN")
    if token:
        return {"Authorization": f"Bearer {token}"}, None

    if WorkspaceClient is None:
        return {}, "databricks-sdk is not installed in the app environment."

    try:
        client_id = os.getenv("DATABRICKS_CLIENT_ID")
        client_secret = os.getenv("DATABRICKS_CLIENT_SECRET")

        if client_id and client_secret:
            workspace = WorkspaceClient(
                host=DATABRICKS_HOST,
                client_id=client_id,
                client_secret=client_secret,
            )
        else:
            workspace = WorkspaceClient(host=DATABRICKS_HOST)

        headers = workspace.config.authenticate()
        if not headers.get("Authorization"):
            return {}, "Databricks SDK did not return an Authorization header."

        return headers, None
    except Exception as e:
        return {}, f"Databricks SDK authentication failed: {e}"


def query_genie_space(question: str, space_id: str, auth_headers: dict, host: str) -> dict:
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
    prompt = f"{ANSWER_INSTRUCTIONS}\n\nUser question:\n{question}"
    
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
        auth_headers, auth_error = get_databricks_auth_headers()
        if auth_error:
            st.session_state.last_response = {
                "error": f"Unable to authenticate: {auth_error}"
            }
        else:
            # Add to history
            if user_question not in st.session_state.query_history:
                st.session_state.query_history.append(user_question)
            
            with st.spinner("🔄 Querying Genie space..."):
                response = query_genie_space(
                    question=user_question,
                    space_id=GENIE_SPACE_ID,
                    auth_headers=auth_headers,
                    host=DATABRICKS_HOST
                )
                st.session_state.last_response = response
                if not response.get("error"):
                    st.session_state.last_results = extract_query_results(response)
    
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
