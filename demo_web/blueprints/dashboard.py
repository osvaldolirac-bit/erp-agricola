from __future__ import annotations

from flask import Blueprint, g, render_template

from demo_web.auth.decorators import login_required, module_required
from demo_web.services.dashboard import gather_dashboard

bp = Blueprint("dashboard", __name__)


@bp.route("/")
@login_required
@module_required("DASHBOARD")
def index():
    ctx = gather_dashboard(g.user["email"], g.user["rol"])
    return render_template(
        "dashboard/index.html",
        page_title="Dashboard",
        active_key="DASHBOARD",
        **ctx,
    )
