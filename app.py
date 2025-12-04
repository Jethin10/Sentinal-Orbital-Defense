from flask import Flask, send_from_directory, jsonify
import os
import main
import threading
import time
import json

app = Flask(__name__)

# Global cache file path
CACHE_FILE = 'simulation_cache.json'

def simulation_loop():
    """Background thread that updates the simulation data every 30 minutes."""
    print("[SERVER] Starting Background Simulation Loop...")
    while True:
        try:
            print("[SERVER] Running simulation update...")
            # Run the heavy simulation
            data = main.get_czml()
            
            # Write to disk atomically (write to temp then rename) to prevent read errors
            temp_file = CACHE_FILE + '.tmp'
            with open(temp_file, 'w') as f:
                json.dump(data, f)
            os.replace(temp_file, CACHE_FILE)
            
            print("[SERVER] Simulation cache updated successfully.")
        except Exception as e:
            print(f"[SERVER] Error in simulation loop: {e}")
        
        # Sleep for 30 minutes before next update
        time.sleep(1800)

def start_background_thread():
    # Check if a thread is already running to avoid duplicates in some environments
    # (Simple check, mainly for local dev reloads)
    for thread in threading.enumerate():
        if thread.name == "SimulationThread":
            return

    thread = threading.Thread(target=simulation_loop, name="SimulationThread", daemon=True)
    thread.start()

# Start the background thread immediately when app loads
start_background_thread()

@app.route('/')
def index():
    """Serves the main visualization page."""
    return send_from_directory('.', 'index.html')

@app.route('/output.czml')
def get_czml():
    """Serves the cached CZML data instantly."""
    if os.path.exists(CACHE_FILE):
        # Serve the cached file directly
        with open(CACHE_FILE, 'r') as f:
            data = json.load(f)
        return jsonify(data)
    else:
        # If simulation hasn't finished the first run yet
        return jsonify({
            "id": "document",
            "version": "1.0",
            "description": "Simulation initializing... please retry in 30 seconds."
        }), 503

@app.route('/<path:filename>')
def serve_static(filename):
    """Serves static files safely (images, etc.)."""
    allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.css', '.js', '.html', '.ico', '.tle'}
    ext = os.path.splitext(filename)[1].lower()
    
    if ext in allowed_extensions:
        return send_from_directory('.', filename)
    return "Forbidden", 403

if __name__ == "__main__":
    print("Starting Sentinel Orbital Defense Server...")
    print("Access at http://localhost:8080")
    app.run(host='0.0.0.0', port=8080, debug=True)