# Example settings

`settings.example.json` lists every setting with the values of the Balanced mode.

```powershell
inplace-unpack-cli archive.zip target --config examples\settings.example.json
```

Keys it doesn't know are ignored, missing ones come from the chosen `mode`, and values outside the limits get
clamped (see `LIMITS` in `inplace_unpack/settings.py`). The app itself saves to
`%APPDATA%\Inplace-Unpack\settings.json`.

Want to keep using your PC normally during a long run? Something like this:

```json
{ "mode": "balanced", "max_write_mb_s": 50, "priority": "idle" }
```
