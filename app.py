# -*- coding: utf-8 -*-
from flask import Flask, render_template

APP_VERSION = "0.4.3"
app = Flask(__name__)

@app.route("/")
def index():
    return render_template("index.html", version=APP_VERSION)

@app.route("/api/version")
def version():
    return {"version": APP_VERSION}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
