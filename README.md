# p2p-chat

Group project for Distributed Systems course.

[Kozheen Taher Esa](https://github.com/astranero)  
[Joonas Ahovalli](https://github.com/joonas-a)  
[Roni Tuohino](https://github.com/ronituohino)

A peer-to-peer (P2P) chat application. The main functionality is creating
networks (Networks / Groups / Chats), which can be thought of as group chats. A
client (Node) can join a network by contacting the leader of the network. The
leaders of each network are elected from the nodes of the network using election
algorithms. The leaders of all networks are stored in a central Node Discovery
Service (NDS) through which a Node can discover existing networks and the
addresses of the leaders.

## TODO

- Leader election system refactor and integration (DONE)
- Message reordering with logical clocks, heartbeat system carries this info (DONE)
- Ping NDS function (refresh button / thread with timer) so that new group info is fetched  (DONE)

Optional:
- Fix tests (NO TIME TO DO THIS)
- 2-way handshake when adding NDS to assure that client can accept incoming requests as well
  - Right now you can start the group chat and do whatever, but you will get no info from others if for example firewall blocks the RPC calls


## Code Structure and Documentation

This project adopts a modular design to enhance debugging, testing, and scalability. The source code is organized into directories based on functionality, with inline comments at critical points to clarify design principles.

### Key Components

- **`client/service/`**: Core services such as leader election, message broadcasting, heartbeat, and synchronization logic.
  - **`leader_election.py`**: Implements the Bully Algorithm for leader election.
  - **`synchronization.py`**: Manages synchronization using logical clocks.

- **`client/nds/`**: Node Discovery Service (NDS) implementation, responsible for group discovery and leader identification.

- **`client/ui/`**: User interface implementation containing logic for creating groups, adding members, and broadcasting messages.

- **`docs/`**: Project documentation files.

- **`tests/`**: Located under the `tests/` directory. Due to refactoring and time constraints, tests are currently non-functional.

---

## Feature Overview

| **Feature**           | **File/Module**                       | **Details**                                                                                          |
|-----------------------|---------------------------------------|------------------------------------------------------------------------------------------------------|
| **Leader Election**   | `client/service/leader_election.py`   | Implements the modified Bully Algorithm and its functionality.                                      |
| **Synchronization**   | `client/service/synchronization.py`   | Handles logical clock-based message ordering and state recovery.                                    |
| **Fault Tolerance**   | `client/service/heartbeat.py`         | Implements heartbeat monitoring and failure detection.                                              |
| **Scalability**       | `client/nds/nds.py`                   | Demonstrates NDS scalability and its role in minimizing centralization.                             |
| **Messaging Protocol**| `client/service/messaging.py`         | Implements JSON-RPC for broadcasting and leader coordination.                                       |

## Deployment

Software is deployed on the VMs provided by the faculty.  
These can be connected via SSH.  
The NDS needs to be on one of the computers, and clients can be run remotely as
well.

To connect to a faculty VM

```
ssh -J <UoH username>@<jump proxy> <UoH username>@<vm>
```

Jump proxies:
- melkki.cs.helsinki.fi

VMs: 
- svm-11.cs.helsinki.fi
- svm-11-2.cs.helsinki.fi
- svm-11-3.cs.helsinki.fi

e.g.

```
ssh -J roturo@melkki.cs.helsinki.fi roturo@svm-11.cs.helsinki.fi
```

Enter UoH account password when prompted (usually twice), once for the jump
proxy, and once for the vm itself.

Clone the git repo in your home folder (where you automatically end up after
login)

```
git clone https://github.com/ronituohino/p2p-chat.git
```

```
cd p2p-chat
```

Continue with the `Requirements` instructions.

## Requirements

Install the [uv](https://docs.astral.sh/uv/) package manager installed if not
already present

```
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Either close and reopen the terminal, or run

```
source $HOME/.local/bin/env
```

Continue with either the `Running the software` instructions, or the
`Development` instructions.

## Running the software

Make sure the repo is up to date

```
git pull
```

Install dependencies 

```
uv sync
```

To run NDS, note that a client should not be run on the same computer as NDS, because IP addresses could get fumbled.

```
uv run nds.py
```

To run client

```
uv run main.py <name>
```

### Note about using the VMs

If you set up the NDS on a VM, to connect to it from your own laptop, you have
to use a proxy. We don't really know how to do it well, so it's recommended that
you SSH into another VM and use a client from there.

## Development

Code is formatted and linted using [ruff](https://docs.astral.sh/ruff/). VS Code
has a nice extension for it, be sure to enable it as the default Python
formatter.

### Tests

Run in directory of the service

```
uv run pytest
```
