from flask import Flask, render_template, request
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

app = Flask(__name__)

ph = PasswordHasher()

# Demo account
username = "admin"
password = "admin"

password_hash = ph.hash(password)

@app.route("/")
def hello():
    return render_template("login.html")

@app.route("/login", methods=["POST"])
def login():
    username_input = request.form.get("username", "")
    password_input = request.form.get("password", "")

    if username_input != username:
        return "Invalid username", 401

    try:
        ph.verify(password_hash, password_input)
        return render_template("login.html")

    except VerifyMismatchError:
        return "Invalid username or password", 401


if __name__ == "__main__":
    app.run(debug=True)
