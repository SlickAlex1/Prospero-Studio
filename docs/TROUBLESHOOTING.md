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

## A setting is greyed out

The installed AnyPS5 release does not contain it yet; it exists only in newer source. Click
**Check for updates now**; it becomes available once AnyPS5 publishes a release that includes it.

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
