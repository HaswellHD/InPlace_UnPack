"""German / English texts. Language follows the Windows UI language."""
from __future__ import annotations

import os

_SIZE_KEYS = {"need", "free", "missing", "size", "total", "alloc"}


def _detect() -> str:
    env = os.environ.get("INPLACE_UNPACK_LANG")
    return env if env in ("de", "en") else "en"   # English unless chosen otherwise


LANG = _detect()


def set_lang(code: str) -> None:
    """Language from the settings; the environment variable still wins."""
    global LANG
    env = os.environ.get("INPLACE_UNPACK_LANG")
    LANG = env if env in ("de", "en") else (code if code in ("de", "en") else "en")


def fmt_bytes(n: int) -> str:
    if n < 0:
        return "?"
    for unit, div in (("GB", 1024 ** 3), ("MB", 1024 ** 2), ("KB", 1024)):
        if n >= div:
            v = f"{n / div:,.2f}"
            if LANG == "de":
                v = v.replace(",", "X").replace(".", ",").replace("X", ".")
            return f"{v} {unit}"
    return f"{n} B"


T = {
    # ---- pre-flight problems (block the start) ----
    "archive_missing": ("Die ZIP-Datei wurde nicht gefunden: {name}",
                        "The ZIP file was not found: {name}"),
    "archive_link": ("Die ZIP-Datei ist eine Verknüpfung (Symlink/Junction). Bitte die echte Datei wählen.",
                     "The ZIP file is a link (symlink/junction). Please choose the real file."),
    "archive_cloud": ("Die ZIP-Datei liegt nur in der Cloud (z. B. OneDrive „Nur online“). Bitte zuerst „Immer auf diesem Gerät behalten“ wählen.",
                      "The ZIP file is a cloud placeholder (e.g. OneDrive online-only). Make it 'Always keep on this device' first."),
    "archive_readonly": ("Die ZIP-Datei ist schreibgeschützt.", "The ZIP file is read-only."),
    "archive_unreadable": ("Die ZIP-Datei kann nicht gelesen werden: {error}",
                           "The ZIP file cannot be read: {error}"),
    "no_sparse": ("Das Laufwerk der ZIP ({fs}) unterstützt keine Sparse-Dateien. Nötig ist NTFS oder ReFS.",
                  "The ZIP's drive ({fs}) does not support sparse files. NTFS or ReFS is required."),
    "target_not_dir": ("Das Ziel ist eine Datei, kein Ordner: {name}",
                       "The target is a file, not a folder: {name}"),
    "journal_corrupt": ("Die Fortschrittsdatei ist beschädigt ({error}): {name}",
                        "The progress file is damaged ({error}): {name}"),
    "journal_other_target": ("Diese ZIP wurde schon teilweise nach „{name}“ entpackt. Bitte genau diesen Zielordner wählen, um fortzusetzen.",
                             "This ZIP was already partly extracted to '{name}'. Choose exactly that folder to resume."),
    "bad_zip": ("Keine gültige oder eine nicht unterstützte ZIP-Datei: {error}",
                "Not a valid or not a supported ZIP file: {error}"),
    "journal_mismatch": ("Die Fortschrittsdatei gehört zu einer anderen ZIP: {name}",
                         "The progress file belongs to a different ZIP: {name}"),
    "encrypted": ("{count} verschlüsselte Einträge (z. B. „{name}“). Verschlüsselte ZIPs werden nicht unterstützt.",
                  "{count} encrypted entries (e.g. '{name}'). Encrypted ZIPs are not supported."),
    "method": ("{count} Einträge mit nicht unterstützter Kompression {method} (z. B. „{name}“).",
               "{count} entries use unsupported compression {method} (e.g. '{name}')."),
    "overlap": ("{count} Einträge überlappen sich (z. B. „{name}“). Die ZIP ist beschädigt oder manipuliert.",
                "{count} entries overlap (e.g. '{name}'). The ZIP is damaged or manipulated."),
    "local_header_missing": ("Der Anfang der ZIP ist schon gelöscht, aber die Fortschrittsdatei fehlt. Ein früherer Lauf wurde nicht sauber fortgesetzt.",
                             "The start of the ZIP was already released but the progress file is missing."),
    "bad_entry": ("{count} beschädigte Einträge (z. B. „{name}“).", "{count} damaged entries (e.g. '{name}')."),
    "path_escape": ("Unsicherer Pfad: {name}", "Unsafe path: {name}"),
    "collides_archive": ("Der Eintrag „{name}“ würde die ZIP selbst oder ihre Fortschrittsdatei überschreiben. Bitte einen anderen Zielordner wählen.",
                         "Entry '{name}' would overwrite the ZIP itself or its progress file. Choose another target folder."),
    "conflict_type": ("{count}× Ordner und Datei mit gleichem Namen im Ziel (z. B. „{name}“).",
                      "{count}× a folder and a file with the same name in the target (e.g. '{name}')."),
    "conflicts": ("{count} Dateien existieren im Ziel schon (z. B. „{name}“). Anderen Ordner wählen oder Überschreiben erlauben.",
                  "{count} files already exist in the target (e.g. '{name}'). Pick another folder or allow overwriting."),
    "space": ("Zu wenig Speicherplatz: benötigt werden etwa {need}, frei sind {free}. Es fehlen {missing}.",
              "Not enough space: about {need} needed, {free} free. {missing} missing."),
    # ---- warnings ----
    "archive_compressed": ("Die ZIP ist mit NTFS komprimiert. Es wird weniger Platz frei als ihre Größe.",
                           "The ZIP is NTFS-compressed; less space is freed than its size."),
    "other_volume": ("ZIP und Ziel liegen auf verschiedenen Laufwerken. Dann hilft das Freigeben nicht, das Ziel braucht den vollen Platz.",
                     "ZIP and target are on different drives, so releasing does not help the target."),
    "renamed": ("{count} Namen wurden für Windows angepasst (z. B. „{name}“ → „{new}“).",
                "{count} names were adjusted for Windows (e.g. '{name}' → '{new}')."),
    "resuming": ("Unterbrochener Vorgang gefunden: {done} von {total} Einträgen sind fertig. Es wird fortgesetzt.",
                 "Interrupted run found: {done} of {total} entries are done. It will resume."),
    "will_overwrite": ("{count} vorhandene Dateien werden überschrieben.",
                       "{count} existing files will be overwritten."),
    # ---- run stopped ----
    "cancelled": ("Angehalten. Sie können jederzeit fortsetzen.", "Paused. You can resume at any time."),
    "out_of_space": ("Der Speicherplatz reicht nicht für „{name}“ (benötigt {need}, frei {free}). Schaffen Sie Platz und setzen Sie dann fort. Bleibt der freie Platz trotz Freigabe gleich, belegen wahrscheinlich Wiederherstellungspunkte (Schattenkopien) den Platz.",
                     "Not enough space for '{name}' (needs {need}, {free} free). Free some space, then resume. If free space does not grow, restore points (shadow copies) are probably holding it."),
    "crc": ("Der Eintrag „{name}“ ist in der ZIP beschädigt ({error}). Alles davor ist entpackt, alles danach ist noch in der ZIP.",
            "Entry '{name}' is damaged in the ZIP ({error}). Everything before it is extracted, everything after is still in the ZIP."),
    "io_error": ("Fehler bei „{name}“: {error}. Sie können fortsetzen, sobald die Ursache behoben ist.",
                 "Error at '{name}': {error}. You can resume once the cause is fixed."),
    "link_in_target": ("Im Zielordner liegt eine Verknüpfung (Junction/Symlink): {path}. Aus Sicherheitsgründen gestoppt.",
                       "There is a link (junction/symlink) in the target: {path}. Stopped for safety."),
    # ---- UI ----
    "app_title": ("Inplace-Unpack", "Inplace-Unpack"),
    "zip_file": ("ZIP-Datei:", "ZIP file:"),
    "target": ("Zielordner:", "Target folder:"),
    "browse": ("Durchsuchen …", "Browse …"),
    "check": ("Prüfen", "Check"),
    "start": ("Entpacken starten", "Start extracting"),
    "resume": ("Fortsetzen", "Resume"),
    "pause": ("Anhalten (fortsetzbar)", "Pause (resumable)"),
    "overwrite": ("Vorhandene Dateien überschreiben", "Overwrite existing files"),
    "delete_after": ("ZIP nach Erfolg löschen", "Delete ZIP when finished"),
    "confirm": ("Ich habe verstanden: Die ZIP-Datei wird dabei unwiderruflich zerstört.",
                "I understand that the ZIP file is irreversibly destroyed in the process."),
    "warning_box": ("ACHTUNG: Dieses Programm löscht die ZIP-Datei Stück für Stück, während es entpackt. "
                    "Bricht der Vorgang ab, kann er fortgesetzt werden. Ist die ZIP aber beschädigt, "
                    "sind die noch nicht entpackten Teile verloren. Verwenden Sie es nur, wenn Sie die ZIP "
                    "notfalls erneut beschaffen können oder den Verlust akzeptieren.",
                    "WARNING: this program deletes the ZIP file piece by piece while it extracts. "
                    "An interrupted run can be resumed, but if the ZIP is damaged, the parts not yet "
                    "extracted are lost. Only use it if you can get the ZIP again or accept that risk."),
    "summary": ("{entries} Einträge, entpackt {total}. ZIP: {size}. Frei auf dem Ziel-Laufwerk: {free}. "
                "Spitzenbedarf: {need} (inkl. Reserve).",
                "{entries} entries, {total} extracted. ZIP: {size}. Free on target drive: {free}. "
                "Peak need: {need} (incl. reserve)."),
    "fits": ("✔ Passt.", "✔ Fits."),
    "not_ok": ("✖ Kann nicht gestartet werden:", "✖ Cannot start:"),
    "status_running": ("{done}/{ntotal} Einträge · {bytes} von {btotal} · {speed}/s (Ø {avg}/s) · ZIP belegt noch {alloc} · frei {free}",
                       "{done}/{ntotal} entries · {bytes} of {btotal} · {speed}/s (avg {avg}/s) · ZIP still uses {alloc} · {free} free"),
    "speed_avg":("{speed}/s (Ø {avg}/s)", "{speed}/s (avg {avg}/s)"),
    "s_delete_parts": ("Geteilte ZIPs: fertige Teile löschen", "Split ZIPs: delete finished parts"),
    "d_delete_parts": ("Bei „name.zip.001, .002, …“ wird jeder Teil gelöscht, sobald alles darin sicher entpackt ist. Aus: Die Teile bleiben erhalten (dann wird der volle Platz gebraucht).",
                       "For 'name.zip.001, .002, …' each part is deleted as soon as everything in it is safely extracted. Off: parts are kept (the full space is needed then)."),
    "s_explorer_menu": ("Im Rechtsklick-Menü des Explorers anzeigen", "Show in the Explorer right-click menu"),
    "d_explorer_menu": ("Fügt „Mit Inplace-Unpack entpacken“ für .zip und .zip.001 hinzu (Windows 11: unter „Weitere Optionen anzeigen“). Nur für Ihr Benutzerkonto, keine Administratorrechte nötig.",
                        "Adds 'Extract with Inplace-Unpack' for .zip and .zip.001 (Windows 11: under 'Show more options'). Only for your user account, no administrator rights needed."),
    "menu_label": ("Mit Inplace-Unpack entpacken", "Extract with Inplace-Unpack"),
    "zip_types": ("ZIP-Archive", "ZIP archives"),
    "done_msg": ("Fertig: {entries} Einträge entpackt ({total}).", "Done: {entries} entries extracted ({total})."),
    "done_keep": ("Die ZIP belegt kaum noch Platz und kann gelöscht werden.",
                  "The ZIP uses almost no space now and can be deleted."),
    "done_deleted": ("Die ZIP wurde gelöscht.", "The ZIP was deleted."),
    "really_start": ("Die ZIP-Datei\n{name}\nwird jetzt beim Entpacken zerstört. Fortfahren?",
                     "The ZIP file\n{name}\nwill now be destroyed while extracting. Continue?"),
    "choose_first": ("Bitte ZIP-Datei und Zielordner wählen.", "Please choose a ZIP file and a target folder."),
    "warnings": ("Hinweise:", "Notes:"),
    "vss_note": ("Hinweis: Gibt es Wiederherstellungspunkte auf dem Laufwerk, wird freigegebener Platz eventuell erst später frei. Das Programm hält dann sauber an.",
                 "Note: if the drive has restore points, released space may not become free; the program then stops cleanly."),
    "unexpected": ("Unerwarteter Fehler: {error}", "Unexpected error: {error}"),
    # ---- 0.3: new problems / stops ----
    "temp_missing": ("Der Temp-Ordner existiert nicht: {name}", "The temp folder does not exist: {name}"),
    "temp_space": ("Im Temp-Ordner ist zu wenig Platz (benötigt {need}): {name}",
                   "Not enough space in the temp folder (needs {need}): {name}"),
    "temp_other_volume": ("Der Temp-Ordner liegt auf einem anderen Laufwerk. Jede Datei muss dann zusätzlich kopiert werden, das ist langsamer.",
                          "The temp folder is on another drive: every file has to be copied, which is slower."),
    "out_of_memory": ("Zu wenig Arbeitsspeicher bei „{name}“. Bitte „Maximaler RAM“ verringern oder den sicheren Modus wählen, dann fortsetzen.",
                      "Out of memory at '{name}'. Lower 'Maximum RAM' or use Safe mode, then resume."),
    "permission": ("Keine Berechtigung bei „{name}“ ({error}). Ist die Datei in einem anderen Programm geöffnet? Danach fortsetzen.",
                   "Permission denied at '{name}' ({error}). Is the file open in another program? Then resume."),
    # ---- modes ----
    "modes": ("Entpack-Modus", "Extraction mode"),
    "mode_safe": ("Sicher", "Safe"),
    "mode_safe_desc": ("Maximale Zuverlässigkeit. 1 Thread, Journal alle 64 MB, jede Datei wird nach dem Schreiben nachgeprüft.",
                       "Maximum reliability. 1 thread, journal every 64 MB, every file is verified after writing."),
    "mode_safe_info": ("Tempo: niedrig · RAM: bis 256 MB, kleine Dateien im RAM · Speicher: max. ~64 MB Rückstand · Zuverlässigkeit: höchste",
                       "Speed: low · RAM: up to 256 MB, small files in RAM · Disk: max. ~64 MB lag · Reliability: highest"),
    "mode_balanced": ("Ausgewogen", "Balanced"),
    "mode_balanced_desc": ("Gutes Tempo, ohne den PC auszubremsen. Niedrige CPU-Priorität, Daten werden alle 64 MB auf die Platte geschrieben (keine Hänger), Journal alle 1 GB (einstellbar).",
                           "Good speed without slowing the PC down. Low CPU priority, data is flushed every 64 MB (no hangs), journal every 1 GB (configurable)."),
    "mode_balanced_info": ("Tempo: hoch · RAM: bis 512 MB, kleine Dateien im RAM · Speicher: max. ~1 GB Rückstand · Zuverlässigkeit: hoch",
                           "Speed: high · RAM: up to 512 MB, small files in RAM · Disk: max. ~1 GB lag · Reliability: high"),
    "mode_performance": ("Leistung", "Performance"),
    "mode_performance_desc": ("Maximales Tempo. 2 Arbeits-Threads, normale Priorität, Journal alle 2 GB. Andere Programme warten öfter auf die Platte.",
                              "Maximum speed. 2 worker threads, normal priority, journal every 2 GB. Other programs wait for the disk more often."),
    "mode_performance_info": ("Tempo: am höchsten · RAM: bis 1 GB · Speicher: max. ~2 GB Rückstand · Zuverlässigkeit: hoch (Daten werden nie vor dem Sichern freigegeben)",
                              "Speed: highest · RAM: up to 1 GB · Disk: max. ~2 GB lag · Reliability: high (data is never released before it is flushed)"),
    "recommended": ("Empfohlen", "Recommended"),
    "modes_header": ("Entpack-Modus: {mode}", "Extraction mode: {mode}"),
    "s_keep_damaged": ("Beschädigte Dateien behalten und weitermachen", "Keep damaged files and continue"),
    "d_keep_damaged": ("Ist eine Datei in der ZIP beschädigt (CRC-Fehler), wird sie unverändert entpackt, in „<zip>.damaged.txt“ vermerkt und es geht automatisch weiter. Aus: Der Vorgang hält an dieser Datei an.",
                       "If a file inside the ZIP is damaged (CRC error) it is extracted unchanged, listed in '<zip>.damaged.txt' and extraction continues automatically. Off: the run stops at that file."),
    "s_language": ("Sprache (nach Neustart)", "Language (after restart)"),
    "d_language": ("en = Englisch, de = Deutsch.", "en = English, de = German."),
    "done_damaged": ("{count} beschädigte Datei(en) wurden unverändert entpackt. Liste: {path}",
                     "{count} damaged file(s) were extracted unchanged. List: {path}"),
    "last_stop": ("Letzter Lauf angehalten:", "Last run stopped:"),
    # ---- advanced settings ----
    "advanced": ("Erweiterte Einstellungen …", "Advanced settings …"),
    "advanced_title": ("Erweiterte Entpack-Einstellungen", "Advanced extraction settings"),
    "tab_cpu": ("CPU", "CPU"), "tab_ram": ("RAM", "RAM"), "tab_storage": ("Speicher", "Storage"),
    "tab_journal": ("Journal & Wiederherstellung", "Journal & recovery"), "tab_other": ("Sonstiges", "Other"),
    "custom_note": ("Werte ändern überschreibt die Voreinstellung des gewählten Modus. Ungültige Werte werden automatisch auf sichere Grenzen gesetzt.",
                    "Changing values overrides the preset of the selected mode. Invalid values are clamped to safe limits."),
    "save": ("Speichern", "Save"), "cancel_btn": ("Abbrechen", "Cancel"),
    "clamped": ("Diese Werte lagen außerhalb der sicheren Grenzen und wurden angepasst:",
                "These values were outside the safe limits and have been adjusted:"),
    "defaults": ("Standard wiederherstellen", "Restore defaults"),
    "s_auto_threads": ("Threads automatisch wählen", "Choose threads automatically"),
    "d_auto_threads": ("Wählt die Thread-Zahl passend zum Modus (1 bzw. 2). Gemessen: Mehr Threads waren auf einer SATA-SSD nicht schneller, die Platte bremst, nicht die CPU. Auf schnellen NVMe-SSDs kann ein höherer Wert helfen, das lässt sich mit „inplace-unpack bench“ prüfen.",
                       "Picks the thread count for the mode (1 or 2). Measured: more threads were not faster on a SATA SSD, the disk is the limit, not the CPU. On fast NVMe drives more may help; check with 'inplace-unpack bench'."),
    "s_max_threads": ("Maximale Threads", "Maximum threads"),
    "d_max_threads": ("Wie viele Einträge gleichzeitig entpackt werden (wenn „automatisch“ aus ist). Höher bedeutet mehr CPU- und Plattenlast.",
                      "How many entries are extracted at the same time (when 'automatic' is off). Higher = more CPU and disk load."),
    "s_max_cpu_percent": ("Maximale CPU-Auslastung (%)", "Maximum CPU usage (%)"),
    "d_max_cpu_percent": ("Obergrenze für die CPU-Nutzung des Programms, bezogen auf den ganzen PC. Wird überschritten, pausiert das Programm kurz.",
                          "Upper limit for the program's CPU use, relative to the whole PC. When exceeded the program pauses briefly."),
    "s_background_mode": ("Hintergrund-Modus (niedrige Platten-Priorität)", "Background mode (low disk priority)"),
    "d_background_mode": ("Sehr niedrige Platten-Priorität für das Entpacken. Achtung: In Messungen auf einer SATA-SSD wurde das Entpacken dadurch langsamer und andere Programme mussten teils sogar länger warten. Gegen einen „langsamen PC“ hilft eher eine Schreib-Obergrenze.",
                          "Very low disk priority for extraction. Note: measured on a SATA SSD it made extraction slower and sometimes made other programs wait longer. A write-speed limit is more effective against a 'slow PC'."),
    "s_priority": ("Priorität", "Priority"),
    "d_priority": ("CPU-Priorität der Entpack-Threads (idle = nur wenn der PC sonst nichts tut). Die Oberfläche behält immer die normale Priorität.",
                   "CPU priority of the extraction threads (idle = only when the PC has nothing else to do). The window always keeps normal priority."),
    "s_max_ram_mb": ("Maximaler RAM (MB)", "Maximum RAM (MB)"),
    "d_max_ram_mb": ("Höchstens so viel RAM für Puffer und kleine Dateien. Obergrenze: ¼ des eingebauten RAMs.",
                     "At most this much RAM for buffers and small files. Upper limit: ¼ of installed RAM."),
    "s_ram_threshold_percent": ("RAM-Schwelle (%)", "RAM threshold (%)"),
    "d_ram_threshold_percent": ("Ist der Arbeitsspeicher des Systems stärker ausgelastet, schreibt das Programm direkt auf die Platte und arbeitet weniger parallel.",
                                "If system memory load is above this, the program streams to disk and runs fewer entries in parallel."),
    "s_auto_memory": ("Automatische Speicherverwaltung", "Automatic memory management"),
    "d_auto_memory": ("Verwendet höchstens ¼ des gerade freien RAMs, auch wenn das Maximum höher ist.",
                      "Uses at most ¼ of currently free RAM, even if the maximum is higher."),
    "s_auto_ram_disk": ("RAM oder Platte automatisch wählen", "Choose RAM or disk automatically"),
    "d_auto_ram_disk": ("Kleine Dateien werden im RAM entpackt und in einem Zug geschrieben, große werden gestreamt. Aus = alles streamen.",
                        "Small files are decompressed in RAM and written in one go, large files are streamed. Off = stream everything."),
    "s_temp_dir": ("Temp-Ordner für unfertige Dateien", "Temp folder for unfinished files"),
    "d_temp_dir": ("Leer = direkt neben der Zieldatei (am schnellsten, empfohlen). Ein Ordner auf einem anderen Laufwerk braucht eine zusätzliche Kopie.",
                   "Empty = next to the target file (fastest, recommended). A folder on another drive needs an extra copy."),
    "s_max_temp_gb": ("Max. unfertige Daten gleichzeitig (GB)", "Max. unfinished data at once (GB)"),
    "d_max_temp_gb": ("Begrenzt, wie viel gleichzeitig parallel entpackt wird. Höher braucht mehr freien Platz.",
                      "Limits how much is extracted in parallel. Higher needs more free space."),
    "s_max_write_mb_s": ("Max. Schreibgeschwindigkeit (MB/s, 0 = unbegrenzt)", "Max. write speed (MB/s, 0 = unlimited)"),
    "d_max_write_mb_s": ("Bremst das Schreiben, damit die Platte für andere Programme frei bleibt.",
                         "Throttles writing so the disk stays usable for other programs."),
    "s_flush_interval_mb": ("Zwischenspeichern alle (MB, 0 = nur am Dateiende)", "Flush every (MB, 0 = end of file only)"),
    "d_flush_interval_mb": ("Große Dateien werden regelmäßig auf die Platte geschrieben statt am Ende auf einmal. Das verhindert lange „Hänger“ und hält den Windows-Cache klein.",
                            "Large files are flushed to disk regularly instead of all at once at the end. Prevents long 'hangs' and keeps the Windows cache small."),
    "s_low_space_warn_gb": ("Warnen unter (GB frei)", "Warn below (GB free)"),
    "d_low_space_warn_gb": ("Zeigt eine Warnung, wenn der freie Platz unter diesen Wert fällt.",
                            "Shows a warning when free space drops below this."),
    "s_sync_interval_mb": ("Journal-Intervall (MB)", "Journal interval (MB)"),
    "d_sync_interval_mb": ("Nach so vielen MB werden der Fortschritt gesichert und der Platz in der ZIP freigegeben. Kleiner bedeutet weniger Platzbedarf und weniger Wiederholung nach einem Absturz, größer weniger Schreibvorgänge.",
                           "After this many MB progress is saved and ZIP space released. Smaller = less space needed and less redone after a crash; larger = fewer writes."),
    "s_verify_written": ("Geschriebene Dateien nachprüfen (CRC)", "Verify written files (CRC)"),
    "d_verify_written": ("Liest jede fertige Datei noch einmal und vergleicht die Prüfsumme, bevor die ZIP-Daten freigegeben werden. Langsamer.",
                         "Reads every finished file back and compares its checksum before the ZIP data is released. Slower."),
    "s_auto_resume": ("Automatisch fortsetzen", "Resume automatically"),
    "d_auto_resume": ("Beim Programmstart werden unterbrochene Vorgänge sofort fortgesetzt. Nach „Platz voll“ oder einem vorübergehenden Fehler wird automatisch erneut versucht.",
                      "On program start interrupted jobs resume immediately. After 'disk full' or a temporary error it retries automatically."),
    "s_resume_after_reboot": ("Nach Neustart von Windows fortsetzen", "Resume after Windows restarts"),
    "d_resume_after_reboot": ("Legt nur während eines laufenden Vorgangs einen Autostart-Eintrag für Ihren Benutzer an. Er wird danach wieder entfernt.",
                              "Adds a per-user autostart entry only while a job is unfinished; it is removed afterwards."),
    "s_auto_optimize": ("Automatische Ressourcen-Optimierung", "Automatic resource optimization"),
    "d_auto_optimize": ("Startet weniger parallele Einträge, wenn RAM oder freier Platz knapp werden.",
                        "Starts fewer parallel entries when RAM or free space gets tight."),
    "s_show_monitor": ("Detaillierte Hardware-Anzeige", "Detailed hardware monitor"),
    "d_show_monitor": ("Zeigt CPU, RAM und Platte in Echtzeit an.", "Shows CPU, RAM and disk in real time."),
    "recovery_info": ("Wiederherstellungs-Info …", "Recovery info …"),
    "no_journal": ("Für diese ZIP gibt es keinen unterbrochenen Vorgang.", "There is no interrupted job for this ZIP."),
    "journal_invalid": ("Die Fortschrittsdatei ist beschädigt: {error}", "The progress file is damaged: {error}"),
    "journal_view": ("Fortschrittsdatei: {path}\nGültig (Prüfsumme ok): ja\nZiel: {target}\nFertig: {done} von {entries} Einträgen\nZuletzt fertig: {last}\nModus: {mode}\nAktualisiert: {updated}\nFormat: {format}",
                     "Progress file: {path}\nValid (checksum ok): yes\nTarget: {target}\nDone: {done} of {entries} entries\nLast finished: {last}\nMode: {mode}\nUpdated: {updated}\nFormat: {format}"),
    # ---- monitor / auto resume ----
    "monitor": ("Hardware-Auslastung", "Hardware utilization"),
    "m_speed": ("Tempo", "Speed"), "m_data": ("Entpackt", "Extracted"),
    "m_elapsed": ("Verstrichen", "Elapsed"), "m_eta": ("Restzeit", "Remaining"),
    "m_cpu": ("CPU (Programm / System)", "CPU (program / system)"),
    "m_ram": ("RAM (Programm / System)", "RAM (program / system)"),
    "m_disk": ("Platte (lesen / schreiben)", "Disk (read / write)"),
    "m_threads": ("Threads (aktiv / max.)", "Threads (active / max.)"),
    "m_free": ("Frei auf Ziel-Laufwerk", "Free on target drive"),
    "low_space_warn": ("⚠ Wenig freier Speicherplatz!", "⚠ Low free disk space!"),
    "auto_resume_countdown": ("Unterbrochener Vorgang „{name}“ wird in {sec} s automatisch fortgesetzt.",
                              "Interrupted job '{name}' resumes automatically in {sec} s."),
    "auto_resume_cancel": ("Nicht fortsetzen", "Don't resume"),
    "auto_retry_wait": ("Automatischer neuer Versuch in {sec} s …", "Retrying automatically in {sec} s …"),
    "resume_found": ("Es gibt einen unterbrochenen Vorgang:\n{name}\nJetzt fortsetzen?", "There is an interrupted job:\n{name}\nResume now?"),
}


def fmt_duration(sec) -> str:
    if sec is None or sec != sec or sec < 0:
        return "–"
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s_ = divmod(rem, 60)
    return f"{h}:{m:02}:{s_:02}" if h else f"{m}:{s_:02}"


def t(key: str, **kw) -> str:
    de, en = T.get(key, (key, key))
    text = de if LANG == "de" else en
    for k, v in list(kw.items()):
        if k in _SIZE_KEYS and isinstance(v, int):
            kw[k] = fmt_bytes(v)
    try:
        return text.format(**kw)
    except (KeyError, IndexError):
        return text


def msg(item) -> str:
    key, params = item
    return t(key, **params)
