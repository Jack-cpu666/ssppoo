# Consolidated Server (app.py)
# Flask web server with SocketIO, HTML, CSS, and JS embedded.
# Includes direct keyboard event capture in the browser.
# MODIFIED: Handles both binary ('screen_data_bytes') and Base64 ('screen_data') screen updates.
# MODIFIED: JavaScript updated for binary data handling.
# MODIFIED: Added server-side FPS throttling for screen updates.

# IMPORTANT: eventlet.monkey_patch() must be called before other imports
import eventlet
eventlet.monkey_patch()

import os
import base64
import time # Added for FPS throttling
from flask import Flask, request, session, redirect, url_for, render_template_string, Response
from flask_socketio import SocketIO, emit, join_room, leave_room, disconnect
import traceback # For detailed error logging


# --- Configuration ---
SECRET_KEY = os.environ.get('FLASK_SECRET_KEY', 'change_this_strong_secret_key_12345')
ACCESS_PASSWORD = os.environ.get('REMOTE_ACCESS_PASSWORD', 'change_this_password_too')

# --- Flask App Setup ---
app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
# Increased buffer size slightly, might help with larger binary frames sometimes
socketio = SocketIO(app, async_mode='eventlet', ping_timeout=20, ping_interval=10, max_http_buffer_size=10 * 1024 * 1024)

# --- Global Variables ---
client_pc_sid = None
# --- FPS Throttling Variables ---
TARGET_FPS = 15 # Increase server FPS target to match client potential (adjust as needed)
MIN_INTERVAL = 1.0 / TARGET_FPS # Minimum time interval between frames
last_broadcast_time = 0 # Timestamp of the last broadcast screen update

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
    <style> body { font-family: 'Inter', sans-serif; } </style>
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

# --- MODIFIED INTERFACE_HTML (JavaScript part updated for binary) ---
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
        html, body { height: 100%; overflow: hidden; font-family: 'Inter', sans-serif; margin: 0; padding: 0; box-sizing: border-box; }
        #screen-view img { max-width: 100%; max-height: 100%; height: auto; width: auto; display: block; cursor: crosshair; background-color: #333; object-fit: contain; }
        #screen-view { width: 100%; height: 100%; overflow: hidden; position: relative; display: flex; align-items: center; justify-content: center; }
        .status-dot { height: 10px; width: 10px; border-radius: 50%; display: inline-block; margin-right: 5px; }
        .status-connected { background-color: #4ade80; } .status-disconnected { background-color: #f87171; } .status-connecting { background-color: #fbbf24; }
        .click-feedback { position: absolute; border: 2px solid red; border-radius: 50%; width: 20px; height: 20px; transform: translate(-50%, -50%) scale(0); pointer-events: none; background-color: rgba(255, 0, 0, 0.3); animation: click-pulse 0.4s ease-out forwards; }
        @keyframes click-pulse { 0% { transform: translate(-50%, -50%) scale(0.5); opacity: 1; } 100% { transform: translate(-50%, -50%) scale(2); opacity: 0; } }
        body:focus { outline: none; }
    </style>
</head>
<body class="bg-gray-200 flex flex-col h-screen" tabindex="0">

    <header class="bg-gray-800 text-white p-3 flex justify-between items-center shadow-md flex-shrink-0">
        <h1 class="text-lg font-semibold">Remote Desktop Control</h1>
        <div class="flex items-center space-x-3">
            <div id="connection-status" class="flex items-center text-xs">
                <span id="status-dot" class="status-dot status-connecting"></span>
                <span id="status-text">Connecting...</span>
            </div>
             <a href="{{ url_for('logout') }}" class="bg-red-600 hover:bg-red-700 text-white text-xs font-medium py-1 px-2 rounded-md transition duration-150 ease-in-out">Logout</a>
        </div>
    </header>

    <main class="flex-grow flex p-2 gap-2 overflow-hidden">
        <div class="flex-grow bg-black rounded-lg shadow-inner flex items-center justify-center overflow-hidden" id="screen-view-container">
            <div id="screen-view">
                 <img id="screen-image" src="https://placehold.co/1920x1080/333333/CCCCCC?text=Waiting+for+Remote+Screen..." alt="Remote Screen"
                       onerror="this.onerror=null; this.src='https://placehold.co/600x338/333333/CCCCCC?text=Error+Loading+Screen'; console.error('Image load error:', this.src);">
            </div>
        </div>
    </main>

    <script>
        document.addEventListener('DOMContentLoaded', () => {
            const socket = io(window.location.origin, { path: '/socket.io/' });
            const screenImage = document.getElementById('screen-image');
            const screenView = document.getElementById('screen-view');
            const connectionStatusDot = document.getElementById('status-dot');
            const connectionStatusText = document.getElementById('status-text');
            let remoteScreenWidth = null;
            let remoteScreenHeight = null;
            let activeModifiers = { ctrl: false, shift: false, alt: false, meta: false };
            let currentImageUrl = null; // To manage Blob URL cleanup

            document.body.focus();
            document.addEventListener('click', (e) => { if (e.target !== screenImage) { document.body.focus(); } });

            function updateStatus(status, message) { connectionStatusText.textContent = message; connectionStatusDot.className = `status-dot ${status}`; }
            function showClickFeedback(x, y, elementRect) { const feedback = document.createElement('div'); feedback.className = 'click-feedback'; feedback.style.left = `${x}px`; feedback.style.top = `${y}px`; screenView.appendChild(feedback); setTimeout(() => { feedback.remove(); }, 400); }

            socket.on('connect', () => { console.log('Connected to server'); updateStatus('status-connecting', 'Server connected, waiting for remote PC...'); });
            socket.on('disconnect', () => { console.warn('Disconnected from server'); updateStatus('status-disconnected', 'Server disconnected'); if (currentImageUrl) URL.revokeObjectURL(currentImageUrl); screenImage.src = 'https://placehold.co/600x338/333333/CCCCCC?text=Server+Disconnected'; remoteScreenWidth = null; remoteScreenHeight = null; currentImageUrl = null;});
            socket.on('connect_error', (error) => { console.error('Connection Error:', error); updateStatus('status-disconnected', 'Connection Error'); if (currentImageUrl) URL.revokeObjectURL(currentImageUrl); screenImage.src = 'https://placehold.co/600x338/333333/CCCCCC?text=Connection+Error'; currentImageUrl = null; });
            socket.on('client_connected', (data) => { console.log(data.message); updateStatus('status-connected', 'Remote PC Connected'); document.body.focus(); });
            socket.on('client_disconnected', (data) => { console.warn(data.message); updateStatus('status-disconnected', 'Remote PC Disconnected'); if (currentImageUrl) URL.revokeObjectURL(currentImageUrl); screenImage.src = 'https://placehold.co/600x338/333333/CCCCCC?text=PC+Disconnected'; remoteScreenWidth = null; remoteScreenHeight = null; currentImageUrl = null; });
            socket.on('command_error', (data) => { console.error('Command Error:', data.message); });

            // --- *** NEW: Handler for Binary Screen Data *** ---
            socket.on('screen_frame_bytes', (imageDataBytes) => {
                // imageDataBytes is expected to be ArrayBuffer or similar
                const blob = new Blob([imageDataBytes], { type: 'image/jpeg' });
                const newImageUrl = URL.createObjectURL(blob);

                // --- Detect Resolution on First Frame ---
                if (remoteScreenWidth === null || remoteScreenHeight === null) {
                    const tempImg = new Image();
                    tempImg.onload = () => {
                        if (remoteScreenWidth === null) { // Check again inside onload
                           remoteScreenWidth = tempImg.naturalWidth;
                           remoteScreenHeight = tempImg.naturalHeight;
                           console.log(`Remote screen resolution detected: ${remoteScreenWidth}x${remoteScreenHeight}`);
                        }
                        URL.revokeObjectURL(tempImg.src); // Clean up temp image URL
                    };
                    tempImg.onerror = () => {
                        console.error("Error loading image dimensions from blob.");
                        URL.revokeObjectURL(tempImg.src);
                    };
                    tempImg.src = newImageUrl; // Use the blob URL for dimension check
                }

                // --- Update Image and Cleanup Old URL ---
                // Store the URL we are about to replace
                const previousUrl = currentImageUrl;
                currentImageUrl = newImageUrl; // Update the current URL immediately

                screenImage.onload = () => {
                    // Only revoke the *previous* URL once the new image has successfully loaded
                    if (previousUrl) {
                        // console.log("Revoking old blob URL:", previousUrl); // Debug
                        URL.revokeObjectURL(previousUrl);
                    }
                };
                 screenImage.onerror = () => {
                     console.error("Error loading image blob:", newImageUrl);
                     // Don't revoke the new URL on error, maybe it will load later? Or revoke?
                     // Let's revoke it to be safe if loading fails.
                     if(currentImageUrl === newImageUrl) { // Check if it hasn't been replaced already
                         URL.revokeObjectURL(newImageUrl);
                         currentImageUrl = previousUrl; // Revert to previous potentially? Risky. Better to just clear.
                         currentImageUrl = null;
                     } else if(previousUrl) { // If it failed but was already replaced, revoke previous
                          URL.revokeObjectURL(previousUrl);
                     }

                 };
                screenImage.src = newImageUrl;
            });

            // --- OLD Base64 Handler (Commented out or remove if client ONLY sends binary) ---
            /*
            socket.on('screen_update', (data) => {
                 const imageSrc = `data:image/jpeg;base64,${data.image}`;
                 screenImage.src = imageSrc;
                 // Original resolution detection logic here (would need cleanup too)
                 console.log("Received Base64 frame (Legacy Handler)");
            });
            */

            // --- Mouse Handling (Unchanged) ---
             screenImage.addEventListener('mousemove', (event) => { if (!remoteScreenWidth) return; const rect = screenImage.getBoundingClientRect(); const x = event.clientX - rect.left; const y = event.clientY - rect.top; const remoteX = Math.round((x / rect.width) * remoteScreenWidth); const remoteY = Math.round((y / rect.height) * remoteScreenHeight); socket.emit('control_command', { action: 'move', x: remoteX, y: remoteY }); });
             screenImage.addEventListener('click', (event) => { if (!remoteScreenWidth) return; const rect = screenImage.getBoundingClientRect(); const x = event.clientX - rect.left; const y = event.clientY - rect.top; const remoteX = Math.round((x / rect.width) * remoteScreenWidth); const remoteY = Math.round((y / rect.height) * remoteScreenHeight); socket.emit('control_command', { action: 'click', button: 'left', x: remoteX, y: remoteY }); showClickFeedback(x, y, rect); document.body.focus(); });
             screenImage.addEventListener('contextmenu', (event) => { event.preventDefault(); if (!remoteScreenWidth) return; const rect = screenImage.getBoundingClientRect(); const x = event.clientX - rect.left; const y = event.clientY - rect.top; const remoteX = Math.round((x / rect.width) * remoteScreenWidth); const remoteY = Math.round((y / rect.height) * remoteScreenHeight); socket.emit('control_command', { action: 'click', button: 'right', x: remoteX, y: remoteY }); showClickFeedback(x, y, rect); document.body.focus(); });
             screenImage.addEventListener('wheel', (event) => { event.preventDefault(); const deltaY = event.deltaY > 0 ? 1 : (event.deltaY < 0 ? -1 : 0); const deltaX = event.deltaX > 0 ? 1 : (event.deltaX < 0 ? -1 : 0); if (deltaY !== 0 || deltaX !== 0) { socket.emit('control_command', { action: 'scroll', dx: deltaX, dy: deltaY }); } document.body.focus(); });

            // --- Keyboard Event Handling (Unchanged) ---
            document.body.addEventListener('keydown', (event) => {
                // console.log(`KeyDown: Key='${event.key}', Code='${event.code}', Ctrl=${event.ctrlKey}, Shift=${event.shiftKey}, Alt=${event.altKey}, Meta=${event.metaKey}`); // Debug
                if (event.key === 'Control') activeModifiers.ctrl = true; if (event.key === 'Shift') activeModifiers.shift = true; if (event.key === 'Alt') activeModifiers.alt = true; if (event.key === 'Meta') activeModifiers.meta = true;
                let shouldPreventDefault = false; const isModifierKey = ['Control', 'Shift', 'Alt', 'Meta', 'CapsLock', 'NumLock', 'ScrollLock'].includes(event.key); const isFKey = event.key.startsWith('F') && event.key.length > 1 && !isNaN(parseInt(event.key.substring(1))); const keysToPrevent = [ 'Tab', 'Enter', 'Escape', 'Backspace', 'Delete', 'Insert', 'Home', 'End', 'PageUp', 'PageDown', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', ' ' ];
                if (event.key.length === 1 && !event.ctrlKey && !event.altKey && !event.metaKey) { shouldPreventDefault = true; } else if (keysToPrevent.includes(event.key) && !(event.altKey && event.key === 'Tab')) { shouldPreventDefault = true; }
                if (event.metaKey && event.shiftKey && event.key.toLowerCase() === 's') { shouldPreventDefault = false; } if (event.altKey && event.key === 'Tab') { shouldPreventDefault = false; } if (event.ctrlKey && ['c', 'v', 'x', 'a', 'z', 'y', 'r', 't', 'w', 'l', 'p', 'f'].includes(event.key.toLowerCase())) { shouldPreventDefault = false; } if (isFKey) { shouldPreventDefault = false; } if (event.ctrlKey && event.shiftKey && ['i', 'j', 'c'].includes(event.key.toLowerCase())) { shouldPreventDefault = false; } if (event.ctrlKey && event.key === 'Tab') { shouldPreventDefault = false; }
                if (shouldPreventDefault) { event.preventDefault(); }
                const command = { action: 'keydown', key: event.key, code: event.code, ctrlKey: event.ctrlKey, shiftKey: event.shiftKey, altKey: event.altKey, metaKey: event.metaKey }; socket.emit('control_command', command);
            });
            document.body.addEventListener('keyup', (event) => {
                // console.log(`KeyUp: Key='${event.key}', Code='${event.code}'`); // Debug
                 if (event.key === 'Control') activeModifiers.ctrl = false; if (event.key === 'Shift') activeModifiers.shift = false; if (event.key === 'Alt') activeModifiers.alt = false; if (event.key === 'Meta') activeModifiers.meta = false;
                 const command = { action: 'keyup', key: event.key, code: event.code }; socket.emit('control_command', command);
            });
             window.addEventListener('blur', () => {
                 console.log('Window blurred - releasing tracked modifier keys');
                 if (activeModifiers.ctrl) { socket.emit('control_command', { action: 'keyup', key: 'Control', code: 'ControlLeft' }); activeModifiers.ctrl = false; } if (activeModifiers.shift) { socket.emit('control_command', { action: 'keyup', key: 'Shift', code: 'ShiftLeft' }); activeModifiers.shift = false; } if (activeModifiers.alt) { socket.emit('control_command', { action: 'keyup', key: 'Alt', code: 'AltLeft' }); activeModifiers.alt = false; } if (activeModifiers.meta) { socket.emit('control_command', { action: 'keyup', key: 'Meta', code: 'MetaLeft' }); activeModifiers.meta = false; }
             });

            updateStatus('status-connecting', 'Initializing...');
             document.body.focus();

        }); // End DOMContentLoaded
    </script>
</body>
</html>
"""

# --- Flask Routes (Unchanged) ---
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        password = request.form.get('password')
        if check_auth(password):
            session['authenticated'] = True
            print("Login successful.")
            return redirect(url_for('interface'))
        else:
            print("Login failed.")
            return render_template_string(LOGIN_HTML, error="Invalid password")
    if session.get('authenticated'):
        return redirect(url_for('interface'))
    return render_template_string(LOGIN_HTML)

@app.route('/interface')
def interface():
    if not session.get('authenticated'):
        print(f"Unauthorized access attempt to /interface.")
        return redirect(url_for('index'))
    return render_template_string(INTERFACE_HTML)

@app.route('/logout')
def logout():
    print("Logging out session.")
    session.pop('authenticated', None)
    return redirect(url_for('index'))

# --- SocketIO Events (Registration, Command Handling Unchanged) ---
@socketio.on('connect')
def handle_connect():
    sid = request.sid
    print(f"[SocketIO Connect] SID: {sid}")

@socketio.on('disconnect')
def handle_disconnect():
    global client_pc_sid
    sid = request.sid
    print(f"[SocketIO Disconnect] SID: {sid}")
    if sid == client_pc_sid:
        print("[!!!] Client PC disconnected.")
        client_pc_sid = None
        emit('client_disconnected', {'message': 'Remote PC disconnected'}, broadcast=True, include_self=False)

@socketio.on('register_client')
def handle_register_client(data):
    global client_pc_sid
    client_token = data.get('token')
    sid = request.sid
    if client_token == ACCESS_PASSWORD:
        if client_pc_sid and client_pc_sid != sid:
             print(f"[RegClient] New client ({sid}) replacing old ({client_pc_sid}). Disconnecting old.")
             try: socketio.disconnect(client_pc_sid)
             except Exception as e: print(f"Error disconnecting old client {client_pc_sid}: {e}", file=sys.stderr)
        elif client_pc_sid == sid: print(f"[RegClient] Re-registered: {sid}")
        else: print(f"[RegClient] Registered: {sid}")

        client_pc_sid = sid
        emit('client_connected', {'message': 'Remote PC connected'}, broadcast=True, include_self=False)
        emit('registration_success', room=sid)
    else:
        print(f"[RegClient] Authentication failed for SID: {sid}", file=sys.stderr)
        emit('registration_fail', {'message': 'Authentication failed'}, room=sid)
        disconnect(sid)


# --- *** NEW: Handler for Binary Screen Data *** ---
@socketio.on('screen_data_bytes')
def handle_screen_data_bytes(data):
    global last_broadcast_time # Allow modification
    if request.sid != client_pc_sid: return # Ignore if not from registered client

    current_time = time.time()
    if current_time - last_broadcast_time < MIN_INTERVAL:
        # print(f"Skipping binary frame, interval too short.") # Debug
        return # Skip frame for throttling

    try:
        # data is already the raw bytes
        if data and isinstance(data, bytes):
            # Broadcast the raw bytes directly
            emit('screen_frame_bytes', data, broadcast=True, include_self=False)
            last_broadcast_time = current_time # Update timestamp
            # print(f"Broadcast binary frame ({len(data)} bytes) at {current_time:.2f}") # Debug
        else:
             print(f"Warning: Received non-bytes data on screen_data_bytes from {request.sid}", file=sys.stderr)

    except Exception as e:
        print(f"!!! ERROR in handle_screen_data_bytes from SID {request.sid}: {e}", file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)


# --- Kept OLD Base64 Handler (for fallback if client uses it) ---
@socketio.on('screen_data')
def handle_screen_data(data):
    global last_broadcast_time
    if request.sid != client_pc_sid: return # Ignore

    print("[Warning] Received data on legacy 'screen_data' event. Client might not be using binary mode.", file=sys.stderr)

    current_time = time.time()
    if current_time - last_broadcast_time < MIN_INTERVAL: return # Throttle

    try:
        image_data = data.get('image') # Expects dict with 'image' key (Base64)
        if image_data and isinstance(image_data, str):
            # Broadcast using the old event name expected by the legacy JS handler
            emit('screen_update', {'image': image_data}, broadcast=True, include_self=False)
            last_broadcast_time = current_time
        else:
             print(f"Warning: Received invalid data format on screen_data from {request.sid}", file=sys.stderr)
    except Exception as e:
        print(f"!!! ERROR in handle_screen_data (legacy) from SID {request.sid}: {e}", file=sys.stderr)
        print(traceback.format_exc(), file=sys.stderr)


# --- Control Command Handler (Unchanged) ---
@socketio.on('control_command')
def handle_control_command(data):
    sid = request.sid
    if client_pc_sid:
        emit('command', data, room=client_pc_sid)
        # print(f"Sent command {data.get('action')} to {client_pc_sid}") # Debug
    else:
        emit('command_error', {'message': 'Client PC not connected'}, room=sid)


# --- Main Execution (Unchanged) ---
if __name__ == '__main__':
    print("--- Starting Flask-SocketIO Server (Optimized for Binary Data) ---")
    port = int(os.environ.get('PORT', 5000))
    print(f"Host: 0.0.0.0 | Port: {port}")
    print(f"Target Server Broadcast FPS: {TARGET_FPS} (Interval: {MIN_INTERVAL:.3f}s)")
    print(f"Binary Screen Handler: ENABLED ('screen_data_bytes' -> 'screen_frame_bytes')")
    print(f"Legacy Base64 Handler: ENABLED ('screen_data' -> 'screen_update')")
    print(f"Access password configured: {'Yes' if ACCESS_PASSWORD != 'change_this_password_too' else 'No (Using default)'}")
    print(f"Secret key configured: {'Yes' if SECRET_KEY != 'change_this_strong_secret_key_12345' else 'No (Using default)'}")
    print("-------------------------------------------------------------")
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
