from flask import Flask, send_from_directory, jsonify
import os
import main

app = Flask(__name__)
# The 'static_folder' argument usually points to a specific folder,
# but here we want to serve files from the root. We'll handle it manually.

@app.route('/')
def index():
    """Serves the main visualization page."""
    return send_from_directory('.', 'index.html')

@app.route('/output.czml')
def get_czml():
    """Runs the simulation and returns fresh CZML data."""
    data = main.get_czml()
    return jsonify(data)

@app.route('/<path:filename>')
def serve_static(filename):
    """Serves static files safely (images, etc.)."""
    allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.css', '.js', '.html', '.ico'}
    ext = os.path.splitext(filename)[1].lower()
    
    if ext in allowed_extensions:
        return send_from_directory('.', filename)
    return "Forbidden", 403

if __name__ == "__main__":
    print("Starting Sentinel Orbital Defense Server...")
    print("Access at http://localhost:8080")
    app.run(host='0.0.0.0', port=8080, debug=True)
