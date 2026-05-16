"""FastAPI server for browser-use backend service.

Runs on localhost only, connecting to internal API services.
"""

import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse

from browser_use.agent.service import Agent
from browser_use.logging_config import get_log_level_runtime, set_log_level_runtime, setup_logging
from browser_use.server.invocation_logger import (
	get_recent_invocations,
	init_invocation_logger,
	is_invocation_logging_enabled,
	log_invocation,
	set_invocation_logging,
	update_invocation,
)
from browser_use.server.models import (
	BatchTaskRequest,
	HealthResponse,
	LLMPayload,
	LogLevelRequest,
	LogLevelResponse,
	TaskOptions,
	TaskRequest,
	TaskResponse,
	TaskResult,
	TaskStatus,
)
from browser_use.server.session_manager import get_session_manager, shutdown_session_manager
from browser_use.utils import get_browser_use_version

logger = logging.getLogger(__name__)

# Global task storage (in-memory for simplicity)
_tasks: dict[str, dict[str, Any]] = {}
_tasks_lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app: FastAPI):
	"""Application lifespan handler."""
	# Startup
	setup_logging()
	init_invocation_logger()

	# Initialize session manager
	session_mgr = get_session_manager()
	await session_mgr.initialize()

	logger.info('Browser-use server started')
	yield

	# Shutdown
	logger.info('Browser-use server shutting down')
	await shutdown_session_manager()
	logger.info('Browser-use server stopped')


app = FastAPI(
	title='Browser-Use Backend Service',
	description='Backend service for browser automation via AI agents',
	version=get_browser_use_version(),
	lifespan=lifespan,
)


def _create_llm(llm_config: LLMPayload) -> Any:
	"""Create LLM client from configuration."""
	from browser_use.llm import LLMManager

	llm_manager = LLMManager()

	if llm_config.provider.value == 'openai':
		from openai import AsyncOpenAI

		client = AsyncOpenAI(api_key=llm_config.api_key or os.getenv('OPENAI_API_KEY'))
		return llm_manager.get_llm_model(client=client, model=llm_config.model or 'gpt-4o')
	elif llm_config.provider.value == 'anthropic':
		from anthropic import AsyncAnthropic

		client = AsyncAnthropic(api_key=llm_config.api_key or os.getenv('ANTHROPIC_API_KEY'))
		return llm_manager.get_llm_model(client=client, model=llm_config.model or 'claude-sonnet-4-7')
	elif llm_config.provider.value == 'google':
		from google.genai import Client as GeminiClient

		client = GeminiClient(api_key=llm_config.api_key or os.getenv('GOOGLE_API_KEY'))
		return llm_manager.get_llm_model(client=client, model=llm_config.model or 'gemini-2.0-flash')
	else:
		raise ValueError(f'Unsupported LLM provider: {llm_config.provider}')


async def _run_task(
	task_id: str,
	task: str,
	llm_config: LLMPayload,
	options: TaskOptions,
) -> dict[str, Any]:
	"""Execute a browser automation task."""
	from browser_use.browser import BrowserProfile

	start_time = time.time()

	# Log task start
	invocation_id = log_invocation(
		task_id=task_id,
		task=task,
		status='running',
		llm_provider=llm_config.provider.value,
		llm_model=llm_config.model,
	)

	# Update task status
	_tasks[task_id] = {
		'status': TaskStatus.RUNNING,
		'invocation_id': invocation_id,
		'task': task,
		'llm_config': llm_config.model_dump(),
		'options': options.model_dump(),
		'started_at': start_time,
	}

	session_mgr = get_session_manager()

	try:
		async with session_mgr.session_context() as browser_session:
			# Configure browser profile
			browser_profile = BrowserProfile(
				headless=options.headless,
				allowed_domains=options.allowed_domains,
			)

			# Create agent
			llm = _create_llm(llm_config)
			agent = Agent(
				task=task,
				llm=llm,
				browser_session=browser_session,
				max_steps=options.max_steps,
				use_vision=options.use_vision,
			)

			# Run agent
			result = await agent.run()

			duration = time.time() - start_time

			# Extract result
			if result.is_done():
				extracted = result.history[-1].result[0].extracted_content if result.history else None
				final_status = TaskStatus.COMPLETED
				error = None
			else:
				extracted = None
				final_status = TaskStatus.FAILED
				error = 'Task did not complete successfully'

			steps = len(result.history) if result.history else 0

			# Update invocation log
			update_invocation(
				invocation_id=invocation_id,
				status='completed',
				result=extracted,
				error=error,
				steps=steps,
				duration_seconds=duration,
			)

			# Update task
			_tasks[task_id].update({
				'status': final_status,
				'result': extracted,
				'error': error,
				'steps': steps,
				'duration_seconds': duration,
			})

			return {
				'task_id': task_id,
				'status': final_status.value,
				'result': extracted,
				'error': error,
				'steps': steps,
				'duration_seconds': duration,
			}

	except Exception as e:
		duration = time.time() - start_time
		error_msg = str(e)

		logger.exception(f'Task {task_id} failed: {e}')

		update_invocation(
			invocation_id=invocation_id,
			status='failed',
			error=error_msg,
			duration_seconds=duration,
		)

		_tasks[task_id].update({
			'status': TaskStatus.FAILED,
			'error': error_msg,
			'duration_seconds': duration,
		})

		return {
			'task_id': task_id,
			'status': TaskStatus.FAILED.value,
			'error': error_msg,
			'duration_seconds': duration,
		}


@app.post('/task', response_model=TaskResponse)
async def create_task(request: TaskRequest) -> TaskResponse:
	"""Submit a new browser automation task."""
	task_id = str(uuid.uuid4())

	_tasks[task_id] = {
		'status': TaskStatus.PENDING,
		'task': request.task,
		'llm_config': request.llm.model_dump(),
		'options': request.options.model_dump(),
	}

	# Run task in background
	asyncio.create_task(_run_task(
		task_id=task_id,
		task=request.task,
		llm_config=request.llm,
		options=request.options,
	))

	# Get invocation_id from task
	invocation_id = _tasks[task_id].get('invocation_id')

	return TaskResponse(
		task_id=task_id,
		status=TaskStatus.PENDING,
		invocation_log_id=invocation_id,
	)


@app.post('/task/sync', response_model=TaskResult)
async def run_task_sync(request: TaskRequest) -> TaskResult:
	"""Run a task synchronously and return result immediately."""
	task_id = str(uuid.uuid4())

	result = await _run_task(
		task_id=task_id,
		task=request.task,
		llm_config=request.llm,
		options=request.options,
	)

	return TaskResult(**result)


@app.get('/task/{task_id}', response_model=TaskResult)
async def get_task(task_id: str) -> TaskResult:
	"""Get task status and result."""
	if task_id not in _tasks:
		raise HTTPException(status_code=404, detail=f'Task {task_id} not found')

	task_data = _tasks[task_id]

	return TaskResult(
		task_id=task_id,
		status=task_data['status'],
		result=task_data.get('result'),
		error=task_data.get('error'),
		steps=task_data.get('steps', 0),
		duration_seconds=task_data.get('duration_seconds'),
	)


@app.post('/logs/level', response_model=LogLevelResponse)
async def change_log_level(request: LogLevelRequest) -> LogLevelResponse:
	"""Change log level at runtime without restart."""
	set_log_level_runtime(request.level.value)

	return LogLevelResponse(
		level=request.level,
		message=f'Log level changed to {request.level.value}',
	)


@app.get('/logs/level', response_model=LogLevelResponse)
async def get_current_log_level() -> LogLevelResponse:
	"""Get current runtime log level."""
	current = get_log_level_runtime()

	return LogLevelResponse(
		level=current,
		message=f'Current log level: {current}',
	)


@app.get('/health', response_model=HealthResponse)
async def health_check() -> HealthResponse:
	"""Health check endpoint."""
	session_mgr = get_session_manager()
	status = await session_mgr.get_status()

	return HealthResponse(
		status='ok',
		version=get_browser_use_version(),
		browser_sessions_available=status['available'],
		invocation_log_enabled=is_invocation_logging_enabled(),
	)


@app.get('/invocations', response_model=list[dict])
async def list_invocations(limit: int = 50) -> list[dict]:
	"""Get recent invocation logs."""
	return get_recent_invocations(limit=limit)


@app.post('/logs/invocation', response_model=dict)
async def toggle_invocation_logging(enabled: bool) -> dict:
	"""Enable or disable invocation logging."""
	set_invocation_logging(enabled)
	return {'enabled': enabled, 'message': f'Invocation logging {"enabled" if enabled else "disabled"}'}


def create_app() -> FastAPI:
	"""Factory function to create FastAPI app."""
	return app


def run_server():
	"""Run the server using uvicorn."""
	import uvicorn

	host = os.getenv('BROWSER_USE_SERVER_HOST', '127.0.0.1')
	port = int(os.getenv('BROWSER_USE_SERVER_PORT', '18792'))

	uvicorn.run(
		'browser_use.server.app:app',
		host=host,
		port=port,
		log_level='info',
	)


if __name__ == '__main__':
	run_server()