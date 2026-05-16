"""Pydantic models for browser-use server API."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class LogLevel(str, Enum):
	"""Valid log levels."""

	DEBUG = 'debug'
	INFO = 'info'
	RESULT = 'result'
	CRITICAL = 'critical'


class LLMProvider(str, Enum):
	"""Supported LLM providers."""

	OPENAI = 'openai'
	ANTHROPIC = 'anthropic'
	GOOGLE = 'google'
	DEEPSEEK = 'deepseek'
	GROK = 'grok'
	AZURE = 'azure'


class TaskStatus(str, Enum):
	"""Task execution status."""

	PENDING = 'pending'
	RUNNING = 'running'
	COMPLETED = 'completed'
	FAILED = 'failed'


class LLMPayload(BaseModel):
	"""LLM configuration for a task."""

	provider: LLMProvider = Field(default=LLMProvider.OPENAI)
	model: str = Field(default='gpt-4o')
	api_key: str | None = Field(default=None)
	temperature: float | None = Field(default=None)
	max_tokens: int | None = Field(default=None)


class TaskOptions(BaseModel):
	"""Options for task execution."""

	headless: bool = Field(default=True)
	max_steps: int = Field(default=50)
	use_vision: bool = Field(default=True)
	system_prompt: str | None = Field(default=None)
	allowed_domains: list[str] | None = Field(default=None)


class TaskRequest(BaseModel):
	"""Request to run a browser automation task."""

	task: str = Field(..., min_length=1, description='Natural language task description')
	llm: LLMPayload = Field(default_factory=LLMPayload)
	options: TaskOptions = Field(default_factory=TaskOptions)


class BatchTaskRequest(BaseModel):
	"""Request to run multiple tasks sequentially."""

	tasks: list[str] = Field(..., min_length=1)
	llm: LLMPayload = Field(default_factory=LLMPayload)
	options: TaskOptions = Field(default_factory=TaskOptions)


class TaskResponse(BaseModel):
	"""Response after submitting a task."""

	task_id: str = Field(..., description='Unique task identifier')
	status: TaskStatus = Field(..., description='Current task status')
	invocation_log_id: str | None = Field(default=None, description='ID for invocation log entry')


class TaskResult(BaseModel):
	"""Task result when completed."""

	task_id: str
	status: TaskStatus
	result: Any | None = Field(default=None, description='Extracted content or result')
	error: str | None = Field(default=None, description='Error message if failed')
	steps: int = Field(default=0, description='Number of steps executed')
	duration_seconds: float | None = Field(default=None, description='Execution time')


class LogLevelRequest(BaseModel):
	"""Request to change log level."""

	level: LogLevel


class LogLevelResponse(BaseModel):
	"""Response with current log level."""

	level: LogLevel
	message: str


class HealthResponse(BaseModel):
	"""Health check response."""

	status: str = 'ok'
	version: str
	browser_sessions_available: int = Field(default=0)
	invocation_log_enabled: bool = Field(default=True)


class ErrorResponse(BaseModel):
	"""Error response."""

	error: str
	detail: str | None = None