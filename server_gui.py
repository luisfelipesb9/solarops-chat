"""Tkinter front-end for the chat server (SPEC.md §5.2).

Server threads only put (kind, data) tuples on a queue; widgets are touched here, on the main
thread, from a poll() callback scheduled with root.after().
"""

import queue
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

from server import MESSAGE_KINDS, format_event

POLL_MS = 100
MAX_EVENTS_PER_POLL = 200  # keeps one poll short even after a burst of traffic
ALERT_KINDS = {"error", "bot_timeout"}


class ServerGUI:
    def __init__(self, root, server, event_queue):
        self.root = root
        self.server = server
        self.events = event_queue
        self._last_rows = {}

        root.title("SolarOps Chat — Servidor")
        root.geometry("1000x640")
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.columnconfigure((0, 1), weight=1)
        root.rowconfigure((0, 1), weight=1)

        self.participants = self._table(0, 0, "Participantes", ("Nome", "Papel", "TLS", "Endereço"))
        self.pending = self._table(0, 1, "Pedidos ao bot pendentes", ("Requisição", "Solicitante", "Espera"))
        self.messages = self._log(1, 0, "Mensagens")
        self.event_log = self._log(1, 1, "Eventos")

        self._after_id = root.after(POLL_MS, self.poll)

    # ------------------------------------------------------------------ widgets
    def _table(self, row, col, title, columns):
        frame = ttk.LabelFrame(self.root, text=title)
        frame.grid(row=row, column=col, sticky="nsew", padx=6, pady=6)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        table = ttk.Treeview(frame, columns=columns, show="headings", height=8)
        for name in columns:
            table.heading(name, text=name)
            table.column(name, width=90, anchor="w")
        table.grid(sticky="nsew")
        return table

    def _log(self, row, col, title):
        frame = ttk.LabelFrame(self.root, text=title)
        frame.grid(row=row, column=col, sticky="nsew", padx=6, pady=6)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        log = ScrolledText(frame, height=12, state="disabled", wrap="word")
        log.tag_config("alert", foreground="#b00020")
        log.grid(sticky="nsew")
        return log

    # ------------------------------------------------------------------ main-thread updates
    def poll(self):
        for _ in range(MAX_EVENTS_PER_POLL):
            try:
                kind, data = self.events.get_nowait()
            except queue.Empty:
                break
            self._show_event(kind, data)
        self._refresh(self.participants, [
            (p["name"], p["role"], "sim" if p["tls"] else "não", p["addr"])
            for p in self.server.snapshot()])
        self._refresh(self.pending, [
            (p["req_id"][:8], p["from"], f"{p['age']:.0f} s")
            for p in self.server.pending_snapshot()])
        self._after_id = self.root.after(POLL_MS, self.poll)

    def _show_event(self, kind, data):
        log = self.messages if kind in MESSAGE_KINDS else self.event_log
        log.configure(state="normal")
        log.insert("end", format_event(kind, data) + "\n", "alert" if kind in ALERT_KINDS else "")
        log.configure(state="disabled")
        log.see("end")

    def _refresh(self, table, rows):
        if self._last_rows.get(table) == rows:  # avoid flicker when nothing changed
            return
        self._last_rows[table] = rows
        table.delete(*table.get_children())
        for row in rows:
            table.insert("", "end", values=row)

    def on_close(self):
        self.root.after_cancel(self._after_id)
        self.server.stop()
        self.root.destroy()
