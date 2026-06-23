"""
pipeline.py

Generic, Thread-Safe Sync & Async Pipeline/Interceptor Middleware Engine.
Allows scaling Chain of Responsibility pattern across core evaluation runner APIs.
"""

import logging
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from contextlib import asynccontextmanager, contextmanager

# ==========================================
# 1. Synchronous Pipeline Service
# ==========================================


class Interceptor[RequestT, ResponseT](ABC):
    """Abstract base class for type-safe synchronous pipeline interceptors."""

    @abstractmethod
    def can_intercept(self, request: RequestT) -> bool:
        """Determines if this interceptor supports the request."""
        pass

    @abstractmethod
    def intercept(
        self, request: RequestT, next_interceptor: Callable[[RequestT], ResponseT]
    ) -> ResponseT:
        """Applies middleware processing (Preempt, Augment, Post-process)."""
        pass


class PipelineService[RequestT, ResponseT]:
    """Sync Pipeline orchestrator with thread-safety and exception barriers."""

    def __init__(
        self, fallback_handler: Callable[[RequestT], ResponseT], service_name: str = "Pipeline"
    ):
        self._lock = threading.RLock()
        self._global_interceptors: list[Interceptor[RequestT, ResponseT]] = []
        self._interceptor_threads: dict[Interceptor[RequestT, ResponseT], int] = {}
        self._fallback = fallback_handler
        self._service_name = service_name
        self._local = threading.local()

    @property
    def _interceptors(self) -> list[Interceptor[RequestT, ResponseT]]:
        """Provides thread-local copy of registered interceptors to ensure thread isolation."""
        if not hasattr(self._local, "interceptors"):
            with self._lock:
                current_thread = threading.get_ident()
                main_thread = threading.main_thread().ident
                self._local.interceptors = [
                    i
                    for i in self._global_interceptors
                    if self._interceptor_threads.get(i) in (current_thread, main_thread)
                ]
        return self._local.interceptors

    def register_interceptor(self, interceptor: Interceptor[RequestT, ResponseT]):
        """Registers an interceptor thread-safely at the head of the priority chain."""
        with self._lock:
            self._global_interceptors.insert(0, interceptor)
            self._interceptor_threads[interceptor] = threading.get_ident()
            if hasattr(self._local, "interceptors"):
                self._local.interceptors.insert(0, interceptor)

    def reset(self):
        """Thread-safely clears all custom interceptors."""
        with self._lock:
            self._global_interceptors.clear()
            self._interceptor_threads.clear()
            if hasattr(self._local, "interceptors"):
                self._local.interceptors.clear()

    @contextmanager
    def override_interceptor(self, interceptor: Interceptor[RequestT, ResponseT]):
        """Context manager to safely register an interceptor temporarily and prevent leaks."""
        self.register_interceptor(interceptor)
        try:
            yield
        finally:
            with self._lock:
                self._interceptor_threads.pop(interceptor, None)
                if interceptor in self._global_interceptors:
                    self._global_interceptors.remove(interceptor)
                if hasattr(self._local, "interceptors") and interceptor in self._local.interceptors:
                    self._local.interceptors.remove(interceptor)

    def execute(self, request: RequestT) -> ResponseT:
        """Executes the request through the chain with error barriers."""

        def make_next(index: int, depth: int) -> Callable[[RequestT], ResponseT]:
            if depth > 50:
                raise RecursionError(
                    f"Max {self._service_name} pipeline depth exceeded. Cycle detected."
                )

            interceptors_list = self._interceptors
            if index >= len(interceptors_list):
                return self._fallback

            interceptor = interceptors_list[index]

            def call_next(req: RequestT) -> ResponseT:
                if interceptor.can_intercept(req):
                    try:
                        return interceptor.intercept(req, make_next(index + 1, depth + 1))
                    except (RecursionError, KeyboardInterrupt, SystemExit, GeneratorExit):
                        # Propagate system control exceptions immediately
                        raise
                    except Exception as e:
                        logging.error(
                            f"[{self._service_name}] Interceptor "
                            f"'{interceptor.__class__.__name__}' failed: {e}. "
                            "Gracefully bypassing to next handler."
                        )
                        return make_next(index + 1, depth + 1)(req)
                else:
                    return make_next(index + 1, depth + 1)(req)

            return call_next

        return make_next(0, 0)(request)


# ==========================================
# 2. Native Asynchronous Pipeline Service
# ==========================================


class AsyncInterceptor[RequestT, ResponseT](ABC):
    """Abstract base class for type-safe native asynchronous pipeline interceptors."""

    @abstractmethod
    def can_intercept(self, request: RequestT) -> bool:
        """Determines if this interceptor supports the request."""
        pass

    @abstractmethod
    async def intercept(
        self,
        request: RequestT,
        next_interceptor: Callable[[RequestT], Coroutine[None, None, ResponseT]],
    ) -> ResponseT:
        """Applies awaitable middleware processing."""
        pass


class AsyncPipelineService[RequestT, ResponseT]:
    """Native Async Pipeline orchestrator supporting awaitable dynamic interceptors."""

    def __init__(
        self,
        fallback_handler: Callable[[RequestT], Coroutine[None, None, ResponseT]],
        service_name: str = "AsyncPipeline",
    ):
        self._lock = threading.RLock()
        self._global_interceptors: list[AsyncInterceptor[RequestT, ResponseT]] = []
        self._interceptor_threads: dict[AsyncInterceptor[RequestT, ResponseT], int] = {}
        self._fallback = fallback_handler
        self._service_name = service_name
        self._local = threading.local()

    @property
    def _interceptors(self) -> list[AsyncInterceptor[RequestT, ResponseT]]:
        """Provides thread-local copy of registered interceptors to ensure thread isolation."""
        if not hasattr(self._local, "interceptors"):
            with self._lock:
                current_thread = threading.get_ident()
                main_thread = threading.main_thread().ident
                self._local.interceptors = [
                    i
                    for i in self._global_interceptors
                    if self._interceptor_threads.get(i) in (current_thread, main_thread)
                ]
        return self._local.interceptors

    def register_interceptor(self, interceptor: AsyncInterceptor[RequestT, ResponseT]):
        """Registers an async interceptor thread-safely at the head of the priority chain."""
        with self._lock:
            self._global_interceptors.insert(0, interceptor)
            self._interceptor_threads[interceptor] = threading.get_ident()
            if hasattr(self._local, "interceptors"):
                self._local.interceptors.insert(0, interceptor)

    def reset(self):
        """Thread-safely clears all custom async interceptors."""
        with self._lock:
            self._global_interceptors.clear()
            self._interceptor_threads.clear()
            if hasattr(self._local, "interceptors"):
                self._local.interceptors.clear()

    @asynccontextmanager
    async def override_interceptor(self, interceptor: AsyncInterceptor[RequestT, ResponseT]):
        """Context manager to safely register an async interceptor temporarily and prevent leaks."""
        self.register_interceptor(interceptor)
        try:
            yield
        finally:
            with self._lock:
                self._interceptor_threads.pop(interceptor, None)
                if interceptor in self._global_interceptors:
                    self._global_interceptors.remove(interceptor)
                if hasattr(self._local, "interceptors") and interceptor in self._local.interceptors:
                    self._local.interceptors.remove(interceptor)

    async def execute(self, request: RequestT) -> ResponseT:
        """Executes the async request through the chain with error barriers."""

        def make_next(
            index: int, depth: int
        ) -> Callable[[RequestT], Coroutine[None, None, ResponseT]]:
            if depth > 50:
                raise RecursionError(
                    f"Max {self._service_name} pipeline depth exceeded. Cycle detected."
                )

            interceptors_list = self._interceptors
            if index >= len(interceptors_list):
                return self._fallback

            interceptor = interceptors_list[index]

            async def call_next(req: RequestT) -> ResponseT:
                if interceptor.can_intercept(req):
                    try:
                        return await interceptor.intercept(req, make_next(index + 1, depth + 1))
                    except (RecursionError, KeyboardInterrupt, SystemExit, GeneratorExit):
                        raise
                    except Exception as e:
                        logging.error(
                            f"[{self._service_name}] Interceptor "
                            f"'{interceptor.__class__.__name__}' failed: {e}. "
                            "Gracefully bypassing to next handler."
                        )
                        return await make_next(index + 1, depth + 1)(req)
                else:
                    return await make_next(index + 1, depth + 1)(req)

            return call_next

        return await make_next(0, 0)(request)
