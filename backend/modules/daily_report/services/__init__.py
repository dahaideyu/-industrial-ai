# cython: annotation_typing=False, infer_types=False, language_level=3
from .report_generator import generate_report_stream

__all__ = ["generate_report_stream"]