# Packaging as a Windows Executable

Using [PyInstaller](https://pyinstaller.org/) from inside the project's
virtual environment:

```bash
pip install pyinstaller
```

```bash
pyinstaller --noconfirm --windowed --name ElectromagnetVNAControl ^
    --add-data "config;config" ^
    src/main.py
```

(On PowerShell, use `` ` `` instead of `^` for line continuation, or put
it on one line.)

Notes:

- `--windowed` suppresses the console window (remove it while debugging
  a packaging problem so you can see tracebacks).
- `--add-data "config;config"` bundles the JSON command-profile files
  next to the executable (`src/config/app_config.py` resolves
  `config/` relative to the project root at dev time; when frozen by
  PyInstaller, copy your edited `config/` folder next to the produced
  `.exe` in `dist/ElectromagnetVNAControl/` if `--add-data` extraction
  doesn't resolve automatically for your PyInstaller version, and adjust
  `CONFIG_DIR` in `src/config/app_config.py` if you package as
  `--onefile` and need `sys._MEIPASS`-relative resolution instead).
- PyVISA-py is a pure-Python VISA backend and packages cleanly. If you
  use NI-VISA instead, the target machine needs NI-VISA's runtime
  installed separately -- PyInstaller cannot bundle that driver.
- Test the frozen `.exe` in Simulation Mode first, then against real
  hardware, before relying on it for an experiment.
- The output folder (`experiments/` by default, or wherever you set it
  in the Data tab) is created next to wherever you run the executable
  from -- run it from a writable location.

The result is a `dist/ElectromagnetVNAControl/` folder containing the
executable and all dependencies; copy that whole folder to deploy it.
