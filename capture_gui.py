import tkinter as tk
from tkinter import ttk, messagebox
import threading
import queue
import time
import csv
import os
import mido

CAPTURE_FILE = 'mappings.csv'
SHORTCUTS_FILE = 'shortcuts.csv'


def ensure_csv_header(path):
    header = ['Control', 'MIDI Type', 'Channel', 'Number (Note/CC)', 'Observed Values', 'Desired Keystroke/Action', 'Notes']
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
    d = msg.dict()
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


class MidiListener(threading.Thread):
    def __init__(self, port_name, out_queue, stop_event):
        super().__init__(daemon=True)
        self.port_name = port_name
        self.out_queue = out_queue
        self.stop_event = stop_event

    def run(self):
        try:
            with mido.open_input(self.port_name) as inport:
                while not self.stop_event.is_set():
                    for msg in inport.iter_pending():
                        self.out_queue.put((time.time(), msg))
                    time.sleep(0.01)
        except Exception as e:
            self.out_queue.put(('error', str(e)))


class CaptureGUI:
    def __init__(self, root):
        self.root = root
        root.title('Numark MT Pro 3 → DaVinci Resolve Mapper')

        self.ports = []
        self.listener = None
        self.listener_stop = threading.Event()
        self.msg_queue = queue.Queue()

        self.shortcuts = self.load_shortcuts()
        self.selected_shortcut = None

        # Top frame: ports
        top = ttk.Frame(root, padding=8)
        top.grid(row=0, column=0, sticky='ew')

        ttk.Label(top, text='MIDI Input:').grid(row=0, column=0, sticky='w')
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(top, textvariable=self.port_var, state='readonly', width=60)
        self.port_combo.grid(row=0, column=1, sticky='ew', padx=6)
        self.refresh_btn = ttk.Button(top, text='Refresh', command=self.refresh_ports)
        self.refresh_btn.grid(row=0, column=2)
        self.start_btn = ttk.Button(top, text='Start Listener', command=self.toggle_listener)
        self.start_btn.grid(row=0, column=3, padx=6)

        # Shortcuts list
        listf = ttk.Frame(root, padding=8)
        listf.grid(row=1, column=0, sticky='nsew')
        root.rowconfigure(1, weight=1)
        root.columnconfigure(0, weight=1)

        self.shortcuts_tree = ttk.Treeview(listf, columns=('shortcut', 'midi'), show='headings', selectmode='browse')
        self.shortcuts_tree.heading('shortcut', text='DaVinci Resolve Shortcuts')
        self.shortcuts_tree.heading('midi', text='Mapped MIDI')
        self.shortcuts_tree.column('midi', width=150)
        self.shortcuts_tree.grid(row=0, column=0, sticky='nsew')
        listf.rowconfigure(0, weight=1)
        listf.columnconfigure(0, weight=1)

        for shortcut in self.shortcuts:
            self.shortcuts_tree.insert('', 'end', iid=shortcut, values=(shortcut, ''))

        self.load_existing_mappings()

        self.shortcuts_tree.bind('<<TreeviewSelect>>', self.on_shortcut_select)

        btnf = ttk.Frame(root, padding=8)
        btnf.grid(row=2, column=0, sticky='ew')
        self.map_btn = ttk.Button(btnf, text='Map Selected Shortcut', command=self.start_mapping_thread)
        self.map_btn.grid(row=0, column=0)
        self.save_all_btn = ttk.Button(btnf, text='Save All Mapped', command=self.save_all)
        self.save_all_btn.grid(row=0, column=1, padx=6)
        self.clear_btn = ttk.Button(btnf, text='Clear Mappings', command=self.clear_mappings)
        self.clear_btn.grid(row=0, column=2)

        # Mapping status
        statusf = ttk.Frame(root, padding=8)
        statusf.grid(row=3, column=0, sticky='ew')
        ttk.Label(statusf, text='Last Mapping:').grid(row=0, column=0, sticky='w')
        self.status_label = ttk.Label(statusf, text='None', foreground='blue')
        self.status_label.grid(row=0, column=1, sticky='w')

        # Live monitor
        monf = ttk.Frame(root, padding=8)
        monf.grid(row=4, column=0, sticky='ew')
        ttk.Label(monf, text='Live MIDI Monitor:').grid(row=0, column=0, sticky='w')
        self.mon_text = tk.Text(monf, height=8, state='disabled')
        self.mon_text.grid(row=1, column=0, sticky='ew')

        self.refresh_ports()
        self.root.after(50, self.poll_queue)

    def load_shortcuts(self):
        shortcuts = []
        seen = set()
        if os.path.exists(SHORTCUTS_FILE):
            with open(SHORTCUTS_FILE, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    key = f"{row['Control']} ({row['Shortcut']})"
                    if key not in seen:
                        shortcuts.append(key)
                        seen.add(key)
        return shortcuts

    def load_existing_mappings(self):
        if not os.path.exists(CAPTURE_FILE):
            return
        mappings = {}
        with open(CAPTURE_FILE, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                control = row.get('Control', '')
                midi_type = row.get('MIDI Type', '')
                channel = row.get('Channel', '')
                number = row.get('Number (Note/CC)', '')
                desired = row.get('Desired Keystroke/Action', '')
                if control and desired:
                    key = f"{control} ({desired})"
                    midi_info = f"chan={channel} {midi_type}={number}"
                    mappings[key] = midi_info
        for shortcut in self.shortcuts:
            if shortcut in mappings:
                self.shortcuts_tree.set(shortcut, 'midi', mappings[shortcut])

    def on_shortcut_select(self, event):
        selected = self.shortcuts_tree.selection()
        if selected:
            item = self.shortcuts_tree.item(selected[0])
            self.selected_shortcut = item['values'][0]

    def refresh_ports(self):
        try:
            self.ports = mido.get_input_names()
        except Exception as e:
            messagebox.showerror('Error', f'Could not list MIDI ports: {e}')
            self.ports = []
        self.port_combo['values'] = self.ports
        if self.ports:
            self.port_combo.current(0)

    def toggle_listener(self):
        if self.listener and self.listener.is_alive():
            self.listener_stop.set()
            self.listener.join(timeout=1)
            self.listener = None
            self.start_btn.config(text='Start Listener')
            self.log('Listener stopped')
        else:
            port = self.port_var.get()
            if not port:
                messagebox.showwarning('No port', 'Select a MIDI input first')
                return
            self.listener_stop.clear()
            self.listener = MidiListener(port, self.msg_queue, self.listener_stop)
            self.listener.start()
            self.start_btn.config(text='Stop Listener')
            self.log(f'Listening on {port}')

    def start_mapping_thread(self):
        if not self.selected_shortcut:
            messagebox.showinfo('No shortcut', 'Select a shortcut first')
            return
        if not (self.listener and self.listener.is_alive()):
            messagebox.showwarning('Listener', 'Start the MIDI listener first')
            return
        t = threading.Thread(target=self.mapping_loop, daemon=True)
        t.start()

    def mapping_loop(self):
        # Map the selected shortcut
        control, desired = self.selected_shortcut.split(' (', 1)
        desired = desired.rstrip(')')
        self.log(f"Press the control for '{control}' (Shortcut: {desired})")
        # wait for a message
        msg = None
        while True:
            try:
                item = self.msg_queue.get(timeout=0.1)
            except queue.Empty:
                if self.listener_stop.is_set():
                    return
                continue
            if item[0] == 'error':
                self.log('Listener error: ' + item[1])
                return
            ts, msgobj = item
            # ignore release messages (many controllers send a press and a release)
            mtype = getattr(msgobj, 'type', '')
            if mtype == 'note_on' and getattr(msgobj, 'velocity', None) == 0:
                # skip release message
                continue
            if mtype == 'note_off':
                continue
            if mtype == 'control_change' and getattr(msgobj, 'value', None) == 0:
                continue
            # accept this message
            msg = msgobj
            break
        if msg is None:
            return
        observed = format_msg(msg)
        md = msg.dict()
        midi_type = md.get('type')
        channel = md.get('channel', '')
        number = md.get('note') if 'note' in md else md.get('control', '')
        append_mapping(CAPTURE_FILE, control, midi_type, channel, number, observed, desired)
        midi_info = f"chan={channel} cc={number} val={md.get('value', '')}"
        self.root.after(0, lambda: self.shortcuts_tree.set(self.selected_shortcut, 'midi', midi_info))
        self.root.after(0, lambda: self.status_label.config(text=f"{control} → {desired}"))
        self.log(f"Mapped '{control}' -> {observed}")

    def save_all(self):
        # already saved per mapping; just confirm
        ensure_csv_header(CAPTURE_FILE)
        messagebox.showinfo('Saved', f'Mappings are saved/appended to {CAPTURE_FILE}')

    def clear_mappings(self):
        if messagebox.askyesno('Clear', 'Clear all mappings in CSV?'):
            if os.path.exists(CAPTURE_FILE):
                os.remove(CAPTURE_FILE)
            self.log('Mappings cleared')

    def log(self, text):
        self.mon_text.config(state='normal')
        self.mon_text.insert('end', text + '\n')
        self.mon_text.see('end')
        self.mon_text.config(state='disabled')

    def poll_queue(self):
        # drain queue and show live messages
        while not self.msg_queue.empty():
            item = self.msg_queue.get()
            if item[0] == 'error':
                self.log('Listener error: ' + item[1])
                continue
            ts, msg = item
            self.log(f"{time.strftime('%H:%M:%S', time.localtime(ts))}  {format_msg(msg)}")
        self.root.after(50, self.poll_queue)


def main():
    root = tk.Tk()
    app = CaptureGUI(root)
    root.geometry('900x600')
    root.mainloop()


if __name__ == '__main__':
    main()
