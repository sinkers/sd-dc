# MCP server: cable-sizing

Cable sizing to AS/NZS 3008.1.1 and 1.2, IEC 60364-5-52, BS 7671 and the NEC,
exposed to Claude as tools.

Standard library only. JSON-RPC 2.0 over stdio, no SDK, so there is nothing to
`pip install` and nothing to keep in step with.

Python 3.9 or newer. That is the `python3` already on macOS and on any current
Linux, so in practice there is nothing to install. Both test suites were run on
3.9.6, 3.11.14, 3.12.12, 3.13.13 and 3.14.3, all green, so the floor is measured
rather than guessed.

- **Command** `python3 /Users/andrewsinclair/workspace/sd-dc/cable-sizing/mcp_server.py`
- **Transport** stdio, or HTTP for a remote client — see *Remote clients* below
- **Server name** `cable-sizing`
- **Tools** 5 &nbsp;|&nbsp; **Resources** 3

## Claude Code

Already registered in this project. To add it elsewhere:

```bash
# this project only
claude mcp add cable-sizing -- python3 /Users/andrewsinclair/workspace/sd-dc/cable-sizing/mcp_server.py

# every project for this user
claude mcp add --scope user cable-sizing -- python3 /Users/andrewsinclair/workspace/sd-dc/cable-sizing/mcp_server.py

# shared with the team, writes .mcp.json into the repo
claude mcp add --scope project cable-sizing -- python3 /Users/andrewsinclair/workspace/sd-dc/cable-sizing/mcp_server.py
```

Then check it:

```bash
claude mcp list          # expect: cable-sizing: ... - Connected
claude mcp get cable-sizing
claude mcp remove cable-sizing
```

Inside a session, `/mcp` lists the server and lets you inspect its tools.

## Remote clients

`mcp_server.py` speaks JSON-RPC over stdio, which only works where the client can
spawn the process. A hosted client cannot, so `http_mcp_server.py` serves the same
protocol over HTTP. Dispatch is `mcp_server.handle`, unchanged — stdio and HTTP
cannot give different answers to the same question because there is only one
implementation of the answer. Standard library only, like everything else here.

```bash
python3 http_mcp_server.py                    # http://127.0.0.1:8766/mcp
MCP_TOKEN=secret python3 http_mcp_server.py   # require a bearer token
```

One endpoint, `/mcp`, per the MCP Streamable HTTP transport. POST a JSON-RPC
request and get a response; a notification returns 202; a batch returns an array.
`GET /mcp` returns 405 — this server has no unsolicited messages to push, and
saying so beats leaving a client waiting on an empty stream. `GET /healthz`
returns the server version, tool and resource names and whether auth is on; it is
deliberately unauthenticated so a health check needs no credential.

`deploy/deploy.sh` puts it behind Caddy on the box that already runs the air twin,
as its own user on loopback. It exposes two ways in: the bearer token in an
`Authorization` header, and a token-in-path URL for clients whose connector UI
takes a URL and nothing else. The second makes the URL itself the credential —
as secret as the token, and it will appear in browser history and proxy logs.
The deploy does not print the token unless asked; read it from `/etc/dcable.env`
on the box, or re-run with `--show-token`.

## Claude Desktop

Edit the config file, then restart Claude Desktop completely (quit, not just
close the window).

- macOS `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "cable-sizing": {
      "command": "python3",
      "args": ["/Users/andrewsinclair/workspace/sd-dc/cable-sizing/mcp_server.py"]
    }
  }
}
```

If you already have an `mcpServers` block, add the `cable-sizing` key to it
rather than replacing the block.

On Windows use `"command": "py"` with `"args": ["-3", "<path>"]`, or the full
path to `python.exe`. Windows paths need escaped backslashes in JSON
(`"C:\\Users\\..."`) or plain forward slashes.

## Any other MCP client

Same two facts: run `python3 /Users/andrewsinclair/workspace/sd-dc/cable-sizing/mcp_server.py` and talk stdio. The server accepts
protocol versions `2025-06-18`, `2025-03-26` and `2024-11-05`, echoing back
whichever the client asks for and falling back to the newest if it asks for
something else.

Smoke test it without a client:

```bash
printf '%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18"}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | python3 /Users/andrewsinclair/workspace/sd-dc/cable-sizing/mcp_server.py
```

## Tools

| Tool | What it does |
|---|---|
| `size_cable` | Selects the smallest conductor that passes every check. **AS/NZS 3008.1.1 only** |
| `check_cable_size` | Checks a size you nominate against a rating you supply. **All five standards** |

### `formation` — state it, do not let it be guessed

Both sizing tools take `formation`, either `trefoil` or `flat_touching`. It is a
**second axis, independent of `method`**: the installation method picks the
rating column (a tray is *unenclosed touching* either way), while the formation
sets the reactance. Single-core cables in trefoil on an unenclosed-touching tray
are the normal case here.

Trefoil and flat differ by about 19 % in reactance. Left unstated the engine
falls back to `trefoil` for conduit and buried methods and `flat_touching`
otherwise, and raises a warning saying so — which can push a selection a size
larger than it needs to be. The response carries `installation.formation` and
`installation.formation_stated` so a reader never has to infer which happened.
Ignored for multicore.
| `list_standards` | The five profiles: reference ambient and soil model, installation methods with ids and diagram keys, voltage drop limits, IEC voltage factor, units, and whether the profile can select |
| `list_cable_types` | Catalogue families and the sizes held |
| `get_installation_diagram` | SVG of an installation arrangement |

### Why two sizing tools rather than one

Selecting a size needs a current-carrying capacity table. The only one held in
this repo is Nexans Australia data on the AS/NZS 3008.1.1 basis, so `size_cable`
works for that part alone.

For the other four, `check_cable_size` takes the size you want and the
`tabulated_rating_a` you read out of that standard's own table, then runs
everything else — design current, derating, operating temperature, voltage drop,
the adiabatic short-circuit check, earth sizing and earth fault loop impedance —
on that standard's rules, and returns every check with its margin.

Nothing derives an ampacity for a table that is absent. Ask `size_cable` for a
NEC size and it returns a tool **error** naming Table 310.16 as the thing to
read, rather than a plausible number. That is deliberate: re-referencing the
Australian ratings to a 30 °C basis with the ambient closed form runs optimistic
by up to 6.5 %, and an optimistic factor undersizes cable.

## Resources

| URI | Contents |
|---|---|
| `cable-sizing://standards` | All five standard profiles as JSON |
| `cable-sizing://cable-types` | Catalogue families and sizes |
| `cable-sizing://openapi` | OpenAPI 3.1 description of the equivalent REST API |

## Things to ask Claude once it is connected

- "Size a 250 kW three-phase feeder at 415 V over 85 m, 45 °C ambient, four
  grouped circuits, touching on a tray."
- "Same feeder but the load is 45 % third-harmonic. What happens to the neutral?"
- "I have 95 mm² on BS 7671 method C rated 270 A. Does it pass for a 90 kW load
  at 400 V over 60 m from a private supply?"
- "What is the difference between the Australian and New Zealand parts of
  AS/NZS 3008?"
- "Show me the installation arrangements IEC 60364-5-52 recognises."

## Relationship to the REST API

`mcp_server.py` and `server.py` both call `service.py`, so a person in the
browser and an agent over MCP get the same answer to the same question. The MCP
server does not need the web server running; they are independent front ends
over the same code.

