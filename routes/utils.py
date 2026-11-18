from functools import wraps
from flask import session, redirect, url_for, flash, render_template_string

def role_required(role):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if session.get("role") != role:
                return redirect(url_for("auth.login"))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def render_placeholder(title):
    return render_template_string(
        """
        {% extends "base.html" %}
        {% block title %}{{ title }} - Health System Management{% endblock %}
        {% block content %}
        <div class="py-4">
          <div class="card">
            <div class="card-body">
              <h2 class="card-title">{{ title }}</h2>
              <p class="card-text text-muted">Not implemented yet</p>
            </div>
          </div>
        </div>
        {% endblock %}
        """,
        title=title,
    )
