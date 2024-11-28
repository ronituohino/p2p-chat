# p2p-chat

Group project for Distributed Systems course.

Kozheen Taher Esa  
Joonas Ahovalli  
Roni Tuohino

A peer-to-peer (P2P) chat application. The main functionality is creating
networks (Networks / Groups / Chats), which can be thought of as group chats. A
client (Node) can join a network by contacting the leader of the network. The
leaders of each network are elected from the nodes of the network using election
algorithms. The leaders of all networks are stored in a central Node Discovery
Service (NDS) through which a Node can discover existing networks and the
addresses of the leaders.

## Todo

- Change `receive_message` in ui to accept a list of messages, which refreshes the entire log
- Add toasts to ui, error handling, start looking into nds stuff

## Development

Make sure you have the [uv](https://docs.astral.sh/uv/) package manager
installed.

Code is formatted and linted using [ruff](https://docs.astral.sh/ruff/). VS Code
has a nice extension for it, be sure to enable it as the default Python
formatter.

Install dependencies for services:

```
cd nds
uv sync
```

```
cd client
uv sync
```

### Client ui development

For effective ui development, launch textual development console:

```
uvx --from textual-dev textual console --port 7654 -x SYSTEM -x EVENT -x DEBUG -x INFO -x LOGGING
```

Textual logs can also be enabled by leaving out the "-x (CLASS)" clauses. More
info on the
[devtools here](https://textual.textualize.io/guide/devtools/#devtools). Textual
can also be run on the browser, which is quite amazing.

After launching the dev console, start the ui itself in a separate terminal

```
uvx --from textual-dev textual run --dev --port 7654 ./client/ui.py
```

`print()` statements will be logged on the dev console with this setup.

### Tests

Run in directory of the service

```
uv run pytest
```