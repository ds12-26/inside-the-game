FROM python:3.13-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY matchmind matchmind
COPY data data
COPY runs runs
COPY web web

EXPOSE 8000
# The same image runs the web app (default) or the Match Data MCP server:
#   python -m matchmind.mcp_server --port 8001
CMD ["uvicorn", "matchmind.api:app", "--host", "0.0.0.0", "--port", "8000"]
