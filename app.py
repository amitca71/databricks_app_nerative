import streamlit as st
import requests
import json
import time
from datetime import datetime

# ============================================================================
# Configuration - Databricks Apps automatically provides authentication
# ============================================================================

# Get Databricks context (automatically available in Databricks Apps)
try:
    from databricks.sdk.runtime import dbutils
    DATABRICKS_HOST = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiUrl().get()
    DATABRICKS_TOKEN = dbutils.notebook.entry_point.getDbutils().notebook().getContext().apiToken().get()
except:
    # Fallback for local development
    import os
    DATABRICKS_HOST = os.getenv("DATABRICKS_HOST", "https://dbc-de54b796-a6c4.cloud.databricks.com")
    DATABRICKS_TOKEN = os.getenv("DATABRICKS_TOKEN", "")

GENIE_SPACE_ID = "01f1455a882b1cd69cba447d909362d0"
DASHBOARD_URL = f"{DATABRICKS_HOST}/dashboardsv3/01f1425e745118cf87a3d81fdf2ee5a7/published"
GENIE_SPACE_URL = f"{DATABRICKS_HOST}/genie/rooms/{GENIE_SPACE_ID}"

# ============================================================================
# Sample Questions
# ============================================================================

SAMPLE_QUESTIONS = {
    "📊 Topic Overview": [
        "What are the top 10 narratives by message count?",
        "Show me the distribution of messages across all topics",
        "Which topics have the most messages?",
        "What are all the topic descriptions and their scores?",
        "List all available topics with their full names"
    ],
    "⚠️ Incitement Analysis": [
        "Show me all messages labeled as incitement",
        "Which topics have the highest proportion of abusive content?",
        "What's the distribution of incitement labels across all topics?",
        "How many messages are normal vs abusive vs incitement?",
        "Show me the top 5 topics with the most abusive messages",
        "What percentage of messages in each topic are abusive?"
    ],
    "📝 Content Exploration": [
        "Show me sample texts from topic 0_0",
        "What are some example messages from the incitement category?",
        "Show me 10 random translated messages with their topics",
        "Give me examples of normal messages from the top topic",
        "Show me the longest messages in the dataset"
    ],
    "🔍 Metadata & Execution": [
        "What execution IDs are available in the data?",
        "How many messages are in each layer of the topic hierarchy?",
        "What models were used in the analysis?",
        "What is the date range of the data?",
        "Show me topic hierarchy with father topics",
        "How many topics are in layer 0 vs layer 1?"
    ],
    "📈 Cross-Analysis": [
        "Compare incitement rates between layer 0 and layer 1 topics",
        "Which parent topics (father_topic) have the most child topics?",
        "Show me topics with more than 100 messages and their incitement breakdown",
        "What's the average message count per topic by layer?",
        "Which topics have the highest incitement to normal ratio?"
    ]
}

# ============================================================================
# Databricks Genie API Functions
# ============================================================================

def query_genie_space(question: str, space_id: str, token: str, host: str) -> dict:
    """
    Query a Databricks Genie space with a natural language question.
    
    Args:
        question: Natural language question to ask
        space_id: Genie space ID
        token: Databricks personal access token
        host: Databricks workspace URL
    
    Returns:
        Dictionary containing the response
    """
    conversation_url = f"{host}/api/2.0/genie/spaces/{space_id}/start-conversation"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    try:
        # Start conversation
        response = requests.post(
            conversation_url,
            headers=headers,
            json={"content": question},
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
        
        max_attempts = 60  # 2 minutes max
        for attempt in range(max_attempts):
            result_response = requests.get(result_url, headers=headers, timeout=30)
            result_response.raise_for_status()
            result_data = result_response.json()
            
            status = result_data.get("status")
            
            if status == "COMPLETED":
                return {
                    "success": True,
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
        "text_response": result.get("content", ""),
        "sql_query": None,
        "data_rows": [],
        "columns": [],
        "chart_spec": None,
        "error": None
    }
    
    # Extract SQL, data, and visualizations from attachments
    for attachment in attachments:
        attachment_type = attachment.get("type")
        
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
    
    return formatted_results

# ============================================================================
# Streamlit UI
# ============================================================================

def main():
    st.set_page_config(
        page_title="BERTopic Narrative Analysis",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Initialize session state
    if "selected_question" not in st.session_state:
        st.session_state.selected_question = ""
    if "query_history" not in st.session_state:
        st.session_state.query_history = []
    
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
    st.markdown('<div class="main-header">🔍 BERTopic Narrative Analysis</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Explore topics, narratives, and incitement patterns from your BERTopic analysis</div>', unsafe_allow_html=True)
    
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
            "Enter your question about the BERTopic data:",
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
        if not DATABRICKS_TOKEN:
            st.error("❌ Unable to authenticate. Please ensure the app has proper permissions.")
        else:
            # Add to history
            if user_question not in st.session_state.query_history:
                st.session_state.query_history.append(user_question)
            
            with st.spinner("🔄 Querying Genie space..."):
                response = query_genie_space(
                    question=user_question,
                    space_id=GENIE_SPACE_ID,
                    token=DATABRICKS_TOKEN,
                    host=DATABRICKS_HOST
                )
                
                if response.get("error"):
                    st.error(f"❌ Error: {response['error']}")
                    if response.get("details"):
                        with st.expander("🔍 Show error details"):
                            st.json(response["details"])
                else:
                    results = extract_query_results(response)
                    
                    # Display results
                    st.markdown("---")
                    st.markdown("## 📊 Results")
                    
                    # Text response
                    if results.get("text_response"):
                        st.markdown("### 💬 Answer")
                        st.markdown(results["text_response"])
                    
                    # Data table
                    if results.get("data_rows") and results.get("columns"):
                        st.markdown("### �� Data")
                        import pandas as pd
                        df = pd.DataFrame(results["data_rows"], columns=results["columns"])
                        st.dataframe(df, use_container_width=True, height=400)
                        
                        # Download button
                        csv = df.to_csv(index=False)
                        st.download_button(
                            label="📥 Download CSV",
                            data=csv,
                            file_name=f"bertopic_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                            mime="text/csv"
                        )
                    
                    # SQL Query
                    if results.get("sql_query"):
                        with st.expander("�� View Generated SQL Query"):
                            st.code(results["sql_query"], language="sql")
                    
                    # Conversation link
                    if response.get("conversation_id"):
                        conversation_url = f"{DATABRICKS_HOST}/genie/rooms/{GENIE_SPACE_ID}?conversationId={response['conversation_id']}"
                        st.markdown(f"🔗 [View full conversation in Genie]({conversation_url})")
    
    elif submit_button and not user_question:
        st.warning("⚠️ Please enter a question")
    
    # Footer
    st.markdown("---")
    st.markdown("""
    <div style='text-align: center; color: #666; padding: 1rem;'>
        <p><strong>Powered by Databricks Genie</strong> | BERTopic Analysis Dashboard</p>
        <p style='font-size: 0.85rem;'>📊 Data: amit.bertopic catalog | Two-layer recursion with incitement enrichment</p>
        <p style='font-size: 0.75rem; color: #999;'>Last updated: May 8, 2026</p>
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
