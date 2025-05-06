# Client implementation (client.py) using ctypes for input control
# OPTIMIZED VERSION: Sends binary JPEG data, tunable quality/FPS.
# Runs on the Windows PC to capture screen and execute commands

import socketio
import mss
import io
import base64
import time
import threading
import os
import sys
import traceback # Added for better error printing
from PIL import Image
import ctypes
import ctypes.wintypes
import math

# --- Configuration ---
SERVER_URL = os.environ.get('REMOTE_SERVER_URL', 'https://ssppoo.onrender.com')
ACCESS_PASSWORD = os.environ.get('REMOTE_ACCESS_PASSWORD', 'change_this_password_too') # MUST MATCH SERVER

# --- Core Optimization Settings ---
SEND_BINARY_DATA = True # True: Send raw bytes (RECOMMENDED, REQUIRES SERVER/CONTROLLER UPDATE)
                        # False: Send Base64 (Original method, higher bandwidth)

FPS = 12 # Target frames per second (Increase carefully, impacts CPU/Network)
JPEG_QUALITY = 55 # JPEG quality (Lower = smaller size, faster encode, less quality. Range 1-100. Try 40-70)

# Mouse Smoothing settings (Reduced duration for potentially less perceived lag)
MOUSE_MOVE_DURATION = 0.03 # Time (seconds) for the smoothed move animation
MOUSE_MOVE_STEPS = 3      # Number of intermediate steps for smoothing

# --- CTypes Constants and Structures ---
# (Keep existing CTypes constants: MOUSEEVENTF_*, KEYEVENTF_*, VK_CODE_MAP, EXTENDED_KEYS)
# Constants for mouse_event
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_HWHEEL = 0x1000 # Horizontal wheel
MOUSEEVENTF_ABSOLUTE = 0x8000

# Constants for keybd_event
KEYEVENTF_KEYDOWN = 0x0000
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001 # For keys like Right Ctrl, Right Alt, Arrow keys, etc.

# Basic Virtual-Key Code mapping (Expand as needed)
# Based on https://learn.microsoft.com/en-us/windows/win32/inputdev/virtual-key-codes
VK_CODE_MAP = {
    # Modifiers (Special handling often needed for L/R versions)
    'Shift': 0x10, 'ShiftLeft': 0xA0, 'ShiftRight': 0xA1,
    'Control': 0x11, 'ControlLeft': 0xA2, 'ControlRight': 0xA3,
    'Alt': 0x12, 'AltLeft': 0xA4, 'AltRight': 0xA5,
    'Meta': 0x5B, 'MetaLeft': 0x5B, 'MetaRight': 0x5C, # Windows Key
    'CapsLock': 0x14,
    'Tab': 0x09,
    'Enter': 0x0D,
    'Escape': 0x1B,
    'Space': 0x20, ' ': 0x20,
    'Backspace': 0x08,
    'Delete': 0x2E,
    'Insert': 0x2D,
    'Home': 0x24,
    'End': 0x23,
    'PageUp': 0x21,
    'PageDown': 0x22,
    # Arrow Keys
    'ArrowUp': 0x26,
    'ArrowDown': 0x28,
    'ArrowLeft': 0x25,
    'ArrowRight': 0x27,
    # Function Keys
    'F1': 0x70, 'F2': 0x71, 'F3': 0x72, 'F4': 0x73, 'F5': 0x74, 'F6': 0x75,
    'F7': 0x76, 'F8': 0x77, 'F9': 0x78, 'F10': 0x79, 'F11': 0x7A, 'F12': 0x7B,
    # Letters (Case insensitive mapping, VK codes are for uppercase)
    'a': 0x41, 'b': 0x42, 'c': 0x43, 'd': 0x44, 'e': 0x45, 'f': 0x46, 'g': 0x47,
    'h': 0x48, 'i': 0x49, 'j': 0x4A, 'k': 0x4B, 'l': 0x4C, 'm': 0x4D, 'n': 0x4E,
    'o': 0x4F, 'p': 0x50, 'q': 0x51, 'r': 0x52, 's': 0x53, 't': 0x54, 'u': 0x55,
    'v': 0x56, 'w': 0x57, 'x': 0x58, 'y': 0x59, 'z': 0x5A,
    # Numbers (Top row)
    '0': 0x30, '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34,
    '5': 0x35, '6': 0x36, '7': 0x37, '8': 0x38, '9': 0x39,
    # Basic Punctuation (May vary with keyboard layout)
    '`': 0xC0, '-': 0xBD, '=': 0xBB, '[': 0xDB, ']': 0xDD, '\\': 0xDC,
    ';': 0xBA, "'": 0xDE, ',': 0xBC, '.': 0xBE, '/': 0xBF,
    # Numpad Keys (Example) - Need separate mapping if distinction required
    # 'Numpad0': 0x60, ...
}

# Extended key flag needed for certain keys
EXTENDED_KEYS = {
    0xA3, # Right Ctrl
    0xA5, # Right Alt
    0x2E, # Delete
    0x2D, # Insert
    0x24, # Home
    0x23, # End
    0x21, # PageUp
    0x22, # PageDown
    0x26, # ArrowUp
    0x28, # ArrowDown
    0x25, # ArrowLeft
    0x27, # ArrowRight
}

user32 = ctypes.windll.user32
# Get screen dimensions using ctypes (generally reliable on Windows)
screen_width = user32.GetSystemMetrics(0) # SM_CXSCREEN
screen_height = user32.GetSystemMetrics(1) # SM_CYSCREEN

# --- Global Variables ---
sio = socketio.Client(logger=False, engineio_logger=False, reconnection_attempts=5, reconnection_delay=3)
stop_event = threading.Event()
capture_thread = None
is_connected = False
monitor_dimensions = {"width": screen_width, "height": screen_height}
last_mouse_pos = {'x': 0, 'y': 0} # Track last known mouse position for smooth move

# --- Input Simulation Functions (using CTypes - Mostly unchanged) ---

def get_vk_code(key_name_or_code):
    """ Tries to map browser key/code names to Windows VK codes. """
    # Prefer 'code' if available (e.g., 'KeyA', 'Digit1') as it's layout independent
    # Fallback to 'key' (e.g., 'a', ';', 'Enter')
    if not key_name_or_code: return None # Handle empty input

    key_lower = key_name_or_code.lower()

    # Direct lookup using common names/codes
    if key_name_or_code in VK_CODE_MAP:
        return VK_CODE_MAP[key_name_or_code]
    if key_lower in VK_CODE_MAP:
        return VK_CODE_MAP[key_lower]

    # Handle 'KeyA', 'KeyB', etc.
    if key_name_or_code.startswith('Key') and len(key_name_or_code) == 4:
        char = key_name_or_code[3:].lower()
        if char in VK_CODE_MAP:
            return VK_CODE_MAP[char]

    # Handle 'Digit1', 'Digit2', etc.
    if key_name_or_code.startswith('Digit') and len(key_name_or_code) == 6:
        char = key_name_or_code[5:]
        if char in VK_CODE_MAP:
            return VK_CODE_MAP[char]

    # Add more specific mappings here if needed (Numpad keys, etc.)
    print(f"Warning: Unmapped key/code: {key_name_or_code}")
    return None


def press_key(vk_code):
    """ Sends a key down event using keybd_event. """
    if vk_code is None: return
    flags = KEYEVENTF_KEYDOWN
    if vk_code in EXTENDED_KEYS:
        flags |= KEYEVENTF_EXTENDEDKEY
    user32.keybd_event(vk_code, 0, flags, 0)

def release_key(vk_code):
    """ Sends a key up event using keybd_event. """
    if vk_code is None: return
    flags = KEYEVENTF_KEYUP
    if vk_code in EXTENDED_KEYS:
        flags |= KEYEVENTF_EXTENDEDKEY
    user32.keybd_event(vk_code, 0, flags, 0)


def mouse_move_to(x, y, smooth=True):
    """ Moves the mouse cursor to absolute coordinates (x, y). """
    global last_mouse_pos
    # Clamp coordinates to screen bounds
    target_x = max(0, min(int(x), screen_width - 1))
    target_y = max(0, min(int(y), screen_height - 1))

    # Avoid moving if already there
    if target_x == last_mouse_pos['x'] and target_y == last_mouse_pos['y']:
        return

    if not smooth or MOUSE_MOVE_DURATION <= 0:
        user32.SetCursorPos(target_x, target_y)
    else:
        start_x = last_mouse_pos['x']
        start_y = last_mouse_pos['y']
        start_time = time.monotonic()
        end_time = start_time + MOUSE_MOVE_DURATION

        # Calculate total steps based on duration and minimum step time
        effective_steps = max(1, MOUSE_MOVE_STEPS) # Ensure at least one step
        step_interval = MOUSE_MOVE_DURATION / effective_steps

        for i in range(1, effective_steps + 1):
            progress = min(i / effective_steps, 1.0)
            # Simple linear interpolation (could use easing functions for fancier feel)
            current_x = int(start_x + (target_x - start_x) * progress)
            current_y = int(start_y + (target_y - start_y) * progress)
            user32.SetCursorPos(current_x, current_y)
            # Check if we need to sleep before the next step
            if time.monotonic() < start_time + (i * step_interval):
                 time.sleep(max(0.001, start_time + (i * step_interval) - time.monotonic())) # Precise sleep

        # Ensure final position is exact in case of rounding/timing issues
        if last_mouse_pos['x'] != target_x or last_mouse_pos['y'] != target_y:
             user32.SetCursorPos(target_x, target_y)

    last_mouse_pos = {'x': target_x, 'y': target_y}


def mouse_click(button='left'):
    """ Performs a mouse click using mouse_event. """
    if button == 'left':
        down_flag, up_flag = MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP
    elif button == 'right':
        down_flag, up_flag = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
    elif button == 'middle':
        down_flag, up_flag = MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP
    else:
        print(f"Unsupported click button: {button}")
        return

    user32.mouse_event(down_flag, 0, 0, 0, 0)
    time.sleep(0.01) # Small delay between down/up might be necessary for some apps
    user32.mouse_event(up_flag, 0, 0, 0, 0)

def mouse_scroll(dx=0, dy=0):
    """ Performs mouse wheel scroll using mouse_event. """
    wheel_delta_unit = 120 # Standard unit for wheel delta

    if dy != 0:
        scroll_amount = -int(dy * wheel_delta_unit) # Invert dy for MOUSEEVENTF_WHEEL
        user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, scroll_amount, 0)
        time.sleep(0.005) # Small delay might help prevent lost scroll events

    if dx != 0:
         scroll_amount = int(dx * wheel_delta_unit)
         user32.mouse_event(MOUSEEVENTF_HWHEEL, 0, 0, scroll_amount, 0)
         time.sleep(0.005)


# --- Screen Capture Thread (OPTIMIZED) ---
def capture_and_send_screen():
    """Captures the screen and sends it to the server via SocketIO (Binary or Base64)."""
    global is_connected, monitor_dimensions
    last_capture_time = 0
    interval = 1.0 / FPS # Target interval between frames

    if not monitor_dimensions or monitor_dimensions["width"] <= 0 or monitor_dimensions["height"] <= 0:
        print("FATAL: Invalid monitor dimensions detected.")
        stop_event.set()
        return

    monitor_area = {"top": 0, "left": 0, "width": monitor_dimensions["width"], "height": monitor_dimensions["height"]}
    print(f"Capture thread starting for area: {monitor_area} at {FPS} FPS, Quality: {JPEG_QUALITY}, Binary: {SEND_BINARY_DATA}")

    try:
        with mss.mss() as sct_instance:
            while not stop_event.is_set():
                if not is_connected or not sio.connected:
                    time.sleep(0.2) # Wait longer if not connected
                    continue

                start_time = time.monotonic()

                # --- Capture ---
                try:
                    img = sct_instance.grab(monitor_area)
                except mss.ScreenShotError as ex:
                    print(f"Screen capture error: {ex}. Retrying...")
                    time.sleep(1)
                    continue # Skip rest of loop iteration

                # --- Convert and Encode ---
                try:
                    pil_img = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")
                    buffer = io.BytesIO()
                    pil_img.save(buffer, format='JPEG', quality=JPEG_QUALITY)
                    # buffer.seek(0) # No need to seek before getvalue()
                    jpeg_data = buffer.getvalue()
                except Exception as e:
                    print(f"Error during Image processing/encoding: {e}")
                    print(traceback.format_exc())
                    time.sleep(0.5)
                    continue # Skip send if encoding failed

                # --- Send Data ---
                if is_connected and sio.connected:
                    try:
                        if SEND_BINARY_DATA:
                            # Send raw bytes (Requires server/client JS update)
                            sio.emit('screen_data_bytes', jpeg_data)
                        else:
                            # Send Base64 encoded string (Original method)
                            img_base64 = base64.b64encode(jpeg_data).decode('utf-8')
                            sio.emit('screen_data', {'image': img_base64})
                    except socketio.exceptions.BadNamespaceError:
                        print("SocketIO BadNamespaceError during send. Assuming disconnected.")
                        is_connected = False # Trigger potential reconnect logic
                        time.sleep(1) # Wait before next attempt
                    except Exception as e:
                        print(f"Error sending screen data: {e}")
                        if not sio.connected:
                            is_connected = False
                        time.sleep(0.5)
                else:
                     # print("Not connected, skipping send.") # Reduce noise
                     pass


                # --- Frame Rate Control ---
                processing_time = time.monotonic() - start_time
                sleep_duration = interval - processing_time
                if sleep_duration > 0.001: # Only sleep if meaningful duration
                    time.sleep(sleep_duration)
                # else: print(f"Warning: Frame processing took longer than interval: {processing_time:.4f}s") # Optional debug

            # End of while loop
    except Exception as e:
        print(f"FATAL error initializing mss or in capture thread setup: {e}")
        print(traceback.format_exc())
        stop_event.set() # Ensure main loop exits

    print("Screen capture thread stopped.")


# --- SocketIO Event Handlers ---
@sio.event
def connect():
    global is_connected, monitor_dimensions, last_mouse_pos
    print(f"Successfully connected to server: {SERVER_URL} (sid: {sio.sid})")

    # Verify dimensions again on connect, maybe primary monitor changed?
    try:
        current_width = user32.GetSystemMetrics(0)
        current_height = user32.GetSystemMetrics(1)
        if current_width != monitor_dimensions["width"] or current_height != monitor_dimensions["height"]:
             print(f"Monitor dimensions changed! Updating to: {current_width}x{current_height}")
             monitor_dimensions = {"width": current_width, "height": current_height}
    except Exception as e:
         print(f"Could not re-verify monitor dimensions on connect: {e}")


    # Get initial mouse position reliably
    try:
        point = ctypes.wintypes.POINT()
        if user32.GetCursorPos(ctypes.byref(point)):
            last_mouse_pos = {'x': point.x, 'y': point.y}
            print(f"Initial mouse position: {last_mouse_pos}")
        else:
             print("Warning: Failed to get initial cursor position.")
             last_mouse_pos = {'x': screen_width // 2, 'y': screen_height // 2} # Default to center
    except Exception as e:
        print(f"Error getting cursor pos: {e}")
        last_mouse_pos = {'x': screen_width // 2, 'y': screen_height // 2}

    print("Registering with server...")
    is_connected = True # Tentatively set true, registration confirm will solidify
    try:
        sio.emit('register_client', {'token': ACCESS_PASSWORD})
    except Exception as e:
        print(f"Error emitting registration: {e}")
        is_connected = False
        if sio.connected:
            sio.disconnect()

@sio.event
def connect_error(data):
    global is_connected
    print(f"Connection failed: {data}")
    is_connected = False
    # No need to set stop_event here, main loop handles retries

@sio.event
def disconnect():
    global is_connected
    print("Disconnected from server.")
    is_connected = False
    # Stop capture thread only if not attempting reconnection automatically
    if not sio.reconnecting:
         print("Stopping capture thread due to permanent disconnect.")
         stop_event.set()

@sio.on('registration_success')
def on_registration_success():
    global capture_thread, is_connected
    print("Client registration successful.")
    is_connected = True # Confirm connection state
    if capture_thread is None or not capture_thread.is_alive():
        print("Starting screen capture thread...")
        stop_event.clear() # Clear stop flag if previously set
        try:
            capture_thread = threading.Thread(target=capture_and_send_screen, args=(), daemon=True)
            capture_thread.start()
            print(f"Capture thread started (Target FPS: {FPS}, Quality: {JPEG_QUALITY}, Binary: {SEND_BINARY_DATA}).")
        except Exception as e:
             print(f"Failed to start capture thread: {e}")
             stop_event.set()
             is_connected = False
             if sio.connected:
                 sio.disconnect()
    else:
        print("Capture thread already running.")

@sio.on('registration_fail')
def on_registration_fail(data):
    print(f"Client registration failed: {data.get('message', 'No reason given')}")
    is_connected = False
    if sio.connected:
        sio.disconnect() # Disconnect if registration fails

# --- Command Handler (Optimized for less lag potential) ---
@sio.on('command')
def handle_command(data):
    # Lightweight check first
    if not is_connected:
        # print("Skipping command, not connected/registered.") # Reduce noise
        return

    action = data.get('action')
    # print(f"Rcv cmd: {action}", data) # Debug - uncomment if needed

    try:
        if action == 'move':
            x = data.get('x')
            y = data.get('y')
            if x is not None and y is not None:
                mouse_move_to(x, y, smooth=True) # Use smoothing for move only events

        elif action == 'click':
            button = data.get('button', 'left')
            x = data.get('x') # Optional coordinates for click
            y = data.get('y')
            if x is not None and y is not None:
                # Move instantly before click for better responsiveness
                mouse_move_to(x, y, smooth=False)
            mouse_click(button)

        elif action == 'keydown':
            key_name = data.get('key')
            key_code_str = data.get('code')
            map_key = key_code_str if key_code_str else key_name
            vk_code = get_vk_code(map_key)
            if vk_code:
                 press_key(vk_code)
            # else: print(f"Unmapped keydown: key='{key_name}', code='{key_code_str}'") # Reduce noise

        elif action == 'keyup':
            key_name = data.get('key')
            key_code_str = data.get('code')
            map_key = key_code_str if key_code_str else key_name
            vk_code = get_vk_code(map_key)
            if vk_code:
                 release_key(vk_code)
            # else: print(f"Unmapped keyup: key='{key_name}', code='{key_code_str}'") # Reduce noise

        elif action == 'scroll':
            dx = data.get('dx', 0)
            dy = data.get('dy', 0)
            # Only call if there's actually scrolling to do
            if dx != 0 or dy != 0:
                mouse_scroll(dx=dx, dy=dy)

        else:
            print(f"Unknown command action: {action}")

    except Exception as e:
        print(f"Error executing command {data}: {e}")
        print(traceback.format_exc())


# --- Main Execution ---
def main():
    global capture_thread, is_connected
    print("--------------------------------------------------")
    print("Starting Remote Control Client (Optimized CTypes)")
    print("--------------------------------------------------")
    print(f"Server URL: {SERVER_URL}")
    print(f"Using Password: {'*' * len(ACCESS_PASSWORD) if ACCESS_PASSWORD else 'None'}")
    print(f"Screen Resolution: {screen_width}x{screen_height}")
    print(f"Target FPS: {FPS}")
    print(f"JPEG Quality: {JPEG_QUALITY}")
    print(f"Send Binary Data: {SEND_BINARY_DATA} "
          f"{'(Requires Server/Controller Update!)' if SEND_BINARY_DATA else '(Using Base64)'}")
    print("--------------------------------------------------")


    while not stop_event.is_set():
        is_connected = False # Reset connection status before attempt

        try:
            print(f"Attempting connection to {SERVER_URL}...")
            sio.connect(SERVER_URL,
                        transports=['websocket'], # Force websocket for potentially lower latency
                        wait_timeout=10)
            # If connect succeeds, sio.wait() blocks until disconnected
            print("Connection established, waiting for events...")
            sio.wait()
            print("sio.wait() finished (disconnected or error).")

        except socketio.exceptions.ConnectionError as e:
            print(f"Connection Error: {e}. Retrying in {sio.reconnection_delay}s...")
            # SocketIO client handles reconnection attempts automatically based on its settings
            # We just need to wait before the *next* explicit connect call if all retries fail
            time.sleep(sio.reconnection_delay)
        except Exception as e:
             print(f"An unexpected error occurred in connection loop: {e}.")
             print(traceback.format_exc())
             print(f"Retrying in {sio.reconnection_delay}s...")
             time.sleep(sio.reconnection_delay) # Wait before next manual attempt


        # If we reach here, it means sio.wait() returned (disconnected)
        # Or an exception occurred during connect itself.
        is_connected = False
        print("Connection lost or failed. Will attempt reconnection if configured.")

        # Check if SocketIO is still trying to reconnect in the background
        if sio.reconnecting:
            print("SocketIO is attempting reconnection in the background...")
            while sio.reconnecting and not stop_event.is_set():
                 time.sleep(1)
            if sio.connected:
                 print("Reconnection successful!")
                 continue # Go back to the top of the while loop to wait for events
            else:
                 print("Background reconnection failed.")


        # Explicitly stop capture thread if not connected and not reconnecting
        if capture_thread and capture_thread.is_alive():
             print("Ensuring capture thread is stopped...")
             stop_event.set() # Signal thread to stop
             capture_thread.join(timeout=2)
             if capture_thread.is_alive():
                 print("Warning: Capture thread did not stop gracefully.")
             capture_thread = None
             stop_event.clear() # Clear for the next potential connection

        # Wait before the next *manual* connection attempt in the main loop
        # (Only if stop wasn't requested)
        if not stop_event.is_set():
            print(f"Waiting {sio.reconnection_delay}s before next manual connection attempt...")
            time.sleep(sio.reconnection_delay)


    # End of main while loop (stop_event is set)
    print("Stop event detected, exiting main loop.")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nCtrl+C detected. Initiating shutdown...")
        stop_event.set()
    finally:
        print("--------------------------------------------------")
        print("Performing final client cleanup...")
        stop_event.set() # Ensure flag is set

        if sio and sio.connected:
            print("Disconnecting SocketIO...")
            try:
                sio.disconnect()
            except Exception as e:
                print(f"Error during final disconnect: {e}")

        if capture_thread and capture_thread.is_alive():
             print("Waiting for capture thread final exit...")
             capture_thread.join(timeout=3)
             if capture_thread.is_alive():
                  print("Warning: Capture thread did not exit in time.")

        print("Client shutdown complete.")
        print("--------------------------------------------------")
        sys.exit(0)
