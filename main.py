#Required libraries
import os
from sqlalchemy import create_engine
import pandas as pd
from groq import Groq
from langchain.memory import ConversationBufferMemory


# Schema description for SQLite. Used by the SQL‐generation LLM prompt.
SCHEMA_DESCRIPTION = """
(Note: Text in parentheses indicates “column_name (TYPE, brief‐description)”)

Use **SQLite** syntax only. Do not use any MySQL‐specific functions
such as `DATE_SUB`, `CURDATE()`, `DATE_FORMAT`. Instead, use
`DATE('now', '-X days')`, `DATE('now')`, `strftime(…)`, etc.

Tables:
orders(
    order_id (UUID, primary key),
    store_id (UUID, foreign key → stores.store_id),
    customer_id (UUID, foreign key → customers.customer_id),
    external_location_id (STRING, external system’s location identifier),
    external_order_id (STRING, external system’s order identifier),
    total_amount_in_cents (INTEGER, total order value),
    discount_amount_in_cents (INTEGER, discount applied),
    delivery_fee_in_cents (INTEGER, fee charged for delivery),
    created_at (DATETIME, order creation timestamp),
    updated_at (DATETIME, last update timestamp),
    fulfillment_type (ENUM: “pickup”|“delivery”|“curbside”),
    tip_amount_in_cents (INTEGER, tip given by customer),
    service_fee_in_cents (INTEGER, platform service fee),
    subscription_discounts_metadata (JSON, subscription discount details),
    notes (STRING, free‐text notes on order),
    delivery_info (JSON, delivery details like addresses/times),
    risk_level (INTEGER, fraud risk score: 0 = low, 1 = high),
    order_type (ENUM: “regular_checkout”|“store_credit_reload”|“gift_card”|“subscription_purchase”),
    perdiem_platform_fee_in_cents (INTEGER, PerDiem’s platform fee),
    scheduled_fulfillment_at (DATETIME, scheduled pickup/delivery time)
)
customers(
    customer_id (UUID, primary key),
    store_id (UUID, foreign key → stores.store_id),
    external_customer_id (STRING, external system’s customer ID)
)
stores(
    store_id (UUID, primary key),
    external_store_id (STRING, external system’s store ID),
    name (STRING, store name),
    active (BOOLEAN, store status),
    created_at (DATETIME, store record creation),
    updated_at (DATETIME, store record last update),
    delivery_fee (JSON, store’s base delivery fee settings),
    platform_fee (JSON, store’s platform fee settings),
    consumer_fee (JSON, consumer‐facing fees),
    pre_sale (JSON, whether scheduled orders are allowed)
)
"""


# Few‐shot prompt examples for converting natural‐language to SQL.
FEW_SHOT_SQL_PROMPT = [
    {
        "role": "system",
        "content": (
            f"{SCHEMA_DESCRIPTION}\n"
            "Convert the user’s natural language request into a valid SQL query for this schema. "
            "**Using SQLite syntax only.** Return only one SQL statement (no extra commentary)."
        )
    },
    # Example: compare week1 vs week2 for a store
    {
        "role": "user",
        "content": "Compare the number of orders between March 1–7 and March 8–14, 2025 for store 'Migos Fine Foods'."
    },
    {
        "role": "assistant",
        "content": (
            "SELECT\n"
            "  SUM(CASE WHEN DATE(o.created_at) BETWEEN '2025-03-01' AND '2025-03-07' THEN 1 ELSE 0 END) AS week1_count,\n"
            "  SUM(CASE WHEN DATE(o.created_at) BETWEEN '2025-03-08' AND '2025-03-14' THEN 1 ELSE 0 END) AS week2_count\n"
            "FROM orders AS o\n"
            "JOIN stores AS s ON o.store_id = s.store_id\n"
            "WHERE s.name = 'Migos Fine Foods';"
        )
    },
    # Example: total revenue for Q1 2025
    {
        "role": "user",
        "content": "Total revenue (in dollars) for 'Migos Fine Foods' from January 1 to March 31, 2025?"
    },
    {
        "role": "assistant",
        "content": (
            "SELECT\n"
            "  ROUND(SUM(o.total_amount_in_cents) / 100.0, 2) AS total_revenue_in_cents\n"
            "FROM orders AS o\n"
            "JOIN stores AS s ON o.store_id = s.store_id\n"
            "WHERE s.name = 'Migos Fine Foods'\n"
            "  AND DATE(o.created_at) BETWEEN '2025-01-01' AND '2025-03-31';"
        )
    },
    # Example: count pickup orders for a specific week
    {
        "role": "user",
        "content": "How many pickup orders did 'Migos Fine Foods' have between March 15 and March 21, 2025?"
    },
    {
        "role": "assistant",
        "content": (
            "SELECT\n"
            "  COUNT(*) AS pickup_orders_week\n"
            "FROM orders AS o\n"
            "JOIN stores AS s ON o.store_id = s.store_id\n"
            "WHERE s.name = 'Migos Fine Foods'\n"
            "  AND o.fulfillment_type = 'pickup'\n"
            "  AND DATE(o.created_at) BETWEEN '2025-03-15' AND '2025-03-21';"
        )
    }
]

# Initialize the Groq client with the environment variable key
api_key = os.getenv("GROQ_KEY")
client = Groq(api_key=api_key)


# Sends a natural‐language query to the LLM with few‐shot context and returns the generated SQLite query.
# We now prepend a context line ("Context: merchant_name or PerDiem internal user") to every prompt.
def nl_to_sql(query: str, context_str: str) -> str:
    messages = FEW_SHOT_SQL_PROMPT + [
        {"role": "user", "content": f"Context: {context_str}"},
        {"role": "user", "content": query}
    ]
    response = client.chat.completions.create(
        model="llama3-70b-8192",
        messages=messages,
        temperature=0.0,
        max_tokens=256
    )
    return response.choices[0].message.content.strip()


# If the initial SQL fails on SQLite, this function builds a prompt containing the user’s question,
# the bad SQL, the error message, and the same context line so the LLM can generate a corrected SQL.
def fix_sql_with_error(question: str, bad_sql: str, error_msg: str, context_str: str) -> str:
    fix_prompt = [
        {
            "role": "system",
            "content": (
                f"{SCHEMA_DESCRIPTION}\n"
                "One of your previously generated SQL statements failed on SQLite with an error. "
                "Below is the user’s original question, the SQL you provided, the SQLite error message, "
                "and the context (merchant or PerDiem internal user). "
                "Please correct the SQL to be valid SQLite syntax and satisfy the original request. "
                "Return only the corrected SQL statement (no commentary)."
            )
        },
        {"role": "user", "content": f"Context: {context_str}"},
        {
            "role": "user",
            "content": (
                f"User question: {question}\n"
                f"Bad SQL: {bad_sql}\n"
                f"SQLite error: {error_msg}"
            )
        }
    ]
    response = client.chat.completions.create(
        model="llama3-70b-8192",
        messages=fix_prompt,
        temperature=0.0,
        max_tokens=256
    )
    return response.choices[0].message.content.strip()


# Few‐shot prompt examples for summarizing the SQL result.
FEW_SHOT_SUMMARY_PROMPT = [
    {
    "role": "system",
    "content": (
        "You are given:\n"
        "• The user’s original question\n"
        "• The final SQL query that was executed\n"
        "• The resulting table (or an error message)\n"
        "• The conversation memory so far\n\n"
        "Instructions:\n"
        "1. Use both the SQL‐extracted table and conversation history to draw your insights and answer the question.\n"
        "2. If relevant, incorporate any context from the conversation memory to clarify or enrich your analysis, but do not let memory override the concrete numbers in the table.\n"
        "3. If the result has multiple rows, include a small markdown‐style table showing those rows.\n"
        "4. Immediately below that table, draw one or two brief insights with precise numbers (in dollars, not cents).\n"
        "5. If those insights suggest an opportunity (e.g., a drop in pickup orders, or one store vastly outperforming others), then propose a specific marketing promotion. DO NOT SUGGEST A MARKETING STRATEGY UNLESS IT FOLLOWS DIRECTLY FROM THE INSIGHTS.\n"
        "6. Otherwise, skip any marketing suggestion.\n"
        "7. Always use only the rows shown—do not add, infer, or omit values.\n"
        "8. If there is an error or no rows, first consult the conversation memory to try to answer the question. If you still cannot provide an answer, reply exactly:\n"
        "   “I’m sorry, I couldn’t retrieve an answer—please rephrase or check the data.”\n"
        "9. If the single row is 0, reply exactly:\n"
        "   “It seems there are zero matching records—please verify your question.”\n"
        "10. Otherwise, for a single non‐zero row, answer in one sentence (no table needed) and only add a marketing idea if it follows logically from the insight."
         "**Any column or anwer representing money (e.g., fields labeled “march_sales”/“total_revenue”) is in cents—always divide those values by 100.0 to convert to dollars before displaying and refer to amounts in dollars.**\n"
    )
    },
    {
        "role": "user",
        "content": "User question: How many months data of orders do I have? and what are those months?"
    },
    {
        "role": "assistant",
        "content": "There are two months with order data: 2025-03 and 2025-04. So the user has data for March 2025 and April 2025."
    }
]

# Instantiate memory once per chatbot session.
memory = ConversationBufferMemory(return_messages=True)



# ----------------------------------------------------------------------
# Function: summarize_result
#
# - Builds the “result_content” string depending on df or error.
# - Loads conversation memory and includes it in the prompt.
# - Calls LLM to generate a summary (or marketing idea).
# - Saves the Q→A pair into memory for future context.
#
# We prepend the same context line here as well.
# ----------------------------------------------------------------------
def summarize_result(question: str, sql_query: str, df: pd.DataFrame = None, error_msg: str = None, context_str: str = "") -> str:
    # Build result_content from DataFrame or error
    if error_msg:
        result_content = f"Error executing SQL: {error_msg}"
    elif df is None or df.empty:
        result_content = "Result: no rows returned."
    else:
        table_text = df.to_csv(index=False)
        if df.shape == (1, 1) and str(df.iat[0, 0]) in ("0", "0.0"):
            result_content = "Result: single value 0"
        else:
            result_content = f"Result Table:\n{table_text}"

    # Load past conversation history from memory
    history_str = memory.load_memory_variables({})["history"]

    # Combine few‐shot prompt, memory, context, and current inputs
    messages = FEW_SHOT_SUMMARY_PROMPT + [
        {"role": "user", "content": f"Context: {context_str}"},
        {
            "role": "user",
            "content": (
                f"Conversation memory so far: {history_str}\n"
                f"User question: {question}\n"
                f"SQL Query: {sql_query}\n"
                f"{result_content}"
            )
        }
    ]

    # Call LLM for summary/insight/marketing suggestion
    response = client.chat.completions.create(
        model="llama3-70b-8192",
        messages=messages,
        temperature=0.0,
        max_tokens=256
    )
    summary = response.choices[0].message.content.strip()

    # Save this question/summary pair into memory for future turns
    memory.save_context({"user": question}, {"assistant": summary})
    return summary

# ----------------------------------------------------------------------
# main(): Launches a console‐based chatbot loop.
# - Connects to SQLite database.
# - Repeatedly reads user input, generates SQL, executes or fixes errors.
# - Calls summarize_result to produce the final answer.
# - Keeps memory alive until session ends.
# ----------------------------------------------------------------------
def main(merchant_name: str, is_per_diem: bool):
    # If merchant_name is provided, build a filtered database containing only that store's data
    original_db_path = "Processed/dashboard_chatbot.db"
    if merchant_name:
        # Load the original database into pandas DataFrames
        original_engine = create_engine(f"sqlite:///{original_db_path}")
        stores_df = pd.read_sql_query("SELECT * FROM stores WHERE name = ?", original_engine, params=(merchant_name,))
        if stores_df.empty:
            raise RuntimeError(f"No store found with name '{merchant_name}'")
        store_id = stores_df.iloc[0]["store_id"]

        # Filter orders and customers tables by store_id
        orders_df = pd.read_sql_query("SELECT * FROM orders WHERE store_id = ?", original_engine, params=(store_id,))
        customers_df = pd.read_sql_query("SELECT * FROM customers WHERE store_id = ?", original_engine, params=(store_id,))

        # Write these filtered tables to a new SQLite file
        filtered_db_path = "Processed/filtered_dashboard_chatbot.db"
        if os.path.exists(filtered_db_path):
            os.remove(filtered_db_path)
        filtered_engine = create_engine(f"sqlite:///{filtered_db_path}")
        stores_df.to_sql("stores", filtered_engine, index=False)
        orders_df.to_sql("orders", filtered_engine, index=False)
        customers_df.to_sql("customers", filtered_engine, index=False)

        engine = create_engine(f"sqlite:///{filtered_db_path}")
        context_str = f"Serving for merchant: {merchant_name}"
    else:
        # Per Diem user: use the full original database
        engine = create_engine(f"sqlite:///{original_db_path}")
        context_str = "Serving for PerDiem internal user"

    print("Chatbot is running. Type your question or 'exit' to quit.")
    while True:
        user_question = input("\nYou: ").strip()
        if not user_question or user_question.lower() == "exit":
            print("Goodbye!")
            break

        # Generate raw SQL from user question, including context
        generated_sql = nl_to_sql(user_question, context_str)

        try:
            # Try executing the SQL directly against the chosen engine
            df_result = pd.read_sql_query(generated_sql, engine)
            error_msg = None
        except Exception as e:
            # If it fails, ask LLM to fix the SQL
            error_msg = str(e)
            corrected_sql = fix_sql_with_error(user_question, generated_sql, error_msg, context_str)
            try:
                df_result = pd.read_sql_query(corrected_sql, engine)
                error_msg = None
                generated_sql = corrected_sql
            except Exception as e2:
                error_msg = str(e2)
                df_result = None

        # Summarize results (or error), passing context
        summary = summarize_result(user_question, generated_sql, df_result, error_msg, context_str)
        print(f"\nAssistant: {summary}")

if __name__ == "__main__":
    # Pass merchant_name AND set is_per_diem=False for a merchant
    # Pass merchant_name="" AND is_per_diem=True for a Per Diem internal user
    merchant_name = os.getenv("MERCHANT_NAME", "")
    is_per_diem = os.getenv("IS_PER_DIEM", "False").lower() == "true"
    main(merchant_name, is_per_diem)
