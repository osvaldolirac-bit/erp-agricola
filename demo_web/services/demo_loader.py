"""Compat: reexporta erp_loader."""
from demo_web.services.erp_loader import (  # noqa: F401
    bind_user_session,
    clear_user_session,
    get_demo_module,
    get_erp_app,
    get_erp_module,
    init_demo_db,
    init_erp_db,
    invalidate_demo_module,
    invalidate_erp_module,
)
