# Fon musiqasi (background music)

MP3s used by the shared player at `tgbot/templates/_music_player.html`,
sourced from Wikimedia Commons (converted from the original .ogg to .mp3
via ffmpeg, 96 kbps, for iOS/Safari WebView compatibility) and re-encoded
at low bitrate to keep page weight down.

| File | Source | License |
|---|---|---|
| `beethoven-moonlight.mp3` | [Beethoven_Moonlight_1st_movement.ogg](https://commons.wikimedia.org/wiki/File:Beethoven_Moonlight_1st_movement.ogg) — perf. Bernd Krueger | CC BY-SA 2.0 DE |
| `beethoven-fur-elise.mp3` | [FurElise.ogg](https://commons.wikimedia.org/wiki/File:FurElise.ogg) | CC0 |
| `bach-air-on-g-string.mp3` | [Air.ogg](https://commons.wikimedia.org/wiki/File:Air.ogg) — U.S. Air Force Strings | Public domain |
| `bach-prelude-c-major.mp3` | [Kimiko Ishizaka — WTC Book 1, Prelude No. 1 in C major, BWV 846](https://commons.wikimedia.org/wiki/File:Kimiko_Ishizaka_-_Bach_-_Well-Tempered_Clavier,_Book_1_-_01_Prelude_No._1_in_C_major,_BWV_846.ogg) | CC0 |
| `mozart-eine-kleine-nachtmusik.mp3` | [Mozart_Eine_kleine_Nachtmusik_KV525_Satz_1_Sonata.ogg](https://commons.wikimedia.org/wiki/File:Mozart_Eine_kleine_Nachtmusik_KV525_Satz_1_Sonata.ogg) | CC BY-SA 2.5 |
| `mozart-piano-sonata-11.mp3` | [Mozart_Eine_kleine_Nachtmusik_KV525_Satz_4_Rondo.ogg](https://commons.wikimedia.org/wiki/File:Mozart_Eine_kleine_Nachtmusik_KV525_Satz_4_Rondo.ogg) (renamed — Rondo movement, not actually Sonata No. 11) | CC BY-SA 2.5 |

The `TRACKS` array in `_music_player.html` must stay in sync with whatever
files actually live in this folder.
