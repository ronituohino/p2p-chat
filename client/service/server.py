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

from structs.client import (
	Group,
	Node,
	Message,
	JoinGroupResponse,
	ReceiveMessageResponse,
)
from structs.generic import Response
from structs.nds import FetchGroupResponse, CreateGroupResponse

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

### SERVER STARTUP, CONNECTIONS, NDS ADDITION


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
		response = FetchGroupResponse.from_json(nds.get_groups())
		if response.ok:
			return response.groups
		else:
			logging.error("Failed to add NDS")
			return None
	except BaseException as e:
		logging.error(f"EXC: Failed to add NDS {e}")
		return None


### GROUP JOINING / LEAVING


def create_group(group_name, nds_ip) -> Group | None:
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
		raise ValueError("Group name cannot be empty.")

	try:
		nds = rpc_client.get_proxy()
		response = CreateGroupResponse.from_json(
			nds.create_group(group_name=group_name)
		)

		if response.ok:
			group_id = response.group.group_id
			this_node = Node(node_id=0, name=self_name, ip=response.group.leader_ip)
			this_group = Group(
				group_id=group_id,
				name=group_name,
				vector_clock=0,
				nds_ip=nds_ip,
				self_id=0,
				leader_id=0,
				peers={0: this_node},
			)
			groups[group_id] = this_group

			logging.info(f"Created group, {group_name}, with ID: {group_id}")
			return this_group
		else:
			logging.error("Failed to create group")
			return None
	except BaseException as e:
		logging.error(f"EXC: Failed to create group: {e}")
		return None


def leave_group(group: Group):
	"""A way for client to request leaving the group

	Args:
		leader_ip (str): An IP addr. of the leader ip
		group_id (str): An ID of the group.

	Returns:
		bool: True, if success
	"""
	if group.group_id not in groups or groups[group.group_id] is None:
		logging.error(f"Cannot leave group {group.group_id} because it does not exist.")
		return groups

	# If we are the leader of the group
	# we can just dip, and stop responding to messages
	if group.self_id == group.leader_id:
		return
	else:
		# If we are not the leader
		# we can just stop sending liveness pings to leader
		# who then notices that we are gone
		return


def request_to_join_group(leader_ip, group_id) -> list[Node] | None:
	"""
	Args:
		leader_ip (str): An IP addr. of the leader ip
		group_id (str): An ID of the group.

	Returns:
		list: A set of nodes if success.
	"""
	rpc_client = create_rpc_client(leader_ip, node_port)
	# This is request to leader
	try:
		leader = rpc_client.get_proxy()
		response = JoinGroupResponse.from_json(leader.join_group(group_id, self_name))
		if response.ok:
			response.group.self_id = response.assigned_peer_id
			groups[group_id] = response.group
			logging.info(f"Joined group: {response.group}")
			# threading.Thread(
			# target=send_heartbeat_to_leader, args=(group_id,), daemon=True
			# ).start()
			# synchronize_with_leader(group_id)
			return list(response.group.peers.values())
		else:
			logging.error(
				f"Failed to join group {group_id} with error: {response.message}"
			)
			return None
	except BaseException as e:
		logging.error(f"EXC: Failed to join group {group_id}: {e}")
		return None


@dispatcher.public
def join_group(group_id, peer_name):
	"""
	This is called when a client asks the group leader if they could join.

	Args:
		group_id (str): UID of the group.
		peer_name (peer_name): name of the peer node.

	Returns:
		response: If success return data of the group.
	"""

	logging.info(f"Peer {peer_name} requesting to join group.")
	try:
		group = groups.get(group_id)
		peer_ip = get_ip()

		if group.leader_id != group.self_id:
			return JoinGroupResponse(
				ok=False,
				message="I am not the leader of that group, and I can't accept the request.",
			).to_json()

		for peer in group.peers.values():
			if peer.name == peer_name:
				return JoinGroupResponse(
					ok=False, message="You are already in this group."
				).to_json()
			if peer.ip == peer_ip:
				return JoinGroupResponse(
					ok=False, message="Someone has the same IP as you in this group."
				).to_json()

		assigned_peer_id = max(group.peers.keys(), default=0) + 1
		group.peers[assigned_peer_id] = Node(
			node_id=assigned_peer_id, name=peer_name, ip=peer_ip
		)

		logging.info(f"Peer {assigned_peer_id} joined with IP {peer_ip}")

		return JoinGroupResponse(
			ok=True, group=group, assigned_peer_id=assigned_peer_id
		).to_json()
	except Exception as e:
		logging.error(f"Error in join_group: {e}")
		return JoinGroupResponse(
			ok=False, message="An unexpected error occurred."
		).to_json()


### THE THINGS ABOVE WORK NOW


def send_message(msg, group_id):
	"""Send a message to be broadcasted by leader.
	Args:
		msg (str): the message.
		group_id (str): UID of the group.
	"""
	group = groups[group_id]
	leader_ip = group.peers[group.leader_id].ip
	msg_id = str(uuid.uuid4())

	logging.info(f"Networking message to leader {leader_ip}")

	# We are the leader, broadcast to others
	if group.self_id == group.leader_id:
		logging.info("We are leader, broadcast")
		message_broadcast(msg, msg_id, group_id, group.self_id)
	elif leader_ip:
		logging.info("We are not leader, broadcast through leader")
		rpc_client = create_rpc_client(leader_ip, node_port)
		send_message_to_peer(
			client=rpc_client, msg=msg, msg_id=msg_id, group_id=group_id
		)
	else:
		logging.error(f"IP for leader {leader_ip} in group {group_id} does not exist.")


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
	response = ReceiveMessageResponse.from_json(
		remote_server.receive_message(msg, msg_id, group_id, source_id, destination_id)
	)
	if response.ok:
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
	group = groups[group_id]

	if msg_id in received_messages:
		return ReceiveMessageResponse(ok=True, message="Duplicate message.").to_json()

	# if vector_clock > current_vector_clock + 1:
	# logging.warning("Detected missing messages. Initiating synchronization.")
	# synchronize_with_leader(group_id)

	# current_vector_clock = max(current_vector_clock, vector_clock) + 1
	# update_group_info(
	# group_id=group_id,
	# group_name=group_name,
	# self_id=self_id,
	# leader_id=leader_id,
	# vector_clock=current_vector_clock,
	# peers=peers,
	# )

	peer = group.peers.get(source_id, None)
	peer_name = peer.get("name", "Unknown")

	if destination_id == group.self_id:
		received_messages.add(msg_id)
		networking.receive_message(source_name=peer_name, msg=msg)
		# store_message(msg, msg_id, group_id, source_id, 0)
		return ReceiveMessageResponse(ok=True, message="Message received.").to_json()
	elif group.self_id == group.leader_id:
		received_messages.add(msg_id)
		networking.receive_message(source_name=peer_name, msg=msg)
		# store_message(msg, msg_id, group_id, source_id, 0)
		message_broadcast(msg, msg_id, group_id, source_id, destination_id)
	else:
		return ReceiveMessageResponse(
			success=False, message="Error message sent to incorrect location."
		).to_json()


def message_broadcast(msg, msg_id, group_id, source_id):
	"""A message broadcasts.

	Args:
		msg (str): A message that user want to send.
		group_id (str): UID of the group.
		source_id (str): Peer ID where the message came from.
	"""
	group = groups[group_id]
	peers = list(group.peers.values())
	other_peers = []
	for p in peers:
		if p.node_id != source_id and p.node_id != group.self_id:
			other_peers.append(p)

	if len(other_peers) < 1:
		logging.info(f"No other peers found for group {group_id}.")
		return

	# vector_clock += 1
	# msg = (vector_clock, msg)
	# update_group_info(
	# group_id=group_id,
	# group_name=group_name,
	# self_id=self_id,
	# leader_id=leader_id,
	# vector_clock=vector_clock,
	# peers=peers,
	# )

	logging.info(f"Broadcasting message to peers: {peers}")
	for peer in other_peers:
		rpc_client = create_rpc_client(peer.ip, node_port)
		send_message_to_peer(rpc_client, msg, msg_id, group_id, source_id, peer.node_id)


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


### IM WORKING ON THE THINGS BETWEEN


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


if __name__ == "__main__":
	serve()
