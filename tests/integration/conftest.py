"""
Shared fixtures for integration tests.

Patches FastAPI's multipart check before any test module is imported so that
the upload endpoint can be registered without python-multipart being importable
as the `multipart` top-level package (conda environment compatibility shim).
"""
import sys
from unittest.mock import MagicMock

# Inject stub BEFORE FastAPI registers any routes that use UploadFile/Form.
# FastAPI's ensure_multipart_is_installed() does `import multipart` which
# fails in some conda envs even when python-multipart is installed.
_stub = MagicMock()
sys.modules.setdefault("multipart", _stub)
sys.modules.setdefault("multipart.multipart", _stub)

# Also patch the check function directly as a belt-and-suspenders guard
import fastapi.dependencies.utils as _fdu

_fdu.ensure_multipart_is_installed = lambda: None  # noqa: E731
