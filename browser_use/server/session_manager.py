"""Browser session management for browser-use server.

Provides a pool of browser sessions for concurrent task execution.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from browser_use.browser import BrowserProfile, BrowserSession
from browser_use.browser.session import BrowserSession as BrowserSessionClass

logger = logging.getLogger(__name__)


class SessionManager:
	"""Manages a pool of browser sessions for the server."""

	def __init__(self, pool_size: int = 2):
		"""Initialize session manager.

		Args:
			pool_size: Number of browser sessions to keep in pool
		"""
		self._pool_size = pool_size
		self._sessions: list[BrowserSessionClass] = []
		self._available: asyncio.Queue[BrowserSessionClass] = asyncio.Queue()
		self._in_use: set[BrowserSessionClass] = set()
		self._lock = asyncio.Lock()
		self._initialized = False

	async def initialize(self) -> None:
		"""Pre-initialize browser sessions in the pool."""
		if self._initialized:
			return

		async with self._lock:
			if self._initialized:
				return

			logger.info(f'Initializing session pool with {self._pool_size} sessions')

			for i in range(self._pool_size):
				browser_profile = BrowserProfile(headless=True)
				browser_session = BrowserSession(browser_profile=browser_profile)
				self._sessions.append(browser_session)
				await self._available.put(browser_session)

			self._initialized = True
			logger.info(f'Session pool initialized with {self._pool_size} sessions')

	async def get_session(self) -> BrowserSessionClass:
		"""Get an available browser session from the pool."""
		if not self._initialized:
			await self.initialize()

		session = await self._available.get()
		async with self._lock:
			self._in_use.add(session)

		logger.debug(f'Session acquired. Available: {self._available.qsize()}, In use: {len(self._in_use)}')
		return session

	async def release_session(self, session: BrowserSessionClass) -> None:
		"""Return a session to the pool."""
		async with self._lock:
			if session in self._in_use:
				self._in_use.remove(session)

		# Check if session is still healthy before returning to pool
		try:
			if hasattr(session, 'is_cdp_connected') and session.is_cdp_connected:
				await self._available.put(session)
				logger.debug(f'Session released. Available: {self._available.qsize()}, In use: {len(self._in_use)}')
			else:
				# Session is dead, replace with a new one
				logger.warning('Session unhealthy, replacing with new session')
				browser_profile = BrowserProfile(headless=True)
				new_session = BrowserSession(browser_profile=browser_profile)
				self._sessions.append(new_session)
				await self._available.put(new_session)
		except Exception as e:
			logger.error(f'Error releasing session: {e}')
			# Create replacement session
			try:
				browser_profile = BrowserProfile(headless=True)
				new_session = BrowserSession(browser_profile=browser_profile)
				await self._available.put(new_session)
			except Exception:
				pass

	@asynccontextmanager
	async def session_context(self) -> AsyncGenerator[BrowserSessionClass, None]:
		"""Context manager for using a session safely."""
		session = await self.get_session()
		try:
			yield session
		finally:
			await self.release_session(session)

	async def get_status(self) -> dict:
		"""Get current status of the session pool."""
		return {
			'pool_size': self._pool_size,
			'available': self._available.qsize(),
			'in_use': len(self._in_use),
			'initialized': self._initialized,
		}

	async def shutdown(self) -> None:
		"""Gracefully shutdown all browser sessions."""
		logger.info('Shutting down session pool')

		async with self._lock:
			for session in self._sessions:
				try:
					if hasattr(session, 'is_cdp_connected') and session.is_cdp_connected:
						await session.kill()
				except Exception as e:
					logger.debug(f'Error closing session: {e}')

			self._sessions.clear()
			self._in_use.clear()
			self._initialized = False

		logger.info('Session pool shutdown complete')


# Global session manager instance
_session_manager: SessionManager | None = None


def get_session_manager(pool_size: int = 2) -> SessionManager:
	"""Get or create the global session manager."""
	global _session_manager
	if _session_manager is None:
		_session_manager = SessionManager(pool_size=pool_size)
	return _session_manager


async def shutdown_session_manager() -> None:
	"""Shutdown the global session manager."""
	global _session_manager
	if _session_manager is not None:
		await _session_manager.shutdown()
		_session_manager = None