FROM python:3.11-slim

WORKDIR /app

# Create non-root user
RUN useradd -m -u 1000 mcpuser

# Install dependencies (copy project files needed for pip install)
COPY pyproject.toml .
COPY src/ ./src/
RUN pip install --no-cache-dir .

# Set ownership on source files
RUN chown -R mcpuser:mcpuser /app/src

# Create directories for data and cache
RUN mkdir -p /home/mcpuser/.obsidian-graph/cache && \
    chown -R mcpuser:mcpuser /home/mcpuser/.obsidian-graph

# Switch to non-root user
USER mcpuser

# Set Python path
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Default command - run MCP server
CMD ["python", "-m", "src.server"]
