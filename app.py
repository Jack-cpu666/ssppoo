# Consolidated Server (app.py)
# Flask web server with SocketIO, HTML, CSS, and JS embedded.
# Includes direct keyboard event capture in the browser.

import os
import base64
from flask import Flask, request, session, redirect, url_for, render_template_string, Response
from flask_socketio import SocketIO, emit, join_room, leave_room, disconnect
import eventlet # Required for async_mode='eventlet'
import traceback # For detailed error logging

# Use eventlet for async operations
eventlet.monkey_patch()

# --- Configuration ---
SECRET_KEY = os.environ.get('FLASK_SECRET_KEY', 'change_this_strong_secret_key_12345')
ACCESS_PASSWORD = os.environ.get('REMOTE_ACCESS_PASSWORD', 'change_this_password_too')

# --- Flask App Setup ---
app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
# Increase ping timeout/interval for potentially less stable connections
socketio = SocketIO(app, async_mode='eventlet', ping_timeout=20, ping_interval=10)

# --- Global Variables ---
client_pc_sid = None
# Store web viewer SIDs to send screen updates only to them (optional optimization)
# viewer_sids = set() # Example if implementing targeted emits later

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

# --- MODIFIED INTERFACE_HTML ---
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
        html, body {
            height: 100%;
            overflow: hidden; /* Prevent body scrollbars */
            font-family: 'Inter', sans-serif;
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        #screen-view img {
            max-width: 100%;
            max-height: 100%; /* Ensure image stays within container */
            height: auto; /* Maintain aspect ratio */
            width: auto; /* Maintain aspect ratio */
            display: block;
            cursor: crosshair;
            background-color: #333; /* Placeholder background */
            object-fit: contain; /* Scale image down to fit */
        }
        #screen-view {
            width: 100%;
            height: 100%; /* Fill available space */
            overflow: hidden;
            position: relative; /* For click feedback positioning */
            display: flex; /* Center image */
            align-items: center; /* Center image */
            justify-content: center; /* Center image */
        }
        .status-dot { height: 10px; width: 10px; border-radius: 50%; display: inline-block; margin-right: 5px; }
        .status-connected { background-color: #4ade80; } /* green-400 */
        .status-disconnected { background-color: #f87171; } /* red-400 */
        .status-connecting { background-color: #fbbf24; } /* amber-400 */

        .click-feedback { position: absolute; border: 2px solid red; border-radius: 50%; width: 20px; height: 20px; transform: translate(-50%, -50%) scale(0); pointer-events: none; background-color: rgba(255, 0, 0, 0.3); animation: click-pulse 0.4s ease-out forwards; }
        @keyframes click-pulse { 0% { transform: translate(-50%, -50%) scale(0.5); opacity: 1; } 100% { transform: translate(-50%, -50%) scale(2); opacity: 0; } }
        /* Focus outline removed for body to prevent blue box on click */
        body:focus { outline: none; }
    </style>
</head>
<body class="bg-gray-200 flex flex-col h-screen" tabindex="0"> <header class="bg-gray-800 text-white p-3 flex justify-between items-center shadow-md flex-shrink-0"> <h1 class="text-lg font-semibold">Remote Desktop Control</h1> <div class="flex items-center space-x-3"> <div id="connection-status" class="flex items-center text-xs"> <span id="status-dot" class="status-dot status-connecting"></span>
                <span id="status-text">Connecting...</span>
            </div>
             <a href="{{ url_for('logout') }}" class="bg-red-600 hover:bg-red-700 text-white text-xs font-medium py-1 px-2 rounded-md transition duration-150 ease-in-out">Logout</a> </div>
    </header>

    <main class="flex-grow flex p-2 gap-2 overflow-hidden"> <div class="flex-grow bg-black rounded-lg shadow-inner flex items-center justify-center overflow-hidden" id="screen-view-container">
            <div id="screen-view">
                 <img id="screen-image" src="https://placehold.co/1920x1080/333333/CCCCCC?text=Waiting+for+Remote+Screen..." alt="Remote Screen"
                      onerror="this.onerror=null; this.src='https://placehold.co/600x338/333333/CCCCCC?text=Error+Loading+Screen';">
            </div>
        </div>

        </main>

    <script>
        // Embedded JavaScript
        document.addEventListener('DOMContentLoaded', () => {
            const socket = io(window.location.origin, { path: '/socket.io/' });
            const screenImage = document.getElementById('screen-image');
            const screenView = document.getElementById('screen-view'); // Parent div for click feedback
            const connectionStatusDot = document.getElementById('status-dot');
            const connectionStatusText = document.getElementById('status-text');
            let remoteScreenWidth = null;
            let remoteScreenHeight = null;
            let isControlPressed = false;
            let isShiftPressed = false;
            let isAltPressed = false;

            // Make body focusable on load to capture keys immediately
             document.body.focus();
             // Refocus body if user clicks elsewhere (e.g., the image)
             document.addEventListener('click', () => {
                 document.body.focus();
             });


            function updateStatus(status, message) {
                connectionStatusText.textContent = message;
                connectionStatusDot.className = `status-dot ${status}`;
            }

            function showClickFeedback(x, y, elementRect) {
                // Adjust position relative to the screenView container
                const feedbackX = x + elementRect.left;
                const feedbackY = y + elementRect.top;

                const feedback = document.createElement('div');
                feedback.className = 'click-feedback';
                // Position feedback relative to the screenView div, not the image directly
                feedback.style.left = `${x}px`; // Use click coords relative to image
                feedback.style.top = `${y}px`;
                screenView.appendChild(feedback);
                setTimeout(() => { feedback.remove(); }, 400);
            }

            socket.on('connect', () => {
                console.log('Connected to server');
                updateStatus('status-connecting', 'Server connected, waiting for remote PC...');
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
                 document.body.focus(); // Ensure body has focus when client connects
            });

            socket.on('client_disconnected', (data) => {
                console.warn(data.message);
                updateStatus('status-disconnected', 'Remote PC Disconnected');
                screenImage.src = 'https://placehold.co/1920x1080/444444/CCCCCC?text=Remote+PC+Disconnected';
                remoteScreenWidth = null; remoteScreenHeight = null;
            });

            socket.on('screen_update', (data) => {
                const imageSrc = `data:image/jpeg;base64,${data.image}`;
                // Only update src if it's different to potentially reduce flicker/reload
                // This might be premature optimization, test if needed
                // if (screenImage.src !== imageSrc) {
                     screenImage.src = imageSrc;
                // }

                if (remoteScreenWidth === null || remoteScreenHeight === null) {
                     const tempImg = new Image();
                     tempImg.onload = () => {
                         if (remoteScreenWidth === null) {
                             remoteScreenWidth = tempImg.naturalWidth;
                             remoteScreenHeight = tempImg.naturalHeight;
                             console.log(`Remote screen resolution detected: ${remoteScreenWidth}x${remoteScreenHeight}`);
                         }
                     };
                     tempImg.onerror = () => console.error("Error loading image to detect dimensions.");
                     tempImg.src = imageSrc;
                }
            });

            socket.on('command_error', (data) => {
                console.error('Command Error:', data.message);
                // Maybe display a less intrusive error message
                // updateStatus('status-disconnected', `Error: ${data.message}`);
            });

            // --- Mouse Event Handling ---
            screenImage.addEventListener('mousemove', (event) => {
                if (!remoteScreenWidth || !remoteScreenHeight) return;
                const rect = screenImage.getBoundingClientRect();
                const x = event.clientX - rect.left;
                const y = event.clientY - rect.top;
                const remoteX = Math.round((x / rect.width) * remoteScreenWidth);
                const remoteY = Math.round((y / rect.height) * remoteScreenHeight);

                const command = { action: 'move', x: remoteX, y: remoteY };
                socket.emit('control_command', command);
                // Debounce or throttle mouse move events if needed to reduce load
            });

            screenImage.addEventListener('click', (event) => {
                if (!remoteScreenWidth || !remoteScreenHeight) return;
                const rect = screenImage.getBoundingClientRect();
                const x = event.clientX - rect.left;
                const y = event.clientY - rect.top;
                const remoteX = Math.round((x / rect.width) * remoteScreenWidth);
                const remoteY = Math.round((y / rect.height) * remoteScreenHeight);

                // Send click command WITH coordinates
                const clickCommand = { action: 'click', button: 'left', x: remoteX, y: remoteY };
                socket.emit('control_command', clickCommand);
                console.log('Sent left click command:', clickCommand);
                showClickFeedback(x, y, rect); // Show feedback relative to image rect
                 document.body.focus(); // Keep body focused
            });

            screenImage.addEventListener('contextmenu', (event) => {
                event.preventDefault();
                if (!remoteScreenWidth || !remoteScreenHeight) return;
                const rect = screenImage.getBoundingClientRect();
                const x = event.clientX - rect.left;
                const y = event.clientY - rect.top;
                const remoteX = Math.round((x / rect.width) * remoteScreenWidth);
                const remoteY = Math.round((y / rect.height) * remoteScreenHeight);

                // Send right click command WITH coordinates
                const clickCommand = { action: 'click', button: 'right', x: remoteX, y: remoteY };
                socket.emit('control_command', clickCommand);
                console.log('Sent right click command:', clickCommand);
                showClickFeedback(x, y, rect); // Show feedback relative to image rect
                 document.body.focus(); // Keep body focused
            });

             // --- Mouse Wheel Handling ---
             screenImage.addEventListener('wheel', (event) => {
                event.preventDefault(); // Prevent page scroll
                // Normalize scroll amount (browsers differ)
                const deltaY = event.deltaY > 0 ? 1 : (event.deltaY < 0 ? -1 : 0); // Vertical scroll clicks
                const deltaX = event.deltaX > 0 ? 1 : (event.deltaX < 0 ? -1 : 0); // Horizontal scroll clicks

                if (deltaY !== 0 || deltaX !== 0) {
                     const command = { action: 'scroll', dx: deltaX, dy: deltaY };
                     socket.emit('control_command', command);
                     console.log('Sent scroll command:', command);
                }
                 document.body.focus(); // Keep body focused
            });

            // --- Keyboard Event Handling ---
            document.body.addEventListener('keydown', (event) => {
                // Log the key event for debugging
                console.log(`KeyDown: Key='${event.key}', Code='${event.code}', Ctrl=${event.ctrlKey}, Shift=${event.shiftKey}, Alt=${event.altKey}`);

                // Basic check to prevent sending modifier keys themselves repeatedly
                if (event.key === 'Control' || event.key === 'Shift' || event.key === 'Alt' || event.key === 'Meta') {
                    if (event.key === 'Control') isControlPressed = true;
                    if (event.key === 'Shift') isShiftPressed = true;
                    if (event.key === 'Alt') isAltPressed = true;
                    // Don't send modifier keydown events if you only care about them *with* other keys
                    // return;
                }

                 // Prevent default browser behavior for keys we want to send
                 // Be careful not to block essential browser functions unintentionally
                if (event.key.length === 1 || event.key.startsWith('Arrow') || ['Enter', 'Tab', 'Escape', 'Backspace', 'Delete', 'Home', 'End', 'PageUp', 'PageDown', 'Insert'].includes(event.key) || event.key.startsWith('F')) {
                     event.preventDefault();
                }
                 // Allow browser functions like Ctrl+C, Ctrl+V, Ctrl+R, F5 unless specifically handled
                 // if (!(event.ctrlKey && ['c', 'v', 'x', 'a'].includes(event.key.toLowerCase())) && event.key !== 'F5' ) {
                 //     event.preventDefault();
                 // }


                const command = {
                    action: 'keydown',
                    key: event.key,       // e.g., 'a', 'Enter', 'Shift'
                    code: event.code,     // e.g., 'KeyA', 'Enter', 'ShiftLeft'
                    ctrlKey: event.ctrlKey,
                    shiftKey: event.shiftKey,
                    altKey: event.altKey,
                    metaKey: event.metaKey // Windows key / Command key
                };
                socket.emit('control_command', command);
            });

            document.body.addEventListener('keyup', (event) => {
                console.log(`KeyUp: Key='${event.key}', Code='${event.code}'`);

                 if (event.key === 'Control') isControlPressed = false;
                 if (event.key === 'Shift') isShiftPressed = false;
                 if (event.key === 'Alt') isAltPressed = false;

                // Always send keyup events
                const command = {
                    action: 'keyup',
                    key: event.key,
                    code: event.code,
                    // We don't usually need modifier states on keyup, but could include if needed
                };
                socket.emit('control_command', command);
            });

             // Handle losing focus (e.g., browser tab change) - release modifiers
             window.addEventListener('blur', () => {
                 console.log('Window blurred - releasing potential modifier keys');
                 if (isControlPressed) {
                     socket.emit('control_command', { action: 'keyup', key: 'Control', code: 'ControlLeft' }); // Assume left?
                     isControlPressed = false;
                 }
                  if (isShiftPressed) {
                     socket.emit('control_command', { action: 'keyup', key: 'Shift', code: 'ShiftLeft' }); // Assume left?
                     isShiftPressed = false;
                 }
                  if (isAltPressed) {
                     socket.emit('control_command', { action: 'keyup', key: 'Alt', code: 'AltLeft' }); // Assume left?
                     isAltPressed = false;
                 }
             });


            updateStatus('status-connecting', 'Initializing...');
             document.body.focus(); // Try focusing body initially

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
            print(f"Login successful for session: {request.sid}")
            return redirect(url_for('interface'))
        else:
            print(f"Login failed for session: {request.sid}")
            return render_template_string(LOGIN_HTML, error="Invalid password")

    if session.get('authenticated'):
        return redirect(url_for('interface'))

    return render_template_string(LOGIN_HTML)

@app.route('/interface')
def interface():
    if not session.get('authenticated'):
        print(f"Unauthorized access attempt to /interface from {request.sid}")
        return redirect(url_for('index'))
    return render_template_string(INTERFACE_HTML)

@app.route('/logout')
def logout():
    print(f"Logging out session: {request.sid}")
    session.pop('authenticated', None)
    return redirect(url_for('index'))

# --- SocketIO Events ---
@socketio.on('connect')
def handle_connect():
    sid = request.sid
    print(f"Socket connected: {sid}")
    # Logic to differentiate viewers vs client PC could be added here if needed
    # e.g., viewers could join a 'viewers' room
    # if session.get('authenticated'): # Check if it's a web viewer connecting
    #     viewer_sids.add(sid)
    #     print(f"Web viewer connected: {sid}")
    #     if client_pc_sid: # Inform new viewer if client is already connected
    #          emit('client_connected', {'message': 'Remote PC already connected'}, room=sid)

@socketio.on('disconnect')
def handle_disconnect():
    global client_pc_sid # , viewer_sids
    sid = request.sid
    print(f"Socket disconnected: {sid}")
    if sid == client_pc_sid:
        print("Client PC disconnected.")
        client_pc_sid = None
        emit('client_disconnected', {'message': 'Remote PC disconnected'}, broadcast=True, include_self=False) # Notify all viewers
    # else: # A web viewer disconnected
    #     viewer_sids.discard(sid)
    #     print(f"Web viewer disconnected: {sid}")


@socketio.on('register_client')
def handle_register_client(data):
    global client_pc_sid
    client_token = data.get('token')
    sid = request.sid
    if client_token == ACCESS_PASSWORD:
        if client_pc_sid and client_pc_sid != sid:
             print(f"New client PC ({sid}) detected, disconnecting old one ({client_pc_sid}).")
             socketio.disconnect(client_pc_sid) # Triggers disconnect handler
        elif client_pc_sid == sid:
             print(f"Client PC ({sid}) re-registered.")
        else:
             print(f"Client PC registered: {sid}")

        client_pc_sid = sid
        emit('client_connected', {'message': 'Remote PC connected'}, broadcast=True, include_self=False) # Notify viewers
        emit('registration_success', room=sid) # Confirm to client
    else:
        print(f"Client PC authentication failed for SID: {sid}")
        emit('registration_fail', {'message': 'Authentication failed'}, room=sid)
        disconnect(sid)

# --- MODIFIED FUNCTION ---
@socketio.on('screen_data')
def handle_screen_data(data):
    # Only process data from the registered client PC
    if request.sid != client_pc_sid:
        return

    try:
        image_data = data.get('image')
        if image_data:
            # *** RE-ENABLED BROADCAST ***
            # Send screen update to all connected sockets (viewers)
            # Optimization: Could send only to SIDs in viewer_sids if tracking them
            emit('screen_update', {'image': image_data}, broadcast=True, include_self=False)

            # Reduce logging frequency - maybe log only periodically or on errors
            # print(f"Sent screen update. Size: {len(image_data)}")

        # else: # Log if empty data is received (might indicate client issue)
        #     print(f"Received empty screen data package from {request.sid}.")

    except Exception as e:
        print(f"!!! ERROR in handle_screen_data processing data from SID {request.sid}: {e}")
        print(traceback.format_exc()) # Print full traceback for errors


@socketio.on('control_command')
def handle_control_command(data):
    sid = request.sid
    # Verify sender is authenticated web interface *OR* potentially allow other authenticated sources later
    if not session.get('authenticated'):
        print(f"Unauthenticated control command attempt from {sid}. Ignoring.")
        return

    if client_pc_sid:
        # Forward the command (move, click, keydown, keyup, scroll) to the client PC
        emit('command', data, room=client_pc_sid)
        # Optional: Log commands for debugging, but can be very verbose
        # print(f"Forwarding command from {sid} to {client_pc_sid}: {data.get('action')}")
    else:
        # Inform the sender if the client PC isn't available
        emit('command_error', {'message': 'Client PC not connected'}, room=sid)


# --- Main Execution ---
if __name__ == '__main__':
    print("Starting Flask-SocketIO server...")
    port = int(os.environ.get('PORT', 5000))
    print(f"Server will run on host 0.0.0.0, port {port}")
    print(f"Access password: {'*' * len(ACCESS_PASSWORD) if ACCESS_PASSWORD else 'None'}")

    # Use Gunicorn for production on Render: gunicorn --worker-class eventlet -w 1 app:app
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
