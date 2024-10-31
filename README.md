# p2p-chat

Group project for Distributed Systems course.

Idea:

- Peer-to-Peer chat application
- CLI frontend
- Python
- gRPC

Minimum requirements:

- Can send messages (1:1) to other active clients (each client is a node) in the
  network

Required parts:

- Discovery, 2 approaches
  - Using other nodes (needs a node address to connect to network, and fetches
    other addresses through that node)
  - Using central discovery node (all nodes in network register to a discovery
    node when connecting to network)

Additional stuff:

- Network forms a group chat to which every client can send messages to
- Message replication to multiple nodes for fault tolerance
- Encrypted messages
- Authentication to the network
- Removing non-compliant clients from the network
