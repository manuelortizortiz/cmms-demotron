from flask import Flask, jsonify
app = Flask(__name__)

@app.route("/")
def home():
    return "CMMS DEMOTRON PRODUCCION OK"

@app.route("/api/version")
def version():
    return {"version":"DEMOTRON_PRODUCCION","status":"ok"}

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
