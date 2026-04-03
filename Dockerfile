FROM python:3.11-slim

WORKDIR /app

# Create non-root user
RUN useradd -m -u 1000 mcpuser

# Install dependencies from pyproject.toml (deps only, not the package itself)
COPY pyproject.toml .
RUN pip install --no-cache-dir $(python3 -c "import tomllib; print(' '.join(tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']))")

# Copy source code and set ownership
COPY --chown=mcpuser:mcpuser src/ ./src/

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
