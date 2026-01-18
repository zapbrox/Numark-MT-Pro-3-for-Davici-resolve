"""
Simple MIDI capture helper for Numark MT Pro 3
- Lists available MIDI input ports
- Listens for incoming MIDI messages in background
- Lets you interactively inspect and save messages into mappings.csv

Dependencies: mido + python-rtmidi
Run: python -m pip install -r requirements.txt
Usage: python capture_midi.py

Commands (in the script):
  h             show help
  l             list captured messages
  s <i> <name> <keystroke>   save message index i into mappings.csv with given control name and keystroke
  q             quit

Example save: s 3 "Play/Pause" Space

"""
import mido
import threading
import queue
import time
import csv
import os
import sys

CAPTURE_FILE = 'mappings.csv'


def midi_listener(port_name, q, stop_event):
    try:
        with mido.open_input(port_name) as inport:
            print(f"Listening on MIDI input: {port_name}")
            while not stop_event.is_set():
                for msg in inport.iter_pending():
                    q.put((time.time(), msg))
                time.sleep(0.01)
    except Exception as e:
        print('Listener error:', e)
        stop_event.set()


def ensure_csv_header(path):
    header = ['Control','MIDI Type','Channel','Number (Note/CC)','Observed Values','Desired Keystroke/Action','Notes']
    if not os.path.exists(path):
        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(header)


def append_mapping(path, control, midi_type, channel, number, observed, desired, notes=''):
    ensure_csv_header(path)
    with open(path, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([control, midi_type, channel, number, observed, desired, notes])


def format_msg(msg):
    # produce a readable one-line representation
    d = msg.dict()
    # keep only common keys
    keys = []
    if 'type' in d:
        keys.append(f"type={d['type']}")
    if 'channel' in d:
        keys.append(f"chan={d['channel']}")
    if 'note' in d:
        keys.append(f"note={d['note']}")
    if 'control' in d:
        keys.append(f"cc={d['control']}")
    if 'value' in d:
        keys.append(f"val={d['value']}")
    if 'velocity' in d:
        keys.append(f"vel={d.get('velocity')}")
    return ' '.join(keys)


def main():
    print('\nNumark MIDI capture helper')
    ports = mido.get_input_names()
    if not ports:
        print('No MIDI input ports found. Connect your Numark and try again.')
        sys.exit(1)

    print('Available MIDI input ports:')
    for i, p in enumerate(ports):
        print(f'  {i}: {p}')

    sel = input('Choose port index (or press Enter for 0): ').strip()
    if sel == '':
        sel = '0'
    try:
        port_index = int(sel)
        port_name = ports[port_index]
    except Exception as e:
        print('Invalid selection, exiting.')
        sys.exit(1)

    q = queue.Queue()
    stop_event = threading.Event()
    t = threading.Thread(target=midi_listener, args=(port_name, q, stop_event), daemon=True)
    t.start()

    captured = []  # list of tuples (timestamp, msg)

    print('\nCommands: h help, l list, s <i> "ControlName" <Keystroke>, q quit')

    try:
        while True:
            # drain queue
            while not q.empty():
                ts, msg = q.get()
                captured.append((ts, msg))
                idx = len(captured) - 1
                print(f'[{idx}] {time.strftime("%H:%M:%S", time.localtime(ts))}  {format_msg(msg)}')

            cmd = input('> ').strip()
            if not cmd:
                continue
            if cmd.lower() in ('h','help'):
                print('h - help')
                print('l - list captured messages')
                print('s <i> "ControlName" <Keystroke> - save message index i to mappings.csv')
                print('   Example: s 3 "Play/Pause" Space')
                print('q - quit')
                continue
            if cmd.lower() == 'l':
                if not captured:
                    print('No messages captured yet.')
                else:
                    for i, (ts, msg) in enumerate(captured):
                        print(f'[{i}] {time.strftime("%H:%M:%S", time.localtime(ts))}  {format_msg(msg)}')
                continue
            if cmd.lower().startswith('s '):
                # simple parser: s <i> "Control Name" <Keystroke>
                parts = cmd.split()
                # better parsing to allow quoted control name
                try:
                    # find first space after 's '
                    rest = cmd[2:].strip()
                    # if quoted control name
                    if rest.startswith('"'):
                        endq = rest.find('"',1)
                        if endq == -1:
                            print('Bad format: missing closing quote for control name')
                            continue
                        ctrl = rest[1:endq]
                        remainder = rest[endq+1:].strip()
                        idx_str, *keyst = remainder.split(None, 1)
                        idx = int(idx_str)
                        desired = keyst[0] if keyst else ''
                    else:
                        # format: s <i> <ControlName> <Keystroke>
                        toks = rest.split(None,2)
                        if len(toks) < 3:
                            print('Bad format. Use: s <index> "Control Name" <Keystroke>')
                            continue
                        idx = int(toks[0])
                        ctrl = toks[1]
                        desired = toks[2]
                except Exception as e:
                    print('Parse error:', e)
                    print('Example: s 3 "Play/Pause" Space')
                    continue

                if idx < 0 or idx >= len(captured):
                    print('Index out of range')
                    continue

                ts, msg = captured[idx]
                md = msg.dict()
                midi_type = md.get('type')
                channel = md.get('channel', '')
                number = ''
                if 'note' in md:
                    number = md.get('note')
                elif 'control' in md:
                    number = md.get('control')
                observed = format_msg(msg)
                append_mapping(CAPTURE_FILE, ctrl, midi_type, channel, number, observed, desired)
                print(f'Saved mapping for index {idx} -> {CAPTURE_FILE}')
                continue

            if cmd.lower() == 'q':
                print('Quitting...')
                break

            print('Unknown command. Type h for help.')

    except (KeyboardInterrupt, EOFError):
        print('\nInterrupted by user')
    finally:
        stop_event.set()
        t.join(timeout=1)
        print('Listener stopped. Goodbye.')


if __name__ == '__main__':
    main()
