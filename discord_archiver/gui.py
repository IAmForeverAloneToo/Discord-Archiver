from __future__ import annotations

import os
import queue
import threading
import webbrowser
from pathlib import Path

from .client import clean_token
from .export import chat_label, export_archive, list_sidebar, retry_media
from .util import Log, program_path
from .viewer import serve_archive


def run_gui(archive: Path | None = None) -> int:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except ImportError:
        print("This Python install has no window toolkit. Run: py -3 -m discord_archiver export")
        return 1

    root = tk.Tk()
    root.title("Discord archiver")
    root.geometry("980x820")
    root.minsize(680, 640)

    archive_var = tk.StringVar(value=str(program_path(None if archive is None else str(archive), "archive")))
    token_var = tk.StringVar()
    users_var = tk.StringVar()
    only_var = tk.BooleanVar(value=False)
    filter_var = tk.StringVar()
    delay_var = tk.StringVar(value="1.15")
    media_var = tk.BooleanVar(value=True)
    friends_var = tk.BooleanVar(value=True)
    leave_var = tk.BooleanVar(value=False)
    external_var = tk.BooleanVar(value=False)
    save_token_var = tk.BooleanVar(value=True)
    show_token_var = tk.BooleanVar(value=False)
    status_var = tk.StringVar(value="Idle")

    token_file = program_path(None, "token.txt")
    if token_file.exists():
        status_var.set("token.txt found. You can start, or paste a new token.")

    frame = ttk.Frame(root, padding=12)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(1, weight=1)

    ttk.Label(
        frame,
        text=(
            "Downloads your own direct messages and files onto this computer. "
            "It does not send messages. Discord can disable accounts that automate the user API."
        ),
        wraplength=720,
    ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

    ttk.Label(frame, text="Token").grid(row=1, column=0, sticky="w")
    token_entry = ttk.Entry(frame, textvariable=token_var, show="*")
    token_entry.grid(row=1, column=1, sticky="ew", padx=6)
    ttk.Checkbutton(frame, text="Show", variable=show_token_var, command=lambda: token_entry.configure(show="" if show_token_var.get() else "*")).grid(row=1, column=2, sticky="w")

    ttk.Label(frame, text="Save to").grid(row=2, column=0, sticky="w", pady=6)
    ttk.Entry(frame, textvariable=archive_var).grid(row=2, column=1, sticky="ew", padx=6)

    def choose_folder() -> None:
        chosen = filedialog.askdirectory(initialdir=archive_var.get() or ".")
        if chosen:
            archive_var.set(chosen)

    ttk.Button(frame, text="Browse", command=choose_folder).grid(row=2, column=2, sticky="ew")

    picker = ttk.LabelFrame(frame, text="Specific chats", padding=8)
    picker.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(0, 6))
    picker.columnconfigure(1, weight=1)
    only_check = ttk.Checkbutton(picker, text="Only selected chats", variable=only_var)
    only_check.grid(row=0, column=0, sticky="w")
    load_btn = ttk.Button(picker, text="Load chats")
    load_btn.grid(row=0, column=2, sticky="e", padx=(8, 0))
    ttk.Label(picker, text="Filter").grid(row=1, column=0, sticky="w", pady=(6, 0))
    ttk.Entry(picker, textvariable=filter_var).grid(row=1, column=1, columnspan=2, sticky="ew", pady=(6, 0))
    list_frame = ttk.Frame(picker)
    list_frame.grid(row=2, column=0, columnspan=3, sticky="ew", pady=6)
    list_frame.columnconfigure(0, weight=1)
    chat_canvas = tk.Canvas(list_frame, height=168, highlightthickness=0)
    chat_scroll = ttk.Scrollbar(list_frame, command=chat_canvas.yview)
    chat_inner = ttk.Frame(chat_canvas)
    chat_window = chat_canvas.create_window((0, 0), window=chat_inner, anchor="nw")
    chat_canvas.configure(yscrollcommand=chat_scroll.set)
    chat_canvas.grid(row=0, column=0, sticky="ew")
    chat_scroll.grid(row=0, column=1, sticky="ns")

    def _fit_chat_list(event) -> None:
        chat_canvas.itemconfigure(chat_window, width=event.width)

    def _scroll_chat_list(_event=None) -> None:
        chat_canvas.configure(scrollregion=chat_canvas.bbox("all"))

    chat_canvas.bind("<Configure>", _fit_chat_list)
    chat_inner.bind("<Configure>", _scroll_chat_list)
    picks = ttk.Frame(picker)
    picks.grid(row=3, column=0, columnspan=3, sticky="ew")
    select_all_btn = ttk.Button(picks, text="Check all shown")
    clear_btn = ttk.Button(picks, text="Clear checks")
    select_all_btn.pack(side="left", padx=(0, 6))
    clear_btn.pack(side="left")
    selection_var = tk.StringVar(value="Selected: none")
    ttk.Label(picker, textvariable=selection_var, wraplength=700).grid(
        row=4, column=0, columnspan=3, sticky="w", pady=(6, 0)
    )
    ttk.Label(picker, text="Extra user IDs").grid(row=5, column=0, sticky="w", pady=(6, 0))
    ttk.Entry(picker, textvariable=users_var).grid(row=5, column=1, columnspan=2, sticky="ew", padx=(6, 0), pady=(6, 0))
    ttk.Label(
        picker,
        text="Check the chats you want. The line under the list names every checked chat before you start.",
        wraplength=700,
    ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(4, 0))

    options = ttk.Frame(frame)
    options.grid(row=5, column=0, columnspan=3, sticky="w", pady=8)
    ttk.Checkbutton(options, text="Download files", variable=media_var).pack(side="left", padx=(0, 12))
    friends_check = ttk.Checkbutton(options, text="Include closed chats with friends", variable=friends_var)
    friends_check.pack(side="left", padx=(0, 12))
    ttk.Checkbutton(options, text="Leave reopened chats in the sidebar", variable=leave_var).pack(side="left")

    extra = ttk.Frame(frame)
    extra.grid(row=6, column=0, columnspan=3, sticky="w")
    ttk.Checkbutton(extra, text="Also download external embed files", variable=external_var).pack(side="left", padx=(0, 12))
    ttk.Checkbutton(extra, text="Save token to token.txt", variable=save_token_var).pack(side="left", padx=(0, 12))
    ttk.Label(extra, text="Delay").pack(side="left")
    ttk.Entry(extra, textvariable=delay_var, width=6).pack(side="left", padx=6)

    buttons = ttk.Frame(frame)
    buttons.grid(row=7, column=0, columnspan=3, sticky="ew", pady=8)
    start_btn = ttk.Button(buttons, text="Start")
    stop_btn = ttk.Button(buttons, text="Stop", state="disabled")
    retry_btn = ttk.Button(buttons, text="Retry missing files")
    fixmedia_btn = ttk.Button(buttons, text="Fix saved files")
    open_btn = ttk.Button(buttons, text="Open folder")
    browse_btn = ttk.Button(buttons, text="Browse archive")
    start_btn.pack(side="left", padx=(0, 6))
    stop_btn.pack(side="left", padx=(0, 6))
    retry_btn.pack(side="left", padx=(0, 6))
    fixmedia_btn.pack(side="left", padx=(0, 6))
    open_btn.pack(side="left", padx=(0, 6))
    browse_btn.pack(side="left")

    ttk.Label(frame, textvariable=status_var).grid(row=8, column=0, columnspan=3, sticky="w")
    log_box = tk.Text(frame, height=18, wrap="word", state="disabled")
    log_box.grid(row=9, column=0, columnspan=3, sticky="nsew", pady=(6, 0))
    frame.rowconfigure(9, weight=1)

    chat_rows: list[dict] = []
    checked: dict[str, tk.BooleanVar] = {}
    events: queue.Queue[str] = queue.Queue()
    worker: threading.Thread | None = None
    stop_event = threading.Event()
    viewer_server = None

    def append_log(line: str) -> None:
        events.put(line)

    def pump() -> None:
        while True:
            try:
                line = events.get_nowait()
            except queue.Empty:
                break
            log_box.configure(state="normal")
            log_box.insert("end", line + "\n")
            log_box.see("end")
            log_box.configure(state="disabled")
        root.after(150, pump)

    def set_running(running: bool) -> None:
        start_btn.configure(state="disabled" if running else "normal")
        retry_btn.configure(state="disabled" if running else "normal")
        fixmedia_btn.configure(state="disabled" if running else "normal")
        load_btn.configure(state="disabled" if running else "normal")
        stop_btn.configure(state="normal" if running else "disabled")
        status_var.set("Working. You can stop and resume." if running else "Idle")

    def resolve_token() -> str:
        typed = token_var.get().strip()
        if typed:
            token = clean_token(typed)
            if save_token_var.get():
                token_file.write_text(token + "\n", encoding="utf-8")
                append_log("Saved token.txt. Keep that file private.")
            return token
        if token_file.exists():
            for line in token_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    return clean_token(line)
        raise SystemExit("Paste your account token first. See the README for how to copy it.")

    def parse_users() -> list[str]:
        raw = users_var.get().replace(";", ",").replace("\n", ",")
        return [part.strip() for part in raw.split(",") if part.strip()]

    def parse_delay() -> float:
        try:
            return max(0.2, float(delay_var.get().strip() or "1.15"))
        except ValueError:
            return 1.15

    def run_job(job) -> None:
        nonlocal worker
        if worker and worker.is_alive():
            return
        try:
            token = resolve_token()
        except SystemExit as exc:
            messagebox.showerror("Discord archiver", str(exc.code or exc))
            return
        destination = Path(archive_var.get().strip() or "archive")
        stop_event.clear()
        set_running(True)
        logger = Log(destination / "export.log", echo=append_log)

        def target() -> None:
            try:
                code = job(destination, token, logger)
                append_log("Done." if code == 0 else f"Stopped with code {code}.")
            except Exception as exc:
                append_log(f"Failed: {exc}")
            finally:
                logger.close()
                root.after(0, lambda: set_running(False))

        worker = threading.Thread(target=target, daemon=False)
        worker.start()

    def selected_rows() -> list[dict]:
        return [row for row in chat_rows if checked.get(str(row.get("id")), tk.BooleanVar()).get()]

    def row_blob(row: dict) -> str:
        return " ".join(
            str(row.get(key) or "")
            for key in ("title", "username", "user_id", "id", "members")
        ).casefold()

    def update_selection_label() -> None:
        rows = selected_rows()
        if not rows:
            selection_var.set("Selected: none. Start will copy every open chat unless you check some and leave Only selected chats on.")
            return
        names = [chat_label(row) for row in rows]
        if len(names) == 1:
            selection_var.set(f"Selected: 1 chat — {names[0]}")
            return
        shown = ", ".join(names[:6])
        extra = f", and {len(names) - 6} more" if len(names) > 6 else ""
        selection_var.set(f"Selected: {len(names)} chats — {shown}{extra}")

    def redraw_chats(*_args) -> None:
        needle = filter_var.get().casefold().strip()
        for child in chat_inner.winfo_children():
            child.destroy()
        shown = 0
        for row in chat_rows:
            if needle and needle not in row_blob(row):
                continue
            cid = str(row.get("id") or "")
            if cid not in checked:
                checked[cid] = tk.BooleanVar(value=False)
            ttk.Checkbutton(
                chat_inner,
                text=chat_label(row),
                variable=checked[cid],
                command=update_selection_label,
            ).pack(anchor="w", fill="x")
            shown += 1
        if not chat_rows:
            ttk.Label(chat_inner, text="Click Load chats to see your open DMs.").pack(anchor="w")
        elif shown == 0:
            ttk.Label(chat_inner, text="No chats match that filter. Checked chats stay selected.").pack(anchor="w")
        update_selection_label()
        root.after_idle(_scroll_chat_list)

    def set_visible_checks(value: bool) -> None:
        needle = filter_var.get().casefold().strip()
        for row in chat_rows:
            if needle and needle not in row_blob(row):
                continue
            cid = str(row.get("id") or "")
            if cid not in checked:
                checked[cid] = tk.BooleanVar(value=value)
            else:
                checked[cid].set(value)
        redraw_chats()

    def selected_channel_ids() -> list[str]:
        return [str(row["id"]) for row in selected_rows()]

    def toggle_only() -> None:
        friends_check.configure(state="disabled" if only_var.get() else "normal")

    def load_chats() -> None:
        try:
            token = resolve_token()
        except SystemExit as exc:
            messagebox.showerror("Discord archiver", str(exc.code or exc))
            return
        status_var.set("Loading open chats...")
        load_btn.configure(state="disabled")

        def work() -> None:
            try:
                rows = list_sidebar(token, delay=parse_delay())
            except SystemExit as exc:
                root.after(0, lambda: append_log(str(exc.code or exc)))
                root.after(0, lambda: load_btn.configure(state="normal"))
                return
            except Exception as exc:
                root.after(0, lambda: append_log(f"Could not list chats: {exc}"))
                root.after(0, lambda: load_btn.configure(state="normal"))
                return

            def apply() -> None:
                chat_rows[:] = rows
                redraw_chats()
                only_var.set(True)
                toggle_only()
                load_btn.configure(state="normal")
                status_var.set(f"{len(rows)} open chats. Select one or more, then Start.")

            root.after(0, apply)

        threading.Thread(target=work, daemon=True).start()

    def start() -> None:
        only = only_var.get()
        chosen = selected_rows()
        selected = [str(row["id"]) for row in chosen] if only else []
        extra_users = parse_users()
        if only and not selected and not extra_users:
            messagebox.showerror(
                "Discord archiver",
                "Check at least one chat, or paste a user ID. The Selected line under the list shows what is checked.",
            )
            return
        if only:
            names = [chat_label(row) for row in chosen]
            if extra_users:
                names.extend(f"user {uid}" for uid in extra_users)
            preview = "\n".join(f"• {name}" for name in names[:20])
            if len(names) > 20:
                preview += f"\n• and {len(names) - 20} more"
            if not messagebox.askokcancel(
                "Copy these chats only?",
                f"{len(names)} chat(s) will be copied. Nothing else.\n\n{preview}",
            ):
                return
            append_log("Copying only: " + ", ".join(names))
        elif chosen:
            if not messagebox.askokcancel(
                "Copy every open chat?",
                "Chats are checked, but Only selected chats is off. Start will copy every open chat, not just the checked ones.",
            ):
                return

        def job(destination: Path, token: str, logger: Log) -> int:
            return export_archive(
                destination,
                token,
                delay=parse_delay(),
                with_friends=False if only else friends_var.get(),
                leave_reopened=leave_var.get(),
                download_media=media_var.get(),
                include_external=external_var.get(),
                channel_ids=selected,
                user_ids=extra_users,
                only=only,
                log=logger,
                stop=stop_event,
            )

        run_job(job)

    def retry() -> None:
        def job(destination: Path, token: str, logger: Log) -> int:
            return retry_media(
                destination,
                token,
                delay=parse_delay(),
                include_external=external_var.get(),
                log=logger,
                stop=stop_event,
            )

        run_job(job)

    def fix_media() -> None:
        from .media import dedupe_media, repair_media_names

        if worker and worker.is_alive():
            return
        destination = Path(archive_var.get().strip() or "archive")
        try:
            renamed = repair_media_names(destination)
            removed = dedupe_media(destination)
        except Exception as exc:
            messagebox.showerror("Discord archiver", f"Could not fix saved files: {exc}")
            return
        append_log(
            f"Fixed {renamed} file names and removed {removed} duplicate files. No Discord connection was made."
        )

    def stop() -> None:
        stop_event.set()
        status_var.set("Stopping after the current page...")
        append_log("Stop requested. Finishing the current page.")

    def open_folder() -> None:
        path = Path(archive_var.get().strip() or "archive")
        path.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(path)  # noqa: S606 - opens the archive folder the user chose
        else:
            webbrowser.open(path.resolve().as_uri())

    def browse() -> None:
        nonlocal viewer_server
        path = Path(archive_var.get().strip() or "archive")
        if viewer_server is not None:
            webbrowser.open(f"http://127.0.0.1:{viewer_server.server_address[1]}/")
            return
        try:
            viewer_server = serve_archive(path, open_browser=True)
        except SystemExit as exc:
            messagebox.showerror("Discord archiver", str(exc.code or exc))
            return
        threading.Thread(target=viewer_server.serve_forever, daemon=True).start()
        append_log(f"Viewer: http://127.0.0.1:{viewer_server.server_address[1]}/")

    def on_close() -> None:
        if worker and worker.is_alive():
            stop_event.set()
            status_var.set("Stopping, then this window will close.")
            root.after(400, on_close)
            return
        if viewer_server is not None:
            viewer_server.shutdown()
        root.destroy()

    redraw_chats()
    only_check.configure(command=toggle_only)
    load_btn.configure(command=load_chats)
    select_all_btn.configure(command=lambda: set_visible_checks(True))
    clear_btn.configure(command=lambda: set_visible_checks(False))
    filter_var.trace_add("write", redraw_chats)
    start_btn.configure(command=start)
    stop_btn.configure(command=stop)
    retry_btn.configure(command=retry)
    fixmedia_btn.configure(command=fix_media)
    open_btn.configure(command=open_folder)
    browse_btn.configure(command=browse)
    root.protocol("WM_DELETE_WINDOW", on_close)
    pump()
    root.mainloop()
    return 0
