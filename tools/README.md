# tools/

`update_anyps5.py` fills this folder from the upstream projects and keeps it up to date:

| Script | From | Used for |
|---|---|---|
| `unwrap_self.py` | [AnyPS5](https://github.com/boykopovar/AnyPS5/tree/main/tools) `main` | Turning decrypted SELF/fSELF containers (`eboot.bin`, `*.prx`) into clean ELF files |
| `self_to_elf.py` | [PS5-SELF-TO-ELF](https://github.com/julienlgy/PS5-SELF-TO-ELF) by julienlgy | Alternative SELF/PRX converter that also repairs broken ELF section tables |
| `import_audit.py` | AnyPS5 `main` | Listing which system functions a converted game imports and whether AnyPS5 provides them |
| `nid_names.py`, `progress.py` | AnyPS5 `main` | Helpers `import_audit.py` needs |

These files belong to their authors and are not stored in this repository (see [NOTICE](../NOTICE)).
Choose the converter in the window (*Build options -> SELF converter*) or with
`anyps5_folder.py --converter-kind unwrap_self|self_to_elf|auto`.
