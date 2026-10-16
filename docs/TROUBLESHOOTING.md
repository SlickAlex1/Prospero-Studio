# Troubleshooting

## Antivirus removes files

**Symptoms**
- `relinker.exe cannot be opened (Permission denied); it may have been quarantined by antivirus`
- The build log ends in the middle of a step, or the console closes during the build
- `eboot.exe`, `anyps5_folder.py` or `tools\unwrap_self.py` disappear after a build

**Cause.** Some antivirus products, Bitdefender in particular, flag the official AnyPS5 `relinker.exe`
with a generic detection (seen: `Trojan.GenericKD.*`). Their behaviour monitoring then treats the whole
chain as one threat: it kills Python and the console that started the relinker, and removes the scripts
and the generated `eboot.exe`.

**Check the relinker is genuine.** Compare its SHA-256 with the `digest` shown for the asset on the
[AnyPS5 releases page](https://github.com/boykopovar/AnyPS5/releases):

```powershell
Get-FileHash .\relinker-v0.1.2.exe
```

`update_anyps5.py` already refuses downloads whose checksum does not match.

**Fix (Bitdefender).**
1. *Protection -> Antivirus -> Settings -> Manage exceptions*: add the tool folder **and** the folder your
   game builds go to, with every scan type enabled, including **Advanced Threat Defense**.
2. *Protection -> Quarantine*: restore the removed files, or run `python update_anyps5.py --force` and
   download this repository again.
3. Restart Windows if a file stays locked ("Access is denied" even though it is listed).

Turning protection off temporarily is not enough: it switches itself back on and removes the files later.

## The game aborts with `param.json kernel.flexibleMemorySize must be a positive multiple of 16 KiB`

Some dumps declare `"flexibleMemorySize": 0`. The tool removes the value from the copy in
`app0\sce_sys\param.json` during the build, so AnyPS5 uses its default. Rebuild with the current version
of the tool.

## The console window closes immediately

Start the tool by double-clicking `Prospero Studio.pyw` (the window shows everything in its *Log* tab), or run
it from Command Prompt: `python anyps5_folder.py`. The build log is also saved as
`<Game>_AnyPS5_setup.log` beside the build folder.

If **`eboot.exe`** closes immediately, start it from a console (`play.bat` keeps the window open) and read
the last lines. Rebuild with **Startup dependency diagnostics** enabled if it reports nothing.

## The game freezes after a menu or scene change

Typical log: `Forcing call to sce::Agc::suspendPoint to avoid TRC R5089 breach`, repeated every few
seconds. This message comes from the game itself (Unity) and means no frames are being produced.

1. In *Runtime settings*, enable **Store GPU results at each flip** (`APS5_STORE_AT_FLIP=1`) and press
   **Play**. It writes GPU results back to game memory every frame, which helps titles that reuse memory
   after GPU work.
2. If it still freezes, set **Timed hang dump** (`APS5_HANG_DUMP_SECS`) to a few seconds after the freeze
   starts. The game then prints every thread's stack and stops: include that output in an
   [AnyPS5 issue](https://github.com/boykopovar/AnyPS5/issues).

## `subgroup capability 61 is unsupported for shader stage 128`

Also: `device does not support VK_EXT_mesh_shader`, or the start-up line
`Vulkan features ... mesh=0`.

**Cause.** The game uses the PS5's NGG/primitive-shader geometry, which AnyPS5 runs as Vulkan **mesh shaders**
(stage 128 is the mesh stage, capability 61 is basic subgroup operations). The selected GPU has no mesh
shader support, so AnyPS5 stops. There is no fallback for these games; no setting or rebuild changes it.

**GPUs with mesh shaders:** NVIDIA GTX 16xx and RTX 20 series or newer, AMD RX 6000 series (RDNA 2) or newer,
Intel Arc. GPUs without them, e.g. NVIDIA GTX 10xx (Pascal) and older, Intel HD/UHD integrated graphics,
can still run games that do not use this kind of geometry (in testing: Animal Well and Blue Prince ran on a
GTX 1050 Ti, Stray did not).

If your PC has two GPUs and the wrong one is selected, set **GPU (part of its name)** (`ANYPS5_GPU`).

## The game runs slowly although the GPU is not fully used

The frame rate is shown in the game window's title (`FPS: ...`).

1. **Log output.** AnyPS5 writes and flushes a log line for many events. In a console window every flush is
   slow and holds the game back. Keep *Runtime settings -> Game log output* on **Log file** (the default;
   the log goes to `anyps5_run.log` in the build folder). Measured with Animal Well: 17.8 -> 18.6 FPS
   average, with fewer dips.
2. **CPU-bound GPU emulation.** On a PS5 the CPU and GPU share memory. On a PC, AnyPS5's GPU driver
   (`libSceAgcDriver.prx`) has to find what the game changed and hand it to the GPU, and translate the PS5's
   GPU commands to Vulkan, largely on one CPU thread. With an older CPU this caps the frame rate while the GPU
   waits. Measured with Animal Well on an i7-6700 + GTX 1050 Ti: ~19 FPS in every present mode, the
   game process using one CPU core's worth of time spread over three threads that take turns
   (AGC driver ~54%, game main loop ~21%, video output ~13%), the busiest thread inside
   `GuestArenaCollectWrites`.
   No setting changes this. What helps: a CPU with faster single cores, and newer AnyPS5 releases, which
   Prospero Studio installs automatically when they are published.
3. *Present mode* (`ANYPS5_PRESENT_MODE`) did not change the frame rate in that test (fifo 19.0,
   mailbox 18.0, immediate 18.8 FPS); leave it at `fifo`.

## A setting is greyed out

The installed AnyPS5 release does not contain it yet; it exists only in newer source. Click
**Check for updates now**; it becomes available once AnyPS5 publishes a release that includes it.

## `FAIL: Ambiguous guest dependency name: <module>.prx`

The dump contains a second copy of a module in the same folder, usually a backup left by the dumping or
conversion tool (`libSceFace.prx.esbak` beside `libSceFace.prx`). The relinker reads every file in
`sce_module`, sees two modules with the same name and stops. Prospero Studio skips files whose extension
ends in `bak` (`.bak`, `.prxbak`, `.binbak`, `.esbak` ...) when copying the game; if you still see the error,
look for another duplicate of the named module in the game's module folders and leave only one.

## `Skipping SELF container` in the relinker output

A bundled module is still a SELF/fSELF container. The tool unwraps decrypted containers automatically; a
module that stays wrapped is usually **encrypted**, and `unwrap_self.py` refuses it. Use a decrypted dump.

## `eboot.bin did not become ELF`

The game's executable is encrypted or compressed. This tool cannot decrypt games; the dump must already be
decrypted.

## The game picks the wrong GPU

On PCs with integrated and dedicated graphics, set **GPU (part of its name)** (`ANYPS5_GPU`) to part of the
dedicated GPU's name, e.g. `NVIDIA` or `RTX`. The available names are printed at start-up in the
`Physical device candidate` lines.

## The game crashes while listing GPUs

The Microsoft *OpenCL, OpenGL and Vulkan Compatibility Pack* installs Mesa Dozen, which can crash some D3D12
drivers. If you have another Vulkan driver, set **Disable Vulkan drivers** (`VK_LOADER_DRIVERS_DISABLE`) to
`*dzn*`.

## `sceKernelMapDirectMemory` ... `commit direct memory pages`

Windows ran out of commit space (RAM + page file). Enlarge the page file or close other programs.
