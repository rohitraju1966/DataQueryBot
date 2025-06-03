# app.py

import os
import re
import streamlit as st
import pandas as pd
from sqlalchemy import create_engine
from langchain.memory import ConversationBufferMemory
from dotenv import load_dotenv

# Load environment variables (GROQ_KEY, MERCHANT_NAME, IS_PER_DIEM)
load_dotenv()

# Import backend functions and memory placeholder from main.py
import main
from main import nl_to_sql, fix_sql_with_error, summarize_result

st.set_page_config(page_title="Per Diem DataQuery Chatbot")

# Load merchant names from CSV (cached)
@st.cache_data
def load_merchant_names():
    df = pd.read_csv("Processed/cleaned_stores.csv")
    return sorted(df["name"].unique().tolist())

merchant_names = load_merchant_names()

# Initialize session state variables
if "current_mode" not in st.session_state:
    # Will hold either "internal" or "merchant:<store_name>"
    st.session_state.current_mode = None

if "engine" not in st.session_state:
    st.session_state.engine = None

if "context_str" not in st.session_state:
    st.session_state.context_str = ""

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if "memories" not in st.session_state:
    # A dict of mode → ConversationBufferMemory
    st.session_state.memories = {}

# Sidebar: select user type and, if merchant, choose merchant name
st.sidebar.title("User Selection")
user_type = st.sidebar.radio("I am a:", ["PerDiem Internal User", "Merchant"])

if user_type == "Merchant":
    selected_merchant = st.sidebar.selectbox("Choose your merchant:", [""] + merchant_names)
    is_per_diem = False
    mode = f"merchant:{selected_merchant}" if selected_merchant else None
else:
    selected_merchant = ""
    is_per_diem = True
    mode = "internal"

# When the mode changes, reset engine, context, chat history, and memory
if mode != st.session_state.current_mode:
    st.session_state.current_mode = mode
    st.session_state.chat_history = []
    if mode:
        st.session_state.memories[mode] = ConversationBufferMemory(return_messages=True)

# Helper to get the current memory object (or None if no mode selected)
def get_current_memory():
    return st.session_state.memories.get(st.session_state.current_mode)

# Function to initialize or filter database based on merchant
def initialize_database(merchant_name: str, is_per_diem_user: bool):
    original_db = "Processed/dashboard_chatbot.db"
    if merchant_name:
        engine_full = create_engine(f"sqlite:///{original_db}")
        stores_df = pd.read_sql_query(
            "SELECT * FROM stores WHERE name = ? LIMIT 1",
            engine_full,
            params=(merchant_name,)
        )
        if stores_df.empty:
            st.error(f"No store found with name '{merchant_name}'")
            return None, ""
        store_id = stores_df.iloc[0]["store_id"]

        orders_df = pd.read_sql_query(
            "SELECT * FROM orders WHERE store_id = ?",
            engine_full,
            params=(store_id,)
        )
        customers_df = pd.read_sql_query(
            "SELECT * FROM customers WHERE store_id = ?",
            engine_full,
            params=(store_id,)
        )

        filtered_db = "Processed/filtered_dashboard_chatbot.db"
        if os.path.exists(filtered_db):
            os.remove(filtered_db)
        engine_filtered = create_engine(f"sqlite:///{filtered_db}")
        stores_df.to_sql("stores", engine_filtered, index=False)
        orders_df.to_sql("orders", engine_filtered, index=False)
        customers_df.to_sql("customers", engine_filtered, index=False)

        context = f"Serving for merchant: {merchant_name}"
        return create_engine(f"sqlite:///{filtered_db}"), context

    else:
        context = "Serving for PerDiem internal user"
        return create_engine(f"sqlite:///{original_db}"), context

# Reinitialize the database engine and context string whenever mode changes
if st.session_state.current_mode:
    if st.session_state.current_mode == "internal":
        st.session_state.engine, st.session_state.context_str = initialize_database("", True)
    else:
        merchant_name = st.session_state.current_mode.split("merchant:")[1]
        if merchant_name:
            st.session_state.engine, st.session_state.context_str = initialize_database(merchant_name, False)
        else:
            st.session_state.engine = None
            st.session_state.context_str = ""

# Title and context display
st.title("Per Diem DataQuery Chatbot")
if st.session_state.context_str:
    st.markdown(f"**{st.session_state.context_str}**")

# Display chat history: user and assistant entries
for entry in st.session_state.chat_history:
    if entry["role"] == "user":
        st.markdown(f"**You:** {entry['content']}")
    else:
        st.markdown("**Assistant:**")
        st.markdown(entry["content"])


def process_query():
    question = st.session_state.input_text.strip()
    if not question or not st.session_state.current_mode:
        return

    # Append user message
    st.session_state.chat_history.append({"role": "user", "content": question})

    # Ensure backend uses the correct memory for both nl_to_sql and fix_sql_with_error
    main.memory = get_current_memory()

    # Attempt up to 5 times: generate SQL → execute → fix if needed
    generated_sql = nl_to_sql(question, st.session_state.context_str)
    if generated_sql.startswith("--ERROR"):
        # If nl_to_sql itself failed, skip retries
        error_msg = generated_sql
        df_result = None
    else:
        df_result = None
        error_msg = None
        MAX_RETRIES = 3
        attempt = 0

        while attempt < MAX_RETRIES:
            try:
                df_result = pd.read_sql_query(generated_sql, st.session_state.engine)
                error_msg = None
                break  # Success, exit retry loop
            except Exception as e:
                error_msg = str(e)
                attempt += 1
                # Generate a corrected SQL using memory + context
                corrected_sql = fix_sql_with_error(
                    question,
                    generated_sql,
                    error_msg,
                    st.session_state.context_str
                )
                if corrected_sql.startswith("--ERROR"):
                    # If correction itself failed, stop retrying
                    break
                generated_sql = corrected_sql

        # If after retries we still have an error, df_result remains None

    # Summarize results or error via LLM
    response = summarize_result(
        question,
        generated_sql,
        df_result,
        error_msg,
        st.session_state.context_str
    )

    # Clean up spacing in the response
    response = re.sub(r"\.([A-Z])", r". \1", response)
    response = re.sub(r"([a-z])([A-Z])", r"\1 \2", response)
    response = re.sub(r"([A-Za-z])(\d)", r"\1 \2", response)

    # Append assistant response
    st.session_state.chat_history.append({"role": "assistant", "content": response})

    # Clear the input box
    st.session_state.input_text = ""

# Single-line text_input with on_change callback
st.text_input(
    "Your question:",
    key="input_text",
    on_change=process_query,
    placeholder="Type a question and press Enter"
)
