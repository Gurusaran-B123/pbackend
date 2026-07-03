import os
import json
import logging
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ProjectHealthBackend")

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# DATABASE INTEGRATION STRATEGY:
# Attempts to load Supabase PostgreSQL using psycopg2.
# Falls back to an in-memory SQLite database if credentials are not configured,
# ensuring the server stays resilient and starts successfully during local tests.

db_engine = "sqlite"
conn = None

# Attempting to load PostgreSQL connection (Supabase)
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL:
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True
        db_engine = "postgres"
        logger.info("⚡ Successfully connected to Supabase PostgreSQL database!")
        
        # Automatically set up the PostgreSQL schema on startup
        with conn.cursor() as cursor:
            # 1. Create Projects Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS projects (
                    id VARCHAR(50) PRIMARY KEY,
                    name TEXT NOT NULL,
                    status VARCHAR(50) NOT NULL CHECK (status IN ('Live', 'Workinprogress', 'Yet to start')),
                    startdate DATE NOT NULL,
                    manager VARCHAR(100) NOT NULL
                );
            """)
            # 2. Create Discussions Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS discussions (
                    id VARCHAR(50) PRIMARY KEY,
                    project_id VARCHAR(50) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    project_name TEXT NOT NULL,
                    points TEXT NOT NULL,
                    date DATE NOT NULL,
                    remarks VARCHAR(50) NOT NULL CHECK (remarks IN ('Approved', 'Not Approved', 'Information', 'For Action', 'Hold', 'Not Relevant now'))
                );
            """)
            # 3. Create Indexes for High Performance Querying
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_discussions_project ON discussions(project_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_discussions_remarks ON discussions(remarks);")
            
            # 4. Seed Initial Project Records
            cursor.execute("""
                INSERT INTO projects (id, name, status, startdate, manager) VALUES 
                ('PRJ-001', 'Apollo Phoenix Upgrade', 'Live', '2026-01-15', 'Clara Oswald'),
                ('PRJ-002', 'Enterprise Security Shield', 'Workinprogress', '2026-03-01', 'Marcus Aurelius'),
                ('PRJ-003', 'Global Logistics Sync', 'Yet to start', '2026-08-10', 'Devon Rex')
                ON CONFLICT (id) DO NOTHING;
            """)
            
            # 5. Seed Initial Discussions Records
            cursor.execute("""
                INSERT INTO discussions (id, project_id, project_name, points, date, remarks) VALUES 
                ('DSC-001', 'PRJ-001', 'Apollo Phoenix Upgrade', 'Completed phase 1 testing. API latency dropped by 34% after implementing caching cluster.', '2026-06-25', 'Approved'),
                ('DSC-002', 'PRJ-002', 'Enterprise Security Shield', 'Identified dependency issues in the auth gateway. Deploying firewall hotfixes this afternoon.', '2026-07-02', 'For Action'),
                ('DSC-003', 'PRJ-001', 'Apollo Phoenix Upgrade', 'Discussed adding multi-factor authentication requirements. Put on secondary roadmap.', '2026-06-29', 'Hold')
                ON CONFLICT (id) DO NOTHING;
            """)
        logger.info("⚡ PostgreSQL tables initialized and seeded successfully!")
    except Exception as e:
        logger.error(f"❌ PostgreSQL database setup failed: {e}. Falling back to SQLite.")
        db_engine = "sqlite"
        conn = None

if db_engine == "sqlite":
    import sqlite3
    logger.info("📂 Using a local/in-memory SQLite database.")
    # Initialize SQLite in-memory tables for immediate functionality
    conn = sqlite3.connect(":memory:", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Create tables
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            startdate TEXT NOT NULL,
            manager TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS discussions (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            project_name TEXT NOT NULL,
            points TEXT NOT NULL,
            date TEXT NOT NULL,
            remarks TEXT NOT NULL
        )
    """)
    
    # Insert seed records
    cursor.execute("SELECT COUNT(*) FROM projects")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO projects VALUES ('PRJ-001', 'Apollo Phoenix Upgrade', 'Live', '2026-01-15', 'Clara Oswald')")
        cursor.execute("INSERT INTO projects VALUES ('PRJ-002', 'Enterprise Security Shield', 'Workinprogress', '2026-03-01', 'Marcus Aurelius')")
        cursor.execute("INSERT INTO projects VALUES ('PRJ-003', 'Global Logistics Sync', 'Yet to start', '2026-08-10', 'Devon Rex')")
        
        cursor.execute("INSERT INTO discussions VALUES ('DSC-001', 'PRJ-001', 'Apollo Phoenix Upgrade', 'Completed phase 1 testing. API latency dropped by 34% after implementing caching cluster.', '2026-06-25', 'Approved')")
        cursor.execute("INSERT INTO discussions VALUES ('DSC-002', 'PRJ-002', 'Enterprise Security Shield', 'Identified dependency issues in the auth gateway. Deploying firewall hotfixes this afternoon.', '2026-07-02', 'For Action')")
        cursor.execute("INSERT INTO discussions VALUES ('DSC-003', 'PRJ-001', 'Apollo Phoenix Upgrade', 'Discussed adding multi-factor authentication requirements. Put on secondary roadmap.', '2026-06-29', 'Hold')")
    conn.commit()


# Database Helper Functions
def execute_query(query, params=(), fetch_all=False, fetch_one=False):
    if db_engine == "postgres":
        import psycopg2
        from psycopg2.extras import RealDictCursor
        global conn
        try:
            # Check connection status and reconnect if broken or uninitialized
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
    else:
        # SQLite execution
        cursor = conn.cursor()
        cursor.execute(query, params)
        if fetch_all:
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        if fetch_one:
            row = cursor.fetchone()
            return dict(row) if row else None
        conn.commit()
        return None


# API ROUTES

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "healthy",
        "database_engine": db_engine,
        "supabase_connected": db_engine == "postgres",
        "timestamp": datetime.utcnow().isoformat()
    })


# Authentication / Session Validation
@app.route("/api/login", methods=["POST"])
def login():
    data = request.json or {}
    email = data.get("email")
    role = data.get("role")
    
    if not email or not role:
        return jsonify({"error": "Missing credentials"}), 400
        
    return jsonify({
        "status": "authenticated",
        "user": {
            "email": email,
            "role": role,
            "name": "Administrator" if role == "Admin" else email.split("@")[0].capitalize()
        }
    })


# PROJECTS API
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
        # Generate ID
        count_row = execute_query("SELECT COUNT(*) as count FROM projects", fetch_one=True)
        count = count_row.get("count") if count_row else 0
        new_id = f"PRJ-{str(count + 1).zfill(3)}"
        
        execute_query(
            "INSERT INTO projects (id, name, status, startdate, manager) VALUES (%s, %s, %s, %s, %s)" if db_engine == "postgres" 
            else "INSERT INTO projects (id, name, status, startdate, manager) VALUES (?, ?, ?, ?, ?)",
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
            "UPDATE projects SET name = %s, status = %s, startdate = %s, manager = %s WHERE id = %s" if db_engine == "postgres"
            else "UPDATE projects SET name = ?, status = ?, startdate = ?, manager = ? WHERE id = ?",
            (name, status, startdate, manager, id)
        )
        return jsonify({"message": "Project updated successfully", "id": id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/projects/<id>", methods=["DELETE"])
def delete_project(id):
    try:
        execute_query(
            "DELETE FROM projects WHERE id = %s" if db_engine == "postgres"
            else "DELETE FROM projects WHERE id = ?",
            (id,)
        )
        # Also clean up related discussions as cascading delete
        execute_query(
            "DELETE FROM discussions WHERE project_id = %s" if db_engine == "postgres"
            else "DELETE FROM discussions WHERE project_id = ?",
            (id,)
        )
        return jsonify({"message": f"Project {id} and its discussions removed."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# DISCUSSIONS API
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
        # Generate ID
        count_row = execute_query("SELECT COUNT(*) as count FROM discussions", fetch_one=True)
        count = count_row.get("count") if count_row else 0
        new_id = f"DSC-{str(count + 1).zfill(3)}"
        
        execute_query(
            "INSERT INTO discussions (id, project_id, project_name, points, date, remarks) VALUES (%s, %s, %s, %s, %s, %s)" if db_engine == "postgres"
            else "INSERT INTO discussions (id, project_id, project_name, points, date, remarks) VALUES (?, ?, ?, ?, ?, ?)",
            (new_id, project_id, project_name, points, date, remarks)
        )
        return jsonify({"id": new_id, "project_id": project_id, "points": points, "date": date, "remarks": remarks}), 201
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
            "UPDATE discussions SET project_id = %s, project_name = %s, points = %s, date = %s, remarks = %s WHERE id = %s" if db_engine == "postgres"
            else "UPDATE discussions SET project_id = ?, project_name = ?, points = ?, date = ?, remarks = ? WHERE id = ?",
            (project_id, project_name, points, date, remarks, id)
        )
        return jsonify({"message": "Discussion log updated successfully", "id": id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/discussions/<id>", methods=["DELETE"])
def delete_discussion(id):
    try:
        execute_query(
            "DELETE FROM discussions WHERE id = %s" if db_engine == "postgres"
            else "DELETE FROM discussions WHERE id = ?",
            (id,)
        )
        return jsonify({"message": f"Discussion {id} deleted."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    # Render and Cloud Run expect port 3000 or the PORT environment variable
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port, debug=True)
