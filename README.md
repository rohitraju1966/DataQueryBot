
# Per Diem DataQuery Chatbot

A Python-based chatbot allowing both Per Diem internal users and merchant users to interactively query sales and revenue data stored in a SQLite database. Users ask natural-language questions, which are converted into SQLite queries by an LLM, executed against a filtered (or full) dataset, and summarized back in plain English. A Streamlit frontend enables easy deployment and real-time interaction.

Application: https://dataquerybot-perdiem.streamlit.app/

---

## Table of Contents

1. [Features](#features)  
2. [Prerequisites](#prerequisites)  
3. [Repository Structure](#repository-structure)  
4. [Installation](#installation)  
5. [Data Preprocessing](#data-preprocessing)  
6. [Database Generation](#database-generation)  
7. [Running the Console Chatbot](#running-the-console-chatbot)  
8. [Running the Streamlit App](#running-the-streamlit-app)  
9. [Environment Variables](#environment-variables)  
10. [Examples](#examples)  
11. [Architecture](#architecture)
12. [DockerFile Run](#docker)

---

## Features

- **Natural-Language to SQL**  
  Uses an LLM (via the `groq` client) to convert user questions into valid SQLite queries, strictly following the schema of the `orders`, `customers`, and `stores` tables.

- **Contextual Memory**  
  Employs a `ConversationBufferMemory` (via LangChain) to maintain conversation context during a single session, allowing follow-up questions to rely on previous exchanges.

- **User Modes**  
  - **Per Diem Internal User**: Access to the full dataset across all stores.  
  - **Merchant**: Access limited to a single store’s data. When a merchant is chosen, the backend filters the database to include only that merchant’s records, ensuring no other store data is visible.

- **Streamlit Frontend**  
  A responsive web interface where users select their role (internal vs. merchant), optionally select their merchant from a dropdown, and then engage in a chat window to ask questions and view results in markdown tables.

- **Data Preprocessing Pipeline**  
  A reusable `DataPreprocessor` class in `preprocess.py` that:  
  1. Replaces problematic commas inside JSON-like fields in raw CSV files.  
  2. Re-assembles cleaned CSV files (`cleaned_orders.csv`, `cleaned_customers.csv`, `cleaned_stores.csv`).  
  3. Loads cleaned data into a SQLite database (`dashboard_chatbot.db`).  

---

## Prerequisites

- Python 3.8 or higher  
- Git  
- pip
- Groq API key to run locally

---

## Repository Structure

```
DataQueryBot/
├── README.md
├── app.py
├── main.py
├── preprocess.py
├── requirements.txt
├── Raw/
│   ├── orders_.csv
│   ├── customers_.csv
│   └── stores.csv
├── Processed/
│   ├── fixed_orders_*.csv
│   ├── fixed_customers_*.csv
│   ├── fixed_stores_*.csv
│   ├── cleaned_orders.csv
│   ├── cleaned_customers.csv
│   ├── cleaned_stores.csv
│   └── dashboard_chatbot.db
├── .gitignore
└── .env.example
```

---

## Installation

```bash
git clone https://github.com/your-username/DataQueryBot.git
cd DataQueryBot
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
```

---

## Data Preprocessing

Please make sure to add your stores, customers and orders CSV files to the Raw folder. 

The data is preprocessed using the preprocess.py file as follows, 
```bash
python preprocess.py
```


---

## Database Generation

After running the preprocessor, you'll get the following in the Processed folder:
- Cleaned CSVs
- SQLite database with `orders`, `customers`, and `stores` tables

---

## Running the Console Chatbot

```bash
python main.py
```

Set your `.env`:
```
GROQ_KEY=your_key
MERCHANT_NAME=""
IS_PER_DIEM=True
```

---

## Running the Streamlit App

Please make sure to set the Groq API key in your env file

```bash
streamlit run app.py
```

---

## Environment Variables

- `GROQ_KEY`  
- `MERCHANT_NAME`  
- `IS_PER_DIEM`

---

## Examples

### Internal User
You: Total revenue in march 2025?

Assistant:

Here is the answer:

The total revenue in March 2025 is $1,326,770.09.


### Merchant (Tikka Shack)
You: total revenue in march 2025?

Assistant:

Here is the result:

| total_revenue_in_dollars |
|--------------------------|
| 78020.08                 |

Insights: The total revenue in March 2025 for Tikka Shack is $78,020.08.

Since this is a significant revenue, a potential opportunity is to increase sales further. A marketing promotion could be: "Offer a 10% discount on all orders above $100 in April 2025 to maintain the sales momentum."

---


## Architecture

## Flowchart

![Architecture_diagram](Architecture_Bot.png)

### main.py Architecture

The `main.py` file handles the backend logic of the chatbot and follows this flow:

1. **Environment Setup**: Loads environment variables to determine user mode (Per Diem internal user vs. merchant). Depending on the mode, it connects to either the full or a filtered SQLite database.

2. **Database Connection**: Uses SQLAlchemy to connect to `dashboard_chatbot.db` or a store-specific filtered version.

3. **LLM Initialization**: Sets up the Groq client and the LLM model used for query generation, query correction and summarization.

4. **Prompt Templates**:
   - **Query Generation Prompt**: Converts natural language to SQL using schema-aware context.
   - **Query Error Correction Prompt loop**: Converts natural language to SQL when the previous attempt fails (tries for three attempts). 
   - **Summarization Prompt**: Translates SQL output into human-readable insights with markdown tables.
    
5. **Chat Loop**:
   - Accepts user input.
   - Uses LLM to convert input to SQL.
   - Executes SQL against the database.
   - If the query fails, attempts recovery using the correction prompt.
   - Feeds result + conversation memory back to the LLM for summarization.
   - Displays insights.

This separation of concerns ensures the model can flexibly support follow-up questions while maintaining safe access to merchant-specific data only.


---

## Docker

1. **Build the Docker image** (from project root, where `Dockerfile` lives):  
   ```bash
   docker build -t dataquerybot:latest .
   ```
2. Run container locally, forwarding port 8501 and loading environment vars:
   
   Please make sure to set the Groq API key in your env file

   ```bash
   docker run -d \ -p 8501:8501 \ --env-file .env \ --name dataquerybot \ dataquerybot:latest```
4. Verify and visit http://localhost:8501 in your browser.

