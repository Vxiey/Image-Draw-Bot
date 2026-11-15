# Bildformat

Formatet läses från bildens innehåll, inte filändelsen. PNG, JPEG, WebP och BMP har testats. Appen visar format, bredd × höjd och om bilden faktiskt innehåller transparenta pixlar. PNG betyder inte automatiskt att bakgrunden är transparent.

Filer, filsläpp och nedladdade bild-URL:er använder samma bildläsare. Inklistrade bildpixlar visas som Clipboard / decoded pixels om originalformatet saknas. En ny inklistrad bild nollställer också föregående motivruta.

5 nya formattester och 12 motivtester passerar. Windows-gränssnittet är inte verifierat här. Starta med Start.bat efter att hela ZIP-filen packats upp.

### Network image import

Import public image links over HTTPS. Private-network hosts, cleartext HTTP, proxy environment settings, credentials embedded in web URLs, and UNC/device paths are not supported by image import. For a trusted intranet image or network-share file, copy it to a local folder before importing.

The raw UNC/device-path check is not a guarantee against OS-managed network drives or filesystem redirects. DNS uses the operating system resolver, which can block until it returns; cancellation and the download deadline are checked before and after resolution, not during the resolver call.
