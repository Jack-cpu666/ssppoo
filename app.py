# Consolidated Server (app.py)
# Flask web server with SocketIO, HTML, CSS, and JS embedded.
# Includes direct keyboard event capture in the browser.

# IMPORTANT: eventlet.monkey_patch() must be called before other imports
import eventlet
eventlet.monkey_patch()

import os
import base64
from flask import Flask, request, session, redirect, url_for, render_template_string, Response
from flask_socketio import SocketIO, emit, join_room, leave_room, disconnect
import traceback # For detailed error logging


# --- Configuration ---
SECRET_KEY = os.environ.get('FLASK_SECRET_KEY', 'change_this_strong_secret_key_12345')
ACCESS_PASSWORD = os.environ.get('REMOTE_ACCESS_PASSWORD', 'change_this_password_too')

# --- Flask App Setup ---
app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
socketio = SocketIO(app, async_mode='eventlet', ping_timeout=20, ping_interval=10)

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

# --- MODIFIED INTERFACE_HTML with updated JS ---
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
                      onerror="this.onerror=null; this.src='https://placehold.co/600x338/333333/CCCCCC?text=Error+Loading+Screen';">
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

            document.body.focus();
            document.addEventListener('click', (e) => { if (e.target !== screenImage) { document.body.focus(); } });

            function updateStatus(status, message) { connectionStatusText.textContent = message; connectionStatusDot.className = `status-dot ${status}`; }
            function showClickFeedback(x, y, elementRect) { const feedback = document.createElement('div'); feedback.className = 'click-feedback'; feedback.style.left = `${x}px`; feedback.style.top = `${y}px`; screenView.appendChild(feedback); setTimeout(() => { feedback.remove(); }, 400); }

            socket.on('connect', () => { console.log('Connected to server'); updateStatus('status-connecting', 'Server connected, waiting for remote PC...'); });
            socket.on('disconnect', () => { console.warn('Disconnected from server'); updateStatus('status-disconnected', 'Server disconnected'); screenImage.src = '...Disconnected'; remoteScreenWidth = null; remoteScreenHeight = null; });
            socket.on('connect_error', (error) => { console.error('Connection Error:', error); updateStatus('status-disconnected', 'Connection Error'); screenImage.src = '...Connection+Error'; });
            socket.on('client_connected', (data) => { console.log(data.message); updateStatus('status-connected', 'Remote PC Connected'); document.body.focus(); });
            socket.on('client_disconnected', (data) => { console.warn(data.message); updateStatus('status-disconnected', 'Remote PC Disconnected'); screenImage.src = '...PC+Disconnected'; remoteScreenWidth = null; remoteScreenHeight = null; });
            socket.on('command_error', (data) => { console.error('Command Error:', data.message); });

            socket.on('screen_update', (data) => {
                const imageSrc = `data:image/jpeg;base64,${data.image}`;
                 screenImage.src = imageSrc;
                if (remoteScreenWidth === null || remoteScreenHeight === null) {
                     const tempImg = new Image();
                     tempImg.onload = () => { if (remoteScreenWidth === null) { remoteScreenWidth = tempImg.naturalWidth; remoteScreenHeight = tempImg.naturalHeight; console.log(`Remote screen resolution: ${remoteScreenWidth}x${remoteScreenHeight}`); } };
                     tempImg.onerror = () => console.error("Error loading image dimensions.");
                     tempImg.src = imageSrc;
                }
            });

            // --- Mouse Handling ---
             screenImage.addEventListener('mousemove', (event) => { if (!remoteScreenWidth) return; const rect = screenImage.getBoundingClientRect(); const x = event.clientX - rect.left; const y = event.clientY - rect.top; const remoteX = Math.round((x / rect.width) * remoteScreenWidth); const remoteY = Math.round((y / rect.height) * remoteScreenHeight); socket.emit('control_command', { action: 'move', x: remoteX, y: remoteY }); });
             screenImage.addEventListener('click', (event) => { if (!remoteScreenWidth) return; const rect = screenImage.getBoundingClientRect(); const x = event.clientX - rect.left; const y = event.clientY - rect.top; const remoteX = Math.round((x / rect.width) * remoteScreenWidth); const remoteY = Math.round((y / rect.height) * remoteScreenHeight); socket.emit('control_command', { action: 'click', button: 'left', x: remoteX, y: remoteY }); showClickFeedback(x, y, rect); document.body.focus(); });
             screenImage.addEventListener('contextmenu', (event) => { event.preventDefault(); if (!remoteScreenWidth) return; const rect = screenImage.getBoundingClientRect(); const x = event.clientX - rect.left; const y = event.clientY - rect.top; const remoteX = Math.round((x / rect.width) * remoteScreenWidth); const remoteY = Math.round((y / rect.height) * remoteScreenHeight); socket.emit('control_command', { action: 'click', button: 'right', x: remoteX, y: remoteY }); showClickFeedback(x, y, rect); document.body.focus(); });
             screenImage.addEventListener('wheel', (event) => { event.preventDefault(); const deltaY = event.deltaY > 0 ? 1 : (event.deltaY < 0 ? -1 : 0); const deltaX = event.deltaX > 0 ? 1 : (event.deltaX < 0 ? -1 : 0); if (deltaY !== 0 || deltaX !== 0) { socket.emit('control_command', { action: 'scroll', dx: deltaX, dy: deltaY }); } document.body.focus(); });

            // --- Keyboard Event Handling ---
            document.body.addEventListener('keydown', (event) => {
                console.log(`KeyDown: Key='${event.key}', Code='${event.code}', Ctrl=${event.ctrlKey}, Shift=${event.shiftKey}, Alt=${event.altKey}, Meta=${event.metaKey}`);

                // Update internal modifier state tracker
                if (event.key === 'Control') activeModifiers.ctrl = true;
                if (event.key === 'Shift') activeModifiers.shift = true;
                if (event.key === 'Alt') activeModifiers.alt = true;
                if (event.key === 'Meta') activeModifiers.meta = true;

                // --- PreventDefault Logic ---
                // Goal: Prevent default for keys that type or navigate within the *browser page*,
                // but ALLOW OS-level shortcuts (like Win+Shift+S, Alt+Tab, Ctrl+C/V etc.)
                let shouldPreventDefault = false;

                const isModifierKey = ['Control', 'Shift', 'Alt', 'Meta', 'CapsLock', 'NumLock', 'ScrollLock'].includes(event.key);
                const isFKey = event.key.startsWith('F') && event.key.length > 1 && !isNaN(parseInt(event.key.substring(1))); // F1-F12

                // Keys we generally WANT to intercept and send to remote
                const keysToPrevent = [
                    'Tab', 'Enter', 'Escape', 'Backspace', 'Delete', 'Insert',
                    'Home', 'End', 'PageUp', 'PageDown',
                    'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
                    ' ' // Spacebar
                ];

                // Check if it's a simple printable character (without Ctrl/Alt/Meta modifiers)
                if (event.key.length === 1 && !event.ctrlKey && !event.altKey && !event.metaKey) {
                     shouldPreventDefault = true;
                }
                // Check if it's one of the specific keys we want to capture
                else if (keysToPrevent.includes(event.key)) {
                     shouldPreventDefault = true;
                }
                 // Allow F-keys to pass through by default (don't prevent) unless Ctrl/Alt/Shift are also held? Decide based on need.
                 // else if (isFKey) { /* Allow F keys by default */ }

                // *** DO NOT PREVENT DEFAULT for specific OS combinations ***
                // Example: Allow Win+Shift+S
                if (event.metaKey && event.shiftKey && event.key.toLowerCase() === 's') {
                    console.log("Allowing Win+Shift+S");
                    shouldPreventDefault = false;
                }
                // Example: Allow Alt+Tab (usually handled by OS anyway)
                if (event.altKey && event.key === 'Tab') {
                     console.log("Allowing Alt+Tab");
                     shouldPreventDefault = false;
                }
                 // Example: Allow Ctrl+C, Ctrl+V, Ctrl+X (Common text operations) - browser often handles these well even if default isn't prevented
                 if (event.ctrlKey && ['c', 'v', 'x', 'a', 'z', 'y', 'r', 't', 'w', 'l', 'p'].includes(event.key.toLowerCase())) {
                      console.log(`Allowing Ctrl+${event.key}`);
                      shouldPreventDefault = false; // Let browser handle copy/paste etc. unless it causes issues
                 }


                if (shouldPreventDefault) {
                    console.log("Preventing default browser action for key:", event.key);
                    event.preventDefault();
                } else {
                     console.log("Allowing default browser action for key:", event.key);
                }


                // Send the event regardless of preventDefault status (client decides how to handle)
                const command = {
                    action: 'keydown',
                    key: event.key, code: event.code,
                    ctrlKey: event.ctrlKey, shiftKey: event.shiftKey, altKey: event.altKey, metaKey: event.metaKey
                };
                socket.emit('control_command', command);
            });

            document.body.addEventListener('keyup', (event) => {
                console.log(`KeyUp: Key='${event.key}', Code='${event.code}'`);

                // Update internal modifier state tracker
                 if (event.key === 'Control') activeModifiers.ctrl = false;
                 if (event.key === 'Shift') activeModifiers.shift = false;
                 if (event.key === 'Alt') activeModifiers.alt = false;
                 if (event.key === 'Meta') activeModifiers.meta = false;

                // Send keyup event to client
                const command = { action: 'keyup', key: event.key, code: event.code };
                socket.emit('control_command', command);
            });

             window.addEventListener('blur', () => {
                 console.log('Window blurred - releasing tracked modifier keys');
                 // Send keyup events for any modifiers thought to be active
                 if (activeModifiers.ctrl) { socket.emit('control_command', { action: 'keyup', key: 'Control', code: 'ControlLeft' }); activeModifiers.ctrl = false; }
                 if (activeModifiers.shift) { socket.emit('control_command', { action: 'keyup', key: 'Shift', code: 'ShiftLeft' }); activeModifiers.shift = false; }
                 if (activeModifiers.alt) { socket.emit('control_command', { action: 'keyup', key: 'Alt', code: 'AltLeft' }); activeModifiers.alt = false; }
                 if (activeModifiers.meta) { socket.emit('control_command', { action: 'keyup', key: 'Meta', code: 'MetaLeft' }); activeModifiers.meta = false; }
             });

            updateStatus('status-connecting', 'Initializing...');
             document.body.focus();

        }); // End DOMContentLoaded
    </script>
</body>
</html>
"""

# --- Flask Routes --- (No changes needed from previous version)
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        password = request.form.get('password')
        if check_auth(password):
            session['authenticated'] = True
            print("Login successful.") # No SID here
            return redirect(url_for('interface'))
        else:
            print("Login failed.") # No SID here
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
    print("Logging out session.") # No SID here
    session.pop('authenticated', None)
    return redirect(url_for('index'))

# --- SocketIO Events --- (No changes needed from previous version)
@socketio.on('connect')
def handle_connect():
    sid = request.sid
    print(f"Socket connected: {sid}")

@socketio.on('disconnect')
def handle_disconnect():
    global client_pc_sid
    sid = request.sid
    print(f"Socket disconnected: {sid}")
    if sid == client_pc_sid:
        print("Client PC disconnected.")
        client_pc_sid = None
        emit('client_disconnected', {'message': 'Remote PC disconnected'}, broadcast=True, include_self=False)

@socketio.on('register_client')
def handle_register_client(data):
    global client_pc_sid
    client_token = data.get('token')
    sid = request.sid
    if client_token == ACCESS_PASSWORD:
        if client_pc_sid and client_pc_sid != sid:
             print(f"New client PC ({sid}) detected, disconnecting old one ({client_pc_sid}).")
             socketio.disconnect(client_pc_sid)
        elif client_pc_sid == sid:
             print(f"Client PC ({sid}) re-registered.")
        else:
             print(f"Client PC registered: {sid}")
        client_pc_sid = sid
        emit('client_connected', {'message': 'Remote PC connected'}, broadcast=True, include_self=False)
        emit('registration_success', room=sid)
    else:
        print(f"Client PC authentication failed for SID: {sid}")
        emit('registration_fail', {'message': 'Authentication failed'}, room=sid)
        disconnect(sid)

@socketio.on('screen_data')
def handle_screen_data(data):
    if request.sid != client_pc_sid: return
    try:
        image_data = data.get('image')
        if image_data:
            emit('screen_update', {'image': image_data}, broadcast=True, include_self=False)
    except Exception as e:
        print(f"!!! ERROR in handle_screen_data from SID {request.sid}: {e}")
        print(traceback.format_exc())

@socketio.on('control_command')
def handle_control_command(data):
    sid = request.sid
    if not session.get('authenticated'): return
    if client_pc_sid:
        emit('command', data, room=client_pc_sid)
    else:
        emit('command_error', {'message': 'Client PC not connected'}, room=sid)

# --- Main Execution --- (No changes needed from previous version)
if __name__ == '__main__':
    print("Starting Flask-SocketIO server...")
    port = int(os.environ.get('PORT', 5000))
    print(f"Server will run on host 0.0.0.0, port {port}")
    print(f"Access password configured: {'Yes' if ACCESS_PASSWORD else 'No'}")
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
