"""
SICAL Operation Processors Package.

This package contains specialized processors for different SICAL operation types.
Each processor handles a specific operation (ADO220, PMP450, etc.) following
the common base class pattern.
"""

from .ado220_processor import ADO220Processor
from .pmp450_processor import PMP450Processor

__all__ = ['ADO220Processor', 'PMP450Processor']
