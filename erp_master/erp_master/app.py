from __future__ import annotations

import os
from functools import wraps

from flask import (
    Flask,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from erp_master.config import Config
from erp_master.db import authenticate, close_db, init_db


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("master_email"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def create_app(config_object: type = Config) -> Flask:
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static",
    )
    app.config.from_object(config_object)

    # Ensure DB directory exists
    db_path = app.config["DATABASE"]
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    app.teardown_appcontext(close_db)

    with app.app_context():
        init_db()

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if session.get("master_email"):
            return redirect(url_for("home"))

        error = None
        if request.method == "POST":
            email = (request.form.get("email") or "").strip()
            password = request.form.get("password") or ""
            user = authenticate(email, password)
            if user:
                session.clear()
                session["master_email"] = user["email"]
                session["master_nombre"] = user.get("nombre") or ""
                session.permanent = True
                nxt = request.args.get("next") or url_for("home")
                if not str(nxt).startswith("/"):
                    nxt = url_for("home")
                return redirect(nxt)
            error = "Usuario o clave incorrectos."

        return render_template(
            "login.html",
            brand=app.config["BRAND_NAME"],
            tagline=app.config["BRAND_TAGLINE"],
            error=error,
        )

    @app.route("/logout", methods=["POST"])
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def home():
        return render_template(
            "home.html",
            brand=app.config["BRAND_NAME"],
            tagline=app.config["BRAND_TAGLINE"],
            tenants=app.config["TENANTS"],
            email=session.get("master_email"),
            nombre=session.get("master_nombre") or "",
        )

    @app.get("/health")
    def health():
        return {"ok": True, "app": "erp_master"}

    return app
