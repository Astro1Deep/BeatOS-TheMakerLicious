# Projects and expansions library — BeatOS 3.8.0

[Español](../BIBLIOTECA_PROYECTOS_EXPANSIONES.md) · [English complete manual](MANUAL_COMPLETO.md)

BeatOS project and expansion cards provide a way to **inspect source files without overwriting them**, then load supported Drum material into a **working copy of the 16-pad rack**. “Show in Finder” and “Copy path” refer to the original file; those actions do not relocate source audio.

## Projects

Search using multiple words, order by name, tempo or sample-reference count, and distinguish XPJ files under **Projects/** from kits and other projects. Project cards display **up to 24 items per page**. In-page reload retains applicable filters, page selection and the rack working copy; it does not reindex the disk.

INDEX_OK, ATTENTION and ERROR refer to indexer checks of file references. They **cannot prove a complete physical project load** or certify all pad layers. The importer checks selected Drum track references separately.

## Expansions

**View programs** opens available XPM programs. **View projects** filters to XPJ files inside the exact expansion folder (including nested demos/templates). **View all projects** returns to the full library. **Browse samples** scopes the sample browser to the exact indexed expansion directory and allows preview/assignment. Clearing that scope does not wipe the rack.

The program browser supports search, type filters, reload and sample preview. **Drum** programs can be edited as a copy. **Keygroup** requires the native MPC engine for its full behavior. Previous, next and random kit navigation in the rack apply to eligible Drum programs, not Keygroups.

A modal maintains search/type when reloading the same expansion. Escape closes it and Tab navigation stays within the dialog; typing must not trigger pads behind the modal.

## Continuing with the rack and Teenage Engineering hub

Return to the source project or expansion catalog without reimporting a still-active copy. Changing tracks or loading a different source **replaces the working copy**—export your changes first. Every kit export uses the first active layer and **only 16 currently visible pads**, not the complete original MPC project arrangement, effects or sequences.

The PO/EP hub can use those pads for a PO-33/PO-133 audio reel or EP-133 interchange kit. Server-backed operations show progress; filtering and browsing do not grant additional network permissions or alter the original music.

After updating BeatOS source code, reload the **whole browser page**. Reloading only the project cards does not update JavaScript.