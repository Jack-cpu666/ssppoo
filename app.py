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

            socket.on('screen_update', (data) => {
                const imageSrc = `data:image/jpeg;base64,${data.image}`;
                screenImage.src = imageSrc;
                if (remoteScreenWidth === null || remoteScreenHeight === null) {
                    const checkDimensions = () => {
                        if (screenImage.complete && screenImage.naturalWidth > 0) {
                            if (remoteScreenWidth === null) { // Check again to avoid race condition
                                remoteScreenWidth = screenImage.naturalWidth;
                                remoteScreenHeight = screenImage.naturalHeight;
                                console.log(`Remote screen resolution detected: ${remoteScreenWidth}x${remoteScreenHeight}`);
                            }
                        } else {
                             // Image might not be fully loaded yet, retry shortly
                             setTimeout(checkDimensions, 50);
                        }
                    };
                    checkDimensions();
                }
            });

            socket.on('command_error', (data) => {
                console.error('Command Error:', data.message);
                alert(`Command Error: ${data.message}`);
            });

            screenImage.addEventListener('click', (event) => {
                if (!remoteScreenWidth || !remoteScreenHeight) return;
                const rect = screenImage.getBoundingClientRect();
                const x = event.clientX - rect.left;
                const y = event.clientY - rect.top;
                const remoteX = Math.round((x / rect.width) * remoteScreenWidth);
                const remoteY = Math.round((y / rect.height) * remoteScreenHeight);
                console.log(`Screen clicked: display(${x.toFixed(0)}, ${y.toFixed(0)}), remote(${remoteX}, ${remoteY})`);
                const moveCommand = { action: 'move', x: remoteX, y: remoteY };
                socket.emit('control_command', moveCommand);
                showClickFeedback(x, y);
                const clickCommand = { action: 'click', button: 'left', x: remoteX, y: remoteY };
                socket.emit('control_command', clickCommand);
                console.log('Sent left click command:', clickCommand);
            });

            screenImage.addEventListener('contextmenu', (event) => {
                event.preventDefault();
                if (!remoteScreenWidth || !remoteScreenHeight) return;
                const rect = screenImage.getBoundingClientRect();
                const x = event.clientX - rect.left;
                const y = event.clientY - rect.top;
                const remoteX = Math.round((x / rect.width) * remoteScreenWidth);
                const remoteY = Math.round((y / rect.height) * remoteScreenHeight);
                console.log(`Screen right-clicked: display(${x.toFixed(0)}, ${y.toFixed(0)}), remote(${remoteX}, ${remoteY})`);
                const moveCommand = { action: 'move', x: remoteX, y: remoteY };
                socket.emit('control_command', moveCommand);
                showClickFeedback(x, y);
                const clickCommand = { action: 'click', button: 'right', x: remoteX, y: remoteY };
                socket.emit('control_command', clickCommand);
                console.log('Sent right click command:', clickCommand);
            });

            leftClickBtn.addEventListener('click', () => {
                socket.emit('control_command', { action: 'click', button: 'left' });
                console.log('Sent left click command (button)');
            });

            rightClickBtn.addEventListener('click', () => {
                socket.emit('control_command', { action: 'click', button: 'right' });
                console.log('Sent right click command (button)');
            });

            keyboardInput.addEventListener('keypress', (event) => {
                if (event.key === 'Enter') {
                    event.preventDefault();
                    const text = keyboardInput.value;
                    if (text) {
                        const command = { action: 'keypress', key: text, is_string: true };
                        socket.emit('control_command', command);
                        console.log('Sent keypress command (string):', command);
                        keyboardInput.value = '';
                    }
                }
            });

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
            return redirect(url_for('interface'))
        else:
            return render_template_string(LOGIN_HTML, error="Invalid password")

    if session.get('authenticated'):
        return redirect(url_for('interface'))

    return render_template_string(LOGIN_HTML)

@app.route('/interface')
def interface():
    if not session.get('authenticated'):
        return redirect(url_for('index'))
    return render_template_string(INTERFACE_HTML)

@app.route('/logout')
def logout():
    session.pop('authenticated', None)
    return redirect(url_for('index'))

# --- SocketIO Events ---
@socketio.on('connect')
def handle_connect():
    print(f"Client connected: {request.sid}")
    # Further auth check happens when client/web interface identifies itself

@socketio.on('disconnect')
def handle_disconnect():
    global client_pc_sid
    print(f"Client disconnected: {request.sid}")
    if request.sid == client_pc_sid:
        print("Client PC disconnected.")
        client_pc_sid = None
        emit('client_disconnected', {'message': 'Remote PC disconnected'}, broadcast=True, include_self=False)

@socketio.on('register_client')
def handle_register_client(data):
    global client_pc_sid
    client_token = data.get('token')
    if client_token == ACCESS_PASSWORD:
        if client_pc_sid and client_pc_sid != request.sid:
             print(f"New client PC ({request.sid}), disconnecting old ({client_pc_sid}).")
             socketio.disconnect(client_pc_sid, silent=True) # Disconnect previous client silently
        elif client_pc_sid == request.sid:
             print(f"Client PC ({request.sid}) re-registered.")
        else:
             print(f"Client PC registered: {request.sid}")

        client_pc_sid = request.sid
        # Notify web interfaces a client is ready
        emit('client_connected', {'message': 'Remote PC connected'}, broadcast=True, include_self=False)
        # Confirm registration to the client PC
        emit('registration_success', room=request.sid)
    else:
        print(f"Client PC authentication failed: {request.sid}")
        emit('registration_fail', {'message': 'Authentication failed'}, room=request.sid)
        disconnect() # Disconnect the unauthorized client PC

@socketio.on('screen_data')
def handle_screen_data(data):
    if request.sid != client_pc_sid:
        # print(f"Ignoring screen data from non-registered client: {request.sid}") # Can be noisy
        return

    image_data = data.get('image')
    if image_data:
        # Broadcast only to authenticated web interfaces (implicitly handled by session check on control_command)
        # Here we broadcast to all connected sockets, JS handles display
        emit('screen_update', {'image': image_data}, broadcast=True, include_self=False)
    else:
        print("Received empty screen data.")


@socketio.on('control_command')
def handle_control_command(data):
    # Check if the sender is an authenticated web interface via session
    if not session.get('authenticated'):
        print(f"Unauthenticated control command from {request.sid}. Ignoring.")
        return # Ignore command if the web user isn't logged in

    if client_pc_sid:
        # print(f"Forwarding command to client PC ({client_pc_sid}): {data}") # Debug
        # Emit the command specifically to the registered client PC
        emit('command', data, room=client_pc_sid)
    else:
        print("Control command received, but no client PC connected.")
        emit('command_error', {'message': 'Client PC not connected'}, room=request.sid) # Notify sender


# --- Main Execution ---
if __name__ == '__main__':
    print("Starting Flask-SocketIO server...")
    # Use host='0.0.0.0' to be accessible externally
    # Port 5000 is default for Flask, Render will assign one.
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
    # For Render deployment, use: gunicorn --worker-class eventlet -w 1 app:app
    # Set debug=False for production
