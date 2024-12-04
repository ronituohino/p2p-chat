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
from tinyrpc.transports.http import HttpPostClientTransport
from tinyrpc import RPCClient
from typing import Optional, List
from sqlitedict import SqliteDict
from structs import Group, Node, NDSResponse, Response

# This needs the server to be on one thread, otherwise IPs will get messed up
env = None


# Custom WSGI app to handle IP extraction
class CustomWSGITransport(WsgiServerTransport):
	def handle(self, environ, start_response):
		global env
		env = environ
		return super().handle(environ, start_response)


def get_ip():
	return env.get("REMOTE_ADDR", "Unknown IP")


dispatcher = RPCDispatcher()
node_port = 50001
nds_port = 50002
nds_servers = SqliteDict("discovery_server.db", autocommit=True)
groups = SqliteDict("groups.db", autocommit=True)
message_store = SqliteDict("messages.db", autocommit=True)
received_messages = set()

self_name = None
networking = None


# group_id: {
#   group_name,
#   self_id,
#   leader_id,
#   vector_clock,
#    peers: {
#        id: {name, ip}
#        }
#    }


def serve(net=None, node_name=None):
	global self_name
	self_name = node_name
	global networking
	networking = net
	global dispatcher
	dispatcher = RPCDispatcher()
	transport = CustomWSGITransport(queue_class=gevent.queue.Queue)
	wsgi_server = gevent.pywsgi.WSGIServer(("0.0.0.0", node_port), transport.handle)
	gevent.spawn(wsgi_server.serve_forever)
	rpc_server = RPCServerGreenlets(transport, JSONRPCProtocol(), dispatcher)
	rpc_server.serve_forever()


def create_rpc_client(ip, port):
	rpc_client = RPCClient(
		JSONRPCProtocol(), HttpPostClientTransport(f"http://{ip}:{port}/", timeout=10)
	)
	return rpc_client


def store_message(msg, msg_id, group_id, source_id):
	"""Store a message locally."""
	if group_id not in message_store:
		message_store[group_id] = []
	messages = message_store[group_id]
	messages.append({"msg_id": msg_id, "source_id": source_id, "msg": msg})
	message_store[group_id] = messages


def get_messages(group_id):
	"""Retrieve all messages for a given group_id."""
	messages = message_store.get(group_id, [])
	return messages


def get_group_info(group_id):
	"""Return (
	  group_name: str,
	  self_id: id,
	  leader_id: id,
	  vector_clock: id,
	  peers: Dict
	)"""

	group = groups.get(group_id, {})
	if not group:
		raise ValueError(f"Group with ID {group_id} does not exist.")

	return (
		group.get("group_name", ""),
		group.get("self_id", ""),
		group.get("leader_id", ""),
		group.get("vector_clock", 0),
		group.get("peers", {}),
	)


def update_group_info(group_id, group_name, self_id, leader_id, vector_clock, peers):
	"""Updates (
	  group_name: str,
	  self_id: id,
	  leader_id: id,
	  vector_clock: id,
	  peers: Dict
	)"""
	groups[group_id] = {
		"group_name": group_name,
		"self_id": self_id,
		"leader_id": leader_id,
		"vector_clock": vector_clock,
		"peers": peers,
	}


def get_group_peers(group_id):
	"""Return all peers related to the group"""
	group = groups.get(group_id, {})
	if not group:
		raise ValueError(f"Group with ID {group_id} does not exist.")
	return group.get("peers", {})


def get_self_id(group_id):
	"""Return self_id related to the group"""
	group = groups.get(group_id, {})
	if not group:
		raise ValueError(f"Group with ID {group_id} does not exist.")
	return group.get("self_id", {})


@dispatcher.public
def fetch_groups(nds_ip) -> List[Group]:
	"""Returns all possible groups to join"""
	nds = nds_servers.get(nds_ip)
	remote_server = nds.get_proxy()
	response = NDSResponse(remote_server.get_groups())
	if response.success:
		return response.data["groups"]
	return []


def add_node_discovery_source(nds_ip) -> bool:
	"""Add a discovery server.

	Args:
	    nds_ip (str): IP addr. of the node discovery server

	Returns:
	    bool: True, indicates success
	"""
	rpc_client = create_rpc_client(ip=nds_ip, port=nds_port)
	nds_servers[nds_ip] = rpc_client
	return True


def request_to_join_group(leader_ip, group_id) -> Optional[List[Node]]:
	"""_summary_

	Args:
	    leader_ip (str): An IP addr. of the leader ip
	    group_id (str): An ID of the group.

	Returns:
	    list: A set of nodes if success.
	"""
	rpc_client = create_rpc_client(leader_ip, node_port)
	# This is request to leader
	remote_server = rpc_client.get_proxy()
	response = remote_server.join_group(group_id, self_name)
	if response.success:
		groups[group_id] = {
			"group_name": response.data["group_name"],
			"self_id": response.data["assigned_peer_id"],
			"leader_id": response.data["leader_id"],
			"vector_clock": response.data["vector_clock"],
			"peers": response.data["peers"],
		}

		logging.info(f"Joined group with Peer ID: {response.data['assigned_peer_id']}")
		return groups[group_id]["peers"]
	else:
		logging.error(f"Failed to join group {group_id} with error: {response.message}")


def request_to_leave_group(leader_ip, group_id):
	"""A way for client to request leaving the group

	Args:
	    leader_ip (str): An IP addr. of the leader ip
	    group_id (str): An ID of the group.

	Returns:
	    bool: True, if success
	"""
	_,_,leader_id,_,_ = get_group_info(group_id)
	self_id = get_self_id(group_id)
	rpc_client = create_rpc_client(leader_ip, node_port)
	remote_server = rpc_client.get_proxy()
	response = remote_server.leave_group(group_id, self_id)
	if response.success:
		groups[group_id] = None
		logging.info(f"{response.message} {group_id}")
		return True
	else:
		logging.error("Failed to join group")


def is_group_leader(leader_id, self_id):
	"""A simple way to check if current node is leader or not.
	Args:
	    leader_id (str): ID of the leader
	    self_id (str): ID of the current node

	Returns:
	    bool: True if the current node is the leader.
	"""
	return leader_id == self_id


def create_group(group_name, nds_ip) -> Optional[Group]:
	"""Create a new group and register it with NDS,
	  making this peer the leader.

	Raises:
	    ValueError: Error if NDS Server does not exists.
	    ValueError: Error if the group name has not been set

	Returns:
	    Group obj: newly created group
	"""
	rpc_client = nds_servers.get(nds_ip, False)
	if not rpc_client:
		raise ValueError(f"NDS server with IP {nds_ip} does not exist.")

	if not group_name:
		raise ValueError("Group name cannot be empty")

	remote_server = rpc_client.get_proxy()
	response = NDSResponse(remote_server.create_group(group_name=group_name))

	if response.success:
		group_id = response.data["group_id"]
		groups[group_id] = {
			"group_name": group_name,
			"self_id": 0,
			"leader_id": 0,
			"vector_clock": 0,
			"peers": {0: {"name": self_name, "ip": response.data["leader_ip"]}},
		}
		logging.info(f"Created group {group_name} with ID: {group_id}")
		return Group(group_name, group_id, response.data["leader_ip"])
	else:
		return None


@dispatcher.public
def join_group(group_id, peer_name):
	"""An server implementation that allows user to join a group.
	This is called when client accesses the group leader.

	Args:
	    group_id (str): UID of the group.
	    peer_ip (str): IP addr. of the node sending the request.
	    peer_name (peer_name): name of the peer node.

	Returns:
	    response: If success return data of the group.
	"""

	logging.info(f"Peer {peer_name} requesting to join group.")
	group_name, self_id, leader_id, vector_clock, peers = get_group_info(group_id)
	peer_ip = get_ip()

	if not is_group_leader(leader_id, self_id):
		return Response(success=False, message="Only leader can validate users.").to_dict()

	for peer in peers.values():
		if peer["name"] == peer_name:
			return Response(
				success=False, message="Peer name already exists in the group."
			).to_dict()
		if peer["ip"] == peer_ip:
			return Response(
				success=False, message="Peer IP already exists in the group."
			).to_dict()

	assigned_peer_id = max(peers.keys(), default=0) + 1
	peers[assigned_peer_id] = {"name": peer_name, "ip": peer_ip}
	groups[group_id] = {
		"group_name": group_name,
		"self_id": self_id,
		"peers": peers,
		"leader_id": leader_id,
		"vector_clock": vector_clock,
	}

	logging.info(f"Peer {assigned_peer_id} joined with IP {peer_ip}")

	return Response(
		success=True,
		message="Joined a group successfully",
		data={
			"group_name": group_name,
			"peers": peers,
			"assigned_peer_id": assigned_peer_id,
			"leader_id": leader_id,
			"vector_clock": vector_clock,
		},
	).to_dict()


@dispatcher.public
def leave_group(group_id, peer_id):
	"""A way for client to send leave request
	  to leader node of the group.

	Args:
	    group_id (str): UID of the group.
	    peer_id (str): UID of the peer wishing to leave the group.

	Returns:
	    response: Success or fail response
	"""

	group_name, self_id, leader_id, vector_clock, peers = get_group_info(group_id)
	if not is_group_leader(leader_id, self_id):
		return Response(success=False, message="Only leader can delete users.")

	for peer_id in list(peers.keys()):
		peers.pop(peer_id)
		groups[group_id] = {
			"group_name": group_name,
			"self_id": self_id,
			"leader_id": leader_id,
			"vector_clock": vector_clock,
			"peers": peers,
		}
		logging.info(f"Peer {peer_id} left the group")
		return Response(success=True, message="Successfully left the group")
	return Response(success=False, message="Peer not found")


def message_broadcast(msg, msg_id, group_id, source_id):
	"""A message broadcasts if destination ID has not been sent.

	Args:
	    msg (str): A message that user want to send.
	    group_id (str): UID of the group.
	    source_id (str): Peer ID where the message came from.
	    destination_id (str): UID of the peer that we wish to send to.
	"""
	group_name, self_id, leader_id, vector_clock, peers = get_group_info(group_id)
	if not peers:
		logging.info(f"No peers found for group {group_id}.")
		return

	vector_clock += 1
	msg = (vector_clock, msg)
	update_group_info(
		group_id=group_id,
		group_name=group_name,
		self_id=self_id,
		leader_id=leader_id,
		vector_clock=vector_clock,
		peers=peers,
	)

	logging.info(f"Broadcasting message to peers: {peers}")
	for peer_id, peer_info in peers.items():
		if peer_id == source_id or peer_id == self_id:
			continue
		peer_ip = peer_info.get("ip", None)
		rpc_client = create_rpc_client(peer_ip, node_port)
		send_message_to_peer(rpc_client, msg, msg_id, group_id, source_id, peer_id)


def send_message(msg, group_id):
	"""Send a message to be broadcasted by leader.
	Args:
	    client (object): The rpc_client to the peer.
	    msg (str): the message.
	    msg_id (str): ID of the message.
	    group_id (str): UID of the group.
	    source_id (str): ID of the source peer.
	"""
	_, _, leader_id, _, peers = get_group_info(group_id)
	leader_ip = peers[leader_id].get("ip", None)
	msg_id = str(uuid.uuid4())
	if leader_ip:
		rpc_client = create_rpc_client(leader_ip, node_port)
		return send_message_to_peer(rpc_client, msg, msg_id, group_id)
	else:
		logging.error(
			f"IP addr. for leader {leader_ip} in group {group_id} does not exist"
		)


def send_message_to_peer(client, msg, msg_id, group_id, destination_id=-1):
	"""Send a message to individual targeted peer.

	Args:
	    client (object): The rpc_client to the peer.
	    msg (str): the message.
	    msg_id (str): ID of the message.
	    group_id (str): UID of the group.
	    source_id (str): ID of the source peer.
	    destination_id (str, optional): A node that we wish to send message to. Defaults to -1.
	"""
	source_id = get_self_id(group_id)
	remote_server = client.get_proxy()
	response = remote_server.receive_message(
		msg, msg_id, group_id, source_id, destination_id
	)
	if response.success:
		logging.info(f"Message sent, here is response: {response.message}")
	else:
		logging.info(f"Failed to send message: {response.message}")


@dispatcher.public
def receive_message(msg, msg_id, group_id, source_id, destination_id):
	"""Handle receiving a message from peer.
	If message is meant for current node, then it will store it, otherwise it will
	broadcast it forward.

	Args:
	    msg (str): the message.
	    msg_id (str): ID of the message.
	    group_id (str): UID of the group.
	    source_id (str): ID of the source peer.
	    destination_id (str, optional): A node that we wish to send message to. Defaults to -1.

	Returns:
	    response: success / fail
	"""
	_, self_id, leader_id, _, _ = get_group_info(group_id)

	if msg_id in received_messages:
		return Response(success=True, message="Duplicate message")

	if destination_id == self_id:
		received_messages.add(msg_id)
		peers = get_group_peers(group_id=group_id)
		peer = peers[source_id]
		peer_name = peer["name"]
		networking.receive_messages(source_name=peer_name, msg=msg)
		store_message(msg, msg_id, group_id, source_id)
		return Response(success=True, message="Message received")
	elif self_id == leader_id:
		received_messages.add(msg_id)
		peers = get_group_peers(group_id=group_id)
		peer = peers[source_id]
		peer_name = peer["name"]
		networking.receive_messages(source_name=peer_name, msg=msg)
		message_broadcast(msg, msg_id, group_id, source_id, destination_id)
	else:
		return Response(
			success=False, message="Error message sent to incorrect location."
		)


def liveness(ip, port):
	"""Liveness check that a node is alive."""
	try:
		with socket.create_connection((ip, port), timeout=2):
			return True
	except (socket.timeout, socket.error):
		return False


if __name__ == "__main__":
	serve()
