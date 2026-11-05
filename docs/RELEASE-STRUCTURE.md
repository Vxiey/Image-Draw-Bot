# Download and package layout

## Windows installer

`ImageDrawBot-<version>-Windows-x64-Setup.exe` installs the complete app and provides
an uninstaller. Python is bundled. Use this for normal installation and in-app
updates. Profiles/settings are stored separately from the installed program.

## Portable ZIP

`ImageDrawBot-<version>-Windows-x64.zip` contains an `ImageDrawBot` folder with
`ImageDrawBot.exe` and its supporting files. Extract everything, then launch the
EXE from that folder. Moving only the EXE or running it inside the ZIP will not
work reliably. Using the in-app installer from a portable build performs a
normal installation; it does not patch the portable folder.

## Source archive

GitHub's source archives contain Python code, build scripts and documentation.
They do not contain the packaged application. Use `Start.bat` with Python 3.11+
on Windows, or download the installer/portable release instead.

## Verification files

Each release includes `ImageDrawBot-<version>-SHA256.txt` and a manifest with file
sizes, version metadata and checksums. Hash verification checks file integrity;
it does not provide a trusted publisher signature. Published Windows downloads are unsigned.
The `ImageDrawBot-` naming applies to v1.0.144-rc1 and later packages; historical releases retain their original asset names.

[Downloads](https://github.com/Vxiey/Image-Draw-Bot/releases)
