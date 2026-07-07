import os
import logging
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ProjectHealthBackend")

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# ==========================================
# DATABASE CONNECTION
# Connects to PostgreSQL (Neon) via DATABASE_URL.
# No fallback — DATABASE_URL is required.
# ==========================================

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL environment variable is not set. "
        "Add it in Render → your service → Environment, using your Neon connection string."
    )

# Modernize connection string scheme to ensure compatibility
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
logger.info("⚡ Successfully connected to PostgreSQL database!")


# ==========================================
# DATABASE HELPERS
# ==========================================
def execute_query(query, params=(), fetch_all=False, fetch_one=False):
    global conn
    try:
        if conn is None or conn.closed:
            conn = psycopg2.connect(DATABASE_URL)
            conn.autocommit = True

        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            if fetch_all:
                return cur.fetchall()
            if fetch_one:
                return cur.fetchone()
            return None
    except Exception as e:
        logger.error(f"PostgreSQL Query Error: {e}")
        raise e


def init_db():
    """Create tables if they don't already exist. No seed/mock data —
    real records are created through Sign Up / the workspace forms."""
    execute_query("""
        CREATE TABLE IF NOT EXISTS employees (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            dept TEXT NOT NULL
        )
    """)
    execute_query("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            startdate TEXT NOT NULL,
            manager TEXT NOT NULL
        )
    """)
    execute_query("""
        CREATE TABLE IF NOT EXISTS discussions (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            project_name TEXT NOT NULL,
            points TEXT NOT NULL,
            date TEXT NOT NULL,
            remarks TEXT NOT NULL
        )
    """)
    execute_query("""
        CREATE TABLE IF NOT EXISTS departments (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL UNIQUE
        )
    """)


init_db()


# ==========================================
# HEALTH CHECK
# ==========================================
@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "healthy",
        "database_engine": "postgres",
        "postgres_connected": True,
        "timestamp": datetime.utcnow().isoformat()
    })


# ==========================================
# AUTHENTICATION
# ==========================================
@app.route("/api/login", methods=["POST"])
def login():
    data = request.json or {}
    email = (data.get("email") or "").strip().lower()
    role = data.get("role")

    if not email or not role:
        return jsonify({"error": "Missing credentials"}), 400

    name = "Administrator"

    if role == "Project Manager":
        try:
            existing = execute_query(
                "SELECT * FROM employees WHERE LOWER(email) = %s",
                (email,), fetch_one=True
            )

            if existing:
                name = existing["name"]
            else:
                # First time this PM has signed in — register them automatically
                name = email.split("@")[0].replace(".", " ").title()
                count_row = execute_query("SELECT COUNT(*) as count FROM employees", fetch_one=True)
                count = count_row.get("count") if count_row else 0
                new_id = f"EMP-{str(count + 1).zfill(3)}"

                execute_query(
                    "INSERT INTO employees (id, name, email, dept) VALUES (%s, %s, %s, %s)",
                    (new_id, name, email, "Engineering")
                )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return jsonify({
        "status": "authenticated",
        "user": {"email": email, "role": role, "name": name}
    })


# ==========================================
# EMPLOYEES API
# ==========================================
@app.route("/api/employees", methods=["GET"])
def get_employees():
    try:
        employees = execute_query("SELECT * FROM employees ORDER BY id ASC", fetch_all=True)
        return jsonify(employees)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/employees", methods=["POST"])
def create_employee():
    data = request.json or {}
    name = data.get("name")
    email = (data.get("email") or "").strip().lower()
    dept = data.get("dept") or "Engineering"

    if not name or not email:
        return jsonify({"error": "Missing required fields"}), 400

    try:
        count_row = execute_query("SELECT COUNT(*) as count FROM employees", fetch_one=True)
        count = count_row.get("count") if count_row else 0
        new_id = f"EMP-{str(count + 1).zfill(3)}"

        execute_query(
            "INSERT INTO employees (id, name, email, dept) VALUES (%s, %s, %s, %s)",
            (new_id, name, email, dept)
        )
        return jsonify({"id": new_id, "name": name, "email": email, "dept": dept}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/employees/<id>", methods=["PUT"])
def update_employee(id):
    data = request.json or {}
    name = data.get("name")
    email = (data.get("email") or "").strip().lower()
    dept = data.get("dept")

    if not name or not email:
        return jsonify({"error": "Missing required fields"}), 400

    try:
        existing = execute_query(
            "SELECT * FROM employees WHERE id = %s",
            (id,), fetch_one=True
        )
        old_name = existing.get("name") if existing else None

        execute_query(
            "UPDATE employees SET name = %s, email = %s, dept = %s WHERE id = %s",
            (name, email, dept, id)
        )

        # Keep project manager references in sync if the name changed
        if old_name and old_name != name:
            execute_query(
                "UPDATE projects SET manager = %s WHERE manager = %s",
                (name, old_name)
            )

        return jsonify({"message": "Employee updated successfully", "id": id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/employees/<id>", methods=["DELETE"])
def delete_employee(id):
    try:
        execute_query("DELETE FROM employees WHERE id = %s", (id,))
        return jsonify({"message": f"Employee {id} removed."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==========================================
# PROJECTS API
# ==========================================
@app.route("/api/projects", methods=["GET"])
def get_projects():
    try:
        projects = execute_query("SELECT * FROM projects ORDER BY id ASC", fetch_all=True)
        return jsonify(projects)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/projects", methods=["POST"])
def create_project():
    data = request.json or {}
    name = data.get("name")
    status = data.get("status")
    startdate = data.get("startdate")
    manager = data.get("manager")

    if not name or not status or not startdate or not manager:
        return jsonify({"error": "Missing required fields"}), 400

    try:
        count_row = execute_query("SELECT COUNT(*) as count FROM projects", fetch_one=True)
        count = count_row.get("count") if count_row else 0
        new_id = f"PRJ-{str(count + 1).zfill(3)}"

        execute_query(
            "INSERT INTO projects (id, name, status, startdate, manager) VALUES (%s, %s, %s, %s, %s)",
            (new_id, name, status, startdate, manager)
        )
        return jsonify({"id": new_id, "name": name, "status": status, "startdate": startdate, "manager": manager}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/projects/<id>", methods=["PUT"])
def update_project(id):
    data = request.json or {}
    name = data.get("name")
    status = data.get("status")
    startdate = data.get("startdate")
    manager = data.get("manager")

    if not name or not status or not startdate or not manager:
        return jsonify({"error": "Missing fields"}), 400

    try:
        execute_query(
            "UPDATE projects SET name = %s, status = %s, startdate = %s, manager = %s WHERE id = %s",
            (name, status, startdate, manager, id)
        )
        # Keep the cached project_name on discussion rows in sync
        execute_query(
            "UPDATE discussions SET project_name = %s WHERE project_id = %s",
            (name, id)
        )
        return jsonify({"message": "Project updated successfully", "id": id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/projects/<id>", methods=["DELETE"])
def delete_project(id):
    try:
        execute_query("DELETE FROM projects WHERE id = %s", (id,))
        execute_query("DELETE FROM discussions WHERE project_id = %s", (id,))
        return jsonify({"message": f"Project {id} and its discussions removed."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==========================================
# DEPARTMENTS API
# ==========================================
@app.route("/api/departments", methods=["GET"])
def get_departments():
    try:
        departments = execute_query("SELECT * FROM departments ORDER BY name ASC", fetch_all=True)
        return jsonify(departments)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/departments", methods=["POST"])
def create_department():
    data = request.json or {}
    name = (data.get("name") or "").strip()

    if not name:
        return jsonify({"error": "Department name is required"}), 400

    try:
        existing = execute_query(
            "SELECT * FROM departments WHERE LOWER(name) = LOWER(%s)",
            (name,), fetch_one=True
        )
        if existing:
            return jsonify(existing), 200

        created = execute_query(
            "INSERT INTO departments (name) VALUES (%s) RETURNING id, name",
            (name,), fetch_one=True
        )
        return jsonify(created), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/departments/<int:id>", methods=["DELETE"])
def delete_department(id):
    try:
        execute_query("DELETE FROM departments WHERE id = %s", (id,))
        return jsonify({"message": f"Department {id} deleted."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ==========================================
# DISCUSSIONS API
# ==========================================
@app.route("/api/discussions", methods=["GET"])
def get_discussions():
    try:
        discussions = execute_query("SELECT * FROM discussions ORDER BY date DESC", fetch_all=True)
        return jsonify(discussions)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/discussions", methods=["POST"])
def create_discussion():
    data = request.json or {}
    project_id = data.get("project_id")
    project_name = data.get("project_name")
    points = data.get("points")
    date = data.get("date")
    remarks = data.get("remarks")

    if not project_id or not project_name or not points or not date or not remarks:
        return jsonify({"error": "Missing fields"}), 400

    try:
        count_row = execute_query("SELECT COUNT(*) as count FROM discussions", fetch_one=True)
        count = count_row.get("count") if count_row else 0
        new_id = f"DSC-{str(count + 1).zfill(3)}"

        execute_query(
            "INSERT INTO discussions (id, project_id, project_name, points, date, remarks) VALUES (%s, %s, %s, %s, %s, %s)",
            (new_id, project_id, project_name, points, date, remarks)
        )
        return jsonify({
            "id": new_id, "project_id": project_id, "project_name": project_name,
            "points": points, "date": date, "remarks": remarks
        }), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/discussions/<id>", methods=["PUT"])
def update_discussion(id):
    data = request.json or {}
    project_id = data.get("project_id")
    project_name = data.get("project_name")
    points = data.get("points")
    date = data.get("date")
    remarks = data.get("remarks")

    if not project_id or not points or not date or not remarks:
        return jsonify({"error": "Missing fields"}), 400

    try:
        execute_query(
            "UPDATE discussions SET project_id = %s, project_name = %s, points = %s, date = %s, remarks = %s WHERE id = %s",
            (project_id, project_name, points, date, remarks, id)
        )
        return jsonify({"message": "Discussion log updated successfully", "id": id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/discussions/<id>", methods=["DELETE"])
def delete_discussion(id):
    try:
        execute_query("DELETE FROM discussions WHERE id = %s", (id,))
        return jsonify({"message": f"Discussion {id} deleted."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port, debug=True)
