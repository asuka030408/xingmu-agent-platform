"""Assemble the local web application from small route modules."""

from flask import Flask, render_template
from flask import jsonify
from psycopg_pool import PoolTimeout

from .config import PROJECT_ROOT
from .routes_booking import booking_routes
from .routes_read import read_routes
from .security import init_security

app = Flask(__name__, template_folder=str(PROJECT_ROOT / "templates"),
            static_folder=str(PROJECT_ROOT / "static"))
app.json.ensure_ascii = False
init_security(app)
app.register_blueprint(read_routes)
app.register_blueprint(booking_routes)


@app.errorhandler(PoolTimeout)
def busy(_error):
    return jsonify({"error": "当前请求较多，请稍后重试。"}), 503


@app.get("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8765, debug=False)
