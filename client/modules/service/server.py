import shelve
import random
from concurrent import futures
import socket
import uuid
import logging

import gevent
import gevent.pywsgi
import gevent.queue
from tinyrpc.protocols.jsonrpc import JSONRPCProtocol
from tinyrpc.transports.wsgi import WsgiServerTransport
from tinyrpc.server.gevent import RPCServerGreenlets
from tinyrpc.dispatch import RPCDispatcher
from tinyrpc.protocols.jsonrpc import JSONRPCProtocol
from tinyrpc.transports.http import HttpPostClientTransport
from tinyrpc import RPCClient

class Response:
    def __init__(self, success: bool, message: str, data=None):
        self.success = success
        self.message = message
        self.data = data

    def __repr__(self):
        return f"Response(success={self.success}, message='{self.message}', data={self.data})"

    def to_dict(self):
        return {
            "success": self.success,
            "message": self.message,
            "data": self.data,
        }


dispatcher = RPCDispatcher()

self_ip = "127.0.0.1"
self_name = "bob"
nds_server = shelve.open(f"discovery_server.db", writeback=True) 
channel_port = 50001
groups = shelve.open(f"groups.db", writeback=True) 
clients = []
message_store = shelve.open(f"messages.db", writeback=True)
received_messages = set()

#group_id: { 
#   group_name, 
#   self_id,
#   leader_id, 
#    peers: {
#        id: {name, ip}
#        }
#    }



def serve(port):
    transport=WsgiServerTransport(queue_class=gevent.queue.Queue)
    wsgi_server = gevent.pywsgi.WSGIServer(('127.0.0.1', port), transport.handle)
    gevent.spawn(wsgi_server.serve_forever)
    rpc_server = RPCServerGreenlets(transport, JSONRPCProtocol(), dispatcher)
    rpc_server.serve_forever()


def create_rpc_client(peer_ip, peer_port=50001):
    rpc_client = RPCClient(
        JSONRPCProtocol(),
        HttpPostClientTransport(f"http://{peer_ip}:{peer_port}/")
    )
    return rpc_client

def store_message(msg, msg_id, group_id, source_id):
        """Store a message locally."""
        if group_id not in message_store:
            message_store[group_id] = []
        message_store[group_id].append({
            "msg_id": msg_id,
            "source_id": source_id,
            "msg": msg
        })
        message_store.sync() 
    

def get_messages(group_id):
    """Retrieve all messages for a given group_id."""
    messages = message_store.get(group_id, [])
    return messages


def get_group_info(group_id):
    """Return all information related to the group"""
    group = groups.get(group_id, {})
    if not group:
        raise ValueError(f"Group with ID {group_id} does not exist.")

    return ( 
        group.get("group_name",""), 
        group.get("self_id",""), 
        group.get("leader_id",""), 
        group.get("peers", {})
    )


@dispatcher.public
def fetch_groups():
    """Returns possible groups to join"""
    groups = []
    for client in nds_server:
        remote_server = client.get_proxy()
        groups.append(remote_server.get_groups())
    return groups


def add_nds(nds_ip):
    """add nds client"""
    rpc_client = create_rpc_client(nds_ip)
    nds_server[nds_ip]=rpc_client
    nds_server.sync() 


def request_to_join_network(leader_ip, group_id):
    rpc_client = create_rpc_client(leader_ip)
    result = remote_server.join_network(group_id, self_ip, self_name)
    if response.success:
        groups[group_id] = {
            "group_name": response.group_name,
            "self_id": response.assigned_peer_id,
            "leader_id": response.leader_id,
            "peers": response.peers
        }

        groups.sync() 
        logging.info(f"Joined network with Peer ID: {response.assigned_peer_id}")
    else:
        logging.errror("Failed to join network")


def is_group_leader(leader_id, self_id):
    return leader_id == self_id


def create_group(group_name, nds_id):
    """Create a new network and register it with NDS, making this peer the leader."""
    rpc_client = nds_server.get(nds_id, False)
    if not rpc_client:
        raise ValueError(f"NDS server with ID {nds_id} does not exist.")

    remote_server = rpc_client.get_proxy()
    response = remote_server.create_group(
        leader_ip=self_ip, group_name=group_name
    )

    if response.success:
        group_id = response.group_id
        groups[group_id] = {
            "group_name": group_name,
            "self_id": 0,
            "leader_id": 0,
            "peers": {
                0: { "name": self_name, "ip": self_ip}
            },
        }
        groups.sync() 
        logging.info(f"Created network {group_name} with ID: {group_id}")
    else: 
        return -1


@dispatcher.public
def join_network(group_id, peer_ip, peer_name):
    group_name, self_id, leader_id, peers = get_group_info(group_id)
    if not is_group_leader(leader_id, self_id):
        return Response(success=False, message="Only leader can validate users.")


    for peer in peers.values():
        if peer["name"] == peer_name:
            return Response(success=False, message="Peer name already exists in the group.")
        if peer["ip"] == peer_ip:
            return Response(success=False, message="Peer IP already exists in the group.")

    assigned_peer_id = max(groups[group_id]["peers"].keys(), default=0) + 1
    peers[assigned_peer_id] = {"name": peer_name, "ip": peer_ip} 
    logging.info(f"Peer {assigned_peer_id} joined with IP {peer_ip}")

    groups.sync() 
    return Response(success=True, message="Joined a group successfully", data={"group_name": group_name, "peers": peers, "assigned_peer_id": assigned_peer_id, "leader_id": leader_id})


@dispatcher.public
def leave_network(group_id, peer_id):
    """Handles leaving the network"""        
    group_name, self_id, leader_id, peers = get_group_info(group_id)
    if not is_group_leader(leader_id, self_id):
        return Response(success=False, message="Only leader can delete users.")

    for peer_id, peer_info in peers.items():
        peers.pop(peer_id)
        logging.info(f"Peer {peer_id} left the network")
        groups.sync() 
        return Response(success=True, message=f"Successfully left the network")
    return Response(success=False, message="Peer not found")


def send_message(msg, group_id, source_id, destination_id):
    """Broadcast a message to all peers using flooding."""
    msg_id = str(uuid.uuid4())
    if destination_id == -1:  
        logging.info(f"Broadcasting message {msg_id} from {source_id}: {msg}")
        message_broadcast(group_id, msg_id, source_id, msg)
        return Response(success=True, message="Message broadcasted")
    else:
        try:
            group_name, self_id, leader_id, peers = get_group_info(group_id)
            ip = peers.get(destination_id, "")
            if ip:
                destination_client = create_rpc_client(ip)
            else: return "Ip addr. not found"
        except KeyError as e:
            return f"Error: {e}"

        if destination_client:
            send_message_to_peer(destination_client, msg, msg_id, group_id, source_id, destination_id)
            return Response(success=True, message="Message sent")
        else:
            return Response(success=False, message="Destination peer not found")


def message_broadcast(msg, msg_id, group_id, source_id):
    """broadcast a message to all peers."""
    group_name, self_id, leader_id, peers = get_group_info(group_id)
    if not peers:
        logging.info(f"No peers found for group {group_id}.")
        return 

    print(f"Broadcasting message to peers: {peers}")
    for peer_id, peer_info in peers.items():
        if peer_id == source_id or peer_id == self_id:
            continue
        peer_ip = peer_info.get("ip")
        rpc_client = create_rpc_client(peer_ip)
        send_message_to_peer(rpc_client, msg, msg_id, group_id, source_id, peer_id)


def send_message_to_peer(client, msg, msg_id, group_id, source_id, destination_id=-1):
    """sends a message to a given peer""" 
    remote_server = client.get_proxy()
    response = remote_server.receive_message(msg, msg_id, group_id, source_id, destination_id)
    if response.success:
        logging.info(f"Message sent, here is response: {response.message}")
    else:
        logging.info(f"Failed to send message: {response.message}")


@dispatcher.public
def receive_message(msg, msg_id, group_id, source_id, destination_id):
    """Handle receiving a broadcasted message."""
    if msg_id in received_messages:
        return Response(success=True, message="Duplicate message")

    if destination_id == self_id:
        received_messages.add(msg_id)
        store_message(msg, msg_id, group_id, source_id)
        return Response(success=True, message="Message received")
    else:
        message_broadcast(msg, msg_id, group_id, source_id, destination_id)


@dispatcher.public
def liveness(ip, port):
	"""Liveness check that a node is alive."""
	try:
		with socket.create_connection((ip, port), timeout=2):
			return True
	except (socket.timeout, socket.error):
		return False


if __name__ == "__main__":
    serve(port=5000)