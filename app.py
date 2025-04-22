# Consolidated Server (app.py)
# Flask web server with SocketIO, HTML, CSS, and JS embedded.

import os
import base64
from flask import Flask, request, session, redirect, url_for, render_template_string, Response
from flask_socketio import SocketIO, emit, join_room, leave_room, disconnect
import eventlet # Required for async_mode='eventlet'
# Use eventlet for async operations
# !!! IMPORTANT: This MUST be called before importing Flask or SocketIO !!!
eventlet.monkey_patch()


# --- Configuration ---
# Use environment variables for secrets; provide defaults for local testing if needed.
# !! Ensure strong, unique values are set in your production environment !!
SECRET_KEY = os.environ.get('FLASK_SECRET_KEY', 'change_this_strong_secret_key_12345_local_dev')
ACCESS_PASSWORD = os.environ.get('REMOTE_ACCESS_PASSWORD', 'change_this_password_too_local_dev')

# --- Flask App Setup ---
app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
# Consider adding configuration for session cookie security (HttpOnly, Secure in production)
# app.config['SESSION_COOKIE_SECURE'] = True # Enable if using HTTPS
# app.config['SESSION_COOKIE_HTTPONLY'] = True
# app.config['SESSION_COOKIE_SAMESITE'] = 'Lax' # Or 'Strict'

socketio = SocketIO(app, async_mode='eventlet')

# --- Global Variables ---
# Stores the SocketIO SID of the currently connected and registered client PC
client_pc_sid = None

# --- Authentication ---
def check_auth(password):
    """Checks if the provided password matches the access password."""
    # Use a more secure comparison method if possible in high-security scenarios,
    # though for this use case, direct comparison might be acceptable.
    return password == ACCESS_PASSWORD

# --- HTML Templates (as strings) ---

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Remote Control - Login</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Inter', sans-serif; }
    </style>
</head>
<body class="bg-gray-100 flex items-center justify-center h-screen">
    <div class="bg-white p-8 rounded-lg shadow-md w-full max-w-sm">
        <h1 class="text-2xl font-semibold text-center text-gray-700 mb-6">Remote Access Login</h1>
        {% if error %}
            <div class="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded relative mb-4" role="alert">
                <span class="block sm:inline">{{ error }}</span>
            </div>
        {% endif %}
        <form method="POST" action="{{ url_for('index') }}">
            <div class="mb-4">
                <label for="password" class="block text-gray-700 text-sm font-medium mb-2">Password</label>
                <input type="password" id="password" name="password" required
                       class="w-full px-4 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                       placeholder="Enter access password">
            </div>
            <button type="submit"
                    class="w-full bg-blue-600 hover:bg-blue-700 text-white font-semibold py-2 px-4 rounded-md transition duration-200 ease-in-out">
                Login
            </button>
        </form>
    </div>
</body>
</html>
"""

INTERFACE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Remote Control Interface</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.4/socket.io.min.js"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        /* Embedded CSS */
        body {
            font-family: 'Inter', sans-serif;
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        #screen-view img {
            max-width: 100%;
            height: auto;
            display: block;
            cursor: crosshair;
            background-color: #333; /* Placeholder background */
        }
        #screen-view {
            width: 100%;
            overflow: hidden;
            position: relative; /* Needed for absolute positioning of click feedback */
        }
        .status-dot {
            height: 10px;
            width: 10px;
            border-radius: 50%;
            display: inline-block;
            margin-right: 5px;
        }
        .status-connected { background-color: #4ade80; } /* green-400 */
        .status-disconnected { background-color: #f87171; } /* red-400 */
        .status-connecting { background-color: #fbbf24; } /* amber-400 */

        .click-feedback {
            position: absolute;
            border: 2px solid red;
            border-radius: 50%;
            width: 20px;
            height: 20px;
            transform: translate(-50%, -50%) scale(0);
            pointer-events: none;
            background-color: rgba(255, 0, 0, 0.3);
            animation: click-pulse 0.4s ease-out forwards;
        }
        @keyframes click-pulse {
            0% { transform: translate(-50%, -50%) scale(0.5); opacity: 1; }
            100% { transform: translate(-50%, -50%) scale(2); opacity: 0; }
        }
    </style>
</head>
<body class="bg-gray-200 flex flex-col h-screen">

    <header class="bg-gray-800 text-white p-4 flex justify-between items-center shadow-md">
        <h1 class="text-xl font-semibold">Remote Desktop Control</h1>
        <div class="flex items-center space-x-4">
            <div id="connection-status" class="flex items-center text-sm">
                <span id="status-dot" class="status-dot status-connecting"></span>
                <span id="status-text">Connecting...</span>
            </div>
             <a href="{{ url_for('logout') }}" class="bg-red-600 hover:bg-red-700 text-white text-sm font-medium py-1 px-3 rounded-md transition duration-150 ease-in-out">Logout</a>
        </div>
    </header>

    <main class="flex-grow flex flex-col md:flex-row p-4 gap-4 overflow-hidden">
        <div class="flex-grow bg-black rounded-lg shadow-inner flex items-center justify-center overflow-hidden" id="screen-view-container">
            <div id="screen-view">
                 <img id="screen-image" src="https://placehold.co/1920x1080/333333/CCCCCC?text=Waiting+for+Remote+Screen+(1080p)" alt="Remote Screen"
                      onerror="this.onerror=null; this.src='https://placehold.co/600x338/333333/CCCCCC?text=Error+Loading+Screen';">
            </div>
        </div>

        <aside class="w-full md:w-64 bg-white p-4 rounded-lg shadow-md flex flex-col space-y-4 overflow-y-auto">
            <h2 class="text-lg font-semibold text-gray-700 border-b pb-2">Controls</h2>
            <div>
                <label for="keyboard-input" class="block text-sm font-medium text-gray-600 mb-1">Keyboard Input</label>
                <input type="text" id="keyboard-input" placeholder="Type here and press Enter"
                       class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-blue-500">
                 <p class="text-xs text-gray-500 mt-1">Sends text on Enter.</p>
            </div>
            <div>
                 <label class="block text-sm font-medium text-gray-600 mb-1">Mouse Clicks</label>
                 <div class="grid grid-cols-2 gap-2">
                      <button id="left-click-btn" class="bg-blue-500 hover:bg-blue-600 text-white font-medium py-2 px-4 rounded-md text-sm">Left Click</button>
                      <button id="right-click-btn" class="bg-green-500 hover:bg-green-600 text-white font-medium py-2 px-4 rounded-md text-sm">Right Click</button>
                 </div>
                 <p class="text-xs text-gray-500 mt-1">Click image for positional clicks.</p>
            </div>
            </aside>
    </main>

    <script>
        // Embedded JavaScript
        document.addEventListener('DOMContentLoaded', () => {
            const socket = io(window.location.origin, { path: '/socket.io/' });
            const screenImage = document.getElementById('screen-image');
            const screenView = document.getElementById('screen-view');
            const keyboardInput = document.getElementById('keyboard-input');
            const leftClickBtn = document.getElementById('left-click-btn');
            const rightClickBtn = document.getElementById('right-click-btn');
            const connectionStatusDot = document.getElementById('status-dot');
            const connectionStatusText = document.getElementById('status-text');
            let remoteScreenWidth = null;
            let remoteScreenHeight = null;

            function updateStatus(status, message) {
                connectionStatusText.textContent = message;
                connectionStatusDot.className = `status-dot ${status}`;
            }

            function showClickFeedback(x, y) {
                const feedback = document.createElement('div');
                feedback.className = 'click-feedback';
                feedback.style.left = `${x}px`;
                feedback.style.top = `${y}px`;
                screenView.appendChild(feedback);
                setTimeout(() => { feedback.remove(); }, 400);
            }

            socket.on('connect', () => {
                console.log('Connected to server via WebSocket');
                updateStatus('status-connecting', 'Connected to server, waiting for remote PC...');
                // Request initial state if needed (e.g., ask server if client is already connected)
                // socket.emit('request_client_status'); // Example custom event
            });

            socket.on('disconnect', () => {
                console.warn('Disconnected from server');
                updateStatus('status-disconnected', 'Server disconnected');
                screenImage.src = 'https://placehold.co/1920x1080/555555/CCCCCC?text=Server+Disconnected';
                remoteScreenWidth = null; remoteScreenHeight = null;
            });

            socket.on('connect_error', (error) => {
                console.error('Connection Error:', error);
                updateStatus('status-disconnected', 'Connection Error');
                screenImage.src = 'https://placehold.co/1920x1080/555555/CCCCCC?text=Connection+Error';
            });

            // Listen for client PC status updates
            socket.on('client_connected', (data) => {
                console.log(data.message);
                updateStatus('status-connected', 'Remote PC Connected');
            });

            socket.on('client_disconnected', (data) => {
                console.warn(data.message);
                updateStatus('status-disconnected', 'Remote PC Disconnected');
                screenImage.src = 'https://placehold.co/1920x1080/444444/CCCCCC?text=Remote+PC+Disconnected';
                remoteScreenWidth = null; remoteScreenHeight = null;
            });

            // Handle screen updates from the server
            socket.on('screen_update', (data) => {
                const imageSrc = `data:image/jpeg;base64,${data.image}`;
                screenImage.src = imageSrc;

                // Auto-detect resolution from the first image received
                // This logic seems fine, using an intermediate image object for dimensions
                if (remoteScreenWidth === null || remoteScreenHeight === null) {
                    const tempImg = new Image();
                    tempImg.onload = () => {
                        if (remoteScreenWidth === null) { // Check again inside callback in case of race condition
                            remoteScreenWidth = tempImg.naturalWidth;
                            remoteScreenHeight = tempImg.naturalHeight;
                            console.log(`Remote screen resolution detected: ${remoteScreenWidth}x${remoteScreenHeight}`);
                        }
                    };
                    tempImg.onerror = () => {
                        console.error("Error loading image to detect dimensions.");
                        // Reset placeholder if needed
                        // screenImage.src = 'https://placehold.co/600x338/333333/CCCCCC?text=Error+Reading+Screen+Dimensions';
                    };
                    tempImg.src = imageSrc; // Set src to trigger load
                }
            });

            // Handle errors sent from the server (e.g., client PC not connected)
            socket.on('command_error', (data) => {
                console.error('Command Error:', data.message);
                alert(`Command Error: ${data.message}`); // Simple alert for user feedback
            });

            // --- Event Listeners for Controls ---

            // Handle clicks on the screen image
            screenImage.addEventListener('click', (event) => {
                if (!remoteScreenWidth || !remoteScreenHeight) {
                    console.warn("Remote screen dimensions not yet known. Click ignored.");
                    return;
                }
                const rect = screenImage.getBoundingClientRect();
                const x = event.clientX - rect.left; // Click position relative to image element
                const y = event.clientY - rect.top;

                // Calculate corresponding coordinates on the remote screen
                const remoteX = Math.round((x / rect.width) * remoteScreenWidth);
                const remoteY = Math.round((y / rect.height) * remoteScreenHeight);

                console.log(`Screen clicked: display(${x.toFixed(0)}, ${y.toFixed(0)}), remote(${remoteX}, ${remoteY})`);

                // Show visual feedback on the interface
                showClickFeedback(x, y);

                // Send the click command with coordinates
                const clickCommand = { action: 'click', button: 'left', x: remoteX, y: remoteY };
                socket.emit('control_command', clickCommand);
                console.log('Sent left click command:', clickCommand);
            });

            // Handle right-clicks on the screen image
            screenImage.addEventListener('contextmenu', (event) => {
                event.preventDefault(); // Prevent browser context menu
                if (!remoteScreenWidth || !remoteScreenHeight) {
                     console.warn("Remote screen dimensions not yet known. Right-click ignored.");
                     return;
                }
                const rect = screenImage.getBoundingClientRect();
                const x = event.clientX - rect.left;
                const y = event.clientY - rect.top;
                const remoteX = Math.round((x / rect.width) * remoteScreenWidth);
                const remoteY = Math.round((y / rect.height) * remoteScreenHeight);

                console.log(`Screen right-clicked: display(${x.toFixed(0)}, ${y.toFixed(0)}), remote(${remoteX}, ${remoteY})`);

                showClickFeedback(x, y); // Use same feedback for right click

                const clickCommand = { action: 'click', button: 'right', x: remoteX, y: remoteY };
                socket.emit('control_command', clickCommand);
                console.log('Sent right click command:', clickCommand);
            });

            // Button clicks (without coordinates - clicks at current cursor position on remote)
            leftClickBtn.addEventListener('click', () => {
                socket.emit('control_command', { action: 'click', button: 'left' });
                console.log('Sent left click command (button)');
            });

            rightClickBtn.addEventListener('click', () => {
                socket.emit('control_command', { action: 'click', button: 'right' });
                console.log('Sent right click command (button)');
            });

            // Keyboard input handling
            keyboardInput.addEventListener('keypress', (event) => {
                if (event.key === 'Enter') {
                    event.preventDefault(); // Prevent form submission if inside one
                    const text = keyboardInput.value;
                    if (text) {
                        // Send the whole string
                        const command = { action: 'keypress', key: text, is_string: true };
                        socket.emit('control_command', command);
                        console.log('Sent keypress command (string):', command);
                        keyboardInput.value = ''; // Clear the input field
                    }
                }
                // Could add handling for single key presses (non-Enter) if needed
            });

            // Initial status
            updateStatus('status-connecting', 'Initializing...');

        }); // End DOMContentLoaded
    </script>
</body>
</html>
"""

# --- Flask Routes ---
@app.route('/', methods=['GET', 'POST'])
def index():
    """Handles login attempts and shows the login page."""
    if request.method == 'POST':
        password = request.form.get('password')
        if check_auth(password):
            session['authenticated'] = True
            # *** FIXED: Cannot access request.sid here. Log remote IP instead. ***
            print(f"Login successful for user at: {request.remote_addr}") # Log successful login
            return redirect(url_for('interface'))
        else:
            # *** FIXED: Cannot access request.sid here. Log remote IP instead. ***
            print(f"Login failed for user at: {request.remote_addr}") # Log failed login
            return render_template_string(LOGIN_HTML, error="Invalid password")

    # If already authenticated (e.g., user refreshes page), redirect to interface
    if session.get('authenticated'):
        return redirect(url_for('interface'))

    # Show login page for GET requests or if authentication fails
    return render_template_string(LOGIN_HTML)

@app.route('/interface')
def interface():
    """Shows the main remote control interface if authenticated."""
    if not session.get('authenticated'):
        # *** FIXED: Cannot access request.sid here. Log remote IP instead. ***
        print(f"Unauthorized access attempt to /interface from {request.remote_addr}") # Log unauthorized access
        return redirect(url_for('index'))
    # User is authenticated, show the main interface
    return render_template_string(INTERFACE_HTML)

@app.route('/logout')
def logout():
    """Logs the user out by clearing the session."""
    # *** FIXED: Cannot access request.sid here. Log remote IP instead. ***
    print(f"Logging out user from: {request.remote_addr}") # Log logout action
    session.pop('authenticated', None)
    return redirect(url_for('index'))

# --- SocketIO Events ---
@socketio.on('connect')
def handle_connect():
    """Handles new SocketIO connections (both web interface and potentially client PC)."""
    # Note: Authentication for web interface happens via Flask session check in routes.
    # Authentication for client PC happens via 'register_client' event below.
    print(f"Socket connected: {request.sid}") # request.sid IS valid here in SocketIO handler
    # Check if a client PC is already connected and notify the new web interface connection
    if client_pc_sid:
        emit('client_connected', {'message': 'Remote PC already connected'}, room=request.sid)
    else:
        # Optionally notify that the client PC is not yet connected
        emit('client_disconnected', {'message': 'Remote PC not connected yet'}, room=request.sid)


@socketio.on('disconnect')
def handle_disconnect():
    """Handles SocketIO disconnections."""
    global client_pc_sid
    print(f"Socket disconnected: {request.sid}")
    # Check if the disconnecting socket IS the registered client PC
    if request.sid == client_pc_sid:
        print(f"Client PC ({request.sid}) disconnected.")
        client_pc_sid = None
        # Notify all connected web interfaces that the client PC is gone
        # broadcast=True sends to all clients EXCEPT the sender (who is disconnecting anyway)
        emit('client_disconnected', {'message': 'Remote PC disconnected'}, broadcast=True)

@socketio.on('register_client')
def handle_register_client(data):
    """Handles the registration attempt from the client PC."""
    global client_pc_sid
    client_token = data.get('token') # Client PC should send its password as 'token'

    if client_token == ACCESS_PASSWORD:
        print(f"Client PC registration attempt from {request.sid}...")
        # If a *different* client PC was already connected, disconnect it first.
        if client_pc_sid and client_pc_sid != request.sid:
             print(f"New client PC ({request.sid}) connecting, disconnecting old one ({client_pc_sid}).")
             # Trigger the 'disconnect' handler for the old client
             socketio.disconnect(client_pc_sid) # Default silent=False is good here

        # Whether it's new or the same one re-registering, store its SID
        client_pc_sid = request.sid
        print(f"Client PC registered successfully: {client_pc_sid}")

        # Notify all connected web interfaces that a client PC is now ready
        emit('client_connected', {'message': 'Remote PC connected'}, broadcast=True)
        # Send confirmation back specifically to the client PC that just registered
        emit('registration_success', {'message': 'Registration successful'}, room=request.sid)
    else:
        # Authentication failed for the client PC trying to register
        print(f"Client PC authentication failed for SID: {request.sid}. Token received: '{client_token}'")
        emit('registration_fail', {'message': 'Authentication failed'}, room=request.sid)
        # Disconnect this unauthorized client PC immediately
        disconnect(request.sid) # disconnect() is a Flask-SocketIO function

@socketio.on('screen_data')
def handle_screen_data(data):
    """Receives screen data from the client PC and broadcasts it to web interfaces."""
    # Ensure this function only processes data from the *currently registered* client PC
    if request.sid != client_pc_sid:
        # Silently ignore data if it's not from the registered client PC.
        # Logging here can be very noisy if other sockets somehow send this event.
        # print(f"Ignoring screen_data from non-client SID: {request.sid}")
        return

    try:
        image_data = data.get('image')
        if image_data:
            # *** RE-ENABLED BROADCAST ***
            # Send the image data to all connected web interfaces
            emit('screen_update', {'image': image_data}, broadcast=True, include_self=False)

            # Optional: Reduce logging frequency for performance
            # import time
            # if not hasattr(handle_screen_data, 'last_log_time') or time.time() - handle_screen_data.last_log_time > 5:
            #     print(f"Received and broadcast screen data from {request.sid}, size: {len(image_data)} bytes.")
            #     handle_screen_data.last_log_time = time.time()

        else:
            print(f"Received empty screen data package from client PC {request.sid}.")

    except Exception as e:
        print(f"!!! ERROR in handle_screen_data processing data from SID {request.sid}: {e}")
        # Consider adding full traceback for debugging:
        # import traceback
        # print(traceback.format_exc())
        # Optionally disconnect the client if errors persist, but be cautious
        # if client_pc_sid == request.sid:
        #     print(f"Disconnecting client PC {request.sid} due to error in handle_screen_data.")
        #     disconnect(request.sid)

@socketio.on('control_command')
def handle_control_command(data):
    """Receives control commands from an authenticated web interface and forwards to the client PC."""
    # IMPORTANT: Verify the sender is an *authenticated web interface* using the Flask session
    if not session.get('authenticated'):
        print(f"Unauthenticated control command attempt from {request.sid}. Command ignored.")
        # Optionally emit an error back, but this might reveal authentication status
        # emit('command_error', {'message': 'Not authenticated'}, room=request.sid)
        return # Stop processing unauthenticated commands

    # If the web interface is authenticated, proceed
    if client_pc_sid:
        # Forward the command specifically to the registered client PC
        # print(f"Forwarding command from web {request.sid} to client PC ({client_pc_sid}): {data}") # Debug log
        emit('command', data, room=client_pc_sid)
    else:
        # No client PC is connected to receive the command
        print(f"Control command from web {request.sid} received, but no client PC connected.")
        emit('command_error', {'message': 'Client PC not connected'}, room=request.sid) # Notify sender


# --- Main Execution ---
if __name__ == '__main__':
    print("Starting Flask-SocketIO server...")
    # Get port from environment variable 'PORT' (used by Render, Heroku, etc.)
    # Default to 5000 if 'PORT' is not set (for local development)
    port = int(os.environ.get('PORT', 5000))
    # Host '0.0.0.0' makes the server accessible externally (important for Render)
    host = '0.0.0.0'
    print(f"Server starting on host {host}, port {port}")

    # Run the SocketIO server using eventlet
    # debug=False is crucial for production and when using eventlet/gevent workers
    # Gunicorn will manage workers; this block is mainly for local `python app.py` execution
    try:
        socketio.run(app, host=host, port=port, debug=False)
    except KeyboardInterrupt:
        print("Server shutting down.")
    except Exception as e:
        print(f"Failed to start server: {e}")


    # Note for Render deployment:
    # Your Render 'Start Command' should typically use gunicorn:
    # web: gunicorn --worker-class eventlet -w 1 app:app
    # Ensure 'gunicorn' and 'eventlet' are listed in your requirements.txt file.
    # The '-w 1' (1 worker) is often recommended with SocketIO and eventlet/gevent
    # to simplify state management, but adjust based on load testing if needed.
