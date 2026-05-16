"""Structured invocation logging for browser-use server.

Logs each task invocation to a single JSONL file with the following structure:
{
  "timestamp": "2026-05-14T12:30:45.123456Z",
  "task_id": "uuid",
  "task": "Navigate to...",
  "status": "completed|failed|running",
  "llm_provider": "openai",
  "llm_model": "gpt-4o",
  "steps": 12,
  "result": "extracted content or error",
  "duration_seconds": 45.2,
  "error": null
}
"""

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Global state
_invocation_log_enabled: bool = True
_log_file_path: Path | None = None
_log_lock = threading.Lock()
_line_count: int = 0
_MAX_LINES = 10_000


def init_invocation_logger(log_file_path: str | Path | None = None) -> None:
	"""Initialize invocation logger with file path.

	Args:
		log_file_path: Path to JSONL log file. Defaults to ~/.config/browseruse/logs/invocations.jsonl
	"""
	global _log_file_path, _invocation_log_enabled

	if log_file_path is None:
		from browser_use.config import CONFIG

		log_dir = CONFIG.XDG_CONFIG_HOME / 'browseruse' / 'logs'
		log_dir.mkdir(parents=True, exist_ok=True)
		log_file_path = log_dir / 'invocations.jsonl'

	_log_file_path = Path(log_file_path).expanduser()
	_log_file_path.parent.mkdir(parents=True, exist_ok=True)

	# Check if invocation logging is disabled via env
	_invocation_log_enabled = os.getenv('BROWSER_USE_INVOCATION_LOGGING', 'true').lower()[:1] in 'ty1'

	# Count existing lines for rotation tracking
	if _log_file_path.exists():
		with open(_log_file_path, 'r') as f:
			global _line_count
			_line_count = sum(1 for _ in f)

	logger.info(f'Invocation logger initialized: {_log_file_path} (enabled={_invocation_log_enabled})')


def set_invocation_logging(enabled: bool) -> None:
	"""Enable or disable invocation logging at runtime."""
	global _invocation_log_enabled
	_invocation_log_enabled = enabled


def is_invocation_logging_enabled() -> bool:
	"""Check if invocation logging is enabled."""
	return _invocation_log_enabled


def _rotate_if_needed() -> None:
	"""Rotate log file if it exceeds MAX_LINES."""
	global _line_count, _log_file_path

	if _line_count < _MAX_LINES or _log_file_path is None:
		return

	# Rotate to dated file
	timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d')
	rotated_path = _log_file_path.parent / f'invocations_{timestamp}.jsonl'

	with _log_lock:
		if _log_file_path.exists():
			import shutil

			shutil.move(str(_log_file_path), str(rotated_path))
		_line_count = 0


def log_invocation(
	task_id: str,
	task: str,
	status: str,
	llm_provider: str,
	llm_model: str,
	result: Any = None,
	error: str | None = None,
	steps: int = 0,
	duration_seconds: float | None = None,
) -> str:
	"""Log a task invocation to the JSONL file.

	Returns the invocation log ID (timestamp-based).
	"""
	global _line_count

	if not _invocation_log_enabled or _log_file_path is None:
		return ''

	_timestamp = datetime.now(timezone.utc)
	invocation_id = f'inv_{_timestamp.strftime("%Y%m%d_%H%M%S")}'

	entry = {
		'timestamp': _timestamp.isoformat(),
		'invocation_id': invocation_id,
		'task_id': task_id,
		'task': task,
		'status': status,
		'llm_provider': llm_provider,
		'llm_model': llm_model,
		'steps': steps,
		'result': result,
		'error': error,
		'duration_seconds': duration_seconds,
	}

	_rotate_if_needed()

	with _log_lock:
		with open(_log_file_path, 'a') as f:
			f.write(json.dumps(entry) + '\n')
			f.flush()
			os.fsync(f.fileno())
		_line_count += 1

	return invocation_id


def update_invocation(
	invocation_id: str,
	status: str | None = None,
	result: Any = None,
	error: str | None = None,
	steps: int | None = None,
	duration_seconds: float | None = None,
) -> None:
	"""Update an existing invocation log entry.

	Note: JSONL doesn't support in-place updates, so this is a no-op for append-only mode.
	For full updates, use a database. This function logs an additional entry with same task_id
	that can be used to correlate updates.
	"""
	if not _invocation_log_enabled or _log_file_path is None:
		return

	_timestamp = datetime.now(timezone.utc)

	update_entry = {
		'timestamp': _timestamp.isoformat(),
		'invocation_id': invocation_id,
		'update': True,
	}

	if status:
		update_entry['status'] = status
	if result is not None:
		update_entry['result'] = result
	if error is not None:
		update_entry['error'] = error
	if steps is not None:
		update_entry['steps'] = steps
	if duration_seconds is not None:
		update_entry['duration_seconds'] = duration_seconds

	with _log_lock:
		with open(_log_file_path, 'a') as f:
			f.write(json.dumps(update_entry) + '\n')
			f.flush()
			os.fsync(f.fileno())
		_line_count += 1


def get_recent_invocations(limit: int = 50) -> list[dict[str, Any]]:
	"""Get recent invocation entries."""
	if _log_file_path is None or not _log_file_path.exists():
		return []

	entries = []
	with open(_log_file_path, 'r') as f:
		for line in f:
			if line.strip():
				entries.append(json.loads(line))

	# Return last 'limit' entries, excluding update entries
	return [e for e in entries[-limit:] if not e.get('update', False)]