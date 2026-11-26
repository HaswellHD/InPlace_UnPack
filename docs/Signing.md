# Signing the .exe

Without a signature, Windows SmartScreen shows "Windows protected your PC" and some antivirus programs get
suspicious. A code-signing certificate fixes most of that.

## Where to get a certificate

A self-made certificate doesn't help, Windows doesn't trust it. Some options (prices and rules change, check
the providers' sites):

- **SignPath Foundation**: free for open-source projects. You apply with the public repo and signing then runs
  in GitHub Actions.
- **Certum Open Source Code Signing**: small yearly fee, identity check with an ID.
- **Microsoft Trusted Signing**: monthly fee, cloud based, not available for individuals in every country.
- Regular OV/EV certificates from the big vendors: expensive. EV gets past SmartScreen right away.

Code-signing keys have to live on hardware (USB token, HSM or cloud) these days, so you'll rarely get a plain
`.pfx` file. Even signed, SmartScreen may warn for the first downloads until the certificate has some reputation.

## Signing with build.ps1

`build.ps1` signs the two .exe files (and the installer) as soon as one of these is set. Otherwise it signs
nothing.

```powershell
# certificate in the Windows store or on a USB token (thumbprint from certmgr.msc)
$env:SIGN_CERT_THUMBPRINT = "<thumbprint>"

# or a .pfx file
$env:SIGN_PFX = "C:\path\to\cert.pfx"; $env:SIGN_PFX_PASSWORD = "<password>"

# or any other signing tool; {file} is replaced with the file to sign
$env:SIGN_COMMAND = 'mysigner sign {file}'
```

Then run `build.cmd` (or `.\build.ps1`). `signtool.exe` comes with the Windows SDK. The signature gets a
timestamp, so it stays valid after the certificate expires.

To check: right-click the .exe → Properties → Digital Signatures, or
`Get-AuthenticodeSignature dist\Inplace-Unpack.exe`.

Never commit certificates or passwords. `*.pfx` and `*.p12` are in `.gitignore`.
