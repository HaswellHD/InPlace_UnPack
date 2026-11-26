# Security

## Which versions get fixes

Only the latest release. Updating is safe: newer versions can pick up runs that older ones started.

## Found a security problem?

Please don't open a public issue for it. Use GitHub's
[private vulnerability reporting](https://github.com/HaswellHD/InPlace_UnPack/security/advisories/new) instead.
I'll try to answer within a week. A small generated archive that shows the problem (not a private file) and
your Windows version help a lot.

## What it protects against

Every archive is treated as untrusted:

- Path tricks like `..`, absolute paths, drive letters, UNC paths, reserved names (`CON`, `NUL`, ...) or odd
  separators. Every output path is cleaned up in `names.py` and checked to stay inside the target folder.
- Junctions or symlinks that already exist in the target folder. They're detected and the run stops.
- Broken or manipulated archives: overlapping entries, missing headers, sizes that don't add up. Those are
  rejected before anything changes. A CRC error either stops the run or keeps that one file as-is and lists it.
- Overwriting: existing files are only replaced if you allow it, and an entry can never overwrite the ZIP or
  its journal.
- Other programs writing to the ZIP mid-run: it's opened so that nobody else can write to it.

What it doesn't fully cover:

- Someone on the same PC creating a junction in the target folder in the split second between the check and
  the write. Since the tool runs without admin rights, that can't give them more access than they already have.
- Classic "zip bombs" (tiny file, enormous output) are caught by the space check, not by a ratio limit.

## Things it never does

- Ask for admin rights.
- Turn off Defender or other security software, or ask you to, or add exclusions.
- Connect to the internet or collect any data.
- Change system settings. The only things it writes outside its own folders are optional and per user:
  an autostart entry while a job is unfinished (only if you enable *Resume after Windows restarts*) and the
  Explorer right-click entry (only if you enable it).
