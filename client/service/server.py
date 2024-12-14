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
	HeartbeatResponse,
	UpdateGroupResponse,
	ReportLogicalClockResponse,
	CallForSynchronizationResponse,
	UpdateMessagesResponse,
)
from structs.generic import Response
from structs.nds import FetchGroupResponse, CreateGroupResponse, NDS_HeartbeatResponse

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
node_port = 5001
nds_port = 5002

heartbeat_min_interval = 2
heartbeat_max_interval = 4

crawler_refresh_rate = 5

overseer_interval = 1
overseer_cycles_timeout = 6

# Runtime constants
dispatcher = RPCDispatcher()
self_name = None
networking = None

# Global variables
nds_servers: dict[str, RPCClient] = {}  # key is nds_ip
active_group: Group = None  # we can only be in one group at a time

message_store_lock = threading.Lock()
received_messages_lock = threading.Lock()


def get_active_group() -> Group:
	global active_group
	return active_group


def set_active_group(group: Group):
	global active_group
	active_group = group


message_store: dict[str, Message] = {}  # key is group_id
received_messages = set()
message_timestamps = {}
MESSAGE_TTL = 300
### SERVER STARTUP, RPC CONNECTIONS, NDS ADDITION


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
		response: FetchGroupResponse = FetchGroupResponse.from_json(nds.get_groups())
		if response.ok:
			# Begin crawling 8)
			start_crawler()
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
		response: CreateGroupResponse = CreateGroupResponse.from_json(
			nds.create_group(group_name=group_name)
		)

		if response.ok:
			group_id = response.group.group_id
			this_node = Node(node_id=0, name=self_name, ip=response.group.leader_ip)
			this_group = Group(
				group_id=group_id,
				name=group_name,
				logical_clock=0,
				nds_ip=nds_ip,
				self_id=0,
				leader_id=0,
				peers={0: this_node},
			)

			set_active_group(this_group)
			start_overlord()

			logging.info(f"Created group, {group_name}, with ID: {group_id}")
			return this_group
		else:
			logging.error("Failed to create group")
			return None
	except BaseException as e:
		logging.error(f"EXC: Failed to create group: {e}")
		return None


def start_overlord():
	start_heartbeat()
	start_overseer()


def request_to_leave_group(group: Group):
	"""A way for client to leave a group."""

	# If we are the leader of the group
	# we can just dip, and stop responding to messages

	# If we are not the leader
	# we can just stop sending liveness pings to leader
	# who then notices that we are gone

	logging.info("Leaving group.")
	active = get_active_group()
	if active and group.group_id == get_active_group().group_id:
		set_active_group(None)
		networking.refresh_group(group)


def request_to_join_group(leader_ip, group_id) -> Group | None:
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
		response: JoinGroupResponse = JoinGroupResponse.from_json(
			leader.join_group(self_name, group_id)
		)
		if response.ok:
			response.group.self_id = response.assigned_peer_id
			set_active_group(response.group)
			logging.info(f"Joined group: {response.group}")
			start_heartbeat()
			synchronize_with_leader()
			return response.group
		else:
			logging.error(f"Failed to join group with error: {response.message}")
			group = get_active_group()
			networking.refresh_group(group)
			return None
	except ConnectionError as e:
		logging.error(f"EXC: Failed to join group: {e}")
		return None


@dispatcher.public
def join_group(peer_name, group_id):
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
		group = get_active_group()

		if not group:
			return JoinGroupResponse(
				ok=False, message="not-in-any-group", assigned_peer_id=-1, group=None
			).to_json()

		peer_ip = get_ip()

		if group.leader_id != group.self_id:
			return JoinGroupResponse(
				ok=False, message="not-leader", assigned_peer_id=-1, group=None
			).to_json()

		if group.group_id != group_id:
			return JoinGroupResponse(
				ok=False, message="not-in-that-group", assigned_peer_id=-1, group=None
			).to_json()

		for peer in group.peers.values():
			if peer.name == peer_name and peer.ip == peer_ip:
				# Overseeing
				last_node_response[peer.node_id] = 0
				return JoinGroupResponse(
					ok=True,
					message="already-in-group",
					assigned_peer_id=peer.node_id,
					group=group,
				).to_json()

		assigned_peer_id = max(group.peers.keys(), default=0) + 1
		# Overseeing
		last_node_response[assigned_peer_id] = 0
		group.peers[assigned_peer_id] = Node(
			node_id=assigned_peer_id, name=peer_name, ip=peer_ip
		)
		networking.refresh_group(group)
		logging.info(f"Peer {assigned_peer_id} joined with IP {peer_ip}")
		return JoinGroupResponse(
			ok=True, message="ok", group=group, assigned_peer_id=assigned_peer_id
		).to_json()

	except Exception as e:
		logging.error(f"Error in join_group: {e}")
		return JoinGroupResponse(
			ok=False, message="error", group=None, assigned_peer_id=0
		).to_json()


### MESSAGING


def send_message(msg) -> bool:
	"""Send a message to be broadcasted by leader, called from ui.
	Args:
		msg (str): the message.

	Returns:
		bool: If message was sent successfully.
	"""

	active = get_active_group()
	if not active:
		return False

	leader_ip = active.peers[active.leader_id].ip
	msg_id = str(uuid.uuid4())

	store_message(
		msg,
		msg_id,
		active_group.group_id,
		active_group.self_id,
		active_group.logical_clock,
	)

	logging.info(f"Networking message to leader {leader_ip}")
	if active.self_id == active.leader_id:
		# We are the leader, broadcast to others
		logging.info("We are leader, broadcast")

		active_group.logical_clock += 1
		return message_broadcast(msg, msg_id, active.group_id, active.self_id)
	elif leader_ip:
		# We are not the leader, send to leader who broadcasts to others
		logging.info("We are not leader, broadcast through leader")
		return send_message_to_peer(
			client_ip=leader_ip,
			msg=msg,
			msg_id=msg_id,
			group_id=active.group_id,
			source_id=active.self_id,
			logical_clock=active.logical_clock,
		)
	else:
		logging.error(
			f"IP for leader {leader_ip} in group {active.group_id} does not exist."
		)
		return False


def send_message_to_peer(client_ip, msg, msg_id, group_id, source_id, logical_clock):
	"""Send a message to individual targeted peer.

	Args:
		client (object): The rpc_client to the peer.
		msg (str): the message.
		msg_id (str): ID of the message.
		group_id (str): UID of the group.
	"""
	try:
		rpc_client = create_rpc_client(client_ip, node_port)
		client = rpc_client.get_proxy()
		response: ReceiveMessageResponse = ReceiveMessageResponse.from_json(
			client.receive_message(
				msg=msg,
				msg_id=msg_id,
				group_id=group_id,
				source_id=source_id,
				leader_logical_clock=logical_clock,
			)
		)
		if response.ok:
			logging.info("Leader received message successfully.")
			return True
		if not response.ok:
			logging.info(f"Failed to send message: {response.message}")
			return False
	except BaseException as e:
		logging.info(f"Failed to send message: {e}")
		return False


@dispatcher.public
def receive_message(msg, msg_id, group_id, source_id, leader_logical_clock=0):
	"""Handle receiving a message from peer.
	If message is meant for current node, then it will store it, otherwise it will
	broadcast it forward.

	Args:
		msg (str): the message.
		msg_id (str): ID of the message.
		group_id (str): UID of the group.
		source_id (str): ID of the source peer.

	Returns:
		response: success / fail
	"""
	group = get_active_group()

	if not group or group.group_id != group_id:
		logging.warning("Couldn't receive a message, no longer in group.")
		return ReceiveMessageResponse(ok=False, message="no-longer-in-group").to_json()
	if msg_id in received_messages:
		logging.warning("Couldn't receive a message, duplicate.")
		return ReceiveMessageResponse(ok=True, message="duplicate").to_json()

	if (
		leader_logical_clock > group.logical_clock + 1
		and group.leader_id != group.self_id
	):
		logging.warning("Detected missing messages. Initiating synchronization.")
		synchronize_with_leader()

	current_logical_clock = max(group.logical_clock, leader_logical_clock) + 1
	group.logical_clock = current_logical_clock

	logging.info("Storing the message...")
	store_message(msg, msg_id, group_id, source_id, current_logical_clock)

	if group.self_id == group.leader_id:
		logging.info("Broadcasting the message forward.")
		message_broadcast(msg, msg_id, group_id, source_id)
	return ReceiveMessageResponse(ok=True, message="ok").to_json()


def message_broadcast(msg, msg_id, group_id, source_id) -> bool:
	"""Broadcast a message as leader to other peers

	Args:
		msg (str): A message that user want to send.
		msg_id (str): ID of the message.
		group_id (str): UID of the group.
		source_id (str): Peer ID where the message came from.

	Returns:
		bool: If message was sent successfully.
	"""
	group = get_active_group()
	peers = list(group.peers.values())
	other_peers = []
	for p in peers:
		if p.node_id != source_id and p.node_id != group.self_id:
			other_peers.append(p)

	if len(other_peers) < 1:
		logging.info(f"No other peers found for group {group_id}.")
		return False

	logical_clock = group.logical_clock + 1
	logging.info(f"Broadcasting message to peers: {peers}")
	for peer in other_peers:
		send_message_to_peer(peer.ip, msg, msg_id, group_id, source_id, logical_clock)
	return True


### NDS Crawler
#
# Periodically fetch new group data from all NDS servers
# Single thread will be enough

crawler: threading.Thread = None


def start_crawler():
	"""NDS crawler to periodically fetch group data from NDS servers"""
	global crawler
	logging.info("CRWL: Got signal to start crawler...")
	if not crawler:
		crawler = threading.Thread(target=crawler_thread, daemon=True)
		crawler.start()
	else:
		logging.info("CRWL: Crawler already running.")


def crawler_thread():
	logging.info("CRWL: Crawler starting.")
	try:
		while True:
			logging.info("CRWL: Crawling.")
			for nds_ip, nds_client in nds_servers.items():
				nds = nds_client.get_proxy()
				response: FetchGroupResponse = FetchGroupResponse.from_json(
					nds.get_groups()
				)
				if response.ok:
					networking.reload_all_groups(
						nds_ip, get_active_group(), response.groups
					)

			# Wait for a bit before fetching again
			time.sleep(crawler_refresh_rate)
	except Exception as e:
		logging.error(f"EXC: CRWL: Crawler failed {e}")
	finally:
		logging.info("CRWL: Crawler killed.")


### HEARTBEAT

# thread that sends rpc to leader or NDS every now and then
heartbeat: threading.Thread = None
heartbeat_counter = 0  # set to the id of the heartbeat
heartbeat_kill_flags = set()


def start_heartbeat():
	global heartbeat
	global heartbeat_counter
	global heartbeat_kill_flags

	if heartbeat:
		# Kill existing heartbeat
		logging.info(f"Killing heartbeat {heartbeat_counter}")
		heartbeat_kill_flags.add(heartbeat_counter)

	logging.info("Starting heartbeat sending.")
	heartbeat_counter += 1
	heartbeat = threading.Thread(
		target=heartbeat_thread, args=(heartbeat_counter,), daemon=True
	)
	heartbeat.start()


def heartbeat_thread(hb_id: int):
	global heartbeat_kill_flags
	# Wrap in try clause, so that can be closed with .raise_exception()
	try:
		while True:
			logging.info(f"HB: Sending heartbeat at {hb_id}.")
			if hb_id in heartbeat_kill_flags:
				raise InterruptedError

			active = get_active_group()
			if not active:
				raise InterruptedError

			# If this node NOT leader, send heartbeat to leader
			if active.self_id != active.leader_id:
				send_heartbeat_to_leader()
			else:
				send_heartbeat_to_nds()

			# Sleep for a random interval, balances out leader election more
			interval = random.uniform(heartbeat_min_interval, heartbeat_max_interval)
			time.sleep(interval)
	finally:
		logging.info(f"HB: Killing heartbeat {hb_id}.")


def send_heartbeat_to_leader():
	active = get_active_group()
	leader_ip = active.peers[active.leader_id].ip
	if not leader_ip:
		logging.error("HB: Leader IP not found, initiating election...")
		leader_election(active.group_id)
		return

	try:
		rpc_client = create_rpc_client(leader_ip, node_port)
		leader = rpc_client.get_proxy()
		logging.info(f"HB: Sending heartbeat to leader from {active.self_id}.")
		response: HeartbeatResponse = HeartbeatResponse.from_json(
			leader.receive_heartbeat(active.self_id, active.group_id)
		)
		if response.ok:
			logging.info("HB: Refreshing peers.")
			active.peers = response.peers
			networking.refresh_group(active)
		elif response.message == "changed-group":
			logging.warning("HB: Leader changed group.")
			leader_election(active.group_id)
		else:
			# response.message == "you-got-kicked-lol"
			logging.warning("HB: Leader said not ok, we got kicked!")
			set_active_group(None)
			networking.refresh_group(None)
	except Exception as e:
		logging.error(f"EXC: HB: Error sending hearbeat to leader: {e}")
		leader_election(active.group_id)


def send_heartbeat_to_nds():
	active = get_active_group()
	# This node is leader, send heartbeat to NDS
	rpc_client = nds_servers[active.nds_ip]
	if not rpc_client:
		logging.error("HB: NDS server not found.")

	try:
		nds = rpc_client.get_proxy()
		logging.info("HB: Sending heartbeat to NDS.")
		response: NDS_HeartbeatResponse = NDS_HeartbeatResponse.from_json(
			nds.receive_heartbeat(active.group_id)
		)
		if not response.ok:
			if response.message == "group-deleted-womp-womp":
				logging.error("HB: NDS deleted the group :(")
				set_active_group(None)
				networking.refresh_group(None)
			else:
				logging.error("HB: NDS rejected heartbeat?")
	except BaseException as e:
		logging.error(f"EXC: HB: Failed to send heartbeat to NDS: {e}")


@dispatcher.public
def receive_heartbeat(peer_id, group_id):
	active = get_active_group()
	if active.group_id != group_id:
		return HeartbeatResponse(
			ok=False, message="changed-group", peers=None, logical_clock=0
		).to_json()

	if peer_id in active.peers:
		last_node_response[peer_id] = 0
		return HeartbeatResponse(
			ok=True,
			message="ok",
			peers=active.peers,
			logical_clock=active.logical_clock,
		).to_json()

	return HeartbeatResponse(
		ok=False, message="you-got-kicked-lol", peers=None, logical_clock=0
	).to_json()


### OVERSEEING

# thread that checks which nodes have sent heartbeat to me (leader) every now and then
overseer: threading.Thread = None
overseer_counter = 0  # set to the id of the heartbeat
overseer_kill_flags = set()

last_node_response: dict[
	str, int
] = {}  # key is node_id, used to check when last heard from node, value is the overseer cycles


def start_overseer():
	"""Starts overseeing thread"""
	global overseer
	global overseer_counter
	global overseer_kill_flags

	if overseer:
		# Kill existing heartbeat
		logging.info(f"Killing overseer {overseer_counter}.")
		overseer_kill_flags.add(overseer_counter)

	logging.info("Starting overseer.")
	overseer_counter += 1
	overseer = threading.Thread(
		target=overseer_thread, args=(overseer_counter,), daemon=True
	)
	overseer.start()


def overseer_thread(ov_id: int):
	"""Thread to monitor hearbeats from followers, deleting ones not active"""
	try:
		while True:
			logging.info(f"OV: Overseeing at {ov_id}.")
			if ov_id in overseer_kill_flags:
				raise InterruptedError

			active = get_active_group()
			if not active or active.self_id != active.leader_id:
				raise InterruptedError

			nodes_to_delete = []
			for node_id in last_node_response.keys():
				new_val = last_node_response[node_id] + 1
				if new_val > 10:
					# If have not received heartbeat from group leader in 10 cycles, delete Group
					nodes_to_delete.append(node_id)
				else:
					last_node_response[node_id] = new_val

			for node_id in nodes_to_delete:
				del last_node_response[node_id]
				del active.peers[node_id]
				logging.info(f"OV: Node {node_id} deleted -- no heartbeat from node.")

			networking.refresh_group(active)
			time.sleep(overseer_interval)
	except Exception as e:
		logging.error(f"EXC: OV: Overseer failed {e}")
	finally:
		logging.info(f"OV: Overseer {ov_id} killed.")


### LEADER ELECTION


def leader_election(group_id):
	logging.info("Starting leader election.")
	active_group = get_active_group()
	peers = active_group.peers
	self_id = active_group.self_id

	low_id_nodes = [peer_id for peer_id in peers if peer_id < self_id]
	got_answer = None
	if not low_id_nodes:
		logging.info("No other nodes found, making self leader.")
		become_leader()
		return

	for peer_id in low_id_nodes:
		peer = peers[peer_id]
		peer_ip = peer.ip

		logging.info(f"Pinging {peer_id} if they want to be leader...")
		try:
			rpc_client = create_rpc_client(peer_ip, node_port)
			remote_server = rpc_client.get_proxy()
			response: Response = Response.from_json(
				remote_server.election_message(group_id, self_id)
			)
			if response.ok:
				logging.info(
					f"{peer_id} responded that they can be leader. Stopping election."
				)
				got_answer = True
		except Exception:
			logging.info(f"No response from {peer_id}.")
			continue

	if not got_answer:
		logging.info("No response from other nodes, making self leader.")
		become_leader()


@dispatcher.public
def election_message(group_id, candidate_id):
	group = get_active_group()
	if group_id == group.group_id:
		self_id = group.self_id
		if self_id < candidate_id:
			leader_election(group_id)
			return Response(ok=True).to_json()
	else:
		return Response(ok=False).to_json()


def become_leader():
	group = get_active_group()
	self_id = group.self_id

	logging.info("Pinging NDS that we want to be leader.")
	did_update, new_nds_group = update_nds_server()

	if did_update and new_nds_group:
		logging.info("NDS made us leader.")
		group.leader_id = self_id
		start_overlord()
		broadcast_new_leader()
		synchronize_messages_with_peers()

	elif not new_nds_group:
		logging.info("NDS has deleted the group already. Creating the group.")
		new_group = create_group(group.group_name, group.nds_ip)
		set_active_group(new_group)
		networking.refresh_group(new_group)

	else:
		current_leader_ip = new_nds_group.leader_ip
		logging.info(
			f"Some leader already exists, with ip {current_leader_ip}, requesting to join group."
		)
		new_group = request_to_join_group(current_leader_ip, new_nds_group.group_id)
		logging.info(f"Group joined {new_group}")
		set_active_group(new_group)
		networking.refresh_group(new_group)
		synchronize_with_leader()


def update_nds_server():
	group = get_active_group()
	group_id = group.group_id
	nds_ip = group.nds_ip
	server = nds_servers[nds_ip]

	if server:
		remote_server = server.get_proxy()
		response: UpdateGroupResponse = UpdateGroupResponse.from_json(
			remote_server.update_group_leader(group_id)
		)
		return (response.ok, response.group)

	else:
		logging.error("NDS server not found.")
		return (False, None)


@dispatcher.public
def still_leader_of_group(group_id):
	group = get_active_group()

	if group and group.group_id == group_id and group.leader_id == group.self_id:
		return Response(ok=True).to_json()
	else:
		return Response(ok=False).to_json()


def broadcast_new_leader():
	group = get_active_group()
	peers = group.peers
	self_id = group.self_id

	peers_to_remove = []
	for peer_id, peer_info in peers.items():
		if peer_id == self_id:
			continue
		peer_ip = peer_info.ip

		try:
			rpc_client = create_rpc_client(peer_ip, node_port)
			remote_server = rpc_client.get_proxy()
			response: Response = Response.from_json(
				remote_server.update_leader(group.group_id, self_id)
			)
			if not response.ok:
				peers_to_remove.append(peer_id)
				logging.info(
					f"Peer {peer_id} no longer in group, removing them from group."
				)
		except Exception:
			peers_to_remove.append(peer_id)
			logging.info(f"Peer {peer_id} not reached, removing them from group.")
			continue

	for peer_id in peers_to_remove:
		group.peers.pop(peer_id)


@dispatcher.public
def update_leader(group_id, new_leader_id):
	group = get_active_group()
	if group and group.group_id == group_id:
		group.leader_id = new_leader_id
		return Response(ok=True).to_json()
	else:
		return Response(ok=False).to_json()


## Synchronization


def store_message(msg, msg_id, group_id, source_id, logical_clock):
	"""Store a message locally."""
	global message_store

	group = get_active_group()

	if not group:
		logging.error("No active group found.")
		return

	with message_store_lock:
		if group_id not in message_store:
			message_store[group_id] = []

		messages = message_store[group_id]

		if msg_id in received_messages:
			logging.info(f"Duplicate message {msg_id} ignored.")
			return

		if logical_clock > group.logical_clock:
			group.logical_clock = logical_clock

		peers = group.peers
		peer = peers[source_id]

		messages.append(
			{
				"msg_id": msg_id,
				"source_id": source_id,
				"source_name": peer.name,
				"msg": msg,
				"logical_clock": logical_clock,
			}
		)

		# Limit message capacity to 2000 latest
		max_capacity = 5000
		if len(messages) > max_capacity:
			messages.sort(key=lambda msg: msg["logical_clock"], reverse=True)
			messages = messages[-max_capacity:]

		message_store[group_id] = messages

	logging.info("Message has been stored, refreshing chat")
	if hasattr(networking, "refresh_chat"):
		try:
			networking.refresh_chat(messages, group.self_id)
			logging.info("Chat has been refreshed")
		except Exception as e:
			logging.error(f"Error refreshing chat_ {e}")
	else:
		logging.warning("Networking does not have a refresh_chat method.")

	with received_messages_lock:
		received_messages.add(msg_id)


def maintain_received_messages():
	"""Thread that periodically removes received messages."""
	while True:
		current_time = time.time()
		with received_messages_lock:
			keys_to_remove = [
				msg_id
				for msg_id, timestamp in message_timestamps.items()
				if current_time - timestamp > MESSAGE_TTL
			]
			for key in keys_to_remove:
				received_messages.discard(key)
				del message_timestamps[key]
		time.sleep(10)


cleanup_thread = threading.Thread(target=maintain_received_messages, daemon=True)
cleanup_thread.start()


# Used on startup, when node joins it can synchronize its messages with leader.
def synchronize_with_leader():
	group = get_active_group()
	leader_id = group.leader_id
	leader_ip = group.peers.get(leader_id, {}).ip

	if not leader_ip:
		logging.warning("Leader IP not found. Synchronization aborted.")
		return False

	try:
		rpc_client = create_rpc_client(leader_ip, node_port)
		remote_server = rpc_client.get_proxy()
		response: CallForSynchronizationResponse = (
			CallForSynchronizationResponse.from_json(
				remote_server.call_for_synchronization(
					group.group_id, group.logical_clock
				)
			)
		)
		if response.ok:
			missing_messages = response.data.get("missing_messages", [])
			if missing_messages:
				logging.info(
					f"Received {len(missing_messages)} missing messages from leader."
				)
				store_missing_messages(group.group_id, missing_messages)
			else:
				logging.info("No missing messages from leader")
		else:
			logging.warning(f"Synchronization failed: {response.message}")
	except Exception as e:
		logging.error(f"Error during synchronization with leader: {str(e)}")
		return False
	return True


def store_missing_messages(group_id, missing_messages):
	"""Store missing messages and update logical clock for the group"""
	group = get_active_group()
	new_messages = []
	logging.info("Storing missing messages.")
	for msg_data in missing_messages:
		msg_id = msg_data["msg_id"]
		if msg_id not in received_messages:
			new_messages.append(msg_data)

	# Storing new messages
	for msg_data in new_messages:
		store_message(
			msg_data["msg"],
			msg_data["msg_id"],
			group_id,
			msg_data["source_id"],
			msg_data["logical_clock"],
		)

	if missing_messages:
		max_logical_clock = max(
			msg_data["logical_clock"] for msg_data in missing_messages
		)
		group.logical_clock = max(group["logical_clock"], max_logical_clock)
		logging.info(f"Updated logical clock to {group.logical_clock}")
	else:
		logging.info("No new messages were added.")


@dispatcher.public
def call_for_synchronization(group_id, peer_logical_clock):
	logging.info("Calling for synchronization.")
	group = get_active_group()
	if group_id != group.group_id:
		return CallForSynchronizationResponse(ok=False, data={}).to_json()

	all_messages = message_store.get(group_id, [])
	missing_messages = [
		msg for msg in all_messages if msg["logical_clock"] > peer_logical_clock
	]

	return CallForSynchronizationResponse(
		ok=True, data={"missing_messages": missing_messages}
	).to_json()


@dispatcher.public
def update_messages(group_id, messages):
	group = get_active_group()
	if group_id == group.group_id:
		for msg_data in messages:
			if msg_data["msg_id"] not in received_messages:
				store_message(
					msg_data["msg"],
					msg_data["msg_id"],
					group_id,
					msg_data["source_id"],
					msg_data["logical_clock"],
				)
		if messages:
			max_logical_clock = max(msg["logical_clock"] for msg in messages)
			group.logical_clock = max(group.get("logical_clock", 0), max_logical_clock)
		return UpdateMessagesResponse(ok=True).to_json()
	return UpdateMessagesResponse(ok=False).to_json()


## If candidate becomes a leader, it will sync all peer messages and updates them based on logical clock.
def synchronize_messages_with_peers():
	group = get_active_group()
	if not group:
		logging.warning("No active group to synchronize messages with peers.")
		return

	all_messages = message_store[group.group_id]
	for peer in group.peers.values():
		try:
			synchronize_with_peer(group, peer, all_messages)
		except Exception as e:
			logging.error(f"Error synchronizing with peer {peer.peer_id}: {str(e)}")


def synchronize_with_peer(group, peer, all_messages):
	"""Synchronize messages with a specific peer"""
	peer_id = peer.peer_id
	if peer_id == group.self_id:
		return

	try:
		rpc_client = create_rpc_client(peer.ip, node_port)
		remote_server = rpc_client.get_proxy()

		peer_logical_clock = get_peer_logical_clock(remote_server, group, peer_id)
		if not peer_logical_clock:
			return

		send_missing_messages(
			remote_server, group, all_messages, peer_logical_clock, peer_id
		)
		receive_missing_messages(remote_server, group, peer_id)

	except Exception as e:
		logging.error(f"Error synchronizing with peer {peer_id}: {str(e)}")


def get_peer_logical_clock(remote_server, group, peer_id):
	"""Get the logical clock from a peer"""
	try:
		response: ReportLogicalClockResponse = ReportLogicalClockResponse.from_json(
			remote_server.report_logical_clock(group.group_id)
		)

		if not response.ok:
			logging.warning(f"Could not fetch logical clock from peer {peer_id}")
			return None
		return response.data["logical_clock"]
	except Exception as e:
		logging.error(f"Error fetching logical clock from peer {peer_id}: {str(e)}")
		return None


def send_missing_messages(
	remote_server, group, all_messages, peer_logical_clock, peer_id
):
	"""Send messages missing from the peer based on it logical clock"""
	out_missing_messages = [
		msg for msg in all_messages if msg["logical_clock"] > peer_logical_clock
	]

	if not out_missing_messages:
		return

	try:
		if out_missing_messages:
			response: UpdateMessagesResponse = UpdateMessagesResponse.from_json(
				remote_server.update_messages(group.group_id, out_missing_messages)
			)
			if response.ok:
				logging.info(
					f"Sent {len(out_missing_messages)} messages to peer {peer_id}"
				)
			else:
				logging.warning(f"Failed to update messages for peer {peer_id}.")
	except Exception as e:
		logging.error(f"Error sending missing messages to peer {peer_id}: {str(e)}")


def receive_missing_messages(remote_server, group, peer_id):
	"""Send messages missing from the peer based on it logical clock"""
	try:
		response: CallForSynchronizationResponse = (
			CallForSynchronizationResponse.from_json(
				remote_server.call_for_synchronization(
					group.group_id, group.logical_clock
				)
			)
		)
		if not response.ok:
			logging.warning(f"Could not synchronize messages with peer {peer_id}.")
			return

		in_missing_messages = response.missing_messages
		if in_missing_messages:
			store_missing_messages(
				group_id=group.group_id, missing_messages=in_missing_messages
			)
			logging.info(
				f"Received {len(in_missing_messages)} messages from peer {peer_id}."
			)
		else:
			logging.info(f"No new messages received from peer {peer_id}.")
	except Exception as e:
		logging.error(f"Error receiving missing messages from peer {peer_id}: {str(e)}")


@dispatcher.public
def report_logical_clock(group_id):
	group = get_active_group()
	if group_id == group.group_id:
		logical_clock = group.get("logical_clock", 0)
		return ReportLogicalClockResponse(
			ok=True,
			message="Logical clock reported succesfully.",
			data={"logical_clock": logical_clock},
		).to_json()


if __name__ == "__main__":
	serve()
