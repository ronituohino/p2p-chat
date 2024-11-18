# p2p-chat

Group project for Distributed Systems course.

Kozheen Taher Esa  
Joonas Ahovalli  
Roni Tuohino  

A peer-to-peer (P2P) chat application. The main functionality is creating
networks (Networks / Groups / Chats), which can be thought of as group chats. A client
(Node) can join a network by contacting the leader of the network. The leaders of each
network are elected from the nodes of the network using election algorithms. The leaders of
all networks are stored in a central Node Discovery Service (NDS) through which a Node
can discover existing networks and the addresses of the leaders.

## Discussion for next week

- Should we develop in [containers](https://docs.astral.sh/uv/guides/integration/docker/#developing-in-a-container)?  
Could be nice because we could do a docker-compose file with nds and like 3 copies of node, and they would update when code changes.

- ruff & config

- uv build-system, scripts

## Development

Make sure you have the [uv](https://docs.astral.sh/uv/) package manager installed.

Code is formatted and linted using [ruff](https://docs.astral.sh/ruff/).
VS Code has a nice extension for it, be sure to enable it as the default Python formatter.

Install dependencies for nds:
```
cd nds
uv sync
```

Install dependencies for client:
```
cd client
uv sync
```

### Client ui development

For effective ui development, launch textual development console:

```
uvx --from textual-dev textual console --port 7654 -x SYSTEM -x EVENT -x DEBUG -x INFO -x LOGGING
```

Textual logs can also be enabled by leaving out the "-x (CLASS)" clauses. More info on the [devtools here](https://textual.textualize.io/guide/devtools/#devtools). Textual can also be run on the browser, which is quite amazing. 

After launching the dev console, start the ui itself in a separate terminal

```
uvx --from textual-dev textual run --dev --port 7654 ./client/modules/ui/ui.py
```

`print()` statements will be logged on the dev console with this setup.