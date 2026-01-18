"""
Listen to MIDI and send corresponding keystrokes (no Bome required).

Reads mappings from mappings.csv (produced by capture_gui.py) and listens on a MIDI input.

Usage:
  python midi_to_key.py            # chooses first available MIDI input
  python midi_to_key.py 1          # choose port index 1 from mido.get_input_names()

CSV format expected (header present):
Control,MIDI Type,Channel,Number (Note/CC),Observed Values,Desired Keystroke/Action,Notes

Notes:
- This script uses mido+python-rtmidi for MIDI and pynput for keyboard control.
- Install requirements: python -m pip install -r requirements.txt && python -m pip install pynput

"""
import csv
import sys
import time
import threading
import math
import argparse
import mido
import json
from pynput.keyboard import Controller, Key

MAPPINGS_CSV = 'mappings.csv'


def load_mappings(path):
    mappings = {}
    try:
        with open(path, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    midi_type = row['MIDI Type']
                    chan = row.get('Channel', '')
                    num = row.get('Number (Note/CC)', '')
                    desired = row.get('Desired Keystroke/Action', '')
                    if not num:
                        continue
                    key = (midi_type.strip(), str(chan).strip(), str(num).strip())
                    mappings[key] = desired.strip()
                except Exception:
                    continue
    except FileNotFoundError:
        print('No mappings.csv found.')
    return mappings


KB = Controller()
DRY_RUN = False
VERBOSE = False

# jog state: (chan, control) -> {dir: -1/1, rate: pulses_per_sec, last_ts, acc}
jog_states = {}
right_count = 0
left_count = 0
jog_lock = threading.Lock()

def jog_worker(stop_event, interval=0.01, max_rate=80.0, timeout=0.35, alpha=0.25, deadzone=0.05, power=1.3):
    """Background worker that sends repeated keypresses according to jog_states.

    Improvements:
    - Uses an exponential moving average (EMA) to smooth noisy speed reports from the encoder.
    - Maps smoothed speed to a pulses-per-second rate using a configurable nonlinear curve (power).
    - Uses an accumulator to emit integer pulses while preserving fractional remainder.
    - Configurable deadzone to ignore tiny values around center.

    Parameters:
    - interval: worker loop sleep; smaller -> more responsive, but more CPU
    - max_rate: maximum pulses (key sends) per second at full encoder deflection
    - timeout: seconds after last message to consider jog stopped and remove state
    - alpha: EMA smoothing factor (0..1). Higher -> more responsive, less smooth.
    - deadzone: normalized threshold (0..1) below which movement is ignored
    - power: exponent applied to |speed| to create a nonlinear response curve
    """
    while not stop_event.is_set():
        now = time.time()
        with jog_lock:
            items = list(jog_states.items())
        print(f"[DEBUG] Worker loop: {len(items)} jog states")
        for (chan, control), st in items:
            last = st.get('last_ts', 0)
            if now - last > timeout:
                # stop and remove stale state
                with jog_lock:
                    if (chan, control) in jog_states:
                        del jog_states[(chan, control)]
                continue

            # simple jog handling: accumulate 20 commands per direction, send one keystroke
            global right_count, left_count
            raw = st.get('raw', 0.0)
            if chan in (1, 2):
                if raw > 1 and raw <= 64:  # right
                    right_count += 1
                    print(f"[DEBUG] Right count: {right_count}")
                    if right_count >= 15:
                        key_to_send = st.get('pos_token', 'Right')
                        print(f"[JOG] Sending {key_to_send} after 15 right commands")
                        if DRY_RUN:
                            print(f"[DRY-RUN] jog -> {key_to_send}")
                        else:
                            parse_and_send(key_to_send)
                        right_count = 0
                elif raw >= 66 and raw < 127:  # left
                    left_count += 1
                    print(f"[DEBUG] Left count: {left_count}")
                    if left_count >= 15:
                        key_to_send = st.get('neg_token', 'Left')
                        print(f"[JOG] Sending {key_to_send} after 15 left commands")
                        if DRY_RUN:
                            print(f"[DRY-RUN] jog -> {key_to_send}")
                        else:
                            parse_and_send(key_to_send)
                        left_count = 0

            with jog_lock:
                jog_states[(chan, control)] = st

        time.sleep(interval)


def parse_and_send(desired):
    # desired examples: 'Space', 'Ctrl+B', 'PageDown', 'Left'
    if not desired:
        return
    parts = desired.replace('ctrl', 'Ctrl').split('+')
    mods = []
    keytok = None
    if len(parts) == 1:
        keytok = parts[0]
    else:
        *mods, keytok = parts

    # map token to pynput Key or char
    def map_token(t):
        t = t.strip()
        if not t:
            return None
        tlow = t.lower()
        if tlow == 'space':
            return Key.space
        if tlow in ('left','arrowleft'):
            return Key.left
        if tlow in ('right','arrowright'):
            return Key.right
        if tlow in ('up','arrowup'):
            return Key.up
        if tlow in ('down','arrowdown'):
            return Key.down
        if tlow == 'pagedown':
            return Key.page_down
        if tlow == 'pageup':
            return Key.page_up
        if tlow in ('enter','return'):
            return Key.enter
        if tlow == 'tab':
            return Key.tab
        # single character
        if len(t) == 1:
            return t
        # fallback: return the string (pynput accepts strings for press)
        return t

    mod_keys = []
    for m in mods:
        mm = m.strip().lower()
        if mm in ('ctrl','control'):
            mod_keys.append(Key.ctrl)
        elif mm in ('shift',):
            mod_keys.append(Key.shift)
        elif mm in ('alt','menu'):
            mod_keys.append(Key.alt)

    main_key = map_token(keytok)

    try:
        if DRY_RUN:
            print(f"[DRY-RUN] Would send: modifiers={mod_keys} key={main_key}")
            return
        # press modifiers
        for mk in mod_keys:
            KB.press(mk)
        if main_key is not None:
            KB.press(main_key)
            KB.release(main_key)
        # release modifiers
        for mk in reversed(mod_keys):
            KB.release(mk)
    except Exception as e:
        print('Failed to send key:', desired, e)


def run_listener(port_name, mappings):
    print('Listening on', port_name)
    prev_cc = {}  # (chan, control) -> last value
    with mido.open_input(port_name) as inport:
        for msg in inport:
            try:
                mtype = msg.type
            except Exception:
                continue
            if mtype == 'note_on' and getattr(msg, 'velocity', 0) == 0:
                continue
            if mtype == 'note_off':
                continue

            chan = getattr(msg, 'channel', '')
            if mtype == 'note_on':
                number = getattr(msg, 'note', '')
                key = ('note_on', str(chan), str(number))
                desired = mappings.get(key) or mappings.get(('note_on', '', str(number))) or mappings.get(('note_on','', ''))
                if desired:
                    print('->', desired)
                    parse_and_send(desired)
            elif mtype == 'control_change':
                control = getattr(msg, 'control', '')
                value = getattr(msg, 'value', 0)
                key_with_chan = ('control_change', str(chan), str(control))
                key_no_chan = ('control_change', '', str(control))
                desired = mappings.get(key_with_chan) or mappings.get(key_no_chan)
                # handle jog-like CCs via delta
                prev = prev_cc.get((chan, control), None)
                prev_cc[(chan, control)] = value
                print(f"[DEBUG] MIDI: chan={chan} control={control} value={value}")
                # Special hardcode for MT Pro 3 jog: chan=1 and chan=2 any control
                if chan in (1, 2):
                    if chan == 1:
                        pos_token = 'Right'
                        neg_token = 'Left'
                    elif chan == 2:
                        pos_token = 'Ctrl+Right'  # zoom in or shuttle faster
                        neg_token = 'Ctrl+Left'  # zoom out or shuttle slower
                    print(f"[DEBUG] Jog received: chan={chan} control={control} value={value}")
                    with jog_lock:
                        jog_states[(chan, control)] = {
                            'raw': value,
                            'last_ts': time.time(),
                            'pos_token': pos_token,
                            'neg_token': neg_token,
                        }
                    print(f"[DEBUG] Jog state set for ({chan}, {control})")
                elif desired:
                    # if desired contains 'Jog' treat incoming CC as speed/position and use jog_worker
                    if 'jog' in desired.lower():
                            # Special handling for Numark MT Pro 3 jog wheels
                            norm = 0.0
                            if chan == 1 and control == 17:
                                # Left jog wheel: chan=1 cc=17
                                if 1 <= value <= 64:
                                    # Right rotation: value 1 (slow) to 64 (fast)
                                    speed = (value - 1) / 63.0
                                    norm = speed  # positive for right
                                elif 66 <= value <= 127:
                                    # Left rotation: value 127 (slow) to 66 (fast)
                                    speed = (127 - value) / 61.0
                                    norm = -speed  # negative for left
                            elif chan == 2 and control == 17:
                                # Right jog wheel: chan=2 cc=17 (assuming same encoding)
                                if 1 <= value <= 64:
                                    speed = (value - 1) / 63.0
                                    norm = speed
                                elif 66 <= value <= 127:
                                    speed = (127 - value) / 61.0
                                    norm = -speed
                            else:
                                # Fallback for other jog controls: assume absolute around 64
                                centered = int(value) - 64
                                norm = max(-1.0, min(1.0, centered / 64.0))
                            # parse optional desired tokens after a colon, e.g. "Jog:Right/Left" -> positive/negative
                            pos_token = 'Right'
                            neg_token = 'Left'
                            try:
                                if ':' in desired:
                                    tail = desired.split(':', 1)[1]
                                    parts = [p.strip() for p in tail.split('/') if p.strip()]
                                    if len(parts) >= 1:
                                        pos_token = parts[0]
                                    if len(parts) >= 2:
                                        neg_token = parts[1]
                            except Exception:
                                pass
                            # store raw value; smoothing and rate mapping happen in jog_worker
                            with jog_lock:
                                prev = jog_states.get((chan, control), {})
                                jog_states[(chan, control)] = {
                                    'raw': value,  # store raw MIDI value
                                    'ema': prev.get('ema', 0.0),
                                    'last_ts': time.time(),
                                    'acc': prev.get('acc', 0.0),
                                    'pos_token': pos_token,
                                    'neg_token': neg_token,
                                }
                    elif 'jog' not in desired.lower() and desired.lower() in ('left','right','j','l'):
                        # older fallback: treat CC as delta-like
                        if prev is None:
                            continue
                        delta = value - prev
                        if delta == 0:
                            continue
                        # use magnitude to repeat
                        steps = max(1, abs(delta) // 8)
                        send_key = 'Right' if delta > 0 else 'Left'
                        for _ in range(steps):
                            parse_and_send(send_key)
                            time.sleep(0.005)
                    else:
                        # for CC mapped to a single key, send when value crosses threshold
                        # e.g., if value > 64 send desired once
                        if value > 64:
                            parse_and_send(desired)
                else:
                    # no mapping, continue
                    pass


def choose_port(index_arg=None):
    ports = mido.get_input_names()
    if not ports:
        print('No MIDI input ports found')
        sys.exit(1)
    if index_arg is None:
        print('Available MIDI inputs:')
        for i, p in enumerate(ports):
            print(i, p)
        print('Using first port by default:', ports[0])
        return ports[0]
    else:
        try:
            idx = int(index_arg)
            return ports[idx]
        except Exception:
            # try to match by name
            for p in ports:
                if index_arg.lower() in p.lower():
                    return p
            print('Could not find port', index_arg)
            sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description='MIDI to key daemon with jog handling')
    parser.add_argument('port', nargs='?', help='MIDI input port index or substring')
    parser.add_argument('--mappings', '-m', default=MAPPINGS_CSV, help='Path to mappings CSV')
    parser.add_argument('--max-rate', type=float, default=0.5, help='Max pulses/sec for jog at full deflection')
    parser.add_argument('--interval', type=float, default=0.01, help='Jog worker loop interval in seconds')
    parser.add_argument('--timeout', type=float, default=0.35, help='Jog state timeout in seconds')
    parser.add_argument('--alpha', type=float, default=0.25, help='EMA smoothing factor (0..1)')
    parser.add_argument('--deadzone', type=float, default=0.1, help='Normalized deadzone (0..1)')
    parser.add_argument('--power', type=float, default=1.3, help='Nonlinear mapping power for speed curve')
    parser.add_argument('--dry-run', action='store_true', help='Do not send actual keypresses; print actions instead')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose logging for jog/raw/ema values')
    args = parser.parse_args()

    global DRY_RUN, VERBOSE
    DRY_RUN = bool(args.dry_run)
    VERBOSE = bool(args.verbose)

    mappings = load_mappings(args.mappings)
    if not mappings:
        print('No mappings loaded. Fill mappings.csv using capture_gui.py first.')
        # continue anyway to allow testing
    port = choose_port(args.port)
    # start jog worker with configured parameters
    stop_event = threading.Event()
    jw = threading.Thread(target=jog_worker, args=(stop_event, args.interval, args.max_rate, args.timeout, args.alpha, args.deadzone, args.power), daemon=True)
    jw.start()
    try:
        run_listener(port, mappings)
    except KeyboardInterrupt:
        print('\nStopped by user')
    finally:
        stop_event.set()


if __name__ == '__main__':
    main()
