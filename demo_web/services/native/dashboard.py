from __future__ import annotations

from flask import render_template

from demo_web.services.dashboard import gather_dashboard


def view(user_email: str, user_rol: str):
    ctx = gather_dashboard(user_email, user_rol)
    return render_template(
        "dashboard/index.html",
        page_title="Dashboard",
        active_key="DASHBOARD",
        **ctx,
    )
