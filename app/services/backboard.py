"""Backboard.io client wrapper service for CloserNotes.

Uses the async context manager pattern for each API call, matching the
working pattern from bb_browser.
"""

import asyncio
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator

from backboard import BackboardClient

from app.config import get_settings


def _ensure_string_id(obj: Any, *attrs: str) -> Any:
    """Ensure specified attributes are strings (convert UUIDs if needed)."""
    for attr in attrs:
        if hasattr(obj, attr):
            val = getattr(obj, attr)
            if val is not None and not isinstance(val, str):
                setattr(obj, attr, str(val))
    return obj


class BackboardService:
    """Wrapper around BackboardClient with helper methods for CloserNotes.
    
    Uses async context manager pattern for each API call to ensure proper
    connection handling.
    """

    def __init__(self, api_key: str | None = None):
        """Initialize the Backboard service.

        Args:
            api_key: Backboard API key. If not provided, reads from settings.
        """
        settings = get_settings()
        self._api_key = api_key or settings.backboard_api_key
        self._default_provider = settings.default_llm_provider
        self._default_model = settings.default_model

    def _run_async(self, coro):
        """Run async coroutine in sync context."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                return asyncio.run(coro)
            return loop.run_until_complete(coro)
        except RuntimeError:
            return asyncio.run(coro)

    # Assistant operations
    async def create_assistant(
        self,
        name: str,
        system_prompt: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Create a new assistant.

        Args:
            name: Assistant name
            system_prompt: System prompt for the assistant
            tools: Optional list of tool definitions

        Returns:
            Created assistant object with assistant_id
        """
        async with BackboardClient(api_key=self._api_key) as client:
            # SDK uses 'description' parameter for system prompts
            kwargs = {
                "name": name,
                "description": system_prompt,
            }
            if tools:
                kwargs["tools"] = tools
            result = await client.create_assistant(**kwargs)
            return _ensure_string_id(result, "assistant_id")

    async def get_assistant(self, assistant_id: str) -> dict[str, Any]:
        """Get an assistant by ID."""
        async with BackboardClient(api_key=self._api_key) as client:
            return await client.get_assistant(assistant_id)

    async def update_assistant(
        self,
        assistant_id: str,
        name: str | None = None,
        system_prompt: str | None = None,
    ) -> dict[str, Any]:
        """Update an assistant."""
        async with BackboardClient(api_key=self._api_key) as client:
            kwargs = {}
            if name is not None:
                kwargs["name"] = name
            if system_prompt is not None:
                kwargs["description"] = system_prompt  # SDK uses 'description'
            return await client.update_assistant(assistant_id, **kwargs)

    async def delete_assistant(self, assistant_id: str) -> dict[str, Any]:
        """Delete an assistant."""
        async with BackboardClient(api_key=self._api_key) as client:
            return await client.delete_assistant(assistant_id)

    # Thread operations
    async def create_thread(self, assistant_id: str) -> dict[str, Any]:
        """Create a new thread under an assistant."""
        async with BackboardClient(api_key=self._api_key) as client:
            result = await client.create_thread(assistant_id)
            return _ensure_string_id(result, "thread_id")

    async def get_thread(self, thread_id: str) -> dict[str, Any]:
        """Get a thread with its messages."""
        async with BackboardClient(api_key=self._api_key) as client:
            return await client.get_thread(thread_id)

    async def list_threads(
        self, skip: int = 0, limit: int = 100
    ) -> list[dict[str, Any]]:
        """List all threads."""
        async with BackboardClient(api_key=self._api_key) as client:
            return await client.list_threads(skip=skip, limit=limit)

    async def delete_thread(self, thread_id: str) -> dict[str, Any]:
        """Delete a thread."""
        async with BackboardClient(api_key=self._api_key) as client:
            return await client.delete_thread(thread_id)

    # Message operations
    async def send_message(
        self,
        thread_id: str,
        content: str,
        memory: str = "Auto",
        llm_provider: str | None = None,
        model_name: str | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        """Send a message to a thread.

        Args:
            thread_id: The thread to send to
            content: Message content
            memory: Memory mode - "Auto", "Readonly", or "off"
            llm_provider: LLM provider (defaults to settings)
            model_name: Model name (defaults to settings)
            stream: Whether to stream the response

        Returns:
            Response object with content and metadata
        """
        async with BackboardClient(api_key=self._api_key) as client:
            return await client.add_message(
                thread_id=thread_id,
                content=content,
                memory=memory,
                llm_provider=llm_provider or self._default_provider,
                model_name=model_name or self._default_model,
                stream=stream,
            )

    async def send_message_with_tools(
        self,
        thread_id: str,
        content: str,
        memory: str = "Auto",
        llm_provider: str | None = None,
        model_name: str | None = None,
    ) -> dict[str, Any]:
        """Send a message and handle tool calls if needed.

        This method handles the tool call loop automatically.

        Args:
            thread_id: The thread to send to
            content: Message content
            memory: Memory mode
            llm_provider: LLM provider
            model_name: Model name

        Returns:
            Final response after any tool calls are resolved
        """
        response = await self.send_message(
            thread_id=thread_id,
            content=content,
            memory=memory,
            llm_provider=llm_provider,
            model_name=model_name,
            stream=False,
        )

        # Handle tool calls if needed
        while response.status == "REQUIRES_ACTION" and response.tool_calls:
            # This would need to be extended with actual tool implementations
            # For now, we'll return the response requiring action
            break

        return response

    async def submit_tool_outputs(
        self,
        thread_id: str,
        run_id: str,
        tool_outputs: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Submit tool outputs to continue a conversation.

        Args:
            thread_id: The thread ID
            run_id: The run ID that requires tool outputs
            tool_outputs: List of {tool_call_id, output} dicts

        Returns:
            Response after processing tool outputs
        """
        async with BackboardClient(api_key=self._api_key) as client:
            return await client.submit_tool_outputs(
                thread_id=thread_id,
                run_id=run_id,
                tool_outputs=tool_outputs,
            )

    # Memory operations
    async def add_memory(
        self,
        assistant_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Add a memory to an assistant.

        Args:
            assistant_id: The assistant to add memory to
            content: Memory content (typically JSON)
            metadata: Optional metadata tags for filtering

        Returns:
            Created memory object
        """
        async with BackboardClient(api_key=self._api_key) as client:
            # Always pass metadata parameter explicitly (even if None)
            return await client.add_memory(
                assistant_id=assistant_id,
                content=content,
                metadata=metadata,
            )

    async def get_memories(self, assistant_id: str) -> dict[str, Any]:
        """Get all memories for an assistant."""
        async with BackboardClient(api_key=self._api_key) as client:
            return await client.get_memories(assistant_id)

    async def get_memory(
        self, assistant_id: str, memory_id: str
    ) -> dict[str, Any]:
        """Get a specific memory."""
        async with BackboardClient(api_key=self._api_key) as client:
            return await client.get_memory(assistant_id, memory_id)

    async def update_memory(
        self,
        assistant_id: str,
        memory_id: str,
        content: str,
    ) -> dict[str, Any]:
        """Update a memory's content."""
        async with BackboardClient(api_key=self._api_key) as client:
            return await client.update_memory(
                assistant_id=assistant_id,
                memory_id=memory_id,
                content=content,
            )

    async def delete_memory(
        self, assistant_id: str, memory_id: str
    ) -> dict[str, Any]:
        """Delete a memory."""
        async with BackboardClient(api_key=self._api_key) as client:
            return await client.delete_memory(assistant_id, memory_id)

    async def get_memory_stats(self, assistant_id: str) -> dict[str, Any]:
        """Get memory usage statistics for an assistant."""
        async with BackboardClient(api_key=self._api_key) as client:
            return await client.get_memory_stats(assistant_id)

    # Document operations
    async def upload_document_to_assistant(
        self, assistant_id: str, file_path: str
    ) -> dict[str, Any]:
        """Upload a document to an assistant for RAG."""
        async with BackboardClient(api_key=self._api_key) as client:
            return await client.upload_document_to_assistant(
                assistant_id=assistant_id,
                file_path=file_path,
            )

    async def upload_document_to_thread(
        self, thread_id: str, file_path: str
    ) -> dict[str, Any]:
        """Upload a document to a thread."""
        async with BackboardClient(api_key=self._api_key) as client:
            return await client.upload_document_to_thread(
                thread_id=thread_id,
                file_path=file_path,
            )

    async def list_assistant_documents(
        self, assistant_id: str
    ) -> list[dict[str, Any]]:
        """List documents attached to an assistant."""
        async with BackboardClient(api_key=self._api_key) as client:
            return await client.list_assistant_documents(assistant_id)

    async def get_document_status(self, document_id: str) -> dict[str, Any]:
        """Get processing status of a document."""
        async with BackboardClient(api_key=self._api_key) as client:
            return await client.get_document_status(document_id)


@asynccontextmanager
async def get_backboard_service() -> AsyncGenerator[BackboardService, None]:
    """Get a BackboardService instance as an async context manager.

    Usage:
        async with get_backboard_service() as service:
            assistant = await service.create_assistant(...)
    """
    service = BackboardService()
    yield service


# Singleton instance for simple use cases
_service_instance: BackboardService | None = None


def get_backboard_service_sync() -> BackboardService:
    """Get a singleton BackboardService instance for sync contexts.

    Note: Caller is responsible for running async methods with asyncio.run()
    or similar.
    """
    global _service_instance
    if _service_instance is None:
        _service_instance = BackboardService()
    return _service_instance
