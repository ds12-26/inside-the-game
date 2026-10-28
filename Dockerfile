FROM python:3.13-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY matchmind matchmind
COPY data data
COPY web web

EXPOSE 8000 8001
# The same image runs the web app (default) or, with APP_ROLE=mcp, the Match Data MCP server.
CMD ["sh", "-c", "if [ \"$APP_ROLE\" = mcp ]; then exec python -m matchmind.mcp.server --port 8001; else exec uvicorn matchmind.render.api:app --host 0.0.0.0 --port 8000; fi"]
