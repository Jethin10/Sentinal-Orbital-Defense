import http.server
import socketserver
import webbrowser
import threading
import time
import os
import sys

PORT = 8000
DIRECTORY = os.path.dirname(os.path.abspath(__file__))

class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

def start_server():
    """Starts the HTTP server in a thread."""
    with socketserver.TCPServer(('', PORT), Handler) as httpd:
        print(f"Serving at http://localhost:{PORT}")
        httpd.serve_forever()

if __name__ == "__main__":
    # Change to the script's directory to ensure correct file serving
    os.chdir(DIRECTORY)
    
    # Start server in a separate thread
    server_thread = threading.Thread(target=start_server)
    server_thread.daemon = True
    server_thread.start()
    
    # Wait a moment for the server to start
    time.sleep(1)
    
    # Open the browser
    url = f"http://localhost:{PORT}/index.html"
    print(f"Opening {url}...")
    webbrowser.open(url)
    
    print("Press Ctrl+C to stop the server.")
    
    try:
        # Keep the main thread alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping server...")
        sys.exit(0)
