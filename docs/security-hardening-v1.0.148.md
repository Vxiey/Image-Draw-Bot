# Windows release security note

Mobile Preview does not share the original image by default. The drawing
preview and safety map are still shared over unencrypted HTTP while Mobile
Preview is active. Use it only on a trusted private network, and leave it off
when working with sensitive images.

A SHA-256 match confirms that a file matches the expected bytes. It does not
authenticate the publisher when the file and its digest come from the same
release channel. Check for a trusted publisher signature independently.

A clean build, passing package checks, and a successful install or upgrade do
not establish an antivirus verdict. Review any detection against the exact
setup, application, or bundled file digest. Do not disable antivirus to install.
