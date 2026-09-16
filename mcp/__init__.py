"""Banjo MCP package initialization.

Workshop's richer built-in products live outside the core wireframe module so
new functional products do not turn that module into a product-specific
monolith.  Importing the package registers those recipes once; every caller of
``mcp.workshop`` therefore sees the same product catalogue.
"""

from . import workshop_products as _workshop_products

_workshop_products.install()
