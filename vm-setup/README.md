# VM setup — headless FreeCAD

A FreeCAD VM with an XML-RPC server, so scripts and agents can build geometry
without a desktop.

Several components need it: [`../piping/`](../piping/),
[`../cooling-model/`](../cooling-model/) and
[`../cable-tray-ezystrut/`](../cable-tray-ezystrut/) all import `FreeCAD` and
`Part` directly and cannot run in a plain interpreter.

## Start here

| File | What |
|---|---|
| [`INSTALL.md`](INSTALL.md) | **build the VM** — cloud-init, provisioning, SSH |
| [`AGENT_INSTRUCTIONS.md`](AGENT_INSTRUCTIONS.md) | how an agent drives it once running |
| `create-vm.sh` | Parallels VM creation |
| `provision.sh` | installs FreeCAD and the RPC server on first boot |
| `freecad_rpc_server.py` | the XML-RPC server itself |
| `cloud-init/` | user-data templates |

## Set a password before you build it

`INSTALL.md` carries `<GENERATED-PASSWORD>` placeholders rather than a real one.
Generate and substitute:

```bash
LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 24; echo
```

The VM authenticates by SSH key; the password is only a console fallback. If you
do not need console access, set `ssh_pwauth: false` and drop the `chpasswd`
block.

## Not in the critical path

`PLAN.md` §4 deliberately keeps FreeCAD out of the design loop: the layout engine
compiles to glTF and IFC directly, and emits a FreeCAD script only when someone
wants STEP or detailed piping solids. Headless FreeCAD is too slow and too
fragile to sit inside an iteration loop.
