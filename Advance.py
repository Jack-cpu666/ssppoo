# Client implementation (client.py) using ctypes for input control
# OPTIMIZED VERSION 2: Sends binary JPEG data, tunable quality/FPS, improved timing & robustness.
# Runs on the Windows PC to capture screen and execute commands

import socketio
import mss
import io
import base64
import time
import threading
import os
import sys
import traceback
from PIL import Image
import ctypes
import ctypes.wintypes
import math

# --- Configuration ---
SERVER_URL = os.environ.get('REMOTE_SERVER_URL', 'https://ssppoo.onrender.com')
ACCESS_PASSWORD = os.environ.get('REMOTE_ACCESS_PASSWORD', 'change_this_password_too') # MUST MATCH SERVER

# --- Core Optimization Settings ---
# !! IMPORTANT !! Set SEND_BINARY_DATA to True ONLY if you updated server/controller JS
# to handle the 'screen_data_bytes' event and raw JPEG binary data.
SEND_BINARY_DATA = True # True: Send raw bytes (LOWER LATENCY/BANDWIDTH - RECOMMENDED)
                        # False: Send Base64 (Original method, higher bandwidth/latency)

FPS = 15 # Target frames per second (Adjust based on CPU/Network. 10-20 is often a good range)
JPEG_QUALITY = 60 # JPEG quality (Lower = smaller size, faster encode, less quality. Try 40-75)

# Mouse Smoothing settings (Reduced duration for potentially less perceived lag)
MOUSE_MOVE_DURATION = 0.025 # Time (seconds) for the smoothed move animation (can set to 0 to disable)
MOUSE_MOVE_STEPS = 3       # Number of intermediate steps for smoothing (if duration > 0)

# --- CTypes Constants and Structures ---
# (Constants MOUSEEVENTF_*, KEYEVENTF_*, VK_CODE_MAP, EXTENDED_KEYS remain the same as previous version)
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
VK_CODE_MAP = {
    'Shift': 0x10, 'ShiftLeft': 0xA0, 'ShiftRight': 0xA1, 'Control': 0x11, 'ControlLeft': 0xA2,
    'ControlRight': 0xA3, 'Alt': 0x12, 'AltLeft': 0xA4, 'AltRight': 0xA5, 'Meta': 0x5B,
    'MetaLeft': 0x5B, 'MetaRight': 0x5C, 'CapsLock': 0x14, 'Tab': 0x09, 'Enter': 0x0D,
    'Escape': 0x1B, 'Space': 0x20, ' ': 0x20, 'Backspace': 0x08, 'Delete': 0x2E, 'Insert': 0x2D,
    'Home': 0x24, 'End': 0x23, 'PageUp': 0x21, 'PageDown': 0x22, 'ArrowUp': 0x26, 'ArrowDown': 0x28,
    'ArrowLeft': 0x25, 'ArrowRight': 0x27, 'F1': 0x70, 'F2': 0x71, 'F3': 0x72, 'F4': 0x73,
    'F5': 0x74, 'F6': 0x75, 'F7': 0x76, 'F8': 0x77, 'F9': 0x78, 'F10': 0x79, 'F11': 0x7A, 'F12': 0x7B,
    'a': 0x41, 'b': 0x42, 'c': 0x43, 'd': 0x44, 'e': 0x45, 'f': 0x46, 'g': 0x47, 'h': 0x48,
    'i': 0x49, 'j': 0x4A, 'k': 0x4B, 'l': 0x4C, 'm': 0x4D, 'n': 0x4E, 'o': 0x4F, 'p': 0x50,
    'q': 0x51, 'r': 0x52, 's': 0x53, 't': 0x54, 'u': 0x55, 'v': 0x56, 'w': 0x57, 'x': 0x58,
    'y': 0x59, 'z': 0x5A, '0': 0x30, '1': 0x31, '2': 0x32, '3': 0x33, '4': 0x34, '5': 0x35,
    '6': 0x36, '7': 0x37, '8': 0x38, '9': 0x39, '`': 0xC0, '-': 0xBD, '=': 0xBB, '[': 0xDB,
    ']': 0xDD, '\\': 0xDC, ';': 0xBA, "'": 0xDE, ',': 0xBC, '.': 0xBE, '/': 0xBF,
}

# Extended key flag needed for certain keys
EXTENDED_KEYS = {
    0xA3, 0xA5, 0x2E, 0x2D, 0x24, 0x23, 0x21, 0x22, 0x26, 0x28, 0x25, 0x27,
}

user32 = ctypes.windll.user32
# Get screen dimensions using ctypes (generally reliable on Windows)
try:
    screen_width = user32.GetSystemMetrics(0) # SM_CXSCREEN
    screen_height = user32.GetSystemMetrics(1) # SM_CYSCREEN
    if screen_width <= 0 or screen_height <= 0:
        raise ValueError("ctypes returned invalid screen dimensions")
except Exception as e:
    print(f"FATAL: Could not get screen dimensions using ctypes: {e}. Exiting.")
    sys.exit(1)


# --- Global Variables ---
sio = socketio.Client(logger=False, engineio_logger=False, reconnection_attempts=5, reconnection_delay=3)
stop_event = threading.Event()
capture_thread = None
is_connected_and_registered = False # Combined flag for clarity
monitor_dimensions = {"width": screen_width, "height": screen_height}
last_mouse_pos = {'x': 0, 'y': 0} # Track last known mouse position for smooth move

# --- Input Simulation Functions (Optimized) ---

def get_vk_code(key_name_or_code):
    """ Tries to map browser key/code names to Windows VK codes. """
    if not key_name_or_code: return None
    key_lower = key_name_or_code.lower()

    if key_name_or_code in VK_CODE_MAP: return VK_CODE_MAP[key_name_or_code]
    if key_lower in VK_CODE_MAP: return VK_CODE_MAP[key_lower]
    if key_name_or_code.startswith('Key') and len(key_name_or_code) == 4:
        char = key_name_or_code[3:].lower()
        if char in VK_CODE_MAP: return VK_CODE_MAP[char]
    if key_name_or_code.startswith('Digit') and len(key_name_or_code) == 6:
        char = key_name_or_code[5:]
        if char in VK_CODE_MAP: return VK_CODE_MAP[char]

    # print(f"Warning: Unmapped key/code: {key_name_or_code}") # Uncomment for debug
    return None


def press_key(vk_code):
    """ Sends a key down event using keybd_event. """
    if vk_code is None: return
    flags = KEYEVENTF_KEYDOWN | (KEYEVENTF_EXTENDEDKEY if vk_code in EXTENDED_KEYS else 0)
    user32.keybd_event(vk_code, 0, flags, 0)

def release_key(vk_code):
    """ Sends a key up event using keybd_event. """
    if vk_code is None: return
    flags = KEYEVENTF_KEYUP | (KEYEVENTF_EXTENDEDKEY if vk_code in EXTENDED_KEYS else 0)
    user32.keybd_event(vk_code, 0, flags, 0)


def mouse_move_to(x, y, smooth=True):
    """ Moves the mouse cursor to absolute coordinates (x, y). """
    global last_mouse_pos
    target_x = max(0, min(int(x), screen_width - 1))
    target_y = max(0, min(int(y), screen_height - 1))

    current_x, current_y = last_mouse_pos['x'], last_mouse_pos['y']
    if target_x == current_x and target_y == current_y:
        return # Already there

    # Use instant move if smoothing disabled or duration is negligible
    if not smooth or MOUSE_MOVE_DURATION <= 0.001:
        user32.SetCursorPos(target_x, target_y)
    else:
        start_time = time.monotonic()
        effective_steps = max(1, MOUSE_MOVE_STEPS)
        step_interval = MOUSE_MOVE_DURATION / effective_steps

        for i in range(1, effective_steps + 1):
            progress = min(i / effective_steps, 1.0)
            # Linear interpolation (could use easing if desired)
            interp_x = int(current_x + (target_x - current_x) * progress)
            interp_y = int(current_y + (target_y - current_y) * progress)
            user32.SetCursorPos(interp_x, interp_y)

            # Precise sleep until next step time
            next_step_time = start_time + (i * step_interval)
            sleep_needed = next_step_time - time.monotonic()
            if sleep_needed > 0.001: # Avoid tiny sleeps
                time.sleep(sleep_needed)

        # Ensure final position is exact
        user32.SetCursorPos(target_x, target_y)

    last_mouse_pos = {'x': target_x, 'y': target_y}


def mouse_click(button='left'):
    """ Performs a mouse click using mouse_event. """
    if button == 'left': down_flag, up_flag = MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP
    elif button == 'right': down_flag, up_flag = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
    elif button == 'middle': down_flag, up_flag = MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP
    else: return # Unsupported

    user32.mouse_event(down_flag, 0, 0, 0, 0)
    time.sleep(0.01) # Small delay can be important
    user32.mouse_event(up_flag, 0, 0, 0, 0)

def mouse_scroll(dx=0, dy=0):
    """ Performs mouse wheel scroll using mouse_event. """
    wheel_delta_unit = 120
    if dy != 0:
        user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, -int(dy * wheel_delta_unit), 0)
        time.sleep(0.005) # Prevent potential scroll loss
    if dx != 0:
        user32.mouse_event(MOUSEEVENTF_HWHEEL, 0, 0, int(dx * wheel_delta_unit), 0)
        time.sleep(0.005)


# --- Screen Capture Thread (OPTIMIZED) ---
def capture_and_send_screen():
    """Captures the screen and sends it efficiently to the server."""
    global is_connected_and_registered, monitor_dimensions
    frame_interval = 1.0 / FPS # Target time per frame

    monitor_area = {"top": 0, "left": 0, "width": monitor_dimensions["width"], "height": monitor_dimensions["height"]}
    print(f"[Capture Thread] Starting. Area: {monitor_area}, Target FPS: {FPS}, Quality: {JPEG_QUALITY}, Binary: {SEND_BINARY_DATA}")

    try:
        with mss.mss() as sct_instance:
            while not stop_event.is_set():
                if not is_connected_and_registered or not sio.connected:
                    time.sleep(0.2) # Wait if not ready
                    continue

                frame_start_time = time.monotonic()

                # --- Capture ---
                try:
                    img = sct_instance.grab(monitor_area)
                    capture_time = time.monotonic()
                except mss.ScreenShotError as ex:
                    print(f"[Capture Thread] Screen capture error: {ex}. Retrying...", file=sys.stderr)
                    time.sleep(1)
                    continue

                # --- Convert and Encode ---
                try:
                    # Re-use buffer for potential minor efficiency gain
                    buffer = io.BytesIO()
                    # Note: Image.frombytes is efficient, direct mss->jpeg might exist but adds complexity
                    pil_img = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")
                    pil_img.save(buffer, format='JPEG', quality=JPEG_QUALITY)
                    jpeg_data = buffer.getvalue()
                    encode_time = time.monotonic()
                except Exception as e:
                    print(f"[Capture Thread] Error during Image processing/encoding: {e}", file=sys.stderr)
                    traceback.print_exc(file=sys.stderr)
                    time.sleep(0.5)
                    continue

                # --- Send Data ---
                send_start_time = time.monotonic()
                if is_connected_and_registered and sio.connected:
                    try:
                        if SEND_BINARY_DATA:
                            sio.emit('screen_data_bytes', jpeg_data)
                        else:
                            img_base64 = base64.b64encode(jpeg_data).decode('utf-8')
                            sio.emit('screen_data', {'image': img_base64})
                        send_end_time = time.monotonic()
                    except socketio.exceptions.BadNamespaceError:
                        print("[Capture Thread] SocketIO BadNamespaceError during send. Assuming disconnected.", file=sys.stderr)
                        is_connected_and_registered = False # Trigger reconnect logic
                        time.sleep(1)
                        continue # Skip sleep calculation for this frame
                    except Exception as e:
                        print(f"[Capture Thread] Error sending screen data: {e}", file=sys.stderr)
                        if not sio.connected:
                            is_connected_and_registered = False
                        time.sleep(0.5)
                        continue # Skip sleep calculation

                # --- Frame Rate Control ---
                frame_end_time = time.monotonic()
                processing_time = frame_end_time - frame_start_time
                sleep_duration = frame_interval - processing_time

                # Optional: Print detailed timing for debugging lag
                # cap_dur = capture_time - frame_start_time
                # enc_dur = encode_time - capture_time
                # send_dur = send_end_time - send_start_time
                # print(f"[Timing] Total: {processing_time:.4f}s (Cap: {cap_dur:.4f}, Enc: {enc_dur:.4f}, Send: {send_dur:.4f}), Sleep: {max(0, sleep_duration):.4f}")

                if sleep_duration > 0.001: # Only sleep if meaningful
                    time.sleep(sleep_duration)
                elif sleep_duration < -0.01: # Warn if consistently falling behind
                     print(f"[Capture Thread] Warning: Frame processing took {abs(sleep_duration):.3f}s longer than interval.", file=sys.stderr)


            # End of while loop
    except Exception as e:
        print(f"[Capture Thread] FATAL error during setup or loop: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        stop_event.set() # Ensure main loop exits

    print("[Capture Thread] Stopped.")


# --- SocketIO Event Handlers ---
@sio.event
def connect():
    global is_connected_and_registered, last_mouse_pos
    is_connected_and_registered = False # Reset flag on new connection
    print(f"[SocketIO] Connection established (sid: {sio.sid}). Registering...")
    # Get current mouse position on connect
    try:
        point = ctypes.wintypes.POINT()
        if user32.GetCursorPos(ctypes.byref(point)):
            last_mouse_pos = {'x': point.x, 'y': point.y}
        else: last_mouse_pos = {'x': screen_width // 2, 'y': screen_height // 2}
    except Exception: last_mouse_pos = {'x': screen_width // 2, 'y': screen_height // 2}

    try:
        sio.emit('register_client', {'token': ACCESS_PASSWORD})
    except Exception as e:
        print(f"[SocketIO] Error emitting registration: {e}", file=sys.stderr)
        if sio.connected: sio.disconnect()

@sio.event
def connect_error(data):
    global is_connected_and_registered
    print(f"[SocketIO] Connection failed: {data}", file=sys.stderr)
    is_connected_and_registered = False

@sio.event
def disconnect():
    global is_connected_and_registered
    print("[SocketIO] Disconnected from server.")
    is_connected_and_registered = False
    # Signal capture thread to stop IF we are not automatically reconnecting
    if not sio.reconnecting:
         print("[SocketIO] Stopping capture thread due to disconnect.")
         stop_event.set()

@sio.on('registration_success')
def on_registration_success():
    global capture_thread, is_connected_and_registered
    print("[SocketIO] Client registration successful.")
    is_connected_and_registered = True # Set flag only after successful registration
    if capture_thread is None or not capture_thread.is_alive():
        print("[SocketIO] Starting screen capture thread...")
        stop_event.clear() # Ensure stop flag is clear before starting
        try:
            capture_thread = threading.Thread(target=capture_and_send_screen, args=(), daemon=True)
            capture_thread.start()
        except Exception as e:
             print(f"[SocketIO] Failed to start capture thread: {e}", file=sys.stderr)
             traceback.print_exc(file=sys.stderr)
             stop_event.set()
             is_connected_and_registered = False
             if sio.connected: sio.disconnect()
    else:
        print("[SocketIO] Capture thread already running.") # Should ideally not happen often

@sio.on('registration_fail')
def on_registration_fail(data):
    global is_connected_and_registered
    print(f"[SocketIO] Client registration failed: {data.get('message', 'No reason given')}", file=sys.stderr)
    is_connected_and_registered = False
    if sio.connected: sio.disconnect()

# --- Command Handler (Optimized) ---
@sio.on('command')
def handle_command(data):
    if not is_connected_and_registered: return # Ignore commands if not ready

    action = data.get('action')
    # print(f"Rcv cmd: {action}", data) # Uncomment for heavy debugging

    try:
        if action == 'move':
            x, y = data.get('x'), data.get('y')
            if x is not None and y is not None: mouse_move_to(x, y, smooth=True)
        elif action == 'click':
            x, y = data.get('x'), data.get('y')
            if x is not None and y is not None: mouse_move_to(x, y, smooth=False) # Instant move
            mouse_click(data.get('button', 'left'))
        elif action == 'keydown':
            vk_code = get_vk_code(data.get('code', data.get('key')))
            if vk_code: press_key(vk_code)
        elif action == 'keyup':
            vk_code = get_vk_code(data.get('code', data.get('key')))
            if vk_code: release_key(vk_code)
        elif action == 'scroll':
            dx, dy = data.get('dx', 0), data.get('dy', 0)
            if dx != 0 or dy != 0: mouse_scroll(dx=dx, dy=dy)
        # else: print(f"Unknown command action: {action}") # Reduce noise
    except Exception as e:
        print(f"Error executing command {data}: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)


# --- Main Execution ---
def main():
    global capture_thread, is_connected_and_registered
    print("--- Remote Control Client (Optimized V2) ---")
    print(f"Server URL: {SERVER_URL}")
    print(f"Screen: {screen_width}x{screen_height} | Target FPS: {FPS} | JPEG Quality: {JPEG_QUALITY}")
    print(f"Binary Mode: {SEND_BINARY_DATA} {'(Requires Server/JS Update!)' if SEND_BINARY_DATA else '(Using Base64)'}")
    print(f"Password Used: {'Yes' if ACCESS_PASSWORD else 'No'}")
    print("--------------------------------------------")

    while not stop_event.is_set():
        is_connected_and_registered = False # Ensure state is reset before connect attempt
        connect_attempt_time = time.monotonic()

        try:
            print(f"[{time.strftime('%H:%M:%S')}] Attempting connection to {SERVER_URL}...")
            sio.connect(SERVER_URL,
                        transports=['websocket'], # Prioritize websockets
                        wait_timeout=10)
            # Blocks here until disconnected
            print(f"[{time.strftime('%H:%M:%S')}] Connection active, waiting for events...")
            sio.wait()
            # Reaches here when sio.disconnect() is called or connection drops
            print(f"[{time.strftime('%H:%M:%S')}] sio.wait() finished (disconnected).")

        except socketio.exceptions.ConnectionError as e:
            print(f"[{time.strftime('%H:%M:%S')}] Connection Error: {e}. Retrying soon...", file=sys.stderr)
            # SocketIO handles background retries based on its settings.
            # We add a delay here before the *next manual* attempt in the loop.
            time.sleep(sio.reconnection_delay)
        except Exception as e:
             print(f"[{time.strftime('%H:%M:%S')}] Unexpected error in connection loop: {e}", file=sys.stderr)
             traceback.print_exc(file=sys.stderr)
             time.sleep(sio.reconnection_delay) # Wait before next manual attempt

        # --- Post-Disconnect / Error Handling ---
        is_connected_and_registered = False # Ensure flag is false after disconnect/error

        # Check if SocketIO is still attempting to reconnect internally
        if sio.reconnecting:
            print(f"[{time.strftime('%H:%M:%S')}] SocketIO attempting background reconnection...")
            while sio.reconnecting and not stop_event.is_set():
                 time.sleep(0.5)
            if sio.connected:
                 print(f"[{time.strftime('%H:%M:%S')}] Background reconnection successful!")
                 # Need to re-register after background reconnect
                 continue # Go to top of loop to attempt registration etc.
            else:
                 print(f"[{time.strftime('%H:%M:%S')}] Background reconnection failed.")

        # Ensure capture thread is stopped if not connected and not reconnecting
        if capture_thread and capture_thread.is_alive():
             print(f"[{time.strftime('%H:%M:%S')}] Ensuring capture thread is stopped...")
             stop_event.set()
             capture_thread.join(timeout=2.0)
             if capture_thread.is_alive():
                 print(f"[{time.strftime('%H:%M:%S')}] Warning: Capture thread did not stop gracefully.", file=sys.stderr)
             capture_thread = None
             stop_event.clear() # Clear for the next connection attempt

        # Wait before the next manual connection attempt in the loop
        if not stop_event.is_set():
            wait_time = max(0, sio.reconnection_delay - (time.monotonic() - connect_attempt_time))
            print(f"[{time.strftime('%H:%M:%S')}] Waiting {wait_time:.1f}s before next connection attempt...")
            time.sleep(wait_time)


    # End of main while loop (stop_event is set)
    print(f"[{time.strftime('%H:%M:%S')}] Stop event detected, exiting main loop.")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n[{time.strftime('%H:%M:%S')}] Ctrl+C detected. Initiating shutdown...")
        stop_event.set()
    finally:
        print(f"[{time.strftime('%H:%M:%S')}] --- Final Client Cleanup ---")
        stop_event.set() # Ensure stop is signaled

        if sio and sio.connected:
            print(f"[{time.strftime('%H:%M:%S')}] Disconnecting SocketIO...")
            try: sio.disconnect()
            except Exception as e: print(f"Error during final disconnect: {e}", file=sys.stderr)

        if capture_thread and capture_thread.is_alive():
             print(f"[{time.strftime('%H:%M:%S')}] Waiting for capture thread final exit...")
             capture_thread.join(timeout=3.0)
             if capture_thread.is_alive():
                  print(f"[{time.strftime('%H:%M:%S')}] Warning: Capture thread did not exit cleanly.", file=sys.stderr)

        print(f"[{time.strftime('%H:%M:%S')}] Client shutdown complete.")
        print("--------------------------------")
        # Use os._exit for a more forceful exit if threads are stuck
        # sys.exit(0)
        os._exit(0)
