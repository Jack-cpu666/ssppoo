# Consolidated Server (app.py)
# Flask web server with SocketIO, HTML, CSS, and JS embedded.

import os
import base64
from flask import Flask, request, session, redirect, url_for, render_template_string, Response
from flask_socketio import SocketIO, emit, join_room, leave_room, disconnect
import eventlet # Required for async_mode='eventlet'

# Use eventlet for async operations
eventlet.monkey_patch()

# --- Configuration ---
SECRET_KEY = os.environ.get('FLASK_SECRET_KEY', 'change_this_strong_secret_key_12345')
ACCESS_PASSWORD = os.environ.get('REMOTE_ACCESS_PASSWORD', 'change_this_password_too')

# --- Flask App Setup ---
app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
socketio = SocketIO(app, async_mode='eventlet')

# --- Global Variables ---
client_pc_sid = None

# --- Authentication ---
def check_auth(password):
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
            position: relative;
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
                // Request initial state if needed
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
                if (remoteScreenWidth === null || remoteScreenHeight === null) {
                     // Use onload for more reliable dimension checking
                     const tempImg = new Image();
                     tempImg.onload = () => {
                         if (remoteScreenWidth === null) { // Check again inside callback
                             remoteScreenWidth = tempImg.naturalWidth;
                             remoteScreenHeight = tempImg.naturalHeight;
                             console.log(`Remote screen resolution detected: ${remoteScreenWidth}x${remoteScreenHeight}`);
                         }
                     };
                     tempImg.onerror = () => {
                         console.error("Error loading image to detect dimensions.");
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

                // Optionally move first, then click (might feel more natural)
                // const moveCommand = { action: 'move', x: remoteX, y: remoteY };
                // socket.emit('control_command', moveCommand);
                // console.log('Sent move command:', moveCommand);

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

                // Optionally move first
                // const moveCommand = { action: 'move', x: remoteX, y: remoteY };
                // socket.emit('control_command', moveCommand);
                // console.log('Sent move command:', moveCommand);

                showClickFeedback(x, y); // Use same feedback for right click

                const clickCommand = { action: 'click', button: 'right', x: remoteX, y: remoteY };
                socket.emit('control_command', clickCommand);
                console.log('Sent right click command:', clickCommand);
            });

            // Button clicks (without coordinates)
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
    if request.method == 'POST':
        password = request.form.get('password')
        if check_auth(password):
            session['authenticated'] = True
            print(f"Login successful for session: {request.sid}") # Log successful login
            return redirect(url_for('interface'))
        else:
            print(f"Login failed for session: {request.sid}") # Log failed login
            return render_template_string(LOGIN_HTML, error="Invalid password")

    # If already authenticated, redirect to interface
    if session.get('authenticated'):
        return redirect(url_for('interface'))

    # Show login page for GET requests or if not authenticated
    return render_template_string(LOGIN_HTML)

@app.route('/interface')
def interface():
    if not session.get('authenticated'):
        print(f"Unauthorized access attempt to /interface from {request.sid}") # Log unauthorized access
        return redirect(url_for('index'))
    # User is authenticated, show the main interface
    return render_template_string(INTERFACE_HTML)

@app.route('/logout')
def logout():
    print(f"Logging out session: {request.sid}") # Log logout action
    session.pop('authenticated', None)
    return redirect(url_for('index'))

# --- SocketIO Events ---
@socketio.on('connect')
def handle_connect():
    # Note: Authentication for web interface happens via Flask session check in routes
    # Authentication for client PC happens via 'register_client' event
    print(f"Socket connected: {request.sid}")
    # Check if a client PC is already connected and notify the new web interface
    if client_pc_sid:
        emit('client_connected', {'message': 'Remote PC already connected'}, room=request.sid)


@socketio.on('disconnect')
def handle_disconnect():
    global client_pc_sid
    print(f"Socket disconnected: {request.sid}")
    # Check if the disconnecting socket is the client PC
    if request.sid == client_pc_sid:
        print("Client PC disconnected.")
        client_pc_sid = None
        # Notify all remaining web interfaces that the client PC is gone
        emit('client_disconnected', {'message': 'Remote PC disconnected'}, broadcast=True, include_self=False)

@socketio.on('register_client')
def handle_register_client(data):
    global client_pc_sid
    client_token = data.get('token')
    if client_token == ACCESS_PASSWORD:
        # If a different client PC was already connected, disconnect it first
        if client_pc_sid and client_pc_sid != request.sid:
             print(f"New client PC ({request.sid}) detected, disconnecting old one ({client_pc_sid}).")
             # Disconnect the old client; it will trigger the 'disconnect' event handler above
             socketio.disconnect(client_pc_sid, silent=True) # silent=True might prevent disconnect handler, test needed. Let's keep it False.
             # socketio.disconnect(client_pc_sid) # Disconnect generates a disconnect event

        # Check if it's the same client PC re-registering (e.g., after network drop)
        elif client_pc_sid == request.sid:
             print(f"Client PC ({request.sid}) re-registered.")
             # No need to change client_pc_sid
        else:
             # This is the first time this client PC is registering in this session
             print(f"Client PC registered: {request.sid}")

        # Store the new client PC's SID
        client_pc_sid = request.sid
        # Notify all connected web interfaces that a client PC is now ready
        emit('client_connected', {'message': 'Remote PC connected'}, broadcast=True, include_self=False)
        # Send confirmation back specifically to the client PC that just registered
        emit('registration_success', room=request.sid)
    else:
        # Authentication failed for the client PC trying to register
        print(f"Client PC authentication failed for SID: {request.sid}")
        emit('registration_fail', {'message': 'Authentication failed'}, room=request.sid)
        # Disconnect this unauthorized client PC immediately
        disconnect(request.sid)

# --- MODIFIED FUNCTION ---
@socketio.on('screen_data')
def handle_screen_data(data):
    # Ensure this function only processes data from the registered client PC
    if request.sid != client_pc_sid:
        # Silently ignore data if it's not from the registered client PC
        # Adding logs here can be very noisy if other sockets try to send data
        return

    try: # *** ADDED TRY BLOCK ***
        image_data = data.get('image')
        if image_data:
            # *** TEMPORARILY COMMENT OUT BROADCAST FOR TESTING ***
            # The line below sends the image to all web viewers. Comment it out
            # to check if simply receiving the data works without disconnection.
            # If the client stays connected with this commented out, the broadcast
            # mechanism (or the load it creates) is the likely issue.

            # emit('screen_update', {'image': image_data}, broadcast=True, include_self=False)

            # Add a print statement to confirm data is being received successfully here
            # Make this less verbose, maybe print only every N frames or on size change later
            print(f"Received screen data from {request.sid}, size: {len(image_data)}. Broadcasting is currently DISABLED for testing.")

        else:
            # Log if empty data is received, which might indicate a client-side issue
            print(f"Received empty screen data package from {request.sid}.")

    except Exception as e: # *** ADDED EXCEPT BLOCK ***
        # Log any error that occurs within this handler
        print(f"!!! ERROR in handle_screen_data processing data from SID {request.sid}: {e}")
        # Consider adding traceback for more detailed debugging:
        # import traceback
        # print(traceback.format_exc())
        # Depending on the error, you might want to disconnect the client PC
        # to prevent repeated errors, but be cautious with this.
        # if client_pc_sid == request.sid:
        #     print(f"Disconnecting client PC {request.sid} due to error in handle_screen_data.")
        #     disconnect(request.sid)

@socketio.on('control_command')
def handle_control_command(data):
    # IMPORTANT: Verify the sender is an authenticated web interface using the Flask session
    if not session.get('authenticated'):
        print(f"Unauthenticated control command attempt from {request.sid}. Command ignored.")
        # Optionally emit an error back to the sender, but might reveal info
        # emit('command_error', {'message': 'Not authenticated'}, room=request.sid)
        return # Crucial to stop processing unauthenticated commands

    # If the web interface is authenticated, proceed to forward the command
    if client_pc_sid:
        # Optional: Log the command being forwarded for debugging
        # print(f"Forwarding command from web interface {request.sid} to client PC ({client_pc_sid}): {data}")
        # Emit the command specifically to the registered client PC's room (socket ID)
        emit('command', data, room=client_pc_sid)
    else:
        # If no client PC is connected, inform the web interface that sent the command
        print(f"Control command from {request.sid} received, but no client PC connected.")
        emit('command_error', {'message': 'Client PC not connected'}, room=request.sid) # Notify sender


# --- Main Execution ---
if __name__ == '__main__':
    print("Starting Flask-SocketIO server...")
    # Get port from environment variable 'PORT' (used by Render, Heroku, etc.)
    # Default to 5000 if 'PORT' is not set (for local development)
    port = int(os.environ.get('PORT', 5000))
    print(f"Server will run on host 0.0.0.0, port {port}")

    # Run the SocketIO server using eventlet
    # debug=True enables auto-reloading but should be False in production
    # Use host='0.0.0.0' to make the server accessible externally (within network/internet)
    socketio.run(app, host='0.0.0.0', port=port, debug=False)

    # Note for Render deployment:
    # Your Procfile should likely use gunicorn:
    # web: gunicorn --worker-class eventlet -w 1 app:app
    # Ensure 'gunicorn' and 'eventlet' are in your requirements.txt
