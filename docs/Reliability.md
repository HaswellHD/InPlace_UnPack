# What happens when things go wrong

Everything here is covered by the tests in `tests/` unless it says otherwise.

| What happens | What the tool does | Tests |
|---|---|---|
| Power cut, crash, process killed | Nothing was freed before file and journal were flushed. The next run continues from the last commit and redoes anything after it. | `test_resume.py` (crash at 4 points × 3 positions, double crash, real process kill), `test_modes.py` (every mode, resume in a different mode) |
| You pause or close the window | Running files are stopped, `.part` files removed, the finished part is committed. | `test_cancel_then_resume` |
| Disk gets full before a file | Checked before every file: it commits and stops cleanly. With auto resume it tries again once there's space. | `test_space_runs_out_during_run_then_resume` |
| Disk gets full while writing | `.part` removed, clean stop, can be resumed. | `test_disk_full_mid_write_removes_part_file` |
| Not enough space from the start | The check refuses and tells you how much is missing. | `test_space_precheck` |
| A file in the ZIP is damaged (CRC) | Balanced / Performance: kept exactly as stored, listed in `<zip>.damaged.txt`, carries on. Safe (or `keep_damaged` off): stops at that file, nothing after it is touched. | `test_damaged_entry_is_kept_and_run_continues`, `test_damaged_large_entry_streamed_is_kept`, `test_crc_error_stops_cleanly`, `test_safe_mode_still_stops_on_damage` |
| Written file doesn't match (Safe mode) | The read-back check fails, it stops before freeing anything. | `test_verify_written_detects_corruption` |
| Encrypted entry, unsupported compression | Refused before anything changes. | `test_encrypted_entry_refused_before_anything_is_destroyed`, `test_deflate64_refused` |
| Overlapping or broken entries | Refused before anything changes. | `test_overlapping_entries_refused` |
| Path tricks, reserved names | Cleaned up, nothing is written outside the target. | `test_zip_slip_stays_inside`, `test_reserved_and_illegal_names` |
| Junction or symlink in the target | Stops, writes nothing through it, the file stays in the ZIP. | `test_junction_inside_target_is_not_followed` |
| Same name twice, or only different in case | Renamed predictably (`a (2).txt`), nothing overwritten. | `test_duplicate_and_case_clashing_names_are_all_kept` |
| Files already in the target | Refused unless overwriting is allowed (read-only files handled). | `test_existing_files_need_permission` |
| An entry would overwrite the ZIP or journal | Refused. | `test_entry_cannot_overwrite_archive_or_journal` |
| Journal edited or damaged | Checksum doesn't match, refused with a clear message. | `test_journal_checksum_detects_tampering` |
| Journal belongs to a different ZIP | Fingerprint doesn't match, refused. | `test_journal_of_other_zip_is_refused` |
| Journal deleted after a partial run | Noticed (header already freed), refused with an explanation. | `test_lost_journal_is_detected` |
| Run started with 0.2.0 | 0.3 continues it. | `test_resume_a_run_started_by_version_0_2_0`, `test_v1_journal_is_still_accepted` |
| Split ZIP, crash after parts were deleted | Continues using the part sizes stored in the journal. | `test_split_crash_and_resume_after_parts_were_deleted` |
| A part of a split ZIP is missing | The check refuses. | `test_missing_part_is_reported` |
| File is open in another program | Clean stop with an explanation, auto retry if enabled. | manual |
| Low on RAM | Stops using RAM for small files, runs fewer at once, a `MemoryError` leads to a clean stop. | `test_low_ram_falls_back_to_streaming` |
| Temp folder on another drive | Copies to the target drive and flushes before renaming, cleans up after itself. | `test_temp_dir_other_volume_copies` |
| Restore points keep the freed space | Free space doesn't grow, the space check stops cleanly. | manual |
| Drive ignores flush commands | Can't be detected by software. Known limitation. | – |

## Files it leaves around while working

- `<name>.~iu<N>.part` next to the file being written (or `iu-<fingerprint>-<N>.part` in the temp folder).
  Removed on errors and on pause; after a hard crash the next run overwrites it, and old ones in the temp folder
  are cleaned up at start.
- `<zip>.unzip-progress` (and a short-lived `.tmp`) next to the ZIP while a job isn't finished. Removed at the end.
- `<zip>.damaged.txt` only if damaged files were found. Stays, so you can see which ones.
