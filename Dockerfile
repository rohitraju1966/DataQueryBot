FROM python:3.9-slim

# environment variables to ensure Streamlit runs in headless mode
ENV PYTHONUNBUFFERED=1
ENV STREAMLIT_SERVER_HEADLESS=true
ENV STREAMLIT_SERVER_ENABLECORS=false
ENV STREAMLIT_SERVER_PORT=8501

# switch to a directory for our app
WORKDIR /app

# Copy only requirements.txt first
COPY requirements.txt /app/

# Install system packages (if any) and Python dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       git \
    && pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y --auto-remove build-essential git \
    && rm -rf /var/lib/apt/lists/*

# Copy the rest of the application code into the container
COPY . /app

# Expose Streamlit’s default port
EXPOSE 8501

# By default, run Streamlit when the container starts
ENTRYPOINT ["streamlit", "run", "app.py", "--server.address=0.0.0.0"]


