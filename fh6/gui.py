"""Tk desktop dashboard for the complete Mad Mike pipeline."""
import json
import os
import queue
import tkinter as tk
from tkinter import ttk, messagebox

from forza_cycle import BASE, PurchaseLedger
from .controller import Controller, set_dpi_awareness
from .pipeline import STAGES
from .session import Session
from .budget import plan_from_sp, POINTS_PER_CAR

CONFIG = BASE/'runs'/'settings.json'
MODES = ('Full pipeline', 'Buy only', 'Mastery only', 'Recognition only')


class App:
    def __init__(self, root, hotkeys=True):
        self.root = root
        self.events = queue.Queue()
        self.controller = Controller(lambda kind, value: self.events.put((kind, value)))
        self.hotkey_ids = []
        self.error_image = None
        self.closing = False
        root.title('HORIZON JAPAN // MISSION CONTROL')
        root.geometry('980x900')
        root.minsize(920, 880)
        root.configure(bg='#061216')
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', font=('Bahnschrift', 10), background='#061216', foreground='#f4fbfb')
        style.configure('TFrame', background='#061216')
        style.configure('Card.TFrame', background='#0b1e24')
        style.configure('TLabel', background='#061216', foreground='#f4fbfb')
        style.configure('Muted.TLabel', foreground='#83a8b0')
        style.configure('Title.TLabel', font=('Bahnschrift', 24, 'bold'))
        style.configure('Metric.TLabel', font=('Bahnschrift', 22, 'bold'), background='#0b1e24')
        style.configure('Card.TLabel', background='#0b1e24', foreground='#83a8b0')
        style.configure('TButton', padding=(14, 9), background='#102830', foreground='#f4fbfb', borderwidth=1)
        style.map('TButton', background=[('active', '#17434c')])
        style.configure('Start.TButton', background='#00e5d4', foreground='#061216', font=('Bahnschrift', 11, 'bold'))
        style.map('Start.TButton', background=[('active', '#5fffee'), ('disabled', '#315247')])
        style.configure('Stop.TButton', background='#ff2f87', foreground='#ffffff')
        style.configure('TEntry', fieldbackground='#102830', foreground='#ffffff', insertcolor='#ffffff')
        style.configure('TCombobox', fieldbackground='#102830', foreground='#ffffff', arrowcolor='#83a8b0')
        style.map('TCombobox', fieldbackground=[('readonly', '#102830')], foreground=[('readonly', '#ffffff')])
        style.configure('Treeview', background='#0b1e24', fieldbackground='#0b1e24', foreground='#f4fbfb', rowheight=29, borderwidth=0)
        style.configure('Treeview.Heading', background='#102830', foreground='#83a8b0', padding=6)
        style.map('Treeview', background=[('selected', '#17434c')])
        style.configure('TProgressbar', troughcolor='#102830', background='#00e5d4')
        outer = ttk.Frame(root, padding=24)
        outer.pack(fill='both', expand=True)
        ttk.Label(outer, text='HORIZON JAPAN // MISSION CONTROL', style='Title.TLabel').pack(anchor='w')
        ttk.Label(outer, text='Home / festival → Journal → Buy → Paints → Choose Car → Mastery → Repeat',
                  style='Muted.TLabel').pack(anchor='w', pady=(4, 18))

        settings = dict(mode=MODES[0], limit=1, monitor=1, timeout=30, title='Forza Horizon 6')
        saved = {}
        try:
            if CONFIG.exists():
                settings.update(json.loads(CONFIG.read_text(encoding='utf-8')))
            saved = Session().data
            if saved and saved.get('phase') != 'complete':
                settings.update(mode=saved['mode'], limit=saved['limit'])
        except (OSError, ValueError, KeyError) as exc:
            self.events.put(('log', f'Could not read saved settings: {exc}'))
        self.mode = tk.StringVar(value=settings['mode'])
        self.limit = tk.StringVar(value=str(settings['limit']))
        self.saved_session = saved
        self._manual_limit = str(settings['limit'])
        self._using_sp = False
        points = settings.get('skill_points', '')
        if saved.get('skill_points') is not None:
            points = saved['skill_points']
            if saved.get('phase') == 'complete':
                points = '' if saved.get('end_reason') == 'ended' else max(0, points - saved.get('rewards', 0) * POINTS_PER_CAR)
        self.current_sp = tk.StringVar(value=str(points))
        self.plan_text = tk.StringVar()
        self.monitor = tk.StringVar(value=str(settings['monitor']))
        self.timeout = tk.StringVar(value=str(settings['timeout']))
        self.title = tk.StringVar(value=settings['title'])
        controls = ttk.Frame(outer)
        controls.pack(fill='x')
        self.inputs = []
        for col, (label, variable, width, values) in enumerate([
                ('Run mode', self.mode, 21, MODES), ('Current SP (optional)', self.current_sp, 13, None),
                ('Cycle limit', self.limit, 8, None),
                ('Monitor', self.monitor, 6, None), ('Timeout (sec)', self.timeout, 10, None)]):
            cell = ttk.Frame(controls)
            cell.grid(row=0, column=col, sticky='nw', padx=(0, 18))
            ttk.Label(cell, text=label, style='Muted.TLabel').pack(anchor='w', pady=(0, 5))
            field = ttk.Combobox(cell, textvariable=variable, values=values, width=width, state='readonly') if values else \
                ttk.Entry(cell, textvariable=variable, width=width)
            field.pack()
            self.inputs.append(field)
            if variable is self.current_sp:
                self.sp_entry = field
            elif variable is self.limit:
                self.limit_entry = field
        ttk.Label(outer, textvariable=self.plan_text, wraplength=915,
                  style='Muted.TLabel').pack(anchor='w', fill='x', pady=(9, 12))

        actions = ttk.Frame(outer)
        actions.pack(fill='x')
        self.start_button = ttk.Button(actions, text='Start / Resume   F6', style='Start.TButton', command=lambda: self.start(5))
        self.start_button.pack(side='left')
        ttk.Button(actions, text='Stop   F7', style='Stop.TButton', command=self.stop).pack(side='left', padx=10)
        self.end_button = ttk.Button(actions, text='End session…', command=self.end_session)
        self.end_button.pack(side='right')
        self.status = tk.StringVar(value='Ready. Open the home/festival menu and press F6 in the game.')
        ttk.Label(outer, textvariable=self.status, wraplength=915).pack(anchor='w', fill='x', pady=(13, 12))

        metrics = ttk.Frame(outer)
        metrics.pack(fill='x', pady=(0, 14))
        self.metrics = {}
        for index, (key, label) in enumerate([('completed', 'CYCLES FINISHED'), ('bought', 'CARS BOUGHT'),
                                             ('rewards', 'WHEELSPIN NODES'), ('credits', 'CONFIRMED SPEND')]):
            card = ttk.Frame(metrics, style='Card.TFrame', padding=(14, 9))
            card.grid(row=0, column=index, sticky='nsew', padx=(0, 8 if index < 3 else 0))
            metrics.columnconfigure(index, weight=1)
            ttk.Label(card, text=label, style='Card.TLabel', font=('Segoe UI', 8)).pack(anchor='w')
            var = tk.StringVar(value='0')
            ttk.Label(card, textvariable=var, style='Metric.TLabel').pack(anchor='w')
            self.metrics[key] = var

        self.tree = ttk.Treeview(outer, columns=('stage', 'status'), show='headings', height=8, selectmode='none')
        self.tree.heading('stage', text='PIPELINE MODULE')
        self.tree.heading('status', text='STATUS')
        self.tree.column('stage', width=650, anchor='w')
        self.tree.column('status', width=145, anchor='w')
        for key, name in STAGES:
            self.tree.insert('', 'end', iid=key, values=(name, 'Waiting'))
        self.tree.tag_configure('active', foreground='#00e5d4')
        self.tree.tag_configure('done', foreground='#83a8b0')
        self.tree.pack(fill='x')
        self.progress = ttk.Progressbar(outer, maximum=len(STAGES))
        self.progress.pack(fill='x', pady=(8, 12))

        log_frame = ttk.Frame(outer)
        log_frame.pack(fill='both', expand=True)
        self.log = tk.Text(log_frame, height=5, bg='#061216', fg='#f4fbfb', insertbackground='white',
                           font=('Consolas', 9), wrap='word', borderwidth=0, padx=10, pady=8, state='disabled')
        scroll = ttk.Scrollbar(log_frame, command=self.log.yview)
        self.log.configure(yscrollcommand=scroll.set)
        self.log.pack(side='left', fill='both', expand=True)
        scroll.pack(side='right', fill='y')
        bottom = ttk.Frame(outer)
        self.footer = bottom
        bottom.pack(fill='x', pady=(12, 0))
        ttk.Button(bottom, text='Open logs', command=lambda: self.open_folder('runs')).pack(side='left')
        ttk.Button(bottom, text='Error screenshot', command=self.open_error).pack(side='left', padx=8)
        ttk.Button(bottom, text='Resolve uncertain purchase…', command=self.resolve).pack(side='right')
        self.append_log('Full pipeline visits Designs & Paints, then selects the new copy through My Cars.')
        self.append_log('Claimed Super Wheelspin node is the reward check. Purchased cars stay in your garage.')
        self.append_log('Enter your current SP to set the car limit automatically, then Start or F6.')
        if saved and saved.get('phase') != 'complete':
            self.events.put(('progress', saved))
            self.events.put(('stage', saved['phase']))
            self.events.put(('done', None))
            self.status.set('Reward already claimed. Resume will only return to Car Collection.'
                            if saved['phase'] == 'return' and saved.get('rewards') else
                            f"Saved session: {saved['phase'].replace('_', ' ')}. Leave the current car unchanged and resume from this stage.")
        try:
            if hotkeys:
                import keyboard
                self.hotkey_ids.append(keyboard.add_hotkey('f6', lambda: self.events.put(('start', 0))))
                # Stop is immediate; it does not wait for Tk's queue.
                self.hotkey_ids.append(keyboard.add_hotkey('f7', self.controller.stop))
        except Exception as exc:
            self.start_button.configure(state='disabled')
            self.status.set(f'Hotkeys unavailable: {exc}. Close and reopen the application.')
        self.current_sp.trace_add('write', self.refresh_plan)
        self.mode.trace_add('write', self.refresh_plan)
        self.refresh_plan()
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(100, self.drain)

    def append_log(self, text):
        self.log.configure(state='normal')
        self.log.insert('end', text+'\n')
        if int(self.log.index('end-1c').split('.')[0]) > 1500:
            self.log.delete('1.0', '300.0')
        self.log.see('end')
        self.log.configure(state='disabled')

    def refresh_plan(self, *args):
        saved = self.saved_session
        pending = bool(saved and saved.get('phase') != 'complete')
        full = self.mode.get() == 'Full pipeline'
        busy = self.controller.busy
        self.sp_entry.configure(state='disabled' if busy or pending or not full else 'normal')
        if pending and self.mode.get() == saved['mode']:
            self.limit.set(str(saved['limit']))
            self.limit_entry.configure(state='disabled' if busy else 'readonly')
            target = str(saved['limit']) if saved['limit'] else 'unlimited'
            self.plan_text.set(f"Resume saved run: {saved['completed']} finished / {target} cars. The original target stays fixed.")
            return
        using_sp = full and bool(self.current_sp.get().strip())
        if using_sp and not self._using_sp:
            self._manual_limit = self.limit.get()
        if using_sp:
            try:
                plan = plan_from_sp(self.current_sp.get())
                self.limit.set(str(plan.cars))
                self.plan_text.set(f'{plan.cars:,} cars • {plan.points_used:,} SP used • '
                                   f'{plan.points_left:,} SP left • {plan.credits:,} CR needed'
                                   + (' — At least 21 SP is required to start.' if not plan.cars else ' — Start / F6 runs this plan.'))
            except ValueError as exc:
                self.limit.set('—')
                self.plan_text.set(str(exc))
        else:
            if self._using_sp:
                self.limit.set(self._manual_limit)
            self.plan_text.set('Enter Current SP to calculate the full run. Leave blank for a manual limit (0 = continuous).'
                               if full else 'Manual cycle limit • 0 = continuous • SP planning is available in Full pipeline mode.')
        self._using_sp = using_sp
        self.limit_entry.configure(state='disabled' if busy else 'readonly' if using_sp else 'normal')

    def config(self):
        skill_points = None
        pending = self.saved_session and self.saved_session.get('phase') != 'complete'
        if pending and self.mode.get() == self.saved_session['mode']:
            limit = self.saved_session['limit']
            skill_points = self.saved_session.get('skill_points')
        elif self.mode.get() == 'Full pipeline' and self.current_sp.get().strip():
            plan = plan_from_sp(self.current_sp.get())
            if plan.cars < 1:
                raise ValueError('At least 21 SP is needed for one complete car. No run started.')
            limit, skill_points = plan.cars, plan.points
        else:
            limit = int(self.limit.get())
        value = dict(mode=self.mode.get(), limit=limit, monitor=int(self.monitor.get()),
                     timeout=float(self.timeout.get()), title=self.title.get().strip())
        if value['mode'] not in MODES or value['limit'] < 0 or value['monitor'] < 1 or not 2 <= value['timeout'] <= 120 or not value['title']:
            raise ValueError('Use a nonnegative cycle limit, monitor 1 or higher, and timeout 2–120 seconds.')
        if skill_points is not None:
            value['skill_points'] = skill_points
        return value

    def start(self, delay=0):
        if self.controller.busy or self.closing:
            return
        try:
            saved = Session().data
            self.saved_session = saved
            config = self.config()
            if saved and saved['phase'] != 'complete' and config['mode'] == 'Mastery only':
                raise ValueError('Resume the unfinished pipeline before using standalone mastery, or end its session after checking the car.')
            CONFIG.parent.mkdir(exist_ok=True)
            CONFIG.write_text(json.dumps(config, indent=2), encoding='utf-8')
        except (ValueError, OSError, KeyError) as exc:
            self.status.set(str(exc))
            return
        self.start_button.configure(state='disabled')
        self.end_button.configure(state='disabled')
        for field in self.inputs:
            field.configure(state='disabled')
        self.controller.start(config, delay)

    def stop(self):
        self.controller.stop()
        self.status.set('Stop requested; finishing input release…' if self.controller.busy else 'Stopped')

    def open_folder(self, name):
        path = BASE/name
        path.mkdir(exist_ok=True)
        os.startfile(str(path))

    def open_error(self):
        if self.error_image and os.path.exists(self.error_image):
            os.startfile(self.error_image)
        else:
            self.open_folder('failures')

    def end_session(self):
        if self.controller.busy:
            return
        if messagebox.askyesno('End this session?', 'This closes the saved cycle without sending game inputs.\n\n'
                'Check the current car first. Any unfinished mastery remains unfinished. The next session may buy a new car.\n\n'
                'Uncertain purchases will still block buying. End the session?', parent=self.root):
            try:
                Session().end()
                self.saved_session = Session().data
                if self.saved_session.get('skill_points') is not None:
                    self.current_sp.set('')
                self.refresh_plan()
                self.status.set('Session ended. Open the home/festival menu before starting a new session.')
            except Exception as exc:
                self.status.set(str(exc))

    def resolve(self):
        if self.controller.busy:
            self.status.set('Stop the program before resolving a purchase.')
            return
        answer = messagebox.askyesnocancel('Check the game first', 'Only use this after inspecting the uncertain purchase in the game.\n\n'
            'Was the car actually bought?\n\nYes = bought\nNo = not bought\nCancel = leave it unresolved', parent=self.root)
        if answer is None:
            return
        try:
            PurchaseLedger().resolve('bought' if answer else 'not-bought')
            self.status.set('Purchase outcome recorded. Resume from the saved stage; no game inputs sent.')
        except Exception as exc:
            self.status.set(str(exc))

    def drain(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'start':
                    self.start(value)
                elif kind == 'status':
                    self.status.set(value)
                    self.append_log(value)
                elif kind == 'log':
                    self.append_log(value)
                elif kind == 'screen':
                    self.root.title(f'FH6 Auto • {value.replace("_", " ")}')
                elif kind == 'error_image':
                    self.error_image = value
                    self.append_log('Error screenshot: '+value)
                elif kind == 'progress':
                    self.saved_session = dict(value)
                    for key in ('completed', 'bought', 'rewards'):
                        self.metrics[key].set(str(value[key]))
                    self.metrics['credits'].set(f"{value['bought']*95000:,}")
                elif kind == 'stage':
                    keys = [key for key, _ in STAGES]
                    index = len(keys) if value == 'complete' else keys.index(value)
                    for i, (key, name) in enumerate(STAGES):
                        skipped = self.mode.get() == 'Buy only' and key in {'paints', 'choose', 'open_mastery', 'mastery'}
                        status = 'Not used' if skipped else 'Done' if i < index else 'Running' if i == index else 'Waiting'
                        self.tree.item(key, values=(name, status), tags=('active' if i == index else 'done' if i < index else '',))
                    self.progress['value'] = index
                elif kind == 'done':
                    for key in self.tree.get_children():
                        name, state = self.tree.item(key, 'values')
                        if state == 'Running':
                            self.tree.item(key, values=(name, 'Stopped'))
                    self.start_button.configure(state='normal')
                    self.end_button.configure(state='normal')
                    for field in self.inputs:
                        field.configure(state='readonly' if isinstance(field, ttk.Combobox) else 'normal')
                    saved = self.saved_session
                    if saved.get('phase') == 'complete' and saved.get('skill_points') is not None:
                        self.current_sp.set(str(max(0, saved['skill_points'] - saved.get('rewards', 0) * POINTS_PER_CAR)))
                    self.refresh_plan()
        except queue.Empty:
            pass
        if self.closing and not self.controller.busy:
            self.root.destroy()
            return
        self.root.after(100, self.drain)

    def close(self):
        self.closing = True
        self.controller.stop()
        self.status.set('Closing after input release…')
        if self.hotkey_ids:
            import keyboard
            for hotkey in self.hotkey_ids:
                keyboard.remove_hotkey(hotkey)
            self.hotkey_ids.clear()


def main():
    set_dpi_awareness()
    # Prevent two dashboard processes from issuing overlapping game inputs.
    import ctypes
    kernel = ctypes.windll.kernel32
    kernel.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel.CreateMutexW(None, False, 'Local\\FH6AutoDashboard')
    already_open = kernel.GetLastError() == 183
    if not handle:
        raise OSError('Could not create the application lock')
    root = tk.Tk()
    if already_open:
        root.withdraw()
        messagebox.showinfo('FH6 Auto', 'The dashboard is already open.', parent=root)
        root.destroy()
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle(handle)
        return
    try:
        App(root)
        root.mainloop()
    finally:
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle(handle)


if __name__ == '__main__':
    main()
