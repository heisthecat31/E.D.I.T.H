E.D.I.T.H - the satellite for the Echo VR lobby
================================================
Even Dead I'm The Hero (a joke from Spider-Man: Far From Home).

Install
  1. Extract this whole zip somewhere (not inside the game folder).
  2. Close Echo VR.
  3. Run install.bat. It finds Echo VR through Spark's settings and asks you to confirm,
     or asks you to drag the Echo VR folder into its window.
  4. Start Echo VR and go to the lobby.

What it installs (into <Echo VR>\bin\win10\plugins)
  EDITH.dll            her behaviour
  EDITH.ini            her settings (kept if you already have one; the new default is EDITH.ini.new)
  EDITH\               her lobby data (mpl_lobby_b2.edith), loaded without changing the game's files
  EdithVoice\          her voice lines
  If the game has no plugins folder yet, it also installs the plugin loader (dbgcore.dll).

Talking to her
  She listens through your microphone (your default recording device). While you're in her lobby
  and not muted on Echo's voice chat, what you say is sent to her server, where it's turned into
  text so she can answer; nothing is sent while you're muted or away from her lobby. To turn her
  ears off, put "mic=off" under [satellite] in EDITH.ini. Say "Edith" to get her attention.

Not compatible with nEVR: the installer checks for it and stops without changing anything.

Uninstall
  Run uninstall.bat. It removes everything above except the plugin loader, which your other
  mods may use.
