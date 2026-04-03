"""
Hub and orphan analysis for knowledge graph.

Identifies highly connected notes (hubs) and isolated notes (orphans)
using materialized connection_count statistics.
"""

import asyncio

from loguru import logger

from .vector_store import PostgreSQLVectorStore


class HubAnalyzer:
    """
    Analyzes note connectivity to find hubs and orphans.

    Uses materialized connection_count column for O(1) queries.

    Thread-Safety:
        - Uses asyncio.Lock for refresh operations
        - Multiple concurrent calls to get_hub_notes/get_orphaned_notes: safe
        - Only ONE vault refresh runs at a time (others wait for completion)

    Performance:
        - Refresh is O(N²) where N = number of notes
        - Triggered when >50% of notes have stale connection_count
        - Awaited inline so counts are fresh before queries return
    """

    def __init__(self, store: PostgreSQLVectorStore):
        """
        Initialize hub analyzer.

        Args:
            store: PostgreSQL vector store instance
        """
        self.store = store
        self._refresh_lock = asyncio.Lock()  # Replaces refresh_in_progress boolean

    async def get_hub_notes(
        self, min_connections: int = 10, threshold: float = 0.5, limit: int = 20
    ) -> list[dict]:
        """
        Find highly connected notes (hubs).

        Args:
            min_connections: Minimum connection count
            threshold: Similarity threshold used for counting
            limit: Max results (1-50)

        Returns:
            List of {path, title, connection_count}
        """
        if not self.store.pool:
            raise ValueError("Store not initialized")

        try:
            # Check if connection_count needs refresh
            await self._ensure_fresh_counts(threshold)

            # Query hubs
            async with self.store.pool.acquire() as conn:
                results = await conn.fetch(
                    """
                    SELECT path, title, connection_count
                    FROM notes
                    WHERE connection_count >= $1
                    ORDER BY connection_count DESC
                    LIMIT $2
                    """,
                    min_connections,
                    limit,
                )

            hubs = [
                {"path": r["path"], "title": r["title"], "connection_count": r["connection_count"]}
                for r in results
            ]

            logger.info(f"Found {len(hubs)} hub notes")
            return hubs

        except Exception as e:
            logger.error(f"Hub query failed: {e}")
            raise

    async def get_orphaned_notes(
        self, max_connections: int = 2, threshold: float = 0.5, limit: int = 20
    ) -> list[dict]:
        """
        Find isolated notes (orphans).

        Args:
            max_connections: Maximum connection count
            threshold: Similarity threshold used for counting
            limit: Max results (1-50)

        Returns:
            List of {path, title, connection_count, modified_at}
        """
        if not self.store.pool:
            raise ValueError("Store not initialized")

        try:
            # Check if connection_count needs refresh
            await self._ensure_fresh_counts(threshold)

            # Query orphans
            async with self.store.pool.acquire() as conn:
                results = await conn.fetch(
                    """
                    SELECT path, title, connection_count, modified_at
                    FROM notes
                    WHERE connection_count <= $1
                    ORDER BY connection_count ASC, modified_at DESC
                    LIMIT $2
                    """,
                    max_connections,
                    limit,
                )

            orphans = [
                {
                    "path": r["path"],
                    "title": r["title"],
                    "connection_count": r["connection_count"],
                    "modified_at": r["modified_at"].isoformat() if r["modified_at"] else None,
                }
                for r in results
            ]

            logger.info(f"Found {len(orphans)} orphaned notes")
            return orphans

        except Exception as e:
            logger.error(f"Orphan query failed: {e}")
            raise

    async def _ensure_fresh_counts(self, threshold: float):
        """
        Ensure connection counts are fresh before querying.

        Checks staleness and refreshes inline so counts are ready when callers query.
        All logic runs inside the lock to prevent TOCTOU races and duplicate refreshes.

        Thread-Safety:
            - Staleness check and refresh are atomic (both inside _refresh_lock)
            - Concurrent callers wait for the lock, then re-check staleness
            - No duplicate refreshes possible
        """
        try:
            async with self._refresh_lock:
                async with self.store.pool.acquire() as conn:
                    stale_count = await conn.fetchval(
                        "SELECT COUNT(*) FROM notes WHERE connection_count = 0"
                    )
                    total_count = await conn.fetchval("SELECT COUNT(*) FROM notes")

                    if total_count > 0 and stale_count / total_count > 0.5:
                        logger.info(
                            f"{stale_count}/{total_count} notes have stale counts, refreshing..."
                        )
                        await self._do_refresh(threshold)

        except Exception as e:
            logger.warning(f"Failed to check count freshness: {e}")

    async def _refresh_all_counts(self, threshold: float):
        """
        Refresh connection_count for all notes (acquires lock).

        Convenience wrapper that acquires _refresh_lock before refreshing.
        Prefer _do_refresh() when caller already holds the lock.
        """
        async with self._refresh_lock:
            await self._do_refresh(threshold)

    async def _do_refresh(self, threshold: float):
        """
        Refresh connection_count for all notes (caller must hold _refresh_lock).

        Uses batched SQL approach instead of O(N²) individual queries.
        Computes counts in batches to balance memory usage and performance.

        Args:
            threshold: Similarity threshold for counting connections

        Performance:
            - Processes notes in batches of 100 to avoid memory issues
            - Each batch uses a single SQL query with vector distance computation
            - Total complexity: O(N * B) where B = batch size, much better than O(N²)
        """
        logger.info("Starting connection count refresh...")

        try:
            distance_threshold = 1.0 - threshold
            batch_size = 100  # Process 100 notes at a time

            async with self.store.pool.acquire() as conn:
                # Get total count for progress logging
                total_notes = await conn.fetchval(
                    "SELECT COUNT(*) FROM notes WHERE embedding IS NOT NULL"
                )

                if total_notes == 0:
                    logger.info("No notes with embeddings to refresh")
                    return

                logger.info(f"Refreshing connection counts for {total_notes} notes...")

                # Process in batches using OFFSET/LIMIT
                processed = 0
                for offset in range(0, total_notes, batch_size):
                    # Get batch of note paths
                    batch_paths = await conn.fetch(
                        """
                        SELECT path FROM notes
                        WHERE embedding IS NOT NULL
                        ORDER BY path
                        LIMIT $1 OFFSET $2
                        """,
                        batch_size,
                        offset,
                    )

                    if not batch_paths:
                        break

                    # Update counts for this batch using a single efficient query
                    # Paths come from database (already validated on insertion), not user input
                    await conn.execute(
                        """
                        UPDATE notes AS n
                        SET connection_count = subq.cnt,
                            last_indexed_at = CURRENT_TIMESTAMP
                        FROM (
                            SELECT n1.path, COUNT(n2.path) AS cnt
                            FROM notes n1
                            LEFT JOIN notes n2 ON n1.path != n2.path
                                AND n2.embedding IS NOT NULL
                                AND (n1.embedding <=> n2.embedding) <= $1
                            WHERE n1.path = ANY($2::text[])
                                AND n1.embedding IS NOT NULL
                            GROUP BY n1.path
                        ) AS subq
                        WHERE n.path = subq.path
                        """,
                        distance_threshold,
                        [r["path"] for r in batch_paths],
                    )

                    processed += len(batch_paths)
                    if processed % 500 == 0 or processed == total_notes:
                        logger.debug(f"Refreshed {processed}/{total_notes} notes")

            logger.success(f"Connection count refresh complete ({total_notes} notes)")

        except Exception as e:
            logger.error(f"Connection count refresh failed: {e}")
