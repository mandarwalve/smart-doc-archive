from flask import Flask, request, render_template, redirect, url_for, session, flash
import pymysql
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os


# --------------------------------------------------
# FLASK APP
# --------------------------------------------------

app = Flask(__name__)
app.secret_key = "smart-document-archive-secret-key"


# --------------------------------------------------
# MYSQL CONFIGURATION
# --------------------------------------------------

DB_HOST = "localhost"
DB_USER = "app_user"
DB_PASSWORD = "mandar@1411"
DB_NAME = "doc_archive"
DB_PORT = 3306


# --------------------------------------------------
# UPLOAD CONFIGURATION
# --------------------------------------------------

UPLOAD_FOLDER = "uploads"

ALLOWED_EXTENSIONS = {
    "pdf",
    "png",
    "jpg",
    "jpeg",
    "doc",
    "docx",
    "txt",
    "xls",
    "xlsx",
    "ppt",
    "pptx"
}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024

os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# --------------------------------------------------
# DATABASE CONNECTION
# --------------------------------------------------

def get_db_connection():
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        port=DB_PORT,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True
    )


# --------------------------------------------------
# CHECK FILE EXTENSION
# --------------------------------------------------

def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


# --------------------------------------------------
# HOME
# --------------------------------------------------

@app.route("/")
def home():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    return render_template("base.html")


# --------------------------------------------------
# REGISTER
# --------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not username or not password:
            flash("Username and password are required.")
            return redirect(url_for("register"))

        if len(password) < 6:
            flash("Password must contain at least 6 characters.")
            return redirect(url_for("register"))

        password_hash = generate_password_hash(password)

        connection = None

        try:
            connection = get_db_connection()

            with connection.cursor() as cursor:

                cursor.execute(
                    """
                    SELECT id
                    FROM users
                    WHERE username = %s
                    """,
                    (username,)
                )

                existing_user = cursor.fetchone()

                if existing_user:
                    flash("Username already exists.")
                    return redirect(url_for("register"))

                cursor.execute(
                    """
                    INSERT INTO users
                    (username, password_hash)
                    VALUES (%s, %s)
                    """,
                    (username, password_hash)
                )

            flash("Registration successful. Please login.")
            return redirect(url_for("login"))

        except pymysql.MySQLError as error:

            print("Registration database error:", error)
            flash("Database error during registration.")
            return redirect(url_for("register"))

        finally:

            if connection:
                connection.close()

    return render_template("register.html")


# --------------------------------------------------
# LOGIN
# --------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        connection = None

        try:

            connection = get_db_connection()

            with connection.cursor() as cursor:

                cursor.execute(
                    """
                    SELECT id, username, password_hash
                    FROM users
                    WHERE username = %s
                    """,
                    (username,)
                )

                user = cursor.fetchone()

            if user and check_password_hash(
                user["password_hash"],
                password
            ):

                session["user_id"] = user["id"]
                session["username"] = user["username"]

                return redirect(url_for("dashboard"))

            flash("Invalid username or password.")
            return redirect(url_for("login"))

        except pymysql.MySQLError as error:

            print("Login database error:", error)
            flash("Database error during login.")
            return redirect(url_for("login"))

        finally:

            if connection:
                connection.close()

    return render_template("login.html")


# --------------------------------------------------
# LOGOUT
# --------------------------------------------------

@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("login"))


# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------

@app.route("/dashboard")
def dashboard():

    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = None

    try:

        connection = get_db_connection()

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    id,
                    title,
                    description,
                    file_name,
                    mime_type,
                    file_size,
                    created_at
                FROM documents
                WHERE user_id = %s
                ORDER BY created_at DESC
                """,
                (session["user_id"],)
            )

            documents = cursor.fetchall()

        return render_template(
            "dashboard.html",
            documents=documents,
            username=session.get("username")
        )

    except pymysql.MySQLError as error:

        print("Dashboard database error:", error)
        flash("Unable to load documents.")
        return redirect(url_for("login"))

    finally:

        if connection:
            connection.close()


# --------------------------------------------------
# UPLOAD
# --------------------------------------------------

@app.route("/upload", methods=["GET", "POST"])
def upload():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":

        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()

        file = request.files.get("file")

        if not title:
            flash("Document title is required.")
            return redirect(url_for("upload"))

        if not file or file.filename == "":
            flash("Please select a file.")
            return redirect(url_for("upload"))

        if not allowed_file(file.filename):
            flash("This file type is not allowed.")
            return redirect(url_for("upload"))

        filename = secure_filename(file.filename)

        user_folder = os.path.join(
            app.config["UPLOAD_FOLDER"],
            str(session["user_id"])
        )

        os.makedirs(user_folder, exist_ok=True)

        file_path = os.path.join(
            user_folder,
            filename
        )

        try:

            file.save(file_path)

            file_size = os.path.getsize(file_path)

            connection = get_db_connection()

            try:

                with connection.cursor() as cursor:

                    cursor.execute(
                        """
                        INSERT INTO documents
                        (
                            user_id,
                            title,
                            description,
                            s3_key,
                            file_name,
                            mime_type,
                            file_size
                        )
                        VALUES
                        (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            session["user_id"],
                            title,
                            description,
                            file_path,
                            filename,
                            file.content_type,
                            file_size
                        )
                    )

                    document_id = cursor.lastrowid

                    cursor.execute(
                        """
                        INSERT INTO audit_log
                        (
                            user_id,
                            document_id,
                            action
                        )
                        VALUES
                        (%s, %s, %s)
                        """,
                        (
                            session["user_id"],
                            document_id,
                            "UPLOAD"
                        )
                    )

                flash("Document uploaded successfully.")
                return redirect(url_for("dashboard"))

            finally:

                connection.close()

        except Exception as error:

            print("Upload error:", error)
            flash("Unable to upload document.")
            return redirect(url_for("upload"))

    return render_template("upload.html")


# --------------------------------------------------
# DOWNLOAD / VIEW DOCUMENT
# --------------------------------------------------

@app.route("/download/<int:doc_id>")
def download(doc_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = None

    try:

        connection = get_db_connection()

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT
                    id,
                    file_name,
                    s3_key
                FROM documents
                WHERE id = %s
                AND user_id = %s
                """,
                (
                    doc_id,
                    session["user_id"]
                )
            )

            document = cursor.fetchone()

            if not document:
                flash("Document not found.")
                return redirect(url_for("dashboard"))

            cursor.execute(
                """
                INSERT INTO audit_log
                (
                    user_id,
                    document_id,
                    action
                )
                VALUES
                (%s, %s, %s)
                """,
                (
                    session["user_id"],
                    doc_id,
                    "VIEW"
                )
            )

        file_path = document["s3_key"]

        if not os.path.exists(file_path):
            flash("File does not exist on the server.")
            return redirect(url_for("dashboard"))

        from flask import send_file

        return send_file(
            file_path,
            as_attachment=True,
            download_name=document["file_name"]
        )

    except Exception as error:

        print("Download error:", error)
        flash("Unable to download document.")
        return redirect(url_for("dashboard"))

    finally:

        if connection:
            connection.close()


# --------------------------------------------------
# DELETE DOCUMENT
# --------------------------------------------------

@app.route("/delete/<int:doc_id>", methods=["POST"])
def delete(doc_id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    connection = None

    try:

        connection = get_db_connection()

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT s3_key
                FROM documents
                WHERE id = %s
                AND user_id = %s
                """,
                (
                    doc_id,
                    session["user_id"]
                )
            )

            document = cursor.fetchone()

            if not document:
                flash("Document not found.")
                return redirect(url_for("dashboard"))

            file_path = document["s3_key"]

            cursor.execute(
                """
                INSERT INTO audit_log
                (
                    user_id,
                    document_id,
                    action
                )
                VALUES
                (%s, %s, %s)
                """,
                (
                    session["user_id"],
                    doc_id,
                    "DELETE"
                )
            )

            cursor.execute(
                """
                DELETE FROM documents
                WHERE id = %s
                AND user_id = %s
                """,
                (
                    doc_id,
                    session["user_id"]
                )
            )

        if file_path and os.path.exists(file_path):
            os.remove(file_path)

        flash("Document deleted successfully.")
        return redirect(url_for("dashboard"))

    except Exception as error:

        print("Delete error:", error)
        flash("Unable to delete document.")
        return redirect(url_for("dashboard"))

    finally:

        if connection:
            connection.close()


# --------------------------------------------------
# SEARCH DOCUMENTS
# --------------------------------------------------

@app.route("/search")
def search():

    if "user_id" not in session:
        return redirect(url_for("login"))

    query = request.args.get("q", "").strip()

    connection = None

    try:

        connection = get_db_connection()

        with connection.cursor() as cursor:

            search_value = f"%{query}%"

            cursor.execute(
                """
                SELECT
                    id,
                    title,
                    description,
                    file_name,
                    mime_type,
                    file_size,
                    created_at
                FROM documents
                WHERE user_id = %s
                AND (
                    title LIKE %s
                    OR description LIKE %s
                    OR file_name LIKE %s
                )
                ORDER BY created_at DESC
                """,
                (
                    session["user_id"],
                    search_value,
                    search_value,
                    search_value
                )
            )

            documents = cursor.fetchall()

        return render_template(
            "dashboard.html",
            documents=documents,
            username=session.get("username"),
            search_query=query
        )

    except pymysql.MySQLError as error:

        print("Search database error:", error)
        flash("Search failed.")
        return redirect(url_for("dashboard"))

    finally:

        if connection:
            connection.close()


# --------------------------------------------------
# TEST ROUTE
# --------------------------------------------------

@app.route("/test-db")
def test_db():

    connection = None

    try:

        connection = get_db_connection()

        with connection.cursor() as cursor:

            cursor.execute("SELECT DATABASE() AS database_name")

            result = cursor.fetchone()

        return f"""
        <h2>MySQL Connected Successfully!</h2>
        <p>Database: {result['database_name']}</p>
        """

    except Exception as error:

        return f"""
        <h2>MySQL Connection Failed</h2>
        <p>{error}</p>
        """

    finally:

        if connection:
            connection.close()


# --------------------------------------------------
# RUN APPLICATION
# --------------------------------------------------

if __name__ == "__main__":

    print("Starting Smart Document Archive...")

    try:

        connection = get_db_connection()
        connection.close()

        print("MySQL connected successfully!")

    except Exception as error:

        print("MySQL connection failed:")
        print(error)

    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )