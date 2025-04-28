from flask import Flask

app = Flask(__name__)

@app.route("/", methods=["GET", "POST"])
def home():
    return "✅ Cloud Run via GitHub Auto Deploy!", 200

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
