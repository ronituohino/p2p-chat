import uuid
import random
import logging
import threading
import time
import gevent
import gevent.pywsgi
import gevent.queue
from tinyrpc.protocols.jsonrpc import JSONRPCProtocol
from tinyrpc.transports.wsgi import WsgiServerTransport
from tinyrpc.server.gevent import RPCServerGreenlets
from tinyrpc.dispatch import RPCDispatcher
from tinyrpc.transports.http import HttpPostClientTransport
from tinyrpc import RPCClient
from typing import Optional
from structs import Group, Node, Response, Message

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


# Constants
node_port = 50001
nds_port = 50002

# Runtime constants
dispatcher = RPCDispatcher()
self_name = None
networking = None

# Global variables
nds_servers: dict[str, RPCClient] = {}  # key is nds_ip
groups: dict[str, Group] = {}  # key is group_id
message_store: dict[str, Message] = {}  # key is group_id
received_messages = set()


def serve(net=None, node_name=None):
	global self_name
	self_name = node_name
	global networking
	networking = net

	transport = CustomWSGITransport(queue_class=gevent.queue.Queue)
	wsgi_server = gevent.pywsgi.WSGIServer(("0.0.0.0", node_port), transport.handle)
	gevent.spawn(wsgi_server.serve_forever)

	rpc_server = RPCServerGreenlets(transport, JSONRPCProtocol(), dispatcher)
	rpc_server.serve_forever()


def create_rpc_client(ip, port):
	"""
	Create a remote client object.
	This itself does not attempt to send anything, so it cannot fail.
	"""
	rpc_client = RPCClient(
		JSONRPCProtocol(), HttpPostClientTransport(f"http://{ip}:{port}/", timeout=5)
	)
	return rpc_client


def add_node_discovery_source(nds_ip):
	"""
	Adds a discovery server, and returns all possible groups to join from NDS or None, if the connection fails.
	"""
	rpc_client = create_rpc_client(ip=nds_ip, port=nds_port)
	nds_servers[nds_ip] = rpc_client

	try:
		nds = rpc_client.get_proxy()
		response = Response(**nds.get_groups())
		return response

		if response.success:
			return map(
				lambda g: Group(
					name=g["group_name"],
					group_id=g["group_id"],
					leader_ip=g["leader_ip"],
				),
				response.data["groups"],
			)
	except BaseException:
		return None


def request_to_join_group(leader_ip, group_id) -> Optional[list[Node]]:
	"""
	Args:
		leader_ip (str): An IP addr. of the leader ip
		group_id (str): An ID of the group.

	Returns:
		list: A set of nodes if success.
	"""
	rpc_client = create_rpc_client(leader_ip, node_port)
	# This is request to leader
	remote_server = rpc_client.get_proxy()
	response_dict = remote_server.join_group(group_id, self_name)
	response = Response(**response_dict)
	if response.success:
		groups[group_id] = {
			"group_name": response.data["group_name"],
			"self_id": response.data["assigned_peer_id"],
			"leader_id": response.data["leader_id"],
			"vector_clock": response.data["vector_clock"],
			"peers": response.data["peers"],
			"nds_ip": response.data["nds_ip"],
		}

		logging.info(f"Joined group with Peer ID: {response.data['assigned_peer_id']}")
		threading.Thread(
			target=send_heartbeat_to_leader, args=(group_id,), daemon=True
		).start()
		synchronize_with_leader(group_id)
		return response.data["peers"]
	else:
		logging.error(f"Failed to join group {group_id} with error: {response.message}")
		return False


def request_to_leave_group(leader_ip, group_id):
	"""A way for client to request leaving the group

	Args:
		leader_ip (str): An IP addr. of the leader ip
		group_id (str): An ID of the group.

	Returns:
		bool: True, if success
	"""
	if group_id not in groups or groups[group_id] is None:
		logging.error(f"Cannot leave group {group_id} because it does not exist.")
		return groups

	self_id = get_self_id(group_id)
	rpc_client = create_rpc_client(leader_ip, node_port)
	remote_server = rpc_client.get_proxy()
	response_dict = remote_server.leave_group(group_id, self_id)
	response = Response(**response_dict)
	if response.success:
		groups[group_id] = {}
		logging.info(f"{response.message} {group_id}")
		return groups
	else:
		logging.error("Failed to leave group")


def store_message(msg, msg_id, group_id, source_id, vector_clock):
	"""Store a message locally."""
	if group_id not in message_store:
		message_store[group_id] = []
	messages = message_store[group_id]
	messages.append(
		{
			"msg_id": msg_id,
			"source_id": source_id,
			"msg": msg,
			"vector_clock": vector_clock,
		}
	)
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
		logging.error(f"Group with ID {group_id} does not exist.")

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


def send_heartbeat_to_leader(group_id):
	_, self_id, leader_id, _, peers = get_group_info(group_id)
	while True:
		leader_ip = peers[leader_id].get("ip", None)
		if leader_ip:
			try:
				rpc_client = create_rpc_client(leader_ip, node_port)
				remote_server = rpc_client.get_proxy()
				response = remote_server.receive_heartbeat(group_id, self_id)
				response = Response(**response)
				if not response.success:
					leader_election(group_id=group_id)
					logging.warning("Leader did not acknowledge heartbeat.")
			except Exception as e:
				logging.error(f"Error sending hearbeat to leader: {e}")
				leader_election(group_id=group_id)
		else:
			logging.error("Leader IP addr. not found. Initiating election...")
			leader_election(group_id=group_id)

		min_interval = 2
		max_interval = 4
		interval = random.uniform(min_interval, max_interval)
		time.sleep(interval)


def get_peer_ip(peer_id, group_id):
	peers = get_group_peers(group_id)
	peer = peers.get(peer_id)
	return peer.get("ip", None)


@dispatcher.public
def receive_heartbeat(group_id, peer_id):
	peers = get_group_peers(group_id)
	if peer_id in peers:
		return Response(success=True, message="Heartbeat received")


def leader_election(group_id):
	_, self_id, _, vector_clock, peers = get_group_info(group_id=group_id)
	low_id_nodes = [peer_id for peer_id in peers if peer_id < self_id]
	got_answer = None
	if not low_id_nodes:
		become_leader(group_id)
	else:
		for peer_id in low_id_nodes:
			if peer_id == self_id:
				continue
			peer_ip = peers[peer_id]["ip"]
			rpc_client = create_rpc_client(peer_ip, node_port)
			try:
				remote_server = rpc_client.get_proxy()
				response = remote_server.election_message(
					group_id, self_id, vector_clock
				)
				response = Response(**response)
				if response.success:
					got_answer = True
			except Exception:
				continue
		if not got_answer:
			become_leader(group_id)


def update_nds_server(group_id):
	group = groups.get(group_id)
	nds_ip = group.get("nds_ip")
	server = nds_servers.get(nds_ip, None)
	if server:
		remote_server = server.get_proxy()
		response_dict = remote_server.update_group_leader(group_id)
		response = Response(**response_dict)
		if response.success:
			return (True, None)
		elif not response.success:
			return (False, response.data.get("leader_ip", None))
	else:
		logging.error("NDS server not found.")
		return (False, None)


def become_leader(group_id):
	group_name, self_id, leader_id, vector_clock, peers = get_group_info(
		group_id=group_id
	)
	leader_id = self_id
	did_update, current_leader_ip = update_nds_server(group_id)
	if not did_update:
		if current_leader_ip:
			logging.info(f"Current leader IP from NDS: {current_leader_ip}")
			request_to_join_group(leader_ip=current_leader_ip, group_id=group_id)
		return
	else:
		update_group_info(group_id, group_name, self_id, leader_id, vector_clock, peers)
		broadcast_new_leader(group_id)
		push_messages_to_peers(group_id)


def push_messages_to_peers(group_id):
	_, _, _, _, peers = get_group_info(group_id=group_id)
	all_messages = message_store.get(group_id, [])
	peers = get_group_peers(group_id=group_id)

	for peer_id, _ in peers.items():
		push_messages_to_peer(
			group_id=group_id, all_messages=all_messages, peer_id=peer_id
		)


@dispatcher.public
def call_for_synchronization(group_id, peer_id, peer_vector_clock):
	all_messages = message_store.get(group_id, [])
	missing_messages = [
		msg for msg in all_messages if msg["vector_clock"] > peer_vector_clock
	]
	return Response(
		success=True,
		message="Missing messages provided.",
		data={"missing_messages": missing_messages},
	)


def synchronize_with_leader(group_id):
	_, self_id, leader_id, vector_clock, peers = get_group_info(group_id=group_id)
	leader_ip = peers.get(leader_id, {}).get("ip")
	if leader_ip:
		rpc_client = create_rpc_client(leader_ip, node_port)
		remote_server = rpc_client.get_proxy()
		response_dict = remote_server.call_for_synchronization(
			group_id, self_id, vector_clock
		)
		response = Response(**response_dict)
		if response.success:
			missing_messages = response.data.get("missing_messages", [])
			if missing_messages:
				update_messages(group_id, missing_messages)


def push_messages_to_peer(group_id, all_messages, peer_id):
	_, self_id, _, _, _ = get_group_info(group_id=group_id)
	if peer_id == self_id:
		return False

	peer_ip = get_peer_ip(peer_id=peer_id, group_id=group_id)
	rpc_client = create_rpc_client(peer_ip, node_port)

	remote_server = rpc_client.get_proxy()
	response_dict = remote_server.report_vector_clock(group_id)
	response = Response(**response_dict)
	if response.success:
		peer_vector_clock = response.data["vector_clock"]
		missing_messages = [
			msg for msg in all_messages if msg["vector_clock"] > peer_vector_clock
		]
		if missing_messages:
			remote_server.update_messages(group_id, missing_messages)
			logging.info(f"Sent {len(missing_messages)} messages to peer {peer_id}")
	else:
		logging.warning(f"Could not fetch vector clock from peer {peer_id}")


@dispatcher.public
def report_vector_clock(group_id):
	group = groups.get(group_id, {})
	vector_clock = group.get("vector_clock", 0)
	return Response(
		success=True,
		message="vector clock reported succesfully.",
		data={"vector_clock": vector_clock},
	)


@dispatcher.public
def update_messages(group_id, messages):
	for msg_data in messages:
		msg_id = msg_data["msg_id"]
		source_id = msg_data["source_id"]
		msg = msg_data["msg"]
		vector_clock = msg_data["vector_clock"]
		if msg_id not in received_messages:
			store_message(msg, msg_id, group_id, source_id, vector_clock)
			received_messages.add(msg_id)
			peers = get_group_peers(group_id)
			peer_info = peers.get(source_id)
			peer_name = peer_info.get("name", "Unknown")
			networking.receive_messages(source_name=peer_name, msg=(vector_clock, msg))

	if messages:
		max_vector_clock = max(msg["vector_clock"] for msg in messages)
		group = groups.get(group_id, {})
		group["vector_clock"] = max(group.get("vector_clock", 0), max_vector_clock)
		groups[group_id] = group
	return Response(success=True, message="messages have been received successfully.")


@dispatcher.public
def election_message(group_id, candidate_id, candidate_vc):
	_, self_id, _, vector_clock, _ = get_group_info(group_id=group_id)
	if self_id < candidate_id and vector_clock >= candidate_vc:
		return Response(success=True, message="ACK")


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
	response_dict = remote_server.create_group(group_name=group_name)
	response = Response(**response_dict)
	if response.success:
		group_id = response.data["group_id"]
		this_node = {0: {"name": self_name, "ip": response.data["leader_ip"]}}
		groups[group_id] = {
			"group_name": group_name,
			"self_id": 0,
			"leader_id": 0,
			"vector_clock": 0,
			"peers": this_node,
			"nds_ip": nds_ip,
		}
		logging.info(f"Created group {group_name} with ID: {group_id}")
		return Group(group_name, group_id, response.data["leader_ip"])
	else:
		return None


def broadcast_new_leader(group_id):
	_, self_id, _, _, peers = get_group_info(group_id)
	for peer_id, peer_info in peers.items():
		if peer_id == self_id:
			continue
		peer_ip = peer_info["ip"]
		rpc_client = create_rpc_client(peer_ip, node_port)
		remote_server = rpc_client.get_proxy()
		remote_server.update_leader(group_id, self_id)


@dispatcher.public
def update_leader(group_id, self_id):
	group = groups.get(group_id, {})
	if group:
		group["leader_id"] = self_id
		groups[group_id] = group
		logging.info("Peer list updated.")
		return Response(success=True, message="Leader has been updated.")
	else:
		return Response(success=False, message="Leader was not updated.")


def broadcast_peer_list(group_id, target_id):
	_, self_id, _, _, peers = get_group_info(group_id)
	for peer_id, peer_info in peers.items():
		if peer_id == self_id or peer_id == target_id:
			continue
		peer_ip = peer_info["ip"]
		rpc_client = create_rpc_client(peer_ip, node_port)
		remote_server = rpc_client.get_proxy()
		remote_server.update_peers(group_id, peers)


@dispatcher.public
def update_peers(group_id, updated_peers):
	group = groups.get(group_id, {})
	if group:
		group["peers"] = updated_peers
		groups[group_id] = group
		logging.info("Peer list updated.")
		return Response(success=True, message="Peer list has been updated.")
	else:
		return Response(success=False, message="Group not found.")


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
	try:
		group_name, self_id, leader_id, vector_clock, peers = get_group_info(group_id)
		peer_ip = get_ip()

		if not is_group_leader(leader_id, self_id):
			return Response(success=False, message="Only leader can validate users.")

		for peer in peers.values():
			if peer["name"] == peer_name:
				return Response(
					success=False, message="Peer name already exists in the group."
				)
			if peer["ip"] == peer_ip:
				return Response(
					success=False, message="Peer IP already exists in the group."
				)

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
		group_name, self_id, leader_id, vector_clock, peers = get_group_info(group_id)
		broadcast_peer_list(group_id=group_id, target_id=assigned_peer_id)
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
		)
	except Exception as e:
		logging.error(f"Error in join_group: {e}")
		return Response(success=False, message="An unexpected error occurred.")


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

	if peer_id in peers:
		peers.pop(peer_id)
		groups[group_id] = {
			"group_name": group_name,
			"self_id": self_id,
			"leader_id": leader_id,
			"vector_clock": vector_clock,
			"peers": peers,
		}
		logging.info(f"Peer {peer_id} left the group")
		broadcast_peer_list(group_id=group_id, target_id=peer_id)
		return Response(success=True, message="Successfully left the group")
	return Response(success=False, message="Peer not found")


def message_broadcast(msg, msg_id, group_id, source_id):
	"""A message broadcasts.

	Args:
		msg (str): A message that user want to send.
		group_id (str): UID of the group.
		source_id (str): Peer ID where the message came from.
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
	response_dict = remote_server.receive_message(
		msg, msg_id, group_id, source_id, destination_id
	)
	response = Response(**response_dict)
	if response.success:
		logging.info(f"Message sent, here is response: {response.message}")
	else:
		logging.info(f"Failed to send message: {response.message}")


@dispatcher.public
def receive_message(msg_with_clock, msg_id, group_id, source_id, destination_id):
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
	vector_clock, msg = msg_with_clock
	group_name, self_id, leader_id, current_vector_clock, peers = get_group_info(
		group_id
	)

	if msg_id in received_messages:
		return Response(success=True, message="Duplicate message")

	if vector_clock > current_vector_clock + 1:
		logging.warning("Detected missing messages. Initiating synchronization.")
		synchronize_with_leader(group_id)

	current_vector_clock = max(current_vector_clock, vector_clock) + 1
	update_group_info(
		group_id=group_id,
		group_name=group_name,
		self_id=self_id,
		leader_id=leader_id,
		vector_clock=current_vector_clock,
		peers=peers,
	)

	peer = peers.get(source_id, None)
	peer_name = peer.get("name", "Unknown")

	if destination_id == self_id:
		received_messages.add(msg_id)
		networking.receive_messages(source_name=peer_name, msg=msg)
		store_message(msg, msg_id, group_id, source_id, vector_clock)
		return Response(success=True, message="Message received")
	elif self_id == leader_id:
		received_messages.add(msg_id)
		networking.receive_messages(source_name=peer_name, msg=msg)
		store_message(msg, msg_id, group_id, source_id, vector_clock)
		message_broadcast(msg_with_clock, msg_id, group_id, source_id, destination_id)
	else:
		return Response(
			success=False, message="Error message sent to incorrect location."
		)


if __name__ == "__main__":
	serve()
