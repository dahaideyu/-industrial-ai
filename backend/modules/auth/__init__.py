# cython: annotation_typing=False, infer_types=False, language_level=3
from .routes import router as auth_router

__all__ = ["auth_router"]
